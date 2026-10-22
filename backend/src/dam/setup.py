"""First-run setup: find likely archive locations, check a folder, write ``archive_root``.

Nothing here guesses silently. ``detect_candidates`` only *lists* folders that exist (cloud
drives and the like); the user picks one, and ``write_archive_root`` is the only thing that
ever changes the config, and only after the caller has asked the user.
"""

import json
import os
import re
import string
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from dam.config import AppPaths, SpecialFolders, load_settings
from dam.core.fs import newline_of, resolve
from dam.core.paths import nfc

NOT_CONFIGURED = (
    "No archive folder configured yet — run `dam init` (or open the app to choose one)."
)

# Provider names (shown to the user)
GOOGLE_DRIVE = "Google Drive"
ONEDRIVE = "OneDrive"
DROPBOX = "Dropbox"
BOX = "Box"
ICLOUD = "iCloud Drive"
NEXTCLOUD = "Nextcloud"
PCLOUD = "pCloud"
INSYNC = "Insync (Google Drive)"


@dataclass(frozen=True)
class Candidate:
    provider: str
    label: str  # e.g. "Google Drive (GoogleDrive-name)": the provider and which account
    path: Path


def current_system() -> str:
    """``"darwin"``, ``"windows"`` or ``"linux"``."""
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("win"):
        return "windows"
    return "linux"


def _dirs(parent: Path, pattern: str) -> list[Path]:
    try:
        return sorted(p for p in parent.glob(pattern) if p.is_dir())
    except OSError:
        return []


def _named(provider: str, path: Path, detail: str | None = None) -> Candidate:
    detail = detail if detail is not None else path.name
    label = provider if detail in ("", provider) else f"{provider} ({detail})"
    return Candidate(provider, label, path)


def _google_drive_root(path: Path) -> Path:
    mine = path / "My Drive"
    return mine if mine.is_dir() else path


def _windows_drive_roots() -> list[Path]:
    return [
        Path(f"{letter}:\\") for letter in string.ascii_uppercase if Path(f"{letter}:\\").exists()
    ]


def detect_candidates(
    home: Path | None = None,
    system: str | None = None,
    drive_roots: Iterable[Path] | None = None,
) -> list[Candidate]:
    """Folders on this machine that look like a cloud-drive or sync folder, in the order
    they are offered. Pure apart from looking at ``home`` (and, on Windows, ``drive_roots``:
    the drive letters to check for Google Drive's ``My Drive``; default: the real ones).
    A folder that does not exist is never listed; the same folder is listed once."""
    home = Path.home() if home is None else home
    system = current_system() if system is None else system
    found: list[Candidate] = []

    if system == "darwin":
        for p in _dirs(home / "Library" / "CloudStorage", "*"):
            n = p.name
            if n.startswith("GoogleDrive"):
                found.append(_named(GOOGLE_DRIVE, _google_drive_root(p), n))
            elif n.startswith("OneDrive"):
                found.append(_named(ONEDRIVE, p, n))
            elif n.startswith("Dropbox"):
                found.append(_named(DROPBOX, p, n))
            elif n.startswith("Box"):
                found.append(_named(BOX, p, n))
        icloud = home / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
        if icloud.is_dir():
            found.append(_named(ICLOUD, icloud, ""))
        found += [_named(DROPBOX, p, "") for p in _dirs(home, "Dropbox")]
        found += [_named(ONEDRIVE, p) for p in _dirs(home, "OneDrive*")]
        found += [_named(GOOGLE_DRIVE, p, "") for p in _dirs(home, "Google Drive")]
    elif system == "windows":
        found += [_named(ONEDRIVE, p) for p in _dirs(home, "OneDrive*")]
        found += [_named(DROPBOX, p, "") for p in _dirs(home, "Dropbox")]
        roots = _windows_drive_roots() if drive_roots is None else list(drive_roots)
        for root in roots:
            mine = root / "My Drive"
            try:
                if mine.is_dir():
                    found.append(_named(GOOGLE_DRIVE, mine, str(root).rstrip("\\/") or str(root)))
            except OSError:
                continue
        found += [_named(ICLOUD, p, "") for p in _dirs(home, "iCloudDrive")]
    else:  # linux and anything else
        found += [_named(DROPBOX, p, "") for p in _dirs(home, "Dropbox")]
        found += [_named(NEXTCLOUD, p, "") for p in _dirs(home, "Nextcloud")]
        found += [_named(ONEDRIVE, p, "") for p in _dirs(home, "OneDrive")]
        found += [_named(PCLOUD, p, "") for p in _dirs(home, "pCloudDrive")]
        found += [_named(INSYNC, p) for p in _dirs(home / "Insync", "*")]

    seen: set[Path] = set()
    unique: list[Candidate] = []
    for c in found:
        try:
            key = resolve(c.path)
        except OSError:
            key = c.path
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def list_subfolders(path: Path, limit: int = 200) -> list[str]:
    """Names of the folders directly in ``path`` (hidden ones left out), sorted; empty if
    it cannot be listed."""
    try:
        names = sorted(
            (e.name for e in os.scandir(path) if e.is_dir() and not e.name.startswith(".")),
            key=str.casefold,
        )
    except OSError:
        return []
    return names[:limit]


@dataclass(frozen=True)
class PathCheck:
    ok: bool
    path: Path | None  # the absolute path that was checked (None for empty input)
    message: str  # why not ok (or "" when ok)
    exists: bool = False
    can_create: bool = False  # does not exist, but its parent is a writable folder


def _is_inside(inner: Path, outer: Path) -> bool:
    return inner == outer or outer in inner.parents


def _resolve(raw: str) -> Path | None:
    text = raw.strip()
    if not text:
        return None
    p = Path(text).expanduser()
    if not p.is_absolute():
        return p
    try:
        return resolve(p)
    except (OSError, RuntimeError):
        return p


def check_archive_path(
    raw: str,
    app_paths: AppPaths,
    home: Path | None = None,
    guard: Callable[[Path], str | None] | None = None,
) -> PathCheck:
    """Can ``raw`` be the archive folder? It must exist (``can_create`` says when it
    could be created), be a readable and writable folder, and not be the home folder, a
    filesystem root, or inside (or around) the app's own data folder. ``guard`` (the
    profiles' isolation rules, ``ProfileStore.root_guard``) returns why a folder clashes
    with another archive, or None."""
    path = _resolve(raw)
    if path is None:
        return PathCheck(False, None, "Enter the path of a folder.")
    if not path.is_absolute():
        return PathCheck(
            False, path, "Use the full path of the folder (it starts with / or a drive letter)."
        )
    home = resolve(Path.home() if home is None else home)
    if path.parent == path:
        return PathCheck(False, path, "That is the top of a disk. Choose a folder inside it.")
    if path == home:
        return PathCheck(
            False, path, "That is your whole home folder. Choose or create a folder inside it."
        )
    if _is_inside(home, path):
        return PathCheck(
            False, path, "That folder contains your home folder. Choose a smaller one."
        )
    data = resolve(app_paths.data_dir)
    if _is_inside(path, data) or _is_inside(data, path):
        return PathCheck(
            False, path, "That folder overlaps the app's own data folder. Choose another."
        )
    if guard is not None and (clash := guard(path)):
        return PathCheck(False, path, clash)
    try:
        exists = path.exists()
        is_dir = path.is_dir()
    except OSError as e:
        return PathCheck(False, path, f"That folder cannot be read ({e.strerror or e}).")
    if not exists:
        parent = path.parent
        writable = parent.is_dir() and os.access(parent, os.W_OK | os.X_OK)
        if writable:
            return PathCheck(False, path, "That folder does not exist yet.", can_create=True)
        return PathCheck(
            False,
            path,
            "That folder does not exist, and the folder above it is missing or read-only.",
        )
    if not is_dir:
        return PathCheck(False, path, "That is a file, not a folder.", exists=True)
    if not os.access(path, os.R_OK | os.X_OK):
        return PathCheck(False, path, "This app cannot read that folder.", exists=True)
    if not os.access(path, os.W_OK):
        return PathCheck(
            False, path, "This app cannot write to that folder (it is read-only).", exists=True
        )
    return PathCheck(True, path, "", exists=True)


# Files the operating systems put in a folder by themselves: they do not make a folder
# "not empty" (compared case-insensitively; also any AppleDouble ``._*`` file).
OS_JUNK = frozenset(
    {
        ".ds_store",
        ".localized",
        ".spotlight-v100",
        ".trashes",
        ".fseventsd",
        ".temporaryitems",
        "thumbs.db",
        "ehthumbs.db",
        "desktop.ini",
        "$recycle.bin",
        "system volume information",
        ".directory",
    }
)


def is_os_junk(name: str) -> bool:
    folded = name.casefold()
    return folded in OS_JUNK or folded.startswith("._")


def visible_entries(folder: Path | None) -> list[str]:
    """The names directly in ``folder`` that are not OS junk (``.DS_Store``,
    ``Thumbs.db``, ``desktop.ini``, ...), sorted; empty when it cannot be read."""
    if folder is None:
        return []
    try:
        return sorted(n for n in os.listdir(folder) if not is_os_junk(n))
    except OSError:
        return []


def is_empty_folder(folder: Path | None) -> bool:
    """A folder that exists and holds nothing but OS junk."""
    if folder is None:
        return False
    try:
        return folder.is_dir() and not visible_entries(folder)
    except OSError:
        return False


def create_archive_folder(check: PathCheck) -> None:
    """Create the one folder ``check`` described (``can_create`` only; its parent exists).
    Call it only after the user confirmed."""
    if not check.can_create or check.path is None:
        raise ValueError("this folder cannot be created")
    check.path.mkdir(parents=False, exist_ok=False)


# -- the settings file -----------------------------------------------------------------

_ACTIVE = re.compile(r"^archive_root[ \t]*:.*$", re.MULTILINE)
_EXAMPLE = re.compile(r"^#[ \t]*archive_root[ \t]*:.*$", re.MULTILINE)


def settings_path(app_paths: AppPaths) -> Path:
    return app_paths.config_dir / "settings.yaml"


def current_archive_root(app_paths: AppPaths) -> str | None:
    """The raw ``archive_root`` in the settings file, or None when unset (or no file)."""
    try:
        raw = yaml.safe_load(settings_path(app_paths).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    value = raw.get("archive_root") if isinstance(raw, dict) else None
    return str(value) if value else None


def is_configured(app_paths: AppPaths) -> bool:
    return current_archive_root(app_paths) is not None


def planned_line(path: Path) -> str:
    """The exact line ``write_archive_root`` puts in the settings file."""
    return f"archive_root: {json.dumps(str(path), ensure_ascii=False)}"


def write_archive_root(app_paths: AppPaths, path: Path) -> Path:
    """Set ``archive_root`` in ``<data dir>/config/settings.yaml`` (seeding the defaults
    first if the file is missing) and nothing else; comments are kept. Returns the file."""
    app_paths.ensure()
    target = settings_path(app_paths)
    raw = target.read_bytes()
    nl = newline_of(raw)
    text = raw.decode("utf-8").replace("\r\n", "\n")
    line = planned_line(path)
    if _ACTIVE.search(text):
        new = _ACTIVE.sub(lambda _m: line, text, count=1)
    else:
        examples = list(_EXAMPLE.finditer(text))
        if examples:  # right after the commented examples
            end = examples[-1].end()
            new = text[:end] + "\n" + line + text[end:]
        else:
            new = line + "\n" + text
    original = raw
    # Written in place, not via a temp file + os.replace: renames are pinned to dam/ops
    # (tests/test_no_delete.py). When a value is replaced, the old file is kept as a backup.
    if _ACTIVE.search(text):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            with open(target.with_name(f"{target.name}.bak-{stamp}"), "xb") as fh:
                fh.write(original)
        except FileExistsError:
            pass  # a backup from this very second exists already
    try:
        with open(target, "w", encoding="utf-8", newline=nl) as f:
            f.write(new)
        if current_archive_root(app_paths) != str(path):
            raise OSError("the setting did not read back as written")
    except OSError:
        with open(target, "wb") as f:
            f.write(original)
        raise
    return target


def special_folders(names: SpecialFolders | None = None) -> list[dict]:
    """The folders the app uses by name inside the archive (``names``: the configured
    ones, default the shipped names). The app uses each one when it exists; a new archive
    can have them made (a layout)."""
    names = SpecialFolders() if names is None else names
    return [
        {
            "role": "inbox",
            "title": "Inbox",
            "name": names.inbox,
            "purpose": "New documents wait here until you file them.",
        },
        {
            "role": "ongoing",
            "title": "Ongoing",
            "name": names.ongoing,
            "purpose": "Shortcuts to the collections you are working on now.",
        },
        {
            "role": "important",
            "title": "Important",
            "name": names.important,
            "purpose": "Shortcuts to the key documents you must not lose.",
        },
        {
            "role": "quarantine",
            "title": "To delete",
            "name": names.quarantine,
            "purpose": "Files you mark for deletion wait here instead. You delete them yourself.",
        },
    ]


def special_folder_status(archive_root: Path) -> list[dict]:
    """``special_folders()`` plus whether each exists in ``archive_root``."""
    return [{**f, "exists": (archive_root / f["name"]).is_dir()} for f in special_folders()]


# -- the layout: special folder names and AI exclusions in the settings file ---------------

_SPECIAL_BLOCK = re.compile(r"^special_folders[ \t]*:[ \t]*\n(?:[ \t]+\S[^\n]*\n?)+", re.MULTILINE)
_PROTECTED_BLOCK = re.compile(r"^protected_paths[ \t]*:[ \t]*\n(?:[ \t]+-[^\n]*\n?)+", re.MULTILINE)
_AI_ACTIVE = re.compile(r"^ai[ \t]*:", re.MULTILINE)


def _block(key: str, items: list[tuple[str, str]] | list[str]) -> str:
    lines = [f"{key}:"]
    for item in items:
        if isinstance(item, tuple):
            lines.append(f"  {item[0]}: {json.dumps(item[1], ensure_ascii=False)}")
        else:
            lines.append(f"  - {json.dumps(item, ensure_ascii=False)}")
    return "\n".join(lines) + "\n"


def _replace_or_insert(text: str, pattern: re.Pattern, block: str) -> str:
    if pattern.search(text):
        return pattern.sub(lambda _m: block, text, count=1)
    return text.rstrip("\n") + "\n" + block


def write_layout_settings(
    app_paths: AppPaths, special: SpecialFolders, ai_exclude: list[str] | None = None
) -> Path:
    """Write the chosen special folder names to ``special_folders`` in the settings file
    (and the same name into ``protected_paths`` when the Important folder was renamed),
    plus, when no ``ai:`` section is set yet, ``ai.exclude_folders`` for the layout's
    private folders. Comments elsewhere are kept; the file it replaces is saved as a
    ``.bak-<time>`` copy. Verified by reading the settings back; restored on failure."""
    app_paths.ensure()
    target = settings_path(app_paths)
    original = target.read_bytes()
    nl = newline_of(original)
    text = original.decode("utf-8").replace("\r\n", "\n")
    old = load_settings(app_paths)
    names = [
        (role, getattr(special, role)) for role in ("inbox", "ongoing", "important", "quarantine")
    ]
    new = _replace_or_insert(text, _SPECIAL_BLOCK, _block("special_folders", names))
    protected = [
        special.important
        if nfc(p).casefold() == nfc(old.special_folders.important).casefold()
        else p
        for p in old.protected_paths
    ]
    if protected != old.protected_paths:
        new = _replace_or_insert(new, _PROTECTED_BLOCK, _block("protected_paths", protected))
    if ai_exclude and not _AI_ACTIVE.search(new):
        new = (
            new.rstrip("\n")
            + "\n"
            + _block("ai", [])[:-1]
            + "\n  exclude_folders:\n"
            + "".join(f"    - {json.dumps(n, ensure_ascii=False)}\n" for n in ai_exclude)
        )
    if new == text:
        return target
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        with open(target.with_name(f"{target.name}.bak-{stamp}"), "xb") as fh:
            fh.write(original)
    except FileExistsError:
        pass
    try:
        with open(target, "w", encoding="utf-8", newline=nl) as f:
            f.write(new)
        if load_settings(app_paths).special_folders != special:
            raise OSError("the settings did not read back as written")
    except (OSError, ValueError, yaml.YAMLError):
        with open(target, "wb") as f:
            f.write(original)
        raise
    return target


# -- the AI excluded folders in the settings file -------------------------------------

_AI_LINE = re.compile(r"^ai[ \t]*:(?P<rest>[^\n]*)$", re.MULTILINE)
_EXCLUDE_KEY = re.compile(r"^(?P<indent>[ \t]+)exclude_folders[ \t]*:(?P<rest>[^\n]*)$")


def _value_of(rest: str) -> str:
    """What follows a ``key:`` on its line, without a trailing comment."""
    return re.sub(r"(^|[ \t])#.*$", "", rest).strip()


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _exclude_lines(indent: str, folders: list[str]) -> list[str]:
    if not folders:
        return [f"{indent}exclude_folders: []"]
    return [f"{indent}exclude_folders:"] + [
        f"{indent}  - {json.dumps(f, ensure_ascii=False)}" for f in folders
    ]


def with_ai_exclude_folders(text: str, folders: list[str]) -> str:
    """``text`` (a settings file, ``\\n`` newlines) with ``ai.exclude_folders`` set to
    ``folders``; everything else, comments included, as it was. No active ``ai:``
    section: one is added at the end. A section written inline (``ai: {...}``) is refused
    (ValueError): it has to be edited by hand."""
    m = _AI_LINE.search(text)
    if m is None:
        return text.rstrip("\n") + "\n" + "\n".join(["ai:", *_exclude_lines("  ", folders)]) + "\n"
    if _value_of(m.group("rest")):
        raise ValueError(
            "the ai: section is written inline; edit exclude_folders in settings.yaml by hand"
        )
    lines = text.split("\n")
    start = text[: m.start()].count("\n")  # the ai: line
    end = start + 1  # the section: indented, blank or comment lines up to the next key
    while end < len(lines) and (not lines[end].strip() or lines[end][:1] in " \t#"):
        if lines[end][:1] == "#":  # a top-level comment ends it unless the section goes on after it
            nxt = end + 1
            while nxt < len(lines) and lines[nxt][:1] == "#":
                nxt += 1
            if nxt >= len(lines) or lines[nxt][:1] not in " \t":
                break
        end += 1
    body = range(start + 1, end)
    keys = [i for i in body if lines[i].strip() and not lines[i].lstrip().startswith("#")]
    child = lines[keys[0]][: _indent(lines[keys[0]])] if keys else "  "
    # the section's own key (one level in), not a deeper one of the same name
    mine = [i for i in keys if lines[i][: _indent(lines[i])] == child]
    at = next((i for i in mine if _EXCLUDE_KEY.match(lines[i])), None)
    if at is None:  # first in the section
        return "\n".join(lines[: start + 1] + _exclude_lines(child, folders) + lines[start + 1 :])
    stop = at + 1
    rest = _EXCLUDE_KEY.match(lines[at]).group("rest")
    comment = re.search(r"(?:^|[ \t])(#.*)$", rest)
    new = _exclude_lines(child, folders)
    if comment:  # the key line's own comment stays
        new[0] += f"  {comment.group(1)}"
    if not _value_of(rest):  # a block list: its items
        while stop < end and (not lines[stop].strip() or _indent(lines[stop]) > len(child) or (
            lines[stop].lstrip().startswith("-") and _indent(lines[stop]) == len(child)
        )):
            stop += 1
        while stop > at + 1 and not lines[stop - 1].strip():  # keep blank lines after it
            stop -= 1
    return "\n".join(lines[:at] + new + lines[stop:])


def write_ai_exclude_folders(app_paths: AppPaths, folders: list[str]) -> Path:
    """Set ``ai.exclude_folders`` in the settings file to ``folders`` (already cleaned),
    replacing the defaults. Comments elsewhere are kept; the file it replaces is saved as
    a ``.bak-<time>`` copy. Verified by reading the settings back; restored on failure."""
    app_paths.ensure()
    target = settings_path(app_paths)
    original = target.read_bytes()
    nl = newline_of(original)
    text = original.decode("utf-8").replace("\r\n", "\n")
    new = with_ai_exclude_folders(text, folders)
    if new == text:
        return target
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        with open(target.with_name(f"{target.name}.bak-{stamp}"), "xb") as fh:
            fh.write(original)
    except FileExistsError:
        pass  # a backup from this very second exists already
    try:
        with open(target, "w", encoding="utf-8", newline=nl) as f:
            f.write(new)
        if load_settings(app_paths).ai.exclude_folders != folders:
            raise OSError("the settings did not read back as written")
    except (OSError, ValueError, yaml.YAMLError):
        with open(target, "wb") as f:
            f.write(original)
        raise
    return target
