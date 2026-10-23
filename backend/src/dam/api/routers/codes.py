"""Filing codes: read the table and replace it as a whole."""

import html
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


# The sheet opened in its own browser tab: its inline styles need a policy of its own
# (the app page's ``style-src 'self'`` would blank them), and it may load nothing.
SHEET_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)
_SHEET_HEADERS = {"Content-Security-Policy": SHEET_CSP, "Referrer-Policy": "no-referrer"}


def _render_sheet(app: App, body: StickerSheetIn) -> str:
    """The sheet's HTML; ``InvalidRequest`` for an unknown code or layout, a start label
    off the sheet, a negative count, nothing to print or too many stickers."""
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
    if any(n > sheets.MAX_STICKERS for n in body.codes.values()):
        raise InvalidRequest(f"too many stickers: at most {sheets.MAX_STICKERS} at once")
    counts: dict[str, int] = {}
    for k, n in body.codes.items():
        counts[k.upper()] = counts.get(k.upper(), 0) + n
    try:
        return sheets.render_sheet(
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


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _flag(name: str, value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    if value.lower() in _TRUE:
        return True
    if value.lower() in _FALSE:
        return False
    raise InvalidRequest(f"{name} must be true or false")


def _whole(name: str, value: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise InvalidRequest(f"{name} must be a whole number") from None


def _sheet_query(
    codes: str, layout: str, start_at: str | None, boxes: str | None,
    blank_labels: str | None, outlines_only: str | None,
) -> StickerSheetIn:
    """The query as a ``StickerSheetIn``: ``codes`` is ``P:12,A:3`` (a code repeated
    adds up)."""
    counts: dict[str, int] = {}
    for part in (p.strip() for p in codes.split(",")):
        if not part:
            continue
        code, sep, n = part.rpartition(":")
        if not sep or not code:
            raise InvalidRequest("codes must look like P:12,A:3")
        counts[code] = counts.get(code, 0) + _whole(f"the count of {code}", n)
    return StickerSheetIn(
        codes=counts,
        layout=layout,
        start_at=_whole("start_at", start_at) if start_at else 1,
        boxes=_flag("boxes", boxes, True),
        blank_labels=_flag("blank_labels", blank_labels, False),
        outlines_only=_flag("outlines_only", outlines_only, False),
    )


def _error_page(message: str) -> HTMLResponse:
    page = (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        "<title>Sticker sheet</title></head>"
        f'<body><p class="error">{html.escape(message)}</p></body></html>\n'
    )
    return HTMLResponse(page, status_code=400, headers=_SHEET_HEADERS)


@router.get(
    "/sticker",
    response_class=Response,
    responses={200: {"content": {"image/svg+xml": {"schema": {"type": "string"}}}}},
)
def sticker_preview(code: str, label: str = "", boxes: str | None = None) -> Response:
    """One sticker as SVG, from the code and label as given (not the saved table): the
    Settings preview while a code is edited. ``boxes`` (default true): with the tick
    boxes. 400 for a code that is not 1 to 4 letters or digits or a label over 24
    characters. Changes nothing."""
    try:
        svg = sheets.sticker_preview(code, label, _flag("boxes", boxes, True))
    except ValueError as e:
        raise InvalidRequest(str(e)) from e
    return Response(
        svg,
        media_type="image/svg+xml",
        headers={"Content-Security-Policy": "default-src 'none'", "Cache-Control": "no-store"},
    )


@router.get(
    "/sheet",
    response_class=Response,
    responses={
        200: {"content": {"text/html": {"schema": {"type": "string"}}}},
        400: {"content": {"text/html": {"schema": {"type": "string"}}}},
    },
)
def sticker_sheet_page(
    app: AppDep,
    layout: str = "",
    codes: str = "",
    start_at: str | None = None,
    boxes: str | None = None,
    blank_labels: str | None = None,
    outlines_only: str | None = None,
) -> HTMLResponse:
    """The sticker sheet (HTML, A4) as a page to open in its own tab and print.
    ``codes``: ``P:12,A:3``; ``start_at``: the first label (1-based); ``boxes`` (default
    true), ``blank_labels`` and ``outlines_only`` (the test print): true or false. Its own
    Content-Security-Policy allows its inline styles and nothing else. A 400 (an unknown
    code or layout, a start label off the sheet, a negative count, nothing to print or
    more than 2000 stickers) is a small HTML page saying why. Changes nothing."""
    try:
        body = _sheet_query(codes, layout, start_at, boxes, blank_labels, outlines_only)
        return HTMLResponse(_render_sheet(app, body), headers=_SHEET_HEADERS)
    except InvalidRequest as e:
        return _error_page(str(e))
