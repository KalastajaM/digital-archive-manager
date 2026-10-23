"""QR sticker hits and their tick boxes in the suggestion and the File N marked batch."""

from fastapi.testclient import TestClient

from dam.api import create_api
from dam.codes.batch import marked_rows
from dam.codes.qr_model import QrRead
from dam.config import SpecialFolders
from dam.extract.base import ExtractedText
from test_api import BASE, LOCAL_ORIGIN
from test_codes_apply import add_in, set_code
from test_inbox import NORTHPOWER_BILL, add_rule

INBOX = SpecialFolders().inbox
BANKS = "10. Financial/Northpower"


def stick(app, drive_id, *reads):
    """Record ``reads`` as the stickers found on the file's (fake) content."""
    sha = f"sha-{drive_id}"
    text = ExtractedText(app.repo.text_for(drive_id), "test")
    app.repo.save_content(drive_id, sha, text, "indexed")
    assert app.repo.save_qr(drive_id, sha, list(reads)) is True


def file_rows(app, rows):
    """File the rows through the API, as the batch panel does."""
    with TestClient(create_api(app), base_url=BASE) as client:
        requests = [r["request"] for r in client.get("/api/filing-codes/batch").json()]
        assert {r["drive_id"] for r in requests} == {r.drive_id for r in rows}
        r = client.post("/api/inbox/file", json={"requests": requests}, headers=LOCAL_ORIGIN)
        assert r.status_code == 200, r.text
        return r.json()


def test_qr_hit_fills_suggestion(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_in(app, fake_archive, f"{INBOX}/bill.pdf", "b1", NORTHPOWER_BILL)
    stick(app, "b1", QrRead("P", 0))
    found = app.inbox.suggestion("b1")
    assert found.tray == "to-pay"
    assert found.tray_source == "code:P"
    assert [(h.code, h.via, h.raw) for h in found.codes] == [("P", "qr", "P")]
    assert found.star is None and found.important is None
    assert found.marks_unclear is False
    [row] = marked_rows(app)
    assert row.codes[0].via == "qr"
    assert row.request.tray == "to-pay"
    assert row.request.star is False and row.request.important is False
    assert row.flag is None


def test_folder_and_sticker_same_code_is_one_code_two_hits(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_in(app, fake_archive, f"{INBOX}/To pay/bill.pdf", "b1", NORTHPOWER_BILL)
    stick(app, "b1", QrRead("P", 0), QrRead("P", 1, "empty", "empty"))
    found = app.inbox.suggestion("b1")
    assert [(h.code, h.via) for h in found.codes] == [("P", "folder"), ("P", "qr")]
    assert found.conflict is False
    assert found.sources.count("code:P") == 1
    [row] = marked_rows(app)
    assert row.flag is None
    assert found.star is False and found.important is False


def test_ticked_star_files_starred(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_in(app, fake_archive, f"{INBOX}/bill.pdf", "b1", NORTHPOWER_BILL)
    stick(app, "b1", QrRead("P", 1, "ticked", "empty"))
    found = app.inbox.suggestion("b1")
    assert found.star is True and found.important is False
    [row] = marked_rows(app)
    assert row.request.star is True and row.request.important is False
    assert row.flag is None
    out = file_rows(app, [row])
    assert out["follow_up_error"] is None
    assert app.marks.marks_for(["b1"]) == {"b1": ["starred"]}

    undone = app.activity.undo(out["batch_id"])
    assert undone.follow_up_error is None
    assert app.marks.marks_for(["b1"]) == {"b1": []}


def test_ticked_important_files_important(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_in(app, fake_archive, f"{INBOX}/bill.pdf", "b1", NORTHPOWER_BILL)
    stick(app, "b1", QrRead("P", 1, "empty", "ticked"))
    [row] = marked_rows(app)
    assert row.request.star is False and row.request.important is True
    out = file_rows(app, [row])
    assert out["follow_up_error"] is None
    assert app.marks.marks_for(["b1"]) == {"b1": ["important"]}

    app.activity.undo(out["batch_id"])
    assert app.marks.marks_for(["b1"]) == {"b1": []}


def test_undo_keeps_a_star_the_file_had_before(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_in(app, fake_archive, f"{INBOX}/bill.pdf", "b1", NORTHPOWER_BILL)
    app.marks.star(["b1"])
    stick(app, "b1", QrRead("P", 1, "ticked", "empty"))
    [row] = marked_rows(app)
    out = file_rows(app, [row])
    app.activity.undo(out["batch_id"])
    assert app.marks.marks_for(["b1"]) == {"b1": ["starred"]}


def test_star_and_important_without_sending_them_behave_as_before(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_in(app, fake_archive, f"{INBOX}/bill.pdf", "b1", NORTHPOWER_BILL)
    with TestClient(create_api(app), base_url=BASE) as client:
        req = {"drive_id": "b1", "name": "bill.pdf", "folder": BANKS}
        r = client.post("/api/inbox/file", json={"requests": [req]}, headers=LOCAL_ORIGIN)
        assert r.status_code == 200, r.text
    assert app.marks.marks_for(["b1"]) == {"b1": []}


def test_unclear_box_flags_row(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_in(app, fake_archive, f"{INBOX}/bill.pdf", "b1", NORTHPOWER_BILL)
    add_in(app, fake_archive, f"{INBOX}/two.pdf", "b2", NORTHPOWER_BILL)
    stick(app, "b1", QrRead("P", 1, "unclear", "empty"))
    stick(app, "b2", QrRead("P", 1, "empty", "unclear"))
    found = app.inbox.suggestion("b1")
    assert found.marks_unclear is True
    assert found.star is None and found.important is False
    rows = {r.drive_id: r for r in marked_rows(app)}
    assert rows["b1"].flag == "unclear"
    assert rows["b1"].problem == "Tick box unclear: star"
    assert rows["b2"].flag == "unclear"
    assert rows["b2"].problem == "Tick box unclear: important"


def test_ticked_on_another_sticker_beats_unclear(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_in(app, fake_archive, f"{INBOX}/bill.pdf", "b1", NORTHPOWER_BILL)
    stick(app, "b1", QrRead("P", 1, "unclear", "empty"), QrRead("P", 1, "ticked", "empty"))
    found = app.inbox.suggestion("b1")
    assert found.star is True and found.marks_unclear is False


def test_unknown_sticker_code_ignored(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_in(app, fake_archive, f"{INBOX}/bill.pdf", "b1", NORTHPOWER_BILL)
    stick(app, "b1", QrRead("ZZ", 1, "ticked", "unclear"))
    found = app.inbox.suggestion("b1")
    assert found.codes == []
    assert found.star is None and found.important is None
    assert found.marks_unclear is False
    assert marked_rows(app) == []


def test_folder_and_sticker_conflict(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_in(app, fake_archive, f"{INBOX}/To pay/bill.pdf", "b1", NORTHPOWER_BILL)
    stick(app, "b1", QrRead("A", 0))
    found = app.inbox.suggestion("b1")
    assert [(h.code, h.via) for h in found.codes] == [("P", "folder"), ("A", "qr")]
    assert found.conflict is True
    [row] = marked_rows(app)
    assert row.flag == "conflict"


def test_sticker_on_a_filed_document_suggests_nothing(app, fake_archive):
    set_code(app, "P", folder="Bills")
    add_in(app, fake_archive, f"{BANKS}/bill.pdf", "b1", NORTHPOWER_BILL)
    stick(app, "b1", QrRead("P", 1, "ticked", "ticked"))
    found = app.inbox.suggestion("b1")
    assert found.codes == []
    assert found.star is None and found.important is None


def test_api_shows_qr_hits_and_ticks(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_in(app, fake_archive, f"{INBOX}/bill.pdf", "b1", NORTHPOWER_BILL)
    stick(app, "b1", QrRead("P", 1, "ticked", "empty"))
    with TestClient(create_api(app), base_url=BASE) as client:
        [entry] = client.get("/api/inbox").json()
        [row] = client.get("/api/filing-codes/batch").json()
    s = entry["suggestion"]
    assert s["codes"][0]["via"] == "qr"
    assert (s["star"], s["important"], s["marks_unclear"]) == (True, False, False)
    assert (row["request"]["star"], row["request"]["important"]) == (True, False)
