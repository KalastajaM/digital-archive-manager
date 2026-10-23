from datetime import date

import pytest

from dam.rules.draft import draft_rule, folder_pattern, name_pattern
from dam.rules.engine import check_template

D = date(2026, 10, 15)


def _draft(**over):
    args = dict(
        text="Fortum Oyj\nAsiakasnumero 123\nHelsinki",
        original_name="helen.pdf",
        filed_name="20261015_Fortum.pdf",
        filed_folder="11. Bills/2026",
        doc_date=D,
        tags=["bill"],
        tray=None,
        payee=None,
        doc_frequency=lambda w: {"helsinki": 0.5}.get(w, 0.01),
        taken_ids=set(),
    )
    args.update(over)
    return draft_rule(**args)


def test_folder_year_becomes_a_pattern():
    assert folder_pattern("11. Bills & Receipts/2026", D) == "11. Bills & Receipts/{year}"
    assert folder_pattern("11. Bills & Receipts/2025", D) == "11. Bills & Receipts/2025"
    assert folder_pattern("13. Taxes", None) == "13. Taxes"


def test_name_date_and_stem_become_patterns():
    assert name_pattern("20261015_Fortum", "lasku 123", D) == "{doc_date:%Y%m%d}_Fortum"
    assert name_pattern("20261015_lasku_123", "lasku 123", D) == "{doc_date:%Y%m%d}_{stem}"
    assert name_pattern("Fortum contract", "scan", None) == "Fortum contract"
    assert name_pattern("20261016_Fortum", "scan", D) == "20261016_Fortum"


def test_literal_braces_are_escaped_so_patterns_stay_valid():
    p = folder_pattern("Odd {x}/2026", D)
    check_template(p)
    assert p.format(year=2026) == "Odd {x}/2026"
    check_template(name_pattern("20261015_a{b}", "scan", D))


def test_draft_ticks_the_rarest_text_word_and_never_a_name_only_word():
    d = _draft()
    assert [w.word for w in d.words if w.ticked] == ["fortum"]
    words = [w.word for w in d.words]
    assert "helsinki" not in words and "helen" not in words
    assert (d.id, d.folder, d.name, d.tags) == (
        "fortum",
        "11. Bills/{year}",
        "{doc_date:%Y%m%d}_Fortum",
        ["bill"],
    )
    assert d.tray is None and d.payee is None


def test_ticks_lowest_frequency_ties_to_earliest():
    d = _draft(
        doc_frequency=lambda w: {"helsinki": 0.2, "fortum": 0.1, "asiakasnumero": 0.1}.get(w, 0.3)
    )
    assert [w.word for w in d.words if w.ticked] == ["fortum"]
    d = _draft(doc_frequency=lambda w: {"fortum": 0.2, "asiakasnumero": 0.05}.get(w, 0.3))
    assert [w.word for w in d.words if w.ticked] == ["asiakasnumero"]


def test_at_most_six_words_offered():
    d = _draft(
        text="alpha bravo charlie delta echoes foxtrot golfer hotel india",
        doc_frequency=lambda w: 0.1,
    )
    assert len(d.words) == 6
    assert [w.word for w in d.words][0] == "alpha"


def test_draft_id_is_unique():
    assert _draft(taken_ids={"fortum"}).id == "fortum-2"
    assert _draft(taken_ids={"fortum", "fortum-2"}).id == "fortum-3"


def test_id_is_ascii_slug():
    d = _draft(text="Äänekoski Oy", doc_frequency=lambda w: {"oy": 1}.get(w, 0.1))
    assert d.id == "aanekoski"


def test_no_draft_without_words():
    assert _draft(text="scan document invoice 123 ab") is None
    assert _draft(doc_frequency=lambda w: 0.9) is None


@pytest.mark.parametrize("folder", ["13. Taxes", "a/2026/b"])
def test_patterns_pass_check_template(folder):
    d = _draft(filed_folder=folder)
    check_template(d.folder)
    check_template(d.name)
