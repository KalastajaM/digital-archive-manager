"""Choosing where an archive keeps its data (settings, index, logs).

``check_data_folder`` looks at a folder the owner names and says whether it can be that
data folder: a new or empty folder (dam makes the archive's data there), or a folder that
already holds dam data (the owner decides whether to use it). It only reads; nothing is
written, copied or deleted here. The sheet that asks the owner shows what this finds.
"""

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dam import setup
from dam.config import AppPaths
from dam.core.fs import resolve
from dam.db.engine import APP_ID
from dam.profiles import ProfileStore, ServeLock, related, root_conflict
from dam.snapshots import db_revision, revision_is_known

State = Literal["new", "dam_data", "refused"]

# Folder names of cloud-sync clients: a SQLite database there is corrupted or forked by
# the sync, so it is never offered as a data folder.
SYNCED_PARTS = frozenset(
    {
        "cloudstorage",
        "dropbox",
        "icloud drive",
        "mobile documents",
        "onedrive",
        "google drive",
        "my drive",
        "box",
        "pcloud drive",
    }
)


@dataclass(frozen=True)
class DataFolderCheck:
    path: Path | None
    state: State
    message: str = ""  # why refused (or what to know about existing data)
    archive_root: str | None = None  # existing data: the documents folder its settings name
    archive_root_exists: bool | None = None  # ... and whether it is there on this computer


def is_synced(path: Path) -> bool:
    return any(part.casefold() in SYNCED_PARTS for part in path.parts)


def data_dir_conflict(path: Path, store: ProfileStore) -> str | None:
    """Why ``path`` cannot be the data folder of a new archive, or None: it may not be,
    contain or sit inside another archive's data folder, contain the folder that holds the
    archive list, or touch any archive folder."""
    profiles = store.load()
    for p in profiles:
        how = related(path, p.data_dir)
        if how == "same":
            return f"That folder is already the data folder of the archive '{p.name}'."
        if how:
            return f"That folder overlaps the data folder of the archive '{p.name}'."
    if related(path, store.base) in ("same", "around"):
        return "That folder contains the app's own data folder. Choose another."
    for p in profiles:
        roots = [Path(r).expanduser() for r in [p.archive_root] if r]
        roots += setup.current_extra_folders(p.paths)
        if any(related(path, r) for r in roots):
            return f"That folder overlaps an archive folder of '{p.name}'. Choose another."
    return None


def _marker_problem(db: Path) -> str | None:
    """The database belongs to another app (another build of dam sharing the folder)."""
    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = con.execute("SELECT value FROM dam_meta WHERE key = 'app'").fetchone()
    except sqlite3.Error:
        return None  # no marker table: an older database of this app, or none
    finally:
        con.close()
    if row and row[0] != APP_ID:
        return "Its database was made by another build of dam, not by this one."
    return None


def check_data_folder(raw: str, store: ProfileStore, home: Path | None = None) -> DataFolderCheck:
    text = raw.strip()
    if not text:
        return DataFolderCheck(None, "refused", "Enter the path of a folder.")
    path = Path(text).expanduser()
    if not path.is_absolute():
        return DataFolderCheck(
            path, "refused", "Use the full path of the folder (it starts with / or a drive letter)."
        )
    try:
        path = resolve(path)
    except (OSError, RuntimeError):
        pass
    home = resolve(Path.home() if home is None else home)
    if path.parent == path or path == home:
        return DataFolderCheck(
            path, "refused", "Choose a folder of its own, not a whole disk or your home folder."
        )
    if is_synced(path):
        return DataFolderCheck(
            path,
            "refused",
            "That folder is synced by a cloud service. The index is a database, and syncing "
            "corrupts it or splits it into copies. Choose a folder on this computer that is "
            "not synced.",
        )
    if message := data_dir_conflict(path, store):
        return DataFolderCheck(path, "refused", message)
    try:
        exists = path.exists()
        is_dir = path.is_dir()
    except OSError as e:
        return DataFolderCheck(path, "refused", f"That folder cannot be read ({e.strerror or e}).")
    if not exists:
        parent = path.parent
        if parent.is_dir() and os.access(parent, os.W_OK | os.X_OK):
            return DataFolderCheck(path, "new")
        return DataFolderCheck(
            path,
            "refused",
            "That folder does not exist, and the folder above it is missing or read-only.",
        )
    if not is_dir:
        return DataFolderCheck(path, "refused", "That is a file, not a folder.")
    if not os.access(path, os.R_OK | os.W_OK | os.X_OK):
        return DataFolderCheck(path, "refused", "This app cannot read and write that folder.")
    if setup.is_empty_folder(path):
        return DataFolderCheck(path, "new")
    paths = AppPaths(path)
    db = paths.db_path
    if not db.exists() and not setup.settings_path(paths).exists():
        return DataFolderCheck(
            path,
            "refused",
            "That folder is not empty and does not hold dam data. Choose an empty or a new folder.",
        )
    if (holder := ServeLock.holder(path)) is not None:
        where = f" (on port {holder['port']})" if holder.get("port") else ""
        return DataFolderCheck(
            path,
            "refused",
            f"A dam window is using this data{where}. Close it first, then try again.",
        )
    if db.exists():
        if problem := _marker_problem(db):
            return DataFolderCheck(path, "refused", problem)
        if not revision_is_known(db_revision(db)):
            return DataFolderCheck(
                path,
                "refused",
                "Its database was made by a newer or different version of dam. This version "
                "cannot open it.",
            )
    root = setup.current_archive_root(paths)
    exists_here = None
    if root:
        root_path = Path(root).expanduser()
        exists_here = root_path.is_dir()
        if clash := root_conflict(root_path, store.load(), store.base, None):
            return DataFolderCheck(
                path, "refused", f"Its documents folder is not free to use: {clash}"
            )
    return DataFolderCheck(path, "dam_data", "", root, exists_here)
