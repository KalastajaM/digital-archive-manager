"""Filesystem primitives. None of them deletes or overwrites anything.

The two exceptions to "no delete" are ``unlink_symlink``, which removes only a
symbolic link that lives inside the given publish root (``##. Ongoing`` or
``##. Important``; never its target), and ``remove_empty_dir``, which removes only an
empty folder strictly inside that root (at any depth, never the root itself) after
deleting its genuine Finder ``.DS_Store`` file. A third, ``remove_moved_picture``, removes
dam's own copy of a rule picture in its settings folder (never an archive file) after the
picture was copied to the archive and the copy was verified. Each call names one root; the
executor passes the root the path lies in (``ArchivePaths.in_publish_root``), and
nothing else is ever passed.
"""

import ctypes
import ctypes.util
import errno
import functools
import hashlib
import os
import secrets
import shutil
import stat
import sys
from collections.abc import Callable
from pathlib import Path

try:  # not installed on Windows
    import xattr
except ImportError:  # pragma: no cover - platform dependent
    xattr = None

from dam.core.fs import readlink, resolve
from dam.core.paths import nfc
from dam.ops.identity import Identity, of_fd, of_stat
from dam.ops.identity import same_object as same_identity
from dam.ops.model import GuardError, OpFailed

RENAME_EXCL = 0x4  # macOS renamex_np
RENAME_NOREPLACE = 0x1  # Linux renameat2
_AT_FDCWD = -100
MAX_COPY_BYTES = 200 * 1024 * 1024  # one file copied into the archive (add / upload)
_COPY_CHUNK = 1024 * 1024
_COPY_FREE_MARGIN = 16 * 1024 * 1024  # left free on the disk after a copy
_NOT_SUPPORTED = {errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)}
# renameat2 answers EINVAL for a file system without RENAME_NOREPLACE, ENOSYS on an old kernel
_NOT_SUPPORTED_LINUX = _NOT_SUPPORTED | {errno.EINVAL, errno.ENOSYS}


def _load_renamex_np():
    if sys.platform != "darwin":  # renamex_np is a macOS call
        return None
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        fn = libc.renamex_np
    except (OSError, AttributeError):
        return None
    fn.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    fn.restype = ctypes.c_int
    return fn


_renamex_np = _load_renamex_np()


def _load_renameat2():
    if not sys.platform.startswith("linux"):  # renameat2 is a Linux call
        return None
    try:
        fn = ctypes.CDLL(None, use_errno=True).renameat2  # glibc 2.28 and later
    except (OSError, AttributeError):
        return None
    fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    fn.restype = ctypes.c_int
    return fn


_renameat2 = _load_renameat2()


def _rename_exclusive(src: Path, dst: Path) -> bool:
    """The system's own no-overwrite rename (macOS ``renamex_np(RENAME_EXCL)``, Linux
    ``renameat2(RENAME_NOREPLACE)``); False when there is none or the volume does not
    support it, so the caller falls back."""
    old, new = os.fsencode(src), os.fsencode(dst)
    if _renamex_np is not None:
        rc, unsupported = _renamex_np(old, new, RENAME_EXCL), _NOT_SUPPORTED
    elif _renameat2 is not None:
        rc = _renameat2(_AT_FDCWD, old, _AT_FDCWD, new, RENAME_NOREPLACE)
        unsupported = _NOT_SUPPORTED_LINUX
    else:
        return False
    if rc == 0:
        return True
    err = ctypes.get_errno()
    if err == errno.EEXIST:
        raise FileExistsError(err, os.strerror(err), str(dst))
    if err not in unsupported:
        raise OSError(err, os.strerror(err), str(src))
    return False


def rename_excl(src: Path, dst: Path) -> None:
    """Rename ``src`` to ``dst`` atomically, failing with FileExistsError if dst exists."""
    if _rename_exclusive(src, dst):
        return
    # On Windows os.rename() itself never replaces an existing entry (it raises
    # FileExistsError), so the check below only gives the same error early.
    # CHECK-THEN-ACT WINDOW (macOS and Linux): something created at ``dst`` between the
    # lexists() check and os.rename() would be replaced. Reached only where the system
    # has no exclusive rename for this volume: a macOS volume that refuses RENAME_EXCL
    # (some exFAT, FAT and network volumes), a Linux file system without
    # RENAME_NOREPLACE, or a C library without renameat2. An archive folder can be on
    # such a disk.
    if os.path.lexists(dst):
        raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), str(dst))
    os.rename(src, dst)


def rename_case_only(src: Path, dst: Path) -> None:
    """Rename an entry to a case/Unicode-normalisation variant of its own name.

    On a case-insensitive volume ``dst`` already "exists" (it is the same entry), so
    RENAME_EXCL would report EEXIST. This is allowed only when ``dst`` is provably the
    same entry: same folded path, same inode (``lstat``: symlinks are not followed,
    the no-follow equivalent of ``os.path.samefile``) and, for non-directories, no
    other hard link (a second hard link would make ``rename`` a silent no-op).
    """
    if _fold_parts(src) != _fold_parts(dst):
        raise FileExistsError(errno.EEXIST, "not a case-only rename", str(dst))
    st_src, st_dst = os.lstat(src), os.lstat(dst)
    if not os.path.samestat(st_src, st_dst):
        raise FileExistsError(errno.EEXIST, "destination is a different entry", str(dst))
    if not stat.S_ISDIR(st_src.st_mode) and st_src.st_nlink != 1:
        raise FileExistsError(errno.EEXIST, "source has other hard links", str(dst))
    # CHECK-THEN-ACT WINDOW: if, between these checks and os.rename(), the entry is
    # replaced by a different one under the other spelling, os.rename() would replace
    # it. This needs a concurrent writer racing a case-only rename of the same name;
    # there is no exclusive variant (RENAME_EXCL reports EEXIST for the same entry).
    os.rename(src, dst)


DIFFERENT_DISKS = (
    "The rules' picture folder and the archive are on different disks, so the file cannot be "
    "renamed into place; it is copied instead."
)


def different_disks_message(a: str, b: str) -> str:
    """Why a move between the archive folders labelled ``a`` and ``b`` (``""``: the main
    folder) is refused: they are on different disks, and outside a move the owner makes
    by hand (``Plan.copy_across``) a move is only a rename."""
    first, second = ("the main folder" if not x else f"'{x}'" for x in (a, b))
    text = (
        f"{first} and {second} are on different disks, so this cannot be moved between them"
        " here."
    )
    return text[0].upper() + text[1:]


PICTURE_RENAME = "rename"
PICTURE_COPY = "copy"
# COPY_ACROSS of a folder move: the destination already holds the file (same size and
# mtime, planned); at act time both hashes are compared and nothing is written
PRESENT = "present"


def move_between_folders(src: Path, dst: Path) -> None:
    """Move the file ``src`` to the new name ``dst`` without overwriting (``rename_excl``).
    Only a rename: on different disks that cannot work (``OpFailed`` says so and the file
    is left where it is); a rule picture crossing disks takes ``copy_picture`` instead."""
    try:
        rename_excl(src, dst)
    except FileExistsError:
        raise
    except OSError as e:
        if e.errno == errno.EXDEV or getattr(e, "winerror", None) == 17:
            raise OpFailed(DIFFERENT_DISKS) from None
        raise


def file_sha256(path: Path, stop: Callable[[], bool] | None = None) -> str:
    """The sha256 of the regular file ``path`` (a link is refused, not followed).
    ``stop`` (looked at between chunks) true ends the reading, as a failure."""
    if not stat.S_ISREG(os.lstat(path).st_mode):
        raise OpFailed(f"{path.name} is not a plain file.")
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_COPY_CHUNK):
            digest.update(chunk)
            if stop is not None and stop():
                raise OpFailed("stopped")
    return digest.hexdigest()


def copy_verified(
    src: Path,
    dst: Path,
    sha256: str,
    limit: int | None = MAX_COPY_BYTES,
    stop: Callable[[], bool] | None = None,
    hash_source: bool = True,
    on_bytes: Callable[[int], None] | None = None,
) -> None:
    """Copy ``src`` to the new file ``dst`` (exclusive create, fsync, ``copy_file``),
    then check that ``dst`` has the size and sha256 of ``src`` and that both are
    ``sha256`` (the hash journaled before). ``src`` is only read. On any failure nothing
    is removed: ``dst`` may remain, ``src`` stays. ``hash_source`` False: ``sha256`` was
    read from ``src`` just before (a copy across disks), so ``src`` is not read a second
    time; a change while copying still shows, as a copy that does not match.
    ``on_bytes``: see ``copy_file``."""
    if hash_source and file_sha256(src, stop) != sha256:
        raise OpFailed(f"{src.name} changed since it was planned, so it is not copied.")
    size = copy_file(src, dst, limit=limit, stop=stop, on_bytes=on_bytes)
    if os.lstat(dst).st_size != size or file_sha256(dst, stop) != sha256:
        raise OpFailed(
            f"The copy {dst.name} does not match {src.name}. Both files stay where they are;"
            " dam never deletes: remove the copy yourself."
        )


copy_picture = copy_verified  # a rule picture crossing disks

TEMP_COPY_PREFIX = ".dam-copy-"  # a copy across disks before it is verified and named
TEMP_COPY_EXTRA = len(TEMP_COPY_PREFIX) + 9  # the prefix, 8 hex digits and "-"
NAME_MAX_BYTES = 255  # the longest name macOS, Linux and Windows volumes all take


def temp_copy_name(name: str) -> str:
    """The temporary name a copy across disks of ``name`` is written under."""
    return f"{TEMP_COPY_PREFIX}{secrets.token_hex(4)}-{name}"


def temp_copy_too_long(name: str) -> int:
    """How many bytes (UTF-8) too long ``name`` is for its temporary copy name; 0 when
    it fits."""
    return max(0, len(name.encode("utf-8")) + TEMP_COPY_EXTRA - NAME_MAX_BYTES)


def copy_across(
    src: Path,
    dst: Path,
    sha256: str,
    stop: Callable[[], bool] | None = None,
    on_bytes: Callable[[int], None] | None = None,
) -> None:
    """Copy the archive file ``src`` to the new file ``dst`` in a folder on another disk:
    written under a temporary name next to ``dst`` (``TEMP_COPY_PREFIX``), verified by
    size and sha256 (``copy_verified``, no size cap), given the source's access and
    modification times, and only then renamed to ``dst`` without overwriting. ``src`` is
    only read. On any failure nothing is removed and the error names the temporary file
    that may remain. ``on_bytes``: see ``copy_file``."""
    temp = dst.parent / temp_copy_name(dst.name)
    try:
        copy_verified(
            src, temp, sha256, limit=None, stop=stop, hash_source=False, on_bytes=on_bytes
        )
        st = os.stat(src)
        os.utime(temp, ns=(st.st_atime_ns, st.st_mtime_ns))
        rename_excl(temp, dst)
    except (OSError, OpFailed) as e:
        left = f" The unfinished copy {temp.name} may remain." if os.path.lexists(temp) else ""
        raise OpFailed(f"{src.name} was not copied to {dst.name} ({e}).{left}") from None


SF_DATALESS = 0x40000000  # macOS: a cloud file whose content is not on this computer


def is_dataless(path: Path) -> bool:
    """A cloud-drive file that is evicted (macOS ``SF_DATALESS``): reading it downloads
    it. Always False where the flag does not exist."""
    return bool(getattr(os.stat(path), "st_flags", 0) & SF_DATALESS)


def remove_moved_picture(source: Path, areas_dir: Path, copy: Path, sha256: str) -> None:
    """Remove the rule picture ``source`` after it was copied to ``copy`` and the copy was
    verified. This is dam's own app-made file, never an archive file. It is removed only
    if ``source`` is a regular file (not a link) directly inside ``areas_dir`` (a real
    folder, not a link), ``copy`` is a different regular file, and both have the content
    hash ``sha256``. Anything else is refused and both files stay."""
    if _fold_parts(resolve(source.parent, strict=True)) != _fold_parts(
        resolve(areas_dir, strict=True)
    ) or stat.S_ISLNK(os.lstat(areas_dir).st_mode):
        raise GuardError(f"{source.name} is not directly inside the rules' picture folder")
    st, st_copy = os.lstat(source), os.lstat(copy)
    if not stat.S_ISREG(st.st_mode) or not stat.S_ISREG(st_copy.st_mode):
        raise GuardError(f"{source.name} and its copy must both be plain files")
    if os.path.samestat(st, st_copy):
        raise GuardError(f"{source.name} and its copy are the same file")
    if file_sha256(source) != sha256 or file_sha256(copy) != sha256:
        raise GuardError(f"{source.name} and its copy are not the same content; both stay")
    # CHECK-THEN-ACT WINDOW: the file could be swapped between the hash and unlink(); the
    # worst case is dam's own crop in its own settings folder, which unlink() of a
    # folder or link cannot reach (a link is removed itself, never its target).
    source.unlink()


def same_disk(a: Path, b: Path) -> bool:
    """``a`` and ``b`` (existing entries) are on the same disk, so one can be renamed
    into the other's folder."""
    return os.stat(a).st_dev == os.stat(b).st_dev


def make_dir(p: Path) -> None:
    p.mkdir(parents=False, exist_ok=False)


def has_room(folder: Path, size: int) -> bool:
    """The disk that holds ``folder`` has room for ``size`` more bytes and still keeps
    the margin every copy leaves free."""
    return shutil.disk_usage(folder).free >= size + _COPY_FREE_MARGIN


def copy_file(
    src: Path,
    dst: Path,
    limit: int | None = MAX_COPY_BYTES,
    stop: Callable[[], bool] | None = None,
    on_bytes: Callable[[int], None] | None = None,
) -> int:
    """Copy the regular file ``src`` to the new file ``dst`` (created exclusively: an
    existing name, also a link, is an error, so nothing is ever overwritten); returns
    the bytes copied. ``src`` is only read. A file over ``limit`` bytes, or a disk
    without room for it, is refused before ``dst`` is created. ``limit`` None: no cap,
    only the free-space check. ``stop`` (looked at between chunks) true ends the copy
    there, as a failure. ``on_bytes`` is called after each chunk with the bytes written
    so far (the progress of a large file).

    If the copy is cut short after ``dst`` was created (the disk filled up, the source
    shrank), a partial file stays: the app never deletes, so the error says so."""
    with open(src, "rb") as source:
        st = os.fstat(source.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise OpFailed(f"{src.name} is not a regular file.")
        if limit is not None and st.st_size > limit:
            raise OpFailed(f"{src.name} is larger than {limit // (1024 * 1024)} MB.")
        if not has_room(dst.parent, st.st_size):
            raise OpFailed("There is not enough free space on the disk for this file.")
        copied = 0
        with open(dst, "xb") as target:
            try:
                while chunk := source.read(_COPY_CHUNK):
                    copied += len(chunk)
                    if limit is not None and copied > limit:
                        raise OpFailed(f"{src.name} is larger than {limit // (1024 * 1024)} MB.")
                    target.write(chunk)
                    if on_bytes is not None:
                        on_bytes(copied)
                    if stop is not None and stop():
                        raise OpFailed("stopped")
                target.flush()
                os.fsync(target.fileno())
            except (OSError, OpFailed) as e:
                raise OpFailed(
                    f"The copy of {src.name} stopped part way ({e}); an incomplete file"
                    f" {dst.name} may remain. dam never deletes: remove it yourself."
                ) from None
    return copied


WINDOWS_LINK_REFUSAL = (
    "Windows needs Developer Mode to create links; enable it or turn off showing "
    "collections in ##. Ongoing"
)


def _is_windows() -> bool:
    return sys.platform == "win32"


@functools.cache
def can_make_links() -> bool:
    """Whether this computer lets the app make links (symbolic links). Always on macOS and
    Linux; on Windows only with Developer Mode (or an administrator), tried once in the
    system's temporary folder (never in the archive)."""
    if not _is_windows():
        return True
    import tempfile

    try:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target.txt"
            target.write_bytes(b"")
            os.symlink(target, Path(tmp) / "link.txt")
    except OSError:
        return False
    return True


def make_symlink(target: Path, link: Path) -> None:
    """Create ``link`` pointing at ``target``; fails if ``link`` exists."""
    try:
        if _is_windows():
            if (link.parent / target).is_dir():  # Windows makes folder links differently
                os.symlink(target, link, target_is_directory=True)
            else:
                os.symlink(target, link)
        else:
            os.symlink(target, link)
    except OSError as e:
        # WinError 1314: the process lacks the privilege to create symbolic links
        if _is_windows() and (
            getattr(e, "winerror", None) == 1314 or isinstance(e, PermissionError)
        ):
            raise OpFailed(WINDOWS_LINK_REFUSAL) from None
        raise


def _fold_parts(p: Path) -> tuple[str, ...]:
    return tuple(nfc(x).casefold() for x in Path(p).parts)


def unlink_symlink(link: Path, root_dir: Path, expected_target: str | None = None) -> None:
    """Remove the symbolic link ``link`` if, and only if, it lives inside ``root_dir``
    (a publish root: ``##. Ongoing`` or ``##. Important``; for an undo of a Link drop,
    the archive folder). ``expected_target``: the link must point exactly there (what
    the app made it with), else it is left alone."""
    if not link.is_symlink():
        raise GuardError(f"{link} is not a symbolic link")
    if expected_target is not None and readlink(link) != expected_target:
        raise GuardError(f"{link} points somewhere else now")
    try:
        if not stat.S_ISDIR(os.lstat(root_dir).st_mode):  # lstat: a link is refused
            raise GuardError(f"{root_dir} is not a real folder")
        real_parent = _fold_parts(resolve(link.parent, strict=True))
        root = _fold_parts(resolve(root_dir, strict=True))
    except (OSError, RuntimeError):
        raise GuardError(f"cannot resolve {link}") from None
    if real_parent[: len(root)] != root:
        raise GuardError(f"{link} is not inside {root_dir}")
    # CHECK-THEN-ACT WINDOW: between these checks and unlink() another process could
    # swap the link for a regular file or re-point a parent folder. Python has no
    # unlinkat(O_NOFOLLOW)-style call; the re-check below keeps the window minimal,
    # and unlink() on a directory fails rather than removing it.
    if not link.is_symlink():  # re-check right before acting
        raise GuardError(f"{link} is not a symbolic link")
    if expected_target is not None and readlink(link) != expected_target:
        raise GuardError(f"{link} points somewhere else now")
    link.unlink()


DS_STORE = ".DS_Store"  # Finder's cache: the only entry remove_empty_dir deletes
FINDER_MAGIC = b"\x00\x00\x00\x01Bud1"  # first bytes of every Finder .DS_Store
DRIVE_ID_PREFIX = "com.google.drivefs.item-id"  # any Drive id xattr: a synced document
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
# Windows cannot open a folder or address a name relative to an open folder (dir_fd)
_HAS_DIR_FD = os.open in os.supports_dir_fd


def _check_finder_cache(dir_fd: int) -> None:
    """Refuse unless ``.DS_Store`` in ``dir_fd`` is a genuine Finder cache: a regular
    file (no link), no other hard link, Finder's magic header, no Drive id."""
    st = os.lstat(DS_STORE, dir_fd=dir_fd)
    if not stat.S_ISREG(st.st_mode):
        raise GuardError(f"{DS_STORE} is not a regular file")
    if st.st_nlink != 1:
        raise GuardError(f"{DS_STORE} has other hard links")
    fd = os.open(DS_STORE, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
    try:
        if not os.path.samestat(os.fstat(fd), st):
            raise GuardError(f"{DS_STORE} changed while being checked")
        if os.read(fd, len(FINDER_MAGIC)) != FINDER_MAGIC:
            raise GuardError(f"{DS_STORE} is not a Finder file (no Finder header)")
        if xattr is not None and any(a.startswith(DRIVE_ID_PREFIX) for a in xattr.listxattr(fd)):
            raise GuardError(f"{DS_STORE} is a Google Drive item")
    finally:
        os.close(fd)


def finder_cache_problem(folder: Path) -> str | None:
    """Read only: why ``remove_empty_dir`` would refuse the ``.DS_Store`` in ``folder``
    (None if it is a genuine Finder cache). Lets a caller skip a removal that is bound
    to fail instead of journaling a failed operation; the act-time checks still run."""
    if not _HAS_DIR_FD:  # no file descriptors on folders: a .DS_Store cannot be vetted
        if os.path.lexists(folder / DS_STORE):
            return f"{DS_STORE} cannot be checked on this platform"
        return None
    try:
        fd = os.open(folder, _DIR_FLAGS)
    except OSError as e:
        return f"cannot open {folder}: {e.strerror}"
    try:
        _check_finder_cache(fd)
    except GuardError as e:
        return str(e)
    except OSError as e:
        return f"cannot read {DS_STORE}: {e.strerror}"
    finally:
        os.close(fd)
    return None


def _parts_inside(path: Path, root_dir: Path) -> list[str]:
    """The components of ``path`` below ``root_dir`` (at least one), by folded
    prefix; ``GuardError`` for the root itself, anything outside it, or a ``.``/``..``
    component (never normalised away: the path must name the folder plainly)."""
    parts, base = Path(path).parts, _fold_parts(root_dir)
    inside = list(parts[len(base) :])
    if (
        _fold_parts(Path(*parts[: len(base)])) != base
        or not inside
        or any(c in ("", ".", "..") for c in inside)
    ):
        raise GuardError(f"{path} is not strictly inside {root_dir}")
    return inside


def remove_empty_dir(path: Path, root_dir: Path, identity: Identity | None = None) -> None:
    """Remove the folder ``path`` if, and only if, it sits strictly inside
    ``root_dir`` (a publish root, ``##. Ongoing`` or ``##. Important``; at any depth,
    never ``root_dir`` itself), holds nothing but
    a genuine Finder ``.DS_Store`` (deleted first) and, when ``identity`` is given, is
    still the folder with that identity (``dev``/``ino`` only; the birth time is not
    compared, since Google Drive re-writes new folders, see ``identity.same_object``)
    (checked on the opened fd: a folder swapped in since it was planned is refused,
    nothing removed).

    Anything else in it (another name, a case variant, a subfolder, a ``.DS_Store``
    that is a folder, a link, hard-linked, without Finder's header or carrying a Drive
    id) is a ``GuardError`` and nothing at all is removed. Never recursive, never
    retried. All work goes through file descriptors opened with O_NOFOLLOW, component
    by component from ``root_dir``, so a folder on the way (or the root itself)
    swapped for a symlink is refused instead of followed.
    """
    inside = _parts_inside(path, root_dir)
    name = inside[-1]
    if not _HAS_DIR_FD:
        _remove_empty_dir_by_path(path, root_dir, inside, identity)
        return
    try:
        if not stat.S_ISDIR(os.lstat(root_dir).st_mode):  # lstat: a link is refused
            raise GuardError(f"{root_dir} is not a real folder")
        # Belt and braces for the per-component O_NOFOLLOW opens below: resolving the
        # parent must stay on the plain path (no link anywhere on the way).
        if _fold_parts(resolve(path.parent, strict=True)) != _fold_parts(
            resolve(root_dir, strict=True).joinpath(*inside[:-1])
        ):
            raise GuardError(f"{path} is not strictly inside {root_dir}")
    except (OSError, RuntimeError):
        raise GuardError(f"cannot resolve {path}") from None
    try:
        pfd = os.open(root_dir, _DIR_FLAGS)
    except OSError as e:
        raise GuardError(f"cannot open {root_dir}: {e.strerror}") from None
    try:
        for component in inside[:-1]:  # each a real folder, opened without following
            try:
                nfd = os.open(component, _DIR_FLAGS, dir_fd=pfd)
            except OSError as e:  # ELOOP: a symlink; ENOTDIR: not a folder
                raise GuardError(
                    f"{path}: {component!r} is not a real folder: {e.strerror}"
                ) from None
            os.close(pfd)
            pfd = nfd
        try:
            fd = os.open(name, _DIR_FLAGS, dir_fd=pfd)
        except OSError as e:  # ELOOP: a symlink; ENOTDIR: not a folder
            raise GuardError(f"{path} is not a real folder: {e.strerror}") from None
        try:
            st = os.fstat(fd)
            if identity is not None and not same_identity(identity, of_fd(fd)):
                raise GuardError(f"{path} is not the folder planned for removal (identity changed)")
            names = os.listdir(fd)
            others = [n for n in names if n != DS_STORE]
            if others:
                raise GuardError(f"not empty: {path} holds {len(others)} entries")
            # The fd's folder must still be the one named ``name`` in its parent (not
            # swapped for a link or another folder since it was opened).
            if not os.path.samestat(st, os.lstat(name, dir_fd=pfd)):
                raise GuardError(f"{path} changed while being checked")
            if names:
                _check_finder_cache(fd)
                # CHECK-THEN-ACT WINDOW: the checked .DS_Store could be swapped for
                # another file between the checks and unlinkat(). unlinkat() on the
                # folder fd removes only that one name (never a link's target, never a
                # folder), so the window needs a concurrent writer inside this folder.
                os.unlink(DS_STORE, dir_fd=fd)
        finally:
            os.close(fd)
        # CHECK-THEN-ACT WINDOW: the folder may be swapped or filled between the
        # samestat check and unlinkat(AT_REMOVEDIR). rmdir removes only an empty
        # directory (never a link: ENOTDIR, never recursively); anything written into
        # it in between makes it fail ENOTEMPTY.
        try:
            os.rmdir(name, dir_fd=pfd)
        except OSError as e:
            if e.errno in (errno.ENOTEMPTY, errno.EEXIST):
                raise GuardError(f"not empty: {path}") from None
            raise
    finally:
        os.close(pfd)


def _remove_empty_dir_by_path(
    path: Path, root_dir: Path, inside: list[str], identity: Identity | None
) -> None:
    """``remove_empty_dir`` for platforms without ``dir_fd`` (Windows): the same checks
    by path (``lstat`` on every component, no link followed), without the file-descriptor
    guarantees. Only an empty folder is removed; there is no ``.DS_Store`` to delete."""
    try:
        current = root_dir
        if not stat.S_ISDIR(os.lstat(current).st_mode):
            raise GuardError(f"{root_dir} is not a real folder")
        for component in inside:
            current = current / component
            st = os.lstat(current)
            if not stat.S_ISDIR(st.st_mode) or getattr(st, "st_file_attributes", 0) & getattr(
                stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
            ):
                raise GuardError(f"{path}: {component!r} is not a real folder")
        if identity is not None and not same_identity(identity, of_stat(st, path=current)):
            raise GuardError(f"{path} is not the folder planned for removal (identity changed)")
        names = os.listdir(path)
        if names:
            raise GuardError(f"not empty: {path} holds {len(names)} entries")
        os.rmdir(path)  # an empty folder only; never a link, never recursive
    except FileNotFoundError:
        raise GuardError(f"cannot resolve {path}") from None
    except OSError as e:
        if e.errno in (errno.ENOTEMPTY, errno.EEXIST):
            raise GuardError(f"not empty: {path}") from None
        raise
