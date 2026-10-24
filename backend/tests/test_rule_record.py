"""The track record of what each learned rule suggested and what the user kept."""

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
