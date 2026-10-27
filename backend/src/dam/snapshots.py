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
member names, limits on what it unpacks to, ``PRAGMA integrity_check``, no database
objects dam never makes, readable settings, a migration revision this app knows), and
its database is migrated to this app's revision in the unpacked copy and must then match
dam's own layout exactly (bare revision ids are shared with an older app that had
another layout). A snapshot of another archive folder (another computer, a moved
folder) is restored only when the caller says so. Every restore keeps this archive's own
folders (``archive_root``, ``extra_folders``) in its settings, and keeps every entry of
the current ``protected_paths`` and ``ai.exclude_folders`` (the snapshot may add to
them, never remove from them): a snapshot file can come from anywhere, and these are the
settings that keep documents safe.
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
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import Engine, event

from dam import settings_write
from dam.config import AppPaths, ExtraFolder, Settings, load_settings
from dam.db.engine import MIGRATIONS_DIR, make_engine, migrate, write_tx
from dam.db.tables import metadata
from dam.errors import Conflict, InvalidRequest, NotFound
from dam.ops.primitives import rename_excl

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
BEFORE_RELABEL = "before-relabel"  # taken before an archive folder's label changes
IMPORTED_SUFFIX = "-imported"
MAX_IMPORT_BYTES = 2 * 1024**3
# what one snapshot may unpack to (a zip bomb stops here): members, bytes in all, and how
# much smaller than its content a large member may be packed (deflate tops out near 1000)
MAX_MEMBERS = 10_000
MAX_UNPACKED_BYTES = 16 * 1024**3
MAX_RATIO = 250
_RATIO_FROM = 1024**2  # small members are not held to the ratio
_COPY_CHUNK = 1024**2
# Windows device names: a member called one of these (with any extension) is a device there
_RESERVED = {"con", "prn", "aux", "nul", *(f"{p}{n}" for p in ("com", "lpt") for n in range(10))}
_NAME = re.compile(
    r"dam-snapshot-\d{8}-\d{6}(?:-\d+)?(?:-before-restore|-before-relabel)?(?:-imported)?\.zip"
)


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
        con.execute("PRAGMA trusted_schema=OFF")
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
        suffix = f"-{kind}" if kind in (BEFORE_RESTORE, BEFORE_RELABEL) else ""
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


def _unsafe_part(part: str) -> bool:
    """A name component that is not one plain name on every platform: empty, ``.`` or
    ``..``, a ``:`` (a drive or an alternate data stream on Windows), a Windows device
    name, or a trailing dot or space (Windows drops it)."""
    return (
        part in ("", ".", "..")
        or ":" in part
        or part.split(".", 1)[0].strip().casefold() in _RESERVED
        or part[-1] in ". "
    )


def _member_target(name: str) -> PurePosixPath | None:
    """The relative path a zip member may be unpacked to; None for a folder entry.
    Anything else (an absolute path, ``..``, a drive or stream, a name we never write)
    is refused, on every platform: a snapshot made on one may be restored on another."""
    if name.endswith("/"):
        return None
    rel = PurePosixPath(name)
    if "\\" in name or rel.is_absolute() or any(_unsafe_part(p) for p in name.split("/")):
        raise InvalidRequest(f"The snapshot holds an unsafe entry: {name}")
    if name in (MANIFEST, DB_NAME, *STATE_FILES) or rel.parts[0] == CONFIG and len(rel.parts) > 1:
        return rel
    raise InvalidRequest(f"The snapshot holds an unexpected entry: {name}")


_TOO_BIG = "The snapshot unpacks to more than a dam snapshot can hold; it was not unpacked."


def _check_sizes(infos: list[zipfile.ZipInfo], target: Path) -> None:
    """Refuse a zip that would unpack to too much, from what it declares (the copy
    counts again, since a zip can declare less than it holds)."""
    if len(infos) > MAX_MEMBERS:
        raise InvalidRequest(f"The snapshot holds more than {MAX_MEMBERS} entries.")
    for info in infos:
        if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise InvalidRequest(f"The snapshot holds an entry dam does not write: {info.filename}")
        if info.file_size > _RATIO_FROM and info.file_size > MAX_RATIO * max(info.compress_size, 1):
            raise InvalidRequest(
                f"The snapshot holds an entry packed unusually small: {info.filename}"
            )
    total = sum(info.file_size for info in infos)
    if total > MAX_UNPACKED_BYTES:
        raise InvalidRequest(_TOO_BIG)
    if total > shutil.disk_usage(target).free:
        raise InvalidRequest("There is not enough free disk space to check this snapshot.")


def _copy_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo, dest: Path, room: int) -> int:
    """Copy one member to ``dest``, at most its declared size and ``room``; the bytes
    written."""
    written = 0
    with zf.open(info) as src, dest.open("xb") as out:
        while chunk := src.read(_COPY_CHUNK):
            written += len(chunk)
            if written > info.file_size or written > room:
                raise InvalidRequest(_TOO_BIG)
            out.write(chunk)
    return written


def _unpack(zf: zipfile.ZipFile, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    infos = zf.infolist()
    _check_sizes(infos, target)
    room = MAX_UNPACKED_BYTES
    for info in infos:
        rel = _member_target(info.filename)
        if rel is None:
            continue
        if stat.S_ISLNK(info.external_attr >> 16):
            raise InvalidRequest(f"The snapshot holds a link: {info.filename}")
        dest = target.joinpath(*rel.parts)
        if not dest.resolve().is_relative_to(root):
            raise InvalidRequest(f"The snapshot holds an unsafe entry: {info.filename}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        room -= _copy_member(zf, info, dest, room)


def _untrusted(engine: Engine) -> Engine:
    """``engine`` with the snapshot's schema distrusted: SQL functions in it (views,
    triggers, indexes, defaults) cannot run app functions."""

    @event.listens_for(engine, "connect")
    def _distrust(dbapi_conn, _record) -> None:
        dbapi_conn.execute("PRAGMA trusted_schema=OFF")

    return engine


def _objects(db: Path) -> list[tuple[str, str, str | None]]:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        con.execute("PRAGMA trusted_schema=OFF")
        return con.execute("SELECT type, name, sql FROM sqlite_master").fetchall()
    finally:
        con.close()


def _foreign_objects(db: Path, revision: str, work: Path) -> str | None:
    """Why the snapshot's database holds something dam's migrations never make at
    ``revision`` (a trigger, a view, an unknown or changed table), or None. Compared
    with a fresh database migrated to that revision."""
    reference = work / ".reference.sqlite"
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    engine = make_engine(reference)
    try:
        with write_tx(engine) as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, revision)
    finally:
        engine.dispose()
    known = {name: sql for kind, name, sql in _objects(reference) if kind == "table"}
    for kind, name, sql in _objects(db):
        if kind in ("trigger", "view"):
            return f"The snapshot's database holds a {kind} ({name}), which dam never makes."
        if kind != "table" or name.startswith("sqlite_"):
            continue
        if name not in known:
            return f"The snapshot's database holds a table dam does not know ({name})."
        virtual = (sql or "").lstrip().upper().startswith("CREATE VIRTUAL")
        if virtual and sql != known[name]:
            return f"The snapshot's database has a table dam made differently ({name})."
    return None


_NOT_DAMS = "This snapshot was not made by this version of dam's database layout."


def _include_name(name: str | None, type_: str, _parents: dict) -> bool:
    """compare_metadata leaves out the full-text index's own tables (not in metadata)."""
    return not (
        type_ == "table" and name and name.startswith("file_fts") and name not in metadata.tables
    )


def _migrate_and_compare(db: Path) -> None:
    """Bring the copy to this app's revision, then refuse it unless its layout is dam's."""
    engine = _untrusted(make_engine(db))
    try:
        try:
            migrate(engine, backup=False)  # a copy being checked
        except Exception as e:
            raise InvalidRequest(f"The snapshot's database could not be updated: {e}") from e
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"include_name": _include_name})
            differences = compare_metadata(context, metadata)
    finally:
        engine.dispose()
    if differences:
        log.warning("snapshot database differs from dam's layout: %s", differences[:5])
        raise Conflict(_NOT_DAMS)


def _unpack_and_check(zip_path: Path, work: Path) -> tuple[dict, Settings]:
    """Unpack ``zip_path`` into ``work`` and check it: the manifest, every entry and
    what they unpack to, the database's integrity, revision and layout (migrating the
    copy in ``work`` to this app's revision), the settings. Returns the manifest and
    settings."""
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
        con.execute("PRAGMA trusted_schema=OFF")
        check = con.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.DatabaseError as e:
        raise InvalidRequest(f"The snapshot's database cannot be read: {e}") from e
    finally:
        con.close()
    if not check or check[0] != "ok":
        raise InvalidRequest("The snapshot's database is damaged (integrity check failed).")
    revision = db_revision(db)
    problem = _revision_problem(revision)
    if problem:
        raise Conflict(problem)
    problem = _foreign_objects(db, revision or "", work)
    if problem:
        raise Conflict(problem)
    # bring the copy to this app's revision now, so reopening after a restore only opens it
    _migrate_and_compare(db)
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
    kept_folders: bool  # its folder settings differed and were replaced by this archive's


def _with_current(current: list[str], incoming: list[str]) -> list[str]:
    """Every entry of ``current``, then those ``incoming`` adds."""
    return [*current, *(e for e in incoming if e not in current)]


def _keep_safety_settings(settings_file: Path, folders: Folders, current: Settings) -> bool:
    """Point the unpacked settings at this archive's own folders and keep every entry
    of the current ``protected_paths`` and ``ai.exclude_folders``. True when the
    snapshot's folder settings differed."""
    text = settings_file.read_bytes().decode("utf-8").replace("\r\n", "\n")
    raw = yaml.safe_load(text) or {}
    snap = Settings.model_validate(raw)
    updates: dict[str, object] = {}
    extra = [
        {"label": e.label, "path": str(e.path), "attached": e.attached}
        for e in folders.extra_folders
    ]
    snap_extra = [
        {"label": e.label, "path": str(e.path.expanduser()), "attached": e.attached}
        for e in snap.extra_folders
    ]
    other = not _same_folder(snap.archive_root, folders.archive_root) or snap_extra != extra
    if folders.archive_root is not None:
        updates["archive_root"] = str(folders.archive_root)
        updates["extra_folders"] = extra
    protected = _with_current(current.protected_paths, snap.protected_paths)
    if protected != snap.protected_paths:
        updates["protected_paths"] = protected
    excluded = _with_current(current.ai.exclude_folders, snap.ai.exclude_folders)
    if excluded != snap.ai.exclude_folders:
        ai = raw.get("ai") if isinstance(raw.get("ai"), dict) else {}
        updates["ai"] = {**ai, "exclude_folders": excluded}
        log.info("restore keeps this archive's AI-excluded folders: %s", excluded)
    if "protected_paths" in updates:
        log.info("restore keeps this archive's protected paths: %s", protected)
    settings_file.write_text(settings_write.with_keys(text, updates), encoding="utf-8")
    written = Settings.model_validate(
        yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}
    )
    if (
        folders.archive_root is not None
        and not _same_folder(written.archive_root, folders.archive_root)
        or not set(current.protected_paths) <= set(written.protected_paths)
        or not set(current.ai.exclude_folders) <= set(written.ai.exclude_folders)
    ):
        raise InvalidRequest("Could not keep this archive's settings in the snapshot's settings.")
    return other and folders.archive_root is not None


def stage(
    paths: AppPaths, name: str, folders: Folders, other_folder_ok: bool, work: Path
) -> StagedRestore:
    """Unpack snapshot ``name`` into ``work`` and check everything that can be checked
    while the archive stays open. A snapshot of another archive folder needs
    ``other_folder_ok``. Every restore keeps ``folders`` and the current protected paths
    and AI-excluded folders. Raises with a plain message; nothing in the data folder is
    changed."""
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
    kept = _keep_safety_settings(work / CONFIG / "settings.yaml", folders, load_settings(paths))
    return StagedRestore(name, work, db_revision(work / DB_NAME) or "", kept)


def _write_db(source: Path, live: Path) -> None:
    """Copy ``source`` into the live database file in place, in one transaction."""
    src = sqlite3.connect(source)
    dst = sqlite3.connect(live)
    try:
        src.execute("PRAGMA trusted_schema=OFF")
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
