"""Activity (journaled batches), undo and crash recovery."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Query

from dam.api.deps import AppDep
from dam.api.marks import batches_out, journal_out
from dam.api.schemas import (
    BatchSummaryOut,
    JournalEntryOut,
    RecoveryResultOut,
    ResolvedOpOut,
    UndoResultOut,
)

router = APIRouter(prefix="/api", tags=["activity"])


@router.get("/activity", response_model=list[BatchSummaryOut])
def activity(
    app: AppDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    q: Annotated[
        str | None, Query(description="Words in the title or in an op's file path")
    ] = None,
    kind: Annotated[
        list[str] | None,
        Query(description="undo, trash, marks, convert, collections, rename, filed or other"),
    ] = None,
    origin: Annotated[str | None, Query(description="ui, cli or auto")] = None,
    status: Annotated[str | None, Query(description="undone, undoable, done or attention")] = None,
    since: Annotated[float | None, Query(description="Started at or after (epoch seconds)")] = None,
    until: Annotated[float | None, Query(description="Started before (epoch seconds)")] = None,
    before: Annotated[
        str | None, Query(description="Continue after this batch (the last of the previous page)")
    ] = None,
) -> list:
    """Batches newest first, filtered; page on with ``before`` = the last batch id.
    A page of ``limit`` batches is the last one when it comes back shorter (ask for
    ``limit`` + 1 to know whether more exist)."""
    batches = app.activity.search(
        q=q,
        kinds=kind,
        origin=origin,
        status=status,
        since=since,
        until=until,
        before=before,
        limit=limit,
    )
    return batches_out(app, batches)


@router.post("/activity/{batch_id}/undo/preview", response_model=list[ResolvedOpOut])
def undo_preview(app: AppDep, batch_id: str) -> list:
    """The exact ops undo would run, with its refusals (400/409); changes nothing."""
    app.activity.get(batch_id)  # NotFound (404) for an unknown batch
    return app.activity.preview_undo(batch_id)


@router.post("/activity/{batch_id}/undo", response_model=UndoResultOut)
def undo(app: AppDep, batch_id: str) -> dict:
    app.activity.get(batch_id)  # NotFound (404) for an unknown batch
    outcome = app.activity.undo(batch_id)
    return {**asdict(outcome.batch), "follow_up_error": outcome.follow_up_error}


@router.get("/recovery", response_model=list[JournalEntryOut])
def pending(app: AppDep) -> list:
    """Journal rows of interrupted operations (run POST /api/recovery to settle them)."""
    return journal_out(app, app.activity.pending())


@router.post("/recovery", response_model=RecoveryResultOut)
def recover(app: AppDep):
    """Settle interrupted operations from the disk (reads only, never changes files)."""
    return app.activity.recover()
