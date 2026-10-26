"""Path spelling helpers that behave the same on POSIX and Windows.

Windows hands back some paths in the extended form ``\\\\?\\C:\\dir`` (``readlink`` of a
link made with an absolute target, ``realpath`` of some inputs) and ``\\\\?\\UNC\\host\\share``
for network shares. The same folder is then spelled two ways, and a string or
``relative_to`` comparison says "outside". Every path read back from the disk goes
through here so that one spelling is used everywhere. On POSIX all of these are
no-ops. Nothing here loosens a check: both sides of a comparison are normalised the
same way, and a path that is not provably the same stays different.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

_EXT = "\\\\?\\"
_EXT_UNC = "\\\\?\\UNC\\"


def strip_extended(s: str) -> str:
    """``\\\\?\\C:\\x`` -> ``C:\\x`` and ``\\\\?\\UNC\\h\\s`` -> ``\\\\h\\s``; anything
    else unchanged."""
    if s.startswith(_EXT_UNC):
        return "\\\\" + s[len(_EXT_UNC) :]
    if s.startswith(_EXT) and len(s) > 5 and s[5] == ":":
        return s[len(_EXT) :]
    return s


def readlink(p: str | os.PathLike) -> str:
    """``os.readlink`` without the Windows extended-path prefix."""
    return strip_extended(os.readlink(p))


def resolve(p: str | os.PathLike, strict: bool = False) -> Path:
    """``Path.resolve`` without the Windows extended-path prefix."""
    return Path(strip_extended(str(Path(p).resolve(strict=strict))))


def listable(directory: Path) -> bool:
    """True when ``directory`` can be opened and listed right now."""
    try:
        with os.scandir(directory):
            return True
    except OSError:
        return False


# OS junk (never deleted, only left out of the index)
_IGNORED_NAMES = {
    ".DS_Store",
    "Icon\r",
    ".tmp.drivedownload",
    ".tmp.driveupload",
    "Thumbs.db",
    "desktop.ini",
}
_IGNORED_FOLDED = {n.casefold() for n in _IGNORED_NAMES if n in ("Thumbs.db", "desktop.ini")}


def is_ignored(name: str) -> bool:
    return (
        name in _IGNORED_NAMES
        or name.casefold() in _IGNORED_FOLDED
        or name.startswith(("~$", ".~"))
        or name.endswith(".tmp")
    )


def lists_nothing(directory: Path) -> bool:
    """``directory`` can be listed and has no entry but OS junk (False when it cannot be
    listed)."""
    try:
        with os.scandir(directory) as it:
            return not any(not is_ignored(e.name) for e in it)
    except OSError:
        return False


def newline_of(raw: bytes) -> str:
    """The line ending a text file uses: CRLF if it has any (Windows editors write it,
    and git may check files out that way), else LF. Rewrites keep it."""
    return "\r\n" if b"\r\n" in raw else "\n"


_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)  # Windows has no such flag


def open_nofollow(path: str | os.PathLike, flags: int, mode: int = 0o777) -> int:
    """``os.open`` that refuses a link at ``path`` (``ELOOP``). Where the OS has no
    ``O_NOFOLLOW`` (Windows) the link is looked for first: not atomic, but the file is
    only the app's own lock/state file in its own data folder."""
    if not _NOFOLLOW and os.path.islink(path):
        raise OSError(errno.ELOOP, "is a link", str(path))
    return os.open(path, flags | _NOFOLLOW, mode)


def realpath(p: str | os.PathLike) -> Path:
    return Path(strip_extended(os.path.realpath(p)))
