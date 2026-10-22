"""The LaunchAgent that runs ``dam remind`` at the reminder hour and at login.

The plist at ``~/Library/LaunchAgents/nl.dam.remind.plist`` is the only file the app
writes outside its data dir; ``uninstall`` removes exactly that file and nothing else.

Each archive (profile) has its own agent: the profile "Main" keeps the label
``nl.dam.remind``, any other gets ``nl.dam.remind.<id>`` (``label_for``), so installing
or removing the reminders of one archive never touches another's.
"""

import os
import plistlib
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

from dam.config import AppPaths

LABEL = "nl.dam.remind"
MAIN_ID = "main"  # the profile that keeps the original label
LAUNCHCTL = "/bin/launchctl"
_NOT_LOADED_CODES = {3, 113}  # "No such process", "Could not find specified service"
_RETRY_AFTER = 1.0  # seconds; bootstrap right after a bootout often reports error 5


class LaunchdError(Exception):
    """Installing or removing the LaunchAgent failed; the message says why."""


def label_for(profile_id: str | None) -> str:
    """The agent label of an archive: ``nl.dam.remind`` for "Main" (and for the single
    archive of older installs), ``nl.dam.remind.<id>`` for any other."""
    return LABEL if profile_id in (None, MAIN_ID) else f"{LABEL}.{profile_id}"


def plist_path(label: str = LABEL) -> Path:
    if "/" in label or "\\" in label or ".." in label:
        raise LaunchdError(f"not a valid LaunchAgent label: {label}")
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def pins_archive(label: str = LABEL) -> bool | None:
    """Does the installed plist name its archive (``--archive``)? None: not installed.
    A plist from before archives existed does not, so it follows the archive in use."""
    try:
        data = plistlib.loads(plist_path(label).read_bytes())
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None
    return "--archive" in data.get("ProgramArguments", [])


def dam_command() -> list[str]:
    """The absolute path of the ``dam`` executable running now (the venv's)."""
    found = shutil.which("dam")
    return [str(Path(found).resolve() if found else Path(sys.argv[0]).resolve())]


def plist(
    dam_cmd: list[str],
    data_dir: Path,
    hour: int,
    label: str = LABEL,
    archive: tuple[Path, str] | None = None,
) -> str:
    """The agent's plist. ``archive``: (base folder, profile id) of an archive; then the
    job runs ``dam --data-dir <base> --archive <id> remind`` and logs in that archive's
    own data folder (``data_dir``). Without it, the older single-archive form."""
    data_dir = Path(data_dir).resolve()
    log = str(AppPaths(data_dir).logs_dir / "remind.log")
    if archive is None:
        args = [*dam_cmd, "--data-dir", str(data_dir), "remind"]
    else:
        base, pid = archive
        args = [*dam_cmd, "--data-dir", str(Path(base).resolve()), "--archive", pid, "remind"]
    return plistlib.dumps(
        {
            "Label": label,
            "ProgramArguments": args,
            "StartCalendarInterval": {"Hour": hour, "Minute": 0},
            "RunAtLoad": True,
            "StandardOutPath": log,
            "StandardErrorPath": log,
        },
        sort_keys=False,
    ).decode("utf-8")


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            [LAUNCHCTL, *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            encoding="utf-8",
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise LaunchdError(f"launchctl failed: {e}") from e


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except FileNotFoundError:
        return False


def _write(path: Path, content: str, force: bool) -> None:
    """Create ``path`` exclusively; an existing different file only with ``force``.
    Never follows a symlink."""
    data = content.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    except FileExistsError:
        if not _regular_file(path):
            raise LaunchdError(f"{path} exists and is not a regular file") from None
        if path.read_bytes() == data:
            return
        if not force:
            raise LaunchdError(
                f"{path} already exists with different content (use --force to replace it)"
            ) from None
        try:
            fd = os.open(path, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
        except OSError as e:
            raise LaunchdError(f"cannot write {path}: {e}") from e
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def _transient(result: subprocess.CompletedProcess) -> bool:
    """launchd's "5: Input/output error": usually the old job still unloading."""
    return result.returncode == 5 or "Input/output error" in (result.stderr or "")


def install(
    dam_cmd: list[str],
    data_dir: Path,
    hour: int,
    force: bool = False,
    label: str = LABEL,
    archive: tuple[Path, str] | None = None,
) -> Path:
    """Write the plist and load it (``launchctl bootstrap gui/<uid>``, retried once after
    a short pause on error 5); return its path."""
    path = plist_path(label)
    _write(path, plist(dam_cmd, data_dir, hour, label, archive), force)
    _launchctl("bootout", _domain(), str(path))  # reload if an older one is loaded
    result = _launchctl("bootstrap", _domain(), str(path))
    if _transient(result):
        time.sleep(_RETRY_AFTER)
        result = _launchctl("bootstrap", _domain(), str(path))
    if result.returncode != 0:
        raise LaunchdError(f"launchctl bootstrap failed: {result.stderr.strip()}")
    return path


def uninstall(path: Path | None = None, label: str = LABEL) -> bool:
    """Unload the agent and remove its plist; return False if there was none.

    Only the exact plist path is ever removed (anything else is refused), and only if
    it is a regular file. If ``~/Library/LaunchAgents`` is itself a symlink, the plist in
    the folder it points to is removed: that is the file launchd reads.
    """
    expected = plist_path(label)
    path = expected if path is None else Path(path)
    if path != expected:
        raise LaunchdError(f"refusing to remove {path}: not the reminder LaunchAgent")
    if not os.path.lexists(path):
        return False
    if not _regular_file(path):
        raise LaunchdError(f"refusing to remove {path}: not a regular file")
    result = _launchctl("bootout", _domain(), str(path))
    if result.returncode != 0 and result.returncode not in _NOT_LOADED_CODES:
        raise LaunchdError(f"launchctl bootout failed: {result.stderr.strip()}")
    path.unlink()
    return True
