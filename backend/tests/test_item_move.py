"""One tray per item: "Put in tray" and the move action move an open item, a move can be
taken back, and an item can be removed from its tray."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from dam.api import create_api
from dam.db.tables import item_files, items, notes
from dam.extract.base import ExtractedText
from dam.index.scanner import scan

BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}
INBOX = "##. Organize"
BILL = "Northpower Oy lasku\nEräpäivä 15.11.2026\nYhteensä 84,20 €"


@pytest.fixture
def client(app):
    with TestClient(create_api(app), base_url=BASE) as c:
        yield c


@pytest.fixture
def scans(app, fake_archive):
    for drive_id, text in (("s1", BILL), ("s2", "a letter")):
        fake_archive.add(f"{INBOX}/{drive_id}.pdf", content=drive_id.encode(), drive_id=drive_id)
        scan(app.paths, app.repo)
        app.repo.save_content(drive_id, None, ExtractedText(text, "test"), "indexed")


def post(client, url, body=None):
    return client.post(url, json=body if body is not None else {}, headers=LOCAL_ORIGIN)


def test_put_in_another_tray_moves_the_item(client, app, scans):
    first = post(client, "/api/items/quick", {"tray": "to-pay", "drive_ids": ["s1"]}).json()
    item = first["created"][0]
    app.notes.set("item", str(item["id"]), "keep me")
    r = post(client, "/api/items/quick", {"tray": "follow-up", "drive_ids": ["s1"]}).json()
    assert r["created"] == [] and r["skipped"] == []
    (moved,) = r["moved"]
    assert moved["id"] == item["id"] and moved["tray_id"] == "follow-up"
    assert moved["title"] == item["title"] and moved["files"] == ["s1"]
    assert r["moved_from"] == {str(item["id"]): "to-pay"}
    # tray A no longer lists it, tray B does; note and history stay; one item row only
    assert app.trays.list("to-pay") == []
    assert [i.id for i in app.trays.list("follow-up")] == [item["id"]]
    assert app.notes.get("item", str(item["id"])) == "keep me"
    kinds = [e.kind for e in app.trays.history(item["id"])]
    assert kinds == ["created", "moved"]
    ev = app.trays.history(item["id"])[-1].data
    assert (ev["from_name"], ev["to_name"]) == ("To pay", "Follow up")
    with app.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(items)).scalar() == 1


def test_move_carries_same_named_fields_and_keeps_the_others(client, app, scans):
    item = post(client, "/api/items/quick", {"tray": "to-pay", "drive_ids": ["s1"]}).json()[
        "created"
    ][0]
    assert item["fields"]["due_date"] == "2026-11-15"
    moved = post(client, f"/api/items/{item['id']}/move", {"tray": "to-action"}).json()
    assert moved["tray_id"] == "to-action"
    assert moved["date"] is None and moved["missing_required"] == ["action_date"]
    # values the new tray has no field for stay in the data, so moving back restores them
    assert moved["fields"]["amount"] == "84.20"
    back = post(client, f"/api/items/{item['id']}/move", {"tray": "to-pay"}).json()
    assert back["fields"]["due_date"] == "2026-11-15" and back["date"] == "2026-11-15"


def test_move_refusals(client, app, scans):
    a = post(client, "/api/items/quick", {"tray": "to-pay", "drive_ids": ["s1"]}).json()["created"][
        0
    ]
    assert post(client, f"/api/items/{a['id']}/move", {"tray": "nope"}).status_code == 404
    # the item's file already has an open item in the target tray
    app.trays.create("to-read", ["s1"], {}, None)
    assert post(client, f"/api/items/{a['id']}/move", {"tray": "to-read"}).status_code == 409
    # a done item stays where it is
    app.trays.done(a["id"], {})
    assert post(client, f"/api/items/{a['id']}/move", {"tray": "to-action"}).status_code == 400


def test_put_in_a_tray_when_the_item_is_done_creates_a_new_open_item(client, app, scans):
    a = post(client, "/api/items/quick", {"tray": "to-pay", "drive_ids": ["s1"]}).json()["created"][
        0
    ]
    app.trays.done(a["id"], {})
    r = post(client, "/api/items/quick", {"tray": "to-read", "drive_ids": ["s1"]}).json()
    assert len(r["created"]) == 1 and r["moved"] == []
    assert app.trays.get(a["id"]).tray_id == "to-pay"  # the done item and its history stay
    assert len(app.trays.list("to-pay", "done")) == 1


def test_undo_move(client, app, scans):
    a = post(client, "/api/items/quick", {"tray": "to-pay", "drive_ids": ["s1"]}).json()["created"][
        0
    ]
    post(client, "/api/items/quick", {"tray": "to-read", "drive_ids": ["s1"]})
    r = post(client, f"/api/items/{a['id']}/undo-move")
    assert r.status_code == 200 and r.json()["tray_id"] == "to-pay"
    assert [i.id for i in app.trays.list("to-pay")] == [a["id"]]
    assert app.trays.list("to-read") == []
    last = app.trays.history(a["id"])[-1]
    assert last.kind == "moved" and last.data["undo"] is True
    # nothing left to take back; and an item edited after the move cannot be taken back
    assert post(client, f"/api/items/{a['id']}/undo-move").status_code == 409
    post(client, f"/api/items/{a['id']}/move", {"tray": "to-read"})
    app.trays.update(a["id"], None, "Renamed")
    assert post(client, f"/api/items/{a['id']}/undo-move").status_code == 409


def test_remove_deletes_the_item_and_leaves_the_files(client, app, scans):
    a = post(client, "/api/items/quick", {"tray": "to-pay", "drive_ids": ["s1"]}).json()["created"][
        0
    ]
    app.notes.set("item", str(a["id"]), "a note")
    assert post(client, f"/api/items/{a['id']}/remove").status_code == 204
    with app.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(items)).scalar() == 0
        assert conn.execute(select(func.count()).select_from(item_files)).scalar() == 0
        assert conn.execute(select(func.count()).select_from(notes)).scalar() == 0
    assert app.repo.get("s1").path == f"{INBOX}/s1.pdf"
    assert post(client, f"/api/items/{a['id']}/remove").status_code == 404
    # a done item can be removed too
    b = post(client, "/api/items/quick", {"tray": "to-pay", "drive_ids": ["s2"]}).json()["created"][
        0
    ]
    app.trays.done(b["id"], {})
    assert post(client, f"/api/items/{b['id']}/remove").status_code == 204
