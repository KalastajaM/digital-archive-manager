"""Names for folders the user creates (New folder, the archive layout).

One set of rules for every platform the archive may be synced to: nothing that Windows,
macOS or Linux would refuse or silently change.
"""

import re

from dam.core.paths import nfc

SPECIAL_PREFIX = "##."
MAX_NAME_BYTES = 255
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)
_BAD_CHARS = re.compile(r'[\x00-\x1f\x7f<>:"|?*/\\]')


class FolderNameError(ValueError):
    """The name cannot be used for a folder; the message says why, in plain words."""


def check_folder_name(name: str, special_names: tuple[str, ...] = ()) -> str:
    """The name as it will be used (NFC, surrounding spaces trimmed), or
    ``FolderNameError``. A name starting with ``##.`` is the app's marker for its special
    folders: allowed only when it is one of ``special_names`` (compared case-insensitively)."""
    if not isinstance(name, str):
        raise FolderNameError("Enter a folder name.")
    clean = nfc(name).strip()
    if not clean:
        raise FolderNameError("Enter a folder name.")
    if clean in (".", ".."):
        raise FolderNameError(f"{clean!r} cannot be used as a folder name.")
    if "/" in clean or "\\" in clean:
        raise FolderNameError("A folder name cannot contain / or \\ . Make one folder at a time.")
    if _BAD_CHARS.search(clean):
        raise FolderNameError('A folder name cannot contain any of < > : " | ? * .')
    if clean.endswith((".", " ")):
        raise FolderNameError("A folder name cannot end with a dot or a space.")
    if clean.startswith("."):
        raise FolderNameError("A folder name cannot start with a dot (it would be hidden).")
    if clean.split(".")[0].rstrip().casefold() in _WINDOWS_RESERVED:
        raise FolderNameError(f"{clean!r} is a reserved name on Windows. Choose another.")
    if len(clean.encode("utf-8")) > MAX_NAME_BYTES:
        raise FolderNameError("That name is too long.")
    if clean.startswith(SPECIAL_PREFIX) and clean.casefold() not in {
        nfc(s).casefold() for s in special_names
    }:
        raise FolderNameError(
            f"Names starting with {SPECIAL_PREFIX} are kept for the app's own folders."
        )
    return clean


def portable_name_problem(name: str) -> str | None:
    """Why the new file or folder name ``name`` would break on Windows or a cloud drive
    the archive is synced to (in plain words), or None when it is fine there: a reserved
    name (CON, PRN, AUX, NUL, COM1-9, LPT1-9, with any extension), a trailing dot or
    space, or one of < > : " | ? * \\ or a control character."""
    if _BAD_CHARS.search(name):
        return (
            f'{name!r} cannot be used: names cannot contain any of < > : " | ? * \\ or '
            "control characters (Windows and cloud drives refuse them)."
        )
    if name.endswith((".", " ")):
        return f"{name!r} cannot be used: a name cannot end with a dot or a space."
    if name.split(".")[0].rstrip().casefold() in _WINDOWS_RESERVED:
        return f"{name!r} is a reserved name on Windows. Choose another."
    return None
