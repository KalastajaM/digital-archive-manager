from decimal import Decimal

from dam import packs
from dam.ai.tasks.ask_archive import stopwords
from dam.rules.fields import detect_fields
from dam.rules.similar import word_tokens


def test_without_finland_no_domestic_reference_but_rf_still():
    packs.activate(packs.build([], ["en"]))
    assert detect_fields("Viitenumero: 1234561").reference is None
    assert detect_fields("RF18 1234 5678 9").reference == "RF18123456789"


def test_labels_come_from_the_enabled_languages():
    assert detect_fields("Yhteensä 12,00 € ja 50,00 €").total == Decimal("12.00")
    packs.activate(packs.build([], ["en"]))
    # "yhteensa" is no label in English: the largest amount is the total
    assert detect_fields("Yhteensä 12,00 € ja 50,00 €").total == Decimal("50.00")


def test_word_lists_follow_the_profile():
    assert "lasku" not in word_tokens("", "Lasku Northbank")
    assert "ja" in stopwords()
    packs.activate(packs.build([], ["en"]))
    assert "lasku" in word_tokens("", "Lasku Northbank")
    assert "ja" not in stopwords()


def test_the_default_matches_unset_settings():
    # the profile an App on a fresh settings file activates
    assert [p.code for p in packs.active().languages] == ["fi", "sv", "en"]
