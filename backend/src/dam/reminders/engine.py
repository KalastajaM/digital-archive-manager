"""Which reminders are due, and the record that each one fired once.

An item's rules give *occasions* (local dates): ``before:N`` is the item's date minus N
days, ``lead:N`` the same with N the item's own lead time (``lead_days_of``), ``overdue``
the day after the date, ``nudge`` the item's creation day plus the
tray's ``nudge_after_days``. An occasion is due from ``hour`` o'clock on its day (and
any time after that day). ``reminders_sent`` holds one row per (item, rule, occasion)
that fired, so a due occasion is reported until it is marked sent, and never again.

All times are local: ``now`` is an aware local datetime (``datetime.now().astimezone()``,
which carries today's fixed UTC offset); ``now.date()``/``now.hour`` are compared as
they are. A creation instant is turned into a day with the system's rules for *that*
instant, so a DST change between creation and now shifts nothing.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Engine, and_, delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from dam.db.engine import write_tx
from dam.db.tables import items, reminders_sent
from dam.trays.model import FIELD_TYPES, ReminderRule, TrayDef, lead_days_of
from dam.trays.service import _load

OVERDUE = "overdue"
NUDGE = "nudge"
_BEFORE = "before:"
_LEAD = "lead:"


@dataclass(frozen=True)
class Due:
    item_id: int
    tray_id: str
    title: str
    rule: str  # "before:3", "before:0", "lead:180", "overdue", "nudge"
    occasion: date
    date: date | None  # the item's date (None for undated items, e.g. a nudge)
    amount: Decimal | None
    tray_name: str = ""


def rule_id(rule: ReminderRule, lead_days: int | None = None) -> str | None:
    """The rule's record id; None for a lead rule when the item has no lead time."""
    if rule.overdue:
        return OVERDUE
    if rule.lead:
        return None if lead_days is None else f"{_LEAD}{lead_days}"
    return f"{_BEFORE}{rule.days_before}"


def _lead_days(tray: TrayDef, stored: dict | None) -> int | None:
    values, _ = _load(tray.fields, stored)
    return lead_days_of(tray, values)


def _occasion(rule: str, when: date | None) -> date | None:
    """The occasion of a date rule for an item dated ``when`` (None: no occasion)."""
    if when is None:
        return None
    if rule == OVERDUE:
        return when + timedelta(days=1)
    for prefix in (_BEFORE, _LEAD):
        if rule.startswith(prefix) and rule[len(prefix) :].isdigit():
            return when - timedelta(days=int(rule[len(prefix) :]))
    return None


def is_due(occasion: date, now: datetime, *, hour: int) -> bool:
    today = now.date()
    return today > occasion or (today == occasion and now.hour >= hour)


def _local_date(timestamp: float) -> date:
    """The local calendar day of an instant, under the system's rules *for that
    instant* (not today's UTC offset: ``now`` from ``astimezone()`` has a fixed one)."""
    return datetime.fromtimestamp(timestamp).date()


def _amount(tray: TrayDef, stored: dict | None) -> Decimal | None:
    """The item's amount: the tray's summary field, else its first money field."""
    name = tray.summary.sum if tray.summary else None
    if name is None:
        name = next((n for n, f in tray.fields.items() if f.type == "money"), None)
    raw = (stored or {}).get(name) if name else None
    if raw is None:
        return None
    try:
        return FIELD_TYPES["money"].parse(raw)
    except ValueError:
        return None


def _occasions(tray: TrayDef, row) -> list[tuple[str, date]]:
    """The item's current (rule, occasion) pairs under its tray's rules."""
    out: list[tuple[str, date]] = []
    lead = _lead_days(tray, row.fields)
    for rule in tray.reminders:
        rid = rule_id(rule, lead)
        occasion = _occasion(rid, row.date) if rid is not None else None
        if occasion is not None:
            out.append((rid, occasion))
    if tray.nudge_after_days is not None:
        out.append((NUDGE, _local_date(row.created) + timedelta(days=tray.nudge_after_days)))
    return out


def due_reminders(
    engine: Engine, trays: Sequence[TrayDef], now: datetime, *, hour: int
) -> list[Due]:
    """Every due occasion of every open item that has not been marked sent yet.

    Items of trays no longer in the config have no rules and are never due. A nudge
    fires at most once per item: any recorded nudge blocks it, whatever its occasion.
    """
    by_id = {t.id: t for t in trays}
    with engine.connect() as conn:
        rows = conn.execute(select(items).where(items.c.state == "open").order_by(items.c.id))
        rows = [r for r in rows if r.tray_id in by_id]
        sent = {
            (r.item_id, r.rule, r.occasion)
            for r in conn.execute(
                select(reminders_sent.c.item_id, reminders_sent.c.rule, reminders_sent.c.occasion)
            )
        }
    nudged = {item_id for item_id, rule, _ in sent if rule == NUDGE}
    dues: list[Due] = []
    for row in rows:
        tray = by_id[row.tray_id]
        amount = _amount(tray, row.fields)
        for rid, occasion in _occasions(tray, row):
            if rid == NUDGE and row.id in nudged:
                continue
            if (row.id, rid, occasion) in sent or not is_due(occasion, now, hour=hour):
                continue
            dues.append(
                Due(row.id, row.tray_id, row.title, rid, occasion, row.date, amount, tray.name)
            )
    return dues


def _priority(rule: str) -> tuple[int, int]:
    """Tie-break on the same occasion: overdue > before:0 > before:N, lead:N > nudge."""
    if rule == OVERDUE:
        return (3, 0)
    for prefix in (_BEFORE, _LEAD):
        if rule.startswith(prefix):
            days = rule[len(prefix) :]
            return (2, -int(days) if days.isdigit() else 0)
    return (0, 0)


def latest_occasions(engine: Engine, trays: Sequence[TrayDef]) -> dict[int, date]:
    """Per open item, the latest recorded *date-rule* occasion that is still one of its
    current occasions (current date and rules). Nudge rows never count: a nudge is
    silenced on its own (at most once per item) and never silences date reminders.

    Rows of an older date are ignored here (they stay in the table, so returning to
    that date never re-fires them): moving a due date earlier, e.g. to fix a misread,
    keeps the new date's reminders.
    """
    by_id = {t.id: t for t in trays}
    with engine.connect() as conn:
        rows = [
            r
            for r in conn.execute(select(items).where(items.c.state == "open"))
            if r.tray_id in by_id
        ]
        recorded = set(
            conn.execute(
                select(reminders_sent.c.item_id, reminders_sent.c.rule, reminders_sent.c.occasion)
            ).all()
        )
    floor: dict[int, date] = {}
    for row in rows:
        valid = [
            o
            for rid, o in _occasions(by_id[row.tray_id], row)
            if rid != NUDGE and (row.id, rid, o) in recorded
        ]
        if valid:
            floor[row.id] = max(valid)
    return floor


def collapse(
    dues: Iterable[Due], floor: Mapping[int, date] | None = None
) -> tuple[list[Due], list[Due]]:
    """Per item keep only the latest due occasion: ``(send, silence)``.

    An item that is found late (an overdue bill filed today) would otherwise fire every
    missed rule at once; the earlier ones are moot and get recorded silently. A due
    whose occasion is earlier than the item's latest recorded *current* occasion
    (``floor``, from ``latest_occasions``; e.g. a rule added to the tray later) is
    silenced too.
    """
    floor = floor or {}
    dues = list(dues)

    def below_floor(d: Due) -> bool:  # nudges are not held to the date-rule floor
        return d.rule != NUDGE and d.item_id in floor and d.occasion < floor[d.item_id]

    late = [d for d in dues if below_floor(d)]
    dues = [d for d in dues if not below_floor(d)]
    latest: dict[int, Due] = {}
    for d in dues:
        best = latest.get(d.item_id)
        if best is None or (d.occasion, _priority(d.rule)) > (best.occasion, _priority(best.rule)):
            latest[d.item_id] = d
    send = [d for d in dues if latest[d.item_id] is d]
    silence = late + [d for d in dues if latest[d.item_id] is not d]
    return send, silence


def mark_sent(engine: Engine, dues: Iterable[Due], channels: list[str], now: datetime) -> None:
    """Record ``dues`` as fired through ``channels`` (``[]``: recorded silently) at ``now``.

    A row that already exists (another run got there first) is left as it is.
    """
    rows = [
        {
            "item_id": d.item_id,
            "rule": d.rule,
            "occasion": d.occasion,
            "fired_at": now.timestamp(),
            "channels": list(channels),
        }
        for d in dues
    ]
    if not rows:
        return
    with write_tx(engine) as conn:
        live = set(
            conn.execute(
                select(items.c.id).where(items.c.id.in_({r["item_id"] for r in rows}))
            ).scalars()
        )
        rows = [r for r in rows if r["item_id"] in live]  # an item deleted meanwhile
        if rows:
            conn.execute(sqlite_insert(reminders_sent).on_conflict_do_nothing(), rows)


def clear_unsent(engine: Engine, item_id: int, trays: Sequence[TrayDef] = ()) -> int:
    """After the item's date (or lead time) changed: forget *silenced* records of
    occasions the item no longer has. Returns how many rows were removed.

    A delivered reminder's row is never deleted, so moving a date away and back (a
    typo, a briefly broken tray file) never sends it again. Silenced rows (``channels
    == []``) of date rules go when their occasion no longer matches the current date;
    a ``lead:N`` row also goes when the item's lead time is no longer N (``trays`` tells
    it, without them lead rows are judged by the date alone); nudge rows depend on the
    creation day only and stay.
    """
    by_id = {t.id: t for t in trays}
    with write_tx(engine) as conn:
        row = conn.execute(
            select(items.c.date, items.c.tray_id, items.c.fields).where(items.c.id == item_id)
        ).first()
        when = row.date if row else None
        tray = by_id.get(row.tray_id) if row else None
        lead = _lead_days(tray, row.fields) if tray is not None and tray.lead else None

        def stale_rule(rule: str, occasion: date) -> bool:
            if rule.startswith(_LEAD) and tray is not None and rule != f"{_LEAD}{lead}":
                return True
            return _occasion(rule, when) != occasion

        stale = [
            (r.rule, r.occasion)
            for r in conn.execute(
                select(
                    reminders_sent.c.rule, reminders_sent.c.occasion, reminders_sent.c.channels
                ).where(reminders_sent.c.item_id == item_id)
            )
            if not r.channels and r.rule != NUDGE and stale_rule(r.rule, r.occasion)
        ]
        for rule, occasion in stale:
            conn.execute(
                delete(reminders_sent).where(
                    and_(
                        reminders_sent.c.item_id == item_id,
                        reminders_sent.c.rule == rule,
                        reminders_sent.c.occasion == occasion,
                    )
                )
            )
        return len(stale)
