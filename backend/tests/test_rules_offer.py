"""The offer to make a rule after a manual filing, and the outcome records."""

import pytest

from dam.rules.model import Rule
from dam.rules.state import RulesState, load_state, save_state
from test_api import make_client, post
from test_inbox import add_scan

TEXT = "Fortum Oyj sähkölasku\nEräpäivä 15.10.2026\nYhteensä 84,20 €"
BILLS = "11. Bills/2026"


@pytest.fixture
def client(app, fake_archive):
    for folder in (BILLS, "11. Bills/Other"):
        fake_archive.add(f"{folder}/old.txt", content=folder.encode(), drive_id=f"old-{folder}")
    app.scan()
    for p in app.rules_dir.glob("*.yaml"):
        p.unlink()
    app.reload_rules()
    with make_client(app) as c:
        yield c


def _file(client, name="20261015_Fortum.pdf", folder=BILLS, via=None):
    body = {"requests": [{"drive_id": "id-a", "name": name, "folder": folder, "tags": []}]}
    if via:
        body["via"] = via
    return post(client, "/api/inbox/file", body)


def _learned(app):
    app.save_rule(
        Rule(
            id="fortum",
            when={"text_contains": ["fortum"]},
            then={"folder": "11. Bills/{year}", "name": "{doc_date:%Y%m%d}_Fortum"},
        )
    )


def test_manual_filing_without_a_rule_offers_a_new_rule(client, app, fake_archive):
    add_scan(app, fake_archive, "lasku.pdf", "id-a", TEXT)
    r = _file(client)
    assert r.status_code == 200, r.text
    offer = r.json()["offer"]
    assert offer["kind"] == "new" and offer["rule_id"] is None
    assert offer["drive_id"] == "id-a"
    assert offer["draft"]["folder"] == "11. Bills/{year}"
    assert "fortum" in [w["word"] for w in offer["draft"]["words"] if w["ticked"]]


def test_changing_a_learned_rules_folder_offers_an_update(client, app, fake_archive):
    _learned(app)
    add_scan(app, fake_archive, "lasku.pdf", "id-a", TEXT)
    r = _file(client, name="20261015_Fortum.pdf", folder="11. Bills/Other")
    offer = r.json()["offer"]
    assert offer["kind"] == "update" and offer["rule_id"] == "fortum"
    stats = app.rule_record.stats()["fortum"]
    assert (stats.suggested, stats.changed) == (1, 1)


def test_kept_rule_suggestion_records_and_offers_nothing(client, app, fake_archive):
    _learned(app)
    add_scan(app, fake_archive, "lasku.pdf", "id-a", TEXT)
    r = _file(client)
    assert r.status_code == 200, r.text
    assert r.json()["offer"] is None
    stats = app.rule_record.stats()["fortum"]
    assert (stats.suggested, stats.changed) == (1, 0)


def test_no_offer_for_batches_codes_declined_or_switched_off(client, app, fake_archive):
    add_scan(app, fake_archive, "lasku.pdf", "id-a", TEXT)
    assert _file(client, via="batch").json()["offer"] is None
    # declined: the ticked-word set is remembered
    add_scan(app, fake_archive, "c.pdf", "id-a2", TEXT)
    save_state(app.app_paths.data_dir, RulesState(declined=[["fortum"]]))
    r = post(
        client,
        "/api/inbox/file",
        {"requests": [{"drive_id": "id-a2", "name": "x.pdf", "folder": BILLS, "tags": []}]},
    )
    assert r.json()["offer"] is None
    save_state(app.app_paths.data_dir, RulesState(offer=False))
    add_scan(app, fake_archive, "d.pdf", "id-a3", TEXT)
    r = post(
        client,
        "/api/inbox/file",
        {"requests": [{"drive_id": "id-a3", "name": "y.pdf", "folder": BILLS, "tags": []}]},
    )
    assert r.json()["offer"] is None
    save_state(app.app_paths.data_dir, RulesState())
    add_scan(app, fake_archive, "e.pdf", "id-a4", TEXT)
    r = post(
        client,
        "/api/inbox/file",
        {
            "via": "codes",
            "requests": [{"drive_id": "id-a4", "name": "z.pdf", "folder": BILLS, "tags": []}],
        },
    )
    assert r.json()["offer"] is None


def test_codes_filing_records_nothing(client, app, fake_archive):
    _learned(app)
    add_scan(app, fake_archive, "lasku.pdf", "id-a", TEXT)
    assert _file(client, via="codes").status_code == 200
    assert "fortum" not in app.rule_record.stats()


def test_unknown_via_is_refused(client):
    assert _file(client, via="magic").status_code == 422


def test_state_defaults_and_roundtrip(tmp_path):
    assert load_state(tmp_path) == RulesState()
    (tmp_path / "rules-state.json").write_text("not json", encoding="utf-8")
    assert load_state(tmp_path) == RulesState()
    save_state(tmp_path, RulesState(offer=False, declined=[["a", "b"]]))
    assert load_state(tmp_path) == RulesState(offer=False, declined=[["a", "b"]])
