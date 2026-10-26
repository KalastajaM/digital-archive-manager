"""Snapshots of one archive's database and settings: take, export, import, restore.

A snapshot is one zip in ``<data dir>/snapshots/``: ``dam.sqlite`` (taken with SQLite's
online backup API, so it is consistent while the app runs), the whole ``config/``
folder, the small state files beside it (``STATE_FILES``) and ``manifest.json``. The
cache, the logs, the lock files, the archives list and the archive's own files are not
in it. Passwords and the AI key are in the Keychain, never in a snapshot.

A snapshot in the data folder does not survive a failed disk: exporting one (a plain
download of the zip) puts a copy wherever the user wants it, and importing one (a zip
picked anywhere) checks it in full and adds it to the list under a new name.

Restoring never deletes anything. The snapshot is unpacked and checked first (safe
member names, ``PRAGMA integrity_check``, readable settings, a migration revision this
app knows), and its database is migrated to this app's revision in the unpacked copy. A
snapshot of another archive folder (another computer, a moved folder) is restored only
when the caller says so, and then keeps this archive's own folders in its settings.
Only then, with the archive closed (``apply_restore`` runs inside
``Host.close_and_reopen``), the copy is written into the live ``dam.sqlite`` with the
backup API and the current ``config/`` and state files are moved aside to
``snapshots/replaced-<time>/`` (``rename_excl``) before the snapshot's are moved in. The
app takes no snapshots by itself and removes none; old ones are the user's to remove.
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

from dam import settings_write
from dam.config import AppPaths, ExtraFolder, Settings
from dam.db.engine import MIGRATIONS_DIR, make_engine, migrate
from dam.ops.primitives import rename_excl
from dam.services.errors import Conflict, InvalidRequest, NotFound

log = logging.getLogger(__name__)

FORMAT = 1
FOLDER = "snapshots"
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
IMPORTED_SUFFIX = "-imported"
MAX_IMPORT_BYTES = 2 * 1024**3
_NAME = re.compile(r"dam-snapshot-\d{8}-\d{6}(?:-\d+)?(?:-before-restore)?(?:-imported)?\.zip")


@dataclass(frozen=True)
class SnapshotInfo:
    name: str
    created_at: str
    size: int
    kind: str
    imported: bool  # added with Import (made elsewhere, or exported and brought back)
    revision: str | None
    app_version: str | None
    archive_root: str | None
    # made for another archive folder: a restore keeps this archive's folders
    other_folder: bool
    problem: str | None  # why it cannot be restored here; None when it can


@dataclass(frozen=True)
class Folders:
    """This archive's folders, as its settings have them now."""

    archive_root: Path | None
    extra_folders: tuple[ExtraFolder, ...] = ()


def snapshots_dir(paths: AppPaths) -> Path:
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
        return "The snapshot's database has no revision."
    try:
        known = _script().get_revision(revision) is not None
    except CommandError:
        known = False
    if not known:
        return (
            f"The snapshot was made by a newer or different version of dam (database "
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


# -- taking a snapshot --------------------------------------------------------------------


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
    return sorted(p for p in paths.config_dir.rglob("*") if p.is_file())


def _free_name(folder: Path, stamp: str, suffix: str) -> str:
    for n in range(1, 1000):
        extra = "" if n == 1 else f"-{n}"
        name = f"dam-snapshot-{stamp}{extra}{suffix}.zip"
        if not os.path.lexists(folder / name):
            return name
    raise Conflict("Too many snapshots with the same time.")  # pragma: no cover


def create_snapshot(
    paths: AppPaths, kind: str = MANUAL, now: datetime | None = None
) -> SnapshotInfo:
    """Write a new snapshot zip into ``snapshots/`` and return what it holds. The zip is
    built in a temporary folder there and moved into place in one step, so a failed
    snapshot leaves no half-written zip."""
    now = now or datetime.now().astimezone()
    folder = snapshots_dir(paths)
    folder.mkdir(parents=True, exist_ok=True)
    settings = yaml.safe_load((paths.config_dir / "settings.yaml").read_text(encoding="utf-8"))
    root = (settings or {}).get("archive_root")
    with tempfile.TemporaryDirectory(dir=folder, prefix=".making-") as tmp:
        work = Path(tmp)
        db_copy = work / DB_NAME
        _copy_db(paths.db_path, db_copy)
        revision = db_revision(db_copy)
        files = [DB_NAME]
        zip_path = work / "snapshot.zip"
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
        suffix = "-before-restore" if kind == BEFORE_RESTORE else ""
        name = _free_name(folder, now.strftime("%Y%m%d-%H%M%S"), suffix)
        rename_excl(zip_path, folder / name)
    log.info("snapshot %s taken (%s, revision %s)", name, kind, revision)
    return read_info(paths, name)


# -- reading snapshots --------------------------------------------------------------------


def path_of(paths: AppPaths, name: str) -> Path:
    """The snapshot called ``name`` in this archive's folder (never a client path)."""
    if not _NAME.fullmatch(name):
        raise InvalidRequest("Not a snapshot name.")
    path = snapshots_dir(paths) / name
    if path.is_symlink() or not path.is_file():
        raise NotFound(f"There is no snapshot called {name}.")
    return path


def _read_manifest(zf: zipfile.ZipFile) -> dict:
    try:
        manifest = json.loads(zf.read(MANIFEST).decode("utf-8"))
    except (KeyError, ValueError) as e:
        raise InvalidRequest("The snapshot has no readable manifest.") from e
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise InvalidRequest("The snapshot is in a format this version of dam does not know.")
    return manifest


def _same_folder(a: str | Path | None, b: Path | None) -> bool:
    if not a or b is None:
        return False
    return Path(a).expanduser().resolve() == Path(b).expanduser().resolve()


def read_info(paths: AppPaths, name: str, archive_root: Path | None = None) -> SnapshotInfo:
    path = path_of(paths, name)
    problem = None
    manifest: dict = {}
    try:
        with zipfile.ZipFile(path) as zf:
            manifest = _read_manifest(zf)
    except (zipfile.BadZipFile, InvalidRequest, OSError) as e:
        problem = str(e) or "The snapshot cannot be read."
    if problem is None:
        problem = _revision_problem(manifest.get("revision"))
    other = archive_root is not None and not _same_folder(
        manifest.get("archive_root"), archive_root
    )
    created = manifest.get("created_at") or datetime.fromtimestamp(
        path.stat().st_mtime
    ).astimezone().isoformat(timespec="seconds")
    return SnapshotInfo(
        name=name,
        created_at=str(created),
        size=path.stat().st_size,
        kind=str(manifest.get("kind") or MANUAL),
        imported=name.endswith(f"{IMPORTED_SUFFIX}.zip"),
        revision=manifest.get("revision"),
        app_version=manifest.get("app_version"),
        archive_root=manifest.get("archive_root"),
        other_folder=problem is None and other,
        problem=problem,
    )


def list_snapshots(paths: AppPaths, archive_root: Path | None = None) -> list[SnapshotInfo]:
    """The snapshots in this archive's folder, newest first."""
    folder = snapshots_dir(paths)
    if not folder.is_dir():
        return []
    names = [p.name for p in folder.iterdir() if _NAME.fullmatch(p.name) and p.is_file()]
    infos = [read_info(paths, n, archive_root) for n in names]
    return sorted(infos, key=lambda i: (i.created_at, i.name), reverse=True)


# -- checking a snapshot ------------------------------------------------------------------


def _member_target(name: str) -> PurePosixPath | None:
    """The relative path a zip member may be unpacked to; None for a folder entry.
    Anything else (an absolute path, ``..``, a name we never write) is refused."""
    if name.endswith("/"):
        return None
    rel = PurePosixPath(name)
    if "\\" in name or rel.is_absolute() or any(p in ("", ".", "..") for p in name.split("/")):
        raise InvalidRequest(f"The snapshot holds an unsafe entry: {name}")
    if name in (MANIFEST, DB_NAME, *STATE_FILES) or rel.parts[0] == CONFIG and len(rel.parts) > 1:
        return rel
    raise InvalidRequest(f"The snapshot holds an unexpected entry: {name}")


def _unpack(zf: zipfile.ZipFile, target: Path) -> None:
    for info in zf.infolist():
        rel = _member_target(info.filename)
        if rel is None:
            continue
        if stat.S_ISLNK(info.external_attr >> 16):
            raise InvalidRequest(f"The snapshot holds a link: {info.filename}")
        dest = target.joinpath(*rel.parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, dest.open("xb") as out:
            shutil.copyfileobj(src, out)


def _unpack_and_check(zip_path: Path, work: Path) -> tuple[dict, Settings]:
    """Unpack ``zip_path`` into ``work`` and check it: the manifest, every entry, the
    database's integrity and revision, the settings. Returns the manifest and settings."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            manifest = _read_manifest(zf)
            _unpack(zf, work)
    except zipfile.BadZipFile as e:
        raise InvalidRequest("That file is not a dam snapshot (not a zip file).") from e
    db = work / DB_NAME
    if not db.is_file():
        raise InvalidRequest("The snapshot has no database.")
    con = sqlite3.connect(db)
    try:
        check = con.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.DatabaseError as e:
        raise InvalidRequest(f"The snapshot's database cannot be read: {e}") from e
    finally:
        con.close()
    if not check or check[0] != "ok":
        raise InvalidRequest("The snapshot's database is damaged (integrity check failed).")
    problem = _revision_problem(db_revision(db))
    if problem:
        raise Conflict(problem)
    settings_file = work / CONFIG / "settings.yaml"
    if not settings_file.is_file():
        raise InvalidRequest("The snapshot has no settings.yaml.")
    try:
        raw = yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}
        settings = Settings.model_validate(raw)
    except Exception as e:
        raise InvalidRequest(f"The snapshot's settings cannot be read: {e}") from e
    return manifest, settings


# -- importing ----------------------------------------------------------------------------


def import_snapshot(paths: AppPaths, source: Path) -> SnapshotInfo:
    """Check the zip ``source`` in full and copy it into ``snapshots/`` as
    ``dam-snapshot-<its time>-imported.zip``. ``source`` itself is left alone."""
    folder = snapshots_dir(paths)
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder, prefix=".importing-") as tmp:
        manifest, _settings = _unpack_and_check(source, Path(tmp) / "unpacked")
        try:
            made = datetime.fromisoformat(str(manifest.get("created_at")))
        except ValueError:
            made = datetime.now().astimezone()
        copy = Path(tmp) / "snapshot.zip"
        with source.open("rb") as src, copy.open("xb") as out:
            shutil.copyfileobj(src, out)
        name = _free_name(folder, made.strftime("%Y%m%d-%H%M%S"), IMPORTED_SUFFIX)
        rename_excl(copy, folder / name)
    log.info("snapshot %s imported (revision %s)", name, manifest.get("revision"))
    return read_info(paths, name)


# -- restoring ----------------------------------------------------------------------------


@dataclass
class StagedRestore:
    """A snapshot unpacked, checked and migrated, ready for ``apply_restore``."""

    name: str
    folder: Path  # the unpacked snapshot (inside a temporary folder in snapshots/)
    revision: str
    kept_folders: bool  # its folder settings were replaced by this archive's


def _keep_folders(settings_file: Path, folders: Folders) -> None:
    """Point the unpacked settings at this archive's own folders."""
    text = settings_file.read_bytes().decode("utf-8").replace("\r\n", "\n")
    extra = [
        {"label": e.label, "path": str(e.path), "attached": e.attached}
        for e in folders.extra_folders
    ]
    updates = {"archive_root": str(folders.archive_root), "extra_folders": extra}
    settings_file.write_text(settings_write.with_keys(text, updates), encoding="utf-8")
    raw = yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}
    if not _same_folder(Settings.model_validate(raw).archive_root, folders.archive_root):
        raise InvalidRequest("Could not set this archive's folder in the snapshot's settings.")


def stage(
    paths: AppPaths, name: str, folders: Folders, other_folder_ok: bool, work: Path
) -> StagedRestore:
    """Unpack snapshot ``name`` into ``work`` and check everything that can be checked
    while the archive stays open. A snapshot of another archive folder needs
    ``other_folder_ok`` and then keeps ``folders``. Raises with a plain message; nothing
    in the data folder is changed."""
    info = read_info(paths, name, folders.archive_root)
    if info.problem:
        raise Conflict(info.problem)
    _manifest, settings = _unpack_and_check(path_of(paths, name), work)
    other = folders.archive_root is not None and not _same_folder(
        settings.archive_root, folders.archive_root
    )
    if other and not other_folder_ok:
        raise Conflict(
            f"The snapshot is of another archive folder ({settings.archive_root}). Confirm "
            "to restore it with this archive's own folders."
        )
    if other:
        _keep_folders(work / CONFIG / "settings.yaml", folders)
    # bring the copy to this app's revision now, so reopening after the swap only opens it
    db = work / DB_NAME
    engine = make_engine(db)
    try:
        migrate(engine)
    except Exception as e:
        raise InvalidRequest(f"The snapshot's database could not be updated: {e}") from e
    finally:
        engine.dispose()
    return StagedRestore(name, work, db_revision(db) or "", other)


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
    """Put the staged snapshot in place; the archive must be closed. Returns the folder
    the replaced settings were moved to (nothing is deleted)."""
    now = now or datetime.now().astimezone()
    _write_db(staged.folder / DB_NAME, paths.db_path)
    folder = snapshots_dir(paths)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    replaced = folder / f"replaced-{stamp}"
    n = 1
    while os.path.lexists(replaced):
        n += 1
        replaced = folder / f"replaced-{stamp}-{n}"
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
        "restored snapshot %s (revision now %s%s); previous settings in %s",
        staged.name,
        staged.revision,
        ", this archive's folders kept" if staged.kept_folders else "",
        replaced,
    )
    return replaced
