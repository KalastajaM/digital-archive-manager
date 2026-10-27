"""Filing codes and their sticker sheets (dam.api.schemas)."""

from typing import Literal

from pydantic import BaseModel, Field

from dam.api.schemas.base import StrictIn
from dam.api.schemas.responses import CodeHitOut

# -- filing codes -------------------------------------------------------------


class FilingCodeIn(StrictIn):
    # checked by ``FilingCode`` (and the app) so a bad entry answers 400 with its text
    code: str
    label: str = ""
    tray: str | None = None
    folder: str | None = None
    name: str | None = None
    tags: list[str] = Field(default_factory=list)
    collections: list[str] = Field(default_factory=list)
    as_suggested: bool = False
    inbox_folder: str | None = None


class FilingCodeOut(BaseModel):
    code: str
    label: str
    tray: str | None
    folder: str | None
    name: str | None
    tags: list[str]
    collections: list[str]
    as_suggested: bool
    inbox_folder: str | None


class CodeProblemOut(BaseModel):
    code: str
    message: str


class CodeWarningOut(BaseModel):
    code: str
    confusable_with: list[str]


class FilingCodesOut(BaseModel):
    codes: list[FilingCodeOut]
    problems: list[CodeProblemOut]
    warnings: list[CodeWarningOut]


class SheetLayoutIn(StrictIn):
    # checked by ``SheetLayout`` so a grid that does not fit A4 answers 400 with its text
    name: str
    columns: int
    rows: int
    label_w_mm: float
    label_h_mm: float
    top_mm: float
    left_mm: float
    gap_x_mm: float
    gap_y_mm: float
    cut_lines: bool = False


class SheetLayoutOut(BaseModel):
    id: str
    name: str
    columns: int
    rows: int
    label_w_mm: float
    label_h_mm: float
    top_mm: float
    left_mm: float
    gap_x_mm: float
    gap_y_mm: float
    cut_lines: bool


class StickerSheetIn(StrictIn):
    # the sheet GET's query, parsed
    # how many stickers of each code, in print order (checked by the route: 400)
    codes: dict[str, int]
    layout: str
    start_at: int = 1
    boxes: bool = True
    blank_labels: bool = False
    outlines_only: bool = False


class AssignCodeIn(StrictIn):
    # give these inbox files this filing code (None: take their assigned code away)
    drive_ids: list[str]
    code: str | None


class AssignCodeOut(BaseModel):
    drive_ids: list[str]
    code: str | None


class FilingCodeFoldersOut(BaseModel):
    # code inbox folders not in the inbox yet, and inbox subfolders that are no code's
    missing: list[str]
    stray: list[str]


class FileRequestOut(BaseModel):
    """A filing request as ``POST /api/inbox/file`` takes it (``FileRequestIn``)."""

    drive_id: str
    name: str
    folder: str  # "" when nothing suggests one (the row needs input)
    tags: list[str]
    tray: str | None
    tray_fields: dict[str, str]
    collections: list[str]
    note: str
    star: bool
    important: bool


class BatchRowOut(BaseModel):
    """A row of the File N marked batch: an inbox file with a filing code, the request
    that files it and the tray fields that will be stored. ``flag``: why the row starts
    unticked (``unclear``: a code or a sticker's tick box read uncertainly,
    ``conflict``: codes disagree, ``needs_input``: the filing would be refused);
    ``problem`` says what to fix ("folder", "Tick box unclear: star", a required tray
    field such as "due date", or the refusal)."""

    drive_id: str
    codes: list[CodeHitOut]
    request: FileRequestOut
    tray_fields: dict[str, str]
    flag: Literal["unclear", "conflict", "needs_input"] | None
    problem: str | None
