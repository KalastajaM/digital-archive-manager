"""Request dependencies shared by the routers."""

from typing import Annotated

from fastapi import Depends, Request

from dam.api.setup_ctl import SetupMode
from dam.app import App
from dam.index.repo import FileRecord
from dam.ops.guards import is_under
from dam.services.archives import ArchiveService, solo
from dam.services.backups import BackupService
from dam.services.errors import Conflict, InvalidRequest, NotFound

UI_ORIGIN = "ui"  # every change made through the API is journaled as coming from the UI


def get_app(request: Request) -> App:
    return request.app.state.dam


AppDep = Annotated[App, Depends(get_app)]


def live_record(app: App, drive_id: str) -> FileRecord:
    """The record for ``drive_id`` (by id only); NotFound if unknown, missing or parked."""
    rec = app.repo.get(drive_id)
    if rec is None or rec.missing or rec.parked_at is not None:
        raise NotFound(drive_id)
    return rec


TO_DELETE_READ_ONLY = "Marked for deletion: restore it first"


def require_editable(app: App, drive_ids: list[str]) -> None:
    """Refuse (400) a change to a file that is in the quarantine folder (``##. To
    Delete``): what is marked for deletion is read-only until it is restored. Its tags,
    collections, notes and tray items stay as they are, so a restored file comes back
    with them. Unknown or missing ids are left to the caller's own checks."""
    for drive_id in dict.fromkeys(drive_ids):
        rec = app.repo.get(drive_id)
        if rec is None or rec.missing or rec.parked_at is not None:
            continue
        if is_under(rec.path_nfc, app.paths.quarantine):
            raise InvalidRequest(f"{TO_DELETE_READ_ONLY}: {rec.path}")


def check_target(app: App, kind: str, target: str) -> None:
    """NotFound unless ``target`` names an existing ``kind`` (a note/checklist owner):
    a live file by drive id, or a collection/item by its id."""
    if kind == "file":
        live_record(app, target)
        return
    # at most 18 digits: always within SQLite's int64 (a longer id cannot exist)
    if not target.isascii() or not target.isdigit() or len(target) > 18:
        raise NotFound(f"{kind} {target[:40]}")
    if kind == "collection":
        app.collections.get(int(target))
    elif kind == "item":
        app.trays.get(int(target))
    else:
        raise NotFound(f"{kind} {target}")


def get_setup(request: Request) -> SetupMode:
    """The first-run setup controller; 409 once the app is configured (the normal
    server has none)."""
    setup = getattr(request.app.state, "setup", None)
    if setup is None:
        raise Conflict("The archive folder is already set up.")
    return setup


SetupDep = Annotated[SetupMode, Depends(get_setup)]


def get_archives(request: Request) -> ArchiveService:
    """The archives (profiles) service of this server."""
    service = getattr(request.app.state, "archives", None)
    if service is None:  # an API built without one: this data folder is the only archive
        service = solo(request.app.state.dam.app_paths)
        request.app.state.archives = service
    return service


ArchivesDep = Annotated[ArchiveService, Depends(get_archives)]


def get_backups(request: Request) -> BackupService:
    """The backups service of this API (made with it in ``create_api``)."""
    return request.app.state.backups


BackupsDep = Annotated[BackupService, Depends(get_backups)]
