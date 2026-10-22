"""Converting the user's own ``##. Important`` into the ! Important built-in, one
top-level entry at a time (stars, Task 3): the same binding preview as Convert
Ongoing (``fingerprint``), one undoable batch per entry."""

from fastapi import APIRouter

from dam.api.deps import AppDep
from dam.api.marks import entries_out
from dam.api.schemas import (
    ConvertPlanOut,
    ConvertResultOut,
    EntryOut,
    ImportantConvertApplyBody,
    ImportantConvertBody,
)

router = APIRouter(prefix="/api/important", tags=["important"])


@router.get("/entries", response_model=list[EntryOut])
def entries(app: AppDep) -> list:
    return entries_out(app, app.convert_important.entries())


@router.post("/preview", response_model=ConvertPlanOut)
def preview(app: AppDep, body: ImportantConvertBody):
    return app.convert_important.preview(body.rel, body.destination)


@router.post("/convert", response_model=ConvertResultOut)
def convert(app: AppDep, body: ImportantConvertApplyBody):
    """Apply exactly the previewed plan (``fingerprint``); a different plan now is 400."""
    return app.convert_important.apply(body.rel, body.destination, body.fingerprint)
