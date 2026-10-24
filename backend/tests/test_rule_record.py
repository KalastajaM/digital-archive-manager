"""The track record of what each learned rule suggested and what the user kept."""

from dam.rules.model import Rule
from dam.services.rule_record import RuleRecord
from test_api import BANKS, INBOX, make_client, post, req


def test_stats_count_filings_and_changes(engine):
    rr = RuleRecord(engine)
    rr.record("b1", "d1", [("r1", "folder", True), ("r1", "name", True)])
    rr.record("b2", "d2", [("r1", "folder", True), ("r1", "name", False)])
    rr.record("b3", "d3", [("r1", "folder", True)])
    stats = rr.stats()
    assert set(stats) == {"r1"}
    assert stats["r1"].suggested == 3
    assert stats["r1"].changed == 1
    assert stats["r1"].last_used is not None
    assert stats["r1"].flagged is False


def test_flagged_after_two_changes_in_last_five(engine):
    rr = RuleRecord(engine)
    for i, kept in enumerate([True, True, False, True, False]):
        rr.record(f"b{i}", f"d{i}", [("r1", "folder", kept)])
    assert rr.stats()["r1"].flagged is True


def test_tray_changes_do_not_flag(engine):
    rr = RuleRecord(engine)
    for i in range(3):
        rr.record(f"b{i}", f"d{i}", [("r1", "tray", False)])
    stats = rr.stats()["r1"]
    assert stats.changed == 3 and stats.flagged is False


def test_old_changes_fall_out_of_the_last_five(engine):
    rr = RuleRecord(engine)
    for i, kept in enumerate([False, False, True, True, True, True, True]):
        rr.record(f"b{i}", f"d{i}", [("r1", "name", kept)])
    assert rr.stats()["r1"].flagged is False


def test_undo_removes_the_batch_outcomes(app, fake_archive):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-1")
    app.scan()
    with make_client(app) as client:
        batch = post(
            client, "/api/inbox/file", {"requests": [req(folder=BANKS)], "dry_run": False}
        ).json()
        app.rule_record.record(batch["batch_id"], "id-1", [("r1", "folder", True)])
        assert "r1" in app.rule_record.stats()
        assert post(client, f"/api/activity/{batch['batch_id']}/undo").status_code == 200
    assert app.rule_record.stats() == {}


def test_last_documents_gives_the_newest_document_still_in_the_archive(app, fake_archive):
    fake_archive.add("Insurance/old.pdf", drive_id="d-old")
    fake_archive.add("Insurance/new.pdf", drive_id="d-new")
    fake_archive.add("Insurance/gone.pdf", drive_id="d-gone")
    app.scan()
    rr = app.rule_record
    rr.record("b1", "d-old", [("r1", "folder", True)])
    rr.record("b2", "d-new", [("r1", "folder", True)])
    rr.record("b3", "d-gone", [("r1", "folder", True)])
    rr.record("b4", "d-nowhere", [("r2", "folder", True)])  # not in the index at all
    (fake_archive.root / "Insurance" / "gone.pdf").unlink()
    app.scan()
    last = rr.last_documents()
    assert set(last) == {"r1"}
    assert (last["r1"].drive_id, last["r1"].name, last["r1"].ext) == ("d-new", "new.pdf", "pdf")
    # the rule list carries it for the editor; a rule never used has none
    app.save_rule(Rule.model_validate({"id": "r1", "when": {"text_contains": ["x"]}}))
    app.save_rule(Rule.model_validate({"id": "never", "when": {"text_contains": ["y"]}}))
    with make_client(app) as client:
        by_id = {r["id"]: r for r in client.get("/api/rules").json()["rules"]}
    assert by_id["r1"]["sample"] == {"drive_id": "d-new", "name": "new.pdf", "ext": "pdf"}
    assert by_id["never"]["sample"] is None
