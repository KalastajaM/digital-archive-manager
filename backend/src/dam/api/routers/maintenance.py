"""Maintenance: checks the owner starts, polls and can stop, and the batches they lead to.

Nothing here runs by itself. Duplicates are replaced or moved to To Delete through one
previewed batch (``dry_run``), like every other change. Reconnecting files moved outside
dam is previewed too, but changes the database only (no batch, no Undo)."""

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
    MaintenanceIgnoredOut,
    MaintenanceIgnoreIn,
    MaintenanceJobOut,
    MaintenanceKindIn,
    MaintenanceStartIn,
    ReadoptIn,
    ReadoptOut,
    ReadoptUndoIn,
    ReconnectIn,
    ReconnectOut,
    ReconnectUndoIn,
)
from dam.app import App
from dam.core.jobs import Job
from dam.errors import NotFound

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


@router.get("/ignored", response_model=list[MaintenanceIgnoredOut])
def ignored(app: AppDep) -> list[dict]:
    """What the owner ignores in the checks' results, newest first."""
    return [asdict(i) for i in app.maintenance.ignored.list()]


@router.post("/ignored", response_model=MaintenanceIgnoredOut)
def ignore(app: AppDep, body: MaintenanceIgnoreIn) -> dict:
    """Ignore a result entry: later results of its check leave it out (see
    ``dam.maintenance.ignored`` for the keys). Nothing in the archive changes."""
    return asdict(app.maintenance.ignored.add(body.kind, body.key, body.label, body.members))


@router.delete("/ignored/{ignored_id}", response_model=MaintenanceForgetOut)
def stop_ignoring(app: AppDep, ignored_id: int) -> dict:
    """Stop ignoring an entry; it shows in the check's results again. 404 if unknown."""
    if not app.maintenance.ignored.unignore(ignored_id):
        raise NotFound(str(ignored_id))
    return {"forgotten": 1}


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
    the kept copy; nothing changes. A group with ``same: name`` holds versions of one
    document (same name, other content). 400: a copy that is Important or locked, files
    not known to be the same (or, for versions, not of the same name), or changed since
    they were scanned."""
    result = app.maintenance.resolve(
        [(g.keep, g.others, g.same) for g in body.groups],
        body.action,
        carry_over=body.carry_over,
        origin=UI_ORIGIN,
        dry_run=body.dry_run,
        links=[i for g in body.groups for i in g.links],
    )
    return result


@router.post("/links/remove", response_model=BatchResultOut)
def remove_links(app: AppDep, body: LinkRemoveIn):
    """Remove broken links inside ``##. Ongoing`` / ``##. Important`` (the one removal
    allowed there); Undo makes them again. ``dry_run`` shows the plan."""
    return app.maintenance.remove_links(body.drive_ids, origin=UI_ORIGIN, dry_run=body.dry_run)


@router.post("/moved/reconnect", response_model=ReconnectOut)
def reconnect_moved(app: AppDep, body: ReconnectIn) -> dict:
    """Reconnect files moved or renamed outside dam: what each old, missing index row had
    (tags, notes, collections, tray items ...) moves to the file's new row, and the old
    row goes. Database only: the archive is not touched. Journaled for Undo (its
    ``undo_id``), but not in Activity. ``dry_run`` lists the pairs with what would move.
    400: a pair that does not hold (see ``MaintenanceService.reconnect``); 404: an
    unknown row."""
    return asdict(
        app.maintenance.reconnect([(p.old, p.new) for p in body.pairs], dry_run=body.dry_run)
    )


@router.post("/moved/undo", response_model=ReconnectOut)
def undo_reconnect(app: AppDep, body: ReconnectUndoIn) -> dict:
    """Undo a reconnect: each old row comes back with what moved from it and is still on
    the new row; what the file was given since stays. A pair that cannot be undone any
    more is in ``errors``. 400: undone already; 404: no such reconnect."""
    return asdict(app.maintenance.undo_reconnect(body.undo_id))


@router.post("/remounted/readopt", response_model=ReadoptOut)
def readopt_remounted(app: AppDep, body: ReadoptIn) -> dict:
    """Take over the new device number of the entries dam made in each of ``roots``
    (``##. Ongoing``, ``##. Important``) after a Drive restart: only where the check
    offers it (just the device number changed, the same way for every changed entry
    under the root). Database only: nothing on disk changes; journaled for Undo (its
    ``undo_id``), but not in Activity. Then the publishers sync. ``dry_run`` lists what
    would be taken over. 400: no root, one that is not a publish root, or nothing to
    take over."""
    return asdict(app.maintenance.readopt(body.roots, dry_run=body.dry_run))


@router.post("/remounted/undo", response_model=ReadoptOut)
def undo_readopt(app: AppDep, body: ReadoptUndoIn) -> dict:
    """Undo a take-over: each entry gets back the device number it was recorded with,
    unless its record changed since (then it is in ``errors``). 400: undone already;
    404: no such take-over."""
    return asdict(app.maintenance.undo_readopt(body.undo_id))
