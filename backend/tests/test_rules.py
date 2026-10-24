import time
from datetime import date, datetime
from pathlib import Path

import pytest

from dam.index.repo import FileRecord
from dam.rules.engine import fold, suggest
from dam.rules.model import Rule, load_rules

INBOX = "##. Organize"
DEFAULTS = Path(__file__).resolve().parents[2] / "defaults" / "rules"


def rec(name: str, folder: str = INBOX, mtime: float | None = None) -> FileRecord:
    path = f"{folder}/{name}" if folder else name
    return FileRecord(drive_id="id", path=path, mtime=mtime)


def rule(id: str = "r", when: dict | None = None, **then) -> Rule:
    return Rule.model_validate({"id": id, "when": when or {}, "then": then})


APTEEKKI = rule(
    "apteekki-receipts",
    {"text_contains": ["apteekki"], "folder_is": INBOX},
    folder="11. Bills & Receipts/{doc_date:%Y}",
    name="{doc_date:%Y%m%d}_Apteekki",
    tags=["receipt"],
)


def test_keeps_conventional_name():
    s = suggest(rec("20260105_Vuokra.PDF"), "", [])
    assert s.name == "20260105_Vuokra.pdf"
    assert s.doc_date == date(2026, 1, 5)
    assert "filename-date" in s.sources


def test_conventional_name_wins_over_rule_name_but_folder_applies():
    s = suggest(rec("20260105_Vuokra.pdf"), "Apteekki", [APTEEKKI])
    assert s.name == "20260105_Vuokra.pdf"
    assert s.folder == "11. Bills & Receipts/2026"


def test_rule_renames_and_folders():
    s = suggest(rec("scan.pdf"), "Apteekki Oy 9.10.2026 Yhteensä 12,50 €", [APTEEKKI])
    assert s.folder == "11. Bills & Receipts/2026"
    assert s.name == "20261009_Apteekki.pdf"
    assert s.tags == ["receipt"]
    assert s.sources == ["text-date", "rule:apteekki-receipts"]
    assert s.doc_date == date(2026, 10, 9)


def test_rule_name_with_extension_not_doubled():
    r = rule(when={"text_contains": ["x"]}, name="{doc_date:%Y%m%d}_X.PDF")
    assert suggest(rec("a.pdf"), "x 1.2.2026", [r]).name == "20260201_X.pdf"


def test_fallback_name_from_text_date():
    s = suggest(rec("File_000.pdf"), "Päiväys 13.10.2026", [])
    assert s.name == "20261013_File_000.pdf"
    assert s.sources == ["text-date"]


def test_fallback_cleans_stem():
    s = suggest(rec("My  scan (2).PDF"), "13.10.2026", [])
    assert s.name == "20261013_My_scan.pdf"
    assert suggest(rec("__a__b(3).jpg"), "13.10.2026", []).name == "20261013_a_b.jpg"


def test_fallback_does_not_double_date():
    s = suggest(rec("20260105 Vuokra.pdf"), "13.10.2026", [])
    assert s.name == "20260105_Vuokra.pdf"
    assert s.doc_date == date(2026, 1, 5)


def test_doc_date_falls_back_to_mtime_local():
    ts = datetime(2025, 3, 4, 12, 0).timestamp()
    s = suggest(rec("a.pdf", mtime=ts), "", [])
    assert s.doc_date == date(2025, 3, 4)
    assert s.name == "20250304_a.pdf"
    assert s.sources == ["mtime"]


def test_no_date_at_all_keeps_clean_stem():
    s = suggest(rec("a b.pdf"), "", [])
    assert s.doc_date is None and s.name == "a_b.pdf"


def test_tags_union_and_first_folder_wins():
    r1 = rule("one", {"text_contains": ["a"]}, folder="F1", tags=["x", "y"])
    r2 = rule("two", {"text_contains": ["a"]}, folder="F2", tags=["y", "z"])
    s = suggest(rec("f.pdf"), "a", [r1, r2])
    assert s.folder == "F1" and s.tags == ["x", "y", "z"]
    assert s.sources[-2:] == ["rule:one", "rule:two"]


def test_template_unknown_key_ignored():
    bad = rule("bad", {"text_contains": ["a"]}, folder="{nope}", name="{nope}_x", tags=["t"])
    s = suggest(rec("f.pdf"), "a 1.2.2026", [bad])
    assert s.folder is None
    assert s.name == "20260201_f.pdf"
    assert "rule:bad (template error)" in s.sources
    assert s.tags == ["t"]


@pytest.mark.parametrize(
    "template",
    [
        "{doc_date.year}",
        "{doc_date.__class__}",
        "{stem[0]}",
        "{stem!r}",
        "{stem!s}",
        "{0}",
        "{}",
        "{doc_date:{stem}}",
        "{stem:>99999999}",
        "{stem",
        "{year.real}",
    ],
)
def test_template_traversal_rejected(template):
    bad = rule("bad", {"text_contains": ["a"]}, folder=template, name=template)
    s = suggest(rec("f.pdf"), "a 1.2.2026", [bad])
    assert s.folder is None
    assert s.name == "20260201_f.pdf"
    assert s.sources[-1] == "rule:bad (template error)"


@pytest.mark.parametrize("folder", ["../x", "/abs", "a//b", "a/", "a/./b", "{stem}/../.."])
def test_unsafe_folder_is_template_error(folder):
    bad = rule("bad", {"text_contains": ["a"]}, folder=folder)
    s = suggest(rec("f.pdf"), "a", [bad])
    assert s.folder is None
    assert s.sources[-1] == "rule:bad (template error)"


def test_missing_doc_date_makes_date_template_error():
    r = rule("r", {"text_contains": ["a"]}, folder="Y/{year}")
    s = suggest(rec("f.pdf"), "a", [r])
    assert s.folder is None and s.sources == ["rule:r (template error)"]


def test_failed_first_rule_falls_through_to_next():
    bad = rule("bad", {"text_contains": ["a"]}, folder="{nope}")
    good = rule("good", {"text_contains": ["a"]}, folder="Fine")
    assert suggest(rec("f.pdf"), "a", [bad, good]).folder == "Fine"


def test_text_contains_ignores_case_and_diacritics():
    r = rule(when={"text_contains": ["lääkäri"]}, folder="M")
    assert suggest(rec("f.pdf"), "LAAKARI Oy", [r]).folder == "M"
    r2 = rule(when={"text_contains": ["LAAKARI"]}, folder="M")
    assert suggest(rec("f.pdf"), "lääkäri", [r2]).folder == "M"
    assert suggest(rec("f.pdf"), "muu", [r]).folder is None
    assert fold("Ä\u0308ß") == "ass"


def test_filename_matches_uses_users_flags():
    ci = rule(when={"filename_matches": "(?i)apteek"}, folder="A")
    cs = rule(when={"filename_matches": "apteek"}, folder="A")
    assert suggest(rec("APTEEKKI.pdf"), "", [ci]).folder == "A"
    assert suggest(rec("APTEEKKI.pdf"), "", [cs]).folder is None
    assert suggest(rec("my_apteekki.pdf"), "", [cs]).folder == "A"


def test_folder_is_nfc_and_case_insensitive():
    r = rule(when={"folder_is": "##. ORGANIZE"}, folder="A")
    assert suggest(rec("f.pdf"), "", [r]).folder == "A"
    assert suggest(rec("f.pdf", folder="other"), "", [r]).folder is None
    assert suggest(rec("f.pdf", folder="##. Organize/sub"), "", [r]).folder is None
    nfd = rule(when={"folder_is": "Lääkkeet"}, folder="A")
    r_nfd = rec("f.pdf", folder="Lääkkeet")
    assert suggest(r_nfd, "", [nfd]).folder == "A"


def test_empty_when_matches_everything():
    assert suggest(rec("f.pdf"), "", [rule(folder="All")]).folder == "All"


# -- loading -----------------------------------------------------------------


def write(d: Path, name: str, text: str) -> None:
    (d / name).write_text(text, encoding="utf-8")


def test_invalid_rule_file_reported_others_load(tmp_path):
    write(tmp_path, "10-good.yaml", "- id: a\n  then: {folder: X}\n")
    write(tmp_path, "20-bad-yaml.yaml", "- id: [unclosed\n")
    write(tmp_path, "30-not-list.yaml", "id: a\n")
    write(tmp_path, "40-bad-rule.yaml", "- id: ok\n- id: b\n  when:\n    filename_matches: '('\n")
    write(tmp_path, "50-unknown-key.yml", "- id: c\n  wehn: {}\n")
    write(tmp_path, "05-first.yaml", "- id: z\n")
    write(tmp_path, "readme.txt", "ignored")
    rules, errors = load_rules(tmp_path)
    assert [r.id for r in rules] == ["z", "a"]
    by_file = {e.file: e.message for e in errors}
    assert set(by_file) == {
        "20-bad-yaml.yaml",
        "30-not-list.yaml",
        "40-bad-rule.yaml",
        "50-unknown-key.yml",
    }
    assert "line" in by_file["20-bad-yaml.yaml"]
    assert "list" in by_file["30-not-list.yaml"]
    assert "line 2" in by_file["40-bad-rule.yaml"] and "regex" in by_file["40-bad-rule.yaml"]
    assert "line 1" in by_file["50-unknown-key.yml"]


def test_load_rules_missing_dir_and_empty_file(tmp_path):
    assert load_rules(tmp_path / "nope") == ([], [])
    write(tmp_path, "a.yaml", "")
    rules, errors = load_rules(tmp_path)
    assert rules == [] and len(errors) == 1


def test_default_examples_load_and_match():
    rules, errors = load_rules(DEFAULTS)
    assert errors == []
    assert len(rules) >= 2
    s = suggest(rec("scan.pdf", mtime=time.time()), "Keskus Apteekki 9.10.2026", rules)
    assert s.name == "20261009_Apteekki.pdf"
    assert s.folder == "11. Bills & Receipts/2026"


# -- fix round 1 --------------------------------------------------------------


def test_original_redos_pattern_is_fast():
    r = rule("evil", {"filename_matches": "(a+)+$"}, folder="X")
    t = time.monotonic()
    assert suggest(rec("a" * 40 + "!.pdf"), "", [r]).folder is None
    assert time.monotonic() - t < 1.0


def test_catastrophic_regex_times_out_quickly():
    # `regex` shortcuts (a+)+$ but still backtracks exponentially on this alternation
    r = rule("evil", {"filename_matches": "(a|aa)+$"}, folder="X")
    t = time.monotonic()
    s = suggest(rec("a" * 40 + "!.pdf"), "", [r])
    assert time.monotonic() - t < 1.5
    assert s.folder is None
    assert "rule:evil (regex timeout)" in s.sources


def test_invalid_regex_rejected_at_load(tmp_path):
    write(tmp_path, "a.yaml", "- id: a\n  when: {filename_matches: '(?P<'}\n")
    assert len(load_rules(tmp_path)[1]) == 1


def test_bogus_mtime_gives_no_date():
    s = suggest(rec("a.pdf", mtime=1e30), "", [])
    assert s.doc_date is None and s.name == "a.pdf"


@pytest.mark.parametrize("tpl", [".hidden", "~$tmp", "a\nb", "a\x00b", "a\x1fb", "/x", ".."])
def test_unsafe_rendered_name_is_template_error(tpl):
    r = rule("r", {"text_contains": ["a"]}, name=tpl)
    s = suggest(rec("f.pdf"), "a 1.2.2026", [r])
    assert s.name == "20260201_f.pdf"
    assert s.sources[-1] == "rule:r (template error)"


def test_double_dot_before_extension_collapsed():
    r = rule("r", {"text_contains": ["a"]}, name="foo.")
    assert suggest(rec("f.pdf"), "a", [r]).name == "foo.pdf"


def test_fallback_name_sanitised():
    assert suggest(rec("~$doc.pdf"), "1.2.2026", []).name == "20260201_doc.pdf"
    assert suggest(rec("a\x07b\x00c.pdf"), "1.2.2026", []).name == "20260201_abc.pdf"


def test_name_truncated_to_255_bytes():
    s = suggest(rec("ä" * 200 + ".pdf"), "1.2.2026", [])
    assert len(s.name.encode()) <= 255 and s.name.endswith(".pdf")
    assert s.name.startswith("20260201_ä")
    r = rule("r", {"text_contains": ["a"]}, name="x" * 400)
    assert len(suggest(rec("f.pdf"), "a", [r]).name.encode()) <= 255


@pytest.mark.parametrize(
    "folder",
    ["##. To Delete", "##. to delete/x/{year}", "##. Organize/sub", "##. ORGANIZE"],
)
def test_folder_in_quarantine_or_inbox_is_template_error(folder):
    r = rule("r", {"text_contains": ["a"]}, folder=folder)
    s = suggest(rec("f.pdf"), "a 1.2.2026", [r])
    assert s.folder is None and s.sources[-1] == "rule:r (template error)"


def test_special_folders_follow_settings():
    from dam.config import SpecialFolders

    r = rule("r", {"text_contains": ["a"]}, folder="Inbox2")
    sp = SpecialFolders(inbox="Inbox2")
    assert suggest(rec("f.pdf"), "a", [r], sp).folder is None
    assert suggest(rec("f.pdf"), "a", [r]).folder == "Inbox2"


def test_nul_in_folder_is_template_error():
    r = rule("r", {"text_contains": ["a"]}, folder="A\x00B")
    assert suggest(rec("f.pdf"), "a", [r]).folder is None


def test_when_null_and_then_null(tmp_path):
    write(tmp_path, "a.yaml", "- id: a\n  when: null\n  then:\n    folder: X\n")
    rules, errors = load_rules(tmp_path)
    assert errors == [] and rules[0].when.folder_is is None


def test_duplicate_ids_across_files_later_file_errors(tmp_path):
    write(tmp_path, "10-a.yaml", "- id: dup\n- id: other\n")
    write(tmp_path, "20-b.yaml", "- id: fresh\n- id: dup\n")
    rules, errors = load_rules(tmp_path)
    assert [r.id for r in rules] == ["dup", "other"]
    assert errors[0].file == "20-b.yaml" and "duplicate id" in errors[0].message


def test_duplicate_ids_within_file_error(tmp_path):
    write(tmp_path, "a.yaml", "- id: x\n- id: x\n")
    rules, errors = load_rules(tmp_path)
    assert rules == [] and "duplicate id" in errors[0].message


def test_invalid_rule_message_says_file_skipped(tmp_path):
    write(tmp_path, "a.yaml", "- id: ok\n- id: b\n  bogus: 1\n")
    rules, errors = load_rules(tmp_path)
    assert rules == [] and "skipped" in errors[0].message


def test_rule_precomputes_matchers():
    r = rule(when={"text_contains": ["Lääkäri"], "filename_matches": "x"})
    assert r._folded_terms == ["laakari"]
    assert r._regex is not None


def test_deeply_nested_rules_file_reported_and_siblings_load(tmp_path):
    write(tmp_path, "10-deep.yaml", "- id: d\n  then: " + "[" * 20000)
    write(tmp_path, "20-good.yaml", "- id: good\n")
    rules, errors = load_rules(tmp_path)
    assert [r.id for r in rules] == ["good"]
    assert [e.file for e in errors] == ["10-deep.yaml"]


def test_oversized_rules_file_skipped(tmp_path):
    write(tmp_path, "big.yaml", "- id: b\n# " + "x" * 300_000 + "\n")
    rules, errors = load_rules(tmp_path)
    assert rules == []
    assert "too large" in errors[0].message


def test_blank_folder_and_name_are_not_set():
    from dam.rules.model import Then

    assert Then(folder="  ", name="").folder is None
    assert Then(folder="  ", name="").name is None
    kept = Then(folder=" 10. Money/{year} ", name="x")
    assert kept.folder == "10. Money/{year}" and kept.name == "x"
