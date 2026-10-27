"""The maintenance service: starts the checks as jobs and turns the owner's choices on a
duplicate group into one previewed, journaled batch.

Replacing or removing duplicates only builds a ``Plan``: QUARANTINE moves the copy to
``##. To Delete`` (never a delete) and, to replace it with a link, a SYMLINK at its old
path to the copy kept. The executor runs it, so the guards, the journal and Undo are the
ones every change has. What the removed copies had (tags, collections, notes ...) is added
to the kept copy afterwards; it is only ever added, never overwritten.

Reconnecting a file moved or renamed outside dam changes the database only (the file is
already where it is): what its old, missing index row had moves to its new row in one
transaction. It is not an operation on the archive, so it is not in Activity and has no
Undo; the preview says so."""

from __future__ import annotations

import dataclasses
import logging
import os
from collections.abc import Callable, Collection, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from sqlalchemy import Engine, select

from dam.collections.service import CollectionService
from dam.core.paths import ArchivePaths, not_connected_message
from dam.db.tables import collection_members, collections
from dam.index.repo import FileRecord, FileRepo, TagRepo
from dam.locks import LockService
from dam.maintenance import checks, duplicates
from dam.maintenance.duplicates import WHY_LOCKED, LockIndex
from dam.maintenance.ignored import IgnoreList, fold_name
from dam.maintenance.jobs import Job, MaintenanceJobs
from dam.notes import NotesService
from dam.ops.executor import Executor
from dam.ops.guards import is_under, parent
from dam.ops.model import BatchResult, Op, OpKind, Plan
from dam.ops.primitives import can_make_links
from dam.services import LOCAL_ID_PREFIX, check_disk_identity, check_origin
from dam.services.assignments import UNSET, AssignmentService
from dam.services.errors import InvalidRequest, NotFound
from dam.trays.service import TrayService

log = logging.getLogger(__name__)

KINDS = (
    "duplicates",
    "empty_folders",
    "broken_links",
    "references",
    "names",
    "waiting",
    "label_clashes",
    "unfinished_copies",
    "moved",
)
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
class ReconnectResult:
    dry_run: bool
    pairs: list[checks.MovedPair] = field(default_factory=list)  # reconnected (or would be)
    errors: list[str] = field(default_factory=list)


def moved_key(pair: checks.MovedPair) -> str:
    """What a "Moved outside dam" pair is ignored as (``dam.maintenance.ignored``)."""
    return f"{pair.old_id}>{pair.new_id}"


@dataclass
class _Pair:
    keep: FileRecord
    removed: list[FileRecord]


def _dups(n: int) -> str:
    return "1 duplicate" if n == 1 else f"{n} duplicates"


# A duplicate group to resolve: (keep, copies to remove), with "name" third when the
# files are versions that share a name rather than identical copies.
Group = tuple[str, Sequence[str]] | tuple[str, Sequence[str], str]


def _name_of(rec: FileRecord) -> str:
    return fold_name(rec.name or PurePosixPath(rec.path).name)


def _resolve_label(moved: int, linked: int) -> str:
    """The batch's title in Activity."""
    if not linked:
        return f"Moved {_dups(moved)} to To Delete"
    if not moved:
        return f"Replaced {_dups(linked)} with a link to the kept copy"
    return f"Moved {_dups(moved)} to To Delete and replaced {linked} with a link"


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
        self.ignored = IgnoreList(engine)

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
            case "label_clashes":
                work = lambda ctx: checks.label_clashes(ctx, repo, paths, engine)  # noqa: E731
            case "unfinished_copies":
                work = lambda ctx: checks.unfinished_copies(ctx, repo, paths, engine)  # noqa: E731
            case "moved":
                work = lambda ctx: checks.moved(ctx, repo, paths, engine)  # noqa: E731
            case _:
                limit = checks.DEFAULT_DAYS if days is None else days
                work = lambda ctx: checks.waiting_in_to_delete(  # noqa: E731
                    ctx, repo, paths, engine, limit
                )
        return self.jobs.start(kind, work)

    def result_of(self, job: Job) -> tuple[str, object]:
        """``(kind, result)`` of a job as it stands now: without what has changed since it
        was found (a duplicate that moved, a folder that is no longer empty or was marked
        for deletion) and without what the owner ignores. Reads the index only."""
        result = job.view().result
        if result is None:
            return job.kind, None
        if job.kind == "duplicates":
            result = duplicates.refresh(result, self.repo, self.paths, self.locks)
        elif job.kind in ("empty_folders", "broken_links", "names"):
            result = self._still_there(result)
        elif job.kind == "unfinished_copies":
            result = self._still_there(result, sized=True)
        elif job.kind == "waiting":
            result = self._still_there(result, waiting=True)
        elif job.kind == "moved":
            result = self._still_moved(result)
        return job.kind, self._not_ignored(job.kind, result)

    def _not_ignored(self, kind: str, result):
        """A copy of ``result`` without the entries the owner ignores, totals lowered."""
        drop = self.ignored.drop
        ids = lambda g: [f.drive_id for f in g.files]  # noqa: E731
        if kind == "duplicates":
            groups, n = drop("duplicates", result.groups, lambda g: g.sha256, ids)
            names, m = drop("versions", result.name_groups, lambda g: fold_name(g.name), ids)
            if not (n or m):
                return result
            return dataclasses.replace(
                result,
                groups=groups,
                groups_total=max(0, result.groups_total - n),
                name_groups=names,
                name_groups_total=max(0, result.name_groups_total - m),
            )
        if kind == "references":
            key = lambda r: "-".join(  # noqa: E731
                (r.kind, r.owner_id, "" if r.item_id is None else str(r.item_id), r.drive_id)
            )
        elif kind in ("empty_folders", "broken_links", "names"):
            key = lambda r: r.drive_id  # noqa: E731
        elif kind == "moved":
            key = moved_key
        else:
            return result
        items, n = drop(kind, result.items, key)
        if not n:
            return result
        return dataclasses.replace(result, items=items, total=max(0, result.total - n))

    def _still_there(self, result, waiting: bool = False, sized: bool = False):
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
        if sized:
            out.total_size = max(0, result.total_size - sum(i.size for i in gone))
        if waiting:
            size = sum(i.size for i in gone)
            out.total_size = max(0, result.total_size - size)
            out.in_to_delete = max(0, result.in_to_delete - len(gone))
            out.in_to_delete_size = max(0, result.in_to_delete_size - size)
        return out

    def _still_moved(self, result: checks.Moved) -> checks.Moved:
        """A copy of a "Moved outside dam" result without the pairs that no longer hold:
        the old row is back, reconnected or gone, the new file moved on or was given
        something of its own."""
        given = self.repo.given([i for p in result.items for i in (p.old_id, p.new_id)])
        kept = []
        for pair in result.items:
            old, new = self.repo.get(pair.old_id), self.repo.get(pair.new_id)
            if (
                old is not None
                and old.missing
                and old.parked_at is None
                and new is not None
                and not new.missing
                and new.parked_at is None
                and new.path == pair.new_path
                and pair.new_id not in given
            ):
                kept.append(pair)
        gone = len(result.items) - len(kept)
        if not gone:
            return result
        return dataclasses.replace(result, items=kept, total=max(0, result.total - gone))

    # -- reconnecting files moved outside dam ---------------------------------------------------

    def _moved_pair(self, old_id: str, new_id: str) -> checks.MovedPair:
        old, new = self.repo.get(old_id), self.repo.get(new_id)
        if old is None:
            raise NotFound(old_id)
        if new is None:
            raise NotFound(new_id)
        if not (old_id.startswith(LOCAL_ID_PREFIX) and new_id.startswith(LOCAL_ID_PREFIX)):
            raise InvalidRequest("Only files without a Drive id are reconnected")
        if not old.missing or old.parked_at is not None:
            raise InvalidRequest(f"{old.path} is not missing")
        if new.missing or new.parked_at is not None:
            raise InvalidRequest(f"{new.path} is not in the archive")
        if new.is_dir or new.is_link:
            raise InvalidRequest(f"{new.path} is not a regular file")
        if any(is_under(new.path, area) for area in duplicates.own_folders(self.paths)):
            raise InvalidRequest(f"{new.path} is in one of the app's own folders")
        if not duplicates.disk_matches(self.paths, new):
            raise InvalidRequest(f"{new.path} {CHANGED}")
        given = self.repo.given([old_id, new_id])
        if new_id in given:
            raise InvalidRequest(f"{new.path} has tags, notes or other things of its own")
        if old_id not in given:
            raise InvalidRequest(f"{old.path} has nothing to reconnect")
        if not (old.sha256 and old.sha256 == new.sha256 and old.size == new.size):
            raise InvalidRequest(
                f"{new.path} is not known to be the same file as {old.path}: run the check again"
            )
        like = checks.moved_pairs_like(
            self.repo, self.paths, self.engine, old.size or 0, old.sha256
        )
        pair = next((p for p in like if (p.old_id, p.new_id) == (old_id, new_id)), None)
        if pair is None:
            raise InvalidRequest(f"{new.path} {CHANGED}")
        if pair.ambiguous:
            raise InvalidRequest(
                f"{old.path} has the content of more than one file (or shares it with "
                "another missing file), so it is not reconnected"
            )
        return pair

    def reconnect(self, pairs: Sequence[tuple[str, str]], dry_run: bool = False) -> ReconnectResult:
        """For each ``(old_id, new_id)`` the "Moved outside dam" check paired: move
        everything given to the file from its old, missing row to its new one and drop
        the old row (``FileRepo.reconnect``; one transaction per pair). Database only:
        nothing in the archive changes, nothing is journaled and there is no Undo.
        ``dry_run`` checks and lists the pairs with what would move.

        Refused (``InvalidRequest``, nothing happens): a file named twice, a pair whose
        old row is not missing or has nothing given, whose new row is not a present
        file, has something of its own or changed since it was scanned, files not known
        to have the same content, and an ambiguous pair."""
        if not pairs:
            raise InvalidRequest("No files given")
        every = [i for pair in pairs for i in pair]
        if len(set(every)) != len(every):
            raise InvalidRequest("A file is named more than once")
        found = [self._moved_pair(old_id, new_id) for old_id, new_id in pairs]
        if dry_run:
            return ReconnectResult(True, found)
        result = ReconnectResult(False)
        for pair in found:
            try:
                pair.moves = self.repo.reconnect(pair.old_id, pair.new_id)
            except ValueError as e:  # changed since it was checked a moment ago
                result.errors.append(f"{pair.new_path}: not reconnected ({e})")
                continue
            log.info("reconnected %s to %s (%s)", pair.old_path, pair.new_path, pair.moves)
            result.pairs.append(pair)
        if any(p.moves.get("collections") for p in result.pairs):
            try:
                self.collections.changed()  # a published link follows the file
            except Exception:
                log.warning("syncing the collections failed", exc_info=True)
        return result

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

    def _pairs(self, groups: Sequence[Group]) -> list[_Pair]:
        if not groups:
            raise InvalidRequest("No duplicates given")
        keeps = [g[0] for g in groups]
        removes = [r for g in groups for r in g[1]]
        every = [*keeps, *removes]
        if len(set(every)) != len(every):
            raise InvalidRequest("A file is named more than once (or is both kept and removed)")
        locks = LockIndex(self.locks)
        pairs = []
        for keep_id, remove_ids, *rest in groups:
            by_name = rest == ["name"]
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
                if by_name:
                    if _name_of(rec) != _name_of(keep):
                        raise InvalidRequest(f"{rec.path} does not have the name of {keep.path}")
                elif not (rec.sha256 and rec.sha256 == keep.sha256 and rec.size == keep.size):
                    raise InvalidRequest(
                        f"{rec.path} is not known to be the same as {keep.path}: "
                        "run the duplicate check again"
                    )
                removed.append(rec)
            pairs.append(_Pair(keep, removed))
        return pairs

    def resolve(
        self,
        groups: Sequence[Group],
        action: str,
        carry_over: bool = True,
        origin: str = "ui",
        dry_run: bool = False,
        links: Collection[str] = (),
    ) -> ResolveResult:
        """For each group ``(keep, [copies to remove])``, or ``(keep, [...], "name")`` for
        versions of one document (the same name, other content): move the copies to ``##. To
        Delete`` (``action`` ``quarantine``) or, ``link``, also make a link to the kept
        copy where each one was. One batch, one Undo. ``carry_over``: add what the removed
        copies had to the kept one (listed in the result; applied unless ``dry_run``).
        ``links``: copies (among those to remove) replaced with a link whatever ``action``
        is, so one batch can move some copies and link others.

        Refused (``InvalidRequest``, nothing happens): a copy that is Important or locked,
        a file not known to have the same content (the check must have hashed both; for
        versions, one with another name), a file
        that changed since it was scanned, a file in the app's own folders, and a link on
        Windows without Developer Mode."""
        check_origin(origin)
        if action not in ACTIONS:
            raise InvalidRequest(f"action must be one of {', '.join(ACTIONS)}")
        pairs = self._pairs(groups)
        linked = {r.drive_id for p in pairs for r in p.removed} if action == "link" else set(links)
        if not linked <= {r.drive_id for p in pairs for r in p.removed}:
            raise InvalidRequest("A copy to replace with a link is not one of the copies to remove")
        if linked and not can_make_links():
            raise InvalidRequest(LINK_UNAVAILABLE)
        ops: list[Op] = []
        ids: list[str] = []
        for pair in pairs:
            for rec in pair.removed:
                ops.append(Op(OpKind.QUARANTINE, rec.path, None))
                ids.append(rec.drive_id)
                if rec.drive_id in linked:
                    ops.append(Op(OpKind.SYMLINK, pair.keep.path, rec.path, exact=True))
        label = _resolve_label(len(ids) - len(linked), len(linked))
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
        if linked and self.rescan is not None and batch.done:
            folders = (parent(r.path) for p in pairs for r in p.removed if r.drive_id in linked)
            for folder in dict.fromkeys(folders):
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
        connected: dict[str, bool] = {}
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
            offline = checks.link_into_offline(self.paths, rec.path, connected)
            if offline is not None:  # not broken: its folder is unplugged
                raise InvalidRequest(not_connected_message(self.paths.folder_of(offline)))
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
