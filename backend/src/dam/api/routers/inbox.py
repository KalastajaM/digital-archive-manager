"""The inbox: list incoming files with suggestions, preview and file them."""

import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query, Request
from starlette.concurrency import run_in_threadpool

from dam.api.deps import UI_ORIGIN, AppDep
from dam.api.marks import with_record_marks
from dam.api.schemas import (
    BatchResultOut,
    FileBody,
    FileItResultOut,
    FileRequestIn,
    InboxEntryOut,
    ResolvedOpOut,
)
from dam.errors import InvalidRequest, TooLarge
from dam.ops.primitives import MAX_COPY_BYTES
from dam.services.inbox import FileRequest
from dam.services.intake import LIMIT_MB

router = APIRouter(prefix="/api/inbox", tags=["inbox"])


def _requests(body: list[FileRequestIn]) -> list[FileRequest]:
    return [FileRequest(**r.model_dump()) for r in body]


@router.get("", response_model=list[InboxEntryOut])
def list_inbox(app: AppDep) -> list:
    return with_record_marks(app, app.inbox.list())


@router.post("/preview", response_model=list[ResolvedOpOut])
def preview(app: AppDep, body: list[FileRequestIn]) -> list:
    return app.inbox.preview(_requests(body), origin=UI_ORIGIN)


@router.post("/file", response_model=FileItResultOut)
def file_it(app: AppDep, body: FileBody) -> dict:
    outcome = app.inbox.file_it(
        _requests(body.requests), dry_run=body.dry_run, origin=UI_ORIGIN, via=body.via
    )
    return {
        **asdict(outcome.batch),
        "tag_error": outcome.tag_error,
        "untagged": outcome.untagged,
        "items": outcome.items,
        "follow_up_error": outcome.follow_up_error,
        "offer": asdict(outcome.offer) if outcome.offer else None,
    }


@router.post("/upload", response_model=BatchResultOut)
async def upload(app: AppDep, request: Request, name: Annotated[str, Query(max_length=255)]):
    """Copy one file into the inbox ("Choose files…"). The body is the file itself
    (``Content-Type: application/octet-stream``); ``name`` is its file name. A taken name
    gets ``_2``, nothing is overwritten, and a file over the size limit is refused (413)
    before anything is written to the archive. Journaled as one batch; undo moves the
    copy to the quarantine folder."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_COPY_BYTES:
        raise TooLarge(f"That file is larger than {LIMIT_MB} MB.")
    uploads = app.app_paths.cache_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    # the temporary file lives outside the archive and removes itself when closed
    with tempfile.NamedTemporaryFile(dir=uploads, delete=True, delete_on_close=False) as tmp:
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_COPY_BYTES:
                raise TooLarge(f"That file is larger than {LIMIT_MB} MB.")
            await run_in_threadpool(tmp.write, chunk)
        if total == 0:
            raise InvalidRequest("That file is empty.")
        await run_in_threadpool(tmp.flush)
        return await run_in_threadpool(app.intake.add_files, [Path(tmp.name)], UI_ORIGIN, [name])
