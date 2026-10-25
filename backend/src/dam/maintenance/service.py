"""The maintenance service: starts the checks as jobs and turns the owner's choices on a
duplicate group into one previewed, journaled batch.

Replacing or removing duplicates only builds a ``Plan``: QUARANTINE moves the copy to
``##. To Delete`` (never a delete) and, to replace it with a link, a SYMLINK at its old
path to the copy kept. The executor runs it, so the guards, the journal and Undo are the
ones every change has. What the removed copies had (tags, collections, notes ...) is added
to the kept copy afterwards; it is only ever added, never overwritten."""

from __future__ import annotations

import dataclasses
import logging
import os
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from sqlalchemy import Engine, select

from dam.collections.service import CollectionService
from dam.core.paths import ArchivePaths
from dam.db.tables import collection_members, collections
from dam.index.repo import FileRecord, FileRepo, TagRepo
from dam.locks import LockService
from dam.maintenance import checks, duplicates
from dam.maintenance.duplicates import WHY_LOCKED, LockIndex
from dam.maintenance.jobs import Job, MaintenanceJobs
from dam.notes import NotesService
from dam.ops.executor import Executor
from dam.ops.guards import is_under, parent
from dam.ops.model import BatchResult, Op, OpKind, Plan
from dam.ops.primitives import can_make_links
from dam.services import check_disk_identity, check_origin
from dam.services.assignments import UNSET, AssignmentService
from dam.services.errors import InvalidRequest, NotFound
from dam.trays.service import TrayService

log = logging.getLogger(__name__)

KINDS = ("duplicates", "empty_folders", "broken_links", "references", "names", "waiting")
ACTIONS = ("quarantine", "link")
LINK_UNAVAILABLE = (
    "Windows needs Developer Mode to make links: turn it on in Windows settings, or move the "
    "copies to To Delete instead"
)
CHANGED = "has changed since the last scan: run the check again"


@dataclass
class CarryOver:
    """What the removed copies of one kept file had, to be added to it."""

    drive_id: str  # the kept copy
    name: str
    tags: list[str] = field(default_factory=list)
    collection_ids: list[int] = field(default_factory=list)
    collections: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # note texts to append
    checklist: list[str] = field(default_factory=list)
    item_ids: list[int] = field(default_factory=list)
    items: list[str] = field(default_factory=list)
    sender: str | None = None
    person: str | None = None

    @property
    def empty(self) -> bool:
        return not (
            self.tags
            or self.collection_ids
            or self.notes
            or self.checklist
            or self.item_ids
            or self.sender
            or self.person
        )


@dataclass
class ResolveResult(BatchResult):
    carry_over: list[CarryOver] = field(default_factory=list)
    carry_errors: list[str] = field(default_factory=list)


@dataclass
class _Pair:
    keep: FileRecord
    removed: list[FileRecord]


class MaintenanceService:
    def __init__(
        self,
        paths: ArchivePaths,
        repo: FileRepo,
        engine: Engine,
        executor: Executor,
        locks: LockService,
        collections_: CollectionService,
        tags: TagRepo,
        notes: NotesService,
        trays: TrayService,
        assignments: AssignmentService,
        tray_name: Callable[[str], str],
        rescan: Callable[[str], object] | None = None,
        important_lock: AbstractContextManager | None = None,
    ) -> None:
        self.paths = paths
        self.repo = repo
        self.engine = engine
        self.executor = executor
        self.locks = locks
        self.collections = collections_
        self.tags = tags
        self.notes = notes
        self.trays = trays
        self.assignments = assignments
        self.tray_name = tray_name
        self.rescan = rescan
        self.important_lock = important_lock if important_lock is not None else nullcontext()
        self.jobs = MaintenanceJobs()

    def close(self) -> None:
        self.jobs.close()

    # -- the checks as jobs -------------------------------------------------------------

    def estimate(self) -> duplicates.DuplicateEstimate:
        """What the duplicate check would read (index only; nothing is opened)."""
        return duplicates.estimate(self.repo, self.paths)

    def start(self, kind: str, days: int | None = None) -> Job:
        """Start the check ``kind`` as a job (an earlier one of that kind is ended)."""
        if kind not in KINDS:
            raise InvalidRequest(f"unknown check {kind!r}")
        if days is not None and not 0 <= days <= checks.MAX_DAYS:
            raise InvalidRequest(f"days must be between 0 and {checks.MAX_DAYS}")
        paths, repo, engine = self.paths, self.repo, self.engine
        work: Callable
        match kind:
            case "duplicates":
                work = lambda ctx: duplicates.find(ctx, repo, paths, self.locks)  # noqa: E731
            case "empty_folders":
                work = lambda ctx: checks.empty_folders(ctx, repo, paths, engine)  # noqa: E731
            case "broken_links":
                work = lambda ctx: checks.broken_links(ctx, repo, paths, engine)  # noqa: E731
            case "references":
                work = lambda ctx: checks.bad_references(ctx, paths, engine, self.tray_name)  # noqa: E731
            case "names":
                work = lambda ctx: checks.bad_names(ctx, repo, paths, engine)  # noqa: E731
            case _:
                limit = checks.DEFAULT_DAYS if days is None else days
                work = lambda ctx: checks.waiting_in_to_delete(  # noqa: E731
                    ctx, repo, paths, engine, limit
                )
        return self.jobs.start(kind, work)

    def result_of(self, job: Job) -> tuple[str, object]:
        """``(kind, result)`` of a job as it stands now: without what has changed since it
        was found (a duplicate that moved, a folder that is no longer empty or was marked
        for deletion). Reads the index only."""
        result = job.view().result
        if result is None:
            return job.kind, None
        if job.kind == "duplicates":
            result = duplicates.refresh(result, self.repo, self.paths, self.locks)
        elif job.kind in ("empty_folders", "broken_links", "names"):
            result = self._still_there(result)
        elif job.kind == "waiting":
            result = self._still_there(result, waiting=True)
        return job.kind, result

    def _still_there(self, result, waiting: bool = False):
        """A copy of a list result without the entries whose file is gone from where it
        was listed (moved, renamed, marked for deletion), with the totals lowered."""
        kept = []
        for item in result.items:
            rec = self.repo.get(item.drive_id)
            if rec and not rec.missing and rec.parked_at is None and rec.path == item.path:
                kept.append(item)
        gone = [i for i in result.items if i not in kept]
        if not gone:
            return result
        out = dataclasses.replace(result, items=kept, total=max(0, result.total - len(gone)))
        if waiting:
            size = sum(i.size for i in gone)
            out.total_size = max(0, result.total_size - size)
            out.in_to_delete = max(0, result.in_to_delete - len(gone))
            out.in_to_delete_size = max(0, result.in_to_delete_size - size)
        return out

    # -- replacing or removing duplicates ---------------------------------------------------

    def _file(self, drive_id: str) -> FileRecord:
        rec = self.repo.get(drive_id)
        if rec is None or rec.missing or rec.parked_at is not None:
            raise NotFound(drive_id)
        if rec.is_dir or rec.is_link:
            raise InvalidRequest(f"{rec.path} is not a regular file")
        if any(is_under(rec.path, area) for area in duplicates.own_folders(self.paths)):
            raise InvalidRequest(f"{rec.path} is in one of the app's own folders")
        if not duplicates.disk_matches(self.paths, rec):
            raise InvalidRequest(f"{rec.path} {CHANGED}")
        return rec

    def _pairs(self, groups: Sequence[tuple[str, Sequence[str]]]) -> list[_Pair]:
        if not groups:
            raise InvalidRequest("No duplicates given")
        keeps = [k for k, _ in groups]
        removes = [r for _, rs in groups for r in rs]
        every = [*keeps, *removes]
        if len(set(every)) != len(every):
            raise InvalidRequest("A file is named more than once (or is both kept and removed)")
        locks = LockIndex(self.locks)
        pairs = []
        for keep_id, remove_ids in groups:
            if not remove_ids:
                raise InvalidRequest("A group needs at least one copy to remove")
            keep = self._file(keep_id)
            removed = []
            for rid in remove_ids:
                rec = self._file(rid)
                why = locks.reason(rec.drive_id, rec.path_nfc)
                if why is not None:
                    raise InvalidRequest(
                        f"{rec.path} is {WHY_LOCKED[why]}, so it is not removed: "
                        "keep it, or choose another copy to remove"
                    )
                if not (rec.sha256 and rec.sha256 == keep.sha256 and rec.size == keep.size):
                    raise InvalidRequest(
                        f"{rec.path} is not known to be the same as {keep.path}: "
                        "run the duplicate check again"
                    )
                removed.append(rec)
            pairs.append(_Pair(keep, removed))
        return pairs

    def resolve(
        self,
        groups: Sequence[tuple[str, Sequence[str]]],
        action: str,
        carry_over: bool = True,
        origin: str = "ui",
        dry_run: bool = False,
    ) -> ResolveResult:
        """For each group ``(keep, [copies to remove])``: move the copies to ``##. To
        Delete`` (``action`` ``quarantine``) or, ``link``, also make a link to the kept
        copy where each one was. One batch, one Undo. ``carry_over``: add what the removed
        copies had to the kept one (listed in the result; applied unless ``dry_run``).

        Refused (``InvalidRequest``, nothing happens): a copy that is Important or locked,
        a file not known to have the same content (the check must have hashed both), a file
        that changed since it was scanned, a file in the app's own folders, and a link on
        Windows without Developer Mode."""
        check_origin(origin)
        if action not in ACTIONS:
            raise InvalidRequest(f"action must be one of {', '.join(ACTIONS)}")
        if action == "link" and not can_make_links():
            raise InvalidRequest(LINK_UNAVAILABLE)
        pairs = self._pairs(groups)
        ops: list[Op] = []
        ids: list[str] = []
        for pair in pairs:
            for rec in pair.removed:
                ops.append(Op(OpKind.QUARANTINE, rec.path, None))
                ids.append(rec.drive_id)
                if action == "link":
                    ops.append(Op(OpKind.SYMLINK, pair.keep.path, rec.path, exact=True))
        count = len(ids)
        what = "1 duplicate" if count == 1 else f"{count} duplicates"
        label = (
            f"Replaced {what} with a link to the kept copy"
            if action == "link"
            else f"Moved {what} to To Delete"
        )
        plan = Plan(ops, origin=origin, label=label)
        with self.important_lock:
            batch = self.executor.apply(
                plan,
                dry_run=dry_run,
                check=lambda resolved: check_disk_identity(
                    self.paths, self.repo, ids, resolved, (OpKind.QUARANTINE,)
                ),
            )
        result = ResolveResult(**vars(batch))
        if dry_run:
            if carry_over:
                result.carry_over = self._carry_plans(pairs)
            return result
        if action == "link" and self.rescan is not None and batch.done:
            for folder in dict.fromkeys(parent(r.path) for p in pairs for r in p.removed):
                try:
                    self.rescan(folder)
                except Exception:  # the batch is done; the watcher's next scan picks it up
                    log.warning("indexing the new links failed", exc_info=True)
        if carry_over:
            gone = {op.src for op in batch.done if op.kind is OpKind.QUARANTINE}
            done_pairs = [
                _Pair(p.keep, [r for r in p.removed if r.path in gone])
                for p in pairs
                if any(r.path in gone for r in p.removed)
            ]
            result.carry_over = self._carry_plans(done_pairs)
            result.carry_errors = self._carry_apply(result.carry_over, batch.batch_id)
        return result

    # -- what the removed copies had ----------------------------------------------------------

    def _carry_plans(self, pairs: list[_Pair]) -> list[CarryOver]:
        plans = [self._carry_plan(p.keep, p.removed) for p in pairs]
        return [c for c in plans if not c.empty]

    def _carry_plan(self, keep: FileRecord, removed: list[FileRecord]) -> CarryOver:
        out = CarryOver(keep.drive_id, keep.name or keep.path)
        ids = [r.drive_id for r in removed]
        have_tags = set(self.tags.for_file(keep.drive_id))
        for rid in ids:
            for tag in self.tags.for_file(rid):
                if tag not in have_tags:
                    have_tags.add(tag)
                    out.tags.append(tag)
        with self.engine.connect() as conn:
            member_of = set(
                conn.execute(
                    select(collection_members.c.collection_id).where(
                        collection_members.c.drive_id == keep.drive_id
                    )
                ).scalars()
            )
            rows = conn.execute(
                select(collections.c.id, collections.c.name, collections.c.kind)
                .select_from(
                    collection_members.join(
                        collections, collections.c.id == collection_members.c.collection_id
                    )
                )
                .where(
                    collection_members.c.drive_id.in_(ids),
                    collections.c.state == "open",
                    collections.c.kind.is_distinct_from("important"),
                )
                .order_by(collections.c.kind.is_(None), collections.c.name)
            ).all()
        for row in rows:
            if row.id not in member_of and row.id not in out.collection_ids:
                out.collection_ids.append(row.id)
                out.collections.append("Starred" if row.kind == "starred" else row.name)
        keep_note = self.notes.get("file", keep.drive_id)
        for rec in removed:
            text = self.notes.get("file", rec.drive_id).strip()
            if text and text not in keep_note and text not in out.notes:
                out.notes.append(text)
        have_checks = {c.text.casefold() for c in self.notes.checklist("file", keep.drive_id)}
        for rec in removed:
            for c in self.notes.checklist("file", rec.drive_id):
                if c.text.casefold() not in have_checks:
                    have_checks.add(c.text.casefold())
                    out.checklist.append(c.text)
        for rec in removed:
            for item in self.trays.for_file(rec.drive_id):
                if keep.drive_id not in item.files and item.id not in out.item_ids:
                    out.item_ids.append(item.id)
                    out.items.append(f"{self.tray_name(item.tray_id)}: {item.title}")
        mine = self.assignments.get([keep.drive_id]).get(keep.drive_id)
        theirs = [a for rid, a in self.assignments.get(ids).items() if rid in ids]
        if mine is None or mine.sender is None:
            out.sender = next((a.sender for a in theirs if a.sender), None)
        if mine is None or mine.person is None:
            out.person = next((a.person for a in theirs if a.person), None)
        return out

    def _carry_apply(self, plans: list[CarryOver], batch_id: str) -> list[str]:
        """Add what the plans list to the kept copies. Each part is tried on its own; the
        ones that failed come back as sentences (the batch itself is done and stays)."""
        errors: list[str] = []
        changed = False
        for c in plans:

            def attempt(what: str, step: Callable[[], object], c: CarryOver = c) -> None:
                try:
                    step()
                except Exception as e:
                    log.warning("carrying %s over to %s failed", what, c.name, exc_info=True)
                    errors.append(f"{c.name}: {what} could not be added ({e})")

            if c.tags:
                attempt("the tags", lambda c=c: self.tags.add(c.drive_id, c.tags))
            for cid in c.collection_ids:
                changed = True
                attempt(
                    "a collection",
                    lambda cid=cid, c=c: self.collections.add_members(
                        cid, [c.drive_id], batch_id, notify=False
                    ),
                )
            for text in c.notes:
                if self.notes.get("file", c.drive_id).strip():
                    attempt(
                        "the note", lambda t=text, c=c: self.notes.append("file", c.drive_id, t)
                    )
                else:
                    attempt(
                        "the note",
                        lambda t=text, c=c: self.notes.add_if_absent(
                            "file", c.drive_id, t, batch_id
                        ),
                    )
            for text in c.checklist:
                attempt(
                    "a checklist entry",
                    lambda t=text, c=c: self.notes.add_check("file", c.drive_id, t),
                )
            for item_id in c.item_ids:
                attempt("a tray item", lambda i=item_id, c=c: self.trays.add_file(i, c.drive_id))
            if c.sender or c.person:
                attempt(
                    "From or For",
                    lambda c=c: self.assignments.set(
                        [c.drive_id],
                        sender=c.sender if c.sender else UNSET,
                        person=c.person if c.person else UNSET,
                    ),
                )
        if changed:
            try:
                self.collections.changed()
            except Exception:
                log.warning("syncing the collections failed", exc_info=True)
        return errors

    # -- broken links in the app's own folders -------------------------------------------------

    def remove_links(
        self, drive_ids: Sequence[str], origin: str = "ui", dry_run: bool = False
    ) -> BatchResult:
        """Remove links in ``##. Ongoing`` / ``##. Important`` whose target is gone (the
        one removal the operation layer allows there; Undo makes the link again).
        Anywhere else a link is moved to To Delete instead, like any file."""
        check_origin(origin)
        if not drive_ids or len(set(drive_ids)) != len(drive_ids):
            raise InvalidRequest("Give each link once")
        ops = []
        for drive_id in drive_ids:
            rec = self.repo.get(drive_id)
            if rec is None or rec.missing or rec.parked_at is not None:
                raise NotFound(drive_id)
            if not rec.is_link:
                raise InvalidRequest(f"{rec.path} is not a link")
            if self.paths.in_publish_root(rec.path) is None:
                raise InvalidRequest(
                    f"{rec.path} is not in {self.paths.ongoing} or {self.paths.important}: "
                    "move it to To Delete instead"
                )
            if os.path.exists(self.paths.abs(rec.path)):
                raise InvalidRequest(f"{rec.path} leads somewhere: it is not a broken link")
            ops.append(Op(OpKind.UNLINK_SYMLINK, rec.path, None))
        n = len(ops)
        name = PurePosixPath(ops[0].src).name if n == 1 else f"{n} broken links"
        plan = Plan(ops, origin=origin, label=f"Removed {name}")
        result = self.executor.apply(plan, dry_run=dry_run)
        if not dry_run and result.done and self.rescan is not None:
            for folder in dict.fromkeys(parent(op.src) for op in ops):
                try:
                    self.rescan(folder)
                except Exception:
                    log.warning("indexing after removing links failed", exc_info=True)
        return result
