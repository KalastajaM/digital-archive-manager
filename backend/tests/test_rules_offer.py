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


def _offer_for(client, app, fake_archive, via=None):
    add_scan(app, fake_archive, "lasku.pdf", "id-a", TEXT)
    return _file(client, via=via).json()["offer"]


def test_no_offer_for_a_batch_filing_but_outcomes_are_recorded(client, app, fake_archive):
    _learned(app)
    add_scan(app, fake_archive, "lasku.pdf", "id-a", TEXT)
    r = _file(client, via="batch", folder="11. Bills/Other")
    assert r.json()["offer"] is None
    stats = app.rule_record.stats()["fortum"]
    assert (stats.suggested, stats.changed) == (1, 1)


def test_the_same_filing_via_the_form_offers(client, app, fake_archive):
    assert _offer_for(client, app, fake_archive, via="form")["kind"] == "new"


def test_no_offer_for_a_codes_filing(client, app, fake_archive):
    assert _offer_for(client, app, fake_archive, via="codes") is None


def test_a_declined_word_set_is_not_offered_again(client, app, fake_archive):
    save_state(app.app_paths.data_dir, RulesState(declined=[["other"]]))
    assert _offer_for(client, app, fake_archive) is not None  # control: another set
    fake_archive.add(f"{BILLS}/old2.txt", content=b"2", drive_id="old-2")
    add_scan(app, fake_archive, "lasku2.pdf", "id-b", TEXT)
    save_state(app.app_paths.data_dir, RulesState(declined=[["fortum"]]))
    body = {"requests": [{"drive_id": "id-b", "name": "n.pdf", "folder": BILLS, "tags": []}]}
    assert post(client, "/api/inbox/file", body).json()["offer"] is None


def test_no_offer_when_switched_off(client, app, fake_archive):
    save_state(app.app_paths.data_dir, RulesState(offer=False))
    assert _offer_for(client, app, fake_archive) is None
    # control: the same filing with the offer on
    add_scan(app, fake_archive, "lasku2.pdf", "id-b", TEXT)
    save_state(app.app_paths.data_dir, RulesState())
    body = {"requests": [{"drive_id": "id-b", "name": "n.pdf", "folder": BILLS, "tags": []}]}
    assert post(client, "/api/inbox/file", body).json()["offer"] is not None


def test_no_offer_for_two_requests_in_one_filing(client, app, fake_archive):
    add_scan(app, fake_archive, "a.pdf", "id-a", TEXT)
    add_scan(app, fake_archive, "b.pdf", "id-b", TEXT)
    body = {
        "requests": [
            {"drive_id": "id-a", "name": "a1.pdf", "folder": BILLS, "tags": []},
            {"drive_id": "id-b", "name": "b1.pdf", "folder": BILLS, "tags": []},
        ]
    }
    assert post(client, "/api/inbox/file", body).json()["offer"] is None


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


def test_no_offer_when_a_kept_folder_or_name_came_from_a_filing_code(tmp_path):
    from dam.rules.engine import Suggestion
    from dam.rules.offer import offer_target

    by_code = Suggestion(name="x.pdf", folder=BILLS, folder_source="code:PAY")
    assert offer_target(by_code, "other.pdf", BILLS, tmp_path)[0] is False
    named = Suggestion(name="20261015_PAY.pdf", name_source="code:PAY")
    assert offer_target(named, "20261015_PAY.pdf", "11. Bills/Other", tmp_path)[0] is False
    # control: the owner changed what the code gave, so the offer stands
    assert offer_target(by_code, "other.pdf", "11. Bills/Other", tmp_path)[0] is True
