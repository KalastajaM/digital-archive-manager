"""The document a rule is made from, in the rule test: judged on its own ("matches" or
"does not match: why") and left out of every count and list of the test."""

import time

import pytest

import synth
from dam.rules.model import Rule
from dam.rules.replay import replay
from test_api import make_client, post
from test_rules_pictures_api import BOX, keep
from test_rules_pictures_api import rule_body as picture_rule
from test_rules_zone import HEADER, INBOX, LETTER, add

WORD = {"id": "fortum", "when": {"text_contains": ["fortum"]}, "then": {"folder": "11. Bills"}}


@pytest.fixture
def api(app):
    with make_client(app) as c:
        for r in list(app.rules):
            app.delete_rule(r.id)
        yield c


def filed(app, fake_archive):
    add(app, fake_archive, "11. Bills/20260110_Fortum.pdf", "a", "Fortum")
    add(app, fake_archive, "11. Bills/20260210_Fortum.pdf", "b", "Fortum")
    add(app, fake_archive, "20. Home/20260310_Fortum.pdf", "c", "Fortum")
    add(app, fake_archive, "20. Home/20260311_Other.pdf", "d", "Nothing")


def wait_job(api, body):
    job = post(api, "/api/rules/replay/jobs", {**body, "sheet": "s"}).json()["job_id"]
    end = time.monotonic() + 15
    while time.monotonic() < end:
        data = api.get(f"/api/rules/replay/jobs/{job}").json()
        if data["state"] not in ("running", "waiting"):
            return data["result"]
        time.sleep(0.05)
    raise AssertionError("the test did not finish")


def test_a_matching_filed_source_is_left_out_of_the_counts(app, fake_archive):
    filed(app, fake_archive)
    rule = Rule.model_validate(WORD)
    before = replay(app.engine, rule, [rule], app.settings.special_folders)
    r = replay(app.engine, rule, [rule], app.settings.special_folders, source_drive_id="c")
    assert before.source is None
    assert (before.matched, before.checked, before.total) == (3, 4, 4)
    assert (r.matched, r.checked, r.total) == (2, 3, 3)
    assert [h.drive_id for h in r.different] == []
    assert (r.source.drive_id, r.source.path, r.source.matched, r.source.reason) == (
        "c",
        "20. Home/20260310_Fortum.pdf",
        True,
        "",
    )


def test_a_source_that_does_not_match_says_why(app, fake_archive):
    filed(app, fake_archive)
    rule = Rule.model_validate(WORD)
    r = replay(app.engine, rule, [rule], app.settings.special_folders, source_drive_id="d")
    assert (r.source.matched, r.source.reason) == (False, "no word found")
    assert (r.matched, r.checked, r.total) == (3, 3, 3)


def test_an_inbox_source_is_judged_by_the_rule_as_written_and_not_counted(app, fake_archive):
    filed(app, fake_archive)
    add(app, fake_archive, f"{INBOX}/scan1.pdf", "i1", "Fortum bill")
    add(app, fake_archive, f"{INBOX}/scan2.pdf", "i2", "Fortum bill")
    add(app, fake_archive, "20. Home/scan3.pdf", "f", "Fortum bill")
    body = {**WORD, "when": {"text_contains": ["fortum"], "folder_is": INBOX}}
    rule = Rule.model_validate(body)
    special = app.settings.special_folders
    plain = replay(app.engine, rule, [rule], special)
    inbox = replay(app.engine, rule, [rule], special, source_drive_id="i1")
    assert plain.inbox == 2 and inbox.inbox == 1
    assert inbox.source.matched is True
    # a filed source: judged without folder_is, as the replay is, so it matches
    home = replay(app.engine, rule, [rule], special, source_drive_id="f")
    assert home.source.matched is True and home.matched == plain.matched - 1
    # an inbox source the rule does not match as written (other folder than the one asked)
    other = Rule.model_validate({**body, "when": {**body["when"], "folder_is": "Elsewhere"}})
    miss = replay(app.engine, other, [other], special, source_drive_id="i1")
    assert (miss.source.matched, miss.source.reason) == (False, "not in the folder ‘Elsewhere’")


def test_a_text_area_reason_is_the_one_of_the_explanation(app, fake_archive):
    add(app, fake_archive, "Insurance/20260101_P.pdf", "a", "Pohjola", LETTER)
    add(app, fake_archive, "Insurance/20260102_P.pdf", "b", "Pohjola", LETTER)
    rule = Rule.model_validate(
        {
            "id": "p",
            "when": {"zones": [{"box": list(HEADER), "text_contains": ["nordea"]}]},
            "then": {"folder": "Insurance"},
        }
    )
    r = replay(
        app.engine,
        rule,
        [rule],
        app.settings.special_folders,
        layouts_for=app.repo.layouts_for,
        source_drive_id="a",
    )
    assert (r.source.matched, r.source.reason) == (False, "no word found in the area")
    assert r.matched == 0 and r.checked == 1 and r.not_checked == []


def test_a_source_whose_page_1_is_not_read_yet_cannot_be_told(app, fake_archive):
    add(app, fake_archive, "Insurance/20260101_P.pdf", "a", "Pohjola")
    rule = Rule.model_validate(
        {
            "id": "p",
            "when": {"zones": [{"box": list(HEADER), "text_contains": ["pohjola"]}]},
            "then": {"folder": "Insurance"},
        }
    )
    r = replay(
        app.engine,
        rule,
        [rule],
        app.settings.special_folders,
        layouts_for=app.repo.layouts_for,
        source_drive_id="a",
    )
    assert r.source.matched is None and "page 1" in r.source.reason
    assert r.not_checked == []  # it is not in the list of the documents waiting either


def test_the_sync_endpoint_leaves_the_source_out(app, api, fake_archive):
    filed(app, fake_archive)
    data = post(api, "/api/rules/replay", {"rule": WORD, "source_drive_id": "a"}).json()
    assert (data["matched"], data["total"]) == (2, 3)
    assert data["source"] == {
        "drive_id": "a",
        "path": "11. Bills/20260110_Fortum.pdf",
        "matched": True,
        "reason": "",
        "area_scores": [],
    }
    assert post(api, "/api/rules/replay", {"rule": WORD}).json()["source"] is None


def test_the_job_leaves_the_source_out_and_reports_it(app, api, fake_archive):
    filed(app, fake_archive)
    result = wait_job(api, {"rule": WORD, "source_drive_id": "d", "near_drive_id": "d"})
    assert (result["matched"], result["total"], result["looked_at"]) == (3, 3, 3)
    assert result["source"]["matched"] is False
    assert result["source"]["reason"] == "no word found"
    listed = [x["drive_id"] for x in result["different"] + result["not_checked"]]
    assert "d" not in listed


def test_a_picture_source_has_its_score_in_the_reason_and_not_in_the_scores(app, api, fake_archive):
    for i in range(3):
        add(app, fake_archive, f"Insurance/Acme/20250{i + 1}10_A.pdf", f"m{i}", "x")
        keep(app, f"m{i}", synth.letter(shift=(2 * i, 3 * i)))
    add(app, fake_archive, "10. Bank/other.pdf", "o", "x")
    keep(app, "o", synth.letter(kind=1))
    saved = {"drive_id": "m0", "box": BOX, "save": True, "rule_id": "acme"}
    image = post(api, "/api/rules/area-picture", saved).json()["image"]
    rule = picture_rule(image)
    del rule["when"]["folder_is"]
    data = post(api, "/api/rules/replay", {"rule": rule, "source_drive_id": "o"}).json()
    assert data["source"]["matched"] is False
    assert "the picture in the area scores 0." in data["source"]["reason"]
    assert data["source"]["reason"].endswith("needs 0.85")
    assert all(s["drive_id"] != "o" for s in data["scores"])
    assert (data["matched"], data["total"]) == (3, 3)
    ok = post(api, "/api/rules/replay", {"rule": rule, "source_drive_id": "m1"}).json()
    assert ok["source"]["matched"] is True
    assert all(s["drive_id"] != "m1" for s in ok["scores"]) and ok["matched"] == 2


def test_a_picture_source_reports_its_score_for_each_area(app, api, fake_archive):
    for i in range(3):
        add(app, fake_archive, f"Insurance/Acme/20250{i + 1}10_A.pdf", f"m{i}", "x")
        keep(app, f"m{i}", synth.letter(shift=(2 * i, 3 * i)))
    add(app, fake_archive, "10. Bank/other.pdf", "o", "x")
    keep(app, "o", synth.letter(kind=1))
    saved = {"drive_id": "m0", "box": BOX, "save": True, "rule_id": "acme"}
    image = post(api, "/api/rules/area-picture", saved).json()["image"]
    rule = picture_rule(image)
    del rule["when"]["folder_is"]
    ok = post(api, "/api/rules/replay", {"rule": rule, "source_drive_id": "m1"}).json()
    [score] = ok["source"]["area_scores"]
    assert ok["source"]["matched"] is True
    assert score is not None and score >= 0.85
    # a document that does not match still says how close it came
    miss = post(api, "/api/rules/replay", {"rule": rule, "source_drive_id": "o"}).json()
    [low] = miss["source"]["area_scores"]
    assert miss["source"]["matched"] is False
    assert low is not None and low < score
    assert f"scores {low:.2f}" in miss["source"]["reason"]


def test_a_source_without_picture_areas_has_no_area_scores(app, fake_archive):
    filed(app, fake_archive)
    rule = Rule.model_validate(WORD)
    r = replay(app.engine, rule, [rule], app.settings.special_folders, source_drive_id="c")
    assert r.source.area_scores == []


def test_the_marked_documents_leave_the_source_out(app, fake_archive):
    filed(app, fake_archive)
    rule = Rule.model_validate({**WORD, "sender": "Fortum Oy"})
    special = app.settings.special_folders
    kwargs = {"sender_ids": lambda sender: ["a", "b", "d"]}
    r = replay(app.engine, rule, [rule], special, source_drive_id="d", **kwargs)
    assert (r.marked.total, r.marked.found, r.marked.missed) == (2, 2, [])
