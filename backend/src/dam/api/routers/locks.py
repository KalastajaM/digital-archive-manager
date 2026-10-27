"""Locks: a safety catch against changes to a file on disk (``dam.locks``).

Locking, unlocking and the list are the app's own data, like tags: nothing is journaled.
The refusal itself happens in the operation layer, whatever route a change takes.
"""

from fastapi import APIRouter

from dam.api.deps import AppDep, live_record
from dam.api.schemas import LocksOut, LockStateOut, UnlockIn
from dam.app import App
from dam.errors import Conflict, InvalidRequest
from dam.locks import IDLE_SECONDS, IMPORTANT, IMPORTANT_FOR_NOW

router = APIRouter(prefix="/api", tags=["locks"])


def _state(app: App, drive_id: str, path_nfc: str, token: str | None = None) -> dict:
    reason = app.locks.reason(drive_id, path_nfc)
    return {
        "drive_id": drive_id,
        "locked": reason is not None,
        "reason": reason,
        "unlocked_now": reason is not None and app.locks.active(drive_id),
        "token": token,
        "expires_after_idle_seconds": IDLE_SECONDS if token else None,
    }


@router.get("/locks", response_model=LocksOut)
def list_locks(app: AppDep) -> dict:
    """The locked files (Important ones and the owner's) and the locked folders."""
    entries = app.locks.entries()
    return {
        "files": [{"drive_id": e.drive_id, "reason": e.reason} for e in entries if not e.is_dir],
        "folders": [e.path for e in entries if e.is_dir],
    }


@router.post("/files/{drive_id}/lock", response_model=LockStateOut)
def lock_file(app: AppDep, drive_id: str) -> dict:
    """Lock the file (or lock it again: any unlock "now" of it ends). An Important file
    is locked already; nothing is stored for it."""
    rec = live_record(app, drive_id)
    if rec.is_dir or rec.is_link:
        raise InvalidRequest("Only files can be locked.")
    if app.locks.reason(drive_id, rec.path_nfc) == IMPORTANT:
        app.locks.release(drive_id)
    else:
        app.locks.lock(drive_id)
    return _state(app, drive_id, rec.path_nfc)


@router.post("/files/{drive_id}/unlock", response_model=LockStateOut)
def unlock_file(app: AppDep, drive_id: str, body: UnlockIn) -> dict:
    """``now``: a token that unlocks the file for requests sending it as ``X-Dam-Unlock``
    until it is released, or unused for a while. ``for_good``: remove the owner's lock.
    409 for an Important file, which can only be unlocked for now."""
    rec = live_record(app, drive_id)
    reason = app.locks.reason(drive_id, rec.path_nfc)
    if reason is None:
        return _state(app, drive_id, rec.path_nfc)
    if body.mode == "for_good":
        if reason == IMPORTANT:
            raise Conflict(IMPORTANT_FOR_NOW)
        app.locks.unlock_for_good(drive_id)
        return _state(app, drive_id, rec.path_nfc)
    return _state(app, drive_id, rec.path_nfc, token=app.locks.grant(drive_id))


@router.delete("/files/{drive_id}/unlock", response_model=LockStateOut)
def release_unlock(app: AppDep, drive_id: str) -> dict:
    """The owner left the file: end every temporary unlock of it at once."""
    rec = live_record(app, drive_id)
    app.locks.release(drive_id)
    return _state(app, drive_id, rec.path_nfc)
