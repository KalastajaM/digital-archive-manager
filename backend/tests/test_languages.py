import unicodedata
from datetime import date

import pytest

from dam import languages
from dam.rules.fields import detect_fields


def test_default_languages():
    assert [p.code for p in languages.enabled()] == ["fi", "en", "sv"]


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
