"""Turn a Plan into ResolvedOps: validate, simulate sequentially, resolve collisions.

Nothing here touches the disk except to read it.
"""

import dataclasses
import os
import stat
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from dam.core.foldernames import FolderNameError, check_folder_name
from dam.core.naming import unique_name
from dam.core.paths import ArchivePaths, not_connected_message
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
from dam.ops.primitives import DS_STORE, PICTURE_COPY, PICTURE_RENAME, different_disks_message

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
MKDIR_NOTE = "create missing folder"


_UNREAD = object()


def _same(a: str, b: str) -> bool:
    return fold_parts(a) == fold_parts(b)


def _add_note(note: str | None, extra: str) -> str:
    return f"{note}; {extra}" if note else extra


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
        for entry in disk.iterdir():
            if fold_parts(entry.name) == want and self.kind(join(folder, entry.name)):
                return entry.name
        return None

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
        if self.locks.refused(disk, self._drive_id(src), entries, granted):
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
        self, folder: str, allow_top_level: bool, quarantine_root: bool = False
    ) -> None:
        """Plan MKDIRs for the missing components of ``folder``.

        A new top-level folder needs ``allow_top_level``. The one exception
        (``quarantine_root``, set only for QUARANTINE ops): the configured quarantine
        folder itself may be created, so marking for deletion works before it exists.
        (An extra folder's To Delete sits one level down, so it needs no exception.)
        """
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
            self.out.append(ResolvedOp(OpKind.MKDIR, None, sub, None, MKDIR_NOTE, made=self.made))
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
        self._require_src(src)
        self._check_locked(src)
        self._check_same_disk(src, folder)
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

    def _check_same_disk(self, src: str, folder: str) -> None:
        """A move between two archive folders is a rename, so it works only when both
        are on one disk: refused here, in the dry run, rather than half way."""
        a, b = self.paths.folder_of(src), self.paths.folder_of(folder)
        if a.label == b.label:
            return
        try:
            same = primitives.same_disk(a.root, b.root)
        except OSError:  # unplugged since check_connected looked
            gone = next((f for f in (a, b) if f.label and not os.path.isdir(f.root)), None)
            raise GuardError(not_connected_message(gone or (b if b.label else a))) from None
        if not same:
            raise OpFailed(different_disks_message(a.label, b.label))

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
