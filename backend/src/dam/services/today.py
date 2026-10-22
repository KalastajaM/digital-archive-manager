"""Today: the items that need attention now, and an overview of trays and collections.

Reads only. Levels: ``overdue`` (date before today), ``today``, ``soon`` (within the
next ``SOON_DAYS`` days) and ``undated`` (an open item in a tray with a date field but
no usable date: it "needs a due date"). Items dated later are not listed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from dam.collections.service import CollectionService
from dam.core.paths import nfc
from dam.index.repo import FileRecord, FileRepo
from dam.notes import NotesService
from dam.ops.guards import is_under
from dam.services.errors import ArchiveUnavailable
from dam.trays.model import FIELD_TYPES, TrayDef
from dam.trays.service import Item, TrayService

if TYPE_CHECKING:
    from dam.services.inbox import InboxEntry

SOON_DAYS = 3
EXCERPT_CHARS = 120
OPEN_ITEMS_PER_TRAY = 8  # rows a tray card on Today shows

Level = Literal["overdue", "today", "soon", "undated"]
FileState = Literal["ok", "missing", "to_delete"]
_LEVEL_ORDER = {"overdue": 0, "today": 1, "soon": 2, "undated": 3}


@dataclass
class AttentionItem:
    item: Item
    tray: str  # the tray id
    level: Level
    missing_required: list[str]
    # "missing": a file of the item is gone (or parked); "to_delete": one is in the
    # quarantine folder; "ok" otherwise
    file_state: FileState
    note_excerpt: str | None  # the item's note on one line, cut at EXCERPT_CHARS; None: no note


@dataclass
class TrayCount:
    tray_id: str
    name: str
    open: int
    overdue: int
    sum: Decimal | None  # the tray's ``summary`` field over its open items; None without one
    waiting_long: int  # open items older than the tray's ``nudge_after_days``


@dataclass
class TrayItems:
    """A tray's first open items for its card on Today: by date, undated last."""

    tray_id: str
    items: list[Item]


@dataclass
class CollectionSummary:
    id: int
    name: str
    files: int
    open_checks: int
    note_excerpt: str
    in_inbox: int  # file members still directly in the inbox (not filed yet)


@dataclass
class Overview:
    inbox: int
    trays: list[TrayCount]
    collections: list[CollectionSummary]


@dataclass
class InboxStats:
    """Today's inbox card. Ages are local days since the file's mtime (its arrival in
    the inbox): ``this_week`` under 7, ``last_week`` 7 to 13, ``older`` 14 or more.
    ``overdue``: inbox files whose scanned due date is before today."""

    count: int
    oldest_days: int | None  # None: no inbox file with a usable mtime
    this_week: int
    last_week: int
    older: int
    overdue: int


@dataclass
class Found:
    """An inbox document whose scan says it belongs in a tray it is not yet in."""

    drive_id: str
    name: str
    tray: str  # the guessed tray's id
    tray_name: str
    due_date: date | None  # from the scan
    total: Decimal | None  # from the scan
    overdue: bool  # the scanned due date is before today


def _age_days(mtime: float | None, today: date) -> int | None:
    if mtime is None:
        return None
    try:
        return (today - date.fromtimestamp(mtime)).days
    except (OverflowError, OSError, ValueError):
        return None


def _level(when: date | None, today: date) -> Level | None:
    if when is None:
        return None
    if when < today:
        return "overdue"
    if when == today:
        return "today"
    if when <= today + timedelta(days=SOON_DAYS):
        return "soon"
    return None


def _excerpt(text: str) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= EXCERPT_CHARS:
        return one_line
    return one_line[:EXCERPT_CHARS].rstrip() + "…"


class TodayService:
    def __init__(
        self,
        trays: TrayService,
        tray_defs: Callable[[], list[TrayDef]],
        collections: CollectionService,
        notes: NotesService,
        inbox_count: Callable[[], int],
        repo: FileRepo,
        quarantine: str,
        unmanaged_count: Callable[[], int],
        inbox_entries: Callable[[], list[InboxEntry]] = lambda: [],
        unmanaged_important_count: Callable[[], int] = lambda: 0,
    ) -> None:
        self.trays = trays
        self._tray_defs = tray_defs
        self.collections = collections
        self.notes = notes
        self._inbox_count = inbox_count
        self.repo = repo
        self._quarantine = nfc(quarantine)
        self._unmanaged_count = unmanaged_count
        self._unmanaged_important_count = unmanaged_important_count
        # the inbox files with their suggestions (InboxService.list: one directory
        # listing plus each file's text; no tree walk)
        self._inbox_entries = inbox_entries

    def file_info(self, item: Item) -> list[tuple[FileRecord | None, FileState]]:
        """Each file of the item with its record (None if unknown) and its state:
        "missing" (gone or parked), "to_delete" (in the quarantine folder) or "ok"."""
        out: list[tuple[FileRecord | None, FileState]] = []
        for drive_id in item.files:
            rec = self.repo.get(drive_id)
            if rec is None or rec.missing or rec.parked_at is not None:
                out.append((rec, "missing"))
            elif is_under(rec.path_nfc, self._quarantine):
                out.append((rec, "to_delete"))
            else:
                out.append((rec, "ok"))
        return out

    def file_state(
        self, item: Item, info: list[tuple[FileRecord | None, FileState]] | None = None
    ) -> FileState:
        """The item's worst file state (``info``: a ``file_info(item)`` result to reuse)."""
        states = {state for _rec, state in (self.file_info(item) if info is None else info)}
        if "missing" in states:
            return "missing"
        return "to_delete" if "to_delete" in states else "ok"

    def level(self, item: Item, today: date) -> Level | None:
        """How urgent an open item is (None: done, or dated later than "soon")."""
        if item.state != "open":
            return None
        level = _level(item.date, today)
        if level is None and item.date is None:
            tray = next((t for t in self._tray_defs() if t.id == item.tray_id), None)
            # only a required date is "missing"; an optional one (Follow up) may stay empty
            date_def = tray.fields.get(tray.date_field) if tray and tray.date_field else None
            if date_def is not None and date_def.required:
                level = "undated"
        return level

    def attention(self, today: date) -> list[AttentionItem]:
        """Open items that are overdue, due today or soon, or need a date; most urgent
        first (by level, then date)."""
        out: list[AttentionItem] = []
        for item in self.trays.list(None, "open"):
            level = self.level(item, today)
            if level is None:
                continue
            note = self.notes.get("item", str(item.id))
            out.append(
                AttentionItem(
                    item,
                    item.tray_id,
                    level,
                    list(item.missing_required),
                    self.file_state(item),
                    _excerpt(note) if note.strip() else None,
                )
            )
        out.sort(key=lambda a: (_LEVEL_ORDER[a.level], a.item.date or date.max))
        return out

    def _count(self, tray: TrayDef, open_items: list[Item], today: date) -> TrayCount:
        mine = [i for i in open_items if i.tray_id == tray.id]
        total = None
        if tray.summary is not None:
            money = FIELD_TYPES["money"]
            total = Decimal("0.00")
            for i in mine:
                value = i.fields.get(tray.summary.sum)
                if isinstance(value, Decimal) and tray.summary.sum not in i.invalid_fields:
                    total += value
            total = money.parse(total)
        waiting = 0
        if tray.nudge_after_days is not None:
            cutoff = today - timedelta(days=tray.nudge_after_days)
            waiting = sum(1 for i in mine if datetime.fromtimestamp(i.created).date() <= cutoff)
        overdue = sum(1 for i in mine if i.date is not None and i.date < today)
        return TrayCount(tray.id, tray.name, len(mine), overdue, total, waiting)

    def open_items(self, limit: int = OPEN_ITEMS_PER_TRAY) -> list[TrayItems]:
        """The first ``limit`` open items of each tray, in tray order, sorted by date
        with undated items last (then oldest first). Database only: no file lookups."""
        open_items = self.trays.list(None, "open")
        out: list[TrayItems] = []
        for tray in self._tray_defs():
            mine = sorted(
                (i for i in open_items if i.tray_id == tray.id),
                key=lambda i: (i.date is None, i.date or date.max, i.created, i.id),
            )
            out.append(TrayItems(tray.id, mine[:limit]))
        return out

    def collection_counts(self, collection_id: int) -> tuple[int, int]:
        """(usable files, folder members expanded; open checklist entries)."""
        checks = self.notes.checklist("collection", str(collection_id))
        return len(self.collections.expand(collection_id)), sum(1 for x in checks if not x.done)

    def collection_in_inbox(self, collection_id: int) -> int:
        """File members still directly in the inbox, by the rule of the collection's
        "Needs attention" strip (present, not quarantined)."""
        members = self.collections.get(collection_id).members
        return sum(
            1
            for m in members
            if not m.is_dir
            and m.path is not None
            and not m.missing
            and not m.quarantined
            and self.repo.in_inbox_path(m.path)
        )

    def overview(self, today: date, entries: list[InboxEntry] | None = None) -> Overview:
        """``entries``: an ``inbox_entries()`` result; when given, the inbox count is its
        length, so it always agrees with ``inbox_stats`` on the same page."""
        open_items = self.trays.list(None, "open")
        trays = [self._count(t, open_items, today) for t in self._tray_defs()]
        summaries = []
        for c in self.collections.list("open"):
            files, open_checks = self.collection_counts(c.id)
            summaries.append(
                CollectionSummary(
                    id=c.id,
                    name=c.name,
                    files=files,
                    open_checks=open_checks,
                    note_excerpt=_excerpt(self.notes.get("collection", str(c.id))),
                    in_inbox=self.collection_in_inbox(c.id),
                )
            )
        inbox = self._inbox_count() if entries is None else len(entries)
        return Overview(inbox, trays, summaries)

    def unmanaged_ongoing(self) -> int:
        """Top-level ``##. Ongoing`` entries that could be converted into collections, by
        a shallow check (top-level entries only; the conversion preview checks deeply);
        0 when Ongoing is unavailable."""
        try:
            return self._unmanaged_count()
        except (ArchiveUnavailable, OSError):
            return 0

    def unmanaged_important(self) -> int:
        """Top-level ``##. Important`` entries the app does not manage yet (Convert
        Important), by the same shallow check; 0 when the folder is unavailable."""
        try:
            return self._unmanaged_important_count()
        except (ArchiveUnavailable, OSError):
            return 0

    def inbox_entries(self) -> list[InboxEntry]:
        return self._inbox_entries()

    def inbox_stats(self, today: date, entries: list[InboxEntry] | None = None) -> InboxStats:
        """Counts for the inbox card (``entries``: an ``inbox_entries()`` result to
        reuse; listed afresh when None)."""
        entries = self._inbox_entries() if entries is None else entries
        ages = [a for e in entries if (a := _age_days(e.record.mtime, today)) is not None]
        overdue = sum(
            1
            for e in entries
            if e.suggestion.fields.due_date is not None and e.suggestion.fields.due_date < today
        )
        return InboxStats(
            count=len(entries),
            oldest_days=max(ages) if ages else None,
            this_week=sum(1 for a in ages if a < 7),
            last_week=sum(1 for a in ages if 7 <= a < 14),
            older=sum(1 for a in ages if a >= 14),
            overdue=overdue,
        )

    def found_in_inbox(
        self, today: date | None = None, entries: list[InboxEntry] | None = None
    ) -> list[Found]:
        """Inbox files with a tray guess that have no open item in that tray, newest
        first (``entries`` as for ``inbox_stats``)."""
        today = date.today() if today is None else today
        entries = self._inbox_entries() if entries is None else entries
        names = {t.id: t.name for t in self._tray_defs()}
        out: list[Found] = []
        for e in entries:
            if e.tray_guess is None or e.tray_guess in e.open_trays:
                continue
            fields = e.suggestion.fields
            out.append(
                Found(
                    drive_id=e.record.drive_id,
                    name=e.record.name or e.record.path,
                    tray=e.tray_guess,
                    tray_name=names.get(e.tray_guess, e.tray_guess),
                    due_date=fields.due_date,
                    total=fields.total,
                    overdue=fields.due_date is not None and fields.due_date < today,
                )
            )
        return out
