"""Converting the current ``##. Ongoing`` into collections, one entry at a time."""

from fastapi import APIRouter

from dam.api.deps import AppDep
from dam.api.marks import entries_out
from dam.api.schemas import (
    ConvertApplyBody,
    ConvertBody,
    ConvertPlanOut,
    ConvertResultOut,
    EntryOut,
)

router = APIRouter(prefix="/api/ongoing", tags=["ongoing"])


@router.get("/entries", response_model=list[EntryOut])
def entries(app: AppDep) -> list:
    return entries_out(app, app.convert.entries())


@router.post("/preview", response_model=ConvertPlanOut)
def preview(app: AppDep, body: ConvertBody):
    """``star``: "Star it" (a link or a real file becomes a ★ member)."""
    return app.convert.preview(
        body.rel, body.collection, body.destination, body.star, body.to_inbox
    )


@router.post("/convert", response_model=ConvertResultOut)
def convert(app: AppDep, body: ConvertApplyBody):
    """Apply exactly the previewed plan (``fingerprint``); a different plan now is 400."""
    return app.convert.apply(
        body.rel,
        body.collection,
        body.destination,
        body.fingerprint,
        body.star,
        body.to_inbox,
    )
