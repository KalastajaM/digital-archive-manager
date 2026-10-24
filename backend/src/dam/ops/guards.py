"""Path-level safety guards for operations (enforced here, never in the UI)."""

import os
import stat
from functools import lru_cache
from pathlib import Path, PurePosixPath

from dam.core.paths import ArchivePaths, OutsideArchiveError, nfc
from dam.ops.model import ABS_TARGET, GuardError, Op, OpKind
from dam.ops.primitives import DS_STORE

_NEEDS_SRC = {
    OpKind.RENAME,
    OpKind.MOVE,
    OpKind.SYMLINK,
    OpKind.UNLINK_SYMLINK,
    OpKind.QUARANTINE,
    OpKind.REMOVE_EMPTY_DIR,
}
_NEEDS_DST = {
    OpKind.RENAME,
    OpKind.MOVE,
    OpKind.MKDIR,
    OpKind.SYMLINK,
    OpKind.COPY,
    OpKind.PICTURE_TO_QUARANTINE,
    OpKind.PICTURE_BACK,
}


@lru_cache(maxsize=8192)
def fold_parts(rel: str) -> tuple[str, ...]:
    """Path components compared the way APFS does: NFC and case-insensitive. A pure
    function of the string, memoised: the planner's simulation compares the same
    few paths over and over (every op walks every earlier event)."""
    return tuple(nfc(p).casefold() for p in PurePosixPath(rel).parts)


def is_under(rel: str, base: str, strict: bool = False) -> bool:
    """True if ``rel`` is ``base`` or inside it (``strict``: inside only)."""
    r, b = fold_parts(rel), fold_parts(base)
    if strict and len(r) == len(b):
        return False
    return r[: len(b)] == b


def parent(rel: str) -> str:
    p = PurePosixPath(rel).parent.as_posix()
    return "" if p == "." else p


def rebase(rel: str, old: str, new: str) -> str:
    """``rel`` (at or under ``old``) re-expressed under ``new``."""
    rest = PurePosixPath(rel).parts[len(PurePosixPath(old).parts) :]
    return PurePosixPath(new, *rest).as_posix() if rest else new


def join(folder: str, name: str) -> str:
    return f"{folder}/{name}" if folder else name


def canonical(rel: str, paths: ArchivePaths) -> str:
    """Normalise ``rel`` (``a//b/./c`` -> ``a/b/c``) after checking it stays inside.

    Any failure to interpret the path (NUL byte, unresolvable, outside) is a GuardError.
    """
    if not isinstance(rel, str) or "\0" in rel:
        raise GuardError(f"{rel!r} is not a valid path.")
    try:
        paths.abs(rel)
    except (OutsideArchiveError, ValueError, OSError) as e:
        raise GuardError(str(e)) from None
    p = PurePosixPath(rel).as_posix()
    return "" if p == "." else p


def is_ds_store_name(name: str) -> bool:
    """``name`` folds (NFC, casefold) to ``.DS_Store``: reserved for Finder's own cache,
    the only file REMOVE_EMPTY_DIR deletes, so no operation may give that name."""
    return nfc(name).casefold() == DS_STORE.casefold()


def _check_not_ds_store(name: str) -> None:
    if is_ds_store_name(name):
        raise GuardError(f"The name {name!r} is reserved for Finder's .DS_Store file.")


def is_abs_target(op: Op) -> bool:
    """A SYMLINK whose target is the journal's ``abs:`` form (outside the archive)."""
    return op.kind is OpKind.SYMLINK and isinstance(op.src, str) and op.src.startswith(ABS_TARGET)


def _is_restore(op: Op, restore: bool) -> bool:
    """An exact op in a plan built by undo: the only ops the restore exceptions apply to."""
    return restore and op.exact


def _check_abs_target(op: Op, restore: bool) -> None:
    target = op.src[len(ABS_TARGET) :]
    if not _is_restore(op, restore):
        raise GuardError("A link to somewhere outside the archive is only allowed when undoing.")
    if "\0" in target or not os.path.isabs(target):
        raise GuardError(f"invalid link target {op.src!r}")


def _check_copy(op: Op, paths: ArchivePaths) -> None:
    """COPY: a file from anywhere on this computer (only read) into the inbox folder
    itself, under a plain file name. Never anywhere else in the archive."""
    if op.exact or op.allow_top_level or op.identity is not None or op.made:
        raise GuardError(f"{op.kind} takes only a source file, the inbox and a name")
    if not (isinstance(op.src, str) and op.src.startswith(ABS_TARGET)):
        raise GuardError("COPY needs the file to copy as an absolute path")
    source = op.src[len(ABS_TARGET) :]
    if "\0" in source or not os.path.isabs(source):
        raise GuardError(f"invalid file to copy {op.src!r}")
    if op.name is None:
        raise GuardError("COPY needs a file name")
    _check_name(op.name)
    _check_not_ds_store(op.name)
    if op.name.startswith(".") or op.name != op.name.strip() or "\\" in op.name:
        raise GuardError(f"{op.name!r} is not a usable file name")
    folder = canonical(op.dst, paths)
    if fold_parts(folder) != fold_parts(paths.inbox):
        raise GuardError(f"Files are only copied into {paths.inbox!r}.")


def _check_picture_name(name: str, what: str) -> None:
    _check_name(name)
    _check_not_ds_store(name)
    if (
        not name.endswith(".png")
        or name.startswith(".")
        or name != name.strip()
        or "\\" in name
        or len(name) > 240
    ):
        raise GuardError(f"{what} {name!r} is not the name of a picture file (a .png)")


def _check_picture_to_quarantine(op: Op, paths: ArchivePaths) -> None:
    """PICTURE_TO_QUARANTINE: a file of the rules' areas folder into the quarantine
    folder itself, under a plain name. Where that folder is, and that the file really is
    a regular file directly in it, is checked against the disk (``check_areas_source``)."""
    if op.exact or op.allow_top_level or op.identity is not None or op.made:
        raise GuardError(f"{op.kind} takes only a source file, the quarantine folder and a name")
    if not (isinstance(op.src, str) and op.src.startswith(ABS_TARGET)):
        raise GuardError(f"{op.kind} needs the picture file as an absolute path")
    source = op.src[len(ABS_TARGET) :]
    if "\0" in source or not os.path.isabs(source):
        raise GuardError(f"invalid picture file {op.src!r}")
    if op.name is None:
        raise GuardError(f"{op.kind} needs a file name")
    _check_picture_name(op.name, "The name")
    _check_picture_name(Path(source).name, "The file")
    folder = canonical(op.dst, paths)
    if fold_parts(folder) != fold_parts(paths.quarantine):
        raise GuardError(f"Pictures are only moved into {paths.quarantine!r}.")


def _check_picture_back(op: Op, paths: ArchivePaths, restore: bool) -> None:
    """PICTURE_BACK: only an undo (``restore`` and ``exact``) puts a picture back, from
    inside the quarantine folder to a plain name in the areas folder."""
    if not _is_restore(op, restore):
        raise GuardError("Only an undo puts a picture back into the rules' areas folder.")
    if op.allow_top_level or op.identity is not None or op.made or op.name is not None:
        raise GuardError(f"{op.kind} takes only a source file and a picture name")
    if op.src is None:
        raise GuardError(f"{op.kind} needs a source")
    src = canonical(op.src, paths)
    if not is_under(src, paths.quarantine, strict=True):
        raise GuardError(f"{src!r} is not in the quarantine folder")
    _check_picture_name(PurePosixPath(src).name, "The file")
    _check_picture_name(op.dst, "The name")


def fold_parts_of(p: Path) -> tuple[str, ...]:
    """``fold_parts`` for an absolute disk path."""
    return tuple(nfc(x).casefold() for x in Path(p).parts)


def check_areas_source(source: Path, areas_dir: Path) -> None:
    """Disk check for PICTURE_TO_QUARANTINE (planning and again right before acting):
    ``source`` is a regular file (not a link) directly inside ``areas_dir``, which is a
    real folder (not a link) and the very folder the executor was told about."""
    if fold_parts_of(source.parent) != fold_parts_of(areas_dir):
        raise GuardError(f"{source.name} is not directly inside the rules' areas folder")
    try:
        folder = os.lstat(areas_dir)
        st = os.lstat(source)
    except FileNotFoundError:
        raise GuardError(f"{source.name} is not in the rules' areas folder") from None
    except OSError as e:
        raise GuardError(f"cannot read {source.name}: {e.strerror}") from None
    if stat.S_ISLNK(folder.st_mode) or not stat.S_ISDIR(folder.st_mode):
        raise GuardError("the rules' areas folder is not a real folder (links are not followed)")
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise GuardError(f"{source.name} is not a plain file (links are not followed)")
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if reparse and (
        getattr(st, "st_file_attributes", 0) & reparse
        or getattr(folder, "st_file_attributes", 0) & reparse
    ):
        raise GuardError(f"{source.name} is not a plain file (links are not followed)")


def _check_name(name: str) -> None:
    if not isinstance(name, str) or name in ("", ".", "..") or "/" in name or "\0" in name:
        raise GuardError(f"{name!r} is not a valid name.")


def _check_not_top(rel: str, op: Op, paths: ArchivePaths, what: str) -> None:
    if paths.is_root(rel):
        raise GuardError(f"{what} is the archive root")
    if paths.is_top_level(rel) and not op.allow_top_level:
        raise GuardError(f"{what} {rel!r} is a top-level folder (needs allow_top_level)")


def touches_protected(rel: str, paths: ArchivePaths) -> bool:
    """``rel`` is protected or contains a protected path."""
    return paths.is_protected(rel) or any(
        is_under(prot, rel) for prot in paths.settings.protected_paths
    )


def removal_protected(rel: str, paths: ArchivePaths) -> bool:
    """``touches_protected`` for a removal inside a publish root: the ``important``
    special folder's own protection (it is protected against quarantine, as every
    protected path) does not refuse removing the app's own entries inside it, but any
    other protected path does, also one configured inside ``##. Important``."""
    important = fold_parts(paths.important)
    others = [p for p in paths.settings.protected_paths if fold_parts(p) != important]
    return any(is_under(rel, prot) or is_under(prot, rel) for prot in others)


def _check_removal_root(src: str, paths: ArchivePaths, what: str) -> None:
    """The one place a removal may happen: strictly inside ``##. Ongoing`` or
    ``##. Important`` (never either root itself, never anywhere else), and not at or
    inside another protected path."""
    if paths.in_publish_root(src) is None:
        raise GuardError(
            f"only {what} inside {paths.ongoing!r} or {paths.important!r} can be removed"
        )
    if removal_protected(src, paths):
        raise GuardError(f"{src!r} is protected and cannot be removed")


def validate(op: Op, paths: ArchivePaths, *, restore: bool = False) -> None:
    """Raise ``GuardError`` if ``op`` is not allowed. Path policy only, no disk access.

    ``restore`` is set only by ``dam.ops.undo`` (never derived from ``Plan.origin``);
    with it and ``op.exact`` two restore-only exceptions apply: an ``abs:`` SYMLINK
    target, and a MOVE of a top-level item back into the root (``allow_top_level``
    still required).
    """
    if op.kind is OpKind.REMOVE_EMPTY_DIR and (
        op.dst is not None or op.name is not None or op.exact or op.allow_top_level
    ):
        raise GuardError(f"{op.kind} takes only a source folder")
    if op.made and (op.kind is not OpKind.REMOVE_EMPTY_DIR or not restore):
        raise GuardError("Only an undo may remove a folder the app made.")
    if op.made and op.identity is None:
        raise GuardError("A folder the app made is removed only with its recorded identity.")
    if op.identity is not None and op.kind is not OpKind.REMOVE_EMPTY_DIR:
        raise GuardError(f"{op.kind} does not take an identity (only REMOVE_EMPTY_DIR does)")
    if op.kind in _NEEDS_SRC and op.src is None:
        raise GuardError(f"{op.kind} needs a source")
    if op.kind in _NEEDS_DST and op.dst is None:
        raise GuardError(f"{op.kind} needs a destination")
    if op.name is not None:
        if op.kind not in (OpKind.MOVE, OpKind.COPY, OpKind.PICTURE_TO_QUARANTINE):
            raise GuardError(f"{op.kind} does not take a name (only MOVE and COPY do)")
        _check_name(op.name)
    if op.kind is OpKind.COPY:
        _check_copy(op, paths)
        return
    if op.kind is OpKind.PICTURE_TO_QUARANTINE:
        _check_picture_to_quarantine(op, paths)
        return
    if op.kind is OpKind.PICTURE_BACK:
        _check_picture_back(op, paths, restore)
        return

    if is_abs_target(op):
        _check_abs_target(op, restore)  # only read (the link points there); never changed
        src = None
    else:
        src = canonical(op.src, paths) if op.kind in _NEEDS_SRC else None
    if src is not None:
        if paths.is_root(src):
            raise GuardError("The archive folder itself cannot be changed.")
        if op.kind is not OpKind.SYMLINK and not op.made:  # a link target is only read
            _check_not_top(src, op, paths, "source")

    match op.kind:
        case OpKind.RENAME:
            _check_name(op.dst)
            _check_not_ds_store(op.dst)
            canonical(join(parent(src), op.dst), paths)
        case OpKind.MOVE:
            folder = canonical(op.dst, paths)
            # Never into the root, even with allow_top_level, except an undo putting a
            # top-level item back where the journal says it was.
            if paths.is_root(folder) and not _is_restore(op, restore):
                raise GuardError("Files cannot go directly in the archive folder.")
            final = join(folder, op.name or PurePosixPath(src).name)
            _check_not_ds_store(PurePosixPath(final).name)
            canonical(final, paths)
            _check_not_top(final, op, paths, "destination")
            if is_under(folder, src):
                raise GuardError(f"{src!r} cannot be moved into itself.")
            if is_under(folder, paths.quarantine) and touches_protected(src, paths):
                raise GuardError(f"{src!r} is protected and cannot be quarantined")
        case OpKind.MKDIR:
            if paths.is_root(canonical(op.dst, paths)):
                raise GuardError("A folder cannot be made directly as the archive folder.")
        case OpKind.SYMLINK:
            link = canonical(op.dst, paths)
            _check_not_ds_store(PurePosixPath(link).name)
            _check_not_top(link, op, paths, "link")
        case OpKind.UNLINK_SYMLINK:
            _check_removal_root(src, paths, "links")
        case OpKind.QUARANTINE:
            if touches_protected(src, paths):
                raise GuardError(f"{src!r} is protected and cannot be quarantined")
            if is_under(src, paths.quarantine):
                raise GuardError(f"{src!r} is already in quarantine")
        case OpKind.REMOVE_EMPTY_DIR:
            # The one folder removal: strictly inside a publish root (``##. Ongoing``
            # or ``##. Important``; never the root itself), at any depth since
            # collection groups became subfolders. That it is a real, empty folder is
            # checked by the planner's simulation and again by the primitive at act
            # time (component by component, no symlink followed). Any empty folder
            # inside a root is accepted here: that it is one the app created is the
            # caller's job (the publisher removes only folders whose identity it
            # recorded in ongoing_entries).
            if op.made:
                # a folder a user-confirmed New folder / layout batch made (undo only):
                # anywhere in the archive, but never inside the app's own areas, and the
                # protection of ##. Important itself does not keep its own empty folder
                if (
                    paths.in_publish_root(src) is not None
                    or is_under(src, paths.quarantine, strict=True)
                    or removal_protected(src, paths)
                ):
                    raise GuardError(f"{src!r} cannot be removed here")
            else:
                _check_removal_root(src, paths, "folders")
