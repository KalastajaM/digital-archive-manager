"""Renewed… on an item of a tray with ``renew`` (the Renew tray): a new date and,
optionally, a new first file, with the Undo of the batch it was part of.

``record`` is DB only. ``apply`` is the whole renewal from the tray: with a new file, the
old one moves into its folder's Expired subfolder (one journaled batch, ``preview``
shows it first; a locked old file needs the request's unlock grant), then ``record``
runs with that batch's id. A renewal with a new file replaces the item's first file
(the other files stay) and passes the old file's ★ and ! marks to the new one; tags and
collections stay on the old file. Each renewal is a ``renewed`` item event holding what
its Undo needs; the Undo appends another ``renewed`` event and never deletes one.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Literal
from uuid import uuid4

from sqlalchemy import Connection, func, select

from dam.collections.marks import MarkService, MarkState
from dam.db.engine import write_tx
from dam.db.tables import item_events, item_files, items, operations
from dam.errors import Conflict, InvalidRequest, NotFound
from dam.index.repo import FileRepo
from dam.locks import LOCKED_MESSAGE, request_tokens
from dam.ops.executor import Executor
from dam.ops.guards import parent
from dam.ops.model import Op, OpKind, Plan, ResolvedOp
from dam.services import check_destination_area, check_disk_identity, check_origin
from dam.trays.service import Item, TrayService, _check_drive_id

RENEWED = "renewed"
GONE = "The old file is no longer in the archive"
IN_TO_DELETE = "The old file is in To Delete"
NOT_CONNECTED = "The old file's archive folder is not connected"


@dataclass
class RenewalPlan:
    """What a renewal does on disk: ``plan`` moves the old file (``old``) into Expired,
    or is None (no new file, or the move is ``skipped`` for that reason); ``locked``:
    the old file as ``{drive_id, name}`` when it is locked and the request carries no
    grant for it (nothing can be applied then)."""

    title: str
    old: str | None = None
    plan: Plan | None = None
    skipped: str | None = None
    locked: list[dict] = field(default_factory=list)


@dataclass
class RenewalPreview:
    ops: list[ResolvedOp]
    skipped: str | None
    locked: list[dict]


@dataclass
class Renewal:
    """A renewal applied: ``undo`` says which Undo reverses it, Activity's (its file
    ops were journaled under ``batch_id``) or the renewal's own (``undo``)."""

    item: Item
    batch_id: str
    undo: Literal["activity", "renewal"]
    skipped: str | None


class RenewalService:
    def __init__(
        self,
        trays: TrayService,
        marks: MarkService,
        repo: FileRepo,
        executor: Executor,
        expired_name: Callable[[], str],
    ) -> None:
        self.trays = trays
        self.marks = marks
        self.collections = marks.collections
        self.engine = trays.engine
        self.repo = repo
        self.executor = executor
        self.expired_name = expired_name  # the settings' ``expired_folder_name``

    # --- the move of the old file -----------------------------------------------------

    def move_op(self, old_drive_id: str) -> tuple[Op | None, str | None]:
        """The MOVE of the old file into ``<its folder>/<Expired>`` (the planner makes
        the folder and gives a taken name ``_2``), or None and why it is skipped: the
        file is gone, in To Delete, or in an archive folder that is not connected."""
        rec = self.repo.get(old_drive_id)
        if rec is None or rec.missing or rec.parked_at is not None:
            return None, GONE
        paths = self.executor.paths
        if paths.is_quarantined(rec.path_nfc):
            return None, IN_TO_DELETE
        label = paths.label_of(rec.path)
        if label and not paths.is_connected(label):
            return None, NOT_CONNECTED
        dest = f"{parent(rec.path)}/{self.expired_name()}"
        check_destination_area(dest, paths)
        return Op(OpKind.MOVE, rec.path, dest), None

    def plan(self, item_id: int, new_drive_id: str | None, origin: str) -> RenewalPlan:
        """The renewal's file plan, refused (``InvalidRequest``) as ``record`` would
        refuse it. Read only."""
        check_origin(origin)
        if new_drive_id is not None:
            new_drive_id = _check_drive_id(new_drive_id)
        with self.engine.connect() as conn:
            before = self._renewable(conn, item_id)
            if new_drive_id is None:
                return RenewalPlan(before.title)
            self._check_new_file(conn, item_id, before, new_drive_id)
        old = before.files[0]
        out = RenewalPlan(before.title, old)
        op, out.skipped = self.move_op(old)
        if op is None:
            return out
        locks = self.executor.locks
        if locks is not None and locks.refused(
            op.src, old, locks.entries(), locks.granted(request_tokens())
        ):
            out.locked = [{"drive_id": old, "name": self.repo.get(old).name}]
            return out
        out.plan = Plan(
            [op],
            origin=origin,
            label=f"Renewed {before.title}: moved {self.repo.get(old).name} to "
            f"{self.expired_name()}",
        )
        return out

    def _check(self, plan: RenewalPlan) -> Callable[[list[ResolvedOp]], None]:
        """The resolved MOVE must be the old file as indexed (``check_disk_identity``)."""
        paths = self.executor.paths
        return lambda ops: check_disk_identity(paths, self.repo, [plan.old], ops)

    def preview(self, item_id: int, new_drive_id: str | None, origin: str = "ui") -> RenewalPreview:
        """What ``apply`` would do: the resolved ops (a new Expired folder, the move),
        why the move is skipped, or the locked old file (then no ops: the planner would
        refuse it). Nothing is changed or journaled."""
        p = self.plan(item_id, new_drive_id, origin)
        ops: list[ResolvedOp] = []
        if p.plan is not None:
            ops = self.executor.preview(p.plan)
            self._check(p)(ops)
        return RenewalPreview(ops, p.skipped, p.locked)

    def apply(
        self, item_id: int, expires: date, new_drive_id: str | None, origin: str = "ui"
    ) -> Renewal:
        """Renew the item: with a new file, first move the old one into Expired as one
        journaled batch (a locked old file without a grant is refused by the planner),
        then ``record`` under that batch's id. A failed move records nothing
        (``InvalidRequest``). Without a move the renewal still gets a batch id, for its
        own Undo (``undo``)."""
        p = self.plan(item_id, new_drive_id, origin)
        if p.locked:
            raise InvalidRequest(LOCKED_MESSAGE)
        batch_id = uuid4().hex
        if p.plan is None:
            item = self.record(item_id, expires, new_drive_id, batch_id)
            return Renewal(item, batch_id, "renewal", p.skipped)
        result = self.executor.apply(p.plan, check=self._check(p), batch_id=batch_id)
        moved = (
            result.failed is None
            and result.error is None
            and any(op.kind is OpKind.MOVE for op in result.done)
        )
        if not moved:
            raise InvalidRequest(
                f"The old file could not be moved, so nothing was renewed: {result.error}"
            )
        item = self.record(item_id, expires, new_drive_id, batch_id)
        return Renewal(item, batch_id, "activity", None)

    def undo(self, batch_id: str) -> Item:
        """The Undo of a renewal that moved no file (``Renewal.undo == "renewal"``);
        returns its item. One that did is undone from Activity (``InvalidRequest``);
        ``Conflict`` once it was undone. The caller runs ``collections.changed``."""
        batch = func.json_extract(item_events.c.data, "$.batch_id")
        with self.engine.connect() as conn:
            journaled = conn.execute(
                select(operations.c.id).where(operations.c.batch_id == batch_id).limit(1)
            ).first()
            item_id = conn.execute(
                select(item_events.c.item_id)
                .where(item_events.c.kind == RENEWED, batch == batch_id)
                .order_by(item_events.c.id)
                .limit(1)
            ).scalar()
        if journaled is not None:
            raise InvalidRequest("That renewal moved a file: undo it from Activity")
        if item_id is None:
            raise NotFound(f"Renewal {batch_id}")
        if not self.undo_batch(batch_id):
            raise Conflict("That renewal was already undone")
        return self.trays.get(item_id)

    # --- the item -----------------------------------------------------------------------

    def _renewable(self, conn: Connection, item_id: int) -> Item:
        """The item, when it can be renewed: open, in a tray with ``renew``."""
        row = self.trays._row(conn, item_id)
        tray = self.trays._find_tray(row.tray_id)
        if tray is None or tray.renew is None:
            raise InvalidRequest("Only an item of a tray with Renewed can be renewed")
        if row.state != "open":
            raise InvalidRequest(f"Item {item_id} is done: reopen it to renew it")
        return self.trays._get(conn, item_id)

    @staticmethod
    def _check_new_file(conn: Connection, item_id: int, before: Item, new_drive_id: str) -> None:
        if not before.files:
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
            before = self._renewable(conn, item_id)
            old_drive_id = before.files[0] if before.files else None
            old_file = {"name": None, "path": None}
            if new_drive_id is not None:
                self._check_new_file(conn, item_id, before, new_drive_id)
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
