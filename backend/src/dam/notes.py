"""Notes and checklists on files, collections and tray items. DB-only, nothing touches the archive.

``target_id`` is a string: a file's drive id, or ``str(id)`` for a collection or an item.
Notes and checklist rows point at their target without a foreign key.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, case, delete, func, insert, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from dam.db.engine import write_tx
from dam.db.tables import checklist_items, notes
from dam.services.errors import InvalidRequest, NotFound

KINDS = ("file", "collection", "item")
NOTE_MAX = 10_000
CHECK_MAX = 500
_SHIFT = 1_000_000


@dataclass
class ChecklistItem:
    id: int
    text: str
    done: bool
    position: int


def _kind(kind: str) -> str:
    if kind not in KINDS:
        raise InvalidRequest(f"kind must be one of {', '.join(KINDS)}")
    return kind


def _check_text(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise InvalidRequest("A checklist entry must not be blank")
    text = text.strip()
    if len(text) > CHECK_MAX:
        raise InvalidRequest(f"A checklist entry is at most {CHECK_MAX} characters")
    return text


def check_note(text: object) -> str:
    """Strip and validate a note's text (``""`` means no note)."""
    if not isinstance(text, str):
        raise InvalidRequest("A note is text")
    text = text.strip()
    if len(text) > NOTE_MAX:
        raise InvalidRequest(f"A note is at most {NOTE_MAX} characters")
    return text


def _item(row) -> ChecklistItem:
    return ChecklistItem(id=row.id, text=row.text, done=bool(row.done), position=row.position)


class NotesService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # --- notes -------------------------------------------------------------------

    def get(self, kind: str, target_id: str) -> str:
        _kind(kind)
        with self.engine.connect() as conn:
            text = conn.execute(
                select(notes.c.text).where(
                    notes.c.target_kind == kind, notes.c.target_id == target_id
                )
            ).scalar_one_or_none()
        return text or ""

    def item_facts(self, item_ids: list[int]) -> dict[int, tuple[bool, int, int]]:
        """For tray lists, two queries for all items: ``{id: (has_note, open, total)}``
        (open and total count the item's checklist entries)."""
        if not item_ids:
            return {}
        ids = [str(i) for i in item_ids]
        out = {i: (False, 0, 0) for i in item_ids}
        with self.engine.connect() as conn:
            noted = {
                r[0]
                for r in conn.execute(
                    select(notes.c.target_id, notes.c.text).where(
                        notes.c.target_kind == "item", notes.c.target_id.in_(ids)
                    )
                )
                if (r[1] or "").strip()
            }
            counts = {
                r[0]: (r[1], r[2])
                for r in conn.execute(
                    select(
                        checklist_items.c.target_id,
                        func.count(),
                        func.coalesce(func.sum(case((checklist_items.c.done, 0), else_=1)), 0),
                    )
                    .where(
                        checklist_items.c.target_kind == "item",
                        checklist_items.c.target_id.in_(ids),
                    )
                    .group_by(checklist_items.c.target_id)
                )
            }
        for i in item_ids:
            total, open_ = counts.get(str(i), (0, 0))
            out[i] = (str(i) in noted, int(open_), int(total))
        return out

    def set(self, kind: str, target_id: str, text: str, batch_id: str | None = None) -> None:
        """Store the note (surrounding whitespace stripped); blank text removes it."""
        _kind(kind)
        text = check_note(text)
        with write_tx(self.engine) as conn:
            if not text:
                conn.execute(
                    delete(notes).where(notes.c.target_kind == kind, notes.c.target_id == target_id)
                )
                return
            self._upsert(conn, kind, target_id, text, batch_id)

    @staticmethod
    def _upsert(
        conn: Connection, kind: str, target_id: str, text: str, batch_id: str | None
    ) -> None:
        stmt = sqlite_insert(notes).values(
            target_kind=kind,
            target_id=target_id,
            text=text,
            updated=time.time(),
            created_by_batch=batch_id,
        )
        # A note a batch did not create is never taken over by a batch (NULL
        # owner, or the owner stays); a user edit (batch_id None) clears the owner,
        # so undoing the original filing never deletes text the user wrote since.
        conn.execute(
            stmt.on_conflict_do_update(
                index_elements=["target_kind", "target_id"],
                set_={
                    "text": stmt.excluded.text,
                    "updated": stmt.excluded.updated,
                    "created_by_batch": case(
                        (stmt.excluded.created_by_batch.is_(None), None),
                        else_=notes.c.created_by_batch,
                    ),
                },
            )
        )

    def append(self, kind: str, target_id: str, text: str) -> str:
        """Add ``text`` below the existing note (a blank line between), in one write
        transaction so a concurrent edit is never lost; returns the whole note.

        Never overwrites: a result over ``NOTE_MAX`` is refused and the note stays as it
        was. Blank text changes nothing.
        """
        _kind(kind)
        text = check_note(text)
        with write_tx(self.engine) as conn:
            current = (
                conn.execute(
                    select(notes.c.text).where(
                        notes.c.target_kind == kind, notes.c.target_id == target_id
                    )
                ).scalar_one_or_none()
                or ""
            )
            if not text:
                return current
            combined = f"{current}\n\n{text}" if current.strip() else text
            if len(combined) > NOTE_MAX:
                raise InvalidRequest(
                    f"The note would be over {NOTE_MAX} characters; nothing was added"
                )
            self._upsert(conn, kind, target_id, combined, None)
        return combined

    def add_if_absent(
        self, kind: str, target_id: str, text: str, batch_id: str | None = None
    ) -> bool:
        """Store the note only if the target has none yet; return whether it was stored.

        Never overwrites (one atomic insert), so undoing the batch can only remove
        text the batch itself wrote. Blank text stores nothing.
        """
        _kind(kind)
        text = check_note(text)
        if not text:
            return False
        with write_tx(self.engine) as conn:
            result = conn.execute(
                sqlite_insert(notes)
                .values(
                    target_kind=kind,
                    target_id=target_id,
                    text=text,
                    updated=time.time(),
                    created_by_batch=batch_id,
                )
                .on_conflict_do_nothing(index_elements=["target_kind", "target_id"])
            )
            return result.rowcount == 1

    def remove_created_by(self, batch_id: str) -> int:
        """Delete (DB only) the notes a batch created; used when that batch is undone.

        Checklist rows carry no batch, so they are not touched here.
        """
        with write_tx(self.engine) as conn:
            return conn.execute(delete(notes).where(notes.c.created_by_batch == batch_id)).rowcount

    # --- checklists --------------------------------------------------------------

    @staticmethod
    def _siblings(conn: Connection, kind: str, target_id: str) -> list:
        return list(
            conn.execute(
                select(checklist_items)
                .where(
                    checklist_items.c.target_kind == kind,
                    checklist_items.c.target_id == target_id,
                )
                .order_by(checklist_items.c.position, checklist_items.c.id)
            )
        )

    @staticmethod
    def _row(conn: Connection, check_id: int):
        row = conn.execute(
            select(checklist_items).where(checklist_items.c.id == check_id)
        ).one_or_none()
        if row is None:
            raise NotFound(f"Checklist entry {check_id}")
        return row

    @staticmethod
    def _renumber(conn: Connection, ids: list[int]) -> None:
        """Give ``ids`` the positions 0..n-1 in that order. Positions are unique per
        target, so everything is first shifted out of the way, then set."""
        if not ids:
            return
        conn.execute(
            update(checklist_items)
            .where(checklist_items.c.id.in_(ids))
            .values(position=checklist_items.c.position + _SHIFT)
        )
        for position, check_id in enumerate(ids):
            conn.execute(
                update(checklist_items)
                .where(checklist_items.c.id == check_id)
                .values(position=position)
            )

    def checklist(self, kind: str, target_id: str) -> list[ChecklistItem]:
        _kind(kind)
        with self.engine.connect() as conn:
            return [_item(r) for r in self._siblings(conn, kind, target_id)]

    def add_check(self, kind: str, target_id: str, text: str) -> ChecklistItem:
        _kind(kind)
        text = _check_text(text)
        with write_tx(self.engine) as conn:
            position = len(self._siblings(conn, kind, target_id))
            check_id = conn.execute(
                insert(checklist_items).values(
                    target_kind=kind,
                    target_id=target_id,
                    text=text,
                    done=False,
                    position=position,
                )
            ).inserted_primary_key[0]
            return _item(self._row(conn, check_id))

    def set_check(self, check_id: int, done: bool | None = None, text: str | None = None) -> None:
        values: dict[str, object] = {}
        if done is not None:
            values["done"] = bool(done)
        if text is not None:
            values["text"] = _check_text(text)
        with write_tx(self.engine) as conn:
            self._row(conn, check_id)
            if values:
                conn.execute(
                    update(checklist_items).where(checklist_items.c.id == check_id).values(**values)
                )

    def remove_check(self, check_id: int) -> None:
        with write_tx(self.engine) as conn:
            row = self._row(conn, check_id)
            conn.execute(delete(checklist_items).where(checklist_items.c.id == check_id))
            rest = self._siblings(conn, row.target_kind, row.target_id)
            self._renumber(conn, [r.id for r in rest])

    def move_check(self, check_id: int, position: int) -> None:
        """Move an entry to ``position`` (clamped to the list); the others are renumbered."""
        with write_tx(self.engine) as conn:
            row = self._row(conn, check_id)
            ids = [
                r.id
                for r in self._siblings(conn, row.target_kind, row.target_id)
                if r.id != check_id
            ]
            ids.insert(max(0, min(position, len(ids))), check_id)
            self._renumber(conn, ids)
