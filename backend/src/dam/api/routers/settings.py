"""Archive settings the app writes to ``settings.yaml``."""

from fastapi import APIRouter

from dam.api.deps import AppDep
from dam.api.schemas import Page1BackfillIn, Page1BackfillOut

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.put("/page1-backfill", response_model=Page1BackfillOut)
def put_page1_backfill(app: AppDep, body: Page1BackfillIn) -> dict:
    """Turn the backfill of page-1 positions for documents outside the inbox on or off.
    400 when settings.yaml could not be written (it is left as it was)."""
    app.set_page1_backfill(body.enabled)
    return {"enabled": app.settings.page1_backfill}
