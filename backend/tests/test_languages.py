import unicodedata
from datetime import date

import pytest

from dam import languages
from dam.rules.fields import detect_fields


def test_default_languages():
    assert [p.code for p in languages.enabled()] == ["fi", "sv", "en"]


def test_unknown_language_is_named():
    with pytest.raises(ValueError, match="'zz'"):
        languages.get("zz")
    with pytest.raises(ValueError, match="'zz'"):
        languages.enabled(["fi", "zz"])


def test_due_labels_in_each_language():
    # values recorded on the code before the move
    assert detect_fields("Due date 31.10.2026 due 1.11.2026").due_date == date(2026, 10, 31)
    assert detect_fields("Maksettava 12,00 € eräpäivä 1.11.2026").due_date == date(2026, 11, 1)
    assert detect_fields("Att betala 45,10 € Förfallodag 2.11.2026").due_date == date(2026, 11, 2)


def test_label_pattern_forms():
    assert languages.label_pattern(["a", "b"]).pattern == "a|b"
    assert languages.label_pattern(["a", "b"], whole_words=True).pattern == r"\b(?:a|b)\b"


def test_every_word_is_nfc_and_lower_case():
    for pack in languages.PACKS.values():
        for w in pack.stopwords + pack.kind_words:
            assert w == unicodedata.normalize("NFC", w) == w.casefold()


def test_no_fragments_never_match():
    # a language set without, say, weak total labels must not match at every position
    assert languages.label_pattern([]).search("Alv 12,00 € 50,00 €") is None
    assert languages.label_pattern([], whole_words=True).search("Alv 12,00 € 50,00 €") is None


def test_dutch_labels_and_months():
    from dam import packs

    before = packs.active()
    try:
        packs.activate(packs.build(["nl"], ["nl", "en"]))
        found = detect_fields("Uiterste betaaldatum: 3 november 2026\nTotaalbedrag € 1.234,56")
        assert found.due_date == date(2026, 11, 3)
        assert str(found.total) == "1234.56"
        assert detect_fields("Te betalen vóór 15 mrt 2027").due_date == date(2027, 3, 15)
        assert (
            detect_fields("Subtotaal € 10,00 Bedrag € 12,10").total
            == detect_fields("Bedrag € 12,10").total
        )
    finally:
        packs.activate(before)


def test_dutch_reads_with_tesseract():
    from dam.extract.ocr import tesseract_languages

    assert tesseract_languages(["nl-NL", "en-US"]) == "nld+eng"
