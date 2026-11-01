"""Files whose content changed: mark a notice as seen, and take that back."""

from fastapi import APIRouter

from dam.api.deps import AppDep
from dam.api.schemas.today import ContentChangesSeenIn, ContentChangesSeenOut

router = APIRouter(prefix="/api/content-changes", tags=["content-changes"])


@router.post("/seen", response_model=ContentChangesSeenOut)
def seen(app: AppDep, body: ContentChangesSeenIn) -> dict:
    """Mark these notices as seen, or with no ``drive_ids`` every open one. Returns the
    ids that were open, for Undo. Nothing on disk is touched."""
    ids = body.drive_ids
    if ids is None:
        rows, _ = app.repo.content_changes(exclude=app.paths.quarantines)
        ids = [r.drive_id for r in rows]
    return {"drive_ids": app.repo.see_changes(ids)}


@router.post("/unseen", response_model=ContentChangesSeenOut)
def unseen(app: AppDep, body: ContentChangesSeenIn) -> dict:
    """Undo ``seen``: these notices are open again."""
    ids = body.drive_ids or []
    app.repo.unsee_changes(ids)
    return {"drive_ids": ids}
