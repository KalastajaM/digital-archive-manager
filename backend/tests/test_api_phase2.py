"""Phase 2 HTTP API: Today, trays and items, collections, notes, Ongoing, export.

Same conventions as ``test_api.py``: a local ``Host``, and every mutating request sends
a local ``Origin`` (``send``).
"""

import os
import zipfile
from datetime import date, timedelta
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from conftest import posix_permissions
from dam.api import create_api
from dam.reminders.notify import RemindResult

BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}
INBOX = "##. Organize"
BANKS = "10. Financial/Banks"
ONG = "##. Ongoing"


@pytest.fixture
def client(app):
    with TestClient(create_api(app), base_url=BASE) as c:
        yield c


def send(client, method: str, url: str, body=None):
    """A mutating request as the UI sends it: JSON body, local ``Origin``."""
    return client.request(method, url, json=body if body is not None else {}, headers=LOCAL_ORIGIN)


def post(client, url, body=None):
    return send(client, "POST", url, body)


@pytest.fixture
def files(app, fake_archive):
    fake_archive.add(f"{BANKS}/20261020_Northpower_bill.pdf", drive_id="f1")
    fake_archive.add(f"{BANKS}/b.pdf", drive_id="f2")
    fake_archive.add(f"{BANKS}/c.txt", content=b"hello", drive_id="f3")
    app.scan()
    return ["f1", "f2", "f3"]


def new_item(client, drive_ids=("f1",), fields=None, tray="to-pay"):
    r = post(
        client,
        "/api/items",
        {"tray": tray, "drive_ids": list(drive_ids), "fields": fields or {}},
    )
    assert r.status_code == 200, r.text
    return r.json()


# -- today --------------------------------------------------------------------------


def test_today(client, app, files):
    due = (date.today() - timedelta(days=1)).isoformat()
    item = new_item(client, fields={"due_date": due, "amount": "84,20"})
    app.last_reminders = RemindResult(errors={"email": "login failed"})
    r = client.get("/api/today")
    assert r.status_code == 200, r.text
    body = r.json()
    [att] = body["attention"]
    assert att["item"]["id"] == item["id"] and att["level"] == "overdue"
    assert att["tray"] == "to-pay" and att["file_state"] == "ok"
    assert att["note_excerpt"] is None
    assert att["item"]["fields"]["amount"] == "84.20"
    pay = body["overview"]["trays"][0]
    assert pay == {
        "tray_id": "to-pay",
        "name": "To pay",
        "open": 1,
        "overdue": 1,
        "sum": "84.20",
        "waiting_long": 0,
    }
    assert body["overview"]["inbox"] == 0 and body["overview"]["collections"] == []
    assert body["unmanaged_ongoing"] == 0
    assert body["ongoing_sync_failure"] is None
    assert body["reminders"] == {
        "last_run": None,
        "errors": {"email": "login failed"},
        "skipped": None,
    }
    assert body["tray_errors"] == []
    by_tray = {t["tray_id"]: t["items"] for t in body["open_items"]}
    assert [i["id"] for i in by_tray["to-pay"]] == [item["id"]]
    assert by_tray["to-pay"][0]["fields"]["amount"] == "84.20"
    assert by_tray["to-read"] == []


def test_today_reports_a_failing_ongoing_sync(client, app, monkeypatch):
    monkeypatch.setattr(type(app.ongoing), "last_failure", "stopped at symlink X: EIO")
    assert client.get("/api/today").json()["ongoing_sync_failure"] == "stopped at symlink X: EIO"


def test_today_reports_tray_errors_and_status_too(client, app):
    (app.trays_dir / "bad.yaml").write_text("id: x\n", encoding="utf-8")
    app.reload_rules()
    [err] = client.get("/api/today").json()["tray_errors"]
    assert err["file"] == "bad.yaml"
    assert client.get("/api/status").json()["tray_errors"] == [err]


# -- trays and items ----------------------------------------------------------------


def test_trays_lists_defs_with_copy_key(client):
    body = client.get("/api/trays").json()
    assert [t["id"] for t in body["trays"]] == ["to-pay", "to-action", "to-read"]
    assert body["errors"] == []
    fields = body["trays"][0]["fields"]
    assert fields["iban"]["copy"] is True and fields["due_date"]["copy"] is False
    assert body["trays"][0]["done"]["label"] == "Mark paid"


def test_item_lifecycle(client, app, files):
    item = new_item(client, fields={"due_date": "2026-11-03", "amount": "84,20"})
    assert item["title"] == "Northpower bill" and item["files"] == ["f1"]
    assert item["date"] == "2026-11-03" and item["tray_name"] == "To pay"
    assert client.get(f"/api/items/{item['id']}").json() == item
    assert [i["id"] for i in client.get("/api/trays/to-pay/items").json()] == [item["id"]]

    r = send(client, "PATCH", f"/api/items/{item['id']}", {"fields": {"amount": "90"}})
    assert r.status_code == 200 and r.json()["fields"]["amount"] == "90.00"
    r = send(client, "PATCH", f"/api/items/{item['id']}", {"title": "Northpower"})
    assert r.json()["title"] == "Northpower"

    r = post(client, f"/api/items/{item['id']}/files", {"drive_id": "f2"})
    assert r.json()["files"] == ["f1", "f2"]
    r = post(client, f"/api/items/{item['id']}/files/remove", {"drive_id": "f1"})
    assert r.json()["files"] == ["f2"]

    r = post(client, f"/api/items/{item['id']}/done", {"fields": {"paid_on": "2026-10-19"}})
    assert r.status_code == 200 and r.json()["state"] == "done"
    assert r.json()["done_fields"] == {"paid_on": "2026-10-19"}
    assert client.get("/api/trays/to-pay/items").json() == []
    assert len(client.get("/api/trays/to-pay/items?state=done").json()) == 1
    r = post(client, f"/api/items/{item['id']}/reopen")
    assert r.status_code == 200 and r.json()["state"] == "open"

    kinds = [e["kind"] for e in client.get(f"/api/items/{item['id']}/history").json()]
    assert kinds == [
        "created",
        "edited",
        "edited",
        "file_added",
        "file_removed",
        "done",
        "reopened",
    ]


def test_tray_items_carry_level_file_state_and_note_flag(client, app, files, fake_archive):
    due = (date.today() - timedelta(days=1)).isoformat()
    late = new_item(client, ["f1"], fields={"due_date": due})
    undated = new_item(client, ["f2"])
    send(client, "PUT", f"/api/notes/item/{undated['id']}", {"text": "call first"})
    rows = {r["id"]: r for r in client.get("/api/trays/to-pay/items").json()}
    assert rows[late["id"]]["level"] == "overdue" and rows[late["id"]]["has_note"] is False
    assert rows[undated["id"]]["level"] == "undated" and rows[undated["id"]]["has_note"] is True
    assert rows[late["id"]]["file_state"] == "ok"
    (fake_archive.root / BANKS / "b.pdf").rename(fake_archive.root / "##. To Delete" / "b.pdf")
    (fake_archive.root / BANKS / "20261020_Northpower_bill.pdf").unlink()
    app.scan()
    rows = {r["id"]: r for r in client.get("/api/trays/to-pay/items").json()}
    assert rows[late["id"]]["file_state"] == "missing"
    assert rows[undated["id"]]["file_state"] == "to_delete"
    post(client, f"/api/items/{late['id']}/done", {"fields": {}})
    [done] = client.get("/api/trays/to-pay/items?state=done").json()
    assert done["level"] is None and done["state"] == "done"


def test_item_files_with_path_and_state(client, app, files, fake_archive):
    item = new_item(client, ["f1"])
    post(client, f"/api/items/{item['id']}/files", {"drive_id": "f3"})
    body = client.get(f"/api/items/{item['id']}/files").json()
    assert body == [
        {
            "drive_id": "f1",
            "path": f"{BANKS}/20261020_Northpower_bill.pdf",
            "ext": "pdf",
            "state": "ok",
            "in_inbox": False,
            "marks": [],
        },
        {
            "drive_id": "f3",
            "path": f"{BANKS}/c.txt",
            "ext": "txt",
            "state": "ok",
            "in_inbox": False,
            "marks": [],
        },
    ]
    (fake_archive.root / BANKS / "c.txt").rename(fake_archive.root / "##. To Delete" / "c.txt")
    (fake_archive.root / BANKS / "20261020_Northpower_bill.pdf").unlink()
    app.scan()
    states = {
        f["drive_id"]: (f["state"], f["path"])
        for f in client.get(f"/api/items/{item['id']}/files").json()
    }
    assert states["f3"] == ("to_delete", "##. To Delete/c.txt")
    assert states["f1"][0] == "missing"
    assert client.get("/api/items/999/files").status_code == 404


def test_item_files_say_which_are_still_in_the_inbox(client, app, files, fake_archive):
    """Directly in the configured inbox folder: "Paid & file it…" offers filing those."""
    fake_archive.add(f"{INBOX}/scan.pdf", drive_id="i1")
    fake_archive.add(f"{INBOX}/sub/deeper.pdf", drive_id="i2")
    app.scan()
    item = new_item(client, ["f1", "i1", "i2"])
    body = client.get(f"/api/items/{item['id']}/files").json()
    assert [(f["drive_id"], f["in_inbox"]) for f in body] == [
        ("f1", False),
        ("i1", True),
        ("i2", False),
    ]
    (fake_archive.root / INBOX / "scan.pdf").unlink()
    app.scan()
    body = client.get(f"/api/items/{item['id']}/files").json()
    assert body[1]["state"] == "missing" and body[1]["in_inbox"] is False


def test_tray_items_carry_their_first_file(client, app, files, fake_archive):
    """The tray list's Quick Look shows each item's first file without a request per row."""
    fake_archive.add(f"{INBOX}/scan.pdf", drive_id="i1")
    app.scan()
    two = new_item(client, ["i1", "f2"])
    rows = {r["id"]: r for r in client.get("/api/trays/to-pay/items").json()}
    assert rows[two["id"]]["first_file"] == {
        "drive_id": "i1",
        "path": f"{INBOX}/scan.pdf",
        "ext": "pdf",
        "state": "ok",
        "in_inbox": True,
        "marks": [],
    }
    post(client, f"/api/items/{two['id']}/files/remove", {"drive_id": "i1"})
    rows = {r["id"]: r for r in client.get("/api/trays/to-pay/items").json()}
    assert rows[two["id"]]["first_file"]["drive_id"] == "f2"
    assert rows[two["id"]]["first_file"]["in_inbox"] is False


def test_item_errors(client, files):
    assert client.get("/api/items/999").status_code == 404
    assert client.get("/api/trays/nope/items").status_code == 404
    assert client.get("/api/trays/to-pay/items?state=weird").status_code == 422
    r = post(client, "/api/items", {"tray": "nope", "drive_ids": ["f1"], "fields": {}})
    assert r.status_code == 404
    r = post(client, "/api/items", {"tray": "to-pay", "drive_ids": ["zzz"], "fields": {}})
    assert r.status_code == 404
    r = post(client, "/api/items", {"tray": "to-pay", "drive_ids": ["f1"], "fields": {"x": 1}})
    assert r.status_code == 400 and "unknown field" in r.json()["error"]
    item = new_item(client)
    assert post(client, f"/api/items/{item['id']}/reopen").status_code == 400
    r = post(client, f"/api/items/{item['id']}/files/remove", {"drive_id": "f1"})
    assert r.status_code == 400  # an item keeps at least one file
    r = post(client, "/api/items", {"tray": "to-pay", "drive_ids": ["f1"], "origin": "cli"})
    assert r.status_code == 422  # extra fields are refused


def test_file_links(client, app, files):
    item = new_item(client)
    c = post(client, "/api/collections", {"name": "Sauna"}).json()
    post(client, f"/api/collections/{c['id']}/members", {"drive_ids": ["f1"]})
    send(client, "PUT", "/api/notes/file/f1", {"text": "keep"})
    body = client.get("/api/files/f1/links").json()
    assert [i["id"] for i in body["items"]] == [item["id"]]
    assert [x["name"] for x in body["collections"]] == ["Sauna"]
    assert body["note"] == "keep"
    assert client.get("/api/files/nope/links").status_code == 404


# -- collections --------------------------------------------------------------------


def test_collections_crud_and_members(client, app, files, fake_archive):
    r = post(client, "/api/collections", {"name": "Sauna"})
    assert r.status_code == 200
    cid = r.json()["id"]
    r = post(client, f"/api/collections/{cid}/members", {"drive_ids": ["f1", "f2"]})
    members = r.json()["collection"]["members"]
    assert [m["drive_id"] for m in members] == ["f1", "f2"]
    assert members[0]["path"] == f"{BANKS}/20261020_Northpower_bill.pdf"
    # the Ongoing publisher ran: a folder of two links
    assert sorted(os.listdir(fake_archive.root / ONG / "Sauna")) == [
        "20261020_Northpower_bill.pdf",
        "b.pdf",
    ]
    r = post(client, f"/api/collections/{cid}/members/remove", {"drive_id": "f2"})
    assert [m["drive_id"] for m in r.json()["collection"]["members"]] == ["f1"]
    assert [c["name"] for c in client.get("/api/collections").json()] == ["Sauna"]
    assert client.get(f"/api/collections/{cid}").json()["name"] == "Sauna"
    assert client.get("/api/collections/999").status_code == 404
    assert post(client, "/api/collections", {"name": "sauna"}).status_code == 400
    assert post(client, "/api/collections/999/members", {"drive_ids": ["f1"]}).status_code == 404


def test_rename_preview_then_apply(client, app, files, fake_archive):
    cid = post(client, "/api/collections", {"name": "Sauna"}).json()["id"]
    post(client, f"/api/collections/{cid}/members", {"drive_ids": ["f1", "f2"]})
    ops = post(client, f"/api/collections/{cid}/rename/preview", {"name": "Spa"}).json()
    assert any(op["dst"] == f"{ONG}/Spa" for op in ops)
    assert (fake_archive.root / ONG / "Sauna").is_dir()  # the preview changed nothing
    assert client.get(f"/api/collections/{cid}").json()["name"] == "Sauna"
    r = send(client, "PATCH", f"/api/collections/{cid}", {"name": "Spa"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["collection"]["name"] == "Spa" and body["problems"] == []
    assert body["batch"]["done"] and body["ongoing_status"] is None
    assert (fake_archive.root / ONG / "Spa").is_dir()
    assert not os.path.lexists(fake_archive.root / ONG / "Sauna")


def test_close_reopen_publish(client, app, files, fake_archive):
    cid = post(client, "/api/collections", {"name": "Sauna"}).json()["id"]
    post(client, f"/api/collections/{cid}/members", {"drive_ids": ["f1", "f2"]})
    ops = post(client, f"/api/collections/{cid}/close/preview").json()
    assert {op["kind"] for op in ops} == {"unlink_symlink", "remove_empty_dir"}
    assert client.get(f"/api/collections/{cid}").json()["state"] == "open"
    r = post(client, f"/api/collections/{cid}/close")
    assert r.status_code == 200, r.text
    assert r.json()["collection"]["state"] == "closed" and r.json()["batch"]["done"]
    assert not os.path.lexists(fake_archive.root / ONG / "Sauna")
    assert [c["name"] for c in client.get("/api/collections?state=closed").json()] == ["Sauna"]
    assert client.get("/api/collections?state=open").json() == []
    assert len(client.get("/api/collections?state=all").json()) == 1

    assert post(client, f"/api/collections/{cid}/reopen/preview").json()
    r = post(client, f"/api/collections/{cid}/reopen")
    assert r.json()["collection"]["state"] == "open"
    assert (fake_archive.root / ONG / "Sauna").is_dir()

    off = {"publisher": "ongoing", "on": False}
    assert post(client, f"/api/collections/{cid}/publish/preview", off).json()
    assert (fake_archive.root / ONG / "Sauna").is_dir()
    r = post(client, f"/api/collections/{cid}/publish", off)
    assert r.json()["collection"]["publish"] == {"ongoing": False}
    assert not os.path.lexists(fake_archive.root / ONG / "Sauna")
    r = post(client, f"/api/collections/{cid}/publish", {"publisher": "other", "on": True})
    assert r.status_code == 422
    assert post(client, "/api/collections/999/close").status_code == 404
    assert post(client, "/api/collections/999/close/preview").status_code == 404


def test_apply_reports_ongoing_problems(client, app, files, fake_archive):
    cid = post(client, "/api/collections", {"name": "Sauna"}).json()["id"]
    post(client, f"/api/collections/{cid}/members", {"drive_ids": ["f1", "f2"]})
    (fake_archive.root / ONG / "Sauna" / "mine.txt").write_text("user file", encoding="utf-8")
    body = post(client, f"/api/collections/{cid}/close").json()
    assert body["ongoing_status"] and body["ongoing_status"].startswith("Needs attention")
    assert body["collection"]["ongoing_status"] == body["ongoing_status"]
    assert (fake_archive.root / ONG / "Sauna" / "mine.txt").exists()


# -- notes and checklists -----------------------------------------------------------


def test_notes(client, app, files):
    assert client.get("/api/notes/file/f1").json() == {"text": ""}
    r = send(client, "PUT", "/api/notes/file/f1", {"text": "  hello  "})
    assert r.status_code == 200 and r.json() == {"text": "hello"}
    assert client.get("/api/notes/file/f1").json() == {"text": "hello"}
    cid = post(client, "/api/collections", {"name": "Sauna"}).json()["id"]
    assert send(client, "PUT", f"/api/notes/collection/{cid}", {"text": "n"}).status_code == 200
    assert client.get("/api/notes/file/nope").status_code == 404
    assert client.get("/api/notes/collection/999").status_code == 404
    assert client.get("/api/notes/collection/abc").status_code == 404
    assert client.get("/api/notes/item/1").status_code == 404
    assert client.get("/api/notes/weird/1").status_code == 422
    r = send(client, "PUT", "/api/notes/file/f1", {"text": "x" * 10_001})
    assert r.status_code == 400


def test_checklist(client, app, files):
    cid = post(client, "/api/collections", {"name": "Sauna"}).json()["id"]
    url = f"/api/checklist/collection/{cid}"
    a = post(client, url, {"text": "call Marco"}).json()
    b = post(client, url, {"text": "order wood"}).json()
    assert [c["text"] for c in client.get(url).json()] == ["call Marco", "order wood"]
    assert send(client, "PATCH", f"/api/checklist/{a['id']}", {"done": True}).status_code == 204
    assert client.get(url).json()[0]["done"] is True
    r = post(client, f"/api/checklist/{b['id']}/move", {"position": 0})
    assert r.status_code == 204
    assert [c["id"] for c in client.get(url).json()] == [b["id"], a["id"]]
    assert post(client, f"/api/checklist/{a['id']}/remove").status_code == 204
    assert [c["id"] for c in client.get(url).json()] == [b["id"]]
    assert send(client, "PATCH", "/api/checklist/999", {"done": True}).status_code == 404
    assert post(client, url, {"text": "  "}).status_code == 400
    assert post(client, "/api/checklist/file/nope", {"text": "x"}).status_code == 404
    # a file whose drive id looks like a route word is still a file target
    assert client.get("/api/checklist/file/f1").json() == []


# -- Ongoing conversion -------------------------------------------------------------


def test_ongoing_entries_preview_and_convert(client, app, files, fake_archive):
    fake_archive.link(f"{ONG}/Bill", f"{BANKS}/b.pdf")
    app.scan()
    [entry] = client.get("/api/ongoing/entries").json()
    assert entry["rel"] == f"{ONG}/Bill" and entry["kind"] == "link"
    assert entry["managed"] is False and entry["problem"] is None
    body = {"rel": f"{ONG}/Bill", "collection": "Bills", "destination": None}
    plan = post(client, "/api/ongoing/preview", body).json()
    assert plan["members"] == [f"{BANKS}/b.pdf"] and plan["fingerprint"]
    assert (plan["collection"], plan["existing"], plan["existing_members"]) == ("Bills", False, 0)
    assert entry["collection_id"] is None and entry["collection_name"] is None
    assert plan["ops"][0]["kind"] == "unlink_symlink"
    assert client.get("/api/today").json()["unmanaged_ongoing"] == 1

    r = post(client, "/api/ongoing/convert", {**body, "fingerprint": "stale"})
    assert r.status_code == 400 and "Preview again" in r.json()["error"]
    assert r.json()["code"] == "stale_preview"
    r = post(client, "/api/ongoing/convert", {**body, "fingerprint": plan["fingerprint"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["collection_id"] and out["batch"]["done"] and out["problems"] == []
    [done] = client.get("/api/ongoing/entries").json()
    assert done["managed"] is True
    assert (done["collection_id"], done["collection_name"]) == (out["collection_id"], "Bills")
    assert client.get("/api/today").json()["unmanaged_ongoing"] == 0
    r = post(client, "/api/ongoing/convert", body)
    assert r.status_code == 422  # fingerprint is required


def test_preview_names_the_collection_it_would_merge_into(client, app, files, fake_archive):
    fake_archive.link(f"{ONG}/Bill", f"{BANKS}/b.pdf")
    app.scan()
    made = post(client, "/api/collections", {"name": "Legal Stuff"}).json()
    body = {"rel": f"{ONG}/Bill", "collection": "legal stuff", "destination": None}
    plan = post(client, "/api/ongoing/preview", body).json()
    assert plan["collection"] == "Legal Stuff"  # the resolved name, not the typed one
    assert plan["existing"] is True and plan["existing_members"] == 0
    r = post(client, "/api/ongoing/convert", {**body, "fingerprint": plan["fingerprint"]})
    assert r.json()["collection_id"] == made["id"]
    fake_archive.link(f"{ONG}/Bill2", f"{BANKS}/b.pdf")
    app.scan()
    [second] = [e for e in client.get("/api/ongoing/entries").json() if not e["managed"]]
    body2 = {"rel": second["rel"], "collection": "LEGAL STUFF", "destination": None}
    plan2 = post(client, "/api/ongoing/preview", body2).json()
    assert (plan2["collection"], plan2["existing_members"]) == ("Legal Stuff", 1)


# -- export -------------------------------------------------------------------------


def test_export_zip_and_download(client, app, files):
    cid = post(client, "/api/collections", {"name": "Sauna å"}).json()["id"]
    post(client, f"/api/collections/{cid}/members", {"drive_ids": ["f1", "f3"]})
    r = post(client, f"/api/collections/{cid}/export", {"format": "zip", "confirm_large": False})
    assert r.status_code == 200, r.text
    out = r.json()
    assert len(out["token"]) == 32 and out["size"] > 0 and out["not_included"] == []
    assert out["needs_confirm"] is False
    d = client.get(f"/api/exports/{out['token']}")
    assert d.status_code == 200
    assert d.headers["content-disposition"] == "attachment; filename*=UTF-8''" + quote(
        "Sauna å.zip", safe=""
    )
    assert d.headers["x-content-type-options"] == "nosniff"
    assert d.headers["cache-control"] == "no-store"
    assert "sandbox" in d.headers["content-security-policy"]
    assert d.headers["content-type"] == "application/zip"
    import io

    names = zipfile.ZipFile(io.BytesIO(d.content)).namelist()
    assert f"{BANKS}/c.txt" in names and "contents.txt" in names


def test_export_pdf_lists_not_included(client, app, files):
    cid = post(client, "/api/collections", {"name": "S"}).json()["id"]
    post(client, f"/api/collections/{cid}/members", {"drive_ids": ["f3"]})
    out = post(client, f"/api/collections/{cid}/export", {"format": "pdf"}).json()
    assert out["not_included"] == [
        {"path": f"{BANKS}/c.txt", "reason": "file type is not included in a PDF"}
    ]
    d = client.get(f"/api/exports/{out['token']}")
    assert d.status_code == 200 and d.headers["content-type"] == "application/pdf"


@posix_permissions
def test_export_zip_lists_not_included(client, app, files, fake_archive):
    cid = post(client, "/api/collections", {"name": "S"}).json()["id"]
    post(client, f"/api/collections/{cid}/members", {"drive_ids": ["f3"]})
    (fake_archive.root / BANKS / "c.txt").chmod(0)
    try:
        out = post(client, f"/api/collections/{cid}/export", {"format": "zip"}).json()
    finally:
        (fake_archive.root / BANKS / "c.txt").chmod(0o644)
    [skip] = out["not_included"]
    assert skip["path"] == f"{BANKS}/c.txt" and skip["reason"]


def test_large_export_needs_confirm(client, app, files, monkeypatch):
    from dam.collections import export

    monkeypatch.setattr(export, "LARGE_EXPORT_BYTES", 1)
    cid = post(client, "/api/collections", {"name": "S"}).json()["id"]
    post(client, f"/api/collections/{cid}/members", {"drive_ids": ["f3"]})
    out = post(client, f"/api/collections/{cid}/export", {"format": "zip"}).json()
    assert out == {"token": None, "size": 5, "needs_confirm": True, "not_included": []}
    body = {"format": "zip", "confirm_large": True}
    assert post(client, f"/api/collections/{cid}/export", body).json()["token"]


def test_export_errors(client, app, files):
    assert post(client, "/api/collections/999/export", {"format": "zip"}).status_code == 404
    cid = post(client, "/api/collections", {"name": "S"}).json()["id"]
    assert post(client, f"/api/collections/{cid}/export", {"format": "rar"}).status_code == 422
    assert client.get("/api/exports/" + "0" * 32).status_code == 404
    assert client.get("/api/exports/..%2F..%2Fdam.sqlite").status_code == 404
    assert client.get("/api/exports/not-a-token").status_code == 404


def test_pruned_export_is_404(client, app, files):
    import shutil

    cid = post(client, "/api/collections", {"name": "S"}).json()["id"]
    post(client, f"/api/collections/{cid}/members", {"drive_ids": ["f3"]})
    token = post(client, f"/api/collections/{cid}/export", {"format": "zip"}).json()["token"]
    shutil.rmtree(app.app_paths.cache_dir / "exports" / token)
    assert client.get(f"/api/exports/{token}").status_code == 404


# -- activity, inbox ----------------------------------------------------------------


def test_activity_has_undoable(client, app, files):
    cid = post(client, "/api/collections", {"name": "S"}).json()["id"]
    post(client, f"/api/collections/{cid}/members", {"drive_ids": ["f1", "f2"]})
    [batch] = client.get("/api/activity").json()
    assert batch["origin"] == "workflow" and batch["undoable"] is False


def test_collection_changes_are_titled_by_what_the_user_did(client, app, files):
    def newest():
        return client.get("/api/activity").json()[0]

    cid = post(client, "/api/collections", {"name": "Sauna"}).json()["id"]
    post(client, f"/api/collections/{cid}/members", {"drive_ids": ["f1", "f2"]})
    assert newest()["label"] == "Added 2 files to Sauna"
    send(client, "PATCH", f"/api/collections/{cid}", {"name": "Sauna rebuild"})
    b = newest()
    assert b["label"] == "Renamed collection Sauna to Sauna rebuild"
    # the label titles the batch only: an automatic sync is still not undoable
    assert b["origin"] == "workflow" and b["undoable"] is False
    post(client, "/api/marks/star", {"drive_ids": ["f3"]})
    assert newest()["label"] == "Starred c.txt"
    post(client, f"/api/collections/{cid}/members/remove", {"drive_id": "f1"})
    assert newest()["label"] == "Removed 20261020_Northpower_bill.pdf from Sauna rebuild"
    # a sync nobody asked for stays unlabelled
    post(client, f"/api/collections/{cid}/members", {"drive_ids": ["f1"]})
    app.collections.set_name(cid, "Sauna again")
    assert newest()["label"] is None


def test_inbox_file_with_tray_collections_and_note(client, app, fake_archive):
    fake_archive.add(f"{INBOX}/scan.pdf", drive_id="in-1")
    app.scan()
    [entry] = client.get("/api/inbox").json()
    assert entry["prefill"] == {}
    req = {
        "drive_id": "in-1",
        "name": "bill.pdf",
        "folder": BANKS,
        "tags": [],
        "tray": "to-pay",
        "tray_fields": {"due_date": "2026-11-03"},
        "collections": ["Sauna"],
        "note": "paid by card?",
    }
    ops = post(client, "/api/inbox/preview", [req]).json()
    assert ops[0]["dst"] == f"{BANKS}/bill.pdf"
    r = post(client, "/api/inbox/file", {"requests": [req]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 1 and body["follow_up_error"] is None
    item = client.get(f"/api/items/{body['items'][0]}").json()
    assert item["date"] == "2026-11-03"
    assert client.get("/api/files/in-1/links").json()["collections"][0]["name"] == "Sauna"


# -- the Phase 1 middleware still guards every new route ---------------------------


@pytest.mark.parametrize(
    "url",
    [
        "/api/items",
        "/api/collections",
        "/api/collections/1/close",
        "/api/ongoing/convert",
        "/api/collections/1/export",
    ],
)
def test_post_needs_json_and_local_origin(client, url):
    r = client.post(url, content=b"x", headers={**LOCAL_ORIGIN, "Content-Type": "text/plain"})
    assert r.status_code == 415
    assert client.post(url, json={}).status_code == 403  # no Origin, no Sec-Fetch-Site


@pytest.mark.parametrize(
    ("method", "url"),
    [("PATCH", "/api/items/1"), ("PUT", "/api/notes/file/x"), ("PATCH", "/api/collections/1")],
)
def test_patch_and_put_need_local_origin(client, method, url):
    assert client.request(method, url, json={}).status_code == 403
    r = client.request(method, url, json={}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_openapi_has_phase2_models(app):
    schema = create_api(app).openapi()
    for path in (
        "/api/today",
        "/api/trays",
        "/api/items/{item_id}",
        "/api/collections/{collection_id}/close/preview",
        "/api/ongoing/convert",
        "/api/exports/{token}",
        "/api/checklist/{check_id}/move",
    ):
        assert path in schema["paths"], path
    names = schema["components"]["schemas"]
    for name in ("TodayOut", "ItemOut", "CollectionOut", "ConvertPlanOut", "ExportOut"):
        assert name in names


# -- serve: background reminders and Ongoing sync -----------------------------------


def wait_for(cond, timeout=10.0):
    import time

    deadline = time.monotonic() + timeout
    while not cond() and time.monotonic() < deadline:
        time.sleep(0.02)
    return cond()


def test_reminders_thread_runs_survives_errors_and_stops(app, monkeypatch):
    import dam.serve as serve_mod

    calls = []

    def fake_run(a, now):
        calls.append(now)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return RemindResult(ran_at=now)

    monkeypatch.setattr(serve_mod, "REMIND_FIRST_S", 0.05)
    monkeypatch.setattr(serve_mod, "REMIND_EVERY_S", 0.05)
    monkeypatch.setattr(serve_mod, "run_reminders", fake_run)
    bg = serve_mod.start_background(app)
    try:
        assert wait_for(lambda: len(calls) >= 3)
        assert all(now.tzinfo is not None for now in calls)
        assert bg.reminders_thread.is_alive()
    finally:
        bg.stop()
    assert not bg.reminders_thread.is_alive()
    assert not any(t.is_alive() for t in bg.threads)


def test_reminders_thread_waits_a_minute_first(app, monkeypatch):
    import dam.serve as serve_mod

    calls = []
    monkeypatch.setattr(serve_mod, "run_reminders", lambda a, now: calls.append(now))
    assert serve_mod.REMIND_FIRST_S == 60 and serve_mod.REMIND_EVERY_S == 3600
    bg = serve_mod.start_background(app)
    bg.scan_thread.join(10)
    bg.stop()  # well before a minute: never ran, and stop did not wait for it
    assert calls == [] and not bg.reminders_thread.is_alive()


def test_skipped_run_keeps_the_last_result(app, monkeypatch):
    import dam.serve as serve_mod

    done = RemindResult(errors={"email": "x"})
    results = [done, RemindResult(skipped="another run in progress")]

    def fake_run(a, now):
        r = results.pop(0)
        if r is done:
            a.last_reminders = r  # run_reminders keeps completed results itself
        return r

    monkeypatch.setattr(serve_mod, "run_reminders", fake_run)
    serve_mod._remind_once(app)
    serve_mod._remind_once(app)
    assert app.last_reminders.errors == {"email": "x"}
    assert app.last_reminders.skipped == "another run in progress"


def test_a_raising_reminder_run_is_shown_on_today(client, app, monkeypatch, caplog):
    import logging

    import dam.serve as serve_mod

    def broken(a, now):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(serve_mod, "run_reminders", broken)
    with caplog.at_level(logging.ERROR, logger="dam.serve"):
        serve_mod._remind_once(app)  # no earlier result: one is created
    assert app.last_reminders.errors == {"run": "database is locked"}
    assert client.get("/api/today").json()["reminders"]["errors"] == {"run": "database is locked"}
    app.last_reminders = RemindResult(errors={"email": "x"})
    serve_mod._remind_once(app)  # added to the last result
    assert app.last_reminders.errors == {"email": "x", "run": "database is locked"}


def test_ongoing_sync_after_initial_scan(app, monkeypatch):
    import dam.serve as serve_mod

    synced = []
    monkeypatch.setattr(app.ongoing, "sync", lambda: synced.append(1))
    bg = serve_mod.start_background(app)
    try:
        bg.scan_thread.join(10)
        assert synced == [1]
    finally:
        bg.stop()


def test_failing_ongoing_sync_does_not_kill_the_scan_thread(app, monkeypatch, caplog):
    import logging
    import threading

    import dam.serve as serve_mod

    def broken():
        raise RuntimeError("sync broke")

    monkeypatch.setattr(app, "sync_publishers", broken)
    wake = threading.Event()
    with caplog.at_level(logging.ERROR, logger="dam.serve"):
        serve_mod._initial_scan(app, wake)
        serve_mod._after_watcher_scan(app, wake)
    assert wake.is_set()
    assert caplog.text.count("ongoing sync failed") == 2


def test_member_routes_report_the_sync(client, app, files, fake_archive):
    cid = post(client, "/api/collections", {"name": "Sauna"}).json()["id"]
    r = post(client, f"/api/collections/{cid}/members", {"drive_ids": ["f1"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [m["drive_id"] for m in body["collection"]["members"]] == ["f1"]
    assert [op["kind"] for op in body["batch"]["done"]] == ["mkdir", "symlink"]
    assert body["problems"] == [] and body["ongoing_status"] is None

    def broken():
        raise RuntimeError("boom")

    app.collections.on_change = broken
    r = post(client, f"/api/collections/{cid}/members/remove", {"drive_id": "f1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["collection"]["members"] == [] and body["batch"] is None
    assert body["problems"] == [
        "Ongoing could not be updated (details are in the log). The next scan will try again."
    ]
    r = post(client, f"/api/collections/{cid}/members", {"drive_ids": ["f2"]})
    assert r.json()["problems"] and r.json()["collection"]["members"][0]["drive_id"] == "f2"


def test_collection_list_rows_count_files_and_open_checks(client, app, files):
    cid = post(client, "/api/collections", {"name": "Sauna"}).json()["id"]
    post(client, f"/api/collections/{cid}/members", {"drive_ids": ["f1", "f2"]})
    url = f"/api/checklist/collection/{cid}"
    a = post(client, url, {"text": "call Marco"}).json()
    post(client, url, {"text": "order wood"})
    send(client, "PATCH", f"/api/checklist/{a['id']}", {"done": True})
    [row] = client.get("/api/collections").json()
    assert row["name"] == "Sauna" and row["files"] == 2 and row["open_checks"] == 1
    post(client, f"/api/collections/{cid}/close")
    [row] = client.get("/api/collections?state=closed").json()
    assert row["files"] == 2 and row["open_checks"] == 1


def test_collection_previews_go_through_the_publisher_registry(client, app):
    cid = post(client, "/api/collections", {"name": "Sauna"}).json()["id"]
    seen = []

    class Fake:
        id = "ongoing"

        def sync(self, dry_run=False):
            return None

        def preview_for(self, collection_ids, **changes):
            seen.append((collection_ids, changes))
            return []

    app.publishers.register(Fake())  # replaces the Ongoing publisher under its id
    assert post(client, f"/api/collections/{cid}/close/preview").json() == []
    assert seen == [([cid], {"state": "closed"})]


@pytest.mark.parametrize("kind", ["collection", "item"])
def test_note_target_ids_out_of_range_are_4xx(client, kind):
    for target in ["9" * 300, "9" * 19, str(2**63)]:
        r = client.get(f"/api/notes/{kind}/{target}")
        assert 400 <= r.status_code < 500, (target, r.status_code)
    assert client.get(f"/api/notes/{kind}/{'9' * 18}").status_code == 404
