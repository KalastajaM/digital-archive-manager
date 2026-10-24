"""Several areas per rule: every area must match, the draft from several boxes, and the
place of a new rule among the learned ones."""

import pytest
import yaml

from dam.extract.layout import Page1Layout
from dam.rules.engine import suggest
from dam.rules.learned import write_rules_file
from dam.rules.model import Rule
from dam.rules.replay import explain, replay
from test_api import LOCAL_ORIGIN, make_client, post
from test_rules_zone import HEADER, INBOX, LETTER, add, layout, rec, seed_frequency

TITLE = (0.05, 0.55, 0.5, 0.65)  # holds "Maksu Pohjolaan" on LETTER


def two_zones(first="pohjola", second="maksu", **extra):
    return Rule.model_validate(
        {
            "id": "both-areas",
            "when": {
                "zones": [
                    {"box": list(HEADER), "text_contains": [first]},
                    {"box": list(TITLE), "text_contains": [second]},
                ],
                "folder_is": INBOX,
            },
            "then": {"folder": "Insurance/Pohjola"},
            **extra,
        }
    )


# --- the model ---------------------------------------------------------------------


def test_a_zone_with_a_picture_is_accepted_and_keeps_its_place_among_the_others():
    rule = Rule.model_validate(
        {
            "id": "x",
            "when": {
                "zones": [
                    {"box": [0.1, 0.1, 0.2, 0.2], "image": "areas/x-1.png"},
                    {"box": [0.3, 0.1, 0.5, 0.2], "text_contains": ["lasku"]},
                ]
            },
        }
    )
    assert [z.is_picture for z in rule.when.zones] == [True, False]
    # the words of a picture area are none: the text check ignores it
    assert rule._folded_zones == [[], ["lasku"]]


def test_a_zone_needs_words_and_cannot_have_both():
    box = [0.1, 0.1, 0.2, 0.2]
    with pytest.raises(ValueError, match="at least one word"):
        Rule.model_validate({"id": "x", "when": {"zones": [{"box": box}]}})
    with pytest.raises(ValueError, match="not both"):
        Rule.model_validate(
            {"id": "x", "when": {"zones": [{"box": box, "text_contains": ["a"], "image": "a.png"}]}}
        )


def test_the_single_zone_key_is_gone():
    with pytest.raises(ValueError):
        Rule.model_validate(
            {"id": "x", "when": {"zone": {"box": [0, 0, 1, 1], "text_contains": ["a"]}}}
        )


def test_several_zones_round_trip_through_a_rule_file(tmp_path):
    path = tmp_path / "learned.yaml"
    write_rules_file(path, [two_zones()])
    on_disk = yaml.safe_load(path.read_text(encoding="utf-8"))[0]["when"]["zones"]
    assert on_disk == [
        {"box": list(HEADER), "text_contains": ["pohjola"]},
        {"box": list(TITLE), "text_contains": ["maksu"]},
    ]


# --- matching -----------------------------------------------------------------------


def test_every_zone_has_to_match():
    both = suggest(rec(), "pohjola maksu", [two_zones()], layout=LETTER)
    assert both.folder == "Insurance/Pohjola"
    # the second word is on the page, but not in the second area
    elsewhere = layout(
        ("Pohjola Vakuutus", (0.08, 0.04, 0.30, 0.07)),
        ("Maksu", (0.08, 0.80, 0.30, 0.83)),
    )
    assert suggest(rec(), "pohjola maksu", [two_zones()], layout=elsewhere).folder is None
    # a document that has the first word only
    only_first = layout(("Pohjola Vakuutus", (0.08, 0.04, 0.30, 0.07)))
    assert suggest(rec(), "pohjola", [two_zones()], layout=only_first).folder is None


def test_within_a_zone_any_word_is_enough():
    rule = Rule.model_validate(
        {
            "id": "r",
            "when": {"zones": [{"box": list(HEADER), "text_contains": ["fortum", "pohjola"]}]},
            "then": {"tags": ["t"]},
        }
    )
    assert suggest(rec(), "pohjola", [rule], layout=LETTER).tags == ["t"]


def test_a_missing_word_in_any_text_zone_means_no_match_and_no_waiting():
    # the second zone's word is not in the document's text: final, page 1 is not looked at
    found = suggest(rec(), "pohjola only", [two_zones()])
    assert found.folder is None and found.waiting_for_page1 is False
    # both words are in the text: now page 1 is needed
    assert suggest(rec(), "pohjola maksu", [two_zones()]).waiting_for_page1 is True


def test_no_zones_means_no_area_condition():
    rule = Rule.model_validate(
        {"id": "r", "when": {"text_contains": ["x"]}, "then": {"tags": ["t"]}}
    )
    assert rule.when.zones == []
    assert suggest(rec(), "x", [rule]).waiting_for_page1 is False


# --- explain -------------------------------------------------------------------------


def test_explain_has_the_lines_of_each_zone_and_names_the_failing_one(app):
    special = app.settings.special_folders
    out = explain(rec(), "pohjola maksu", [two_zones()], special, None, LETTER)
    assert out[0].matched and out[0].zone_lines == [["Pohjola Vakuutus"], ["Maksu Pohjolaan"]]
    assert "in area 1" in out[0].why and "in area 2" in out[0].why
    miss = explain(rec(), "pohjola maksu", [two_zones(second="fortum")], special, None, LETTER)
    assert not miss[0].matched and miss[0].why == "no word found in area 2"


# --- replay ---------------------------------------------------------------------------


def test_replay_needs_every_zone_and_reads_missing_pages(app, fake_archive):
    add(app, fake_archive, "Insurance/Pohjola/20250110_A.pdf", "a", "pohjola maksu", LETTER)
    # the first word only
    first = layout(("Pohjola", (0.08, 0.04, 0.30, 0.07)))
    add(app, fake_archive, "10. Bank/b.pdf", "b", "pohjola maksu", first)
    add(app, fake_archive, "10. Bank/c.pdf", "c", "pohjola maksu")  # not read yet
    add(app, fake_archive, "10. Bank/d.pdf", "d", "pohjola")  # second word missing from text
    wanted = []
    rule = two_zones()
    r = replay(
        app.engine,
        rule,
        [rule],
        app.settings.special_folders,
        layouts_for=app.repo.layouts_for,
        want_layouts=wanted.extend,
    )
    assert r.matched == 1 and wanted == ["c"]
    assert [n.path for n in r.not_checked] == ["10. Bank/c.pdf"]
    assert r.checked == 3  # a, b and d are looked at; c waits


# --- the draft from several boxes ---------------------------------------------------------


def test_draft_zone_with_two_boxes_has_one_ticked_word_per_box(app, fake_archive):
    seed_frequency(app, fake_archive)
    add(app, fake_archive, f"{INBOX}/a.pdf", "a", "pohjola vakuutus maksu pohjolaan", LETTER)
    with make_client(app) as c:
        r = post(
            c, "/api/rules/draft-zone", {"drive_id": "a", "boxes": [list(HEADER), list(TITLE)]}
        )
    assert r.status_code == 200, r.text
    d = r.json()
    assert [z["box"] for z in d["zones"]] == [list(HEADER), list(TITLE)]
    assert [z["lines"] for z in d["zones"]] == [["Pohjola Vakuutus"], ["Maksu Pohjolaan"]]
    for z in d["zones"]:
        assert [w["ticked"] for w in z["words"]].count(True) == 1
    assert d["place_above"] is None


def test_draft_zone_starts_from_the_documents_from_assignment(app, fake_archive):
    seed_frequency(app, fake_archive)
    add(app, fake_archive, f"{INBOX}/a.pdf", "a", "pohjola vakuutus", LETTER)
    with make_client(app) as c:
        body = {"drive_id": "a", "boxes": [list(HEADER)]}
        assert post(c, "/api/rules/draft-zone", body).json()["sender"] is None
        app.assignments.set(["a"], sender="Pohjola")
        assert post(c, "/api/rules/draft-zone", body).json()["sender"] == "Pohjola"
        # a sender given in the request wins
        other = post(c, "/api/rules/draft-zone", {**body, "sender": "Other"}).json()
        assert other["sender"] == "Other"


def test_draft_zone_names_the_empty_box(app, fake_archive):
    add(app, fake_archive, f"{INBOX}/a.pdf", "a", "x", LETTER)
    with make_client(app) as c:
        r = post(
            c,
            "/api/rules/draft-zone",
            {"drive_id": "a", "boxes": [list(HEADER), [0.6, 0.8, 0.9, 0.9]]},
        )
        assert r.status_code == 400 and "box 2" in r.json()["error"]
        assert post(c, "/api/rules/draft-zone", {"drive_id": "a", "boxes": []}).status_code in (
            400,
            422,
        )
        assert post(
            c, "/api/rules/draft-zone", {"drive_id": "a", "boxes": [[0, 0, 1]]}
        ).status_code in (400, 422)


# --- the order -------------------------------------------------------------------------------


def plain(rule_id, word="pohjola"):
    return Rule.model_validate(
        {"id": rule_id, "when": {"text_contains": [word]}, "then": {"folder": "Insurance"}}
    )


def test_the_draft_says_which_learned_rule_it_goes_above(app, fake_archive):
    seed_frequency(app, fake_archive)
    app.save_rule(plain("first", "fortum"))
    app.save_rule(plain("sender"))
    add(app, fake_archive, f"{INBOX}/a.pdf", "a", "pohjola vakuutus", LETTER)
    with make_client(app) as c:
        d = post(c, "/api/rules/draft-zone", {"drive_id": "a", "boxes": [list(HEADER)]}).json()
    assert d["place_above"] == "sender"


def test_a_rule_in_a_hand_written_file_is_not_a_place(app, fake_archive):
    seed_frequency(app, fake_archive)
    (app.rules_dir / "mine.yaml").write_text(
        "- id: hand\n  when: {text_contains: [pohjola]}\n  then: {tags: [t]}\n", encoding="utf-8"
    )
    app.reload_rules()
    add(app, fake_archive, f"{INBOX}/a.pdf", "a", "pohjola vakuutus", LETTER)
    with make_client(app) as c:
        d = post(c, "/api/rules/draft-zone", {"drive_id": "a", "boxes": [list(HEADER)]}).json()
    assert d["place_above"] is None


def order(app, *ids):
    """The rules among ``ids`` in load order (the app ships example rules too)."""
    return [r.id for r in app.rules if r.id in ids]


def save_body(rule_id):
    return {
        "id": rule_id,
        "when": {"zones": [{"box": list(HEADER), "text_contains": ["pohjola"]}]},
        "then": {"folder": "Insurance/New"},
    }


def test_saving_with_place_above_puts_the_rule_directly_above(app):
    for rid in ("one", "two", "three"):
        app.save_rule(plain(rid, rid))
    with make_client(app) as c:
        r = c.put("/api/rules/new?place_above=two", json=save_body("new"), headers=LOCAL_ORIGIN)
        assert r.status_code == 200, r.text
    assert order(app, "one", "new", "two", "three") == ["one", "new", "two", "three"]


def test_place_above_is_ignored_for_unknown_or_hand_written_rules(app):
    app.save_rule(plain("one", "one"))
    (app.rules_dir / "mine.yaml").write_text(
        "- id: hand\n  when: {text_contains: [x]}\n  then: {tags: [t]}\n", encoding="utf-8"
    )
    before = (app.rules_dir / "mine.yaml").read_text(encoding="utf-8")
    with make_client(app) as c:
        assert (
            c.put(
                "/api/rules/a?place_above=nope", json=save_body("a"), headers=LOCAL_ORIGIN
            ).status_code
            == 200
        )
        assert (
            c.put(
                "/api/rules/b?place_above=hand", json=save_body("b"), headers=LOCAL_ORIGIN
            ).status_code
            == 200
        )
    assert order(app, "one", "a", "b", "hand") == ["one", "a", "b", "hand"]
    assert (app.rules_dir / "mine.yaml").read_text(encoding="utf-8") == before


def test_replay_puts_the_new_rule_above_place_above(app, fake_archive):
    add(app, fake_archive, "Insurance/Pohjola/20250110_A.pdf", "a", "pohjola vakuutus", LETTER)
    app.save_rule(plain("sender"))
    body = {"rule": save_body("new")}
    with make_client(app) as c:
        below = post(c, "/api/rules/replay", body).json()
        above = post(c, "/api/rules/replay", {**body, "place_above": "sender"}).json()
    assert below["shadowed"] == [{"drive_id": "a", "rule_id": "sender"}]
    assert above["shadowed"] == []


def test_a_page_that_is_read_but_empty_does_not_match_any_zone():
    empty = Page1Layout([], "text-layer")
    assert suggest(rec(), "pohjola maksu", [two_zones()], layout=empty).folder is None


def test_place_above_is_found_for_boxes_drawn_on_a_filed_letter(app, fake_archive):
    """Learned rules carry ``folder_is: <inbox>``; a filed document is not in the inbox,
    so the rest of the rule is what counts."""
    seed_frequency(app, fake_archive)
    learned = Rule.model_validate(
        {
            "id": "pohjola",
            "when": {"text_contains": ["pohjola"], "folder_is": INBOX},
            "then": {"folder": "Insurance"},
        }
    )
    app.save_rule(learned)
    add(app, fake_archive, "Insurance/Pohjola/20250110_A.pdf", "a", "pohjola vakuutus", LETTER)
    with make_client(app) as c:
        d = post(c, "/api/rules/draft-zone", {"drive_id": "a", "boxes": [list(HEADER)]}).json()
        assert d["place_above"] == "pohjola"
        rule = {
            "id": d["id"],
            "when": {
                "folder_is": INBOX,
                "zones": [{"box": list(HEADER), "text_contains": ["pohjola"]}],
            },
            "then": {"folder": "X"},
        }
        above = post(c, "/api/rules/replay", {"rule": rule, "place_above": d["place_above"]})
        below = post(c, "/api/rules/replay", {"rule": rule})
    assert above.json()["shadowed"] == []
    assert below.json()["shadowed"] == [{"drive_id": "a", "rule_id": "pohjola"}]
