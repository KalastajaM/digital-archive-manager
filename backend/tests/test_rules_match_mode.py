"""How an area's words match: starts a word, whole word, or anywhere."""

import pytest
import yaml

from dam.core.text import fold
from dam.rules.engine import suggest, zone_matches
from dam.rules.learned import write_rules_file
from dam.rules.model import Rule, TermTest, load_rules
from dam.rules.replay import explain, replay
from test_rules_zone import HEADER, INBOX, add, layout, rec


def zone_rule(word, mode=None, rid="r"):
    zone = {"box": list(HEADER), "text_contains": [word]}
    if mode is not None:
        zone["match"] = mode
    return Rule.model_validate(
        {"id": rid, "when": {"zones": [zone], "folder_is": INBOX}, "then": {"folder": "X"}}
    )


def hits(word, mode, text):
    return TermTest(fold(word), mode)(fold(text))


# word, text, (word_start, whole_word, anywhere)
CASES = [
    ("kela", "Kela", (1, 1, 1)),
    ("kela", "Kelan", (1, 0, 1)),
    ("kela", "Kelalta", (1, 0, 1)),
    ("kela", "Kela.", (1, 1, 1)),
    ("kela", "(Kela)", (1, 1, 1)),
    ("kela", "Kela/Fimea", (1, 1, 1)),
    ("kela", "Ukela", (0, 0, 1)),
    ("vakuutus", "Henkivakuutus", (0, 0, 1)),
    ("vakuutus", "Vakuutuskirja", (1, 0, 1)),
    ("vakuutus", "Vakuutus", (1, 1, 1)),
    ("op", "OP-Pohjola", (1, 1, 1)),
    ("pohjola", "OP-Pohjola", (1, 1, 1)),
    ("op-pohjola", "OP-Pohjola Oyj", (1, 1, 1)),
    ("op-pohjola", "XOP-Pohjola", (0, 0, 1)),
    ("lasku", "Laskunumero 12", (1, 0, 1)),
    ("lasku", "Myyntilasku", (0, 0, 1)),
    ("12", "Lasku 123", (1, 0, 1)),
    ("12", "Lasku 12", (1, 1, 1)),
    ("12", "Lasku A12", (0, 0, 1)),  # digits are word characters
    ("12", "viite_12", (1, 1, 1)),  # an underscore is not a letter or digit: a boundary
    ("maksu pohjolaan", "Maksu Pohjolaan", (1, 1, 1)),
    ("maksu pohjolaan", "Maksu Pohjolaantie", (1, 0, 1)),
    ("maksu pohjolaan", "Tilimaksu Pohjolaan", (0, 0, 1)),
    ("maksu pohjolaan", "Maksu  Pohjolaan", (0, 0, 0)),  # words in sequence as written
    ("ääni", "Ääni ja kuva", (1, 1, 1)),
    ("ääni", "Äänite", (1, 0, 1)),
    ("åke", "Åkerman", (1, 0, 1)),
]


@pytest.mark.parametrize(("word", "text", "expected"), CASES)
def test_each_mode_against_examples(word, text, expected):
    got = tuple(int(hits(word, m, text)) for m in ("word_start", "whole_word", "anywhere"))
    assert got == expected


def test_a_term_ending_in_punctuation_needs_no_boundary_after_it():
    assert hits("oy.", "whole_word", "Pohjola Oy. Helsinki")
    assert hits("oy.", "whole_word", "Pohjola Oy.Helsinki")


def test_a_zone_without_match_behaves_as_before():
    z = zone_rule("vakuutus").when.zones[0]
    assert z.match == "anywhere"
    found = layout(("Henkivakuutus", (0.1, 0.04, 0.3, 0.07)))
    assert suggest(rec(), "henkivakuutus", [zone_rule("vakuutus")], layout=found).folder == "X"
    start = zone_rule("vakuutus", "word_start")
    assert suggest(rec(), "henkivakuutus", [start], layout=found).folder is None


def test_live_matching_uses_the_mode_of_the_zone():
    page = layout(("Kelan etuus", (0.08, 0.04, 0.30, 0.07)))
    assert zone_matches(zone_rule("kela", "word_start"), 0, page)
    assert not zone_matches(zone_rule("kela", "whole_word"), 0, page)
    assert zone_matches(zone_rule("kela", "anywhere"), 0, page)


def test_the_full_text_pre_filter_uses_the_same_mode():
    # the pre-filter must not hold back a document the lines would match, and must not let
    # a document through whose text cannot match
    page = layout(("Kelan etuus", (0.08, 0.04, 0.30, 0.07)))
    ok = suggest(rec(), "kelan etuus", [zone_rule("kela", "word_start")], layout=page)
    assert ok.folder == "X"
    no = suggest(rec(), "ukelan etuus", [zone_rule("kela", "word_start")], layout=page)
    assert no.folder is None and not no.waiting_for_page1


def test_explain_names_the_word_that_matched_by_mode():
    page = layout(("Henkivakuutus Kelalta", (0.08, 0.04, 0.30, 0.07)))
    rule = zone_rule("vakuutus", "word_start")
    out = explain(rec(), "henkivakuutus kelalta", [rule], None, None, layout=page)[0]
    assert not out.matched and "no word found" in out.why
    assert out.areas[0].lines == []
    rule = zone_rule("vakuutus", "anywhere")
    out = explain(rec(), "henkivakuutus kelalta", [rule], None, None, layout=page)[0]
    assert out.matched and len(out.areas[0].lines) == 1


def test_match_is_written_only_when_not_the_default(tmp_path):
    path = tmp_path / "learned.yaml"
    rules = [zone_rule("a", "word_start", "one"), zone_rule("b", "whole_word", "two")]
    rules.append(zone_rule("c", "anywhere", "three"))
    rules.append(zone_rule("d", None, "four"))
    write_rules_file(path, rules)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    modes = [r["when"]["zones"][0].get("match") for r in data]
    assert modes == ["word_start", "whole_word", None, None]
    again, errors = load_rules(tmp_path)
    assert errors == []
    assert [r.when.zones[0].match for r in again] == [
        "word_start",
        "whole_word",
        "anywhere",
        "anywhere",
    ]


def test_a_picture_area_takes_no_match_mode():
    with pytest.raises(ValueError, match="match is for"):
        Rule.model_validate(
            {
                "id": "p",
                "when": {
                    "zones": [
                        {
                            "box": [0.1, 0.1, 0.2, 0.2],
                            "image": "areas/p-1.png",
                            "match": "whole_word",
                        }
                    ]
                },
            }
        )
    with pytest.raises(ValueError):
        zone_rule("a", "sometimes")


TEXTS = [
    "Kela",
    "Kelan päätös",
    "Henkivakuutus",
    "Vakuutuskirja",
    "OP-Pohjola Vakuutus",
    "Ukela",
    "Vakuutus 12",
]


@pytest.mark.parametrize("mode", ["word_start", "whole_word", "anywhere"])
@pytest.mark.parametrize("word", ["kela", "vakuutus"])
def test_replay_counts_equal_live_matching(app, fake_archive, mode, word):
    rule = zone_rule(word, mode)
    expected = 0
    for n, text in enumerate(TEXTS):
        page = layout((text, (0.08, 0.04, 0.30, 0.07)))
        add(app, fake_archive, f"10. Bank/d{n}.pdf", f"d{n}", text.lower(), page)
        expected += zone_matches(rule, 0, page)
    result = replay(
        app.engine,
        rule,
        [rule],
        app.settings.special_folders,
        layouts_for=app.repo.layouts_for,
        want_layouts=lambda ids: None,
    )
    assert result.matched == expected
    assert expected == sum(hits(word, mode, t) for t in TEXTS)
