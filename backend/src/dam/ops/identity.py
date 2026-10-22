"""File identity: how the app tells that a folder or link is still the very one it
saw or made, and not one the user deleted and put back in its place.

An identity is ``(dev, ino, birth)``, all kept as text in the database (a Windows
file index is an unsigned 64-bit number or more and does not fit a SQLite INTEGER).

* ``dev`` / ``ino``: ``st_dev`` / ``st_ino``. Alone they are NOT enough: ext4, tmpfs
  and others hand a freed inode number straight to the next file created, so a folder
  deleted and recreated gets the same number.
* ``birth``: when this file system object was created, tagged with where it came from,
  so that two values are only ever compared when they mean the same thing:

  - ``b:<ns>``  the birth time. macOS and Windows ``st_birthtime``; Linux ``statx``
    ``stx_btime`` (read through libc with ctypes, since Python's ``os.stat`` has no
    birth time on Linux; ext4, xfs, btrfs and recent tmpfs report it).
  - ``c:<ns>``  Linux only, links only, when the file system reports no birth time:
    ``st_ctime_ns``. A link's inode is never written after creation, so its ctime is
    effectively its birth, and a recreated link always gets a new one. (A rename of
    the link also changes it; that only makes the app refuse, which is safe.)
  - absent: nothing better exists (a folder on a Linux file system without birth
    time). A folder's ctime is deliberately NOT used: it changes whenever an entry is
    added to or removed from the folder, so a folder the app made, filled and emptied
    again would never be removed. For such a folder the identity is ``(dev, ino)``
    alone: a delete-and-recreate that reuses the inode number is then not detected.
    Removal is still limited to empty folders inside the publish roots, so the worst
    case is the removal of an empty folder at a path the app owned.

Comparison (``same``): ``dev`` and ``ino`` must be equal. When the recorded identity
has a birth, the current one must have the same one: a different value, a different
source, or none at all means "not the same", never a match by default. A recorded
identity without a birth (a row from before migration 0024, or a platform that has
none) is compared on ``(dev, ino)`` only.
"""

from __future__ import annotations

import os
import stat
import struct
import sys
from typing import NamedTuple


class Identity(NamedTuple):
    dev: int
    ino: int
    birth: str | None = None

    def columns(self) -> dict[str, str | None]:
        """The values for the ``st_dev`` / ``st_ino`` / ``st_birth`` TEXT columns."""
        return {"st_dev": str(self.dev), "st_ino": str(self.ino), "st_birth": self.birth}


def from_columns(dev: object, ino: object, birth: object = None) -> Identity:
    return Identity(int(dev), int(ino), None if birth in (None, "") else str(birth))  # type: ignore[call-overload]


# -- birth time -------------------------------------------------------------------

_AT_FDCWD = -100
_AT_SYMLINK_NOFOLLOW = 0x100
_AT_EMPTY_PATH = 0x1000
_STATX_BTIME = 0x800
_STATX_BUF = 256
_BTIME_OFFSET = 80  # struct statx: stx_btime (i64 sec, u32 nsec, i32 pad)


def _statx_birth_ns(path: str | os.PathLike | None, fd: int | None) -> int | None:
    """``stx_btime`` in ns of ``path`` (not following a link) or of the open ``fd``;
    None when the kernel, libc or file system cannot say."""
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        statx = libc.statx
    except (OSError, AttributeError, ImportError):
        return None
    buf = ctypes.create_string_buffer(_STATX_BUF)
    statx.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.c_void_p,
    ]
    statx.restype = ctypes.c_int
    if fd is not None:
        rc = statx(fd, b"", _AT_EMPTY_PATH, _STATX_BTIME, buf)
    else:
        assert path is not None
        rc = statx(_AT_FDCWD, os.fsencode(path), _AT_SYMLINK_NOFOLLOW, _STATX_BTIME, buf)
    if rc != 0:
        return None
    mask = struct.unpack_from("=I", buf, 0)[0]
    if not mask & _STATX_BTIME:
        return None
    sec, nsec = struct.unpack_from("=qI", buf, _BTIME_OFFSET)
    return sec * 1_000_000_000 + nsec


def birth_of(
    st: os.stat_result, path: str | os.PathLike | None = None, fd: int | None = None
) -> str | None:
    """The tagged birth of the object ``st`` describes (see the module doc)."""
    ns = getattr(st, "st_birthtime_ns", None)
    if ns is None:
        bt = getattr(st, "st_birthtime", None)  # macOS, Windows (Python 3.12+)
        if bt is not None:
            ns = round(bt * 1_000_000_000)
    if ns is not None:
        return f"b:{ns}"
    if sys.platform.startswith("linux") and (path is not None or fd is not None):
        ns = _statx_birth_ns(path, fd)
        if ns is not None:
            return f"b:{ns}"
        if stat.S_ISLNK(st.st_mode):
            return f"c:{st.st_ctime_ns}"
    return None


def of_stat(
    st: os.stat_result, path: str | os.PathLike | None = None, fd: int | None = None
) -> Identity:
    """The identity of what ``st`` (an lstat/fstat result) describes; ``path`` or
    ``fd`` lets Linux ask the kernel for the birth time."""
    return Identity(st.st_dev, st.st_ino, birth_of(st, path, fd))


def of_path(path: str | os.PathLike) -> Identity:
    """Identity of the entry at ``path``, not following a link (OSError if missing)."""
    return of_stat(os.lstat(path), path=path)


def of_fd(fd: int) -> Identity:
    return of_stat(os.fstat(fd), fd=fd)


def same(recorded: Identity | tuple | None, current: Identity) -> bool:
    """``current`` is the recorded object. See the module doc for the rules."""
    if recorded is None:
        return False
    rec = recorded if isinstance(recorded, Identity) else Identity(*recorded)
    if (rec.dev, rec.ino) != (current.dev, current.ino):
        return False
    if rec.birth is None:
        return True
    return current.birth == rec.birth
