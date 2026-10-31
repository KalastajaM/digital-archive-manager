"""Renewing from the Inbox (Task 6): a filing request with ``renews`` files the new
document and renews the item in one batch with one Undo; the candidates route feeds the
Inbox's "Renews …?" suggestion."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from dam.api import create_api
from dam.config import Person
from dam.errors import InvalidRequest
from dam.locks import LOCKED_MESSAGE, with_tokens
from dam.ops.model import GuardError
from dam.services.inbox import FileRequest
from test_inbox import INBOX, add_scan

BANKS = "10. Financial/Banks"
OLD = f"{BANKS}/passport-old.pdf"
EXPIRED = f"{BANKS}/Expired/passport-old.pdf"
BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}
OLD_DATE = date(2027, 6, 30)
NEW_DATE = date(2037, 6, 30)


@pytest.fixture
def item(app, fake_archive):
    fake_archive.add(OLD, drive_id="old")
    fake_archive.add(f"{BANKS}/terms.pdf", drive_id="terms")
    add_scan(app, fake_archive, "scan.pdf", "new", "passport")
    return app.trays.create(
        "renew", ["old", "terms"], {"expires": OLD_DATE.isoformat(), "kind": "Passport"}, None
    )


@pytest.fixture
def client(app):
    with TestClient(create_api(app), base_url=BASE) as c:
        yield c


def at(fake_archive, rel):
    return (fake_archive.root / rel).exists()


def req(item, **kw):
    args = {"renews": item.id, "renew_expires": NEW_DATE}
    args.update(kw)
    return FileRequest("new", "passport-2037.pdf", BANKS, **args)


def unchanged(app, item, fake_archive):
    after = app.trays.get(item.id)
    assert after.files == ["old", "terms"] and after.date == OLD_DATE
    assert [e for e in app.trays.history(item.id) if e.kind == "renewed"] == []
    assert at(fake_archive, OLD) and at(fake_archive, f"{INBOX}/scan.pdf")


def test_candidates_list_folder_person_locked(client, app, item):
    app.settings.people = [Person(name="Tiina", match=["Tiina Visser"])]
    app.assignments.set(["old"], person="Tiina")
    app.trays.create("to-pay", ["terms"], {}, None)  # not a tray with renew
    done = app.trays.create("renew", ["new"], {"expires": "2030-01-01"}, None)
    app.trays.done(done.id, {})
    r = client.get("/api/renewals/open")
    assert r.status_code == 200, r.text
    assert r.json() == [
        {
            "item_id": item.id,
            "title": item.title,
            "drive_id": "old",
            "expires": OLD_DATE.isoformat(),
            "kind": "Passport",
            "folder": BANKS,
            "person": "Tiina",
            "locked": False,
        }
    ]
    app.marks.mark_important(["old"], None)
    token = app.locks.grant("old")
    r = client.get("/api/renewals/open", headers={"X-Dam-Unlock": token})
    # the stored state: a grant does not make it unlocked
    assert r.json()[0]["locked"] is True


def test_filing_with_renews_moves_old_and_records(app, item, fake_archive):
    ops = app.inbox.preview([req(item)])
    assert [(o.kind.value, o.src, o.dst) for o in ops] == [
        ("mkdir", None, f"{BANKS}/Expired"),
        ("move", OLD, EXPIRED),
        ("move", f"{INBOX}/scan.pdf", f"{BANKS}/passport-2037.pdf"),
    ]
    out = app.inbox.file_it([req(item)])
    assert out.batch.error is None and out.follow_up_error is None
    assert out.renew_skipped is None
    assert out.renew_batch == out.batch.batch_id and out.renew_undo == "activity"
    assert at(fake_archive, f"{BANKS}/passport-2037.pdf")
    assert at(fake_archive, EXPIRED) and not at(fake_archive, OLD)
    after = app.trays.get(item.id)
    assert after.files == ["new", "terms"] and after.date == NEW_DATE
    (ev,) = [e for e in app.trays.history(item.id) if e.kind == "renewed"]
    assert ev.data["batch_id"] == out.batch.batch_id
    assert ev.data["moved"] is True and ev.data["expired"] == "Expired"
    assert out.items == []


def test_one_undo_reverses_filing_and_renewal(app, item, fake_archive):
    app.marks.star(["old"])
    out = app.inbox.file_it([req(item)])
    assert app.marks.marks_for(["old", "new"]) == {"old": [], "new": ["starred"]}
    undone = app.activity.undo(out.batch.batch_id)
    assert undone.batch.error is None and undone.follow_up_error is None
    assert at(fake_archive, OLD) and at(fake_archive, f"{INBOX}/scan.pdf")
    assert not at(fake_archive, f"{BANKS}/passport-2037.pdf")
    after = app.trays.get(item.id)
    assert after.files == ["old", "terms"] and after.date == OLD_DATE
    assert app.marks.marks_for(["old", "new"]) == {"old": ["starred"], "new": []}


def test_renews_needs_date(app, item, fake_archive):
    for call in (app.inbox.preview, app.inbox.file_it):
        with pytest.raises(InvalidRequest, match="new expiry"):
            call([req(item, renew_expires=None)])
    with pytest.raises(InvalidRequest, match="without"):
        app.inbox.preview([FileRequest("new", "a.pdf", BANKS, renew_expires=NEW_DATE)])
    unchanged(app, item, fake_archive)


def test_renews_done_item_refused(app, item, fake_archive):
    app.trays.done(item.id, {})
    for call in (app.inbox.preview, app.inbox.file_it):
        with pytest.raises(InvalidRequest, match="reopen it"):
            call([req(item)])
    assert at(fake_archive, OLD) and at(fake_archive, f"{INBOX}/scan.pdf")


def test_renews_refuses_what_a_renewal_refuses(app, item, fake_archive):
    other = app.trays.create("to-pay", ["new"], {}, None)
    with pytest.raises(InvalidRequest, match="Renewed"):
        app.inbox.preview([req(other)])
    with pytest.raises(InvalidRequest, match="another open item"):
        app.inbox.preview([req(item)])
    unchanged(app, item, fake_archive)


def test_renews_one_item_twice_refused(app, item, fake_archive):
    add_scan(app, fake_archive, "scan2.pdf", "new2", "passport")
    second = FileRequest("new2", "b.pdf", BANKS, renews=item.id, renew_expires=NEW_DATE)
    with pytest.raises(InvalidRequest, match="twice"):
        app.inbox.file_it([req(item), second])
    unchanged(app, item, fake_archive)


def test_locked_old_without_grant_refused(app, item, fake_archive):
    app.marks.mark_important(["old"], None)
    for call in (app.inbox.preview, app.inbox.file_it):
        with pytest.raises(GuardError, match=LOCKED_MESSAGE.split(".")[0]):
            call([req(item)])
    unchanged(app, item, fake_archive)


def test_locked_old_with_grant_files_and_moves(app, item, fake_archive):
    app.marks.mark_important(["old"], None)
    with with_tokens([app.locks.grant("old")]):
        out = app.inbox.file_it([req(item)])
    assert out.batch.error is None
    assert at(fake_archive, EXPIRED)
    assert app.trays.get(item.id).files == ["new", "terms"]


def test_old_file_gone_files_and_records(app, item, fake_archive):
    (fake_archive.root / OLD).unlink()
    app.scan()
    out = app.inbox.file_it([req(item)])
    assert out.renew_skipped == "The old file is no longer in the archive"
    assert out.renew_batch == out.batch.batch_id and out.renew_undo == "activity"
    assert at(fake_archive, f"{BANKS}/passport-2037.pdf")
    assert app.trays.get(item.id).files == ["new", "terms"]
    (ev,) = [e for e in app.trays.history(item.id) if e.kind == "renewed"]
    assert ev.data["moved"] is False and ev.data["expired"] is None
    app.activity.undo(out.batch.batch_id)
    assert app.trays.get(item.id).files == ["old", "terms"]


def test_no_ops_gets_its_own_batch(app, item, fake_archive):
    (fake_archive.root / OLD).unlink()
    app.scan()
    out = app.inbox.file_it([FileRequest("new", "scan.pdf", INBOX, **_renew(item))])
    assert out.batch.done == []
    assert out.renew_batch and out.renew_undo == "renewal"
    assert app.trays.get(item.id).files == ["new", "terms"]
    app.renewals.undo(out.renew_batch)
    assert app.trays.get(item.id).date == OLD_DATE


def test_renews_skips_the_tray_step(app, item, fake_archive):
    out = app.inbox.file_it([req(item, tray="to-read")])
    assert out.items == [] and app.trays.list("to-read") == []
    assert app.trays.get(item.id).files == ["new", "terms"]


def test_wire_format(client, app, item, fake_archive):
    body = {
        "requests": [
            {
                "drive_id": "new",
                "name": "passport-2037.pdf",
                "folder": BANKS,
                "renews": item.id,
                "renew_expires": NEW_DATE.isoformat(),
            }
        ]
    }
    r = client.post("/api/inbox/file", json=body, headers=LOCAL_ORIGIN)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["renew_undo"] == "activity" and out["renew_batch"] == out["batch_id"]
    assert out["renew_skipped"] is None
    assert app.trays.get(item.id).date == NEW_DATE


def _renew(item):
    return {"renews": item.id, "renew_expires": NEW_DATE}


def test_a_failed_renewal_reports_no_renew_undo(app, item, fake_archive, monkeypatch):
    # the item is marked done after the filing's checks, so the renewal itself refuses it
    renewals = app.inbox.renewals
    original = renewals.record

    def done_first(*args, **kwargs):
        app.trays.done(item.id, {})
        return original(*args, **kwargs)

    monkeypatch.setattr(renewals, "record", done_first)
    out = app.inbox.file_it([req(item)])
    assert out.batch.error is None
    assert out.follow_up_error is not None
    assert out.renew_undo is None and out.renew_batch is None and out.renew_skipped is None
    assert [e for e in app.trays.history(item.id) if e.kind == "renewed"] == []


def test_new_file_takes_the_old_files_name(app, fake_archive):
    # the old file moves out first, so the new one gets the name the owner chose
    old = f"{BANKS}/Passport.pdf"
    fake_archive.add(old, drive_id="old")
    add_scan(app, fake_archive, "scan.pdf", "new", "passport")
    item = app.trays.create("renew", ["old"], {"expires": OLD_DATE.isoformat()}, None)
    request = FileRequest("new", "Passport.pdf", BANKS, **_renew(item))
    ops = app.inbox.preview([request])
    assert [(o.kind.value, o.src, o.dst) for o in ops] == [
        ("mkdir", None, f"{BANKS}/Expired"),
        ("move", old, f"{BANKS}/Expired/Passport.pdf"),
        ("move", f"{INBOX}/scan.pdf", old),
    ]
    out = app.inbox.file_it([request])
    assert out.batch.error is None and out.follow_up_error is None
    assert at(fake_archive, f"{BANKS}/Expired/Passport.pdf") and at(fake_archive, old)
    assert app.repo.get("new").path == old
    assert app.trays.get(item.id).files == ["new"]
    undone = app.activity.undo(out.batch.batch_id)
    assert undone.batch.error is None
    assert app.repo.get("old").path == old and at(fake_archive, f"{INBOX}/scan.pdf")
    assert not at(fake_archive, f"{BANKS}/Expired/Passport.pdf")
    assert app.trays.get(item.id).files == ["old"]
