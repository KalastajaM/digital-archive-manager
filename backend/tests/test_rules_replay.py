"""Replaying a rule against the files already filed, and explaining which rule files one."""

from dam.extract.base import ExtractedText
from dam.index.repo import FileRecord
from dam.index.scanner import scan
from dam.rules.model import Rule
from dam.rules.replay import explain, replay

INBOX = "##. Organize"
FORTUM_RULE = {
    "id": "fortum",
    "when": {"text_contains": ["fortum"], "folder_is": INBOX},
    "then": {"folder": "11. Bills/{year}", "name": "{doc_date:%Y%m%d}_Fortum"},
}


def add_filed(app, fake_archive, rel, drive_id, text):
    fake_archive.add(rel, content=drive_id.encode(), drive_id=drive_id)
    scan(app.paths, app.repo)
    app.repo.save_content(drive_id, None, ExtractedText(text, "test"), "indexed")


def test_replay_counts_same_and_different(app, fake_archive):
    add_filed(app, fake_archive, "11. Bills/2025/20250110_Fortum.pdf", "a", "Fortum")
    add_filed(app, fake_archive, "11. Bills/2026/20260210_Fortum.pdf", "b", "Fortum")
    add_filed(app, fake_archive, "20. Home/20260301_Fortum.pdf", "c", "Fortum")
    add_filed(app, fake_archive, f"{INBOX}/20260401_Fortum.pdf", "d", "Fortum")
    add_filed(app, fake_archive, "20. Home/20260301_Other.pdf", "e", "Nothing relevant")
    rule = Rule.model_validate(FORTUM_RULE)
    r = replay(app.engine, rule, [rule], app.settings.special_folders)
    assert (r.matched, r.same, r.inbox) == (3, 2, 1)
    assert [h.path_rule for h in r.different] == ["11. Bills/2026/20260301_Fortum.pdf"]
    assert r.different[0].path_now == "20. Home/20260301_Fortum.pdf"
    assert (r.checked, r.total, r.truncated) == (r.total, r.total, False)
    assert r.shadowed == []


def test_replay_without_dates_never_crashes(app, fake_archive):
    add_filed(app, fake_archive, "20. Home/fortum.pdf", "a", "Fortum")
    rule = Rule.model_validate(FORTUM_RULE)
    r = replay(app.engine, rule, [rule], app.settings.special_folders)
    assert r.matched == 1 and r.same == 0
    assert [(h.drive_id, h.path_rule) for h in r.different] == [("a", "")]


def test_replay_reports_an_earlier_rule_winning(app, fake_archive):
    add_filed(app, fake_archive, "11. Bills/2026/20260210_Fortum.pdf", "a", "Fortum invoice")
    generic = Rule.model_validate(
        {"id": "invoice", "when": {"text_contains": ["invoice"]}, "then": {"folder": "99. Misc"}}
    )
    tags_only = Rule.model_validate(
        {"id": "tagger", "when": {"text_contains": ["fortum"]}, "then": {"tags": ["x"]}}
    )
    rule = Rule.model_validate(FORTUM_RULE)
    r = replay(app.engine, rule, [tags_only, generic, rule], app.settings.special_folders)
    assert r.shadowed == [("a", "invoice")]
    later = replay(app.engine, rule, [rule, generic], app.settings.special_folders)
    assert later.shadowed == []


def test_replay_stops_at_the_budget(app, fake_archive):
    add_filed(app, fake_archive, "20. Home/20260301_Fortum.pdf", "a", "Fortum")
    add_filed(app, fake_archive, "20. Home/20260302_Fortum.pdf", "b", "Fortum")
    rule = Rule.model_validate(FORTUM_RULE)
    r = replay(app.engine, rule, [rule], app.settings.special_folders, budget_s=0)
    assert (r.checked, r.total, r.truncated, r.matched) == (0, 2, True, 0)


def test_explain_says_which_word_matched_and_what_wins(app, fake_archive):
    special = app.settings.special_folders
    fortum = Rule.model_validate(FORTUM_RULE)
    other = Rule.model_validate(
        {"id": "nope", "when": {"text_contains": ["zzz"]}, "then": {"folder": "1. X"}}
    )
    namey = Rule.model_validate({"id": "namey", "when": {"filename_matches": "(?i)^abc"}})
    rec = FileRecord(drive_id="x", path=f"{INBOX}/invoice.pdf")
    out = {
        e.rule_id: e
        for e in explain(rec, "Your Fortum bill 15.11.2026", [fortum, other, namey], special, None)
    }
    assert out["fortum"].matched and out["fortum"].why == "word ‘fortum’"
    assert out["fortum"].wins == ["folder", "name"]
    assert not out["nope"].matched and out["nope"].why == "no word found" and out["nope"].wins == []
    assert not out["namey"].matched and out["namey"].why.startswith("file name")
    elsewhere = FileRecord(drive_id="y", path="20. Home/invoice.pdf")
    e = explain(elsewhere, "Fortum", [fortum], special, None)[0]
    assert not e.matched and e.why == "not in the inbox"
