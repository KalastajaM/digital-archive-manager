"""The File N marked batch: one row per inbox file with a filing code (``dam.codes.batch``)."""

import pytest
from fastapi.testclient import TestClient

from dam.api import create_api
from dam.codes.batch import marked_rows
from dam.config import SpecialFolders
from dam.ops.model import GuardError
from dam.services.errors import InvalidRequest
from test_api import BASE, LOCAL_ORIGIN
from test_codes_apply import add_in
from test_inbox import NORTHPOWER_BILL, add_rule

INBOX = SpecialFolders().inbox
NO_DUE_DATE = "Northpower Oy lasku\nYhteensä 84,20 €"
BANKS = "10. Financial/Northpower"


def rows_by_id(app):
    return {r.drive_id: r for r in marked_rows(app)}


def test_tray_code_row_has_tray_fields(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_in(app, fake_archive, f"{INBOX}/To pay/bill.pdf", "b1", NORTHPOWER_BILL)
    [row] = marked_rows(app)
    assert row.drive_id == "b1"
    assert [h.code for h in row.codes] == ["P"]
    assert row.request.tray == "to-pay"
    assert row.request.folder == BANKS
    assert row.tray_fields["due_date"] == "2026-11-15"
    assert row.tray_fields["amount"] == "84.20"
    assert row.request.tray_fields == row.tray_fields
    assert row.flag is None
    assert row.problem is None


def test_missing_due_date_needs_input(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_in(app, fake_archive, f"{INBOX}/To pay/bill.pdf", "b1", NO_DUE_DATE)
    [row] = marked_rows(app)
    assert row.flag == "needs_input"
    assert "due date" in row.problem
    # shown empty, sent empty: filing cannot fill in a value the row did not show
    assert row.tray_fields["due_date"] == ""
    assert row.request.tray_fields == row.tray_fields


def test_as_suggested_without_folder_needs_input(app, fake_archive):
    add_in(app, fake_archive, f"{INBOX}/File as suggested/scan.pdf", "f1", "nothing known")
    [row] = marked_rows(app)
    assert row.flag == "needs_input"
    assert row.problem == "folder"
    assert row.request.tray is None
    assert row.request.folder == ""
    with pytest.raises((InvalidRequest, GuardError)):
        app.inbox.preview([row.request])


def test_unmarked_inbox_file_gives_no_row(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_in(app, fake_archive, f"{INBOX}/bill.pdf", "b0", NORTHPOWER_BILL)
    assert marked_rows(app) == []


def test_preview_refusal_needs_input(app, fake_archive):
    # a rule folder inside the quarantine: the request is refused before anything moves
    add_rule(app, folder=SpecialFolders().quarantine)
    add_in(app, fake_archive, f"{INBOX}/File as suggested/bill.pdf", "f1", NORTHPOWER_BILL)
    [row] = marked_rows(app)
    assert row.flag == "needs_input"
    assert row.problem


def test_batch_flags_name_clash(app, fake_archive):
    add_rule(app, folder=BANKS, name="{doc_date:%Y%m%d}_Northpower")
    add_in(app, fake_archive, f"{INBOX}/File as suggested/a.pdf", "f1", NORTHPOWER_BILL)
    add_in(app, fake_archive, f"{INBOX}/File as suggested/b.pdf", "f2", NORTHPOWER_BILL)
    rows = marked_rows(app)
    assert [r.request.name for r in rows] == ["20261115_Northpower.pdf"] * 2
    first, second = rows
    assert first.flag is None
    assert second.flag == "needs_input"
    assert "20261115_Northpower.pdf" in second.problem


def test_name_clash_found_in_pairs_when_the_batch_is_refused(app, fake_archive, monkeypatch):
    add_rule(app, folder=BANKS, name="{doc_date:%Y%m%d}_Northpower")
    other_day = NORTHPOWER_BILL.replace("15.11.2026", "16.11.2026")
    add_in(app, fake_archive, f"{INBOX}/File as suggested/a.pdf", "f1", NORTHPOWER_BILL)
    add_in(app, fake_archive, f"{INBOX}/File as suggested/b.pdf", "f2", NORTHPOWER_BILL)
    add_in(app, fake_archive, f"{INBOX}/File as suggested/c.pdf", "f3", other_day)
    real = app.inbox.preview

    def refuse_big(reqs, *args, **kwargs):
        if len(reqs) >= 3:
            raise InvalidRequest("refused as a whole")
        return real(reqs, *args, **kwargs)

    monkeypatch.setattr(app.inbox, "preview", refuse_big)
    rows = rows_by_id(app)
    assert rows["f3"].request.name == "20261116_Northpower.pdf"
    assert rows["f3"].flag is None
    # f1 and f2 take the same name: whichever comes later is flagged, the other is not
    flagged = [d for d in ("f1", "f2") if rows[d].flag is not None]
    assert len(flagged) == 1
    assert rows[flagged[0]].flag == "needs_input"
    assert "20261115_Northpower.pdf" in rows[flagged[0]].problem


def test_invalid_code_gives_no_row(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_in(app, fake_archive, f"{INBOX}/To pay/bill.pdf", "b1", NORTHPOWER_BILL)
    assert [r.drive_id for r in marked_rows(app)] == ["b1"]
    # the To pay tray is deleted by hand: code P names an unknown tray and is skipped
    (app.trays_dir / "10-to-pay.yaml").unlink()
    app.reload_rules()
    assert [p.code for p in app.code_problems] == ["P"]
    assert "b1" not in rows_by_id(app)


def test_file_ticked_rows_is_one_undoable_batch(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_in(app, fake_archive, f"{INBOX}/To pay/one.pdf", "b1", NORTHPOWER_BILL)
    add_in(app, fake_archive, f"{INBOX}/To pay/two.pdf", "b2", NORTHPOWER_BILL)
    with TestClient(create_api(app), base_url=BASE) as client:
        rows = client.get("/api/filing-codes/batch").json()
        assert {r["drive_id"] for r in rows} == {"b1", "b2"}
        assert all(r["flag"] is None for r in rows)
        requests = [r["request"] for r in rows]
        r = client.post("/api/inbox/preview", json=requests, headers=LOCAL_ORIGIN)
        assert r.status_code == 200, r.text
        r = client.post("/api/inbox/file", json={"requests": requests}, headers=LOCAL_ORIGIN)
        assert r.status_code == 200, r.text
        out = r.json()
    assert sorted(op["drive_id"] for op in out["done"] if op["kind"] == "move") == ["b1", "b2"]
    assert len(out["items"]) == 2
    assert out["follow_up_error"] is None
    items = app.trays.list("to-pay", "open")
    assert sorted(f for i in items for f in i.files) == ["b1", "b2"]
    assert all(i.fields["due_date"] is not None for i in items)
    assert app.repo.get("b1").path.startswith(BANKS + "/")

    undone = app.activity.undo(out["batch_id"])
    assert undone.follow_up_error is None
    assert app.repo.get("b1").path == f"{INBOX}/To pay/one.pdf"
    assert app.repo.get("b2").path == f"{INBOX}/To pay/two.pdf"
    assert app.trays.list("to-pay", "open") == []
    assert {r.drive_id for r in marked_rows(app)} == {"b1", "b2"}


def test_today_marked_count(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_in(app, fake_archive, f"{INBOX}/To pay/bill.pdf", "b1", NORTHPOWER_BILL)
    add_in(app, fake_archive, f"{INBOX}/To pay/late.pdf", "b2", NO_DUE_DATE)  # needs input
    add_in(app, fake_archive, f"{INBOX}/plain.pdf", "p1", NORTHPOWER_BILL)  # no code
    with TestClient(create_api(app), base_url=BASE) as client:
        today = client.get("/api/today").json()
    assert today["marked"] == 2
    assert today["inbox_stats"]["count"] == 3
