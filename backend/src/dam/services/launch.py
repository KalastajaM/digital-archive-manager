"""Open a file in its default app, or reveal it in the file manager.

macOS: ``open`` / ``open -R``. Windows: ``os.startfile`` / ``explorer /select,``.
Linux: ``xdg-open`` (reveal opens the containing folder).

The path always comes from the index (by drive id), never from the client. It is
resolved (symlinks followed) and must still lie inside the archive root: a stale
index entry or a symlink pointing elsewhere is refused. ``open`` gets a list of
arguments, never a shell string. The runner is injectable so tests never launch.
"""

import logging
import os
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from dam.core.fs import resolve
from dam.core.paths import ArchiveFolder, ArchivePaths, OutsideArchiveError
from dam.index.repo import FileRecord
from dam.services.errors import Conflict, NotFound, NotSupported

log = logging.getLogger(__name__)

OPEN_TIMEOUT_S = 15
# never launched from the archive (Show in Finder still works)
RUNNABLE_EXTS = frozenset(
    {
        # apps, scripts and installers
        ".app", ".command", ".terminal", ".workflow", ".sh", ".pkg", ".mpkg", ".scpt",
        ".action", ".jar",
        # system extensions and plug-in bundles (opening one installs or loads it)
        ".prefpane", ".saver", ".kext", ".appex", ".qlgenerator", ".mdimporter",
        ".plugin", ".bundle", ".framework",
        # internet and file locations (opening one follows a link from the archive)
        ".webloc", ".url", ".inetloc", ".fileloc", ".afploc", ".ftploc", ".mailloc",
        ".newsloc", ".vncloc", ".atloc",
        # drivers and system extensions
        ".component", ".dext", ".systemextension",
        # disk images (opening one mounts it)
        ".dmg", ".iso",
        # more installers, helpers and bundles that run, install or load something
        ".tool", ".mobileconfig", ".shortcut", ".scptd", ".osax", ".xpc", ".service",
        # app libraries (opening one hands the whole library to its app)
        ".photoslibrary", ".musiclibrary", ".fcpbundle",
        # Windows programs, scripts, installers and shortcuts
        ".exe", ".com", ".bat", ".cmd", ".msi", ".msp", ".ps1", ".psm1", ".vbs", ".vbe",
        ".js", ".jse", ".wsf", ".wsh", ".scr", ".reg", ".hta", ".msc", ".cpl", ".lnk",
        ".pif", ".gadget", ".application", ".appref-ms", ".msix", ".appx",
        # Linux launchers and packages
        ".desktop", ".appimage", ".run", ".deb", ".rpm", ".flatpakref", ".snap",
    }
)  # fmt: skip
NO_APPS = "Won't open apps or scripts from the archive — use Show in Finder"
NO_FOLDERS = "Won't open folders from the archive — use Show in Finder"
NO_LINK_TARGET = "Won't open a link to outside the archive or to nothing — use Show in Finder"
OPEN_BIN = "/usr/bin/open"
XDG_OPEN = "xdg-open"
EXPLORER = "explorer"
STARTFILE = "<startfile>"  # marker for "os.startfile(path)" (Windows has no open program)

# args -> exit status
Runner = Callable[[list[str]], int]


def run_open(args: list[str]) -> int:
    """Run ``open`` (``args[0]``) without a shell; its exit status."""
    if args[0] == STARTFILE:
        try:
            os.startfile(args[1])  # type: ignore[attr-defined]  # Windows only
        except OSError as e:
            log.warning("startfile failed: %s", e)
            return 1
        return 0
    try:
        done = subprocess.run(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=OPEN_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        log.warning("%s timed out", args[0])
        return -1
    if done.returncode:
        log.warning("%s exited %d: %s", args[0], done.returncode, done.stderr[:500])
    return done.returncode


def _require_connected(paths: ArchivePaths, folder: ArchiveFolder) -> None:
    if folder.label and not paths.is_connected(folder.label):
        raise Conflict(
            f"'{folder.label}' is not connected ({folder.root}). Connect it and try again."
        )


def resolve_inside(paths: ArchivePaths, rec: FileRecord) -> Path:
    """``rec``'s file with every symlink resolved; ``NotFound`` if it does not exist,
    ``OutsideArchiveError`` if it resolves outside the archive root."""
    folder = paths.folder_of(rec.path)
    _require_connected(paths, folder)
    path = paths.abs(rec.path)
    try:
        real = resolve(path, strict=True)
    except (OSError, RuntimeError):
        raise NotFound(f"{rec.name} is not there any more") from None
    if not real.is_relative_to(folder.root):
        raise OutsideArchiveError(f"{rec.name} resolves to a path outside the archive")
    return real


def _runnable_name(name: str) -> bool:
    return Path(name).suffix.lower() in RUNNABLE_EXTS


def _runnable(
    paths: ArchivePaths, rec: FileRecord, real: Path, via: FileRecord | None = None
) -> bool:
    """An app or script type (by the record's or the resolved name, or the name of the
    link ``via`` that led here), anything inside such a bundle (any ancestor component,
    in the indexed, the resolved or the link's path), or a regular file with an
    executable bit."""
    names = [rec.name or "", real.name]
    names += Path(rec.path).parts[:-1]
    if via is not None:
        names += Path(via.path).parts
    names += paths.rel(real).split("/")[:-1]
    if any(_runnable_name(n) for n in names):
        return True
    try:
        st = real.stat()
    except OSError:
        return True  # cannot tell: do not launch
    return stat.S_ISREG(st.st_mode) and bool(st.st_mode & 0o111)


class LaunchService:
    def __init__(
        self, paths: ArchivePaths, runner: Runner = run_open, platform: str = sys.platform
    ) -> None:
        self.paths = paths
        self.runner = runner
        self.platform = platform

    def open(self, rec: FileRecord) -> None:
        """Open ``rec`` in its default app (``/usr/bin/open <path>``); ``Conflict`` for
        folders, apps, scripts, installers, anything inside such a bundle and any
        executable file."""
        self._run(rec, [])

    def reveal(self, rec: FileRecord) -> None:
        """Show ``rec`` selected in a Finder window (``open -R <path>``)."""
        self._run(rec, ["-R"])

    def reveal_folder(self, rel: str) -> None:
        """Show the archive folder ``rel`` ("" = the archive folder) in the file manager
        (Finder, Explorer, ...). It is resolved and must be a real folder inside the
        archive."""
        self._check_platform()
        folder = self.paths.folder_of(rel)
        _require_connected(self.paths, folder)
        try:
            real = resolve(self.paths.abs(rel), strict=True)
        except (OSError, RuntimeError, OutsideArchiveError):
            raise NotFound(f"{rel or 'the archive folder'} is not there") from None
        if not real.is_dir() or not (real == folder.root or real.is_relative_to(folder.root)):
            raise NotFound(f"{rel or 'the archive folder'} is not a folder in the archive")
        status = self.runner(self.command(False, real))
        if status != 0:
            raise Conflict(f"Could not open the folder (the system opener exited {status})")

    def open_link(self, link: FileRecord, target: FileRecord | None) -> None:
        """Open the file the link ``link`` stands for (``target``, see
        ``services.links``) with every refusal of ``open`` applied to the target;
        ``Conflict`` when it has none (outside the archive or missing)."""
        self._check_platform()
        if target is None:
            raise Conflict(NO_LINK_TARGET)
        self._run(target, [], via=link)

    def reveal_link(self, link: FileRecord, target: FileRecord | None) -> None:
        """Show the link's target in Finder; without one, the link itself (never what
        it points to outside the archive)."""
        if target is not None:
            self._run(target, ["-R"])
            return
        self._check_platform()
        folder = self.paths.folder_of(link.path)
        _require_connected(self.paths, folder)
        path = self.paths.abs(link.path)
        if not path.is_symlink():
            raise NotFound(f"{link.name} is not there any more")
        try:
            parent = resolve(path.parent, strict=True)
        except (OSError, RuntimeError):
            raise NotFound(f"{link.name} is not there any more") from None
        if not parent.is_relative_to(folder.root):
            raise OutsideArchiveError(f"{link.name} lies outside the archive")
        self._launch(link, ["-R"], parent / path.name)

    def _check_platform(self) -> None:
        if self.platform not in ("darwin", "win32") and not self.platform.startswith("linux"):
            raise NotSupported("opening files is not supported on this platform")

    def _run(self, rec: FileRecord, flags: list[str], via: FileRecord | None = None) -> None:
        self._check_platform()
        real = resolve_inside(self.paths, rec)
        if not flags:
            if _runnable(self.paths, rec, real, via):
                raise Conflict(NO_APPS)  # before the folder rule: an .app is a folder
            if rec.is_dir or real.is_dir():
                raise Conflict(NO_FOLDERS)
        self._launch(rec, flags, real)

    def command(self, reveal: bool, path: Path) -> list[str]:
        """The argument list that opens (or reveals) ``path`` on this platform."""
        if self.platform == "darwin":
            return [OPEN_BIN, *(["-R"] if reveal else []), str(path)]
        if self.platform == "win32":
            if reveal:  # explorer wants one "/select,<path>" argument
                return [EXPLORER, f"/select,{path}"]
            return [STARTFILE, str(path)]
        # Linux: xdg-open cannot select a file, so reveal opens its folder
        return [XDG_OPEN, str(path.parent if reveal else path)]

    def _launch(self, rec: FileRecord, flags: list[str], path: Path) -> None:
        status = self.runner(self.command("-R" in flags, path))
        # explorer.exe reports 1 even when it worked
        if status != 0 and not (self.platform == "win32" and "-R" in flags and status == 1):
            raise Conflict(f"Could not open {rec.name} (the system opener exited {status})")
