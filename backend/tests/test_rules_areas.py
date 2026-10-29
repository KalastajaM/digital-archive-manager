"""Showing areas: the areas behind a suggestion (every matching rule's, the address area, the
person's line) and in a rule's explanation (also for rules that did not match)."""

from dam.extract.layout import Page1Layout
from dam.rules.engine import suggest
from dam.rules.model import Rule
from dam.rules.people import PeopleContext, person_line
from dam.rules.replay import explain
from test_api import make_client, post
from test_people import PEOPLE, ZONE, addressed
from test_rules_zone import HEADER, INBOX, LETTER, add, layout, rec
from test_rules_zones_many import TITLE, two_zones


def plain_zone(rule_id, word, box=HEADER, **then):
    return Rule.model_validate(
        {
            "id": rule_id,
            "when": {"zones": [{"box": list(box), "text_contains": [word]}], "folder_is": INBOX},
            "then": then,
        }
    )


def test_a_suggestion_has_the_areas_of_every_matching_rule_and_the_lines_that_matched():
    rules = [
        plain_zone("winner", "pohjola", folder="Insurance"),
        two_zones(),  # also matches, but the first rule gave the folder
    ]
    found = suggest(rec(), "pohjola maksu", rules, layout=LETTER)
    by_rule = {(a.rule_id, a.index): a for a in found.areas if a.kind == "text"}
    assert set(by_rule) == {("winner", 0), ("both-areas", 0), ("both-areas", 1)}
    winner = by_rule["winner", 0]
    assert winner.box == HEADER and winner.wins is True and winner.matched is True
    assert winner.lines == [(0.08, 0.04, 0.30, 0.07)]
    # the second rule gave the folder nothing (the first won it): drawn, not stronger
    second = by_rule["both-areas", 1]
    assert second.box == TITLE and second.lines == [(0.08, 0.60, 0.40, 0.63)]
    assert by_rule["both-areas", 0].wins is False


def test_a_rule_that_did_not_match_has_no_areas_in_the_suggestion():
    found = suggest(rec(), "pohjola", [plain_zone("r", "fortum")], layout=LETTER)
    assert found.areas == []


def test_an_unread_page_has_no_areas():
    found = suggest(rec(), "pohjola", [plain_zone("r", "pohjola")], layout=None)
    assert found.areas == [] and found.person_line is None


def people(assigned=None, zone=ZONE):
    return PeopleContext(PEOPLE, zone, assigned)


def test_the_address_area_and_the_persons_line():
    rule = Rule.model_validate(
        {
            "id": "mail",
            "when": {"text_contains": ["kela"], "folder_is": INBOX},
            "then": {"folder": "Mail/{person}"},
        }
    )
    page = addressed("Tiina Visser", "Kotikatu 1")
    found = suggest(rec(), "kela", [rule], layout=page, people=people())
    [address] = [a for a in found.areas if a.kind == "address"]
    assert address.rule_id == "" and address.box == ZONE
    assert address.lines == [page.lines[0].box]
    assert found.person_line is not None and found.person_line.box == page.lines[0].box
    # no person found: the area is still there, without a line
    none = suggest(rec(), "kela", [rule], layout=addressed("Someone"), people=people())
    [area] = [a for a in none.areas if a.kind == "address"]
    assert area.lines == [] and none.person_line is None


def test_a_rules_own_address_area_is_the_one_drawn():
    letter = Page1Layout(
        [addressed("Tiina Visser", y0=0.80).lines[0]], "text-layer"
    )  # far below the usual area
    rule = Rule.model_validate(
        {
            "id": "mail",
            "when": {"text_contains": ["kela"]},
            "then": {"folder": "Mail/{person}"},
            "person_zone": [0.05, 0.75, 0.5, 0.9],
        }
    )
    found = suggest(rec(), "kela", [rule], layout=letter, people=people())
    [address] = [a for a in found.areas if a.kind == "address"]
    assert address.rule_id == "mail" and address.box == (0.05, 0.75, 0.5, 0.9)
    assert found.person == "Tiina" and found.person_line is not None


def test_the_person_line_of_two_lines_is_their_union():
    page = addressed("Tiina", "Visser", "Kotikatu 1")
    box = person_line(page, ZONE, PEOPLE, "Tiina")
    top, bottom = page.lines[0].box, page.lines[1].box
    assert box == (min(top[0], bottom[0]), top[1], max(top[2], bottom[2]), bottom[3])
    assert person_line(page, ZONE, PEOPLE, "Michiel") is None
    assert person_line(None, ZONE, PEOPLE, "Tiina") is None


# --- explain --------------------------------------------------------------------------


def test_explain_draws_the_areas_of_rules_that_did_not_match_with_the_reason(app):
    special = app.settings.special_folders
    out = explain(
        rec(),
        "pohjola maksu",
        [two_zones(), two_zones(second="fortum"), plain_zone("elsewhere", "pohjola")],
        special,
        None,
        LETTER,
    )
    both, miss, _ = out
    assert both.matched and [a.reason for a in both.areas] == [None, None]
    assert [a.lines for a in both.areas] == [[(0.08, 0.04, 0.30, 0.07)], [(0.08, 0.60, 0.40, 0.63)]]
    assert not miss.matched
    assert [a.matched for a in miss.areas] == [False, False]
    assert [a.reason for a in miss.areas] == [miss.why, "no word found in area 2"]
    # the first area did match its word: its line is shown
    assert miss.areas[0].lines and not miss.areas[1].lines


def test_explain_of_an_unread_page_says_so_in_each_area(app):
    out = explain(
        rec(), "pohjola", [plain_zone("r", "pohjola")], app.settings.special_folders, None, None
    )
    assert [a.reason for a in out[0].areas] == ["page 1 has not been read yet"]


def test_explain_marks_the_rule_that_won(app):
    out = explain(
        rec(),
        "pohjola",
        [plain_zone("a", "pohjola", folder="X"), plain_zone("b", "pohjola", folder="Y")],
        app.settings.special_folders,
        None,
        LETTER,
    )
    assert [a.areas[0].wins for a in out] == [True, False]


# --- the API --------------------------------------------------------------------------


def test_inbox_files_and_explain_api_have_the_areas(app, fake_archive):
    app.save_rule(plain_zone("pohjola", "pohjola", folder="Insurance/Pohjola"))
    add(app, fake_archive, f"{INBOX}/a.pdf", "a", "pohjola vakuutus", LETTER)
    with make_client(app) as c:
        entry = c.get("/api/inbox").json()[0]["suggestion"]
        file_s = c.get("/api/files/a/suggestions").json()
        explained = post(c, "/api/rules/explain", {"drive_id": "a"}).json()
    expected = {
        "rule_id": "pohjola",
        "index": 0,
        "box": list(HEADER),
        "kind": "text",
        "lines": [[0.08, 0.04, 0.3, 0.07]],
        "score": None,
        "matched": True,
        "reason": None,
        "wins": True,
        "document": False,
    }
    assert entry["areas"][0] == expected and file_s["areas"][0] == expected
    assert entry["person_line"] is None and file_s["person_line"] is None
    mine = next(x for x in explained if x["rule_id"] == "pohjola")
    assert mine["areas"] == [expected]


def test_api_person_line_has_a_box(app, fake_archive):
    rule = Rule.model_validate(
        {"id": "mail", "when": {"text_contains": ["kela"]}, "then": {"folder": "Mail/{person}"}}
    )
    app.save_rule(rule)
    app.set_people(PEOPLE, ZONE)
    page = layout(("Tiina Visser", (0.08, 0.15, 0.30, 0.17)))
    add(app, fake_archive, f"{INBOX}/a.pdf", "a", "kela", page)
    with make_client(app) as c:
        s = c.get("/api/files/a/suggestions").json()
    assert s["person_line"] == {"box": [0.08, 0.15, 0.3, 0.17]}
    [address] = [a for a in s["areas"] if a["kind"] == "address"]
    assert address["rule_id"] == "" and address["lines"] == [[0.08, 0.15, 0.3, 0.17]]
