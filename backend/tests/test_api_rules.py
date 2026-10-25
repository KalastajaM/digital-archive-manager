"""The rules API: list with stats, replay, save, delete, move, explain, offer state."""

import pytest

from dam.extract.base import ExtractedText
from dam.index.scanner import scan
from dam.rules.model import LEARNED_FILE, Rule
from dam.rules.state import load_state
from test_api import INBOX, LOCAL_ORIGIN, make_client, post


def rule_body(rule_id, text="fortum", folder="11. Bills/{year}", **extra):
    return {
        "id": rule_id,
        "when": {"text_contains": [text]},
        "then": {"folder": folder, "tags": ["bill"], **extra},
    }


def put(client, url, body):
    return client.put(url, json=body, headers=LOCAL_ORIGIN)


@pytest.fixture
def api(app):
    # a clean slate: the seeded example rules would only get in the way
    with make_client(app) as c:
        for r in list(app.rules):
            app.delete_rule(r.id)
        yield c


def ids(data):
    return [r["id"] for r in data["rules"]]


def test_list_has_stats_file_and_state(app, api):
    app.save_rule(Rule.model_validate(rule_body("a")))
    data = api.get("/api/rules").json()
    assert ids(data) == ["a"]
    r = data["rules"][0]
    assert (r["file"], r["learned"]) == (LEARNED_FILE, True)
    assert r["when"] == {
        "text_contains": ["fortum"],
        "filename_matches": None,
        "folder_is": None,
        "zones": [],
        "person": None,
    }
    assert r["then"]["tags"] == ["bill"]
    assert r["stats"] == {"suggested": 0, "changed": 0, "last_used": None, "flagged": False}
    assert data["errors"] == []
    assert data["state"] == {"offer": True, "declined": 0}


def test_list_marks_a_hand_written_file_and_reports_bad_files(app, api):
    (app.rules_dir / "mine.yaml").write_text(
        "- id: hand\n  when: {text_contains: [x]}\n  then: {tags: [t]}\n", encoding="utf-8"
    )
    (app.rules_dir / "bad.yaml").write_text("not: a list\n", encoding="utf-8")
    app.reload_rules()
    data = api.get("/api/rules").json()
    hand = next(r for r in data["rules"] if r["id"] == "hand")
    assert (hand["file"], hand["learned"]) == ("mine.yaml", False)
    assert [e["file"] for e in data["errors"]] == ["bad.yaml"]


def test_save_new_then_replace_keeps_position(app, api):
    assert ids(put(api, "/api/rules/a", rule_body("a")).json()) == ["a"]
    put(api, "/api/rules/b", rule_body("b", "other"))
    r = put(api, "/api/rules/a2?replaces=a", rule_body("a2", "changed"))
    assert r.status_code == 200, r.text
    assert ids(r.json()) == ["a2", "b"]
    assert r.json()["rules"][0]["when"]["text_contains"] == ["changed"]


def test_save_refuses_a_repeated_id_and_an_invalid_rule(app, api):
    put(api, "/api/rules/a", rule_body("a"))
    dup = put(api, "/api/rules/a", rule_body("a"))
    assert dup.status_code == 400 and "exists already" in dup.json()["error"]
    bad = put(api, "/api/rules/x", {"id": "x", "when": {"filename_matches": "("}})
    assert bad.status_code == 400 and "invalid regex" in bad.json()["error"]
    assert "Value error" not in bad.json()["error"]
    blank = put(api, "/api/rules/y", {"id": "y", "when": {"text_contains": [" "]}})
    assert blank.status_code == 400
    assert ids(api.get("/api/rules").json()) == ["a"]


def test_save_replacing_an_unknown_rule_is_404(api):
    assert put(api, "/api/rules/a?replaces=nope", rule_body("a")).status_code == 404


def test_delete_and_unknown_404(app, api):
    put(api, "/api/rules/a", rule_body("a"))
    put(api, "/api/rules/b", rule_body("b"))
    r = api.delete("/api/rules/a", headers=LOCAL_ORIGIN)
    assert r.status_code == 200 and ids(r.json()) == ["b"]
    assert api.delete("/api/rules/nope", headers=LOCAL_ORIGIN).status_code == 404


def test_move_and_refusal_for_a_hand_written_rule(app, api):
    for n in "abc":
        put(api, f"/api/rules/{n}", rule_body(n, n))
    r = post(api, "/api/rules/c/move", {"delta": -2})
    assert ids(r.json()) == ["c", "a", "b"]
    (app.rules_dir / "mine.yaml").write_text(
        "- id: hand\n  when: {text_contains: [x]}\n  then: {tags: [t]}\n", encoding="utf-8"
    )
    app.reload_rules()
    refused = post(api, "/api/rules/hand/move", {"delta": 1})
    assert refused.status_code == 400
    assert post(api, "/api/rules/nope/move", {"delta": 1}).status_code == 404


def add_filed(app, fake_archive, rel, drive_id, text):
    fake_archive.add(rel, content=drive_id.encode(), drive_id=drive_id)
    scan(app.paths, app.repo)
    app.repo.save_content(drive_id, None, ExtractedText(text, "test"), "indexed")


def test_replay_shape(app, api, fake_archive):
    add_filed(app, fake_archive, "11. Bills/2026/20260210_Fortum.pdf", "a", "Fortum")
    add_filed(app, fake_archive, "20. Home/20260301_Fortum.pdf", "b", "Fortum")
    body = {
        "rule": {
            "id": "fortum",
            "when": {"text_contains": ["fortum"]},
            "then": {"folder": "11. Bills/{year}", "name": "{doc_date:%Y%m%d}_Fortum"},
        }
    }
    r = post(api, "/api/rules/replay", body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert (data["matched"], data["same"], data["inbox"]) == (2, 1, 0)
    assert data["different"] == [
        {
            "drive_id": "b",
            "path_now": "20. Home/20260301_Fortum.pdf",
            "path_rule": "11. Bills/2026/20260301_Fortum.pdf",
        }
    ]
    assert data["shadowed"] == []
    assert (data["checked"], data["total"], data["truncated"]) == (2, 2, False)
    # replay changes nothing
    assert api.get("/api/rules").json()["rules"] == []


def test_replay_places_a_new_rule_after_the_learned_ones(app, api, fake_archive):
    add_filed(app, fake_archive, "11. Bills/2026/20260210_Fortum.pdf", "a", "Fortum invoice")
    app.save_rule(Rule.model_validate(rule_body("invoice", "invoice", "99. Misc")))
    (app.rules_dir / "zz.yaml").write_text(
        "- id: later\n  when: {text_contains: [x]}\n  then: {tags: [t]}\n", encoding="utf-8"
    )
    app.reload_rules()
    new = post(api, "/api/rules/replay", {"rule": rule_body("fortum")}).json()
    assert new["shadowed"] == [{"drive_id": "a", "rule_id": "invoice"}]


def test_replay_with_replaces_uses_the_old_position(app, api, fake_archive):
    add_filed(app, fake_archive, "11. Bills/2026/20260210_Fortum.pdf", "a", "Fortum invoice")
    app.save_rule(Rule.model_validate(rule_body("fortum")))
    app.save_rule(Rule.model_validate(rule_body("invoice", "invoice", "99. Misc")))
    first = post(api, "/api/rules/replay", {"rule": rule_body("fortum"), "replaces": "fortum"})
    assert first.json()["shadowed"] == []
    last = post(api, "/api/rules/replay", {"rule": rule_body("fortum"), "replaces": "invoice"})
    assert last.json()["shadowed"] == [{"drive_id": "a", "rule_id": "fortum"}]
    unknown = post(api, "/api/rules/replay", {"rule": rule_body("x"), "replaces": "nope"})
    assert unknown.status_code == 404


def test_replay_takes_the_document_the_areas_were_drawn_on_and_an_opaque_cursor(
    app, api, fake_archive
):
    for i in range(3):
        add_filed(app, fake_archive, f"11. Bills/2026/2026020{i + 1}_Fortum.pdf", f"a{i}", "Fortum")
    add_filed(app, fake_archive, "20. Home/20260301_Fortum.pdf", "z", "Fortum")
    body = {"rule": rule_body("fortum"), "near_drive_id": "z"}
    first = post(api, "/api/rules/replay", body)
    assert first.status_code == 200, first.text
    assert (first.json()["matched"], first.json()["looked_at"]) == (4, 4)
    # an unknown document is not a reason to refuse the test
    assert post(api, "/api/rules/replay", {**body, "near_drive_id": "nope"}).status_code == 200
    # a cursor from a test the server no longer has
    stale = post(api, "/api/rules/replay", {**body, "after": "r1.deadbeef.2"})
    assert stale.status_code == 400 and "run it again" in stale.json()["error"]


def test_replay_invalid_rule_is_400(api):
    r = post(api, "/api/rules/replay", {"rule": {"id": "x", "when": {"filename_matches": "("}}})
    assert r.status_code == 400 and "invalid regex" in r.json()["error"]


def test_explain(app, api, fake_archive):
    add_filed(app, fake_archive, f"{INBOX}/20260401_Fortum.pdf", "d", "Fortum invoice")
    app.save_rule(Rule.model_validate(rule_body("fortum")))
    app.save_rule(Rule.model_validate(rule_body("nomatch", "zzz")))
    r = post(api, "/api/rules/explain", {"drive_id": "d"})
    assert r.status_code == 200, r.text
    by_id = {x["rule_id"]: x for x in r.json()}
    assert by_id["fortum"]["matched"] is True and "folder" in by_id["fortum"]["wins"]
    assert by_id["nomatch"]["matched"] is False and by_id["nomatch"]["why"]
    assert post(api, "/api/rules/explain", {"drive_id": "missing"}).status_code == 404


def test_state_toggle_decline_and_clear(app, api):
    r = put(api, "/api/rules/state", {"offer": False})
    assert r.status_code == 200 and r.json() == {"offer": False, "declined": 0}
    assert load_state(app.app_paths.data_dir).offer is False
    r = post(api, "/api/rules/state/decline", {"words": ["Fortum", "invoice", "fortum"]})
    assert r.json() == {"offer": False, "declined": 1}
    post(api, "/api/rules/state/decline", {"words": ["invoice", "FORTUM"]})  # same set
    again = post(api, "/api/rules/state/decline", {"words": ["other"]})
    assert again.json()["declined"] == 2
    assert load_state(app.app_paths.data_dir).declined == [["fortum", "invoice"], ["other"]]
    unchanged = put(api, "/api/rules/state", {"offer": None})
    assert unchanged.json() == {"offer": False, "declined": 2}
    cleared = put(api, "/api/rules/state", {"clear_declined": True})
    assert cleared.json() == {"offer": False, "declined": 0}
    assert api.get("/api/rules").json()["state"] == {"offer": False, "declined": 0}


def test_save_path_id_must_match_body_and_not_be_reserved(app, api):
    put(api, "/api/rules/a", rule_body("a"))
    mismatch = put(api, "/api/rules/a2?replaces=a", rule_body("other"))
    assert mismatch.status_code == 400 and "differ" in mismatch.json()["error"]
    renamed = put(api, "/api/rules/a2?replaces=a", rule_body("a2"))
    assert renamed.status_code == 200 and ids(renamed.json()) == ["a2"]
    # PUT /state is routed to the state route first (so a rule body there is a 422)
    assert put(api, "/api/rules/state", rule_body("state")).status_code == 422
    for name in ("replay", "explain"):
        r = put(api, f"/api/rules/{name}", rule_body(name))
        assert r.status_code == 400 and "reserved" in r.json()["error"]


def test_a_rules_collections_are_saved_listed_and_prefill_the_inbox(app, api, fake_archive):
    body = rule_body("kela", "kela", "50. Medical", collections=["Sauna", "Taxes"])
    body["when"]["folder_is"] = INBOX
    assert put(api, "/api/rules/kela", body).status_code == 200
    listed = api.get("/api/rules").json()["rules"][0]
    assert listed["then"]["collections"] == ["Sauna", "Taxes"]
    assert "collections:" in (app.rules_dir / "learned.yaml").read_text(encoding="utf-8")
    fake_archive.add(f"{INBOX}/scan.pdf", content=b"k", drive_id="k")
    scan(app.paths, app.repo)
    app.repo.save_content("k", None, ExtractedText("Kela", "test"), "indexed")
    suggestion = api.get("/api/inbox").json()[0]["suggestion"]
    assert suggestion["collections"] == ["Sauna", "Taxes"]
    assert suggestion["collection_sources"] == {"Sauna": "rule:kela", "Taxes": "rule:kela"}


def test_a_rule_without_collections_lists_an_empty_list(api):
    put(api, "/api/rules/a", rule_body("a"))
    assert api.get("/api/rules").json()["rules"][0]["then"]["collections"] == []
    bad = put(api, "/api/rules/b", rule_body("b", collections=[" "]))
    assert bad.status_code == 400
