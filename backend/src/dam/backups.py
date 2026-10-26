"""Backups of one archive's database and settings, and restoring one.

A backup is one zip in ``<data dir>/backups/``: ``dam.sqlite`` (taken with SQLite's
online backup API, so it is consistent while the app runs), the whole ``config/``
folder, the small state files beside it (``STATE_FILES``) and ``manifest.json``. The
cache, the logs, the lock files, the archives list and the archive's own files are not
in it. Passwords and the AI key are in the Keychain, never in a backup.

Restoring never deletes anything. The backup is unpacked and checked first (safe member
names, ``PRAGMA integrity_check``, readable settings, a migration revision this app
knows, the same archive folder), and its database is migrated to this app's revision in
the unpacked copy. Only then, with the archive closed (``apply_restore`` runs inside
``Host.reopen``), the copy is written into the live ``dam.sqlite`` with the backup API
and the current ``config/`` and state files are moved aside to
``backups/replaced-<time>/`` (``rename_excl``) before the backup's are moved in. The
app makes no backups by itself and removes none; old ones are the user's to remove.
"""

import json
import logging
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath

import yaml
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError

from dam.config import AppPaths, Settings
from dam.db.engine import MIGRATIONS_DIR, make_engine, migrate
from dam.ops.primitives import rename_excl
from dam.services.errors import Conflict, InvalidRequest, NotFound

log = logging.getLogger(__name__)

FORMAT = 1
FOLDER = "backups"
MANIFEST = "manifest.json"
DB_NAME = "dam.sqlite"
CONFIG = "config"
# beside config/: the AI on/off switch, the learned-rules state, the tray defaults record
STATE_FILES = (
    "ai-state.json",
    "rules-state.json",
    "tray-defaults-seeded.json",
    "tray-defaults-dismissed.json",
)
MANUAL, BEFORE_RESTORE = "manual", "before-restore"
_NAME = re.compile(r"dam-backup-\d{8}-\d{6}(?:-\d+)?(?:-before-restore)?\.zip")


@dataclass(frozen=True)
class BackupInfo:
    name: str
    created_at: str
    size: int
    kind: str
    revision: str | None
    app_version: str | None
    archive_root: str | None
    problem: str | None  # why it cannot be restored here; None when it can


def backups_dir(paths: AppPaths) -> Path:
    return paths.data_dir / FOLDER


def app_version() -> str:
    try:
        return version("dam")
    except PackageNotFoundError:  # pragma: no cover - always installed with uv
        return "unknown"


# -- revisions ----------------------------------------------------------------------------


def _script() -> ScriptDirectory:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return ScriptDirectory.from_config(config)


def head_revision() -> str:
    return _script().get_current_head() or ""


def _revision_problem(revision: str | None) -> str | None:
    """None when this app can open a database at ``revision`` (it migrates it up)."""
    if not revision:
        return "The backup's database has no revision."
    try:
        known = _script().get_revision(revision) is not None
    except CommandError:
        known = False
    if not known:
        return (
            f"The backup was made by a newer or different version of dam (database "
            f"revision {revision}). This version cannot open it."
        )
    return None


def db_revision(db: Path) -> str | None:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT version_num FROM alembic_version").fetchone()
        return row[0] if row else None
    except sqlite3.DatabaseError:
        return None
    finally:
        con.close()


# -- taking a backup ----------------------------------------------------------------------


def _copy_db(source: Path, target: Path) -> None:
    """A consistent copy of a live database (WAL included) with the online backup API."""
    src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.execute("PRAGMA busy_timeout=30000")
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _config_files(paths: AppPaths) -> list[Path]:
    """The regular files in ``config/`` (a linked file is read through; linked folders
    are not followed)."""
    root = paths.config_dir
    return sorted(p for p in root.rglob("*") if p.is_file())


def _new_name(folder: Path, kind: str, now: datetime) -> str:
    stamp = now.strftime("%Y%m%d-%H%M%S")
    suffix = "-before-restore" if kind == BEFORE_RESTORE else ""
    for n in range(1, 1000):
        extra = "" if n == 1 else f"-{n}"
        name = f"dam-backup-{stamp}{extra}{suffix}.zip"
        if not os.path.lexists(folder / name):
            return name
    raise Conflict("Too many backups in the same second.")  # pragma: no cover


def create_backup(paths: AppPaths, kind: str = MANUAL, now: datetime | None = None) -> BackupInfo:
    """Write a new backup zip into ``backups/`` and return what it holds. The zip is
    built in a temporary folder there and moved into place in one step, so a failed
    backup leaves no half-written zip."""
    now = now or datetime.now().astimezone()
    folder = backups_dir(paths)
    folder.mkdir(parents=True, exist_ok=True)
    settings = yaml.safe_load((paths.config_dir / "settings.yaml").read_text(encoding="utf-8"))
    root = (settings or {}).get("archive_root")
    with tempfile.TemporaryDirectory(dir=folder, prefix=".making-") as tmp:
        work = Path(tmp)
        db_copy = work / DB_NAME
        _copy_db(paths.db_path, db_copy)
        revision = db_revision(db_copy)
        files = [DB_NAME]
        zip_path = work / "backup.zip"
        with zipfile.ZipFile(zip_path, "x", zipfile.ZIP_DEFLATED) as zf:
            zf.write(db_copy, DB_NAME)
            for p in _config_files(paths):
                arc = f"{CONFIG}/{p.relative_to(paths.config_dir).as_posix()}"
                zf.writestr(arc, p.read_bytes())
                files.append(arc)
            for name in STATE_FILES:
                p = paths.data_dir / name
                if p.is_file():
                    zf.writestr(name, p.read_bytes())
                    files.append(name)
            manifest = {
                "format": FORMAT,
                "created_at": now.isoformat(timespec="seconds"),
                "kind": kind,
                "app_version": app_version(),
                "revision": revision,
                "archive_root": str(root) if root else None,
                "files": files,
            }
            zf.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
        name = _new_name(folder, kind, now)
        rename_excl(zip_path, folder / name)
    log.info("backup %s made (%s, revision %s)", name, kind, revision)
    return read_info(paths, name)


# -- reading backups ----------------------------------------------------------------------


def _path_of(paths: AppPaths, name: str) -> Path:
    """The backup called ``name`` in this archive's backups folder (never a client path)."""
    if not _NAME.fullmatch(name):
        raise InvalidRequest("Not a backup name.")
    path = backups_dir(paths) / name
    if path.is_symlink() or not path.is_file():
        raise NotFound(f"There is no backup called {name}.")
    return path


def _read_manifest(zf: zipfile.ZipFile) -> dict:
    try:
        manifest = json.loads(zf.read(MANIFEST).decode("utf-8"))
    except (KeyError, ValueError) as e:
        raise InvalidRequest("The backup has no readable manifest.") from e
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise InvalidRequest("The backup is in a format this version of dam does not know.")
    return manifest


def _same_folder(a: str | None, b: Path | None) -> bool:
    if not a or b is None:
        return False
    return Path(a).expanduser().resolve() == Path(b).expanduser().resolve()


def read_info(paths: AppPaths, name: str, archive_root: Path | None = None) -> BackupInfo:
    path = _path_of(paths, name)
    problem = None
    manifest: dict = {}
    try:
        with zipfile.ZipFile(path) as zf:
            manifest = _read_manifest(zf)
    except (zipfile.BadZipFile, InvalidRequest, OSError) as e:
        problem = str(e) or "The backup cannot be read."
    if problem is None:
        problem = _revision_problem(manifest.get("revision"))
    if problem is None and archive_root is not None:
        if not _same_folder(manifest.get("archive_root"), archive_root):
            problem = (
                f"The backup is of another archive folder ({manifest.get('archive_root')}), "
                "not this one."
            )
    created = manifest.get("created_at") or datetime.fromtimestamp(
        path.stat().st_mtime
    ).astimezone().isoformat(timespec="seconds")
    return BackupInfo(
        name=name,
        created_at=str(created),
        size=path.stat().st_size,
        kind=str(manifest.get("kind") or MANUAL),
        revision=manifest.get("revision"),
        app_version=manifest.get("app_version"),
        archive_root=manifest.get("archive_root"),
        problem=problem,
    )


def list_backups(paths: AppPaths, archive_root: Path | None = None) -> list[BackupInfo]:
    """The backups in this archive's backups folder, newest first."""
    folder = backups_dir(paths)
    if not folder.is_dir():
        return []
    names = [p.name for p in folder.iterdir() if _NAME.fullmatch(p.name) and p.is_file()]
    infos = [read_info(paths, n, archive_root) for n in names]
    return sorted(infos, key=lambda i: (i.created_at, i.name), reverse=True)


# -- restoring ----------------------------------------------------------------------------


def _member_target(name: str) -> PurePosixPath | None:
    """The relative path a zip member may be unpacked to; None for a folder entry.
    Anything else (an absolute path, ``..``, a name we never write) is refused."""
    if name.endswith("/"):
        return None
    rel = PurePosixPath(name)
    if (
        "\\" in name
        or rel.is_absolute()
        or any(part in ("", ".", "..") for part in name.split("/"))
    ):
        raise InvalidRequest(f"The backup holds an unsafe entry: {name}")
    if name in (MANIFEST, DB_NAME, *STATE_FILES) or rel.parts[0] == CONFIG and len(rel.parts) > 1:
        return rel
    raise InvalidRequest(f"The backup holds an unexpected entry: {name}")


def _unpack(zf: zipfile.ZipFile, target: Path) -> None:
    for info in zf.infolist():
        rel = _member_target(info.filename)
        if rel is None:
            continue
        if stat.S_ISLNK(info.external_attr >> 16):
            raise InvalidRequest(f"The backup holds a link: {info.filename}")
        dest = target.joinpath(*rel.parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, dest.open("xb") as out:
            shutil.copyfileobj(src, out)


@dataclass
class StagedRestore:
    """A backup unpacked, checked and migrated, ready for ``apply_restore``."""

    name: str
    folder: Path  # the unpacked backup (inside a temporary folder in backups/)
    revision: str


def stage(paths: AppPaths, name: str, archive_root: Path | None, work: Path) -> StagedRestore:
    """Unpack backup ``name`` into ``work`` and check everything that can be checked
    while the archive stays open. Raises with a plain message; nothing is changed."""
    info = read_info(paths, name, archive_root)
    if info.problem:
        raise Conflict(info.problem)
    with zipfile.ZipFile(_path_of(paths, name)) as zf:
        _unpack(zf, work)
    db = work / DB_NAME
    if not db.is_file():
        raise InvalidRequest("The backup has no database.")
    con = sqlite3.connect(db)
    try:
        check = con.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.DatabaseError as e:
        raise InvalidRequest(f"The backup's database cannot be read: {e}") from e
    finally:
        con.close()
    if not check or check[0] != "ok":
        raise InvalidRequest("The backup's database is damaged (integrity check failed).")
    settings_file = work / CONFIG / "settings.yaml"
    if not settings_file.is_file():
        raise InvalidRequest("The backup has no settings.yaml.")
    try:
        raw = yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}
        settings = Settings.model_validate(raw)
    except Exception as e:
        raise InvalidRequest(f"The backup's settings cannot be read: {e}") from e
    if archive_root is not None and not _same_folder(
        str(settings.archive_root) if settings.archive_root else None, archive_root
    ):
        raise Conflict("The backup's settings are for another archive folder, not this one.")
    # bring the copy to this app's revision now, so reopening after the swap only opens it
    engine = make_engine(db)
    try:
        migrate(engine)
    except Exception as e:
        raise InvalidRequest(f"The backup's database could not be updated: {e}") from e
    finally:
        engine.dispose()
    return StagedRestore(name, work, db_revision(db) or "")


def _write_db(source: Path, live: Path) -> None:
    """Copy ``source`` into the live database file in place, in one transaction."""
    src = sqlite3.connect(source)
    dst = sqlite3.connect(live)
    try:
        dst.execute("PRAGMA busy_timeout=30000")
        # the backup API cannot write into a WAL database with another page size
        dst.execute("PRAGMA journal_mode=DELETE")
        src.backup(dst)
        dst.execute("PRAGMA journal_mode=WAL")
    finally:
        dst.close()
        src.close()


def apply_restore(paths: AppPaths, staged: StagedRestore, now: datetime | None = None) -> Path:
    """Put the staged backup in place; the archive must be closed. Returns the folder the
    replaced settings were moved to (nothing is deleted)."""
    now = now or datetime.now().astimezone()
    _write_db(staged.folder / DB_NAME, paths.db_path)
    folder = backups_dir(paths)
    replaced = folder / f"replaced-{now.strftime('%Y%m%d-%H%M%S')}"
    n = 1
    while os.path.lexists(replaced):
        n += 1
        replaced = folder / f"replaced-{now.strftime('%Y%m%d-%H%M%S')}-{n}"
    replaced.mkdir(parents=True)
    try:
        for name in (CONFIG, *STATE_FILES):
            current = paths.data_dir / name
            if os.path.lexists(current):
                rename_excl(current, replaced / name)
            incoming = staged.folder / name
            if os.path.lexists(incoming):
                rename_excl(incoming, current)
    except BaseException:
        log.exception("restoring the settings of %s failed half way", staged.name)
        raise Conflict(
            f"The database was restored, but the settings could not all be put back. "
            f"The previous settings are in {replaced}."
        ) from None
    log.info(
        "restored backup %s (revision now %s); previous settings in %s",
        staged.name,
        staged.revision,
        replaced,
    )
    return replaced
