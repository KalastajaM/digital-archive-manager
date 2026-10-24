"""Zone conditions: text in an area of page 1, the lines-in-box endpoints, the draft from
a box and the replay with exact candidates."""

import pytest
import yaml

from dam.extract.base import ExtractedText
from dam.extract.layout import Line, Page1Layout
from dam.index.repo import FileRecord
from dam.index.scanner import scan
from dam.rules.engine import suggest
from dam.rules.learned import write_rules_file
from dam.rules.model import Rule, load_rules
from dam.rules.replay import NOT_READ, explain, replay
from test_api import make_client, post

INBOX = "##. Organize"
HEADER = (0.05, 0.02, 0.45, 0.14)


def zone_rule(word="pohjola", box=HEADER, **extra):
    return Rule.model_validate(
        {
            "id": "pohjola",
            "when": {"zone": {"box": list(box), "text_contains": [word]}, "folder_is": INBOX},
            "then": {"folder": "Insurance/Pohjola", "name": "{doc_date:%Y%m%d}_Pohjola"},
            **extra,
        }
    )


def layout(*lines):
    return Page1Layout([Line(t, b) for t, b in lines], "text-layer")


LETTER = layout(
    ("Pohjola Vakuutus", (0.08, 0.04, 0.30, 0.07)),
    ("Michiel Visser", (0.08, 0.20, 0.30, 0.22)),
    ("Maksu Pohjolaan", (0.08, 0.60, 0.40, 0.63)),
)


def add(app, fake_archive, rel, drive_id, text, page1=None):
    fake_archive.add(rel, content=drive_id.encode(), drive_id=drive_id)
    scan(app.paths, app.repo)
    app.repo.save_content(
        drive_id, f"sha-{drive_id}", ExtractedText(text, "test", False, page1), "indexed"
    )


def rec(path=f"{INBOX}/a.pdf", ext="pdf"):
    return FileRecord(drive_id="a", path=path, name=path.rsplit("/")[-1], ext=ext)


# --- the model ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "zone",
    [
        {"box": [0.1, 0.1, 0.05, 0.2], "text_contains": ["a"]},  # x0 >= x1
        {"box": [0.1, 0.3, 0.2, 0.2], "text_contains": ["a"]},  # y0 >= y1
        {"box": [-0.1, 0.1, 0.2, 0.2], "text_contains": ["a"]},
        {"box": [0.1, 0.1, 1.2, 0.2], "text_contains": ["a"]},
        {"box": [0.1, 0.1, 0.2], "text_contains": ["a"]},
        {"box": [0.1, 0.1, 0.2, 0.2], "text_contains": []},
        {"box": [0.1, 0.1, 0.2, 0.2], "text_contains": [" "]},
        {"box": [0.1, 0.1, 0.2, 0.2], "text_contains": ["a"], "extra": 1},
    ],
)
def test_a_bad_zone_is_refused(zone):
    with pytest.raises(ValueError):
        Rule.model_validate({"id": "x", "when": {"zone": zone}})


def test_old_rule_files_load_unchanged_and_a_zone_round_trips(tmp_path):
    (tmp_path / "old.yaml").write_text(
        "- id: old\n  when: {text_contains: [x], folder_is: '##. Organize'}\n  then: {tags: [t]}\n",
        encoding="utf-8",
    )
    rules, errors = load_rules(tmp_path)
    assert errors == [] and rules[0].when.zone is None
    path = tmp_path / "learned.yaml"
    write_rules_file(path, [zone_rule()])
    assert yaml.safe_load(path.read_text(encoding="utf-8"))[0]["when"]["zone"] == {
        "box": list(HEADER),
        "text_contains": ["pohjola"],
    }
    again, errors = load_rules(tmp_path)
    assert errors == [] and again[0].when.zone == zone_rule().when.zone


# --- matching -------------------------------------------------------------------------


def names(found):
    return [s.split(":")[1] for s in found.sources if s.startswith("rule:")]


def test_a_word_in_the_zone_matches_and_a_word_elsewhere_does_not():
    found = suggest(rec(), "pohjola vakuutus", [zone_rule()], layout=LETTER)
    assert found.folder == "Insurance/Pohjola" and found.folder_source == "rule:pohjola"
    assert not found.waiting_for_page1
    # "pohjolaan" is on the page, but not in the zone
    other = layout(("Maksu Pohjolaan", (0.08, 0.60, 0.40, 0.63)))
    assert suggest(rec(), "maksu pohjolaan", [zone_rule()], layout=other).folder is None


def test_matching_folds_case_and_diacritics_and_uses_the_margin():
    near = layout(("POHJOLA", (0.10, 0.155, 0.30, 0.175)))  # just under the box, in the margin
    assert suggest(rec(), "x", [zone_rule()], layout=near).folder == "Insurance/Pohjola"
    far = layout(("POHJOLA", (0.10, 0.30, 0.30, 0.32)))
    assert suggest(rec(), "x", [zone_rule()], layout=far).folder is None
    accent = layout(("Pöhjölä", (0.1, 0.04, 0.3, 0.07)))
    assert suggest(rec(), "x", [zone_rule("pohjola")], layout=accent).folder == "Insurance/Pohjola"


def test_no_layout_means_no_match_and_waiting():
    found = suggest(rec(), "pohjola", [zone_rule()])
    assert found.folder is None and found.waiting_for_page1 is True
    # read, but no text: a non-match that is final
    empty = suggest(rec(), "pohjola", [zone_rule()], layout=Page1Layout([], "text-layer"))
    assert empty.folder is None and empty.waiting_for_page1 is False


def test_waiting_only_when_the_other_conditions_hold():
    elsewhere = rec("10. Home/a.pdf")  # folder_is is the inbox
    assert suggest(elsewhere, "x", [zone_rule()]).waiting_for_page1 is False
    docx = rec(f"{INBOX}/a.docx", ext="docx")  # no page 1 will ever be read
    assert suggest(docx, "x", [zone_rule()]).waiting_for_page1 is False
    both = Rule.model_validate(
        {
            "id": "both",
            "when": {
                "text_contains": ["fortum"],
                "zone": {"box": list(HEADER), "text_contains": ["a"]},
            },
        }
    )
    assert suggest(rec(), "nothing", [both]).waiting_for_page1 is False
    assert suggest(rec(), "fortum", [both]).waiting_for_page1 is True


def test_all_conditions_still_have_to_match():
    both = Rule.model_validate(
        {
            "id": "both",
            "when": {
                "text_contains": ["fortum"],
                "zone": {"box": list(HEADER), "text_contains": ["pohjola"]},
            },
            "then": {"tags": ["t"]},
        }
    )
    assert suggest(rec(), "fortum", [both], layout=LETTER).tags == ["t"]
    assert suggest(rec(), "other", [both], layout=LETTER).tags == []


# --- explain --------------------------------------------------------------------------


def test_explain_says_what_is_in_the_zone(app):
    out = explain(rec(), "pohjola", [zone_rule()], app.settings.special_folders, None, LETTER)
    assert out[0].matched and "in the area" in out[0].why
    assert out[0].zone_lines == ["Pohjola Vakuutus"]
    miss = explain(
        rec(), "pohjola", [zone_rule("fortum")], app.settings.special_folders, None, LETTER
    )
    assert not miss[0].matched and miss[0].why == "no word found in the area"
    unread = explain(rec(), "pohjola", [zone_rule()], app.settings.special_folders, None, None)
    assert unread[0].why == "page 1 has not been read yet"


# --- the inbox ------------------------------------------------------------------------


def test_the_inbox_suggests_from_the_zone_and_asks_for_unread_pages(app, fake_archive):
    app.save_rule(zone_rule())
    add(app, fake_archive, f"{INBOX}/a.pdf", "a", "pohjola vakuutus", LETTER)
    add(app, fake_archive, f"{INBOX}/b.pdf", "b", "pohjola vakuutus")
    entries = {e.record.drive_id: e for e in app.inbox.list()}
    assert entries["a"].suggestion.folder == "Insurance/Pohjola"
    assert entries["b"].suggestion.folder is None and entries["b"].suggestion.waiting_for_page1
    assert "b" in app.content._wanted and "a" not in app.content._wanted


def test_inbox_api_has_waiting_for_page1(app, fake_archive):
    app.save_rule(zone_rule())
    add(app, fake_archive, f"{INBOX}/b.pdf", "b", "pohjola vakuutus")
    with make_client(app) as c:
        entry = c.get("/api/inbox").json()[0]
    assert entry["suggestion"]["waiting_for_page1"] is True


# --- the lines endpoints ---------------------------------------------------------------


def test_page1_endpoint_gives_lines_or_queues_a_read(app, fake_archive):
    add(app, fake_archive, f"{INBOX}/a.pdf", "a", "x", LETTER)
    add(app, fake_archive, f"{INBOX}/b.pdf", "b", "x")
    add(app, fake_archive, f"{INBOX}/c.docx", "c", "x")
    with make_client(app) as c:
        got = c.get("/api/files/a/page1").json()
        assert got["read"] is True and got["unavailable"] is None
        assert got["lines"][0] == {"text": "Pohjola Vakuutus", "box": [0.08, 0.04, 0.3, 0.07]}
        unread = c.get("/api/files/b/page1").json()
        assert unread == {"read": False, "lines": [], "unavailable": None}
        assert "b" in app.content._wanted
        docx = c.get("/api/files/c/page1").json()
        assert docx["read"] is False and "no page 1" in docx["unavailable"]
        assert c.get("/api/files/nope/page1").status_code == 404


def test_lines_in_a_box_use_the_matching_rule(app, fake_archive):
    add(app, fake_archive, f"{INBOX}/a.pdf", "a", "x", LETTER)
    with make_client(app) as c:
        r = post(c, "/api/files/a/page1/lines", {"box": list(HEADER)})
        assert r.status_code == 200
        assert [ln["text"] for ln in r.json()["lines"]] == ["Pohjola Vakuutus"]
        wide = post(c, "/api/files/a/page1/lines", {"box": [0, 0, 1, 0.3]}).json()
        assert [ln["text"] for ln in wide["lines"]] == ["Pohjola Vakuutus", "Michiel Visser"]
        assert post(c, "/api/files/a/page1/lines", {"box": [0.5, 0.5, 0.2, 0.2]}).status_code == 400
        assert post(c, "/api/files/a/page1/lines", {"box": [0, 0, 2, 1]}).status_code == 400
        assert post(c, "/api/files/a/page1/lines", {"box": [0, 0, 1]}).status_code in (400, 422)


# --- the draft from a box -----------------------------------------------------------------


def seed_frequency(app, fake_archive, n=8):
    for i in range(n):
        add(app, fake_archive, f"30. Other/{i}.pdf", f"o{i}", f"lasku maksu number{i}")


def test_draft_zone_for_an_inbox_document(app, fake_archive):
    seed_frequency(app, fake_archive)
    add(app, fake_archive, f"{INBOX}/a.pdf", "a", "pohjola vakuutus oy", LETTER)
    with make_client(app) as c:
        r = post(
            c, "/api/rules/draft-zone", {"drive_id": "a", "box": list(HEADER), "sender": "Pohjola"}
        )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["box"] == list(HEADER) and d["folder_is"] == INBOX and d["sender"] == "Pohjola"
    assert d["lines"] == ["Pohjola Vakuutus"]
    assert [w["word"] for w in d["words"]] == ["pohjola", "vakuutus"]
    assert [w["ticked"] for w in d["words"]].count(True) == 1
    assert d["folder"] is None and d["name"] is None and d["id"] == "pohjola"


def test_draft_zone_for_a_filed_document_gives_its_folder_and_name(app, fake_archive):
    seed_frequency(app, fake_archive)
    add(app, fake_archive, "11. Bills/2026/20260210_Pohjola.pdf", "a", "pohjola x", LETTER)
    app.tags.add("a", ["insurance"])
    with make_client(app) as c:
        d = post(c, "/api/rules/draft-zone", {"drive_id": "a", "box": list(HEADER)}).json()
    assert d["folder"] == "11. Bills/{year}"
    assert d["name"] == "{doc_date:%Y%m%d}_Pohjola"
    assert d["tags"] == ["insurance"] and d["folder_is"] == INBOX


def test_draft_zone_refusals(app, fake_archive):
    add(app, fake_archive, f"{INBOX}/a.pdf", "a", "x", LETTER)
    add(app, fake_archive, f"{INBOX}/b.pdf", "b", "x")
    with make_client(app) as c:
        unread = post(c, "/api/rules/draft-zone", {"drive_id": "b", "box": list(HEADER)})
        assert unread.status_code == 400 and "not been read" in unread.json()["error"]
        empty = post(c, "/api/rules/draft-zone", {"drive_id": "a", "box": [0.6, 0.8, 0.9, 0.9]})
        assert empty.status_code == 400 and "no text" in empty.json()["error"]
        assert (
            post(c, "/api/rules/draft-zone", {"drive_id": "nope", "box": list(HEADER)}).status_code
            == 404
        )
        assert (
            post(
                c, "/api/rules/draft-zone", {"drive_id": "a", "box": [0.5, 0.5, 0.1, 0.1]}
            ).status_code
            == 400
        )


# --- the replay ------------------------------------------------------------------------------


def fill(app, fake_archive):
    add(
        app, fake_archive, "Insurance/Pohjola/20250110_Pohjola.pdf", "a", "Pohjola vakuutus", LETTER
    )
    # the word is on the page, but outside the zone
    other = layout(("Maksu Pohjolaan", (0.08, 0.60, 0.40, 0.63)))
    add(app, fake_archive, "10. Bank/statement.pdf", "b", "Maksu Pohjolaan", other)
    # right word, page 1 not read yet
    add(app, fake_archive, "20. Home/20260301_Letter.pdf", "c", "Pohjola kirje")
    add(app, fake_archive, "20. Home/notes.pdf", "d", "nothing relevant")
    add(app, fake_archive, f"{INBOX}/new.pdf", "e", "pohjola uusi", LETTER)


def test_replay_looks_at_candidates_only_and_never_counts_unread_as_non_match(app, fake_archive):
    fill(app, fake_archive)
    wanted = []
    r = replay(
        app.engine,
        zone_rule(),
        [zone_rule()],
        app.settings.special_folders,
        layouts_for=app.repo.layouts_for,
        want_layouts=wanted.extend,
    )
    assert (r.matched, r.inbox) == (1, 1)
    assert r.same == 1 and r.different == []
    assert [(n.path, n.reason) for n in r.not_checked] == [
        ("20. Home/20260301_Letter.pdf", NOT_READ)
    ]
    assert r.reading == 1 and wanted == ["c"]
    assert r.total == 4 and r.checked == 3 and not r.truncated  # 4 filed, 1 not checked


def test_replay_reasons_come_from_the_indexer(app, fake_archive):
    fill(app, fake_archive)
    r = replay(
        app.engine,
        zone_rule(),
        [zone_rule()],
        app.settings.special_folders,
        layouts_for=app.repo.layouts_for,
        layout_blocked=lambda drive_id: "no OCR engine",
    )
    assert [n.reason for n in r.not_checked] == ["no OCR engine"] and r.reading == 0


def test_replay_api_shape_queues_reads_and_wakes_the_indexer(app, fake_archive):
    fill(app, fake_archive)
    woken = []
    app.wake_indexer = lambda: woken.append(1)
    body = {
        "rule": {
            "id": "pohjola",
            "when": {"zone": {"box": list(HEADER), "text_contains": ["pohjola"]}},
            "then": {"folder": "Insurance/Pohjola"},
        }
    }
    with make_client(app) as c:
        data = post(c, "/api/rules/replay", body).json()
    assert data["not_checked"] == [{"path": "20. Home/20260301_Letter.pdf", "reason": NOT_READ}]
    assert data["reading"] == 1 and woken and "c" in app.content._wanted
    # once page 1 is read the document is checked
    app.repo.save_layout("c", "sha-c", LETTER)
    with make_client(app) as c:
        again = post(c, "/api/rules/replay", body).json()
    assert again["not_checked"] == [] and again["reading"] == 0 and again["matched"] == 2


def test_replay_of_a_plain_rule_is_unchanged(app, fake_archive):
    fill(app, fake_archive)
    rule = Rule.model_validate({"id": "p", "when": {"text_contains": ["pohjola"]}})
    r = replay(app.engine, rule, [rule], app.settings.special_folders)
    assert r.not_checked == [] and r.reading == 0 and r.matched == 3
