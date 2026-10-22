"""Quick "Put in tray" and taking it back (discard), through the HTTP API."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from dam.api import create_api
from dam.db.tables import checklist_items, item_events, item_files, items, notes, reminders_sent
from dam.extract.base import ExtractedText
from dam.index.scanner import scan
from dam.services.errors import InvalidRequest

BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}
INBOX = "##. Organize"
NORTHPOWER_BILL = (
    "Northpower Oy lasku\nEräpäivä 15.11.2026\nYhteensä 84,20 €\n"
    "IBAN FI21 1234 5600 0007 85\nViitenumero RF18 5390 0754 7034"
)


@pytest.fixture
def client(app):
    with TestClient(create_api(app), base_url=BASE) as c:
        yield c


def post(client, url, body=None):
    return client.post(url, json=body if body is not None else {}, headers=LOCAL_ORIGIN)


@pytest.fixture
def scans(app, fake_archive):
    for drive_id, text in (("s1", NORTHPOWER_BILL), ("s2", "a letter")):
        fake_archive.add(f"{INBOX}/{drive_id}.pdf", content=drive_id.encode(), drive_id=drive_id)
        scan(app.paths, app.repo)
        app.repo.save_content(drive_id, None, ExtractedText(text, "test"), "indexed")
    return ["s1", "s2"]


def test_quick_creates_items_with_the_scan_prefill(client, app, scans):
    r = post(client, "/api/items/quick", {"tray": "to-pay", "drive_ids": ["s1", "s2"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["skipped"] == []
    first, second = body["created"]
    assert first["files"] == ["s1"] and second["files"] == ["s2"]
    assert first["fields"]["amount"] == "84.20" and first["date"] == "2026-11-15"
    assert first["fields"]["iban"] == "FI2112345600000785"
    assert second["fields"] == {}
    # the files stay in the inbox (DB only)
    assert app.repo.get("s1").path == f"{INBOX}/s1.pdf"


def test_quick_skips_files_already_in_tray(client, app, scans):
    post(client, "/api/items/quick", {"tray": "to-pay", "drive_ids": ["s1"]})
    r = post(client, "/api/items/quick", {"tray": "to-pay", "drive_ids": ["s1", "s2"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["skipped"] == ["s1"]
    assert [i["files"] for i in body["created"]] == [["s2"]]
    assert len(app.trays.list("to-pay")) == 2
    # another tray: the file's item moves there (one tray per file), none is created
    r = post(client, "/api/items/quick", {"tray": "to-read", "drive_ids": ["s1"]})
    assert r.json()["skipped"] == [] and r.json()["created"] == []
    assert [i["tray_id"] for i in r.json()["moved"]] == ["to-read"]


def test_quick_errors(client, scans):
    r = post(client, "/api/items/quick", {"tray": "nope", "drive_ids": ["s1"]})
    assert r.status_code == 404
    r = post(client, "/api/items/quick", {"tray": "to-pay", "drive_ids": ["unknown"]})
    assert r.status_code == 404
    r = post(client, "/api/items/quick", {"tray": "to-pay", "drive_ids": []})
    assert r.status_code == 400


def test_quick_refuses_a_folder(client, app, scans):
    from dam.index.repo import FileRecord

    (app.paths.root / "40. House/Sauna").mkdir(parents=True)
    app.repo.upsert(FileRecord(drive_id="dir1", path="40. House/Sauna", is_dir=True))
    r = post(client, "/api/items/quick", {"tray": "to-pay", "drive_ids": ["s1", "dir1"]})
    assert r.status_code == 400, r.text
    assert "Folders cannot be put in a tray" in r.text
    assert app.trays.list("to-pay") == []  # nothing created, not even for the file
    with pytest.raises(InvalidRequest, match="Folders cannot be put in a tray"):
        app.trays.create_quick("to-pay", ["dir1"])


def test_quick_with_fields_uses_them_instead_of_the_prefill(client, app, scans):
    """An AI suggestion's fields, exactly as shown: no prefill added (the IBAN the scan
    found is not shown, so not stored); the same checks as a plain Put in."""
    body = {"tray": "to-pay", "drive_ids": ["s1"], "fields": {"amount": "90.00"}}
    r = post(client, "/api/items/quick", body)
    assert r.status_code == 200, r.text
    (item,) = r.json()["created"]
    assert item["fields"] == {"amount": "90.00"}
    # a stale client (the row still offering Put in) gets "already in", not a second item
    r = post(client, "/api/items/quick", body)
    assert r.status_code == 200, r.text
    assert r.json() == {"created": [], "skipped": ["s1"], "moved": [], "moved_from": {}}
    assert len(app.trays.list("to-pay")) == 1
    # fields are for one file; unknown fields and bad values are refused
    r = post(client, "/api/items/quick", {**body, "tray": "to-read", "drive_ids": ["s1", "s2"]})
    assert r.status_code == 400 and "one file" in r.text
    r = post(
        client, "/api/items/quick", {"tray": "to-read", "drive_ids": ["s2"], "fields": {"x": "1"}}
    )
    assert r.status_code == 400
    r = post(
        client,
        "/api/items/quick",
        {"tray": "to-pay", "drive_ids": ["s2"], "fields": {"amount": "lots"}},
    )
    assert r.status_code == 400
    assert len(app.trays.list("to-pay")) == 1


def test_quick_with_fields_refuses_a_folder(client, app, scans):
    from dam.index.repo import FileRecord

    (app.paths.root / "40. House/Sauna").mkdir(parents=True)
    app.repo.upsert(FileRecord(drive_id="dir1", path="40. House/Sauna", is_dir=True))
    r = post(client, "/api/items/quick", {"tray": "to-pay", "drive_ids": ["dir1"], "fields": {}})
    assert r.status_code == 400 and "Folders cannot be put in a tray" in r.text


def counts(app, item_id: int) -> dict[str, int]:
    out = {}
    with app.engine.connect() as conn:
        out["items"] = conn.scalar(select(func.count()).where(items.c.id == item_id))
        for t in (item_files, item_events, reminders_sent):
            out[t.name] = conn.scalar(select(func.count()).where(t.c.item_id == item_id))
        for t in (notes, checklist_items):
            out[t.name] = conn.scalar(
                select(func.count()).where(t.c.target_kind == "item", t.c.target_id == str(item_id))
            )
    return out


def test_discard_removes_the_item_rows(client, app, scans):
    [item] = post(client, "/api/items/quick", {"tray": "to-pay", "drive_ids": ["s1"]}).json()[
        "created"
    ]
    other = post(client, "/api/items/quick", {"tray": "to-read", "drive_ids": ["s2"]}).json()
    other_id = other["created"][0]["id"]
    with app.engine.begin() as conn:
        conn.execute(
            reminders_sent.insert().values(
                item_id=item["id"], rule="r", occasion=date(2026, 11, 15), fired_at=0.0, channels=[]
            )
        )
    before = counts(app, item["id"])
    assert before["reminders_sent"] == 1 and before["item_files"] == 1
    assert before["item_events"] == 1 and before["items"] == 1
    r = post(client, f"/api/items/{item['id']}/discard")
    assert r.status_code == 204, r.text
    assert counts(app, item["id"]) == dict.fromkeys(counts(app, item["id"]), 0)
    assert client.get(f"/api/items/{item['id']}").status_code == 404
    assert counts(app, other_id)["items"] == 1  # other items untouched
    assert app.repo.get("s1").path == f"{INBOX}/s1.pdf"  # the file is untouched


@pytest.mark.parametrize("what", ["note", "check"])
def test_discard_refuses_an_item_with_text_the_user_typed(client, app, scans, what):
    [item] = post(client, "/api/items/quick", {"tray": "to-pay", "drive_ids": ["s1"]}).json()[
        "created"
    ]
    if what == "note":
        app.notes.set("item", str(item["id"]), "a note")
    else:
        app.notes.add_check("item", str(item["id"]), "check")
    r = post(client, f"/api/items/{item['id']}/discard")
    assert r.status_code == 409
    assert r.json()["error"] == "item was changed — mark it done instead"
    assert client.get(f"/api/items/{item['id']}").status_code == 200
    after = counts(app, item["id"])
    assert after["notes" if what == "note" else "checklist_items"] == 1


def test_discard_refuses_after_edit(client, app, scans):
    [item] = post(client, "/api/items/quick", {"tray": "to-pay", "drive_ids": ["s1"]}).json()[
        "created"
    ]
    app.trays.update(item["id"], {"amount": "90"}, None)
    r = post(client, f"/api/items/{item['id']}/discard")
    assert r.status_code == 409
    assert r.json()["error"] == "item was changed — mark it done instead"
    assert client.get(f"/api/items/{item['id']}").status_code == 200


def test_discard_refuses_a_done_item(client, app, scans):
    [item] = post(client, "/api/items/quick", {"tray": "to-read", "drive_ids": ["s2"]}).json()[
        "created"
    ]
    app.trays.done(item["id"], {})
    r = post(client, f"/api/items/{item['id']}/discard")
    assert r.status_code == 409
    assert r.json()["error"] == "item was changed — mark it done instead"


def test_discard_unknown_item_is_404(client):
    assert post(client, "/api/items/999/discard").status_code == 404
