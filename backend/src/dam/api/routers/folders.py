"""Archive folders: the main folder and the extra ones (list, add, detach, attach).

Each change edits only the settings file and the index, never a file in a folder; a
``dry_run`` answers with the same numbers and writes nothing. After a change to the
attached set the running server opens the archive afresh (``Host.reopen``), so the
change takes effect at once; without one the answer says ``restart_needed``.
"""

from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter

from dam import archive_folders
from dam.api.deps import AppDep, ArchivesDep
from dam.api.schemas import (
    ArchiveFolderAddIn,
    ArchiveFolderAttachIn,
    ArchiveFolderDetachIn,
    ArchiveFoldersOut,
    FolderChangeOut,
)
from dam.archive_folders import FolderChange
from dam.services.archives import ArchiveService

router = APIRouter(prefix="/api/archive-folders", tags=["archive-folders"])


def _done(archives: ArchiveService, change: FolderChange) -> dict:
    restart_needed = change.reopen and not archives.reopen()
    return {
        "label": change.label,
        "path": change.path,
        "files": change.files,
        "restart_needed": restart_needed,
    }


@router.get("", response_model=ArchiveFoldersOut)
def list_folders(app: AppDep) -> dict:
    """The main folder first, then every extra folder, detached ones included."""
    folders = archive_folders.list_folders(app.app_paths, app.repo)
    return {"folders": [asdict(f) for f in folders]}


@router.post("", response_model=FolderChangeOut)
def add_folder(app: AppDep, archives: ArchivesDep, body: ArchiveFolderAddIn) -> dict:
    """Add a folder to the archive under ``label``; 400 with the reason when it cannot
    be (it overlaps a folder of any archive, the label is taken, it cannot be read)."""
    change = archive_folders.add_folder(
        app.app_paths,
        body.label,
        Path(body.path),
        body.dry_run,
        store=archives.store,
        current_id=archives.current_id,
    )
    return _done(archives, change)


@router.post("/{label}/detach", response_model=FolderChangeOut)
def detach_folder(
    app: AppDep, archives: ArchivesDep, label: str, body: ArchiveFolderDetachIn
) -> dict:
    """Take the folder out of the archive (it stays listed, detached). Its index rows
    are marked missing, or with ``forget`` removed; ``files`` says how many."""
    change = archive_folders.detach_folder(
        app.app_paths, app.repo, label, body.forget, body.dry_run
    )
    return _done(archives, change)


@router.post("/{label}/attach", response_model=FolderChangeOut)
def attach_folder(
    app: AppDep, archives: ArchivesDep, label: str, body: ArchiveFolderAttachIn
) -> dict:
    """Attach a detached folder again, after the same checks as adding one."""
    change = archive_folders.attach_folder(
        app.app_paths,
        label,
        body.dry_run,
        store=archives.store,
        current_id=archives.current_id,
    )
    return _done(archives, change)
