"""Turn a Plan into ResolvedOps: validate, simulate sequentially, resolve collisions.

Nothing here touches the disk except to read it.
"""

import dataclasses
import math
import os
import stat
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from dam.core.foldernames import FolderNameError, check_folder_name
from dam.core.naming import unique_name
from dam.core.paths import ArchivePaths, nfc, not_connected_message
from dam.index.driveid import read_drive_id
from dam.ops import primitives
from dam.ops.guards import (
    canonical,
    check_areas_source,
    check_connected,
    fold_parts,
    is_abs_target,
    is_under,
    join,
    parent,
    rebase,
    removal_protected,
    touches_protected,
    validate,
)
from dam.ops.model import ABS_TARGET, GuardError, Op, OpFailed, OpKind, Plan, ResolvedOp
from dam.ops.primitives import (
    DS_STORE,
    PICTURE_COPY,
    PICTURE_RENAME,
    PRESENT,
    TEMP_COPY_PREFIX,
    different_disks_message,
)

if TYPE_CHECKING:
    from dam.locks import LockService

_EXACT_SOURCE = {OpKind.QUARANTINE, OpKind.REMOVE_EMPTY_DIR}  # never follow a redirect

# ops whose source is not (only) an archive path: COPY and PICTURE_TO_QUARANTINE read an
# "abs:" file; PICTURE_BACK is handled by its own case (its source is in the archive)
_OUTSIDE_SOURCE = {OpKind.COPY, OpKind.PICTURE_TO_QUARANTINE}


def _outside(op: Op) -> bool:
    """The op's source is not an archive path: a COPY of a file elsewhere on this
    computer, or a rule picture. (A COPY of a file already in the archive is read like
    any other archive source.)"""
    if op.kind is OpKind.COPY:
        return isinstance(op.src, str) and op.src.startswith(ABS_TARGET)
    return op.kind in _OUTSIDE_SOURCE

COLLISION_NOTE = "renamed to avoid collision"
COPY_NOTE = "copied, then removed from dam's settings folder"
COPY_BACK_NOTE = "copied back; the copy in To Delete stays"
ORIGINAL_STAYS_NOTE = "the original stays in To Delete"
MKDIR_NOTE = "create missing folder"
PRESENT_NOTE = "already at the destination; checked, not copied again"
# how far a file's mtime at the destination may be from the source's and still count
# as ``present`` (FAT32 keeps 2-second steps)
_PRESENT_MTIME_NS = 2_000_000_000


_UNREAD = object()


def _same(a: str, b: str) -> bool:
    return fold_parts(a) == fold_parts(b)


def _below(folder: str, parts: tuple[str, ...]) -> str:
    """``folder`` joined with the path ``parts`` (none: ``folder`` itself)."""
    return "/".join((folder, *parts)) if folder else "/".join(parts)


def _add_note(note: str | None, extra: str) -> str:
    return f"{note}; {extra}" if note else extra


def list_tree(root: Path, name: str) -> list[tuple[tuple[str, ...], str, os.stat_result]]:
    """Everything inside the folder ``root`` (named ``name`` in messages), links not
    followed, as (path parts relative to ``root``, kind, lstat), parents before children,
    each folder's entries sorted by folded name. ``.DS_Store`` files are left out; an
    unfinished copy (``.dam-copy-*``), anything that is not a file, folder or link, or
    two names of one folder that differ only in case or normalization refuses. The
    planner lists a folder moved across disks with it, and the executor lists it again
    before the folder goes to To Delete."""
    out: list[tuple[tuple[str, ...], str, os.stat_result]] = []

    def walk(folder: Path, rel: tuple[str, ...]) -> None:
        with os.scandir(folder) as it:
            entries = sorted(it, key=lambda e: (fold_parts(e.name), e.name))
        for one, other in zip(entries, entries[1:], strict=False):
            if fold_parts(one.name) == fold_parts(other.name):
                # a case- or normalization-sensitive disk: the tree (keyed by folded
                # name) would hold only one of them, and the other could reach To Delete
                # uncopied
                raise GuardError(
                    f"{_below(name, rel)} holds {one.name} and {other.name}, which differ"
                    " only in case or accents. Rename one of them first."
                )
        for entry in entries:
            st = entry.stat(follow_symlinks=False)
            if entry.name.startswith(TEMP_COPY_PREFIX):
                raise GuardError(f"Remove the unfinished copy {entry.name} first.")
            if stat.S_ISLNK(st.st_mode):
                kind = "link"
            elif stat.S_ISDIR(st.st_mode):
                kind = "dir"
            elif stat.S_ISREG(st.st_mode):
                if entry.name == DS_STORE:
                    continue  # Finder makes it again; the original goes with the folder
                kind = "file"
            else:
                raise GuardError(
                    f"{entry.name} is not a file, folder or link, so"
                    f" {name} is not copied across disks."
                )
            out.append(((*rel, entry.name), kind, st))
            if kind == "dir":
                walk(Path(entry.path), (*rel, entry.name))

    walk(root, ())
    return out


def tree_key(parts: tuple[str, ...]) -> str:
    """The key of an entry in a folder move's ``tree``: its folded path inside the folder."""
    return "/".join(fold_parts("/".join(parts)))


def tree_of(
    listed: list[tuple[tuple[str, ...], str, os.stat_result]],
) -> dict[str, tuple[str, int | None, float | None]]:
    """A ``list_tree`` listing as a folder move's ``tree``: files with size and mtime,
    folders and links by kind only."""
    return {
        tree_key(parts): (kind, st.st_size, st.st_mtime) if kind == "file" else (kind, None, None)
        for parts, kind, st in listed
    }


class _Sim:
    """The archive as it will look after the ops simulated so far.

    Events: ("create", path, kind), ("move", old, new), ("remove", path).
    """

    def __init__(self, paths: ArchivePaths) -> None:
        self.paths = paths
        self.events: list[tuple] = []

    def _origin(self, rel: str) -> tuple[str | None, str | None]:
        """Walk events backwards: (disk rel, None) or (None, simulated kind or None)."""
        r = rel
        for ev in reversed(self.events):
            match ev:
                case ("create", p, kind):
                    if _same(r, p):
                        return None, kind
                    if is_under(r, p):
                        return None, None
                case ("move", old, new):
                    if is_under(r, new):
                        r = rebase(r, new, old)
                    elif is_under(r, old):
                        return None, None
                case ("remove", p):
                    if is_under(r, p):
                        return None, None
        return r, None

    def kind(self, rel: str) -> str | None:
        """Kind of entry at ``rel``: dir, link, file or None. Symlinks are never followed."""
        disk, kind = self._origin(rel)
        if disk is None:
            return kind
        p = self.paths.join(disk)
        if p.is_symlink():
            return "link"
        if p.is_dir():
            return "dir"
        return "file" if os.path.lexists(p) else None

    def disk_path(self, rel: str) -> Path | None:
        disk, _ = self._origin(rel)
        return None if disk is None else self.paths.join(disk)

    def _current(self, start: int, rel: str) -> str | None:
        """Where an entry created/moved at event ``start`` is now (None if gone)."""
        r = rel
        for ev in self.events[start + 1 :]:
            match ev:
                case ("move", old, new) if is_under(r, old):
                    r = rebase(r, old, new)
                case ("remove", p) if is_under(r, p):
                    return None
        return r

    def added_names(self, folder: str) -> list[str]:
        """Names of entries the simulation has put directly into ``folder``."""
        names = []
        for i, ev in enumerate(self.events):
            target = ev[1] if ev[0] == "create" else ev[2] if ev[0] == "move" else None
            if target is None:
                continue
            now = self._current(i, target)
            if now is not None and _same(parent(now), folder):
                names.append(PurePosixPath(now).name)
        return names

    def entries(self, folder: str) -> list[tuple[str, str, bool]]:
        """(name, kind, untouched) of everything in ``folder`` at this point of the
        batch. ``untouched``: an on-disk entry no earlier op of the batch created, moved
        or renamed (entries put there by an earlier op are listed with False)."""
        added = self.added_names(folder)
        out = [(n, self.kind(join(folder, n)), False) for n in added]
        disk = self.disk_path(folder)
        if disk is not None and disk.is_dir() and not disk.is_symlink():
            taken = {fold_parts(n) for n in added}
            for entry in disk.iterdir():
                if fold_parts(entry.name) in taken:
                    continue  # that name now holds what the earlier op put there
                kind = self.kind(join(folder, entry.name))
                if kind is not None:
                    out.append((entry.name, kind, True))
        return out

    def spell(self, rel: str) -> str:
        """``rel`` with every existing component in its actual (on-disk) spelling."""
        out: list[str] = []
        for part in PurePosixPath(rel).parts:
            folder = "/".join(out)
            if self.kind(folder) != "dir":  # missing (or not a folder): keep the rest as is
                out.append(part)
                continue
            out.append(self._spelling_in(folder, part) or part)
        return "/".join(out)

    def _spelling_in(self, folder: str, name: str) -> str | None:
        want = fold_parts(name)
        for added in reversed(self.added_names(folder)):
            if fold_parts(added) == want:
                return added
        disk = self.disk_path(folder)
        if disk is None or not disk.is_dir():
            return None
        # On a case-sensitive volume ``report.pdf`` and ``Report.pdf`` can both exist:
        # prefer the exact spelling, then the same name in another normal form, and only
        # then a name that differs in case.
        best: tuple[int, str] | None = None
        for entry in disk.iterdir():
            n = entry.name
            if fold_parts(n) != want or not self.kind(join(folder, n)):
                continue
            rank = 0 if n == name else 1 if nfc(n) == nfc(name) else 2
            if rank == 0:
                return n
            if best is None or rank < best[0]:
                best = (rank, n)
        return best[1] if best else None

    def free_name(self, folder: str, name: str, exclude: str | None = None) -> str:
        """``unique_name`` against the disk folder plus entries simulated into it.

        Names vacated earlier in the batch still count as taken (conservative: may add
        an unnecessary suffix, never risks a collision).
        """
        disk = self.disk_path(folder)
        directory = disk if disk is not None else self.paths.join(folder)
        added = self.added_names(folder)
        if exclude is not None:
            added = [a for a in added if fold_parts(a) != fold_parts(exclude)]
        return unique_name(directory, name, exclude=exclude, taken=added)


class Planner:
    def __init__(
        self,
        paths: ArchivePaths,
        areas_dir: Path | None = None,
        locks: "LockService | None" = None,
    ) -> None:
        self.paths = paths
        self.areas_dir = areas_dir  # the rules' picture folder (PICTURE_* ops only)
        # the lock service, when locked files must be refused (never in an undo)
        self.locks = locks

    def resolve(
        self, plan: Plan, *, restore: bool = False, connected: dict[str, bool] | None = None
    ) -> list[ResolvedOp]:
        """``restore``: only for plans built by ``dam.ops.undo`` (see ``validate``).
        ``connected``: folder connectivity already looked at in this planning (undo)."""
        self.sim = _Sim(self.paths)
        self.aliases: list[tuple[str, str]] = []  # (requested path, actual path)
        self.from_protected: list[str] = []  # current paths of entries moved out of protection
        self.out: list[ResolvedOp] = []
        self._restore = restore
        self._locked_state = _UNREAD  # read when the first file is to be changed
        self.locked_names: list[str] = []  # files this plan may not change (locked)
        # label -> connected, for this planning: each folder's root is listed once
        self._connected: dict[str, bool] = {} if connected is None else connected
        if plan.inbox_folders and not plan.new_folders:
            raise GuardError("Inbox folders are made only by a new-folder plan.")
        self.made = plan.new_folders  # MKDIRs of a New folder / layout batch are "made"
        # a move by hand may copy files across disks; an undo never does
        self._copy_plan = plan.copy_across and not restore
        self._copy_bytes: dict[str, int] = {}  # folder label -> bytes copied into it
        ops = self._new_folder_ops(plan) if plan.new_folders else plan.ops
        for op in ops:
            # not a place that changes: a RENAME's or PICTURE_BACK's dst is a name, an
            # UNLINK_SYMLINK's the target the link is only compared with
            other_dst = op.kind in (OpKind.RENAME, OpKind.PICTURE_BACK, OpKind.UNLINK_SYMLINK)
            check_connected(
                self.paths, op.src, None if other_dst else op.dst, known=self._connected
            )
            validate(op, self.paths, restore=restore)
            redirect = None
            if not _outside(op) and op.src is not None and not is_abs_target(op):
                src = self.sim.spell(canonical(op.src, self.paths))
                src, redirect = self._alias(src)
                if redirect is not None and op.kind in _EXACT_SOURCE:
                    # Quarantine and folder removal must name exactly what they remove:
                    # never follow a redirect.
                    raise GuardError(
                        f"ambiguous: {op.src!r} was renamed earlier in this batch;"
                        f" name {src!r} explicitly"
                    )
                op = dataclasses.replace(op, src=src)
                validate(op, self.paths, restore=restore)
            self._resolve_one(op)
            if redirect is not None:  # the op's own entry is always appended last
                self.out[-1].note = _add_note(self.out[-1].note, redirect)
        if self.locked_names:
            raise GuardError(self._locked_message(len(plan.ops)))
        self._check_space()
        return self.out

    def _lock_state(self):
        """(locked entries, ids unlocked by this request's grants), or None when locks do
        not apply: no lock service, nothing locked, or an undo (it only puts back what
        the owner did)."""
        if self.locks is None or self._restore:
            return None
        from dam.locks import request_tokens

        entries = self.locks.entries()
        if not entries:
            return None
        return entries, self.locks.granted(request_tokens())

    def _check_locked(self, src: str) -> None:
        """Note ``src`` (a RENAME, MOVE or QUARANTINE source) when it is, holds or lies
        inside a locked file that no unlock covers. The plan is refused at the end, with
        every such file named."""
        if self._locked_state is _UNREAD:
            self._locked_state = self._lock_state()
        if self._locked_state is None:
            return
        disk, _ = self.sim._origin(src)
        if disk is None:  # made earlier in this batch: nothing locked about it
            return
        entries, granted = self._locked_state
        drive_id = self.locks.indexed_id(disk) or self._drive_id(src)
        if self.locks.refused(disk, drive_id, entries, granted):
            self.locked_names.append(PurePosixPath(src).name)

    def _locked_message(self, ops: int) -> str:
        from dam.locks import LOCKED_MESSAGE

        names = list(dict.fromkeys(self.locked_names))
        if ops == 1 and len(names) == 1:
            return LOCKED_MESSAGE
        if len(names) == 1:
            return f"This file is locked ({names[0]}). Unlock it to change it."
        return f"These files are locked ({', '.join(names)}). Unlock them to change them."

    def _new_folder_ops(self, plan: Plan) -> list[Op]:
        """The ops of a ``Plan.new_folders`` plan (the user-confirmed New folder and
        layout workflows, the only way a top-level folder is ever created): nothing but
        MKDIR, every folder name checked, nothing inside the app's own folders. Returns
        the ops with ``allow_top_level`` set; no other plan gets that.

        With ``Plan.inbox_folders`` a folder directly inside the inbox (its parent,
        folded, is exactly the inbox) is allowed as well; nothing deeper."""
        special = self.paths.settings.special_folders
        names = (special.inbox, special.ongoing, special.important, special.quarantine)
        out = []
        for op in plan.ops:
            if op.kind is not OpKind.MKDIR or op.exact or op.src is not None:
                raise GuardError("A new-folder plan holds only plain folder creations.")
            folder = canonical(op.dst, self.paths)
            for part in PurePosixPath(folder).parts:
                try:
                    check_folder_name(part, names)
                except FolderNameError as e:
                    raise GuardError(str(e)) from None
            inbox_child = plan.inbox_folders and fold_parts(parent(folder)) == fold_parts(
                special.inbox
            )
            # the special folders, and the extra folders' To Delete
            for area in (*names, *self.paths.quarantines[1:]):
                if is_under(folder, area, strict=True) and not (
                    inbox_child and area == special.inbox
                ):
                    raise GuardError(f"Folders are not made inside {area!r}.")
            out.append(dataclasses.replace(op, allow_top_level=True))
        return out

    def _alias(self, src: str) -> tuple[str, str | None]:
        """Follow a collision suffix given to an earlier op's destination.

        Redirect only when the requested path was vacated (nothing there any more in
        the simulation); if a different entry still lives there the reference is
        ambiguous and the plan is refused.
        """
        for requested, actual in reversed(self.aliases):
            if is_under(src, requested):
                if self.sim.kind(requested) is not None:
                    raise GuardError(
                        f"ambiguous: {src!r} names an existing entry, but an earlier op in"
                        f" this batch was renamed from {requested!r} to {actual!r}"
                    )
                new = rebase(src, requested, actual)
                return new, f"redirected from {src!r} (earlier collision suffix)"
        return src, None

    def _require_src(self, src: str, kinds: tuple[str, ...] = ("file", "dir", "link")) -> str:
        # Every ancestor must be a real folder: never act through a symlinked directory.
        # (Re-checked at apply time by the executor's destination-parent check and by
        # ArchivePaths.abs; a folder swapped for a link in between is a residual window.)
        for i in range(1, len(PurePosixPath(src).parts)):
            anc = PurePosixPath(*PurePosixPath(src).parts[:i]).as_posix()
            if self.sim.kind(anc) != "dir":
                raise GuardError(f"{anc!r} is not a folder (symlinks are not followed)")
        kind = self.sim.kind(src)
        if kind is None:
            raise GuardError(f"source {src!r} does not exist")
        if kind not in kinds:
            raise GuardError(f"source {src!r} is not a {' or '.join(kinds)}")
        return kind

    def _ensure_folder(
        self,
        folder: str,
        allow_top_level: bool,
        quarantine_root: bool = False,
        made: bool | None = None,
    ) -> None:
        """Plan MKDIRs for the missing components of ``folder``.

        A new top-level folder needs ``allow_top_level``. The one exception
        (``quarantine_root``, set only for QUARANTINE ops): the configured quarantine
        folder itself may be created, so marking for deletion works before it exists.
        (An extra folder's To Delete sits one level down, so it needs no exception.)
        ``made``: flag the MKDIRs as made (default: the plan's ``new_folders``).
        """
        made = self.made if made is None else made
        parts = PurePosixPath(folder).parts
        for i in range(1, len(parts) + 1):
            sub = PurePosixPath(*parts[:i]).as_posix()
            kind = self.sim.kind(sub)
            if kind == "dir":
                continue
            if kind is not None:
                raise GuardError(f"{sub!r} exists and is not a folder")
            is_quarantine_root = quarantine_root and _same(sub, self.paths.quarantine)
            if self.paths.is_top_level(sub) and not (allow_top_level or is_quarantine_root):
                raise GuardError(f"would create top-level folder {sub!r} (needs allow_top_level)")
            self.out.append(ResolvedOp(OpKind.MKDIR, None, sub, None, MKDIR_NOTE, made=made))
            self.sim.events.append(("create", sub, "dir"))

    def _free_or_exact(self, op: Op, folder: str, wanted: str, src: str | None) -> str:
        """The name to use in ``folder``: a free variant of ``wanted``, or (``op.exact``)
        ``wanted`` itself, refusing if anything other than ``src`` occupies it."""
        same_folder = src is not None and _same(parent(src), folder)
        exclude = PurePosixPath(src).name if same_folder else None
        if not op.exact:
            return self.sim.free_name(folder, wanted, exclude=exclude)
        target = join(folder, wanted)
        # Checked against the simulation: the path must be free at this point of the
        # batch (not the conservative "vacated names stay taken" rule for suffixes).
        if not (src is not None and _same(src, target)) and self.sim.kind(target) is not None:
            raise GuardError(f"cannot restore {target!r}: the path is occupied")
        return wanted

    def _drive_id(self, rel: str) -> str | None:
        disk = self.sim.disk_path(rel)
        return read_drive_id(disk) if disk is not None else None

    def _is_protected_origin(self, rel: str) -> bool:
        """``rel`` is, contains, or lies inside something that started in a protected path."""
        return touches_protected(rel, self.paths) or self._moved_from_protected(rel)

    def _moved_from_protected(self, rel: str) -> bool:
        """``rel`` is, contains, or lies inside an entry this batch moved out of a
        protected path."""
        return any(is_under(p, rel) or is_under(rel, p) for p in self.from_protected)

    def _track_protected(self, src: str, dst: str) -> None:
        moved = [rebase(p, src, dst) if is_under(p, src) else p for p in self.from_protected]
        if self.paths.is_protected(src):
            moved.append(dst)
        for prot in self.paths.settings.protected_paths:
            if is_under(prot, src, strict=True):
                moved.append(rebase(prot, src, dst))
        self.from_protected = moved

    def _relocate(self, op: Op, folder: str) -> None:
        """MOVE / QUARANTINE / RENAME: put ``op.src`` into ``folder`` under a free name."""
        src = op.src
        kind = self._require_src(src)
        self._check_locked(src)
        if not self._same_disk(src, folder):
            if op.kind is OpKind.MOVE and self._copy_plan and kind == "file":
                self._copy_across(op, folder)
                return
            # a folder in To Delete is never copied back across disks
            if (
                op.kind is OpKind.MOVE
                and self._copy_plan
                and kind == "dir"
                and not self.paths.is_quarantined(src)
            ):
                self._copy_folder(op, folder)
                return
            a, b = self.paths.folder_of(src), self.paths.folder_of(folder)
            raise OpFailed(different_disks_message(a.label, b.label))
        into_quarantine = self.paths.is_quarantined(folder)
        if into_quarantine and self._is_protected_origin(src):
            raise GuardError(f"{src!r} comes from a protected path and cannot be quarantined")
        folder = self.sim.spell(folder)
        self._ensure_folder(
            folder, op.allow_top_level, quarantine_root=op.kind is OpKind.QUARANTINE
        )
        if op.kind is OpKind.RENAME:
            wanted = op.dst
        else:
            wanted = op.name or PurePosixPath(src).name
        name = self._free_or_exact(op, folder, wanted, src)
        dst = join(folder, name)
        if name != wanted:
            self.aliases.append((join(folder, wanted), dst))
        note = COLLISION_NOTE if name != wanted else None
        self.out.append(ResolvedOp(op.kind, src, dst, self._drive_id(src), note))
        self.sim.events.append(("move", src, dst))
        self._track_protected(src, dst)

    def _same_disk(self, src: str, folder: str) -> bool:
        """A move between two archive folders is a rename, so it works only when both
        are on one disk; otherwise it is refused (or copied across) here, in the dry
        run, rather than half way."""
        a, b = self.paths.folder_of(src), self.paths.folder_of(folder)
        if a.label == b.label:
            return True
        try:
            return primitives.same_disk(a.root, b.root)
        except OSError:  # unplugged since check_connected looked
            gone = next((f for f in (a, b) if f.label and not os.path.isdir(f.root)), None)
            raise GuardError(not_connected_message(gone or (b if b.label else a))) from None

    def _copy_across(self, op: Op, folder: str) -> None:
        """A MOVE of the file ``op.src`` into ``folder`` in an archive folder on another
        disk: COPY_ACROSS (a verified copy under a free name), then a QUARANTINE of the
        original into its own folder's To Delete. An original already in a To Delete
        (a restore) stays there. A protected file is refused: its original could not go
        to To Delete."""
        src = op.src
        name = PurePosixPath(src).name
        if self._is_protected_origin(src):
            raise GuardError(f"{name} is protected, so it is not copied across disks.")
        folder = self.sim.spell(folder)
        self._ensure_folder(folder, op.allow_top_level)
        original_stays = self.paths.is_quarantined(src)
        if not original_stays:  # made first, so the move to To Delete follows the copy
            aside = self.sim.spell(self._quarantine_folder(src))
            self._ensure_folder(aside, False, quarantine_root=True)
        copy = self._plan_copy(src, folder, op.name or name)
        if original_stays:
            copy.note = _add_note(copy.note, ORIGINAL_STAYS_NOTE)
            return
        self._relocate(Op(OpKind.QUARANTINE, src, None), self._quarantine_folder(src))
        self.out[-1].note = _add_note(self.out[-1].note, f"copied to {copy.dst}")

    def _plan_copy(self, src: str, dst_folder: str, wanted: str) -> ResolvedOp:
        """A COPY_ACROSS of the file ``src`` into ``dst_folder`` (spelled, existing in the
        simulation) under a free variant of ``wanted``; appended, and its size counted
        for ``_check_space``."""
        free = self.sim.free_name(dst_folder, wanted)
        if over := primitives.temp_copy_too_long(free):
            raise GuardError(
                f"{free} is too long a name to copy across disks: the copy is first written"
                f" under a longer temporary name. Shorten it by {over} characters and try again."
            )
        dst = join(dst_folder, free)
        if free != wanted:
            self.aliases.append((join(dst_folder, wanted), dst))
        disk = self.sim.disk_path(src)
        size = os.lstat(disk).st_size
        label = self.paths.label_of(dst)
        self._copy_bytes[label] = self._copy_bytes.get(label, 0) + size
        rop = ResolvedOp(
            OpKind.COPY_ACROSS,
            src,
            dst,
            self._drive_id(src),
            COLLISION_NOTE if free != wanted else None,
            size=size,
            cloud_only=primitives.is_dataless(disk),
        )
        self.out.append(rop)
        self.sim.events.append(("create", dst, "file"))
        return rop

    def _list_tree(self, src: str) -> list[tuple[tuple[str, ...], str, os.stat_result]]:
        """``list_tree`` of the folder ``src`` as it is on disk now."""
        root = self.sim.disk_path(src)
        if root is None:
            raise GuardError(f"{src!r} was made in this batch, so it is not copied across disks.")
        return list_tree(root, PurePosixPath(src).name)

    def _present(self, src_st: os.stat_result, dst: str) -> bool:
        """``dst`` (on disk before this batch) is a regular file with the size of the
        source and an mtime at most 2 seconds from it (exFAT keeps coarser times than
        APFS, and FAT32 keeps them in 2-second steps); the hashes are compared at act
        time, which is the real check."""
        disk = self.sim.disk_path(dst)
        if disk is None:
            return False
        try:
            st = os.lstat(disk)
        except OSError:
            return False
        return (
            stat.S_ISREG(st.st_mode)
            and st.st_size == src_st.st_size
            and abs(st.st_mtime_ns - src_st.st_mtime_ns) <= _PRESENT_MTIME_NS
        )

    def _copy_folder(self, op: Op, folder: str) -> None:
        """A MOVE of the folder ``op.src`` into ``folder`` in an archive folder on another
        disk: MKDIR (made) of the missing folders of the mirrored tree, parents first; a
        COPY_ACROSS per file in tree order (``present`` when the destination already
        holds it); then one QUARANTINE of the whole source into its own folder's To
        Delete, carrying the destination (``copied_to``) and the planned ``tree``.

        A destination folder of that name is merged into (a second move after a stopped
        one); one taken by a file or link gives ``_N``. Links inside are not copied: they
        go to To Delete with the folder. A protected entry anywhere refuses the move."""
        src = op.src
        name = PurePosixPath(src).name
        if self._is_protected_origin(src):
            if self.paths.is_protected(src):
                raise GuardError(f"{name} is protected, so it is not copied across disks.")
            raise GuardError(f"{name} holds a protected entry, so it is not copied across disks.")
        listed = self._list_tree(src)
        folder = self.sim.spell(folder)
        self._ensure_folder(folder, op.allow_top_level)
        wanted = op.name or name
        root = self.sim.spell(join(folder, wanted))
        root_note = None
        if self.sim.kind(root) not in (None, "dir"):
            free = self._free_or_exact(op, folder, wanted, src)
            root = join(folder, free)
            self.aliases.append((join(folder, wanted), root))
            root_note = COLLISION_NOTE
        first = len(self.out)
        self._ensure_folder(root, op.allow_top_level, made=True)
        if root_note is not None and len(self.out) > first:
            self.out[first].note = _add_note(self.out[first].note, root_note)
        for parts, kind, _ in listed:
            if kind == "dir":
                self._ensure_folder(self.sim.spell(_below(root, parts)), False, made=True)
        links = 0
        for parts, kind, st in listed:
            if kind == "link":
                links += 1
                continue
            if kind != "file":
                continue
            file_src = _below(src, parts)
            dst_folder = self.sim.spell(_below(root, parts[:-1]))
            there = self.sim.spell(join(dst_folder, parts[-1]))
            if self.sim.kind(there) == "file" and self._present(st, there):
                self.out.append(
                    ResolvedOp(
                        OpKind.COPY_ACROSS,
                        file_src,
                        there,
                        self._drive_id(file_src),
                        PRESENT_NOTE,
                        size=st.st_size,
                        method=PRESENT,
                        # its act reads the original: a cloud-only one is downloaded
                        cloud_only=primitives.is_dataless(self.sim.disk_path(file_src)),
                    )
                )
                continue
            self._plan_copy(file_src, dst_folder, parts[-1])
        tree = tree_of(listed)
        self._relocate(Op(OpKind.QUARANTINE, src, None), self._quarantine_folder(src))
        quarantine = self.out[-1]
        quarantine.copied_to = root
        quarantine.tree = tree
        quarantine.note = _add_note(quarantine.note, f"copied to {root}")
        if links:
            quarantine.note = _add_note(
                quarantine.note,
                "1 link is not copied; it goes to To Delete with the folder"
                if links == 1
                else f"{links} links are not copied; they go to To Delete with the folder",
            )

    def _check_space(self) -> None:
        """Every archive folder that files are copied into has room for all of them (and
        the margin ``copy_file`` keeps free); checked once here, and again per file."""
        for label, size in self._copy_bytes.items():
            folder = next(f for f in self.paths.folders if f.label == label)
            if not primitives.has_room(folder.root, size):
                where = f"'{label}'" if label else "the main folder"
                needed = math.ceil(size / (1024 * 1024))
                raise OpFailed(
                    f"There is not enough free space on {where} for these files"
                    f" ({needed} MB needed)."
                )

    def _quarantine_folder(self, src: str) -> str:
        """Where QUARANTINE puts ``src``: its own folder's To Delete, keeping the path
        inside that folder (``Old years/2009/a.pdf`` -> ``Old years/##. To Delete/2009``)."""
        parts = PurePosixPath(src).parts
        inner = parts[1:] if self.paths.label_of(src) else parts
        return PurePosixPath(self.paths.quarantine_for(src), *inner).parent.as_posix()

    def _areas(self) -> Path:
        if self.areas_dir is None:
            raise GuardError("The rules' picture folder is not known here, so no picture is moved.")
        return Path(self.areas_dir)

    def _picture_to_quarantine(self, op: Op) -> None:
        """A regular file directly in the rules' areas folder into the quarantine folder
        (made if missing, as for QUARANTINE), under a free variant of ``op.name``."""
        areas = self._areas()
        source = Path(op.src[len(ABS_TARGET) :])
        check_areas_source(source, areas)
        folder = self.sim.spell(canonical(op.dst, self.paths))
        self._ensure_folder(folder, False, quarantine_root=True)
        # a rename works only on one disk: look at the folder, or at what holds it
        disk = self.paths.join(folder)
        while not os.path.lexists(disk) and disk != disk.parent:
            disk = disk.parent
        method = PICTURE_RENAME if primitives.same_disk(areas, disk) else PICTURE_COPY
        name = self.sim.free_name(folder, op.name)
        dst = join(folder, name)
        notes = [COLLISION_NOTE] if name != op.name else []
        if method == PICTURE_COPY:
            notes.append(COPY_NOTE)
        self.out.append(
            ResolvedOp(op.kind, op.src, dst, None, "; ".join(notes) or None, method=method)
        )
        self.sim.events.append(("create", dst, "file"))

    def _picture_back(self, op: Op) -> None:
        """Undo of the above: the file in the quarantine folder back to its plain name in
        the areas folder, refused when that name is taken or the folder is gone."""
        areas = self._areas()
        src = op.src
        self._require_src(src, kinds=("file",))
        target = areas / op.dst
        try:
            folder = os.lstat(areas)
        except OSError:
            raise GuardError(
                "The rules' picture folder is gone, so the picture cannot go back."
            ) from None
        if stat.S_ISLNK(folder.st_mode) or not stat.S_ISDIR(folder.st_mode):
            raise GuardError(
                "the rules' areas folder is not a real folder (links are not followed)"
            )
        if os.path.lexists(target):
            raise GuardError(
                f"cannot put {op.dst!r} back: a picture with that name is already in the"
                " rules' areas folder"
            )
        disk = self.sim.disk_path(src)
        copy = disk is not None and not primitives.same_disk(areas, disk)
        self.out.append(
            ResolvedOp(
                op.kind,
                src,
                f"{ABS_TARGET}{target}",
                None,
                COPY_BACK_NOTE if copy else None,
                method=PICTURE_COPY if copy else PICTURE_RENAME,
            )
        )
        if not copy:  # a copy back leaves the file in the quarantine folder
            self.sim.events.append(("remove", src))

    def _resolve_one(self, op: Op) -> None:
        paths = self.paths
        match op.kind:
            case OpKind.RENAME:
                self._relocate(op, parent(op.src))
            case OpKind.MOVE:
                self._relocate(op, canonical(op.dst, paths))
            case OpKind.QUARANTINE:
                self._relocate(op, self._quarantine_folder(op.src))
            case OpKind.MKDIR:
                folder = self.sim.spell(canonical(op.dst, paths))
                if op.exact and self.sim.kind(folder) is not None:
                    # undo of REMOVE_EMPTY_DIR: put back a new folder, never reuse one
                    raise GuardError(f"cannot restore {folder!r}: the path is occupied")
                self._ensure_folder(folder, op.allow_top_level)
            case OpKind.COPY:
                folder = self.sim.spell(canonical(op.dst, paths))
                if self.sim.kind(folder) != "dir":
                    raise GuardError(
                        f"The folder {folder!r} does not exist yet, so there is nowhere to"
                        " copy the file to. Create the archive's special folders first."
                    )
                within = not _outside(op)
                if within:  # a file already in the archive: a plain file, never a link
                    self._require_src(op.src, kinds=("file",))
                wanted = op.name or PurePosixPath(op.src).name
                name = self.sim.free_name(folder, wanted)
                dst = join(folder, name)
                note = COLLISION_NOTE if name != wanted else None
                drive_id = self._drive_id(op.src) if within else None
                self.out.append(ResolvedOp(op.kind, op.src, dst, drive_id, note))
                self.sim.events.append(("create", dst, "file"))
            case OpKind.PICTURE_TO_QUARANTINE:
                self._picture_to_quarantine(op)
            case OpKind.PICTURE_BACK:
                self._picture_back(op)
            case OpKind.SYMLINK:
                outside = is_abs_target(op)  # only in undo restores (guards); never looked at
                if not outside:
                    self._require_src(op.src)
                link = canonical(op.dst, paths)
                folder = self.sim.spell(parent(link))
                self._ensure_folder(folder, op.allow_top_level)
                wanted = PurePosixPath(link).name
                name = self._free_or_exact(op, folder, wanted, None)
                dst = join(folder, name)
                note = COLLISION_NOTE if name != wanted else None
                drive_id = None if outside else self._drive_id(op.src)
                self.out.append(ResolvedOp(op.kind, op.src, dst, drive_id, note))
                self.sim.events.append(("create", dst, "link"))
            case OpKind.UNLINK_SYMLINK:
                self._require_src(op.src, kinds=("link",))
                # outside the publish roots only an undo gets here (guards): it names the
                # target the app made the link with
                outside_roots = self.paths.in_publish_root(op.src) is None
                self.out.append(
                    ResolvedOp(
                        op.kind,
                        op.src,
                        op.src,
                        expect_target=op.dst if outside_roots or op.exact else None,
                    )
                )
                self.sim.events.append(("remove", op.src))
            case OpKind.REMOVE_EMPTY_DIR:
                self._require_src(op.src, kinds=("dir",))
                # inside ##. Important the folder's own protection does not count
                # (guards.removal_protected); anything that started in a protected
                # path and was moved in this batch still does
                if removal_protected(op.src, self.paths) or self._moved_from_protected(op.src):
                    raise GuardError(f"{op.src!r} comes from a protected path")
                # Only Finder's own cache may go: exactly ".DS_Store", a file, on disk
                # before this batch (never one an earlier op created, moved or renamed).
                others = [
                    n
                    for n, k, untouched in self.sim.entries(op.src)
                    if not (n == DS_STORE and k == "file" and untouched)
                ]
                if others:
                    raise GuardError(
                        f"not empty: {op.src!r} holds {len(others)} entries"
                        f" (only a {DS_STORE} file may be removed with it)"
                    )
                drive_id = self._drive_id(op.src)
                self.out.append(
                    ResolvedOp(
                        op.kind, op.src, op.src, drive_id, identity=op.identity, made=op.made
                    )
                )
                self.sim.events.append(("remove", op.src))
