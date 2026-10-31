"""Renewed… on an item of a tray with ``renew`` (the Renew tray): a new date and,
optionally, a new first file, with the Undo of the batch it was part of.

DB only: moving the old file to its folder's Expired subfolder is the caller's (a file
operation in the same batch). A renewal with a new file replaces the item's first file
(the other files stay) and passes the old file's ★ and ! marks to the new one; tags and
collections stay on the old file. Each renewal is a ``renewed`` item event holding what
its Undo needs; the Undo appends another ``renewed`` event and never deletes one.
"""

from __future__ import annotations

from collections import Counter
from contextlib import nullcontext
from dataclasses import asdict
from datetime import date

from sqlalchemy import func, select

from dam.collections.marks import MarkService, MarkState
from dam.db.engine import write_tx
from dam.db.tables import item_events, item_files, items
from dam.errors import InvalidRequest
from dam.trays.service import Item, TrayService, _check_drive_id

RENEWED = "renewed"


class RenewalService:
    def __init__(self, trays: TrayService, marks: MarkService) -> None:
        self.trays = trays
        self.marks = marks
        self.collections = marks.collections
        self.engine = trays.engine

    def record(
        self, item_id: int, expires: date, new_drive_id: str | None, batch_id: str | None
    ) -> Item:
        """Renew the item: ``expires`` is its new date; ``new_drive_id`` (None: the
        files stay) becomes its first file in place of the old one, and takes the old
        file's marks. One transaction; ``on_date_changed`` and, when marks moved, the
        publisher sync run after the commit."""
        if not isinstance(expires, date):
            raise InvalidRequest("The new expiry is a date")
        if new_drive_id is not None:
            new_drive_id = _check_drive_id(new_drive_id)
        lock = self.collections.important_lock if new_drive_id else nullcontext()
        marks: MarkState | None = None
        new_marks: MarkState | None = None
        with lock, write_tx(self.engine) as conn:
            row = self.trays._row(conn, item_id)
            tray = self.trays._find_tray(row.tray_id)
            if tray is None or tray.renew is None:
                raise InvalidRequest("Only an item of a tray with Renewed can be renewed")
            if row.state != "open":
                raise InvalidRequest(f"Item {item_id} is done: reopen it to renew it")
            before = self.trays._get(conn, item_id)
            old_drive_id = before.files[0] if before.files else None
            old_file = {"name": None, "path": None}
            if new_drive_id is not None:
                if old_drive_id is None:
                    raise InvalidRequest("The item has no file to replace")
                # the Undo takes the new file off the item, so it must not be on it yet
                if new_drive_id in before.files:
                    raise InvalidRequest("This file is already on the item")
                other = conn.execute(
                    select(items.c.id)
                    .join(item_files, item_files.c.item_id == items.c.id)
                    .where(
                        items.c.state == "open",
                        items.c.id != item_id,
                        item_files.c.drive_id == new_drive_id,
                    )
                    .limit(1)
                ).first()
                if other is not None:
                    raise InvalidRequest("That file belongs to another open item")
                old_file = self.trays._file_data(conn, old_drive_id)
                marks = self.marks.state_in(conn, old_drive_id)
                new_marks = self.marks.state_in(conn, new_drive_id)
                self.trays.replace_first_file(conn, item_id, old_drive_id, new_drive_id)
                if marks.starred or marks.important:
                    self.marks.transfer_in(conn, old_drive_id, new_drive_id, marks)
            self.trays.set_date_field(conn, item_id, expires)
            self.trays._event(
                conn,
                item_id,
                RENEWED,
                {
                    "old_date": before.date.isoformat() if before.date else None,
                    "new_date": expires.isoformat(),
                    "old_drive_id": old_drive_id,
                    "new_drive_id": new_drive_id,
                    "old_name": old_file["name"],
                    "old_path": old_file["path"],
                    "marks": asdict(marks) if marks is not None else None,
                    # what the new file had before, so the Undo leaves those marks on it
                    "new_marks": asdict(new_marks) if new_marks is not None else None,
                    "batch_id": batch_id,
                },
            )
            item = self.trays._get(conn, item_id)
        if marks is not None and (marks.starred or marks.important):
            self.collections.changed()
        if before.date != expires:
            self.trays._date_changed([item_id])
        return item

    def undo_batch(self, batch_id: str) -> int:
        """Undo the renewals of ``batch_id`` not undone yet; return how many. Each item
        gets its old first file back in front (the new one comes off) and the old file
        its marks (the new file keeps the ones it had before, in its own group); the old
        date comes back only while the date is still the renewal's. Other fields are
        not touched. No publisher sync here: the caller runs
        ``collections.changed`` (``ActivityService.undo``)."""
        batch = func.json_extract(item_events.c.data, "$.batch_id")
        restored: list[int] = []
        redated: list[int] = []
        with self.collections.important_lock, write_tx(self.engine) as conn:
            events = conn.execute(
                select(item_events)
                .where(item_events.c.kind == RENEWED, batch == batch_id)
                .order_by(item_events.c.id.desc())
            ).all()
            # an Undo of this batch already ran for these renewals (latest first)
            undone = Counter(e.item_id for e in events if e.data.get("undo"))
            for ev in events:
                if ev.data.get("undo"):
                    continue
                if undone[ev.item_id]:
                    undone[ev.item_id] -= 1
                    continue
                data = ev.data
                old, new = data.get("old_drive_id"), data.get("new_drive_id")
                if new is not None and old is not None:
                    self.trays.replace_first_file(conn, ev.item_id, new, old)
                    if data.get("marks"):
                        state = MarkState(**data["marks"])
                        if state.starred or state.important:
                            prior = data.get("new_marks")
                            self.marks.restore_in(
                                conn, old, new, state, MarkState(**prior) if prior else None
                            )
                current = self.trays._get(conn, ev.item_id).date
                if current is not None and current.isoformat() == data["new_date"]:
                    old_date = data.get("old_date")
                    self.trays.set_date_field(
                        conn, ev.item_id, date.fromisoformat(old_date) if old_date else None
                    )
                    redated.append(ev.item_id)
                self.trays._event(conn, ev.item_id, RENEWED, {"undo": True, "batch_id": batch_id})
                restored.append(ev.item_id)
        self.trays._date_changed(redated)
        return len(restored)
