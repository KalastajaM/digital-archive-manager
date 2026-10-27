"""The Today screen (dam.api.schemas)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from dam.api.schemas.responses import Mark
from dam.api.schemas.rules import RuleErrorOut
from dam.api.schemas.trays import ItemOut

# -- Today ----------------------------------------------------------------------------


class AttentionItemOut(BaseModel):
    item: ItemOut
    tray: str
    level: Literal["overdue", "today", "soon", "undated"]
    missing_required: list[str]
    file_state: Literal["ok", "missing", "to_delete"]
    note_excerpt: str | None  # the item's note on one line, at most 120 chars + "…"


class TrayCountOut(BaseModel):
    tray_id: str
    name: str
    open: int
    overdue: int
    sum: Decimal | None
    waiting_long: int


class CollectionSummaryOut(BaseModel):
    id: int
    name: str
    files: int
    open_checks: int
    note_excerpt: str
    # file members still directly in the inbox or in a filing code's inbox folder
    in_inbox: int


class OverviewOut(BaseModel):
    inbox: int
    trays: list[TrayCountOut]
    collections: list[CollectionSummaryOut]


class InboxStatsOut(BaseModel):
    count: int
    oldest_days: int | None  # local days since the oldest inbox file's mtime
    this_week: int  # under 7 days
    last_week: int  # 7 to 13 days
    older: int  # 14 days or more
    overdue: int  # scanned due date before today


class FoundOut(BaseModel):
    """An inbox document guessed to belong in a tray it has no open item in."""

    drive_id: str
    name: str
    tray: str
    tray_name: str
    due_date: date | None
    total: Decimal | None
    overdue: bool
    marks: list[Mark]


class RemindersStatusOut(BaseModel):
    last_run: datetime | None  # the last completed check (None: none since start)
    errors: dict[str, str] = Field(description="channel id -> error of the last check")
    skipped: str | None  # why the latest check was skipped (another run was busy)


class TrayItemsOut(BaseModel):
    """A tray's first open items for its Today card: by date, undated last."""

    tray_id: str
    items: list[ItemOut]


class TodayOut(BaseModel):
    attention: list[AttentionItemOut]
    overview: OverviewOut
    unmanaged_ongoing: int
    # top-level ``##. Important`` entries not managed by the app yet (Convert Important)
    unmanaged_important: int = 0
    # why the Ongoing sync keeps failing (the same plan is not retried); None when fine
    ongoing_sync_failure: str | None
    reminders: RemindersStatusOut
    tray_errors: list[RuleErrorOut]
    inbox_stats: InboxStatsOut
    found: list[FoundOut]
    open_items: list[TrayItemsOut]  # per tray in tray order, at most 8 each
    # inbox files with a filing code (the File N marked button), flagged ones included
    marked: int = 0
    # inbox files the barcode pass has still to read for QR stickers ("Reading filing
    # codes..."); 0 when the code table is empty
    reading_codes: int = 0
