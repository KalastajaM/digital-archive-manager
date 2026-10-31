"""Renewed… from the tray (Task 5): the preview, the move of the old file into its
folder's Expired subfolder, locks, and the Undo (Activity's, or the renewal's own)."""

import os
from datetime import date

import pytest
from fastapi.testclient import TestClient

from dam.api import create_api

BANKS = "10. Financial/Banks"
OLD = f"{BANKS}/passport-old.pdf"
BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}
OLD_DATE = date(2027, 6, 30)
NEW_DATE = date(2037, 6, 30)


@pytest.fixture
def item(app, fake_archive):
    fake_archive.add(OLD, drive_id="old")
    fake_archive.add(f"{BANKS}/passport-new.pdf", drive_id="new")
    fake_archive.add(f"{BANKS}/terms.pdf", drive_id="terms")
    app.scan()
    return app.trays.create(
        "renew", ["old", "terms"], {"expires": OLD_DATE.isoformat(), "kind": "Passport"}, None
    )


@pytest.fixture
def client(app):
    with TestClient(create_api(app), base_url=BASE) as c:
        yield c


def send(client, url, body=None, tokens=()):
    headers = dict(LOCAL_ORIGIN)
    if tokens:
        headers["X-Dam-Unlock"] = ", ".join(tokens)
    return client.post(url, json=body if body is not None else {}, headers=headers)


def body(drive_id="new"):
    out = {"expires": NEW_DATE.isoformat()}
    if drive_id is not None:
        out["drive_id"] = drive_id
    return out


def preview(client, item, drive_id="new", tokens=()):
    r = send(client, f"/api/items/{item.id}/renew/preview", body(drive_id), tokens)
    assert r.status_code == 200, r.text
    return r.json()


def renew(client, item, drive_id="new", tokens=()):
    return send(client, f"/api/items/{item.id}/renew", body(drive_id), tokens)


def at(fake_archive, rel):
    return (fake_archive.root / rel).exists()


def unchanged(app, item):
    after = app.trays.get(item.id)
    assert after.files == ["old", "terms"]
    assert after.date == OLD_DATE
    assert [e for e in app.trays.history(item.id) if e.kind == "renewed"] == []


def test_preview_lists_move_and_mkdir(client, app, item, fake_archive):
    out = preview(client, item)
    assert out["skipped"] is None and out["locked"] == []
    assert [(o["kind"], o["src"], o["dst"]) for o in out["ops"]] == [
        ("mkdir", None, f"{BANKS}/Expired"),
        ("move", OLD, f"{BANKS}/Expired/passport-old.pdf"),
    ]
    assert at(fake_archive, OLD) and not at(fake_archive, f"{BANKS}/Expired")
    unchanged(app, item)


def test_apply_moves_old_into_expired(client, app, item, fake_archive):
    r = renew(client, item)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["item"]["files"] == ["new", "terms"]
    assert out["item"]["date"] == NEW_DATE.isoformat()
    assert out["skipped"] is None and out["undo"] == "activity"
    assert not at(fake_archive, OLD)
    assert at(fake_archive, f"{BANKS}/Expired/passport-old.pdf")
    assert at(fake_archive, f"{BANKS}/passport-new.pdf")
    (ev,) = [e for e in app.trays.history(item.id) if e.kind == "renewed"]
    assert ev.data["batch_id"] == out["batch_id"]
    assert ev.data["moved"] is True and ev.data["expired"] == "Expired"
    batch = app.activity.get(out["batch_id"])
    assert batch.label == f"Renewed {item.title}: moved passport-old.pdf to Expired"


def test_name_taken_gets_2(client, app, item, fake_archive):
    fake_archive.add(f"{BANKS}/Expired/passport-old.pdf", drive_id="older")
    app.scan()
    ops = preview(client, item)["ops"]
    assert [(o["kind"], o["dst"]) for o in ops] == [("move", f"{BANKS}/Expired/passport-old_2.pdf")]
    assert renew(client, item).status_code == 200
    assert at(fake_archive, f"{BANKS}/Expired/passport-old_2.pdf")
    assert at(fake_archive, f"{BANKS}/Expired/passport-old.pdf")


def test_renew_expired_path_is_a_file(client, app, item, fake_archive):
    fake_archive.add(f"{BANKS}/Expired", drive_id="expired-file")
    app.scan()
    r = send(client, f"/api/items/{item.id}/renew/preview", body())
    assert r.status_code == 400 and "not a folder" in r.text
    r = renew(client, item)
    assert r.status_code == 400 and "not a folder" in r.text
    assert at(fake_archive, OLD)
    unchanged(app, item)


def test_renew_old_file_missing_skips_move(client, app, item, fake_archive):
    (fake_archive.root / OLD).unlink()
    app.scan()
    out = preview(client, item)
    assert out == {
        "ops": [],
        "skipped": "The old file is no longer in the archive",
        "locked": [],
    }
    r = renew(client, item)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["skipped"] == "The old file is no longer in the archive"
    assert out["undo"] == "renewal" and out["batch_id"]
    assert out["item"]["files"] == ["new", "terms"]
    (ev,) = [e for e in app.trays.history(item.id) if e.kind == "renewed"]
    assert ev.data["moved"] is False and ev.data["expired"] is None
    r = send(client, "/api/renewals/undo", {"batch_id": out["batch_id"]})
    assert r.status_code == 200, r.text
    assert r.json()["files"] == ["old", "terms"]
    assert r.json()["date"] == OLD_DATE.isoformat()


def test_renew_old_file_in_to_delete_skips_move(client, app, item, fake_archive):
    app.browse.quarantine(["old"], origin="ui")
    out = preview(client, item)
    assert out["ops"] == [] and out["skipped"] == "The old file is in To Delete"
    r = renew(client, item)
    assert r.status_code == 200, r.text
    assert r.json()["skipped"] == "The old file is in To Delete"
    assert r.json()["undo"] == "renewal"


def test_renew_old_file_not_connected_skips_move(extra_folder, app, client, fake_archive, tmp_path):
    extra_folder.add("2009/passport-old.pdf", drive_id="old")
    fake_archive.add(f"{BANKS}/passport-new.pdf", drive_id="new")
    app.scan()
    item = app.trays.create("renew", ["old"], {"expires": OLD_DATE.isoformat()}, None)
    os.rename(extra_folder.root, tmp_path / "unplugged")
    app.scan()
    out = preview(client, item)
    assert out["ops"] == []
    assert out["skipped"] == "The old file's archive folder is not connected"
    r = renew(client, item)
    assert r.status_code == 200, r.text
    assert r.json()["item"]["files"] == ["new"]


def test_renew_old_file_at_the_top_skips_move(client, app, fake_archive):
    fake_archive.add("passport-old.pdf", drive_id="old")
    fake_archive.add(f"{BANKS}/passport-new.pdf", drive_id="new")
    app.scan()
    item = app.trays.create("renew", ["old"], {"expires": OLD_DATE.isoformat()}, None)
    out = preview(client, item)
    assert out["ops"] == [] and out["skipped"] == "The old file is at the top of the archive"
    r = renew(client, item)
    assert r.status_code == 200, r.text
    assert r.json()["skipped"] == "The old file is at the top of the archive"
    assert r.json()["item"]["files"] == ["new"]
    assert at(fake_archive, "passport-old.pdf") and not at(fake_archive, "Expired")


def test_locked_preview_reports_locked(client, app, item, fake_archive):
    app.marks.mark_important(["old"], None)
    out = preview(client, item)
    assert out == {
        "ops": [],
        "skipped": None,
        "locked": [{"drive_id": "old", "name": "passport-old.pdf"}],
    }
    r = renew(client, item)
    assert r.status_code == 400, r.text
    assert at(fake_archive, OLD)
    unchanged(app, item)


def test_a_stored_lock_is_reported_too(client, app, item):
    app.locks.lock("old")
    assert preview(client, item)["locked"] == [{"drive_id": "old", "name": "passport-old.pdf"}]


def test_apply_with_grant_moves_important(client, app, item, fake_archive):
    app.marks.star(["old"])
    app.marks.mark_important(["old"], "Docs/ID")
    token = app.locks.grant("old")
    out = preview(client, item, tokens=[token])
    assert out["locked"] == [] and [o["kind"] for o in out["ops"]] == ["mkdir", "move"]
    r = renew(client, item, tokens=[token])
    assert r.status_code == 200, r.text
    assert at(fake_archive, f"{BANKS}/Expired/passport-old.pdf")
    assert app.marks.marks_for(["old", "new"]) == {"old": [], "new": ["starred", "important"]}


def test_activity_undo_reverses_all(client, app, item, fake_archive):
    app.marks.star(["old"])
    app.marks.mark_important(["old"], "Docs/ID")
    r = renew(client, item, tokens=[app.locks.grant("old")])
    assert r.status_code == 200, r.text
    batch_id = r.json()["batch_id"]
    r = send(client, f"/api/activity/{batch_id}/undo")
    assert r.status_code == 200, r.text
    assert r.json()["error"] is None and r.json()["follow_up_error"] is None
    assert at(fake_archive, OLD)
    # an undo never removes a folder a move made (dam.ops.undo): Expired stays, empty
    assert list((fake_archive.root / BANKS / "Expired").iterdir()) == []
    after = app.trays.get(item.id)
    assert after.files == ["old", "terms"] and after.date == OLD_DATE
    assert app.marks.marks_for(["old", "new"]) == {"old": ["starred", "important"], "new": []}


def test_renamed_expired_setting_used(client, app, item, fake_archive):
    r = client.put(
        "/api/settings/expired-folder", json={"name": "Vanhentuneet"}, headers=LOCAL_ORIGIN
    )
    assert r.status_code == 200, r.text
    ops = preview(client, item)["ops"]
    assert ops[-1]["dst"] == f"{BANKS}/Vanhentuneet/passport-old.pdf"
    r = renew(client, item)
    assert r.status_code == 200, r.text
    assert at(fake_archive, f"{BANKS}/Vanhentuneet/passport-old.pdf")
    assert app.activity.get(r.json()["batch_id"]).label.endswith("to Vanhentuneet")


def test_renew_without_file_moves_nothing(client, app, item, fake_archive):
    out = preview(client, item, drive_id=None)
    assert out == {"ops": [], "skipped": None, "locked": []}
    r = renew(client, item, drive_id=None)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["item"]["files"] == ["old", "terms"]
    assert out["item"]["date"] == NEW_DATE.isoformat()
    assert out["undo"] == "renewal" and out["batch_id"] and out["skipped"] is None
    assert at(fake_archive, OLD)
    r = send(client, "/api/renewals/undo", {"batch_id": out["batch_id"]})
    assert r.status_code == 200, r.text
    assert r.json()["date"] == OLD_DATE.isoformat()


def test_renew_without_file_ignores_a_lock(client, app, item):
    app.marks.mark_important(["old"], None)
    assert preview(client, item, drive_id=None)["locked"] == []
    assert renew(client, item, drive_id=None).status_code == 200


def test_renewal_undo_restores_the_marks(client, app, item, fake_archive):
    app.marks.star(["old"])
    (fake_archive.root / OLD).unlink()
    app.scan()
    out = renew(client, item).json()
    assert app.marks.marks_for(["old", "new"]) == {"old": [], "new": ["starred"]}
    r = send(client, "/api/renewals/undo", {"batch_id": out["batch_id"]})
    assert r.status_code == 200, r.text
    assert app.marks.marks_for(["old", "new"]) == {"old": ["starred"], "new": []}


def test_renewal_undo_refuses_a_journaled_batch(client, app, item):
    batch_id = renew(client, item).json()["batch_id"]
    r = send(client, "/api/renewals/undo", {"batch_id": batch_id})
    assert r.status_code == 400 and "Activity" in r.text
    assert app.trays.get(item.id).files == ["new", "terms"]


def test_renewal_undo_unknown_or_twice(client, app, item):
    assert send(client, "/api/renewals/undo", {"batch_id": "nope"}).status_code == 404
    batch_id = renew(client, item, drive_id=None).json()["batch_id"]
    assert send(client, "/api/renewals/undo", {"batch_id": batch_id}).status_code == 200
    assert send(client, "/api/renewals/undo", {"batch_id": batch_id}).status_code == 409


def test_renew_refuses_what_record_refuses(client, app, item):
    r = renew(client, item, drive_id="terms")
    assert r.status_code == 400 and "already on the item" in r.text
    r = send(client, f"/api/items/{item.id}/renew/preview", body("terms"))
    assert r.status_code == 400 and "already on the item" in r.text
    assert renew(client, item, drive_id="unknown").status_code == 404
    unchanged(app, item)


def test_renew_refuses_an_item_of_another_tray(client, app, item):
    other = app.trays.create("to-pay", ["new"], {}, None)
    r = send(client, f"/api/items/{other.id}/renew/preview", body(None))
    assert r.status_code == 400 and "Renewed" in r.text


def test_history_shows_the_renewal_and_its_undo(client, app, item):
    batch_id = renew(client, item, drive_id=None).json()["batch_id"]
    assert send(client, "/api/renewals/undo", {"batch_id": batch_id}).status_code == 200
    r = client.get(f"/api/items/{item.id}/history")
    assert r.status_code == 200, r.text
    renewed = [e for e in r.json() if e["kind"] == "renewed"]
    assert renewed[0]["data"]["new_date"] == NEW_DATE.isoformat()
    assert renewed[0]["data"]["batch_id"] == batch_id
    assert renewed[1]["data"] == {"undo": True, "batch_id": batch_id}
