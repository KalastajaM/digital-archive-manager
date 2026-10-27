"""Filing codes the owner assigns to inbox files in the app (``dam.codes.assigned``)."""

import pytest

from dam.codes.assigned import assign_code
from dam.codes.batch import marked_rows
from dam.codes.qr_model import QrRead
from dam.config import SpecialFolders
from dam.errors import InvalidRequest, NotFound
from test_api import LOCAL_ORIGIN, make_client
from test_codes_apply import add_in
from test_codes_qr_batch import file_rows, stick
from test_inbox import NORTHPOWER_BILL, add_rule

INBOX = SpecialFolders().inbox
BANKS = "10. Financial/Northpower"


def hits(found):
    return [(h.code, h.via, h.overridden) for h in found.codes]


def test_assigned_code_fills_suggestion_and_batch(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_in(app, fake_archive, f"{INBOX}/bill.pdf", "b1", NORTHPOWER_BILL)
    assert marked_rows(app) == []
    assert assign_code(app, ["b1"], "p") == "P"
    found = app.inbox.suggestion("b1")
    assert hits(found) == [("P", "assigned", False)]
    assert found.tray == "to-pay"
    assert found.tray_source == "code:P"
    [row] = marked_rows(app)
    assert row.codes[0].via == "assigned"
    assert row.request.tray == "to-pay"
    assert row.flag is None


def test_assigning_another_replaces_it_and_none_removes_it(app, fake_archive):
    add_in(app, fake_archive, f"{INBOX}/bill.pdf", "b1", NORTHPOWER_BILL)
    assign_code(app, ["b1"], "P")
    assign_code(app, ["b1"], "R")
    assert hits(app.inbox.suggestion("b1")) == [("R", "assigned", False)]
    assign_code(app, ["b1"], None)
    assert app.inbox.suggestion("b1").codes == []


def test_assigned_code_overrides_folder_without_conflict(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_in(app, fake_archive, f"{INBOX}/To pay/bill.pdf", "b1", NORTHPOWER_BILL)
    assign_code(app, ["b1"], "D")  # file as suggested: no tray, against the folder's P
    found = app.inbox.suggestion("b1")
    assert hits(found) == [("D", "assigned", False), ("P", "folder", True)]
    assert found.conflict is False
    assert found.tray is None
    assert found.folder == BANKS
    [row] = marked_rows(app)
    assert row.flag is None


def test_assigned_code_overrides_sticker_but_keeps_its_tick_boxes(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_in(app, fake_archive, f"{INBOX}/bill.pdf", "b1", NORTHPOWER_BILL)
    stick(app, "b1", QrRead("P", 1, "ticked", "empty"))
    assign_code(app, ["b1"], "R")
    found = app.inbox.suggestion("b1")
    assert hits(found) == [("R", "assigned", False), ("P", "qr", True)]
    assert found.tray == "to-read"
    assert found.star is True and found.important is False


def test_removing_it_brings_the_other_codes_back(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_in(app, fake_archive, f"{INBOX}/To pay/bill.pdf", "b1", NORTHPOWER_BILL)
    stick(app, "b1", QrRead("D", 0))
    assert app.inbox.suggestion("b1").conflict is True
    assign_code(app, ["b1"], "P")
    assert app.inbox.suggestion("b1").conflict is False
    assign_code(app, ["b1"], None)
    found = app.inbox.suggestion("b1")
    assert found.conflict is True
    assert [h.overridden for h in found.codes] == [False, False]


def test_code_no_longer_in_the_table_sets_nothing_and_overrides_nothing(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_in(app, fake_archive, f"{INBOX}/To pay/bill.pdf", "b1", NORTHPOWER_BILL)
    assign_code(app, ["b1"], "R")
    assert app.save_codes([c for c in app.codes if c.code != "R"]) == []
    found = app.inbox.suggestion("b1")
    assert hits(found) == [("R", "assigned", False), ("P", "folder", False)]
    assert found.tray == "to-pay"
    [row] = marked_rows(app)
    assert [h.code for h in row.codes] == ["P"]


def test_refusals_change_nothing(app, fake_archive):
    add_in(app, fake_archive, f"{INBOX}/bill.pdf", "b1", NORTHPOWER_BILL)
    add_in(app, fake_archive, f"{BANKS}/old.pdf", "b2", NORTHPOWER_BILL)
    with pytest.raises(InvalidRequest, match="unknown filing code"):
        assign_code(app, ["b1"], "ZZ")
    with pytest.raises(InvalidRequest, match="not in the inbox"):
        assign_code(app, ["b1", "b2"], "P")
    with pytest.raises(NotFound):
        assign_code(app, ["b1", "nope"], "P")
    with pytest.raises(InvalidRequest, match="no files"):
        assign_code(app, [], "P")
    assert app.repo.assigned_code("b1") is None


def test_kept_after_filing_and_back_with_undo(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_in(app, fake_archive, f"{INBOX}/bill.pdf", "b1", NORTHPOWER_BILL)
    assign_code(app, ["b1"], "R")
    [row] = marked_rows(app)
    out = file_rows(app, [row])
    rec = app.repo.get("b1")
    assert rec.path.startswith(BANKS + "/")
    # outside the inbox it routes nothing
    assert app.inbox.suggestion("b1").codes == []
    app.activity.undo(out["batch_id"])
    assert hits(app.inbox.suggestion("b1")) == [("R", "assigned", False)]


def test_api_assigns_and_refuses(app, fake_archive):
    add_in(app, fake_archive, f"{INBOX}/one.pdf", "b1", NORTHPOWER_BILL)
    add_in(app, fake_archive, f"{INBOX}/two.pdf", "b2", NORTHPOWER_BILL)
    with make_client(app) as c:
        body = {"drive_ids": ["b1", "b2", "b1"], "code": "a"}
        r = c.put("/api/filing-codes/assigned", json=body, headers=LOCAL_ORIGIN)
        assert r.status_code == 200, r.text
        assert r.json() == {"drive_ids": ["b1", "b2"], "code": "A"}
        rows = c.get("/api/filing-codes/batch").json()
        assert [h["via"] for r in rows for h in r["codes"]] == ["assigned", "assigned"]
        assert rows[0]["codes"][0]["overridden"] is False
        body = {"drive_ids": ["b1"], "code": "ZZ"}
        r = c.put("/api/filing-codes/assigned", json=body, headers=LOCAL_ORIGIN)
        assert r.status_code == 400
        body = {"drive_ids": ["nope"], "code": None}
        r = c.put("/api/filing-codes/assigned", json=body, headers=LOCAL_ORIGIN)
        assert r.status_code == 404
        body = {"drive_ids": ["b1"], "code": None}
        r = c.put("/api/filing-codes/assigned", json=body, headers=LOCAL_ORIGIN)
        assert r.status_code == 200
    assert app.repo.assigned_code("b1") is None
    assert app.repo.assigned_code("b2") == "A"
