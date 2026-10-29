"""Browse the index, list filing targets, search, move files and quarantine."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from dam.api.deps import UI_ORIGIN, AppDep
from dam.api.marks import with_marks, with_open_items
from dam.api.schemas import (
    BatchResultOut,
    CopyJobOut,
    DirEntryOut,
    FlatFilesOut,
    LinkThereBody,
    MoveBody,
    MoveResultOut,
    QuarantineBody,
    RenameBody,
    ResolvedOpOut,
    RestoreBody,
    SearchHitOut,
)
from dam.core.jobs import Job
from dam.errors import NotFound

router = APIRouter(prefix="/api", tags=["browse"])


@router.get("/browse", response_model=list[DirEntryOut])
def browse(app: AppDep, path: str = "", collection: int | None = None) -> list:
    return with_open_items(
        app, with_marks(app, app.browse.list_dir(path, collection_id=collection))
    )


@router.get("/browse/files", response_model=FlatFilesOut)
def browse_files(
    app: AppDep,
    path: str = "",
    collection: int | None = None,
    sort: Literal["name", "date", "size", "folder"] = "name",
    dir: Literal["asc", "desc"] = "asc",
    limit: Annotated[int, Query(ge=1, le=500)] = 500,
) -> dict:
    rows, total = app.browse.files_below(
        path, collection_id=collection, sort=sort, desc=dir == "desc", limit=limit
    )
    return {"rows": with_open_items(app, with_marks(app, rows)), "total": total}


@router.get("/folders", response_model=list[str])
def folders(app: AppDep) -> list[str]:
    return app.browse.folders()


@router.get("/search", response_model=list[SearchHitOut])
def search(
    app: AppDep,
    q: str = "",
    folder: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    tag: Annotated[list[str] | None, Query(max_length=20)] = None,
    tag_mode: Literal["all", "any"] = "all",
) -> list:
    """``q`` is plain words (full text) and ``name:value`` filters (``name``, ``in``, ``tag``,
    ``collection``, ``from``, ``for``, ``type``, ``date``, ``before``, ``after``, ``tray``,
    ``is``; ``-`` in front excludes; quotes for values with spaces). Every filter must hold.
    ``tag`` (repeat it) adds tag filters. ``tag_mode`` ``all``: a file needs every tag;
    ``any``: at least one. 400 for a filter value that cannot be right (a bad date)."""
    hits = app.search(q, folder=folder or None, limit=limit, tags=tag, tag_mode=tag_mode)
    return with_open_items(app, with_marks(app, hits))


@router.post("/quarantine", response_model=BatchResultOut)
def quarantine(app: AppDep, body: QuarantineBody):
    return app.browse.quarantine(body.drive_ids, origin=UI_ORIGIN, dry_run=body.dry_run)


@router.post("/restore", response_model=BatchResultOut)
def restore(app: AppDep, body: RestoreBody):
    """Take entries out of To Delete again (original place, the inbox or a folder);
    ``dry_run`` shows the plan, including a folder made again and a name given ``_N``."""
    return app.browse.restore(
        body.drive_ids, body.to, origin=UI_ORIGIN, dry_run=body.dry_run, folder=body.folder
    )


@router.post("/browse/move/preview", response_model=list[ResolvedOpOut])
def move_preview(app: AppDep, body: MoveBody) -> list:
    return app.browse.move_preview(body.drive_ids, body.folder, origin=UI_ORIGIN, mode=body.mode)


@router.post("/browse/move", response_model=MoveResultOut)
def move(app: AppDep, body: MoveBody):
    return app.browse.move(body.drive_ids, body.folder, origin=UI_ORIGIN, mode=body.mode)


@router.post("/browse/link-there/preview", response_model=list[ResolvedOpOut])
def link_there_preview(app: AppDep, body: LinkThereBody) -> list:
    """The links ``link-there`` would make: one in each folder (Relatives)."""
    return app.browse.link_there_preview(body.drive_id, body.folders, origin=UI_ORIGIN)


@router.post("/browse/link-there", response_model=MoveResultOut)
def link_there(app: AppDep, body: LinkThereBody):
    """A link to one file in each of several folders, as one batch: one Undo removes all."""
    return app.browse.link_there(body.drive_id, body.folders, origin=UI_ORIGIN)


def _copy_job_out(job: Job) -> dict:
    view = job.view()
    return {
        "job_id": view.job_id,
        "state": view.state,
        "version": view.version,
        "done": view.done,
        "total": view.total,
        "bytes_done": view.bytes_done,
        "bytes_total": view.bytes_total,
        "current": view.current,
        "elapsed_s": view.elapsed_s,
        "error": view.error,
        "result": None if view.result is None else vars(view.result),
    }


@router.get("/browse/move/jobs/latest", response_model=CopyJobOut | None)
def latest_copy_job(app: AppDep) -> dict | None:
    """The latest move across disks of this run (a finished one too), else null."""
    job = app.copy_jobs.latest()
    return None if job is None else _copy_job_out(job)


@router.get("/browse/move/jobs/{job_id}", response_model=CopyJobOut)
def get_copy_job(app: AppDep, job_id: str) -> dict:
    job = app.copy_jobs.get(job_id)
    if job is None:
        raise NotFound(job_id)
    return _copy_job_out(job)


@router.post("/browse/move/jobs/{job_id}/stop", response_model=CopyJobOut)
def stop_copy_job(app: AppDep, job_id: str) -> dict:
    """End the move after the file being copied (it is finished, and its original goes
    to To Delete); the files not reached stay where they are. Idempotent."""
    job = app.copy_jobs.get(job_id)
    if job is None:
        raise NotFound(job_id)
    job.stop()
    job.join(2.0)
    return _copy_job_out(job)


@router.post("/browse/rename/preview", response_model=list[ResolvedOpOut])
def rename_preview(app: AppDep, body: RenameBody) -> list:
    return app.browse.rename_file_preview(body.drive_id, body.name, body.folder, origin=UI_ORIGIN)


@router.post("/browse/rename", response_model=MoveResultOut)
def rename(app: AppDep, body: RenameBody):
    return app.browse.rename_file(body.drive_id, body.name, body.folder, origin=UI_ORIGIN)
