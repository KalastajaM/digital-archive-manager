"""A runtime guard: only the operation layer (``dam/ops``) writes to a fake archive.

``test_no_delete.py`` reads the source for deletes and renames. This guard watches what
really happens while the tests run, through one ``sys.addaudithook`` for the session: any
call that creates, changes, renames or removes an entry inside a registered fake archive
root (every ``FakeArchive``) must come from ``dam/ops``, from the tests themselves, or from
one of the few documented exceptions below. Anything else raises an ``AssertionError`` at
the call and is also recorded, so a broad ``except Exception`` in the code under test
cannot hide it: the ``_archive_write_guard`` fixture in conftest fails the test at
teardown.

A test that hits a known bug can allow one place with
``@pytest.mark.archive_write_allowed("dam/<file>.py:<function>", reason="...")``.
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

import dam

SRC = os.path.dirname(os.path.abspath(dam.__file__)) + os.sep
OPS = os.path.join(SRC, "ops") + os.sep
TESTS = os.path.dirname(os.path.abspath(__file__)) + os.sep

# Non-ops code that may write into an archive, each documented in docs/reference.md:
# (file relative to src/dam, function or "*" for the whole module) -> reason
EXCEPTIONS: dict[tuple[str, str], str] = {
    # the one folder the user confirmed for a new archive (Setup / ``dam init``),
    # made before there is an archive for the ops layer to work in
    ("setup.py", "create_archive_folder"): "creates the archive folder itself",
    # "Add archive... > Create a demo archive" makes the (new or empty) demo folder ...
    ("services/archives.py", "add"): "creates the new demo archive folder",
    # ... and ``dam.demo`` fills it with fictional files ("The demo archive")
    ("demo.py", "*"): "fills a new, empty demo archive with fictional files",
}

# event -> positions of the path arguments whose target is changed
_PATH_EVENTS: dict[str, tuple[int, ...]] = {
    "os.remove": (0,),  # os.remove, os.unlink, Path.unlink
    "os.rmdir": (0,),
    "os.mkdir": (0,),
    "os.rename": (0, 1),  # os.rename, os.replace, Path.rename/replace
    "os.symlink": (1,),
    "os.link": (1,),
    "os.truncate": (0,),
    "os.chmod": (0,),
    "os.chown": (0,),
    "os.chflags": (0,),
    "os.utime": (0,),
    "os.setxattr": (0,),
    "os.removexattr": (0,),
    "os.mkfifo": (0,),
    "os.mknod": (0,),
    "shutil.copyfile": (1,),
    "shutil.copymode": (1,),
    "shutil.copystat": (1,),
    "shutil.copytree": (1,),
    "shutil.move": (0, 1),
    "shutil.rmtree": (0,),
    "shutil.chown": (0,),
}
_SHELL_EVENTS = {"os.system", "subprocess.Popen"}
_WATCHED = frozenset(_PATH_EVENTS) | _SHELL_EVENTS | {"open"}

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
# commands that change files; reading tools (qlmanage, textutil, open, tesseract) are fine
_MUTATING = frozenset(
    "mv rm rmdir cp mkdir touch ln rsync ditto chmod chown chflags xattr setfile install"
    " truncate tee dd move del copy xcopy robocopy ren rename md mklink".split()
)


class _State:
    installed = False
    roots: tuple[str, ...] = ()  # each with a trailing separator
    allowed: frozenset[str] = frozenset()  # "dam/<file>.py:<function>" for this test
    violations: list[str] = []


state = _State()


def install() -> None:
    """Add the hook once per session (an audit hook can never be removed)."""
    if not state.installed:
        sys.addaudithook(_hook)
        state.installed = True


def register(root: Path) -> None:
    """Watch ``root`` (both as given and resolved, e.g. /var vs /private/var on macOS)."""
    forms = {os.path.normpath(os.path.abspath(root)), os.path.realpath(root)}
    new = tuple(f.rstrip(os.sep) + os.sep for f in forms)
    state.roots = state.roots + tuple(r for r in new if r not in state.roots)


def reset(allowed: frozenset[str] = frozenset()) -> None:
    state.roots = ()
    state.allowed = allowed
    state.violations = []


def _in_archive(path: object, dir_fd: object = None) -> str | None:
    if isinstance(path, int) or path is None:
        return None
    try:
        p = os.fsdecode(path)
    except TypeError:
        return None
    if not os.path.isabs(p):
        if dir_fd not in (None, -1):
            return None  # relative to an open folder (the ops primitives): cannot tell
        p = os.path.abspath(p)
    else:
        p = os.path.normpath(p)
    candidate = p + os.sep
    for root in state.roots:
        if candidate.startswith(root):
            return p
    return None


def _is_write_open(mode: object, flags: object) -> bool:
    if isinstance(mode, str):
        return any(c in mode for c in "wax+")
    return isinstance(flags, int) and bool(flags & _WRITE_FLAGS)


def _shell_target(event: str, args: tuple) -> str | None:
    """The archive path a mutating command names, if any."""
    if event == "os.system":
        try:
            words = _split(os.fsdecode(args[0]))
        except (ValueError, TypeError):
            words = str(args[0]).split()
        cwd = None
    else:
        _executable, argv, cwd, _env = args
        if isinstance(argv, (str, bytes, os.PathLike)):
            try:
                words = _split(os.fsdecode(argv))
            except ValueError:
                words = os.fsdecode(argv).split()
        else:
            words = [os.fsdecode(a) for a in argv if isinstance(a, (str, bytes, os.PathLike))]
    if not words:
        return None
    command = os.path.basename(words[0]).lower().removesuffix(".exe")
    if command in ("sh", "bash", "zsh", "cmd", "cmd.exe") and len(words) > 2:
        return _shell_target("os.system", (" ".join(words[2:]),))
    if command not in _MUTATING:
        return None
    for word in words[1:]:
        found = _in_archive(word)
        if found:
            return found
    if cwd is not None and _in_archive(cwd):
        return _in_archive(cwd)
    return None


def _split(line: str) -> list[str]:
    """A command line in words. Windows hands Popen's audit hook one joined string
    with backslash paths, which POSIX splitting would mangle."""
    if os.name != "nt":
        return shlex.split(line)
    words = shlex.split(line, posix=False)
    return [w[1:-1] if len(w) > 1 and w[0] == w[-1] == '"' else w for w in words]


def _offender():
    """The innermost frame of dam or the tests, or None when the write is allowed."""
    frame = sys._getframe(2)
    first = None
    while frame is not None:
        name = frame.f_code.co_filename
        if name.startswith(OPS):
            return None
        if first is None and (name.startswith(SRC) or name.startswith(TESTS)):
            first = frame
        frame = frame.f_back
    if first is None or first.f_code.co_filename.startswith(TESTS):
        return None  # the tests build their fake archives; pytest cleans up tmp folders
    rel = first.f_code.co_filename[len(SRC) :].replace(os.sep, "/")
    func = first.f_code.co_name
    if (rel, func) in EXCEPTIONS or (rel, "*") in EXCEPTIONS:
        return None
    if f"dam/{rel}:{func}" in state.allowed:
        return None
    return first


def _hook(event: str, args: tuple) -> None:
    if not state.roots or event not in _WATCHED:
        return
    if event == "open":
        if not _is_write_open(args[1], args[2]):
            return
        target = _in_archive(args[0])
    elif event in _SHELL_EVENTS:
        target = _shell_target(event, args)
    else:
        dir_fd = args[-1] if event in ("os.remove", "os.rmdir", "os.mkdir") else None
        target = None
        for i in _PATH_EVENTS[event]:
            if i < len(args):
                target = _in_archive(args[i], dir_fd)
                if target:
                    break
    if target is None:
        return
    frame = _offender()
    if frame is None:
        return
    rel = frame.f_code.co_filename[len(SRC) :].replace(os.sep, "/")
    message = (
        f"archive write outside dam/ops: {event} on {target!r} from "
        f"dam/{rel}:{frame.f_lineno} ({frame.f_code.co_name}). Only the operation layer "
        "writes to the archive (CONTRIBUTING, safety rules)."
    )
    state.violations.append(message)
    raise AssertionError(message)
