"""Browse the indexed archive and quarantine entries."""

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from dam.config import SpecialFolders
from dam.core.paths import nfc
from dam.index.repo import FLAT_SORTS, FileRecord, FileRepo
from dam.ops.executor import Executor
from dam.ops.guards import canonical, fold_parts, is_ds_store_name, is_under, parent
from dam.ops.jobs import CopyJobs
from dam.ops.model import BatchResult, GuardError, Op, OpKind, Plan, ResolvedOp
from dam.ops.primitives import can_make_links
from dam.services import check_destination_area, check_disk_identity, check_origin
from dam.services.errors import InvalidRequest, NotFound
from dam.services.links import link_target

log = logging.getLogger(__name__)


def _sort_key(s: str) -> str:
    return nfc(s).casefold()


@dataclass
class DirEntry:
    name: str
    path: str
    is_dir: bool
    is_link: bool
    size: int | None
    mtime: float | None
    drive_id: str


@dataclass
class MoveResult(BatchResult):
    """A move batch, plus the drive ids that needed no op (already in that folder)."""

    unchanged: list[str] = field(default_factory=list)
    folder: str = ""  # the destination, as a canonical archive-relative path


class _Background(Exception):  # noqa: N818 - a hand-over, not an error
    """The plan copies files across disks: it runs as a background job instead."""

    def __init__(self, ops: list[ResolvedOp]) -> None:
        super().__init__("copies across disks")
        self.ops = ops


@dataclass
class _Move:
    plan: Plan
    ids: list[str]  # the requested drive id of each op, in plan order
    unchanged: list[str]  # ids already in the folder (no op)
    folder: str  # canonical destination rel


# ``(path_nfc, is_dir, drive_id)`` of a collection's live direct members
MemberPaths = Callable[[int], list[tuple[str, bool, str]]]
# ``(drive_id, path_nfc, is_dir)`` of the entries marked ! Important
# (MarkService.important_paths)
ImportantPaths = Callable[[], list[tuple[str, str, bool]]]

IMPORTANT_REFUSAL = "This file is marked Important; unmark it first"
IMPORTANT_FOLDER_REFUSAL = "This file is in a folder marked Important; unmark it first"
LINK_UNAVAILABLE = (
    "Windows needs Developer Mode to make links: turn it on in Windows settings, or use Copy"
)
DROP_MODES = ("move", "link", "copy")

FLAT_LIMIT = 500


def _entry(r: FileRecord) -> DirEntry:
    return DirEntry(r.name, r.path, r.is_dir, r.is_link, r.size, r.mtime, r.drive_id)


def _under(path_nfc: str, folder_nfc: str) -> bool:
    """``path_nfc`` is ``folder_nfc`` or below it (``""``: the root holds everything)."""
    return not folder_nfc or path_nfc == folder_nfc or path_nfc.startswith(folder_nfc + "/")


class BrowseService:
    def __init__(
        self,
        repo: FileRepo,
        executor: Executor,
        special: SpecialFolders,
        member_paths: MemberPaths | None = None,
        important: ImportantPaths | None = None,
        important_lock: AbstractContextManager | None = None,
        rescan: Callable[[str], object] | None = None,
    ) -> None:
        self.repo = repo
        # indexes a folder right after a link or copy was made in it (else the watcher does)
        self.rescan = rescan
        self.executor = executor
        self.special = special
        # a collection's members, for the collection filter (CollectionService.member_paths)
        self.member_paths = member_paths
        # the files marked Important, which quarantine refuses, and the lock that
        # keeps new Important members out while a quarantine runs
        # (CollectionService.important_lock)
        self.important = important
        self.important_lock = important_lock if important_lock is not None else nullcontext()
        # runs moves across disks in the background (``dam.ops.jobs``); set by the App.
        # Without it such a move runs in the request.
        self.copy_jobs: CopyJobs | None = None

    def resolve(self, arg: str) -> FileRecord:
        """The live record for ``arg``: a drive id, else an absolute or archive-relative path.

        Relative paths are relative to the archive root, never the working directory.
        Raises ``NotFound`` if nothing live (not missing, not parked) matches, and
        ``OutsideArchiveError`` for a path outside the archive.
        """
        rec = self.repo.get(arg)
        if rec is None:
            paths = self.executor.paths
            path = Path(arg)
            rec = self.repo.by_path(paths.rel(path if path.is_absolute() else paths.abs(arg)))
        if rec is None or rec.missing or rec.parked_at is not None:
            raise NotFound(arg)
        return rec

    def list_dir(self, rel: str = "", collection_id: int | None = None) -> list[DirEntry]:
        """Direct children of ``rel`` (a trailing "/" is ignored) from the index:
        folders first, then by name.

        With ``collection_id``, only the children on the way to one of its members
        (a folder holding a member at any depth, a member folder, a member file); inside
        a member folder everything is shown. Raises ``NotFound`` for an unknown
        collection."""
        rel = rel.rstrip("/")
        children = [r for r in self.repo.list_dir(rel) if r.parked_at is None]
        if collection_id is not None:
            keep = self._on_the_way(nfc(rel), self._members(collection_id))
            if keep is not None:
                children = [r for r in children if r.path_nfc in keep]
        entries = [_entry(r) for r in children]
        entries.sort(key=lambda e: (not e.is_dir, _sort_key(e.name)))
        return entries

    def _members(self, collection_id: int) -> list[tuple[str, bool, str]]:
        if self.member_paths is None:
            raise InvalidRequest("Collections are not available here")
        return self.member_paths(collection_id)  # its own and its descendants' members

    @staticmethod
    def _on_the_way(rel: str, members: list[tuple[str, bool, str]]) -> set[str] | None:
        """The paths of ``rel``'s children to keep for these members; None (keep all)
        when ``rel`` is a member folder or lies inside one."""
        prefix = rel + "/" if rel else ""
        keep: set[str] = set()
        for path, is_dir, _ in members:
            if is_dir and rel and _under(rel, path):
                return None
            if path.startswith(prefix) and path != rel:
                keep.add(prefix + path[len(prefix) :].split("/", 1)[0])
        return keep

    def _flat_args(self, rel: str, collection_id: int | None) -> tuple[str, dict]:
        """``rel`` without a trailing "/", and the ``within``/``exclude`` keywords of
        ``FileRepo.files_below`` for it (see ``files_below``)."""
        rel = rel.rstrip("/")
        rel_n = nfc(rel)
        exclude = [
            a
            for a in map(nfc, (self.special.ongoing, *self.executor.paths.quarantines))
            if not _under(rel_n, a)
        ]
        within = None
        if collection_id is not None:
            members = self._members(collection_id)
            within = (
                [p for p, is_dir, _ in members if is_dir],
                [d for _, is_dir, d in members if not is_dir],
            )
        return rel, {"within": within, "exclude": exclude}

    def files_below(
        self,
        rel: str = "",
        collection_id: int | None = None,
        sort: str = "name",
        desc: bool = False,
        limit: int = FLAT_LIMIT,
    ) -> tuple[list[DirEntry], int]:
        """The Files view: up to ``limit`` files at any depth below ``rel``, sorted by
        ``sort`` (name, date, size, folder), plus the total.

        Ongoing (app links that mirror collections) and the quarantine are left out
        unless ``rel`` is inside them. With ``collection_id``: only the member files
        of it and of the collections below it, and the files below their member
        folders. Two indexed path-range queries; the disk is never read."""
        if sort not in FLAT_SORTS:
            raise InvalidRequest(f"Cannot sort by {sort!r}")
        rel, kw = self._flat_args(rel, collection_id)
        rows, total = self.repo.files_below(rel, sort=sort, desc=desc, limit=limit, **kw)
        return [_entry(r) for r in rows], total

    def files_below_sql(
        self, rel: str = "", collection_id: int | None = None, sort: str = "name"
    ) -> list[str]:
        """The SQL ``files_below`` runs for these arguments (query-plan tests)."""
        rel, kw = self._flat_args(rel, collection_id)
        return self.repo.files_below_sql(rel, sort=sort, **kw)

    def folders(self) -> list[str]:
        """Every indexed folder except the quarantine and inbox trees (filing targets)."""
        hidden = (*self.executor.paths.quarantines, self.special.inbox)
        return sorted(
            (p for p in self.repo.dir_paths() if not any(is_under(p, h) for h in hidden)),
            key=_sort_key,
        )

    def quarantine(self, drive_ids: list[str], origin: str, dry_run: bool = False) -> BatchResult:
        """Move the entries into the quarantine folder (mirrored path). Never deletes.

        The whole batch is refused (``InvalidRequest``), before anything is planned,
        when one of the entries is marked ! Important, is a folder holding one, or lies
        under a folder that is marked (protection follows the mark down). The
        marks are read and the batch runs under ``important_lock``
        (``CollectionService.important_lock``), so nothing can be marked Important in
        between: such a mark waits for the batch, and the next quarantine sees it.
        Other member changes (★, ordinary collections) never wait for it."""
        check_origin(origin)
        records = []
        for drive_id in drive_ids:
            rec = self.repo.get(drive_id)
            if rec is None or rec.missing or rec.parked_at is not None:
                raise NotFound(drive_id)
            records.append(rec)
        ops = [Op(OpKind.QUARANTINE, rec.path, None) for rec in records]
        with self.important_lock:
            self._refuse_important(records)
            what = records[0].name if len(records) == 1 else f"{len(records)} files"
            plan = Plan(ops, origin=origin, label=f"Moved {what} to To Delete")
            return self.executor.apply(plan, dry_run=dry_run)

    def restore(
        self,
        drive_ids: list[str],
        to: str,
        origin: str,
        dry_run: bool = False,
        folder: str | None = None,
    ) -> BatchResult:
        """Move entries out of the quarantine folder again, as one journaled batch (a
        MOVE per entry; Undo puts them back in To Delete). Never deletes.

        ``to`` ``"original"``: back to the path they were marked at (the path with the
        quarantine prefix stripped); a folder that no longer exists is made again (an
        MKDIR in the plan), a name that is taken gets ``_N`` (the plan says so).
        ``to`` ``"inbox"``: into the inbox folder. ``to`` ``"folder"``: into ``folder`` (an
        ordinary archive folder, made if missing; never the top of the archive, ``##.
        Ongoing``, ``##. Important`` or ``##. To Delete``): a drag out of To Delete. A
        folder marked for deletion moves as
        a whole; an entry inside another selected folder comes along with it. Refused
        (``InvalidRequest``): an entry not in the quarantine folder, the quarantine
        folder itself, a folder that stood at the top of the archive, and an original
        place in ``##. Ongoing`` (use the inbox)."""
        check_origin(origin)
        if to not in ("original", "inbox", "folder"):
            raise InvalidRequest(f"cannot restore to {to!r}")
        if (to == "folder") != (folder is not None):
            raise InvalidRequest("A folder is given with, and only with, restoring to a folder")
        target = self._drop_folder(folder, "restored") if folder is not None else None
        if isinstance(drive_ids, str) or not isinstance(drive_ids, list | tuple) or not drive_ids:
            raise InvalidRequest("No files given")
        if len(set(drive_ids)) != len(drive_ids):
            dup = next(d for d in drive_ids if drive_ids.count(d) > 1)
            raise InvalidRequest(f"File {dup!r} requested more than once")
        paths = self.executor.paths
        records = []
        for drive_id in drive_ids:
            rec = self.repo.get(drive_id)
            if rec is None or rec.missing or rec.parked_at is not None:
                raise NotFound(drive_id)
            if not paths.is_quarantined(rec.path, strict=True):
                where = paths.quarantine_for(rec.path)
                raise InvalidRequest(f"{rec.path} is not in {where}: nothing to restore")
            records.append(rec)
        dirs = [r.path for r in records if r.is_dir]
        records = [r for r in records if not any(is_under(r.path, d, strict=True) for d in dirs)]
        ops = []
        for rec in records:
            original = self._original(rec.path)
            if to == "inbox":
                dest = self.special.inbox
            elif target is not None:
                dest = target
            else:
                dest = parent(original)
                if not dest:
                    raise InvalidRequest(
                        f"{rec.path}: it stood at the top of the archive; restore it to the inbox"
                    )
                try:
                    check_destination_area(dest, paths)
                except InvalidRequest:
                    raise InvalidRequest(
                        f"{rec.path}: its original place is in {self.special.ongoing};"
                        " restore it to the inbox"
                    ) from None
            ops.append(Op(OpKind.MOVE, rec.path, dest, allow_top_level=to == "original"))
        what = records[0].name if len(records) == 1 else f"{len(records)} files"
        label = f"Restored {what} from To Delete"
        if to == "inbox":
            label += " to the inbox"
        elif target is not None:
            label += f" to {target}"
        plan = Plan(ops, origin=origin, label=label, copy_across=True)
        if dry_run:
            return self.executor.apply(plan, dry_run=True)
        return self._apply_or_background(plan, None, lambda r: r)

    def _apply_or_background(
        self,
        plan: Plan,
        check: Callable[[list[ResolvedOp]], None] | None,
        result_of: Callable[[BatchResult], BatchResult],
    ) -> BatchResult:
        """Apply ``plan``, or, when it copies files across disks, run it as a background
        job (``copy_jobs``) and answer with its ``job_id`` at once. Refusals (and
        ``check``) answer the request either way. ``result_of`` turns a batch into the
        answer (and the job's result). The job plans again and runs with the same
        ``check``, so what runs is what was checked; its progress counts the files copied
        and their bytes, also within a large file."""

        def check_here(ops: list[ResolvedOp]) -> None:
            if check is not None:
                check(ops)
            if self.copy_jobs is not None and any(o.kind is OpKind.COPY_ACROSS for o in ops):
                raise _Background(ops)

        try:
            return result_of(self.executor.apply(plan, check=check_here))
        except _Background as hand_over:
            resolved = hand_over.ops
        copies = [r for r in resolved if r.kind is OpKind.COPY_ACROSS]
        total, size = len(copies), sum(r.size or 0 for r in copies)

        def work(ctx) -> BatchResult:
            moved = {"files": 0, "bytes": 0}
            ctx.progress(0, total, 0, size, PurePosixPath(copies[0].src).name)

            def progress(rop: ResolvedOp, index: int, ops: int) -> None:
                if rop.kind is not OpKind.COPY_ACROSS:
                    return
                moved["files"] += 1
                moved["bytes"] += rop.size or 0
                n = moved["files"]
                upcoming = PurePosixPath(copies[n].src).name if n < total else None
                ctx.progress(n, total, moved["bytes"], size, upcoming)

            def copied(rop: ResolvedOp, n: int) -> None:
                name = PurePosixPath(rop.src).name
                ctx.progress(moved["files"], total, moved["bytes"] + n, size, name)

            result = self.executor.apply(
                plan, check=check, should_stop=ctx.stopped, progress=progress, copied=copied
            )
            if result.stopped:
                result.error = f"Stopped: {moved['files']} of {total} files moved."
            return result_of(result)

        job = self.copy_jobs.start(work)
        return result_of(BatchResult("", False, job_id=job.job_id))

    def _original(self, path: str) -> str:
        """``path`` (inside a quarantine folder) without that folder's quarantine prefix,
        so in the same archive folder: ``Old years/##. To Delete/2009/a.pdf`` ->
        ``Old years/2009/a.pdf``."""
        paths = self.executor.paths
        label = paths.label_of(path)
        quarantine = paths.quarantine_for(path)
        parts = PurePosixPath(path).parts[len(PurePosixPath(quarantine).parts) :]
        return PurePosixPath(*((label,) if label else ()), *parts).as_posix()

    def _refuse_important(self, records: list[FileRecord]) -> None:
        """One query for the Important entries; refuse if any record is one, is a
        folder with one below it, or lies under a marked folder (``IMPORTANT_FOLDER_
        REFUSAL``). No per-record queries: the marked set is read once."""
        if self.important is None or not records:
            return
        marked = self.important()
        if not marked:
            return
        ids = {drive_id for drive_id, _, _ in marked}
        marked_folders = [p for _, p, is_dir in marked if is_dir]
        for rec in records:
            if rec.drive_id in ids:
                raise InvalidRequest(f"{IMPORTANT_REFUSAL}: {rec.path}")
            path = nfc(rec.path_nfc)
            if rec.is_dir:
                below = next((p for _, p, _ in marked if _under(p, path)), None)
                if below is not None:
                    raise InvalidRequest(f"{IMPORTANT_REFUSAL}: {below}")
            if any(_under(path, p) for p in marked_folders):
                raise InvalidRequest(f"{IMPORTANT_FOLDER_REFUSAL}: {rec.path}")

    def _drop_folder(self, folder: str, what: str) -> str:
        """The canonical archive folder files dropped on ``folder`` go into, refused
        (``InvalidRequest``) for the top of the archive and the app's own folders."""
        try:
            dest = canonical(folder, self.executor.paths)
        except GuardError:
            raise InvalidRequest(f"{folder!r} is not a folder in the archive") from None
        if not dest:
            raise InvalidRequest("Not allowed: the top of the archive holds folders only")
        paths = self.executor.paths
        for area in (*paths.quarantines, self.special.ongoing, self.special.important):
            if is_under(dest, area):
                raise InvalidRequest(f"Nothing is {what} into {area}: the app keeps that folder")
        return dest

    def _resolve_row(self, rec: FileRecord, mode: str) -> FileRecord:
        """A row of ``##. Ongoing`` or ``##. Important`` (the app's links) stands for the
        file it links to: that file is what moves, is linked or is copied. A link that
        leads nowhere in the archive is refused. A move of a file marked Important is
        refused (a row in ``##. Important`` is one by definition)."""
        area = next(
            (
                a
                for a in (self.special.ongoing, self.special.important)
                if is_under(rec.path, a, strict=True)
            ),
            None,
        )
        if area is None or not rec.is_link:
            return rec
        target = link_target(self.executor.paths, self.repo, rec)
        if target is None:
            raise InvalidRequest(f"{rec.path}: the link points outside the archive or to nothing")
        if mode == "move":
            if area == self.special.important:
                raise InvalidRequest(f"{IMPORTANT_REFUSAL}: {target.path}")
            self._refuse_important([target])
        return target

    # -- move -----------------------------------------------------------------

    def move_plan(self, drive_ids: list[str], folder: str, origin: str = "ui") -> Plan:
        """One MOVE op per file into ``folder``, keeping its name (see ``_move_ops``)."""
        return self._move_ops(drive_ids, folder, origin).plan

    def _drop(self, drive_ids: list[str], folder: str, origin: str, mode: str) -> "_Move":
        """The plan of a drop of files on a folder: ``mode`` ``move`` (rows of Ongoing and
        Important stand for the file they link to), ``link`` or ``copy`` (see
        ``_link_copy_ops``)."""
        if mode not in DROP_MODES:
            raise InvalidRequest(f"unknown way to put files in a folder: {mode!r}")
        if mode == "move":
            move = self._move_ops(drive_ids, folder, origin, resolve_rows=True)
            move.plan.copy_across = True  # a move by hand may cross disks
            return move
        return self._link_copy_ops(drive_ids, folder, origin, mode)

    def _check_drop(self, ids: list[str], resolved: list[ResolvedOp], mode: str) -> None:
        kinds = {"move": None, "link": (OpKind.SYMLINK,), "copy": (OpKind.COPY,)}[mode]
        if kinds is None:
            self._check_identity(ids, resolved)
        else:
            check_disk_identity(self.executor.paths, self.repo, ids, resolved, kinds)

    def move_preview(
        self, drive_ids: list[str], folder: str, origin: str = "ui", mode: str = "move"
    ) -> list[ResolvedOp]:
        """The ops ``move`` would run: new folders, ``_N`` collision renames (with their
        note). Nothing is journaled or changed. Refused (``InvalidRequest``) when the
        disk no longer matches the index (``_check_identity``)."""
        move = self._drop(drive_ids, folder, origin, mode)
        resolved = self.executor.preview(move.plan)
        self._check_drop(move.ids, resolved, mode)
        return resolved

    def move(
        self,
        drive_ids: list[str],
        folder: str,
        origin: str = "ui",
        dry_run: bool = False,
        mode: str = "move",
    ) -> MoveResult:
        """Move the files into ``folder`` as one journaled (undoable) batch. ``mode``
        ``link``: a symbolic link to each file in ``folder`` instead (the file stays;
        Undo removes the link); ``copy``: a copy of each (Undo moves the copy to ``##. To
        Delete``).

        The resolved ops pass ``_check_identity`` before anything is applied, and the
        executor runs exactly those ops. A failed or interrupted batch is returned as
        is, never raised. Collection members are tracked by drive id: the next scan and
        Ongoing sync repoint their links, nothing is synced here.
        """
        move = self._drop(drive_ids, folder, origin, mode)
        def check(ops: list[ResolvedOp]) -> None:
            self._check_drop(move.ids, ops, mode)

        if mode == "move" and not dry_run:
            return self._apply_or_background(
                move.plan,
                check,
                lambda r: MoveResult(**vars(r), unchanged=move.unchanged, folder=move.folder),
            )
        result = self.executor.apply(move.plan, dry_run=dry_run, check=check)
        if mode != "move" and result.done and not dry_run and self.rescan is not None:
            try:
                self.rescan(move.folder)
            except Exception:  # the batch is done; the watcher's next scan picks them up
                log.warning("indexing the new links or copies failed", exc_info=True)
        return MoveResult(**vars(result), unchanged=move.unchanged, folder=move.folder)

    # -- rename ("Edit details…") ---------------------------------------------

    def rename_file_preview(
        self, drive_id: str, name: str, folder: str, origin: str = "ui"
    ) -> list[ResolvedOp]:
        """The ops ``rename_file`` would run (none when nothing changes); nothing is
        journaled. Refused when the disk no longer matches the index, as for a move."""
        move = self._move_ops([drive_id], folder, origin, name=name)
        resolved = self.executor.preview(move.plan)
        self._check_identity(move.ids, resolved)
        return resolved

    def rename_file(
        self, drive_id: str, name: str, folder: str, origin: str = "ui", dry_run: bool = False
    ) -> MoveResult:
        """Give one file ``name`` in ``folder`` as one journaled (undoable) batch: a
        RENAME in its own folder, else a MOVE carrying the new name. The same area
        rules and identity check as ``move``; a name already taken gets ``_N``."""
        move = self._move_ops([drive_id], folder, origin, name=name)
        result = self.executor.apply(
            move.plan, dry_run=dry_run, check=lambda ops: self._check_identity(move.ids, ops)
        )
        return MoveResult(**vars(result), unchanged=move.unchanged, folder=move.folder)

    def _check_identity(self, ids: list[str], resolved: list[ResolvedOp]) -> None:
        """Each MOVE must be the requested file, a regular file on disk
        (``check_disk_identity``): catches an index that is stale."""
        check_disk_identity(self.executor.paths, self.repo, ids, resolved)

    def _move_ops(
        self,
        drive_ids: list[str],
        folder: str,
        origin: str,
        name: str | None = None,
        resolve_rows: bool = False,
    ) -> "_Move":
        """The MOVE plan, the id of each op's file (in plan order), the ids already in
        ``folder`` (no op) and the canonical destination rel.

        Area rules only (files only; nothing from or into Ongoing, nothing into the
        quarantine; ``InvalidRequest``). Everything else (collisions, new folders, top
        level, protected paths, a destination that is a file or a link) is left to the
        executor's guards, as for filing.

        ``resolve_rows`` (a drop): a row of ``##. Ongoing`` / ``##. Important`` stands for
        the file it links to, which is what moves (``_resolve_row``).

        ``name`` (one file only, "Edit details…"): the file's new name; in its own
        folder that is a RENAME, elsewhere a MOVE with ``name``.
        """
        check_origin(origin)
        if name is not None:
            if len(drive_ids) != 1:
                raise InvalidRequest("A new name is for one file")
            if not name or "/" in name or name in (".", "..") or name != name.strip():
                raise InvalidRequest(f"Invalid name {name!r}")
            if len(name.encode()) > 255:
                raise InvalidRequest("The name is longer than 255 bytes")
            if is_ds_store_name(name):
                raise InvalidRequest(f"The name {name!r} is reserved for Finder's .DS_Store")
        if isinstance(drive_ids, str) or not isinstance(drive_ids, list | tuple):
            raise InvalidRequest("Drive ids must be a list")
        if not drive_ids:
            raise InvalidRequest("No files given")
        if len(set(drive_ids)) != len(drive_ids):
            dup = next(d for d in drive_ids if drive_ids.count(d) > 1)
            raise InvalidRequest(f"File {dup!r} requested more than once")
        try:
            dest = canonical(folder, self.executor.paths)
        except GuardError:
            raise InvalidRequest(f"{folder!r} is not a folder in the archive") from None
        check_destination_area(dest, self.executor.paths)
        move = _Move(Plan([], origin=origin), [], [], dest)
        requested = list(drive_ids)
        drive_ids = []  # the files that move: a row of Ongoing / Important is its target
        for requested_id in requested:
            rec = self.repo.get(requested_id)
            if rec is None or rec.missing or rec.parked_at is not None:
                raise NotFound(requested_id)
            if resolve_rows:
                rec = self._resolve_row(rec, "move")
                if rec.drive_id in drive_ids:  # two rows (two collections) of one file
                    continue
            drive_id = rec.drive_id
            drive_ids.append(drive_id)
            if rec.is_dir:
                raise InvalidRequest(f"{rec.path}: folders cannot be moved yet")
            if rec.is_link:
                raise InvalidRequest(f"{rec.path}: links cannot be moved")
            for area in (self.special.ongoing, *self.executor.paths.quarantines):
                if is_under(rec.path, area):
                    raise InvalidRequest(f"{rec.path}: files in {area} cannot be moved")
            renamed = name is not None and name != rec.name
            if fold_parts(parent(rec.path)) == fold_parts(dest):
                if not renamed:
                    move.unchanged.append(drive_id)
                    continue
                move.plan.ops.append(Op(OpKind.RENAME, rec.path, name))
            else:
                move.plan.ops.append(
                    Op(OpKind.MOVE, rec.path, dest, name=name if renamed else None)
                )
            move.ids.append(drive_id)
        move.plan.label = self._move_label(drive_ids, name, dest, move)
        return move

    def _link_copy_ops(self, drive_ids: list[str], folder: str, origin: str, mode: str) -> "_Move":
        """``mode`` ``link``: a SYMLINK in ``folder`` to each file (named like it); the
        file stays where it is. ``copy``: a COPY of each file into ``folder`` (a taken
        name, also the file's own in its own folder, gets ``_N``). Rows of ``##. Ongoing``
        / ``##. Important`` act on the file they link to. Files already in ``folder``
        need no link (``unchanged``). Nothing is made in the top of the archive or in the
        app's own folders; a file marked for deletion is restored first."""
        check_origin(origin)
        verb = "linked" if mode == "link" else "copied"
        if isinstance(drive_ids, str) or not isinstance(drive_ids, list | tuple):
            raise InvalidRequest("Drive ids must be a list")
        if not drive_ids:
            raise InvalidRequest("No files given")
        if len(set(drive_ids)) != len(drive_ids):
            dup = next(d for d in drive_ids if drive_ids.count(d) > 1)
            raise InvalidRequest(f"File {dup!r} requested more than once")
        dest = self._drop_folder(folder, verb)
        if mode == "link" and not can_make_links():
            raise InvalidRequest(LINK_UNAVAILABLE)
        move = _Move(Plan([], origin=origin), [], [], dest)
        chosen: list[FileRecord] = []
        for requested_id in drive_ids:
            rec = self.repo.get(requested_id)
            if rec is None or rec.missing or rec.parked_at is not None:
                raise NotFound(requested_id)
            if self.executor.paths.is_quarantined(rec.path):
                raise InvalidRequest(f"{rec.path}: restore it first, then it can be {verb}")
            rec = self._resolve_row(rec, mode)
            if any(r.drive_id == rec.drive_id for r in chosen):
                continue  # two rows (two collections) of one file
            chosen.append(rec)
            if rec.is_dir:
                raise InvalidRequest(f"{rec.path}: folders cannot be {verb} yet")
            if rec.is_link:
                raise InvalidRequest(f"{rec.path}: links cannot be {verb}")
            if self.executor.paths.is_quarantined(rec.path) or any(
                is_under(rec.path, a) for a in (self.special.ongoing, self.special.important)
            ):
                raise InvalidRequest(f"{rec.path}: files in the app's own folders cannot be {verb}")
            if mode == "link":
                if fold_parts(parent(rec.path)) == fold_parts(dest):
                    move.unchanged.append(rec.drive_id)
                    continue
                move.plan.ops.append(Op(OpKind.SYMLINK, rec.path, f"{dest}/{rec.name}"))
            else:
                move.plan.ops.append(Op(OpKind.COPY, rec.path, dest))
            move.ids.append(rec.drive_id)
        if move.ids:
            what = chosen[0].name if len(chosen) == 1 else f"{len(chosen)} files"
            move.plan.label = (
                f"Linked {what} in {dest}" if mode == "link" else f"Copied {what} to {dest}"
            )
        return move

    def _move_label(
        self, drive_ids: list[str], name: str | None, dest: str, move: "_Move"
    ) -> str | None:
        """The batch's title: "Moved X to <folder>", or for one file given a name
        ("Edit details…") "Renamed X to Y"."""
        if not move.ids:
            return None
        first = self.repo.get(drive_ids[0])
        old = first.name if first is not None else None
        if len(drive_ids) == 1 and name is not None and old is not None and name != old:
            if fold_parts(parent(first.path)) == fold_parts(dest):
                return f"Renamed {old} to {name}"
            return f"Renamed {old} to {name} and moved it to {dest}"
        what = old if len(move.ids) == 1 and old else f"{len(move.ids)} files"
        return f"Moved {what} to {dest}"
