"""Maintenance: checks the owner starts, polls and can stop, and the batches they lead to.

Nothing here runs by itself. Duplicates are replaced or moved to To Delete through one
previewed batch (``dry_run``), like every other change."""

from dataclasses import asdict

from fastapi import APIRouter

from dam.api.deps import UI_ORIGIN, AppDep
from dam.api.schemas import (
    BatchResultOut,
    DuplicateEstimateOut,
    DuplicateResolveIn,
    DuplicateResolveOut,
    LinkRemoveIn,
    MaintenanceForgetOut,
    MaintenanceJobOut,
    MaintenanceKindIn,
    MaintenanceStartIn,
)
from dam.app import App
from dam.maintenance.jobs import Job
from dam.services.errors import NotFound

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])


def _job_out(app: App, job: Job) -> dict:
    view = job.view(with_result=False)
    out = {
        "job_id": view.job_id,
        "kind": view.kind,
        "state": view.state,
        "version": view.version,
        "done": view.done,
        "total": view.total,
        "bytes_done": view.bytes_done,
        "bytes_total": view.bytes_total,
        "current": view.current,
        "elapsed_s": view.elapsed_s,
        "error": view.error,
    }
    if view.state != "running":
        kind, result = app.maintenance.result_of(job)
        if result is not None:
            out[kind] = asdict(result)
    return out


@router.get("/duplicates/estimate", response_model=DuplicateEstimateOut)
def estimate(app: AppDep) -> dict:
    """How many files the duplicate check would read and how big they are (the files
    that share a size with another and have no stored hash). Reading a file kept
    online-only in Google Drive downloads it. Reads the index only."""
    return asdict(app.maintenance.estimate())


@router.post("/jobs", response_model=MaintenanceJobOut)
def start(app: AppDep, body: MaintenanceStartIn) -> dict:
    """Start a check. An earlier job of the same kind is ended. Poll it with
    ``GET /api/maintenance/jobs/{job_id}``; stop it with ``POST .../stop``."""
    return _job_out(app, app.maintenance.start(body.kind, body.days))


@router.delete("/jobs", response_model=MaintenanceForgetOut)
def forget(app: AppDep, kind: MaintenanceKindIn | None = None) -> dict:
    """Reset: forget the checks of ``kind`` (all kinds when left out) and their results,
    ending one still running. Nothing in the archive changes."""
    return {"forgotten": app.maintenance.jobs.forget(kind)}


@router.get("/jobs/latest/{kind}", response_model=MaintenanceJobOut | None)
def latest(app: AppDep, kind: str) -> dict | None:
    """The latest job of ``kind`` of this run (finished ones too), else null."""
    job = app.maintenance.jobs.latest(kind)
    return None if job is None else _job_out(app, job)


@router.get("/jobs/{job_id}", response_model=MaintenanceJobOut)
def get_job(app: AppDep, job_id: str) -> dict:
    """Progress, and once the check is over (done or stopped) its result."""
    job = app.maintenance.jobs.get(job_id)
    if job is None:
        raise NotFound(job_id)
    return _job_out(app, job)


@router.post("/jobs/{job_id}/stop", response_model=MaintenanceJobOut)
def stop_job(app: AppDep, job_id: str) -> dict:
    """End a check where it is; what it found so far stays. Idempotent."""
    job = app.maintenance.jobs.get(job_id)
    if job is None:
        raise NotFound(job_id)
    job.stop()
    job.join(2.0)
    return _job_out(app, job)


@router.post("/duplicates/resolve", response_model=DuplicateResolveOut)
def resolve_duplicates(app: AppDep, body: DuplicateResolveIn):
    """Move the chosen copies to To Delete, or replace them with a link to the copy kept,
    as one batch (one Undo). ``dry_run`` lists every operation and what would be added to
    the kept copy; nothing changes. 400: a copy that is Important or locked, files not
    known to be the same, or changed since they were scanned."""
    result = app.maintenance.resolve(
        [(g.keep, g.others) for g in body.groups],
        body.action,
        carry_over=body.carry_over,
        origin=UI_ORIGIN,
        dry_run=body.dry_run,
    )
    return result


@router.post("/links/remove", response_model=BatchResultOut)
def remove_links(app: AppDep, body: LinkRemoveIn):
    """Remove broken links inside ``##. Ongoing`` / ``##. Important`` (the one removal
    allowed there); Undo makes them again. ``dry_run`` shows the plan."""
    return app.maintenance.remove_links(body.drive_ids, origin=UI_ORIGIN, dry_run=body.dry_run)
