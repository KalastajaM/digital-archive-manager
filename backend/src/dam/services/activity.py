"""Activity: the operations journal grouped into batches, undo and crash recovery."""

import logging
from contextlib import nullcontext
from dataclasses import dataclass

from sqlalchemy import case, func, or_, select

from dam import special_folders
from dam.collections.ongoing import OngoingPublisher
from dam.collections.service import CollectionService
from dam.core.text import fold
from dam.db.tables import operations
from dam.errors import Conflict, InvalidRequest, NotFound
from dam.notes import NotesService
from dam.ops.executor import Executor
from dam.ops.model import BatchResult, ResolvedOp
from dam.ops.undo import ACTED, SYNC_ORIGIN, JournalEntry, RecoveryResult, entries
from dam.services.rule_record import RuleRecord
from dam.trays.service import TrayService

log = logging.getLogger(__name__)


# What a batch is, for the Activity filter. Each batch falls in exactly one (first match).
KINDS = ("undo", "trash", "marks", "convert", "collections", "folders", "rename", "filed", "other")
STATUSES = ("undone", "undoable", "done", "attention")  # attention: failed or interrupted
ORIGINS = ("ui", "cli", "auto")  # auto: the automatic Ongoing/Important sync ("workflow")
_ORIGIN_VALUE = {"ui": "ui", "cli": "cli", "auto": SYNC_ORIGIN}


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass
class BatchSummary:
    batch_id: str
    created: float
    origin: str
    ops: list[JournalEntry]
    undone: bool  # every op that acted has been reverted
    is_undo: bool  # this batch is itself an undo
    # undo would be accepted: something acted, nothing interrupted, not already undone,
    # not an undo, not an automatic Ongoing sync
    undoable: bool = False
    # What the user did, as the workflow stated it when it made the batch (None for
    # older batches and automatic syncs: the UI derives a title from the ops)
    label: str | None = None
    # an undo batch: the batch it reverted, and that batch's label
    undo_of: str | None = None
    undoes_label: str | None = None


@dataclass
class UndoOutcome:
    """The undo batch, plus the first error removing what the undone batch created
    (items, memberships, notes); the files were restored as ``batch`` says."""

    batch: BatchResult
    follow_up_error: str | None = None


class ActivityService:
    def __init__(
        self,
        executor: Executor,
        trays: TrayService,
        collections: CollectionService,
        notes: NotesService,
        rule_record: RuleRecord,
        ongoing: OngoingPublisher | None = None,
    ) -> None:
        self.executor = executor
        self.trays = trays
        self.collections = collections
        self.notes = notes
        self.rule_record = rule_record
        self.ongoing = ongoing

    def recent(self, limit: int = 50) -> list[BatchSummary]:
        """The ``limit`` most recent batches, newest first."""
        return self.search(limit=limit)

    def search(
        self,
        *,
        q: str | None = None,
        kinds: list[str] | None = None,
        origin: str | None = None,
        status: str | None = None,
        since: float | None = None,
        until: float | None = None,
        before: str | None = None,
        limit: int = 50,
    ) -> list[BatchSummary]:
        """Batches, newest first, narrowed in SQL (all filters together).

        ``q``: every word must occur (case and accents ignored) in the batch's title
        or in the source or destination path of one of its ops, so a file name finds
        each change that touched it. ``kinds`` (any of ``KINDS``), ``origin``
        (``ORIGINS``), ``status`` (``STATUSES``), ``since`` (inclusive) and ``until``
        (exclusive) as epoch seconds of the batch's start. ``before``: the batch id
        after which to continue (the last batch of the previous page).
        """
        for value, allowed, name in (
            (origin, ORIGINS, "origin"),
            (status, STATUSES, "status"),
        ):
            if value is not None and value not in allowed:
                raise InvalidRequest(f"unknown {name} {value!r}")
        for k in kinds or []:
            if k not in KINDS:
                raise InvalidRequest(f"unknown kind {k!r}")
        o = operations.c

        def flag(condition) -> object:
            return func.max(case((condition, 1), else_=0)) == 1

        def count(condition) -> object:
            return func.sum(case((condition, 1), else_=0))

        label = func.max(o.label)
        batch_origin = func.max(o.origin)
        is_undo = flag(o.undo_of.is_not(None))
        kind = case(
            (is_undo, "undo"),
            (
                or_(
                    flag(o.kind == "quarantine"),
                    label.like("% to To Delete"),
                    label.like("Restored % from To Delete%"),
                ),
                "trash",
            ),
            (
                or_(
                    label.like("Starred %"),
                    label.like("Removed the star from %"),
                    label.like("Marked % as important"),
                    label.like("Removed % from Important"),
                ),
                "marks",
            ),
            (label.like("Converted %"), "convert"),
            # New folder (and a layout's folders): only folders made, not by the Ongoing sync
            (
                (batch_origin != SYNC_ORIGIN)
                & (or_(label.like("Created the folder %"), count(o.kind != "mkdir") == 0)),
                "folders",
            ),
            (
                or_(
                    label.like("%collection%"),
                    label.like("Added % to %"),
                    label.like("Removed % from %"),
                    label.like("Created group%"),
                    batch_origin == SYNC_ORIGIN,
                ),
                "collections",
            ),
            (or_(label.like("Renamed %"), flag(o.kind == "rename")), "rename"),
            (or_(label.like("Filed %"), label.like("Moved %"), flag(o.kind == "move")), "filed"),
            else_="other",
        )
        live = count(o.state.in_(ACTED))
        acted_n = count(o.state.in_((*ACTED, "undone")))
        conditions = []
        if kinds:
            conditions.append(kind.in_(kinds))
        if origin:
            conditions.append(batch_origin == _ORIGIN_VALUE[origin])
        if status == "undone":
            conditions.append((acted_n > 0) & (live == 0))
        elif status == "undoable":
            conditions.append(
                (live > 0)
                & (count(o.state == "planned") == 0)
                & ~is_undo
                & (batch_origin != SYNC_ORIGIN)
            )
        elif status == "done":
            conditions.append(live > 0)
        elif status == "attention":
            conditions.append(count(o.state.in_(("planned", "failed"))) > 0)
        if since is not None:
            conditions.append(func.min(o.created) >= since)
        if until is not None:
            conditions.append(func.min(o.created) < until)
        newest = func.max(o.id)
        words = [fold(w) for w in (q or "").split()]
        with self.executor.engine.connect() as conn:
            if before is not None:
                last = conn.execute(
                    select(func.max(o.id)).where(o.batch_id == before)
                ).scalar_one_or_none()
                if last is None:
                    raise NotFound(f"batch {before}")
                conditions.append(newest < last)
            query = select(o.batch_id).group_by(o.batch_id)
            for word in words:
                text = func.dam_fold(
                    func.coalesce(o.label, "")
                    + " "
                    + func.coalesce(o.src, "")
                    + " "
                    + func.coalesce(o.dst, "")
                )
                query = query.where(
                    o.batch_id.in_(
                        select(o.batch_id).where(text.like(f"%{_like_escape(word)}%", escape="\\"))
                    )
                )
            if conditions:
                query = query.having(*conditions)
            batch_ids = list(conn.execute(query.order_by(newest.desc()).limit(limit)).scalars())
        if not batch_ids:
            return []
        grouped: dict[str, list[JournalEntry]] = {b: [] for b in batch_ids}
        for row in entries(self.executor, operations.c.batch_id.in_(batch_ids)):
            grouped[row.batch_id].append(row)
        return self._with_undone_labels([self._summary(b, rows) for b, rows in grouped.items()])

    def get(self, batch_id: str) -> BatchSummary:
        rows = entries(self.executor, operations.c.batch_id == batch_id)
        if not rows:
            raise NotFound(f"batch {batch_id}")
        return self._with_undone_labels([self._summary(batch_id, rows)])[0]

    def _with_undone_labels(self, batches: list[BatchSummary]) -> list[BatchSummary]:
        """Fill ``undoes_label`` of the undo batches from the batches they reverted."""
        wanted = {b.undo_of for b in batches if b.undo_of}
        if not wanted:
            return batches
        with self.executor.engine.connect() as conn:
            labels = dict(
                conn.execute(
                    select(operations.c.batch_id, func.max(operations.c.label))
                    .where(operations.c.batch_id.in_(wanted))
                    .group_by(operations.c.batch_id)
                ).all()
            )
        for b in batches:
            if b.undo_of:
                b.undoes_label = labels.get(b.undo_of)
        return batches

    def preview_undo(self, batch_id: str) -> list[ResolvedOp]:
        """What ``undo(batch_id)`` would do, as resolved ops, with the same refusals;
        changes nothing and journals nothing. Planned under the sync lock, as undo
        plans, so a sync cannot be half-way through Ongoing while it is read."""
        lock = self.ongoing.sync_lock if self.ongoing is not None else nullcontext()
        with lock:
            return self.executor.preview_undo(batch_id)

    def undo(self, batch_id: str) -> UndoOutcome:
        """Undo the batch's file operations; if that fully succeeded, also delete (DB
        only) the tray items, collection memberships and notes the batch created.

        If the undo stopped partway (``failed``/``error``/``index_error``), they are
        kept: some files are still filed, and the user should still see the item.
        Undoing again later (once the problem is fixed) removes them. A failure while
        removing them is logged and returned in ``follow_up_error`` (the others are
        still tried); the file undo already happened.
        """
        # The publisher's sync lock is held across the file undo and the cleanup that
        # goes with it (as Ongoing conversion's apply holds it), so no sync - e.g. one
        # the watcher triggers - plans against a half-undone Ongoing. Lock order:
        # sync_lock, then INDEX_LOCK (inside the executor), as in a sync. The re-sync
        # runs after the lock is released.
        if special_folders.is_rename(self.executor.engine, batch_id):
            # the folder alone would go back, leaving the settings and rules on the new name
            raise Conflict(
                "That is a rename of a folder: undo it from Activity in the app, "
                "which also puts the settings, rules and stored paths back."
            )
        lock = self.ongoing.sync_lock if self.ongoing is not None else nullcontext()
        removed = None
        forgotten = None
        with lock:
            result = self.executor.undo(batch_id)
            outcome = UndoOutcome(result)
            ok = result.failed is None and result.error is None and result.index_error is None
            if ok:
                if self.ongoing is not None:
                    # entries the batch put in a publish root (a conversion) that are
                    # gone again (their records are forgotten)
                    forgotten = self._remove(outcome, batch_id, self.ongoing.forget_undone)
                removed = self._remove(
                    outcome,
                    batch_id,
                    lambda b: self.collections.remove_created_by(b, notify=False),
                )
        # Re-sync when the DB changed, or when the publisher lost an entry the undo
        # took away while its member is still wanted (a converted file the user
        # marked again): the sync publishes it beside the restored shortcut.
        if (removed and removed.total) or forgotten:
            self.collections.changed()
        if ok:
            for cleanup in (
                self.trays.remove_created_by,
                self.notes.remove_created_by,
                self.rule_record.remove_created_by,
            ):
                self._remove(outcome, batch_id, cleanup)
        return outcome

    @staticmethod
    def _remove(outcome: UndoOutcome, batch_id: str, cleanup) -> object:
        """Run one follow-up removal; a failure is logged and kept in ``outcome``."""
        try:
            return cleanup(batch_id)
        except Exception as e:
            log.warning("removing what batch %s created failed", batch_id, exc_info=True)
            outcome.follow_up_error = outcome.follow_up_error or f"{type(e).__name__}: {e}"
            return None

    def pending(self) -> list[JournalEntry]:
        return self.executor.pending()

    def recover(self) -> RecoveryResult:
        return self.executor.recover()

    @staticmethod
    def _summary(batch_id: str, rows: list[JournalEntry]) -> BatchSummary:
        acted = [r for r in rows if r.state in (*ACTED, "undone")]
        undone = bool(acted) and all(r.state == "undone" for r in acted)
        is_undo = any(r.undo_of is not None for r in rows)
        undoable = (
            any(r.state in ACTED for r in rows)
            and not undone
            and not is_undo
            and not any(r.state == "planned" for r in rows)
            and not any(r.origin == SYNC_ORIGIN for r in rows)
        )
        return BatchSummary(
            batch_id=batch_id,
            created=rows[0].created,
            origin=rows[0].origin,
            ops=rows,
            undone=undone,
            is_undo=is_undo,
            undoable=undoable,
            label=next((r.label for r in rows if r.label), None),
            undo_of=next((r.undo_of for r in rows if r.undo_of), None),
        )
