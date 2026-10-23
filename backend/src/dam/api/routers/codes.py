"""Filing codes: read the table and replace it as a whole."""

from dataclasses import asdict

from fastapi import APIRouter, Response
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from dam.api.deps import UI_ORIGIN, AppDep
from dam.api.schemas import (
    BatchResultOut,
    BatchRowOut,
    FilingCodeFoldersOut,
    FilingCodeIn,
    FilingCodesOut,
    ResolvedOpOut,
    SheetLayoutIn,
    SheetLayoutOut,
    StickerSheetIn,
)
from dam.app import App
from dam.codes import folders, sheets
from dam.codes.batch import marked_rows
from dam.codes.model import FilingCode, confusable_with, format_validation
from dam.services.errors import InvalidRequest

router = APIRouter(prefix="/api/filing-codes", tags=["filing-codes"])


def _out(app: App) -> dict:
    codes = [c.code for c in app.codes]
    warnings = []
    for c in codes:
        others = confusable_with(c, [o for o in codes if o != c])
        if others:
            warnings.append({"code": c, "confusable_with": others})
    return {
        "codes": [c.model_dump() for c in app.codes],
        "problems": [asdict(p) for p in app.code_problems],
        "warnings": warnings,
    }


@router.get("", response_model=FilingCodesOut)
def list_codes(app: AppDep) -> dict:
    """The loaded codes, entries of the file that were skipped (``problems``) and codes
    that look like each other (``warnings``)."""
    return _out(app)


@router.put("", response_model=FilingCodesOut)
def replace_codes(app: AppDep, body: list[FilingCodeIn]) -> dict:
    """Replace the whole table (the old file is kept as a backup); 400 with the reason
    if any code is invalid, repeated or names an unknown tray."""
    codes = []
    for entry in body:
        try:
            codes.append(FilingCode.model_validate(entry.model_dump()))
        except ValidationError as e:
            raise InvalidRequest(f"{entry.code}: {format_validation(e)}") from e
    app.save_codes(codes)
    return _out(app)


@router.get("/folders", response_model=FilingCodeFoldersOut)
def code_folders(app: AppDep) -> dict:
    """The codes' inbox folders that are missing, and inbox subfolders that are no code's."""
    return {
        "missing": folders.missing_inbox_folders(app),
        "stray": folders.stray_inbox_folders(app),
    }


@router.post("/folders/preview", response_model=list[ResolvedOpOut])
def code_folders_preview(app: AppDep) -> list:
    """The folders "Create the folders" would make. Changes nothing."""
    return folders.preview_inbox_folders(app, origin=UI_ORIGIN)


@router.post("/folders", response_model=BatchResultOut)
def create_code_folders(app: AppDep):
    """Make the missing code folders in the inbox: journaled, undoable while empty."""
    return folders.create_inbox_folders(app, origin=UI_ORIGIN)


@router.get("/batch", response_model=list[BatchRowOut])
def batch(app: AppDep) -> list:
    """The File N marked rows: each inbox file with a filing code, the request that files
    it (post the ticked ones to ``/api/inbox/file``) and a flag when it needs a look.
    Changes nothing."""
    return marked_rows(app)


@router.get("/sheets", response_model=list[SheetLayoutOut])
def sheet_layouts(app: AppDep) -> list:
    """The sticker sheet layouts: the built-in ones, then the saved custom one (id
    ``custom``) if there is one."""
    return [lay.model_dump() for lay in sheets.load_layouts(app.app_paths.config_dir)]


@router.put("/sheets/custom", response_model=SheetLayoutOut)
def save_custom_sheet(app: AppDep, body: SheetLayoutIn) -> dict:
    """Save the custom sheet layout (the old file is kept as a backup); 400 with the
    reason if the labels do not fit an A4 page or are too small for a sticker."""
    try:
        layout = sheets.SheetLayout.model_validate({"id": sheets.CUSTOM_ID, **body.model_dump()})
    except ValidationError as e:
        raise InvalidRequest(format_validation(e)) from e
    try:
        return sheets.save_custom(app.app_paths.config_dir, layout).model_dump()
    except OSError as e:
        raise InvalidRequest(f"the layout could not be saved: {e}") from e


@router.post(
    "/sheet",
    response_class=Response,  # not HTMLResponse: errors stay JSON in the schema
    responses={200: {"content": {"text/html": {"schema": {"type": "string"}}}}},
)
def sticker_sheet(app: AppDep, body: StickerSheetIn) -> HTMLResponse:
    """A printable page of stickers (HTML, A4) for the chosen codes and counts; 400 for
    an unknown code or layout, a start label off the sheet, a negative count, nothing to
    print or more than 2000 stickers. Changes nothing."""
    table = {c.code: c for c in app.codes}
    unknown = [k for k in body.codes if k.upper() not in table]
    if unknown:
        raise InvalidRequest(f"unknown filing code: {', '.join(unknown)}")
    layout = next(
        (lay for lay in sheets.load_layouts(app.app_paths.config_dir) if lay.id == body.layout),
        None,
    )
    if layout is None:
        raise InvalidRequest(f"unknown sheet layout {body.layout!r}")
    if any(n < 0 for n in body.codes.values()):
        raise InvalidRequest("a count cannot be negative")
    counts: dict[str, int] = {}
    for k, n in body.codes.items():
        counts[k.upper()] = counts.get(k.upper(), 0) + n
    try:
        page = sheets.render_sheet(
            [table[k] for k in counts],
            counts,
            layout,
            start_at=body.start_at,
            boxes=body.boxes,
            blank_labels=body.blank_labels,
            outlines_only=body.outlines_only,
        )
    except ValueError as e:
        raise InvalidRequest(str(e)) from e
    return HTMLResponse(page, headers={"X-Content-Type-Options": "nosniff"})
