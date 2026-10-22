"""Items in trays: create, edit, mark done, reopen, list. DB-only, nothing touches the archive.

Field values are parsed by ``FIELD_TYPES``: ``Item`` holds Python values (``date``,
``Decimal``...), the DB holds their JSON form (ISO dates, ``"84.20"``).
"""

# Annotations stay strings: the ``list`` method would otherwise shadow ``list[...]``
# in the annotations after it on Python 3.13.
from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import (
    Connection,
    Engine,
    and_,
    delete,
    func,
    insert,
    literal_column,
    select,
    update,
)

from dam.core.naming import fix_mojibake
from dam.db.engine import write_tx
from dam.db.tables import (
    checklist_items,
    files,
    item_events,
    item_files,
    items,
    notes,
    reminders_sent,
)
from dam.services.errors import Conflict, InvalidRequest, NotFound
from dam.trays.model import FIELD_TYPES, FieldDef, TrayDef

log = logging.getLogger(__name__)

REMOVED_TRAY_NAME = "(removed tray)"
CHANGED_SINCE_CREATED = "item was changed — mark it done instead"
CHANGED_SINCE_MOVED = "item was changed since it moved"
STATES = ("open", "done")
_DATE_PREFIX = re.compile(r"^[0-9]{8}_", re.ASCII)


@dataclass
class Item:
    id: int
    tray_id: str
    title: str
    fields: dict
    date: date | None
    state: str
    created: float
    done_at: float | None
    done_fields: dict | None
    files: list[str]
    created_by_batch: str | None
    # required fields with no usable value (unset, or stored value now invalid)
    missing_required: list[str] = field(default_factory=list)
    # stored values the field's current type cannot parse (the tray file changed);
    # they are kept as stored, shown raw, and replaced when the user sets a new value
    invalid_fields: list[str] = field(default_factory=list)
    tray_name: str = ""
    # the item's tray is no longer in the config: shown under "(removed tray)"
    tray_removed: bool = False


@dataclass
class ItemEvent:
    """One line of an item's history: ``kind`` is created | edited | done | reopened |
    file_added | file_removed | moved; ``data`` holds what changed (stored JSON forms)."""

    id: int
    at: float
    kind: str
    data: dict


@dataclass
class QuickResult:
    """``create_quick``: the items created, the existing open items moved into the tray
    from another one (a file lives in one tray), and the files skipped because they
    already have an open item in that tray."""

    created: list[Item]
    skipped: list[str]
    moved: list[Item] = field(default_factory=list)
    # the tray each moved item came from (tray id), by item id, for the undo toast
    moved_from: dict[int, str] = field(default_factory=dict)


def _is_blank(raw: object) -> bool:
    return raw is None or (isinstance(raw, str) and not raw.strip())


def _parse_input(defs: dict[str, FieldDef], raw: dict) -> dict[str, object]:
    """Parse user input; a blank value (``None``/``""``) parses to ``None`` (= unset)."""
    if not isinstance(raw, dict):
        raise InvalidRequest("fields must be a mapping")
    parsed: dict[str, object] = {}
    for name, value in raw.items():
        fdef = defs.get(name)
        if fdef is None:
            raise InvalidRequest(f"unknown field {name!r}")
        if _is_blank(value):
            parsed[name] = None
            continue
        try:
            parsed[name] = FIELD_TYPES[fdef.type].parse(value)
        except ValueError as e:
            raise InvalidRequest(f"{name}: {e}") from e
    return parsed


def _dump(
    defs: dict[str, FieldDef],
    values: dict[str, object],
    invalid: Collection[str] = (),
) -> dict[str, object]:
    """Values → JSON. Undefined fields and ``invalid`` (raw, unparsed) ones go as they are."""
    return {
        name: FIELD_TYPES[defs[name].type].dump(value)
        if name in defs and name not in invalid
        else value
        for name, value in values.items()
    }


def _load(defs: dict[str, FieldDef], stored: dict | None) -> tuple[dict, set[str]]:
    """JSON → ``(values, invalid)``. A field no longer defined keeps its raw value; one
    its current type cannot parse keeps its raw value too and is listed in ``invalid``."""
    values: dict[str, object] = {}
    invalid: set[str] = set()
    for name, raw in (stored or {}).items():
        fdef = defs.get(name)
        if fdef is None:
            values[name] = raw
            continue
        try:
            values[name] = FIELD_TYPES[fdef.type].parse(raw)
        except ValueError:
            values[name] = raw
            invalid.add(name)
    return values, invalid


def _date_of(tray: TrayDef, values: dict, invalid: set[str]) -> date | None:
    """The item's sort/reminder date under the tray's *current* config."""
    name = tray.date_field
    if name is None or name in invalid:
        return None
    return values.get(name)


def _check_drive_id(drive_id: object) -> str:
    if not isinstance(drive_id, str) or not drive_id:
        raise InvalidRequest("A file is given by its drive id")
    return drive_id


def _display_name(conn: Connection, drive_id: str) -> str:
    """``20261020_Acme_bill.pdf`` → ``Acme bill``; the drive id if the file is unknown."""
    row = conn.execute(
        select(files.c.name, files.c.ext).where(files.c.drive_id == drive_id)
    ).one_or_none()
    if row is None or not row.name:
        return drive_id
    name = fix_mojibake(row.name)
    if row.ext and name.lower().endswith("." + row.ext.lower()):
        name = name[: -len(row.ext) - 1]
    name = " ".join(_DATE_PREFIX.sub("", name).replace("_", " ").split())
    return name or drive_id


def _render_title(tray: TrayDef, name: str, when: date | None) -> str:
    values: dict[str, object] = {"name": name}
    if when is not None:
        values["date"] = when
    try:
        title = tray.item_title.format_map(values).strip()
    except (KeyError, ValueError, TypeError, IndexError, AttributeError):
        return name  # e.g. {date} with no date yet
    return title or name


def _clean_title(title: str) -> str:
    if not isinstance(title, str) or not title.strip():
        raise InvalidRequest("A title must not be blank")
    return title.strip()


class TrayService:
    def __init__(
        self,
        engine: Engine,
        trays: Callable[[], list[TrayDef]],
        on_date_changed: Callable[[int], None] | None = None,
        prefill_for: Callable[[str], dict[str, str]] | None = None,
    ) -> None:
        self.engine = engine
        self._trays = trays
        # Called with the item id, after the commit, for each item whose date changed
        # (an edit or ``refresh_dates``); the App wires reminders.engine.clear_unsent.
        self._on_date_changed = on_date_changed
        # A file's scan prefill (``FieldDef.prefill`` keys) for ``create_quick``; the App
        # wires InboxService.prefill_for. None: no prefill.
        self.prefill_for = prefill_for

    def _date_changed(self, item_ids: Collection[int]) -> None:
        """Run the hook for each item; a failing hook is logged, never raised (the
        change itself has committed)."""
        if self._on_date_changed is None:
            return
        for item_id in item_ids:
            try:
                self._on_date_changed(item_id)
            except Exception:
                log.warning("date-change hook failed for item %s", item_id, exc_info=True)

    # --- lookups -----------------------------------------------------------------

    def defs(self) -> list[TrayDef]:
        """The trays currently configured."""
        return list(self._trays())

    def _find_tray(self, tray_id: str) -> TrayDef | None:
        return next((t for t in self._trays() if t.id == tray_id), None)

    def _tray(self, tray_id: str) -> TrayDef:
        tray = self._find_tray(tray_id)
        if tray is None:
            raise NotFound(f"Tray {tray_id}")
        return tray

    def _row(self, conn: Connection, item_id: int):
        row = conn.execute(select(items).where(items.c.id == item_id)).one_or_none()
        if row is None:
            raise NotFound(f"Item {item_id}")
        return row

    def _items(self, conn: Connection, rows) -> list[Item]:
        rows = list(rows)
        ids = [r.id for r in rows]
        by_item: dict[int, list[str]] = {i: [] for i in ids}
        if ids:
            for item_id, drive_id in conn.execute(
                select(item_files.c.item_id, item_files.c.drive_id)
                .where(item_files.c.item_id.in_(ids))
                .order_by(literal_column("item_files.rowid"))
            ):
                by_item[item_id].append(drive_id)
        trays = {t.id: t for t in self._trays()}
        return [self._item(r, trays.get(r.tray_id), by_item[r.id]) for r in rows]

    @staticmethod
    def _item(row, tray: TrayDef | None, drive_ids: list[str]) -> Item:
        defs = tray.fields if tray else {}
        values, invalid = _load(defs, row.fields)
        missing = [
            n for n, f in defs.items() if f.required and (values.get(n) is None or n in invalid)
        ]
        return Item(
            id=row.id,
            tray_id=row.tray_id,
            title=row.title,
            fields=values,
            date=row.date if tray is None else _date_of(tray, values, invalid),
            state=row.state,
            created=row.created,
            done_at=row.done_at,
            done_fields=(
                None
                if row.done_fields is None
                else _load(tray.done.fields if tray else {}, row.done_fields)[0]
            ),
            files=drive_ids,
            created_by_batch=row.created_by_batch,
            missing_required=missing,
            invalid_fields=sorted(invalid),
            tray_name=tray.name if tray else REMOVED_TRAY_NAME,
            tray_removed=tray is None,
        )

    def _get(self, conn: Connection, item_id: int) -> Item:
        return self._items(conn, [self._row(conn, item_id)])[0]

    @staticmethod
    def _event(conn: Connection, item_id: int, kind: str, data: dict) -> None:
        conn.execute(
            insert(item_events).values(item_id=item_id, at=time.time(), kind=kind, data=data)
        )

    # --- queries -----------------------------------------------------------------

    def get(self, item_id: int) -> Item:
        with self.engine.connect() as conn:
            return self._get(conn, item_id)

    def history(self, item_id: int) -> list[ItemEvent]:
        """The item's events, oldest first."""
        with self.engine.connect() as conn:
            self._row(conn, item_id)
            rows = conn.execute(
                select(item_events)
                .where(item_events.c.item_id == item_id)
                .order_by(item_events.c.at, item_events.c.id)
            )
            return [ItemEvent(r.id, r.at, r.kind, dict(r.data or {})) for r in rows]

    def list(self, tray_id: str | None = None, state: str = "open") -> list[Item]:
        """Open: by date (undated last), then created. Done: most recently done first.

        ``tray_id=None`` lists every tray, including items of trays removed from the
        config. An unknown ``tray_id`` is ``NotFound`` unless items still carry it.
        """
        if state not in STATES:
            raise InvalidRequest(f"state must be one of {', '.join(STATES)}")
        query = select(items).where(items.c.state == state)
        if state == "open":
            query = query.order_by(
                items.c.date.is_(None), items.c.date, items.c.created, items.c.id
            )
        else:
            query = query.order_by(items.c.done_at.desc(), items.c.id.desc())
        with self.engine.connect() as conn:
            if tray_id is not None:
                if (
                    self._find_tray(tray_id) is None
                    and not conn.execute(
                        select(items.c.id).where(items.c.tray_id == tray_id).limit(1)
                    ).first()
                ):
                    raise NotFound(f"Tray {tray_id}")
                query = query.where(items.c.tray_id == tray_id)
            return self._items(conn, conn.execute(query))

    def for_file(self, drive_id: str) -> list[Item]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(items)
                .join(item_files, item_files.c.item_id == items.c.id)
                .where(item_files.c.drive_id == drive_id)
                .order_by(items.c.created, items.c.id)
            )
            return self._items(conn, rows)

    def open_for_files(self, drive_ids: Collection[str]) -> list[Item]:
        """The open items that hold any of ``drive_ids`` (one query plus their files),
        oldest first."""
        ids = list(dict.fromkeys(drive_ids))
        if not ids:
            return []
        holding = select(item_files.c.item_id).where(item_files.c.drive_id.in_(ids))
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(items)
                .where(items.c.state == "open", items.c.id.in_(holding))
                .order_by(items.c.created, items.c.id)
            )
            return self._items(conn, rows)

    def open_trays(self, drive_ids: Collection[str]) -> dict[str, list[str]]:
        """For each of ``drive_ids`` that has open items: the tray ids of those items
        (one query; files with none are left out)."""
        ids = list(dict.fromkeys(drive_ids))
        if not ids:
            return {}
        with self.engine.connect() as conn:
            return self._open_trays(conn, ids)

    @staticmethod
    def _open_trays(conn: Connection, drive_ids: list[str]) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        rows = conn.execute(
            select(item_files.c.drive_id, items.c.tray_id)
            .join(items, items.c.id == item_files.c.item_id)
            .where(items.c.state == "open", item_files.c.drive_id.in_(drive_ids))
            .order_by(items.c.created, items.c.id)
        )
        for drive_id, tray_id in rows:
            trays = out.setdefault(drive_id, [])
            if tray_id not in trays:
                trays.append(tray_id)
        return out

    def filing_fields(self, tray_id: str, fields: dict, prefill: dict[str, str]) -> dict:
        """Check ``fields`` for a new item in ``tray_id`` and fill in the ones not given
        from ``prefill`` (scan values, keyed by ``FieldDef.prefill``).

        Raises ``InvalidRequest`` for an unknown tray, an unknown field or a value that
        does not parse. A given field always wins, a blank one included (the user
        cleared it); a prefill value that does not parse is left out. Required fields
        may stay missing (the item is flagged). Returns raw values for ``create``.
        """
        tray = self._find_tray(tray_id)
        if tray is None:
            raise InvalidRequest(f"unknown tray {tray_id!r}")
        _parse_input(tray.fields, fields)
        out = dict(fields)
        for name, fdef in tray.fields.items():
            raw = prefill.get(fdef.prefill) if fdef.prefill else None
            if name in out or raw is None:
                continue
            try:
                FIELD_TYPES[fdef.type].parse(raw)
            except ValueError:
                continue
            out[name] = raw
        return out

    # --- changes -----------------------------------------------------------------

    def create(
        self,
        tray_id: str,
        drive_ids: list[str],
        fields: dict,
        title: str | None,
        batch_id: str | None = None,
    ) -> Item:
        tray = self._tray(tray_id)
        drive_ids = self._drive_ids(drive_ids)
        values = self._values(tray, fields)
        with write_tx(self.engine) as conn:
            return self._get(conn, self._insert(conn, tray, drive_ids, values, title, batch_id))

    @staticmethod
    def _drive_ids(drive_ids: object) -> list[str]:
        if isinstance(drive_ids, str | bytes) or not isinstance(drive_ids, list | tuple):
            raise InvalidRequest("drive_ids must be a list of drive ids")
        out = list(dict.fromkeys(_check_drive_id(d) for d in drive_ids))
        if not out:
            raise InvalidRequest("An item needs at least one file")
        return out

    @staticmethod
    def _values(tray: TrayDef, fields: dict) -> dict[str, object]:
        return {k: v for k, v in _parse_input(tray.fields, fields).items() if v is not None}

    def _insert(
        self,
        conn: Connection,
        tray: TrayDef,
        drive_ids: list[str],
        values: dict[str, object],
        title: str | None,
        batch_id: str | None,
    ) -> int:
        when = _date_of(tray, values, set())
        stored = _dump(tray.fields, values)
        if title is None:
            title = _render_title(tray, _display_name(conn, drive_ids[0]), when)
        title = _clean_title(title)
        item_id = conn.execute(
            insert(items).values(
                tray_id=tray.id,
                title=title,
                fields=stored,
                date=when,
                state="open",
                created=time.time(),
                created_by_batch=batch_id,
            )
        ).inserted_primary_key[0]
        conn.execute(insert(item_files), [{"item_id": item_id, "drive_id": d} for d in drive_ids])
        self._event(
            conn, item_id, "created", {"title": title, "fields": stored, "files": drive_ids}
        )
        return item_id

    def create_quick(
        self, tray_id: str, drive_ids: list[str], fields: dict | None = None
    ) -> QuickResult:
        """One item per file in ``tray_id``, each with the file's scan prefill ("Put in
        <tray>"; DB only, the file stays where it is). A file that already has an open
        item in that tray is skipped, never given a second one. A file that has an open
        item in another tray gets that item moved here instead (see ``move``); a file
        whose items are all done gets a new open item. A folder is refused.

        ``fields`` (one file only: an AI suggestion, exactly as shown) are that item's
        values instead of the prefill; the same checks apply."""
        tray = self._tray(tray_id)
        drive_ids = self._drive_ids(drive_ids)
        if fields is not None and len(drive_ids) != 1:
            raise InvalidRequest("fields are for one file at a time")
        with self.engine.connect() as conn:
            folders = conn.execute(
                select(files.c.drive_id).where(files.c.drive_id.in_(drive_ids), files.c.is_dir)
            ).first()
        if folders is not None:
            raise InvalidRequest("Folders cannot be put in a tray")
        values = {}
        for drive_id in drive_ids:
            if fields is not None:
                values[drive_id] = self._values(tray, self.filing_fields(tray.id, fields, {}))
                continue
            prefill = self.prefill_for(drive_id) if self.prefill_for else {}
            values[drive_id] = self._values(tray, self.filing_fields(tray.id, {}, prefill))
        skipped: list[str] = []
        moved_from: dict[int, str] = {}
        with write_tx(self.engine) as conn:
            already = self._open_trays(conn, drive_ids)
            new_ids: list[int] = []
            for drive_id in drive_ids:
                if tray.id in already.get(drive_id, []):
                    skipped.append(drive_id)
                    continue
                elsewhere = self._open_item_of(conn, drive_id)
                if elsewhere is not None:
                    if elsewhere.id not in moved_from:
                        self._move(conn, elsewhere, tray, None, {})
                        moved_from[elsewhere.id] = elsewhere.tray_id
                    continue
                new_ids.append(self._insert(conn, tray, [drive_id], values[drive_id], None, None))
            created = [self._get(conn, i) for i in new_ids]
            moved = [self._get(conn, i) for i in moved_from]
        self._date_changed(list(moved_from))
        return QuickResult(created, skipped, moved, moved_from)

    @staticmethod
    def _open_item_of(conn: Connection, drive_id: str):
        """The oldest open item the file belongs to (any tray), or None."""
        return conn.execute(
            select(items)
            .join(item_files, item_files.c.item_id == items.c.id)
            .where(items.c.state == "open", item_files.c.drive_id == drive_id)
            .order_by(items.c.created, items.c.id)
            .limit(1)
        ).first()

    def move(self, item_id: int, tray_id: str) -> Item:
        """Move an open item to another tray: the same item (title, note, checklist,
        history and files stay), with a "moved" line in its history.

        Field values are kept by name: the ones the target tray also has carry over (a
        value its type cannot parse is flagged invalid, as after any tray edit); the
        others stay in the item's data, hidden, so moving back restores them. The date
        is recomputed from the target tray's date field. Refused for a done item, and
        when one of the item's files already has an open item in the target tray.
        ``on_date_changed`` runs after the commit (the target tray has its own reminders).
        """
        tray = self._tray(tray_id)
        with write_tx(self.engine) as conn:
            row = self._row(conn, item_id)
            if row.state != "open":
                raise InvalidRequest("Only an open item can move to another tray")
            if row.tray_id == tray.id:
                return self._get(conn, item_id)
            clash = conn.execute(
                select(items.c.id)
                .join(item_files, item_files.c.item_id == items.c.id)
                .where(
                    items.c.state == "open",
                    items.c.tray_id == tray.id,
                    item_files.c.drive_id.in_(
                        select(item_files.c.drive_id).where(item_files.c.item_id == item_id)
                    ),
                )
                .limit(1)
            ).first()
            if clash is not None:
                raise Conflict(f"A file of this item is already in {tray.name}")
            self._move(conn, row, tray, None, {})
            item = self._get(conn, item_id)
        self._date_changed([item_id])
        return item

    def _move(self, conn: Connection, row, tray: TrayDef, batch_id: str | None, extra: dict):
        """Re-home ``row`` (an open item) in ``tray``; ``extra``: field values (parsed)
        that override the carried-over ones."""
        values, invalid = _load(tray.fields, row.fields)
        for name, value in extra.items():
            values[name] = value
            invalid.discard(name)
        stored = _dump(tray.fields, values, invalid)
        conn.execute(
            update(items)
            .where(items.c.id == row.id)
            .values(tray_id=tray.id, fields=stored, date=_date_of(tray, values, invalid))
        )
        src = self._find_tray(row.tray_id)
        data = {
            "from": row.tray_id,
            "from_name": src.name if src else REMOVED_TRAY_NAME,
            "to": tray.id,
            "to_name": tray.name,
        }
        if batch_id is not None:
            data["batch_id"] = batch_id
        self._event(conn, row.id, "moved", data)

    def move_in_filing(
        self, drive_id: str, tray_id: str, fields: dict, batch_id: str | None
    ) -> Item | None:
        """Filing a file into a tray: move the file's open item from another tray here,
        with the values typed in the filing form on top (``fields`` as ``filing_fields``
        returns them). None if the file has no open item in another tray."""
        tray = self._tray(tray_id)
        extra = self._values(tray, fields)
        with write_tx(self.engine) as conn:
            row = self._open_item_of(conn, drive_id)
            if row is None or row.tray_id == tray.id:
                return None
            self._move(conn, row, tray, batch_id, extra)
            item = self._get(conn, row.id)
        self._date_changed([item.id])
        return item

    def undo_move(self, item_id: int) -> Item:
        """Put a just-moved item back in the tray it came from (the toast's Undo). Only
        while its latest history line is that move; otherwise ``Conflict``."""
        with write_tx(self.engine) as conn:
            row = self._row(conn, item_id)
            last = conn.execute(
                select(item_events)
                .where(item_events.c.item_id == item_id)
                .order_by(item_events.c.at.desc(), item_events.c.id.desc())
                .limit(1)
            ).first()
            if (
                row.state != "open"
                or last is None
                or last.kind != "moved"
                or last.data.get("to") != row.tray_id
                or last.data.get("undo")
            ):
                raise Conflict(CHANGED_SINCE_MOVED)
            self._move_back(conn, row, last.data)
            item = self._get(conn, item_id)
        self._date_changed([item_id])
        return item

    def _move_back(self, conn: Connection, row, moved: dict) -> None:
        tray = self._find_tray(moved["from"])
        if tray is None:
            raise Conflict("The tray it came from no longer exists")
        values, invalid = _load(tray.fields, row.fields)
        conn.execute(
            update(items)
            .where(items.c.id == row.id)
            .values(tray_id=tray.id, date=_date_of(tray, values, invalid))
        )
        data = {
            "from": moved["to"],
            "from_name": moved["to_name"],
            "to": tray.id,
            "to_name": tray.name,
            "undo": True,
        }
        self._event(conn, row.id, "moved", data)

    def update(self, item_id: int, fields: dict | None, title: str | None) -> Item:
        """Edit the title and/or some fields (a blank value clears that field).

        A stored value the field's current type cannot parse is kept as it is until the
        user sets a new value for that field. ``on_date_changed`` runs *after* the commit,
        only when the item's date changed.
        """
        with write_tx(self.engine) as conn:
            row = self._row(conn, item_id)
            tray = self._find_tray(row.tray_id)
            changes: dict[str, list] = {}
            patch: dict[str, object] = {}
            if fields and tray is None:
                raise InvalidRequest("The item's tray was removed: fields cannot be edited")
            if tray is not None:
                current, invalid = _load(tray.fields, row.fields)
                values, still_invalid = dict(current), set(invalid)
                for name, value in _parse_input(tray.fields, fields or {}).items():
                    still_invalid.discard(name)
                    if value is None:
                        values.pop(name, None)
                    else:
                        values[name] = value
                old = _dump(tray.fields, current, invalid)
                new = _dump(tray.fields, values, still_invalid)
                for name in sorted(old.keys() | new.keys()):
                    if old.get(name) != new.get(name):
                        changes[name] = [old.get(name), new.get(name)]
                if changes:
                    patch["fields"] = new
                patch["date"] = _date_of(tray, values, still_invalid)
            new_title = row.title if title is None else _clean_title(title)
            if new_title != row.title:
                changes["title"] = [row.title, new_title]
                patch["title"] = new_title
            date_changed = "date" in patch and patch["date"] != row.date
            if changes or date_changed:
                conn.execute(update(items).where(items.c.id == item_id).values(**patch))
            if changes:
                self._event(conn, item_id, "edited", {"changes": changes})
            item = self._get(conn, item_id)
        if date_changed:
            self._date_changed([item_id])
        return item

    def _current_date(self, row) -> date | None:
        tray = self._find_tray(row.tray_id)
        if tray is None:
            return row.date
        values, invalid = _load(tray.fields, row.fields)
        return _date_of(tray, values, invalid)

    def refresh_dates(self) -> int:
        """Recompute the date of every open item from the current tray config (after the
        tray files were reloaded); return how many changed. ``on_date_changed`` runs for
        each of them after the commit."""
        changed: list[int] = []
        with write_tx(self.engine) as conn:
            for row in conn.execute(select(items).where(items.c.state == "open")).all():
                when = self._current_date(row)
                if when != row.date:
                    conn.execute(update(items).where(items.c.id == row.id).values(date=when))
                    changed.append(row.id)
        self._date_changed(changed)
        return len(changed)

    def done(self, item_id: int, done_fields: dict) -> Item:
        """Mark done; done fields not given take their default (``paid_on: today``)."""
        with write_tx(self.engine) as conn:
            row = self._row(conn, item_id)
            if row.state == "done":
                raise InvalidRequest(f"Item {item_id} is already done")
            tray = self._find_tray(row.tray_id)
            defs = tray.done.fields if tray else {}
            values = {
                k: v for k, v in _parse_input(defs, done_fields or {}).items() if v is not None
            }
            for name, fdef in defs.items():
                if name not in values and fdef.default == "today":
                    values[name] = date.today()
            missing = [n for n, f in defs.items() if f.required and n not in values]
            if missing:
                raise InvalidRequest(f"Missing {', '.join(missing)}")
            stored = _dump(defs, values)
            result = conn.execute(
                update(items)
                .where(items.c.id == item_id, items.c.state == "open")
                .values(
                    state="done",
                    done_at=time.time(),
                    done_fields=stored,
                    date=self._current_date(row),
                )
            )
            if result.rowcount != 1:
                raise InvalidRequest(f"Item {item_id} is already done")
            self._event(conn, item_id, "done", {"done_fields": stored})
            return self._get(conn, item_id)

    def reopen(self, item_id: int) -> Item:
        """Undo "done": the item is open again; the old done fields stay in its history."""
        with write_tx(self.engine) as conn:
            row = self._row(conn, item_id)
            if row.state != "done":
                raise InvalidRequest(f"Item {item_id} is not done")
            result = conn.execute(
                update(items)
                .where(items.c.id == item_id, items.c.state == "done")
                .values(state="open", done_at=None, done_fields=None, date=self._current_date(row))
            )
            if result.rowcount != 1:
                raise InvalidRequest(f"Item {item_id} is not done")
            self._event(conn, item_id, "reopened", {"done_fields": row.done_fields})
            return self._get(conn, item_id)

    @staticmethod
    def _file_data(conn: Connection, drive_id: str) -> dict:
        """A file event's data: the drive id plus the name and path at that moment, so the
        history can still name a file after it left the item (None if not indexed)."""
        row = conn.execute(
            select(files.c.name, files.c.path).where(files.c.drive_id == drive_id)
        ).first()
        return {
            "drive_id": drive_id,
            "name": row.name if row else None,
            "path": row.path if row else None,
        }

    def add_file(self, item_id: int, drive_id: str) -> Item:
        drive_id = _check_drive_id(drive_id)
        with write_tx(self.engine) as conn:
            self._row(conn, item_id)
            exists = conn.execute(
                select(item_files.c.item_id).where(
                    item_files.c.item_id == item_id, item_files.c.drive_id == drive_id
                )
            ).first()
            if not exists:
                conn.execute(insert(item_files).values(item_id=item_id, drive_id=drive_id))
                self._event(conn, item_id, "file_added", self._file_data(conn, drive_id))
            return self._get(conn, item_id)

    def remove_file(self, item_id: int, drive_id: str) -> Item:
        with write_tx(self.engine) as conn:
            item = self._get(conn, item_id)
            if drive_id not in item.files:
                raise NotFound(f"File {drive_id} in item {item_id}")
            if len(item.files) == 1:
                raise InvalidRequest("An item keeps at least one file")
            conn.execute(
                delete(item_files).where(
                    item_files.c.item_id == item_id, item_files.c.drive_id == drive_id
                )
            )
            self._event(conn, item_id, "file_removed", self._file_data(conn, drive_id))
            return self._get(conn, item_id)

    def remove_created_by(self, batch_id: str) -> int:
        """Delete (DB only) the items a batch created, with everything hanging off them,
        and move the items a filing in the batch moved into a tray back where they were.

        Used when that batch is undone. Notes and checklist rows point at items without a
        foreign key, so they are deleted here explicitly.
        """
        with write_tx(self.engine) as conn:
            ids = list(
                conn.execute(
                    select(items.c.id).where(items.c.created_by_batch == batch_id)
                ).scalars()
            )
            self._delete_items(conn, ids)
            # items a filing in this batch moved into a tray go back where they were
            batch = func.json_extract(item_events.c.data, "$.batch_id")
            moves = conn.execute(
                select(item_events)
                .where(item_events.c.kind == "moved", batch == batch_id)
                .order_by(item_events.c.id.desc())
            ).all()
            back: list[int] = []
            for ev in moves:
                row = conn.execute(select(items).where(items.c.id == ev.item_id)).first()
                if row is None or row.state != "open" or row.tray_id != ev.data["to"]:
                    continue
                if self._find_tray(ev.data["from"]) is None:
                    continue
                self._move_back(conn, row, ev.data)
                back.append(row.id)
        self._date_changed(back)
        return len(ids) + len(back)

    def remove(self, item_id: int) -> None:
        """Remove an item from its tray, open or done (DB only: the files are not touched).
        The item, its history, note, checklist and reminder records are deleted."""
        with write_tx(self.engine) as conn:
            self._row(conn, item_id)
            self._delete_items(conn, [item_id])

    def discard(self, item_id: int) -> None:
        """Take back a just-created item (the toast's "take it back"): delete it (DB
        only) with its file links, history and reminder rows. Only while it is open, its
        history holds nothing but "created" and it has no note or checklist entry (text
        the user typed is never deleted here); otherwise ``Conflict``."""
        with write_tx(self.engine) as conn:
            row = self._row(conn, item_id)
            kinds = list(
                conn.execute(
                    select(item_events.c.kind).where(item_events.c.item_id == item_id)
                ).scalars()
            )
            typed = any(
                conn.execute(
                    select(table.c.id)
                    .where(table.c.target_kind == "item", table.c.target_id == str(item_id))
                    .limit(1)
                ).first()
                for table in (notes, checklist_items)
            )
            if row.state != "open" or kinds != ["created"] or typed:
                raise Conflict(CHANGED_SINCE_CREATED)
            self._delete_items(conn, [item_id])

    @staticmethod
    def _delete_items(conn: Connection, ids: list[int]) -> None:
        """Delete items and everything hanging off them. Notes and checklist rows point
        at items without a foreign key, so they are deleted here explicitly."""
        if not ids:
            return
        targets = [str(i) for i in ids]
        for table in (notes, checklist_items):
            conn.execute(
                delete(table).where(
                    and_(table.c.target_kind == "item", table.c.target_id.in_(targets))
                )
            )
        for table in (item_files, item_events, reminders_sent):
            conn.execute(delete(table).where(table.c.item_id.in_(ids)))
        conn.execute(delete(items).where(items.c.id.in_(ids)))
