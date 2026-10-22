from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, insert, select, update

from dam.db.tables import (
    checklist_items,
    files,
    item_events,
    item_files,
    items,
    notes,
    reminders_sent,
)
from dam.services.errors import InvalidRequest, NotFound
from dam.trays.model import TrayDef, load_trays
from dam.trays.service import REMOVED_TRAY_NAME, TrayService

DEFAULTS = Path(__file__).resolve().parents[2] / "defaults" / "trays"


@pytest.fixture
def config():
    trays, errors = load_trays(DEFAULTS)
    assert errors == []
    return {"trays": trays}


@pytest.fixture
def svc(engine, config):
    return TrayService(engine, lambda: config["trays"])


def add_file(engine, drive_id: str, name: str, missing: bool = False) -> None:
    ext = name.rsplit(".", 1)[1].lower() if "." in name else None
    with engine.begin() as conn:
        conn.execute(
            insert(files).values(
                drive_id=drive_id,
                path=f"10. Financial/{name}",
                path_nfc=f"10. Financial/{name}",
                name=name,
                ext=ext,
                is_dir=False,
                missing=missing,
            )
        )


def count(engine, table, *where) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table).where(*where)).scalar_one()


def test_create_with_prefilled_fields(engine, svc):
    add_file(engine, "d1", "20261020_Northpower_electricity_bill.pdf")
    item = svc.create(
        "to-pay",
        ["d1"],
        {
            "due_date": "2026-11-03",
            "amount": "84,20",
            "iban": "FI21 1234 5600 0007 85",
            "reference": "RF18 5390 0754 7034",
        },
        title=None,
    )
    assert item.title == "Northpower electricity bill"
    assert item.tray_id == "to-pay" and item.state == "open"
    assert item.fields == {
        "due_date": date(2026, 11, 3),
        "amount": Decimal("84.20"),
        "iban": "FI2112345600000785",
        "reference": "RF18539007547034",
    }
    assert item.date == date(2026, 11, 3)
    assert item.files == ["d1"]
    assert item.missing_required == []
    with engine.connect() as conn:
        row = conn.execute(select(items.c.fields, items.c.date)).one()
        kinds = list(conn.execute(select(item_events.c.kind)).scalars())
    assert row.fields == {
        "due_date": "2026-11-03",
        "amount": "84.20",
        "iban": "FI2112345600000785",
        "reference": "RF18539007547034",
    }
    assert row.date == date(2026, 11, 3)
    assert kinds == ["created"]
    assert svc.get(item.id) == item


def test_missing_required_is_allowed_but_listed(engine, svc):
    item = svc.create("to-pay", ["d1"], {"amount": "84.20"}, title=None)
    assert item.missing_required == ["due_date"]
    assert item.date is None
    assert item.fields["amount"] == Decimal("84.20")
    assert item.title == "d1"  # no file row: falls back to the drive id


@pytest.mark.parametrize("raw", ["84,20", "84.20"])
def test_money_parsed_both_ways(svc, raw):
    assert svc.create("to-pay", ["d"], {"amount": raw}, None).fields["amount"] == Decimal("84.20")


def test_create_rejects_unknown_field_bad_value_and_tray(svc):
    with pytest.raises(InvalidRequest, match="vendor"):
        svc.create("to-pay", ["d"], {"vendor": "x"}, None)
    with pytest.raises(InvalidRequest, match="amount"):
        svc.create("to-pay", ["d"], {"amount": "lots"}, None)
    with pytest.raises(InvalidRequest):
        svc.create("to-pay", [], {}, None)
    with pytest.raises(InvalidRequest):
        svc.create("to-pay", ["d"], {}, "   ")
    with pytest.raises(NotFound):
        svc.create("to-nowhere", ["d"], {}, None)


def test_explicit_title_and_date_template(engine, config):
    config["trays"] = [
        TrayDef.model_validate(
            {
                "id": "t",
                "name": "T",
                "order": 1,
                "item_title": "{name} {date:%d.%m}",
                "fields": {"due": {"type": "date"}},
                "date_field": "due",
            }
        )
    ]
    svc = TrayService(engine, lambda: config["trays"])
    add_file(engine, "d1", "20261020_Water_bill.pdf")
    assert svc.create("t", ["d1"], {"due": "2026-11-03"}, None).title == "Water bill 03.11"
    assert svc.create("t", ["d1"], {}, None).title == "Water bill"  # no date: plain name
    assert svc.create("t", ["d1"], {}, " Mine ").title == "Mine"


def test_name_without_date_prefix_or_extension(engine, svc):
    add_file(engine, "d1", "Lease_contract.v2.PDF")
    assert svc.create("to-read", ["d1"], {}, None).title == "Lease contract.v2"


def test_done_sets_paid_on_today_and_reopen_undoes(engine, svc):
    item = svc.create("to-pay", ["d1"], {"due_date": "2026-11-03"}, None)
    done = svc.done(item.id, {})
    assert done.state == "done"
    assert done.done_fields == {"paid_on": date.today()}
    assert done.done_at is not None
    with pytest.raises(InvalidRequest):
        svc.done(item.id, {})
    again = svc.reopen(item.id)
    assert again.state == "open"
    assert again.done_at is None and again.done_fields is None
    with pytest.raises(InvalidRequest):
        svc.reopen(item.id)
    explicit = svc.done(item.id, {"paid_on": "2026-10-30"})
    assert explicit.done_fields == {"paid_on": date(2026, 10, 30)}
    svc.reopen(item.id)
    with pytest.raises(InvalidRequest, match="tip"):
        svc.done(item.id, {"tip": "1"})
    assert event_kinds(engine, item.id) == ["created", "done", "reopened", "done", "reopened"]


def event_kinds(engine, item_id):
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(item_events.c.kind)
                .where(item_events.c.item_id == item_id)
                .order_by(item_events.c.id)
            ).scalars()
        )


def test_update_records_edit_and_recomputes_date(engine, config):
    changed_dates = []
    svc = TrayService(engine, lambda: config["trays"], on_date_changed=changed_dates.append)
    item = svc.create("to-pay", ["d1"], {"due_date": "2026-11-03", "amount": "5"}, None)
    updated = svc.update(item.id, {"due_date": "2026-11-10", "amount": None}, "Renamed")
    assert updated.date == date(2026, 11, 10)
    assert "amount" not in updated.fields
    assert updated.title == "Renamed"
    assert changed_dates == [item.id]
    svc.update(item.id, None, "Renamed again")
    assert changed_dates == [item.id]  # title-only edit: date unchanged
    assert event_kinds(engine, item.id) == ["created", "edited", "edited"]
    svc.update(item.id, {"amount": None}, None)  # no change: no event
    assert event_kinds(engine, item.id) == ["created", "edited", "edited"]
    with pytest.raises(InvalidRequest):
        svc.update(item.id, {"vendor": "x"}, None)
    with pytest.raises(NotFound):
        svc.update(999, None, "x")
    cleared = svc.update(item.id, {"due_date": ""}, None)
    assert cleared.date is None and "due_date" not in cleared.fields
    assert cleared.missing_required == ["due_date"]
    assert changed_dates == [item.id, item.id]
    with engine.connect() as conn:
        assert conn.execute(select(items.c.date)).scalar_one() is None


def test_list_ordering(svc):
    late = svc.create("to-pay", ["a"], {"due_date": "2026-12-01"}, "late")
    undated = svc.create("to-pay", ["b"], {}, "undated")
    early = svc.create("to-pay", ["c"], {"due_date": "2026-11-01"}, "early")
    undated2 = svc.create("to-pay", ["d"], {}, "undated2")
    action = svc.create("to-action", ["e"], {"action_date": "2026-11-15"}, "action")
    assert [i.title for i in svc.list("to-pay")] == ["early", "late", "undated", "undated2"]
    assert [i.title for i in svc.list()] == ["early", "action", "late", "undated", "undated2"]
    svc.done(late.id, {})
    svc.done(early.id, {})
    assert [i.title for i in svc.list("to-pay", state="done")] == ["early", "late"]
    assert [i.title for i in svc.list("to-pay")] == ["undated", "undated2"]
    assert {undated.id, undated2.id, action.id} == {i.id for i in svc.list()}
    with pytest.raises(NotFound):
        svc.list("to-nowhere")
    with pytest.raises(InvalidRequest):
        svc.list(state="sideways")


def test_item_of_removed_tray_stays_listable(engine, svc, config):
    item = svc.create("to-read", ["d1"], {}, "Old")
    config["trays"] = [t for t in config["trays"] if t.id != "to-read"]
    listed = svc.list()
    assert [i.id for i in listed] == [item.id]
    assert listed[0].tray_removed and listed[0].tray_name == REMOVED_TRAY_NAME
    assert [i.id for i in svc.list("to-read")] == [item.id]
    assert svc.update(item.id, None, "Older").title == "Older"
    with pytest.raises(InvalidRequest, match="removed"):
        svc.update(item.id, {"x": "1"}, None)
    assert svc.done(item.id, {}).state == "done"
    with pytest.raises(NotFound):
        svc.create("to-read", ["d1"], {}, None)


def test_file_whose_row_is_missing_keeps_item_and_files(engine, svc):
    add_file(engine, "d1", "20261020_Bill.pdf")
    item = svc.create("to-pay", ["d1"], {}, None)
    with engine.begin() as conn:
        conn.execute(update(files).where(files.c.drive_id == "d1").values(missing=True))
    listed = svc.list("to-pay")
    assert [i.id for i in listed] == [item.id]
    assert listed[0].files == ["d1"]
    assert [i.id for i in svc.for_file("d1")] == [item.id]


def test_files_add_remove_and_for_file(engine, svc):
    item = svc.create("to-pay", ["d1", "d1"], {}, "x")
    assert item.files == ["d1"]
    assert svc.add_file(item.id, "d2").files == ["d1", "d2"]
    assert svc.add_file(item.id, "d2").files == ["d1", "d2"]  # idempotent
    other = svc.create("to-read", ["d2"], {}, "y")
    assert [i.id for i in svc.for_file("d2")] == [item.id, other.id]
    assert svc.remove_file(item.id, "d1").files == ["d2"]
    with pytest.raises(NotFound):
        svc.remove_file(item.id, "d1")
    with pytest.raises(InvalidRequest):
        svc.remove_file(item.id, "d2")  # an item keeps at least one file
    with pytest.raises(NotFound):
        svc.add_file(999, "d1")
    assert svc.for_file("nobody") == []


def test_remove_created_by(engine, svc):
    a = svc.create("to-pay", ["d1"], {}, "a", batch_id="b1")
    b = svc.create("to-read", ["d1", "d2"], {}, "b", batch_id="b1")
    keep = svc.create("to-read", ["d1"], {}, "keep", batch_id="b2")
    assert a.created_by_batch == "b1"
    with engine.begin() as conn:
        for item_id in (a.id, keep.id):
            conn.execute(
                insert(notes).values(
                    target_kind="item", target_id=str(item_id), text="n", updated=1.0
                )
            )
            conn.execute(
                insert(checklist_items).values(
                    target_kind="item", target_id=str(item_id), text="c", position=0
                )
            )
        conn.execute(
            insert(reminders_sent).values(
                item_id=a.id,
                rule="days_before:0",
                occasion=date(2026, 11, 3),
                fired_at=1.0,
                channels=[],
            )
        )
        conn.execute(
            insert(reminders_sent).values(
                item_id=keep.id,
                rule="days_before:0",
                occasion=date(2026, 11, 3),
                fired_at=1.0,
                channels=[],
            )
        )
        # a file note with the same id string must survive
        conn.execute(
            insert(notes).values(target_kind="file", target_id=str(a.id), text="f", updated=1.0)
        )
    assert svc.remove_created_by("b1") == 2
    assert [i.id for i in svc.list()] == [keep.id]
    assert count(engine, item_files, item_files.c.item_id.in_([a.id, b.id])) == 0
    assert count(engine, item_events, item_events.c.item_id.in_([a.id, b.id])) == 0
    assert count(engine, notes) == 2
    assert count(engine, notes, notes.c.target_kind == "file") == 1
    assert count(engine, checklist_items) == 1
    assert count(engine, reminders_sent) == 1
    assert svc.remove_created_by("b1") == 0
    with pytest.raises(NotFound):
        svc.get(a.id)


def text_to_date_tray(config) -> None:
    config["trays"] = [
        TrayDef.model_validate(
            {
                "id": "t",
                "name": "T",
                "order": 1,
                "fields": {"when": {"type": "text", "required": True}, "note": {"type": "text"}},
            }
        )
    ]


def test_field_type_change_keeps_raw_value_and_can_be_repaired(engine, config):
    text_to_date_tray(config)
    svc = TrayService(engine, lambda: config["trays"])
    item = svc.create("t", ["d1"], {"when": "next tuesday"}, "x")
    data = config["trays"][0].model_dump()
    data["fields"]["when"]["type"] = "date"
    data["date_field"] = "when"
    config["trays"] = [TrayDef.model_validate(data)]

    stale = svc.get(item.id)
    assert stale.fields["when"] == "next tuesday"
    assert stale.invalid_fields == ["when"]
    assert stale.missing_required == ["when"]
    assert stale.date is None

    edited = svc.update(item.id, {"note": "call them"}, None)  # unrelated edit works
    assert edited.fields == {"when": "next tuesday", "note": "call them"}
    assert edited.date is None and edited.missing_required == ["when"]
    with engine.connect() as conn:
        assert conn.execute(select(items.c.fields)).scalar_one()["when"] == "next tuesday"

    repaired = svc.update(item.id, {"when": "2026-11-03"}, None)
    assert repaired.fields["when"] == date(2026, 11, 3)
    assert repaired.invalid_fields == [] and repaired.missing_required == []
    assert repaired.date == date(2026, 11, 3)


def test_date_recomputed_from_current_config(engine, config, svc):
    item = svc.create("to-pay", ["d1"], {"due_date": "2026-11-03"}, "x")
    other = svc.create("to-pay", ["d2"], {"due_date": "2026-11-04"}, "y")
    done = svc.create("to-pay", ["d3"], {"due_date": "2026-11-05"}, "z")
    svc.done(done.id, {})
    data = next(t for t in config["trays"] if t.id == "to-pay").model_dump()
    data["fields"]["due_date"]["type"] = "text"
    data["fields"]["due_date"]["prefill"] = None
    data["date_field"] = None
    data["reminders"] = []
    config["trays"] = [TrayDef.model_validate(data)] + [
        t for t in config["trays"] if t.id != "to-pay"
    ]
    assert svc.done(item.id, {}).date is None
    with engine.connect() as conn:
        assert conn.execute(select(items.c.date).where(items.c.id == item.id)).scalar_one() is None
    assert svc.refresh_dates() == 1  # only the other open item changed
    with engine.connect() as conn:
        dates = dict(conn.execute(select(items.c.id, items.c.date)).all())
    assert dates[other.id] is None
    assert dates[done.id] == date(2026, 11, 5)  # done items are left alone
    assert svc.refresh_dates() == 0


def test_done_and_reopen_are_conditional(engine, svc):
    item = svc.create("to-read", ["d1"], {}, "x")
    with engine.begin() as conn:
        conn.execute(update(items).values(state="done"))
    with pytest.raises(InvalidRequest):
        svc.done(item.id, {})
    with engine.begin() as conn:
        conn.execute(update(items).values(state="open"))
    with pytest.raises(InvalidRequest):
        svc.reopen(item.id)


def test_drive_id_validation(svc):
    with pytest.raises(InvalidRequest):
        svc.create("to-read", "d1", {}, "x")
    item = svc.create("to-read", ["d1"], {}, "x")
    for bad in ("", None, 5):
        with pytest.raises(InvalidRequest):
            svc.add_file(item.id, bad)


def test_file_events_record_name_and_path(engine, svc):
    add_file(engine, "d1", "bill.pdf")
    add_file(engine, "d2", "receipt.png")
    item = svc.create("to-pay", ["d1"], {}, "x")
    svc.add_file(item.id, "d2")
    svc.remove_file(item.id, "d1")
    svc.add_file(item.id, "d9")  # not in the index: no name or path known
    events = [(e.kind, e.data) for e in svc.history(item.id) if e.kind.startswith("file_")]
    assert events == [
        (
            "file_added",
            {"drive_id": "d2", "name": "receipt.png", "path": "10. Financial/receipt.png"},
        ),
        ("file_removed", {"drive_id": "d1", "name": "bill.pdf", "path": "10. Financial/bill.pdf"}),
        ("file_added", {"drive_id": "d9", "name": None, "path": None}),
    ]
