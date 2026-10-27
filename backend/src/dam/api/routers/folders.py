"""Archive folders: the main folder and the extra ones (list, add, detach, attach,
change a label).

Each change edits only the settings file and the index, never a file in a folder; a
``dry_run`` answers with the same numbers and writes nothing. After a change to the
attached set the running server opens the archive afresh (``Host.reopen``), so the
change takes effect at once; without one the answer says ``restart_needed``.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter

from dam import archive_folders
from dam.api.deps import AppDep, ArchivesDep, SnapshotsDep
from dam.api.schemas import (
    ArchiveFolderAddIn,
    ArchiveFolderAttachIn,
    ArchiveFolderDetachIn,
    ArchiveFolderRelabelIn,
    ArchiveFoldersOut,
    FolderChangeOut,
    RelabelOut,
)
from dam.app import App
from dam.archive_folders import FolderChange
from dam.errors import Conflict
from dam.services.archives import ArchiveService

router = APIRouter(prefix="/api/archive-folders", tags=["archive-folders"])


@contextmanager
def _not_busy(app: App) -> Iterator[None]:
    """409 before anything is written while a job runs that a reopen would end, or a
    batch of changes that would journal into the closed database; inside, no move
    across disks or batch starts (it would be refused), so the answer holds until the
    change is done."""
    with app.held():
        yield


def _done(archives: ArchiveService, change: FolderChange) -> dict:
    restart_needed = change.restart_needed or (change.reopen and not archives.reopen())
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
    be (it overlaps a folder of any archive, the label is taken, it cannot be read).
    409 while a maintenance check or rule replay runs."""
    with _not_busy(app):
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
    """Take the folder out of the archive; it stays listed, detached, and its index rows
    are marked missing. With ``forget`` the rows are removed and the folder leaves the
    list. ``files`` says how many. The archive is reopened before the index changes (see
    ``archive_folders.detach_folder``)."""
    with _not_busy(app):
        change = archive_folders.detach_folder(
            app.app_paths, app.repo, label, body.forget, body.dry_run, reopen=archives.reopen
        )
        return _done(archives, change)


@router.post("/{label}/attach", response_model=FolderChangeOut)
def attach_folder(
    app: AppDep, archives: ArchivesDep, label: str, body: ArchiveFolderAttachIn
) -> dict:
    """Attach a detached folder again, after the same checks as adding one."""
    with _not_busy(app):
        change = archive_folders.attach_folder(
            app.app_paths,
            label,
            body.dry_run,
            store=archives.store,
            current_id=archives.current_id,
        )
        return _done(archives, change)


def _relabel_out(change: archive_folders.RelabelChange) -> dict:
    out = asdict(change)
    out["files"] = [{"name": name, "lines": lines} for name, lines in change.files]
    return out


@router.post("/{label}/relabel", response_model=RelabelOut)
def relabel_folder(
    app: AppDep, snaps: SnapshotsDep, label: str, body: ArchiveFolderRelabelIn
) -> dict:
    """Change the folder's label: every stored path under it (index, journal, settings,
    rules) is rewritten; nothing on disk changes. The dry run answers with what changes.
    Applying closes the archive, changes it and opens it again (``dam serve`` only: 409
    otherwise), after a snapshot. 409 while a job runs."""
    with _not_busy(app):
        change = archive_folders.relabel_folder(app.app_paths, label, body.label, True, app.engine)
        if body.dry_run:
            return _relabel_out(change)
        if snaps.reopener is None:
            raise Conflict("This window cannot change a label. Start dam with `dam serve`.")
        done = snaps.reopener.close_and_reopen(
            lambda: archive_folders.relabel_folder(app.app_paths, label, body.label, False)
        )
        return _relabel_out(done)
