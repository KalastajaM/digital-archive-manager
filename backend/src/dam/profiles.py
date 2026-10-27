"""Archives (profiles): several fully separate archives, each with its own data folder.

``<base>/archives.yaml`` lists them. ``<base>`` is the platform data folder (or
``DAM_DATA_DIR`` / ``--data-dir``). A profile is nothing but a data folder with the usual
layout (``config/``, ``dam.sqlite``, ``cache/``, ``logs/``, exports): the database, the
settings, the rules, the logs, the reminder state and the AI on/off state of one archive
never mix with another's.

* An existing single-archive install is adopted as the profile "Main" with ``data_dir:
  <base>`` itself: nothing is moved, renamed or rewritten, only ``archives.yaml`` is
  created. A new profile lives in ``<base>/archives/<id>``.
* Forgetting a profile only removes its line from ``archives.yaml``. Neither its data
  folder nor its archive folder is ever touched (``tests/test_no_delete.py`` pins that
  nothing in this package deletes).
* Two profiles never share an archive folder, never nest one inside another and never
  keep an archive folder inside a data folder (``root_conflict``).
* ``ServeLock``: one process serves a profile, or changes it from the command line, at a
  time.
"""

import contextlib
import dataclasses
import json
import os
import re
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

from dam import setup
from dam.config import AppPaths
from dam.core.fs import open_nofollow, resolve
from dam.core.text import fold_name
from dam.services.errors import Conflict, InvalidRequest, NotFound

try:  # POSIX
    import fcntl
except ImportError:  # pragma: no cover - platform dependent
    fcntl = None
    import msvcrt

REGISTRY_NAME = "archives.yaml"
MAIN_ID = "main"
MAIN_NAME = "Main"
SUBFOLDER = "archives"  # <base>/archives/<id>: where new profiles live
MAX_NAME = 40
LOCK_NAME = "serve.lock"
INFO_NAME = "serve.json"

# (label, colour): the profile colour shown as a dot and a thin band
PALETTE: list[tuple[str, str]] = [
    ("Blue", "#3b6fd4"),
    ("Orange", "#d9822b"),
    ("Purple", "#8a5cc7"),
    ("Teal", "#1f8a8a"),
    ("Red", "#c84b4b"),
    ("Green", "#2f8f5b"),
    ("Pink", "#c44f8f"),
    ("Gray", "#6b7280"),
]
_HEX = re.compile(r"#[0-9a-fA-F]{6}")
_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    color: str
    data_dir: Path
    active: bool = False

    @property
    def paths(self) -> AppPaths:
        return AppPaths(self.data_dir)

    @property
    def archive_root(self) -> str | None:
        """The archive folder written in this profile's settings (None: not set up)."""
        return setup.current_archive_root(self.paths)


def default_base() -> Path:
    """``DAM_DATA_DIR`` or the platform's data folder (same rule as ``AppPaths``)."""
    return AppPaths().data_dir


def clean_name(raw: str) -> str:
    name = " ".join(unicodedata.normalize("NFC", raw).split())
    if not name:
        raise InvalidRequest("Give the archive a name.")
    if len(name) > MAX_NAME:
        raise InvalidRequest(f"Use a name of at most {MAX_NAME} characters.")
    if any(unicodedata.category(c).startswith("C") for c in name):
        raise InvalidRequest("The name cannot contain control characters.")
    return name


def clean_color(raw: str) -> str:
    value = raw.strip()
    if not _HEX.fullmatch(value):
        raise InvalidRequest("Use a colour like #3b6fd4.")
    return value.lower()


def slugify(name: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")
    return slug[:40].strip("-") or "archive"


class ProfileStore:
    """The registry ``<base>/archives.yaml``: read it, change it, write it back.

    Every change loads the file, changes the list and writes it again, so another
    process's change is not lost. ``load`` writes nothing (``persist`` only for
    adopting an existing single-archive folder)."""

    def __init__(self, base: Path | None = None) -> None:
        self.base = (default_base() if base is None else Path(base)).expanduser().absolute()

    @property
    def path(self) -> Path:
        return self.base / REGISTRY_NAME

    # -- reading ------------------------------------------------------------------------

    def _has_single_layout(self) -> bool:
        return (self.base / "config" / "settings.yaml").exists() or (
            self.base / "dam.sqlite"
        ).exists()

    def _main(self) -> Profile:
        return Profile(MAIN_ID, MAIN_NAME, PALETTE[0][1], self.base, True)

    def load(self, persist: bool = False) -> list[Profile]:
        """The profiles, in order; exactly one is active. Without ``archives.yaml`` the
        folder itself is "Main" (written to disk only with ``persist`` and only when the
        folder already holds a single-archive layout)."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            profiles = [self._main()]
            if persist and self._has_single_layout():
                self._save(profiles)
            return profiles
        except OSError as e:
            raise InvalidRequest(f"Cannot read {self.path}: {e.strerror or e}") from None
        try:
            raw = yaml.safe_load(text) or {}
            profiles = self._parse(raw)
        except (yaml.YAMLError, ValueError, TypeError, AttributeError) as e:
            raise InvalidRequest(
                f"Cannot read {self.path}: {e}. Fix or remove that file (your archives "
                "and their data folders are not touched)."
            ) from None
        return profiles or [self._main()]

    def _parse(self, raw: object) -> list[Profile]:
        if not isinstance(raw, dict) or not isinstance(raw.get("archives", []), list):
            raise ValueError("expected a list under 'archives'")
        out: list[Profile] = []
        for i, entry in enumerate(raw.get("archives") or [], 1):
            if not isinstance(entry, dict):
                raise ValueError(f"archive {i} is not a mapping")
            pid = str(entry.get("id", ""))
            if not _ID.fullmatch(pid):
                raise ValueError(f"archive {i} has no valid id")
            if any(p.id == pid for p in out):
                raise ValueError(f"the id '{pid}' is used twice")
            data_dir = Path(str(entry.get("data_dir", ""))).expanduser()
            if not str(entry.get("data_dir", "")).strip():
                raise ValueError(f"archive '{pid}' has no data_dir")
            if not data_dir.is_absolute():
                data_dir = self.base / data_dir
            color = str(entry.get("color", ""))
            out.append(
                Profile(
                    pid,
                    clean_name(str(entry.get("name") or pid)),
                    color.lower() if _HEX.fullmatch(color) else PALETTE[0][1],
                    data_dir,
                    entry.get("active") is True,
                )
            )
        if not out:
            return out
        first = next((i for i, p in enumerate(out) if p.active), 0)
        return [dataclasses.replace(p, active=i == first) for i, p in enumerate(out)]

    def active(self) -> Profile:
        return next(p for p in self.load() if p.active)

    def find(self, key: str, profiles: list[Profile] | None = None) -> Profile:
        """A profile by id, else by name (case-insensitive)."""
        profiles = self.load() if profiles is None else profiles
        text = key.strip()
        for p in profiles:
            if p.id == text:
                return p
        wanted = fold_name(text)
        for p in profiles:
            if fold_name(p.name) == wanted:
                return p
        raise NotFound(f"There is no archive called '{key}'.")

    # -- writing ------------------------------------------------------------------------

    def _save(self, profiles: list[Profile]) -> None:
        doc = {
            "archives": [
                {
                    "id": p.id,
                    "name": p.name,
                    "color": p.color,
                    "data_dir": str(p.data_dir),
                    "active": p.active,
                }
                for p in profiles
            ]
        }
        header = (
            "# The archives dam knows. Each one has its own data folder (settings, index,\n"
            "# logs). Removing an entry here forgets the archive; no folder is deleted.\n"
        )
        text = header + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)
        self.base.mkdir(parents=True, exist_ok=True)
        # In place, not via a temp file + rename: renames live in dam/ops only
        # (tests/test_no_delete.py). The old bytes are put back if the write fails.
        try:
            original = self.path.read_bytes()
        except FileNotFoundError:
            original = None
        try:
            with open(self.path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            if [(p.id, p.name, p.color, p.active) for p in self.load()] != [
                (p.id, p.name, p.color, p.active) for p in profiles
            ]:
                raise OSError("the archive list did not read back as written")
        except (OSError, InvalidRequest):
            if original is not None:
                with open(self.path, "wb") as f:
                    f.write(original)
            raise

    def _write(self, profiles: list[Profile]) -> None:
        self._save(profiles)

    def _unique_name(self, name: str, profiles: list[Profile], skip: str | None = None) -> None:
        if any(fold_name(p.name) == fold_name(name) for p in profiles if p.id != skip):
            raise Conflict(f"There is already an archive called '{name}'.")

    def check_new_name(self, name: str) -> str:
        """The cleaned ``name`` if a new archive may have it (Conflict if taken)."""
        cleaned = clean_name(name)
        self._unique_name(cleaned, self.load())
        return cleaned

    def _free_id(self, name: str, profiles: list[Profile]) -> str:
        base = slugify(name)
        taken = {p.id for p in profiles}
        n = 1
        while True:
            pid = base if n == 1 else f"{base}-{n}"
            if pid not in taken and not os.path.lexists(self.base / SUBFOLDER / pid):
                return pid
            n += 1

    def next_color(self, profiles: list[Profile] | None = None) -> str:
        used = {p.color for p in (self.load() if profiles is None else profiles)}
        for _label, color in PALETTE[1:] + PALETTE[:1]:
            if color not in used:
                return color
        return PALETTE[1][1]

    def add(self, name: str, color: str | None = None) -> Profile:
        """Register a new profile and make its (empty, seeded) data folder. It is not
        made active."""
        name = clean_name(name)
        profiles = self.load()
        self._unique_name(name, profiles)
        pid = self._free_id(name, profiles)
        chosen = clean_color(color) if color else self.next_color(profiles)
        profile = Profile(pid, name, chosen, self.base / SUBFOLDER / pid, False)
        profile.paths.ensure()  # config seeded from the shipped defaults; nothing else
        self._write([*profiles, profile])
        return profile

    def set_active(self, key: str) -> Profile:
        profiles = self.load()
        target = self.find(key, profiles)
        self._write([dataclasses.replace(p, active=p.id == target.id) for p in profiles])
        return dataclasses.replace(target, active=True)

    def set_name(self, key: str, new_name: str) -> Profile:
        name = clean_name(new_name)
        profiles = self.load()
        target = self.find(key, profiles)
        self._unique_name(name, profiles, skip=target.id)
        updated = dataclasses.replace(target, name=name)
        self._write([updated if p.id == target.id else p for p in profiles])
        return updated

    def recolor(self, key: str, color: str) -> Profile:
        value = clean_color(color)
        profiles = self.load()
        target = self.find(key, profiles)
        updated = dataclasses.replace(target, color=value)
        self._write([updated if p.id == target.id else p for p in profiles])
        return updated

    def forget(self, key: str, switch_to: str | None = None) -> Profile:
        """Remove the profile from the registry (and nothing else: no folder is touched).
        The last one cannot be forgotten; forgetting the active one needs ``switch_to``
        (another profile, which becomes active). Returns the forgotten profile."""
        profiles = self.load()
        target = self.find(key, profiles)
        if len(profiles) == 1:
            raise Conflict(
                f"'{target.name}' is your only archive, so it cannot be forgotten. "
                "Add another archive first."
            )
        rest = [p for p in profiles if p.id != target.id]
        if target.active:
            if switch_to is None:
                raise Conflict(
                    f"'{target.name}' is the archive in use. Choose which archive to open "
                    "instead (switch to it first), then forget this one."
                )
            heir = self.find(switch_to, rest)
            rest = [dataclasses.replace(p, active=p.id == heir.id) for p in rest]
        self._write(rest)
        return target

    # -- the isolation guards -----------------------------------------------------------

    def root_guard(self, current_id: str | None) -> Callable[[Path], str | None]:
        """A check for ``setup.check_archive_path``: why a folder cannot be the archive
        folder of profile ``current_id`` (None: it can)."""

        def guard(path: Path) -> str | None:
            return root_conflict(path, self.load(), self.base, current_id)

        return guard

    def root_problems(self) -> dict[str, str]:
        """Profiles whose configured archive folder breaks the isolation rules, by id
        (a hand-edited settings file can do that)."""
        profiles = self.load()
        out: dict[str, str] = {}
        for p in profiles:
            root = p.archive_root
            if root:
                message = root_conflict(Path(root).expanduser(), profiles, self.base, p.id)
                if message:
                    out[p.id] = message
                    continue
            for extra in setup.current_extra_folders(p.paths):
                message = root_conflict(extra, profiles, self.base, p.id)
                if message:
                    out[p.id] = message
                    break
        return out


# -- paths that may not overlap -------------------------------------------------------


def _real(path: Path) -> Path:
    try:
        return resolve(path.expanduser())
    except (OSError, RuntimeError):
        return path.expanduser().absolute()


def _case_insensitive(path: Path) -> bool:
    """Does the file system holding ``path`` ignore case? Probed on the nearest existing
    folder up the path; the platform's usual answer when it cannot tell."""
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    name = probe.name
    swapped = name.swapcase()
    if name and swapped != name:
        other = probe.parent / swapped
        try:
            return other.exists() and os.path.samefile(probe, other)
        except OSError:
            pass
    return sys.platform in ("darwin", "win32")


def _keys(*paths: Path) -> list[str]:
    real = [_real(p) for p in paths]
    fold = any(_case_insensitive(p) for p in real)
    out = []
    for p in real:
        text = unicodedata.normalize("NFC", str(p))
        out.append(text.casefold() if fold else text)
    return out


def related(a: Path, b: Path) -> str | None:
    """``"same"``, ``"inside"`` (a is inside b), ``"around"`` (a contains b) or None;
    resolved real paths, case-insensitive where the file system is."""
    ka, kb = _keys(a, b)
    if ka == kb:
        return "same"
    sep = os.sep
    if ka.startswith(kb.rstrip(sep) + sep):
        return "inside"
    if kb.startswith(ka.rstrip(sep) + sep):
        return "around"
    return None


def root_conflict(
    candidate: Path, profiles: list[Profile], base: Path, current_id: str | None
) -> str | None:
    """Why ``candidate`` cannot be the archive folder of profile ``current_id``, or None.

    It may not touch any profile's data folder (or the folder holding ``archives.yaml``),
    and may not be, contain or sit inside another profile's archive folder or one of its
    extra folders."""
    for p in profiles:
        if related(candidate, p.data_dir):
            return (
                f"That folder overlaps the data folder of the archive '{p.name}'. Choose another."
            )
    if related(candidate, base):
        return "That folder overlaps the app's own data folder. Choose another."
    for p in profiles:
        if p.id == current_id:
            continue
        root = p.archive_root
        how = related(candidate, Path(root).expanduser()) if root else None
        if how == "same":
            return f"That folder is already the archive folder of '{p.name}'. Choose another."
        if how == "inside":
            return f"That folder is inside the archive folder of '{p.name}'. Choose another."
        if how == "around":
            return f"That folder contains the archive folder of '{p.name}'. Choose another."
        for extra in setup.current_extra_folders(p.paths):
            how = related(candidate, extra)
            if how == "same":
                return (
                    f"That folder is already an extra archive folder of '{p.name}'. Choose another."
                )
            if how == "inside":
                return (
                    f"That folder is inside an extra archive folder of '{p.name}'. Choose another."
                )
            if how == "around":
                return (
                    f"That folder contains an extra archive folder of '{p.name}'. Choose another."
                )
    return None


# -- one server per profile ------------------------------------------------------------


class Locked(Exception):
    """Another process holds this profile: a server (``port`` is its port when known) or
    a command that changes it (``command``, e.g. ``"dam scan"``)."""

    def __init__(self, data_dir: Path, port: int | None, command: str | None = None) -> None:
        self.data_dir = data_dir
        self.port = port
        self.command = command
        if command:
            message = (
                f"A dam command ({command}) is changing this archive right now. "
                "Wait for it to finish, then try again."
            )
        else:
            message = (
                "This archive is already open in another dam window"
                + (f" (on port {port})" if port else "")
                + ". Close that one first, or use it."
            )
        super().__init__(message)


def _try_lock(fh) -> bool:
    if fcntl is not None:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True
    try:  # pragma: no cover - Windows
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return False
    return True


def _unlock(fh) -> None:
    if fcntl is not None:
        with contextlib.suppress(OSError):
            fcntl.flock(fh, fcntl.LOCK_UN)
    else:  # pragma: no cover - Windows
        with contextlib.suppress(OSError):
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)


def _read_info(data_dir: Path) -> dict:
    try:
        raw = json.loads((data_dir / INFO_NAME).read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def _command(info: dict) -> str | None:
    """The command named in ``serve.json``, when a command (not a server) holds the lock."""
    command = info.get("command")
    return command if info.get("kind") == "cli" and isinstance(command, str) else None


class ServeLock:
    """``<data dir>/serve.lock``: held (an OS lock, gone when the process ends, even a
    crash) by the process that serves the profile, or by a command that changes it
    (``dam scan``, ``dam file``, ...), so the two never write at once. ``serve.json``
    beside it says who: ``kind`` "serve" with the port, or "cli" with the command; it
    only means something while the lock is held."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self._fh = None

    def acquire(self, port: int | None = None, command: str | None = None) -> None:
        """Take the lock or raise ``Locked``. ``command``: a command takes it (``"dam
        file"``), not a server."""
        if self._fh is not None:
            return
        self.data_dir.mkdir(parents=True, exist_ok=True)
        try:
            fd = open_nofollow(self.data_dir / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as e:
            raise InvalidRequest(
                f"Cannot open the lock file in {self.data_dir}: {e.strerror or e}"
            ) from None
        fh = os.fdopen(fd, "r+", encoding="utf-8")
        if not _try_lock(fh):
            fh.close()
            info = _read_info(self.data_dir)
            raise Locked(self.data_dir, info.get("port"), _command(info))
        self._fh = fh
        self._write_info(port, command)

    def publish(self, port: int) -> None:
        """Say on which port this process serves the profile (after ``acquire``)."""
        if self._fh is None:
            return
        self._write_info(port, None)

    def _write_info(self, port: int | None, command: str | None) -> None:
        info: dict = {"pid": os.getpid(), "port": port, "since": datetime.now().isoformat()}
        info["kind"] = "cli" if command else "serve"
        if command:
            info["command"] = command
        with contextlib.suppress(OSError):
            (self.data_dir / INFO_NAME).write_text(json.dumps(info), encoding="utf-8")

    def release(self) -> None:
        if self._fh is None:
            return
        _unlock(self._fh)
        self._fh.close()
        self._fh = None

    @property
    def held(self) -> bool:
        return self._fh is not None

    @staticmethod
    def holder(data_dir: Path) -> dict | None:
        """Who holds ``data_dir`` right now (``{"port": ..., "command": ...}``: a
        server's port, or the command that changes it), or None when nobody does.
        Writes nothing. Do not call it for a folder this process holds itself."""
        path = Path(data_dir) / LOCK_NAME
        if not path.exists():
            return None
        try:
            fd = open_nofollow(path, os.O_RDWR)
        except OSError:
            return None
        with os.fdopen(fd, "r+", encoding="utf-8") as fh:
            if _try_lock(fh):
                _unlock(fh)
                return None
        info = _read_info(Path(data_dir))
        return {"port": info.get("port"), "command": _command(info)}
