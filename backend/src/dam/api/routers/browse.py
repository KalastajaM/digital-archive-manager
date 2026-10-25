"""Browse the index, list filing targets, search, move files and quarantine."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from dam.api.deps import UI_ORIGIN, AppDep
from dam.api.marks import with_marks
from dam.api.schemas import (
    BatchResultOut,
    DirEntryOut,
    FlatFilesOut,
    MoveBody,
    MoveResultOut,
    QuarantineBody,
    RenameBody,
    ResolvedOpOut,
    SearchHitOut,
)

router = APIRouter(prefix="/api", tags=["browse"])


@router.get("/browse", response_model=list[DirEntryOut])
def browse(app: AppDep, path: str = "", collection: int | None = None) -> list:
    return with_marks(app, app.browse.list_dir(path, collection_id=collection))


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
    return {"rows": with_marks(app, rows), "total": total}


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
    """Words in ``q`` and/or ``tag`` (repeat it). ``tag_mode`` ``all``: a file needs every
    tag; ``any``: at least one."""
    return with_marks(
        app, app.search(q, folder=folder or None, limit=limit, tags=tag, tag_mode=tag_mode)
    )


@router.post("/quarantine", response_model=BatchResultOut)
def quarantine(app: AppDep, body: QuarantineBody):
    return app.browse.quarantine(body.drive_ids, origin=UI_ORIGIN, dry_run=body.dry_run)


@router.post("/browse/move/preview", response_model=list[ResolvedOpOut])
def move_preview(app: AppDep, body: MoveBody) -> list:
    return app.browse.move_preview(body.drive_ids, body.folder, origin=UI_ORIGIN)


@router.post("/browse/move", response_model=MoveResultOut)
def move(app: AppDep, body: MoveBody):
    return app.browse.move(body.drive_ids, body.folder, origin=UI_ORIGIN)


@router.post("/browse/rename/preview", response_model=list[ResolvedOpOut])
def rename_preview(app: AppDep, body: RenameBody) -> list:
    return app.browse.rename_file_preview(body.drive_id, body.name, body.folder, origin=UI_ORIGIN)


@router.post("/browse/rename", response_model=MoveResultOut)
def rename(app: AppDep, body: RenameBody):
    return app.browse.rename_file(body.drive_id, body.name, body.folder, origin=UI_ORIGIN)
