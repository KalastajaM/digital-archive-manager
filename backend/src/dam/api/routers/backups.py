"""Backups of this archive's database and settings: list, make one, restore one, show
the folder.

Behind the same local-only protections as every route. Nothing is deleted: a restore
moves the replaced settings aside, and old backups are the user's to remove.
"""

from fastapi import APIRouter, Response

from dam.api.deps import BackupsDep
from dam.api.schemas import BackupOut, BackupRestoreIn, BackupRestoreOut, BackupsOut

router = APIRouter(prefix="/api/backups", tags=["backups"])


@router.get("", response_model=BackupsOut)
def list_backups(backups: BackupsDep) -> dict:
    return backups.overview()


@router.post("", response_model=BackupOut)
def create_backup(backups: BackupsDep) -> dict:
    """Back up the database and settings now (the app keeps running)."""
    return backups.create()


@router.post("/{name}/restore", response_model=BackupRestoreOut)
def restore_backup(backups: BackupsDep, name: str, body: BackupRestoreIn) -> dict:
    """Replace the database and settings with backup ``name``. With ``backup_current``
    the current state is backed up first. The archive closes and opens again."""
    return backups.restore(name, body.backup_current)


@router.post("/reveal", status_code=204, response_class=Response)
def reveal_backups(backups: BackupsDep) -> Response:
    """Show the backups folder in Finder / Explorer."""
    backups.reveal()
    return Response(status_code=204)
