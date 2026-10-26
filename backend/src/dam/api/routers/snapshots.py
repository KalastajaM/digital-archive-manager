"""Snapshots of this archive's database and settings: list, take one, export (download)
one, import one, restore one, show the folder.

Behind the same local-only protections as every route. Nothing is deleted: a restore
moves the replaced settings aside, and old snapshots are the user's to remove.
"""

import tempfile
from pathlib import Path

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from dam.api.deps import SnapshotsDep
from dam.api.schemas import SnapshotOut, SnapshotRestoreIn, SnapshotRestoreOut, SnapshotsOut
from dam.services.errors import InvalidRequest, TooLarge
from dam.snapshots import MAX_IMPORT_BYTES

router = APIRouter(prefix="/api/snapshots", tags=["snapshots"])
_TOO_LARGE = f"That file is larger than {MAX_IMPORT_BYTES // 1024**3} GB; it is not a snapshot."


@router.get("", response_model=SnapshotsOut)
def list_snapshots(snapshots: SnapshotsDep) -> dict:
    return snapshots.overview()


@router.post("", response_model=SnapshotOut)
def create_snapshot(snapshots: SnapshotsDep) -> dict:
    """Take a snapshot of the database and settings now (the app keeps running)."""
    return snapshots.create()


@router.post("/import", response_model=SnapshotOut)
async def import_snapshot(snapshots: SnapshotsDep, request: Request) -> dict:
    """Add a snapshot zip saved elsewhere (``Content-Type: application/octet-stream``, the
    body is the file). It is checked in full first; nothing is restored yet."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_IMPORT_BYTES:
        raise TooLarge(_TOO_LARGE)
    uploads = snapshots.paths.cache_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    # the temporary file lives in the cache and removes itself when closed
    with tempfile.NamedTemporaryFile(dir=uploads, delete=True, delete_on_close=False) as tmp:
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_IMPORT_BYTES:
                raise TooLarge(_TOO_LARGE)
            await run_in_threadpool(tmp.write, chunk)
        if total == 0:
            raise InvalidRequest("That file is empty.")
        await run_in_threadpool(tmp.flush)
        return await run_in_threadpool(snapshots.import_file, Path(tmp.name))


@router.get("/{name}/download")
def export_snapshot(snapshots: SnapshotsDep, name: str) -> FileResponse:
    """The snapshot zip as a download, to keep somewhere other than this computer."""
    return FileResponse(snapshots.file(name), media_type="application/zip", filename=name)


@router.post("/{name}/restore", response_model=SnapshotRestoreOut)
def restore_snapshot(snapshots: SnapshotsDep, name: str, body: SnapshotRestoreIn) -> dict:
    """Replace the database and settings with snapshot ``name``. With
    ``snapshot_current`` the current state is kept as a snapshot first. A snapshot of
    another archive folder needs ``other_folder_ok`` and keeps this archive's folders.
    The archive closes and opens again."""
    return snapshots.restore(name, body.snapshot_current, body.other_folder_ok)


@router.post("/reveal", status_code=204, response_class=Response)
def reveal_snapshots(snapshots: SnapshotsDep) -> Response:
    """Show the snapshots folder in Finder / Explorer."""
    snapshots.reveal()
    return Response(status_code=204)
