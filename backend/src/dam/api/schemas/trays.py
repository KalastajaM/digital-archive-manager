"""Trays and their items (dam.api.schemas)."""

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from dam.api.schemas.base import StrictIn
from dam.api.schemas.responses import Mark
from dam.api.schemas.rules import RuleErrorOut
from dam.trays.model import TrayDef

# -- Phase 2: trays and items ------------------------------------------------------


class TraysOut(BaseModel):
    trays: list[TrayDef]  # in order; a field's ``copy`` means "show a copy button"
    errors: list[RuleErrorOut]  # tray files that were skipped


class ItemOut(BaseModel):
    id: int
    tray_id: str
    title: str
    # field name -> value: dates as "YYYY-MM-DD", money as "84.20", text, IBAN and
    # reference as text, checkbox as bool; a value named in ``invalid_fields`` is the
    # raw stored value
    fields: dict[str, Any]
    date: date | None
    state: Literal["open", "done"]
    created: float
    done_at: float | None
    done_fields: dict[str, Any] | None
    files: list[str]  # drive ids
    created_by_batch: str | None
    missing_required: list[str]
    invalid_fields: list[str]
    tray_name: str
    tray_removed: bool


class PrintedFieldsOut(BaseModel):
    iban: str
    amount: str | None
    reference: str
    due_date: date | None


class ItemBarcodeOut(BaseModel):
    """The item's Finnish bank barcode, built from its current fields."""

    code: str | None  # the 54 digits; None when it cannot be built (see ``reason``)
    modules: list[int] | None  # Code 128 set C bar/space widths, bar first
    reason: str | None  # one line: why there is no barcode
    printed: str | None  # the barcode read from one of the item's files
    # ``printed``'s values in the item field formats ("FI…" compact, "84.20",
    # "YYYY-MM-DD"); amount/due_date None where the barcode leaves them open
    printed_fields: PrintedFieldsOut | None
    mismatch: list[str]  # field names where ``printed`` disagrees with the fields


class QuickOut(BaseModel):
    created: list[ItemOut]
    skipped: list[str]  # drive ids that already had an open item in that tray
    # open items of other trays moved into this one (a file lives in one tray), and the
    # tray id each came from, by item id (as a string key), for the Undo
    moved: list[ItemOut]
    moved_from: dict[str, str]


class ItemMoveBody(StrictIn):
    """Move an open item to another tray."""

    tray: str


class ItemFileOut(BaseModel):
    drive_id: str
    path: str | None  # None: not in the index
    ext: str | None
    # "missing": gone (or parked); "to_delete": in the quarantine folder
    state: Literal["ok", "missing", "to_delete"]
    # present and directly in the inbox or in a filing code's inbox folder (not filed yet)
    in_inbox: bool
    marks: list[Mark]
    # the extra archive folder it lies in (None: the main folder, or not in the index),
    # and whether that folder is connected now
    folder: str | None = None
    connected: bool = True


class TrayItemOut(ItemOut):
    """An item as a tray list shows it: how urgent (the Today levels; None when done or
    dated later), whether a file is missing or in the quarantine folder, whether the
    item has a note, and its first file (for Quick Look on the list)."""

    level: Literal["overdue", "today", "soon", "undated"] | None
    file_state: Literal["ok", "missing", "to_delete"]
    has_note: bool
    checklist_open: int  # open to-dos on the item's checklist
    checklist_total: int
    # "written": the owner wrote a summary on any of its files, else "ai" if any has one
    summary: Literal["ai", "written"] | None
    first_file: ItemFileOut | None  # None: the item has no files


class ItemEventOut(BaseModel):
    id: int
    at: float
    kind: Literal[
        "created", "edited", "done", "reopened", "file_added", "file_removed", "moved", "merged_in"
    ]
    data: dict[str, Any]
