"""People and the address area: detection, {person} in templates, when.person, drafts,
the replay of rules that need a person and the settings API."""

from datetime import date

import pytest
import yaml

from dam.config import DEFAULT_ADDRESS_ZONE, Person, Settings, load_settings
from dam.extract.base import ExtractedText
from dam.extract.layout import Line, Page1Layout
from dam.index.repo import FileRecord
from dam.index.scanner import scan
from dam.rules.draft import folder_pattern
from dam.rules.engine import NeedsPerson, TemplateError, render, suggest
from dam.rules.model import Rule
from dam.rules.people import PeopleContext, detect_people, pick_person
from dam.rules.replay import NOT_READ, PERSON_UNKNOWN, replay
from test_api import LOCAL_ORIGIN, make_client, post

INBOX = "##. Organize"
ZONE = (0.06, 0.10, 0.52, 0.30)
MICHIEL = Person(name="Michiel", match=["Michiel Visser", "M. Visser"])
TIINA = Person(name="Tiina", match=["Tiina Visser"])
PEOPLE = [MICHIEL, TIINA]


def at(text, y, x=0.08, h=0.02):
    return Line(text, (x, y, x + 0.25, y + h))


def addressed(*names, y0=0.15):
    return Page1Layout([at(n, y0 + 0.03 * i) for i, n in enumerate(names)], "text-layer")


# --- detection ------------------------------------------------------------------------


def test_a_name_in_one_line_or_split_over_two_lines():
    assert detect_people(addressed("Michiel Visser", "Kotikatu 1"), ZONE, PEOPLE) == ["Michiel"]
    assert detect_people(addressed("Michiel", "Visser", "Kotikatu 1"), ZONE, PEOPLE) == ["Michiel"]
    # two lines that are not adjacent do not join: a line between them
    assert detect_people(addressed("Michiel", "Kotikatu 1", "Visser"), ZONE, PEOPLE) == []


def test_matching_is_folded_and_ignores_other_text_in_the_line():
    assert detect_people(addressed("HERRA MICHIEL  VISSER"), ZONE, PEOPLE) == ["Michiel"]
    only = [Person(name="Aino", match=["Äänekoski Öberg"])]
    assert detect_people(addressed("aanekoski oberg"), ZONE, only) == ["Aino"]


def test_only_the_address_zone_counts():
    below = Page1Layout([at("Michiel Visser", 0.70)], "text-layer")
    assert detect_people(below, ZONE, PEOPLE) == []
    assert detect_people(None, ZONE, PEOPLE) == []
    assert detect_people(addressed("Michiel Visser"), ZONE, []) == []


def test_one_character_off_only_for_long_matches():
    # "Michiel Visser" has 13 letters: one OCR error is tolerated
    assert detect_people(addressed("Michlel Visser"), ZONE, PEOPLE) == ["Michiel"]
    assert detect_people(addressed("Michiel Vissr"), ZONE, PEOPLE) == ["Michiel"]
    assert detect_people(addressed("Michlel Vlsser"), ZONE, PEOPLE) == []  # two off
    short = [Person(name="Tiina", match=["Tiina V"])]  # six letters: exact only
    assert detect_people(addressed("Tiina V"), ZONE, short) == ["Tiina"]
    assert detect_people(addressed("Tilna V"), ZONE, short) == []


def test_two_people_found_means_no_person():
    both = addressed("Michiel Visser", "Tiina Visser")
    assert detect_people(both, ZONE, PEOPLE) == ["Michiel", "Tiina"]
    assert pick_person(["Michiel", "Tiina"]) is None
    assert pick_person(["Tiina"]) == "Tiina" and pick_person([]) is None


# --- the settings -----------------------------------------------------------------------


def test_default_address_zone_is_the_window_field_on_a_4():
    x0, y0, x1, y1 = DEFAULT_ADDRESS_ZONE
    assert (x0 * 210, y0 * 297, x1 * 210, y1 * 297) == pytest.approx((20, 40, 110, 80), abs=0.5)
    assert Settings().address_zone == DEFAULT_ADDRESS_ZONE and Settings().people == []


@pytest.mark.parametrize(
    "person",
    [
        {"name": " ", "match": ["a"]},
        {"name": "a/b", "match": ["a"]},
        {"name": "..", "match": ["a"]},
        {"name": "Tiina", "match": []},
        {"name": "Tiina", "match": [" "]},
    ],
)
def test_a_bad_person_is_refused(person):
    with pytest.raises(ValueError):
        Settings.model_validate({"people": [person]})


def test_names_are_distinct_and_the_zone_is_a_box():
    with pytest.raises(ValueError):
        Settings.model_validate(
            {"people": [{"name": "A", "match": ["a"]}, {"name": "a", "match": ["b"]}]}
        )
    with pytest.raises(ValueError):
        Settings.model_validate({"address_zone": [0.5, 0.1, 0.2, 0.3]})


# --- templates -----------------------------------------------------------------------------


def test_person_renders_and_a_missing_person_gives_no_value():
    assert render("Mail/{person}/{year}", date(2026, 1, 2), "x", "Tiina") == "Mail/Tiina/2026"
    with pytest.raises(NeedsPerson):
        render("Mail/{person}", None, "x")
    with pytest.raises(TemplateError):  # still unknown keys are refused
        render("{nope}", None, "x", "Tiina")


def rec(path=f"{INBOX}/a.pdf", ext="pdf", drive_id="a"):
    return FileRecord(drive_id=drive_id, path=path, name=path.rsplit("/")[-1], ext=ext)


def person_rule(rule_id="mail", folder="Mail/{person}", name=None, **extra):
    when = {"text_contains": ["kela"], "folder_is": INBOX, **extra.pop("when", {})}
    return Rule.model_validate(
        {"id": rule_id, "when": when, "then": {"folder": folder, "name": name}, **extra}
    )


def ctx(assigned=None, zone=ZONE):
    return PeopleContext(PEOPLE, zone, assigned)


def test_suggest_fills_person_from_the_address_area():
    found = suggest(rec(), "kela", [person_rule()], layout=addressed("Tiina Visser"), people=ctx())
    assert found.folder == "Mail/Tiina" and found.folder_source == "rule:mail"
    assert (found.person, found.person_source, found.people_found) == (
        "Tiina",
        "address area",
        ["Tiina"],
    )


def test_an_assignment_beats_detection():
    found = suggest(
        rec(), "kela", [person_rule()], layout=addressed("Tiina Visser"), people=ctx("Michiel")
    )
    assert found.folder == "Mail/Michiel" and found.person_source == "assigned"
    assert found.people_found == ["Tiina"]  # what page 1 says is still reported


def test_no_person_means_no_folder_and_the_next_rule_may_give_one():
    rules = [person_rule(), person_rule("fallback", folder="Mail/Unsorted")]
    two = addressed("Tiina Visser", "Michiel Visser")
    found = suggest(rec(), "kela", rules, layout=two, people=ctx())
    assert found.folder == "Mail/Unsorted" and found.folder_source == "rule:fallback"
    assert found.person is None and found.people_found == ["Michiel", "Tiina"]
    assert "template error" not in " ".join(found.sources)  # not an error: just no person
    none = suggest(rec(), "kela", [person_rule()], layout=addressed("Someone"), people=ctx())
    assert none.folder is None and none.person is None


def test_name_templates_use_person_too():
    rules = [person_rule(folder=None, name="Kela_{person}")]
    found = suggest(
        rec("##. Organize/scan.pdf"),
        "kela",
        rules,
        layout=addressed("Tiina Visser"),
        people=ctx(),
    )
    assert found.name == "Kela_Tiina.pdf" and found.name_source == "rule:mail"


def test_a_rule_that_needs_a_person_waits_for_page_1():
    found = suggest(rec(), "kela", [person_rule()], layout=None, people=ctx())
    assert found.folder is None and found.waiting_for_page1 is True
    assigned = suggest(rec(), "kela", [person_rule()], layout=None, people=ctx("Tiina"))
    assert assigned.folder == "Mail/Tiina" and not assigned.waiting_for_page1


def test_when_person_is_a_condition():
    rule = person_rule(when={"person": "tiina"})
    assert suggest(rec(), "kela", [rule], layout=addressed("Tiina Visser"), people=ctx()).folder
    assert not suggest(
        rec(), "kela", [rule], layout=addressed("Michiel Visser"), people=ctx()
    ).folder
    assert suggest(rec(), "kela", [rule], layout=None, people=ctx("Tiina")).folder
    # unread page: waiting; read but no person: no match, not waiting
    assert suggest(rec(), "kela", [rule], layout=None, people=ctx()).waiting_for_page1
    unknown = suggest(rec(), "kela", [rule], layout=addressed("Nobody"), people=ctx())
    assert unknown.folder is None and not unknown.waiting_for_page1


def test_person_zone_replaces_the_address_zone_for_that_rule():
    letter = Page1Layout([at("Tiina Visser", 0.80)], "text-layer")  # far below the usual area
    plain = person_rule()
    own = person_rule(person_zone=[0.05, 0.75, 0.5, 0.9])
    assert suggest(rec(), "kela", [plain], layout=letter, people=ctx()).folder is None
    found = suggest(rec(), "kela", [own], layout=letter, people=ctx())
    assert found.folder == "Mail/Tiina"
    assert (found.person, found.person_source) == ("Tiina", "rule:mail")
    assert found.people_found == ["Tiina"]


def test_person_zone_must_be_a_box():
    with pytest.raises(ValueError):
        person_rule(person_zone=[0.5, 0.5, 0.2, 0.2])
    with pytest.raises(ValueError):
        person_rule(when={"person": " "})


# --- the draft -------------------------------------------------------------------------------


def test_the_draft_proposes_person_for_a_folder_named_like_the_person():
    assert folder_pattern("Mail/Tiina/2026", None, "tiina") == "Mail/{person}/2026"
    assert folder_pattern("Mail/Tiina/2026", None) == "Mail/Tiina/2026"
    assert folder_pattern("Mail/Tiinaa", None, "Tiina") == "Mail/Tiinaa"  # whole part only


# --- the replay ------------------------------------------------------------------------------


def add(app, fake_archive, rel, drive_id, text, page1=None):
    fake_archive.add(rel, content=drive_id.encode(), drive_id=drive_id)
    scan(app.paths, app.repo)
    app.repo.save_content(
        drive_id, f"sha-{drive_id}", ExtractedText(text, "test", False, page1), "indexed"
    )


def fill(app, fake_archive):
    add(app, fake_archive, "Mail/Tiina/20250110_Kela.pdf", "a", "Kela", addressed("Tiina Visser"))
    add(
        app,
        fake_archive,
        "Mail/Michiel/20250210_Kela.pdf",
        "b",
        "Kela",
        addressed("Michiel Visser"),
    )
    add(app, fake_archive, "Mail/Tiina/20250310_Kela.pdf", "c", "Kela", addressed("Someone Else"))
    add(app, fake_archive, "Mail/Tiina/20250410_Kela.pdf", "d", "Kela")  # page 1 not read
    add(app, fake_archive, "Mail/Tiina/20250510_Kela.docx", "e", "Kela")  # nothing to read


def run(app, rule, **kw):
    return replay(
        app.engine,
        rule,
        [rule],
        app.settings.special_folders,
        layouts_for=app.repo.layouts_for,
        want_layouts=kw.pop("want", None),
        people=PEOPLE,
        address_zone=ZONE,
        **kw,
    )


def test_replay_renders_person_and_counts_unknown_people_as_not_checked(app, fake_archive):
    fill(app, fake_archive)
    rule = person_rule(folder="Mail/{person}", name="{doc_date:%Y%m%d}_Kela")
    queued = []
    r = run(app, rule, want=queued.extend)
    assert (r.matched, r.same) == (2, 2)
    assert sorted((n.path.rsplit("/")[-1], n.reason) for n in r.not_checked) == [
        ("20250310_Kela.pdf", PERSON_UNKNOWN),
        ("20250410_Kela.pdf", NOT_READ),
        ("20250510_Kela.docx", PERSON_UNKNOWN),
    ]
    assert queued == ["d"] and r.reading == 1


def test_replay_uses_the_owners_assignment_first(app, fake_archive):
    fill(app, fake_archive)
    rule = person_rule(folder="Mail/{person}", name="{doc_date:%Y%m%d}_Kela")
    r = run(
        app, rule, assigned_persons=lambda: {"c": "Tiina", "d": "Tiina", "e": "Tiina", "b": "Tiina"}
    )
    # b is assigned to Tiina although its page says Michiel: the rule would refile it
    assert r.not_checked == [] and r.matched == 5
    assert [h.drive_id for h in r.different] == ["b"]
    assert r.different[0].path_rule == "Mail/Tiina/20250210_Kela.pdf"


def test_replay_of_when_person(app, fake_archive):
    fill(app, fake_archive)
    rule = person_rule(folder="Mail/Tiina", when={"person": "Tiina"})
    r = run(app, rule)
    # a matches; b is Michiel's (a checked non-match); c, d, e have no known person
    assert r.matched == 1
    assert sorted(n.reason for n in r.not_checked) == sorted(
        [PERSON_UNKNOWN, NOT_READ, PERSON_UNKNOWN]
    )


# --- the settings API ---------------------------------------------------------------------------


def test_people_api_round_trip_writes_settings_yaml(app, app_paths):
    path = app_paths.config_dir / "settings.yaml"
    path.write_text("# my comment\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
    with make_client(app) as c:
        got = c.get("/api/settings/people").json()
        assert got["people"] == [] and got["address_zone"] == list(DEFAULT_ADDRESS_ZONE)
        assert got["default_address_zone"] == list(DEFAULT_ADDRESS_ZONE)
        body = {
            "people": [
                {"name": "Michiel", "match": ["Michiel Visser", "M. Visser"]},
                {"name": "Tiina", "match": ["Tiina Visser"]},
            ],
            "address_zone": [0.06, 0.1, 0.52, 0.3],
        }
        r = c.put("/api/settings/people", json=body, headers=LOCAL_ORIGIN)
        assert r.status_code == 200, r.text
        assert r.json()["people"] == body["people"] and r.json()["address_zone"] == [
            0.06,
            0.1,
            0.52,
            0.3,
        ]
        # the file has it, the comments and other keys are still there
        raw = (app_paths.config_dir / "settings.yaml").read_text(encoding="utf-8")
        assert yaml.safe_load(raw)["people"][1] == {"name": "Tiina", "match": ["Tiina Visser"]}
        assert "# my comment" in raw and "archive_root:" in raw
        settings = load_settings(app_paths)
        assert [p.name for p in settings.people] == ["Michiel", "Tiina"]
        assert settings.address_zone == (0.06, 0.1, 0.52, 0.3)
        assert [p.name for p in app.settings.people] == ["Michiel", "Tiina"]
        # without a zone the zone stays
        again = c.put(
            "/api/settings/people",
            json={"people": [{"name": "Aino", "match": ["Aino"]}]},
            headers=LOCAL_ORIGIN,
        )
        assert again.json()["address_zone"] == [0.06, 0.1, 0.52, 0.3]
        assert [p["name"] for p in again.json()["people"]] == ["Aino"]
        # emptying the list is allowed
        empty = c.put("/api/settings/people", json={"people": []}, headers=LOCAL_ORIGIN)
        assert empty.json()["people"] == [] and load_settings(app_paths).people == []


@pytest.mark.parametrize(
    "body",
    [
        {"people": [{"name": "a/b", "match": ["x"]}]},
        {"people": [{"name": "Tiina", "match": []}]},
        {"people": [{"name": "A", "match": ["x"]}, {"name": "a", "match": ["y"]}]},
        {"people": [], "address_zone": [0.9, 0.1, 0.2, 0.3]},
    ],
)
def test_bad_people_are_refused_and_nothing_is_written(app, app_paths, body):
    before = (app_paths.config_dir / "settings.yaml").read_bytes()
    with make_client(app) as c:
        r = c.put("/api/settings/people", json=body, headers=LOCAL_ORIGIN)
    assert r.status_code == 400
    assert (app_paths.config_dir / "settings.yaml").read_bytes() == before


def test_rule_api_keeps_person_and_person_zone(app):
    with make_client(app) as c:
        for r in list(app.rules):
            app.delete_rule(r.id)
        body = {
            "id": "mail",
            "when": {"text_contains": ["kela"], "person": "Tiina"},
            "then": {"folder": "Mail/{person}"},
            "person_zone": [0.05, 0.75, 0.5, 0.9],
        }
        r = c.put("/api/rules/mail", json=body, headers=LOCAL_ORIGIN)
        assert r.status_code == 200, r.text
        rule = r.json()["rules"][0]
        assert rule["when"]["person"] == "Tiina" and rule["person_zone"] == [0.05, 0.75, 0.5, 0.9]
        bad = c.put(
            "/api/rules/x",
            json={**body, "id": "x", "person_zone": [0.9, 0.1, 0.2, 0.3]},
            headers=LOCAL_ORIGIN,
        )
        assert bad.status_code == 400
        # the example in the Inbox: a letter for Tiina gets her folder
    assert app.rules[0].person_zone == (0.05, 0.75, 0.5, 0.9)


def test_inbox_entry_carries_person_and_sources(app, fake_archive):
    app.settings.people = PEOPLE
    app.settings.address_zone = ZONE
    for r in list(app.rules):
        app.delete_rule(r.id)
    app.save_rule(person_rule())
    add(app, fake_archive, f"{INBOX}/a.pdf", "a", "kela", addressed("Tiina Visser"))
    with make_client(app) as c:
        s = c.get("/api/inbox").json()[0]["suggestion"]
    assert s["folder"] == "Mail/Tiina"
    assert (s["person"], s["person_source"], s["people_found"]) == (
        "Tiina",
        "address area",
        ["Tiina"],
    )


def test_explain_reports_the_person_rule(app, fake_archive):
    app.settings.people = PEOPLE
    app.settings.address_zone = ZONE
    for r in list(app.rules):
        app.delete_rule(r.id)
    app.save_rule(person_rule(when={"person": "Michiel"}))
    add(app, fake_archive, f"{INBOX}/a.pdf", "a", "kela", addressed("Tiina Visser"))
    with make_client(app) as c:
        out = post(c, "/api/rules/explain", {"drive_id": "a"}).json()
    assert out[0]["matched"] is False and out[0]["why"] == "the document is not for Michiel"


def test_the_offer_after_a_filing_proposes_person_in_the_folder(app, fake_archive):
    from test_rules_offer import TEXT

    app.settings.people = PEOPLE
    app.settings.address_zone = ZONE
    for p in app.rules_dir.glob("*.yaml"):
        p.unlink()
    app.reload_rules()
    fake_archive.add("11. Bills/Tiina/2026/old.txt", content=b"old", drive_id="old")
    add(app, fake_archive, f"{INBOX}/lasku.pdf", "id-a", TEXT, addressed("Tiina Visser"))
    with make_client(app) as client:
        body = {
            "requests": [
                {
                    "drive_id": "id-a",
                    "name": "20261015_Fortum.pdf",
                    "folder": "11. Bills/Tiina/2026",
                }
            ]
        }
        r = post(client, "/api/inbox/file", body)
    assert r.status_code == 200, r.text
    assert r.json()["offer"]["draft"]["folder"] == "11. Bills/{person}/{year}"


def test_people_are_found_in_the_words_inside_the_box_not_the_whole_line():
    from dam.config import Person
    from dam.extract.layout import Line, Page1Layout, Word
    from dam.rules.people import detect_people

    line = Line(
        "Michiel Visser Tiina Visser",
        (0.1, 0.1, 0.9, 0.13),
        [
            Word("Michiel", (0.1, 0.1, 0.25, 0.13)),
            Word("Visser", (0.27, 0.1, 0.4, 0.13)),
            Word("Tiina", (0.6, 0.1, 0.75, 0.13)),
            Word("Visser", (0.77, 0.1, 0.9, 0.13)),
        ],
    )
    page = Page1Layout([line], "text-layer")
    people = [
        Person(name="Michiel", match=["Michiel Visser"]),
        Person(name="Tiina", match=["Tiina Visser"]),
    ]
    assert detect_people(page, (0.05, 0.05, 0.45, 0.2), people) == ["Michiel"]
    assert detect_people(page, (0, 0, 1, 1), people) == ["Michiel", "Tiina"]
