"""A stand-in for the ``xattr`` package where it is missing or cannot hold the Drive id
attribute (Windows; Linux file systems without user xattrs).

macOS uses the real package. On Linux the real package is wrapped so that the macOS
attribute name (which has no namespace) is stored as ``user.<name>``. On Windows there
are no extended attributes at all, so values are kept in memory per file identity
(device and inode, which survive renames). Either way the tests set and read Drive ids
exactly as on macOS. ``install()`` puts the result in ``sys.modules['xattr']`` so the
application code that imports ``xattr`` gets it too.
"""

import errno
import os
import sys
import tempfile
import types

_MEMORY: dict[tuple[int, int], dict[str, bytes]] = {}


def _identity(target, symlink: bool) -> tuple[int, int]:
    if isinstance(target, int):
        st = os.fstat(target)
    else:
        st = os.lstat(target) if symlink else os.stat(target)
    return (st.st_dev, st.st_ino)


def _memory_module() -> types.ModuleType:
    mod = types.ModuleType("xattr")

    def getxattr(f, attr, symlink=False):
        try:
            return _MEMORY[_identity(f, symlink)][attr]
        except KeyError:
            raise OSError(errno.ENODATA, "no such attribute") from None

    def setxattr(f, attr, value, flags=0, symlink=False):
        _MEMORY.setdefault(_identity(f, symlink), {})[attr] = bytes(value)

    def removexattr(f, attr, symlink=False):
        try:
            del _MEMORY[_identity(f, symlink)][attr]
        except KeyError:
            raise OSError(errno.ENODATA, "no such attribute") from None

    def listxattr(f, symlink=False):
        return list(_MEMORY.get(_identity(f, symlink), {}))

    mod.getxattr, mod.setxattr = getxattr, setxattr
    mod.removexattr, mod.listxattr = removexattr, listxattr
    return mod


def _user_namespace(real) -> types.ModuleType:
    mod = types.ModuleType("xattr")

    def ns(attr: str) -> str:
        return attr if attr.startswith("user.") else f"user.{attr}"

    def getxattr(f, attr, symlink=False):
        return real.getxattr(f, ns(attr), symlink=symlink)

    def setxattr(f, attr, value, flags=0, symlink=False):
        return real.setxattr(f, ns(attr), value, flags, symlink=symlink)

    def removexattr(f, attr, symlink=False):
        return real.removexattr(f, ns(attr), symlink=symlink)

    def listxattr(f, symlink=False):
        return [a.removeprefix("user.") for a in real.listxattr(f, symlink=symlink)]

    mod.getxattr, mod.setxattr = getxattr, setxattr
    mod.removexattr, mod.listxattr = removexattr, listxattr
    return mod


def install() -> None:
    if sys.platform == "darwin":
        return
    try:
        import xattr as real
    except ImportError:
        sys.modules["xattr"] = _memory_module()
        return
    wrapped = _user_namespace(real)
    try:
        with tempfile.NamedTemporaryFile() as probe:
            wrapped.setxattr(probe.name, "com.google.drivefs.item-id#S", b"x")
            wrapped.getxattr(probe.name, "com.google.drivefs.item-id#S")
    except OSError:
        sys.modules["xattr"] = _memory_module()
    else:
        sys.modules["xattr"] = wrapped
