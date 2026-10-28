"""Ask the operating system's own folder dialog for a folder (the "Choose…" buttons).

A browser cannot give a web page the absolute path of a folder, so the local server opens
the native dialog on this computer and returns the path. This only asks: it never creates,
changes or removes anything, and it is not an archive operation.

macOS: ``osascript`` (``choose folder``). Windows: PowerShell with the .NET folder dialog.
Linux: ``zenity``, else ``kdialog``; with neither (or no desktop session) the answer is
"unavailable" and the user types the path. The runner is injectable so tests never open a
dialog. Output is read as bytes and decoded as UTF-8 (a name that is not valid text is
refused rather than guessed).
"""

import logging
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

TIMEOUT_S = 15 * 60  # the user may take their time
PROMPT = "Choose the archive folder"
OSASCRIPT = "/usr/bin/osascript"
CANCEL_CODE = 3  # the PowerShell snippet exits with this when the user cancels

# The dialog is shown through the frontmost app (osascript itself has no window, so its
# dialog would open behind the browser); if that app refuses, it is shown plainly.
MAC_SCRIPT = [
    "on pick(p, dl)",
    "if dl is missing value then return choose folder with prompt p",
    "return choose folder with prompt p default location dl",
    "end pick",
    "on run argv",
    "set p to item 1 of argv",
    "set dl to missing value",
    "if (count of argv) > 1 then set dl to POSIX file (item 2 of argv)",
    "try",
    "set a to path to frontmost application as text",
    "tell application a to set f to my pick(p, dl)",
    "on error msg number n",
    "if n = -128 then error number -128",
    "set f to my pick(p, dl)",
    "end try",
    "return POSIX path of f",
    "end run",
]

WINDOWS_SCRIPT = (
    "Add-Type -AssemblyName System.Windows.Forms; "
    "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false); "
    "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
    "$d.Description = $env:DAM_PROMPT; "
    "$d.ShowNewFolderButton = $false; "
    "if ($env:DAM_START -and (Test-Path -LiteralPath $env:DAM_START)) "
    "{ $d.SelectedPath = $env:DAM_START }; "
    "$o = New-Object System.Windows.Forms.Form; $o.TopMost = $true; "
    "if ($d.ShowDialog($o) -eq [System.Windows.Forms.DialogResult]::OK) "
    "{ [Console]::Out.Write($d.SelectedPath) } else { exit " + str(CANCEL_CODE) + " }"
)

NO_DIALOG_HERE = "This computer has no folder window dam can open. Type the path instead."
NO_DESKTOP = "No desktop session was found to show a folder window. Type the path instead."
NOT_TEXT = "That folder's name is not valid text, so dam cannot use it. Type the path instead."
TIMED_OUT = "The folder window did not answer in time. Type the path instead."
BUSY = "A folder window is already open."
FAILED = "The folder window could not be opened. Type the path instead."


@dataclass(frozen=True)
class Run:
    code: int
    out: bytes = b""


# command, extra environment -> result; raises OSError (not runnable) or TimeoutExpired
Runner = Callable[[list[str], dict[str, str]], Run]


@dataclass(frozen=True)
class Choice:
    path: str | None = None
    cancelled: bool = False
    unavailable: str | None = None


def run_command(args: list[str], env: dict[str, str]) -> Run:
    """Run a dialog program without a shell (no console window on Windows)."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    done = subprocess.run(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=TIMEOUT_S,
        env={**os.environ, **env},
        creationflags=flags,
        check=False,
    )
    return Run(done.returncode, done.stdout)


_open = threading.Lock()


def start_folder(start: str | None, home: Path | None = None) -> Path:
    """Where the dialog opens: the nearest existing folder of ``start``, else home."""
    fallback = home if home is not None else Path.home()
    text = (start or "").strip()
    if not text or "\0" in text:
        return fallback
    try:
        here = Path(text).expanduser()
        if not here.is_absolute():
            return fallback
        for candidate in (here, *here.parents):
            if candidate.is_dir():
                return candidate
    except (OSError, ValueError, RuntimeError):
        pass
    return fallback


def _clean(raw: bytes) -> str | None:
    """The chosen path from a dialog's output: UTF-8, no trailing newline or slash."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    text = text.strip("\r\n")
    if len(text) > 1 and text.endswith(("/", "\\")) and not text.endswith((":\\", ":/")):
        text = text.rstrip("/\\") or text[:1]
    return text


def _answer(raw: bytes) -> Choice:
    text = _clean(raw)
    if text is None:
        return Choice(unavailable=NOT_TEXT)
    if not text.strip() or "\0" in text:
        return Choice(cancelled=True)
    return Choice(path=text)


def _mac(runner: Runner, start: Path) -> Choice:
    args = [OSASCRIPT]
    for line in MAC_SCRIPT:
        args += ["-e", line]
    args += [PROMPT, str(start)]
    done = runner(args, {})
    if done.code == 0:
        return _answer(done.out)
    return Choice(cancelled=True) if done.code == 1 else Choice(unavailable=FAILED)


def _windows(runner: Runner, start: Path) -> Choice:
    shell = shutil.which("powershell") or shutil.which("pwsh") or "powershell"
    args = [shell, "-NoProfile", "-NonInteractive", "-STA", "-WindowStyle", "Hidden"]
    env = {"DAM_PROMPT": PROMPT, "DAM_START": str(start)}
    done = runner(args + ["-Command", WINDOWS_SCRIPT], env)
    if done.code == 0:
        return _answer(done.out)
    return Choice(cancelled=True) if done.code == CANCEL_CODE else Choice(unavailable=FAILED)


def _linux(runner: Runner, start: Path) -> Choice:
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return Choice(unavailable=NO_DESKTOP)
    here = str(start).rstrip("/") + "/"
    attempts = []
    if shutil.which("zenity"):
        attempts.append(
            ["zenity", "--file-selection", "--directory", f"--title={PROMPT}", f"--filename={here}"]
        )
    if shutil.which("kdialog"):
        attempts.append(["kdialog", "--getexistingdirectory", here, "--title", PROMPT])
    for args in attempts:
        try:
            done = runner(args, {})
        except OSError:
            continue
        if done.code == 0:
            return _answer(done.out)
        if done.code == 1:  # both programs exit 1 when the window is closed
            return Choice(cancelled=True)
    return Choice(unavailable=FAILED if attempts else NO_DIALOG_HERE)


def choose_folder(
    start: str | None = None,
    *,
    platform: str | None = None,
    runner: Runner = run_command,
    home: Path | None = None,
) -> Choice:
    """Open the system folder dialog (blocking until the user answers) and return the
    chosen absolute path, or that it was cancelled, or why it is unavailable."""
    system = platform if platform is not None else sys.platform
    if not _open.acquire(blocking=False):
        return Choice(unavailable=BUSY)
    try:
        here = start_folder(start, home)
        try:
            if system == "darwin":
                return _mac(runner, here)
            if system.startswith("win"):
                return _windows(runner, here)
            return _linux(runner, here)
        except subprocess.TimeoutExpired:
            return Choice(unavailable=TIMED_OUT)
        except OSError:
            log.info("folder dialog could not run", exc_info=True)
            return Choice(unavailable=NO_DIALOG_HERE)
    finally:
        _open.release()
