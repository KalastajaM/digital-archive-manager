"""Merging items (and undoing it) and adding a file at a position: DB only."""

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select

from dam.api import create_api
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
from dam.errors import Conflict, InvalidRequest, NotFound
from dam.notes import NOTE_MAX, NotesService
from dam.trays.model import load_trays
from dam.trays.service import TrayService

DEFAULTS = Path(__file__).resolve().parents[2] / "defaults" / "trays"
BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}


@pytest.fixture
def svc(engine):
    trays, errors = load_trays(DEFAULTS)
    assert errors == []
    return TrayService(engine, lambda: trays)


@pytest.fixture
def notes_svc(engine):
    return NotesService(engine)


def add_file(engine, drive_id: str, name: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(files).values(
                drive_id=drive_id,
                path=f"10. Financial/{name}",
                path_nfc=f"10. Financial/{name}",
                name=name,
                ext="pdf",
                is_dir=False,
                missing=False,
            )
        )


def count(engine, table, *where) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table).where(*where)).scalar_one()


def kinds(svc, item_id) -> list[str]:
    return [e.kind for e in svc.history(item_id)]


def test_add_file_at_a_position_puts_it_back(engine, svc):
    item = svc.create("to-read", ["d1", "d2", "d3"], {}, "x")
    svc.remove_file(item.id, "d2")
    assert svc.add_file(item.id, "d2", 1).files == ["d1", "d2", "d3"]
    svc.remove_file(item.id, "d1")
    assert svc.add_file(item.id, "d1", 0).files == ["d1", "d2", "d3"]
    svc.remove_file(item.id, "d3")
    assert svc.add_file(item.id, "d3", 99).files == ["d1", "d2", "d3"]  # clamped
    assert svc.add_file(item.id, "d4").files == ["d1", "d2", "d3", "d4"]  # default: the end
    assert svc.add_file(item.id, "d1", 3).files == ["d1", "d2", "d3", "d4"]  # already there


def test_merge_adds_files_note_and_checklist_and_removes_the_source(engine, svc, notes_svc):
    add_file(engine, "d2", "second.pdf")
    target = svc.create("to-read", ["d1", "d2"], {}, "Target")
    source = svc.create("to-read", ["d2", "d3", "d4"], {}, "Source")
    notes_svc.set("item", str(target.id), "target note")
    notes_svc.set("item", str(source.id), "source note")
    notes_svc.add_check("item", str(target.id), "t1")
    notes_svc.add_check("item", str(source.id), "s1")
    notes_svc.add_check("item", str(source.id), "s2")
    check = notes_svc.checklist("item", str(source.id))[0]
    notes_svc.set_check(check.id, done=True)

    merged = svc.merge(target.id, source.id)

    assert merged.id == target.id and merged.title == "Target" and merged.tray_id == "to-read"
    assert merged.files == ["d1", "d2", "d3", "d4"]  # in order, d2 once
    assert notes_svc.get("item", str(target.id)) == "target note\n\n--- Source ---\nsource note"
    assert [(c.text, c.done, c.position) for c in notes_svc.checklist("item", str(target.id))] == [
        ("t1", False, 0),
        ("s1", True, 1),
        ("s2", False, 2),
    ]
    with pytest.raises(NotFound):
        svc.get(source.id)
    assert count(engine, items, items.c.id == source.id) == 0
    assert count(engine, item_files, item_files.c.item_id == source.id) == 0
    assert count(engine, notes, notes.c.target_id == str(source.id)) == 0
    assert count(engine, checklist_items, checklist_items.c.target_id == str(source.id)) == 0
    # the files themselves are untouched
    assert count(engine, files, files.c.drive_id == "d2") == 1


def test_merge_records_a_history_event_without_the_snapshot(engine, svc, notes_svc):
    target = svc.create("to-read", ["d1"], {}, "Target")
    source = svc.create("to-read", ["d1", "d2"], {}, "Source")
    notes_svc.set("item", str(source.id), "n")
    notes_svc.add_check("item", str(source.id), "s1")
    svc.merge(target.id, source.id)
    event = svc.history(target.id)[-1]
    assert event.kind == "merged_in"
    assert event.data["title"] == "Source" and event.data["item_id"] == source.id
    assert [f["drive_id"] for f in event.data["files"]] == ["d2"]
    assert event.data["note"] is True and event.data["checks"] == 1
    assert "snapshot" not in event.data


def test_merge_into_a_target_without_a_note_starts_the_note_with_the_separator(
    engine, svc, notes_svc
):
    target = svc.create("to-read", ["d1"], {}, "Target")
    source = svc.create("to-read", ["d2"], {}, "Source")
    notes_svc.set("item", str(source.id), "hello")
    svc.merge(target.id, source.id)
    assert notes_svc.get("item", str(target.id)) == "--- Source ---\nhello"


def test_merge_keeps_the_targets_own_fields_tray_and_date(engine, svc):
    target = svc.create("to-pay", ["d1"], {"amount": "10.00", "due_date": "2026-11-01"}, "Target")
    source = svc.create("to-read", ["d2"], {}, "Source")
    merged = svc.merge(target.id, source.id)
    assert (merged.tray_id, merged.fields, merged.date) == (
        target.tray_id,
        target.fields,
        target.date,
    )


def test_merge_refuses_itself_unknown_ids_done_items_and_a_note_too_long(engine, svc, notes_svc):
    a = svc.create("to-read", ["d1"], {}, "A")
    b = svc.create("to-read", ["d2"], {}, "B")
    with pytest.raises(InvalidRequest):
        svc.merge(a.id, a.id)
    with pytest.raises(NotFound):
        svc.merge(a.id, 999)
    with pytest.raises(NotFound):
        svc.merge(999, a.id)
    svc.done(b.id, {})
    with pytest.raises(InvalidRequest):
        svc.merge(a.id, b.id)
    with pytest.raises(InvalidRequest):
        svc.merge(b.id, a.id)
    c = svc.create("to-read", ["d3"], {}, "C")
    d = svc.create("to-read", ["d4"], {}, "D")
    notes_svc.set("item", str(c.id), "x" * (NOTE_MAX - 5))
    notes_svc.set("item", str(d.id), "y" * 100)
    with pytest.raises(InvalidRequest):
        svc.merge(c.id, d.id)
    # nothing happened to either
    assert svc.get(d.id).files == ["d4"] and svc.get(c.id).files == ["d3"]
    assert notes_svc.get("item", str(d.id)) == "y" * 100
    assert kinds(svc, c.id) == ["created"]


def test_undo_merge_restores_both_items_as_they_were(engine, svc, notes_svc):
    target = svc.create("to-read", ["d1"], {}, "Target")
    source = svc.create("to-pay", ["d1", "d2"], {"amount": "5.00"}, "Source")
    svc.add_file(source.id, "d3", 0)
    notes_svc.set("item", str(target.id), "keep")
    notes_svc.set("item", str(source.id), "src")
    notes_svc.add_check("item", str(target.id), "t1")
    notes_svc.add_check("item", str(source.id), "s1")
    notes_svc.add_check("item", str(source.id), "s2")
    with engine.begin() as conn:
        conn.execute(
            insert(reminders_sent).values(
                item_id=source.id,
                rule="due",
                occasion=date(2026, 11, 1),
                fired_at=1.0,
                channels=["app"],
            )
        )
    before_source = svc.get(source.id)
    before_events = [(e.kind, e.at, e.data) for e in svc.history(source.id)]
    before_target_events = kinds(svc, target.id)

    svc.merge(target.id, source.id)
    undone = svc.undo_merge(target.id)

    assert undone.id == target.id and undone.files == ["d1"]
    assert notes_svc.get("item", str(target.id)) == "keep"
    assert [c.text for c in notes_svc.checklist("item", str(target.id))] == ["t1"]
    assert kinds(svc, target.id) == before_target_events
    back = svc.get(source.id)
    assert back == before_source  # same id, files in order, fields, tray, dates
    assert notes_svc.get("item", str(source.id)) == "src"
    assert [(c.text, c.position) for c in notes_svc.checklist("item", str(source.id))] == [
        ("s1", 0),
        ("s2", 1),
    ]
    assert [(e.kind, e.at, e.data) for e in svc.history(source.id)] == before_events
    assert count(engine, reminders_sent, reminders_sent.c.item_id == source.id) == 1
    assert count(engine, item_events, item_events.c.kind == "merged_in") == 0


def test_undo_merge_removes_a_note_the_target_did_not_have(engine, svc, notes_svc):
    target = svc.create("to-read", ["d1"], {}, "Target")
    source = svc.create("to-read", ["d2"], {}, "Source")
    notes_svc.set("item", str(source.id), "src")
    svc.merge(target.id, source.id)
    svc.undo_merge(target.id)
    assert notes_svc.get("item", str(target.id)) == ""


def test_undo_merge_conflicts_once_the_target_changed(engine, svc, notes_svc):
    target = svc.create("to-read", ["d1"], {}, "Target")
    source = svc.create("to-read", ["d2"], {}, "Source")
    notes_svc.set("item", str(source.id), "src")
    svc.merge(target.id, source.id)
    notes_svc.set("item", str(target.id), "edited since")
    with pytest.raises(Conflict):
        svc.undo_merge(target.id)
    # a new event also blocks it
    notes_svc.set("item", str(target.id), "--- Source ---\nsrc")
    svc.add_file(target.id, "d9")
    with pytest.raises(Conflict):
        svc.undo_merge(target.id)
    assert svc.get(target.id).files == ["d1", "d2", "d9"]


def test_undo_merge_without_a_merge_conflicts(svc):
    a = svc.create("to-read", ["d1"], {}, "A")
    with pytest.raises(Conflict):
        svc.undo_merge(a.id)
    with pytest.raises(NotFound):
        svc.undo_merge(999)


def test_undo_merge_conflicts_when_the_source_id_was_taken(engine, svc):
    target = svc.create("to-read", ["d1"], {}, "Target")
    source = svc.create("to-read", ["d2"], {}, "Source")
    svc.merge(target.id, source.id)
    with write_tx(engine) as conn:
        conn.execute(
            insert(items).values(
                id=source.id, tray_id="to-read", title="x", fields={}, state="open", created=1.0
            )
        )
    with pytest.raises(Conflict):
        svc.undo_merge(target.id)


# --- through the API ---------------------------------------------------------------------


@pytest.fixture
def client(app):
    with TestClient(create_api(app), base_url=BASE) as c:
        yield c


def post(client, url, body=None):
    return client.post(url, json=body if body is not None else {}, headers=LOCAL_ORIGIN)


def test_merge_api(client, app):
    a = app.trays.create("to-read", ["d1"], {}, "A")
    b = app.trays.create("to-read", ["d2"], {}, "B")
    r = post(client, f"/api/items/{a.id}/merge", {"item_id": b.id})
    assert r.status_code == 200, r.text
    assert r.json()["files"] == ["d1", "d2"]
    assert client.get(f"/api/items/{b.id}").status_code == 404
    history = client.get(f"/api/items/{a.id}/history").json()
    assert history[-1]["kind"] == "merged_in" and "snapshot" not in history[-1]["data"]
    r = post(client, f"/api/items/{a.id}/undo-merge")
    assert r.status_code == 200, r.text
    assert r.json()["files"] == ["d1"]
    assert client.get(f"/api/items/{b.id}").json()["files"] == ["d2"]
    assert post(client, f"/api/items/{a.id}/undo-merge").status_code == 409


def test_merge_api_errors(client, app):
    a = app.trays.create("to-read", ["d1"], {}, "A")
    assert post(client, f"/api/items/{a.id}/merge", {"item_id": a.id}).status_code == 400
    assert post(client, f"/api/items/{a.id}/merge", {"item_id": 999}).status_code == 404
    assert post(client, "/api/items/999/merge", {"item_id": a.id}).status_code == 404
