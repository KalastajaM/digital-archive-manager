"""AI: status, the two-step prepare/run and the call log (spec §4)."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Query

from dam.ai.tasks import find_relatives
from dam.api.deps import AppDep
from dam.api.marks import with_marks
from dam.api.schemas import (
    AIExcludeIn,
    AILogOut,
    AIPrepareIn,
    AIRunIn,
    AIStateIn,
    AIStatusOut,
    PreparedOut,
    RunOut,
)

router = APIRouter(prefix="/api/ai", tags=["ai"])

LOG_LIMIT = 50


@router.get("/status", response_model=AIStatusOut)
def ai_status(app: AppDep) -> dict:
    """On/off, whether a key is present (never the key), the month's spend and cap."""
    return app.ai.status()


@router.post("/state", response_model=AIStatusOut)
def ai_state(app: AppDep, body: AIStateIn) -> dict:
    """Switch AI on or off (as ``dam ai --on/--off``); answers the new status."""
    app.ai.set_enabled(body.enabled)
    return app.ai.status()


@router.put("/exclude-folders", response_model=AIStatusOut)
def ai_exclude_folders(app: AppDep, body: AIExcludeIn) -> dict:
    """Save the excluded folders (the whole list) to settings.yaml and use them at once;
    answers the new status. 400 for a bad entry, 409 if the file could not be written."""
    app.ai.set_exclude_folders(body.folders)
    return app.ai.status()


@router.get("/log", response_model=AILogOut)
def ai_log(app: AppDep, limit: Annotated[int, Query(ge=1, le=1000)] = LOG_LIMIT) -> dict:
    """The newest ``limit`` calls, newest first."""
    return {"rows": app.ai.recent(limit)}


@router.post("/{task}/prepare", response_model=PreparedOut)
def ai_prepare(app: AppDep, task: str, body: AIPrepareIn) -> dict:
    """What would be sent and what it costs; nothing is sent. 409 while AI is off."""
    return asdict(app.ai.prepare(task, body.params))


@router.post("/{task}/run", response_model=RunOut)
def ai_run(app: AppDep, task: str, body: AIRunIn) -> dict:
    """Send exactly the prepared payload; 400 if anything changed since the preview."""
    app.ai.get_task(task)  # 404 for an unknown task before the token is looked at
    out = asdict(app.ai.run(body.token, task))
    if task == "find-relatives":
        out["data"] = find_relatives.resolve(app, out["data"])  # the files as they are now
    citations = out["data"].get("citations")
    if isinstance(citations, list) and citations:
        # each cited file's ★ / ! marks, as they are now (a cached answer too): one query
        out["data"]["citations"] = with_marks(app, citations)
    return out
