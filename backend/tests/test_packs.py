import pytest

from dam import packs
from dam.rules import fields


@pytest.fixture(autouse=True)
def _default_profile():
    yield
    packs.activate(packs.build(packs.DEFAULT_COUNTRIES, packs.DEFAULT_LANGUAGES))


def test_build_orders_core_first_and_languages_as_given():
    p = packs.build(["fi"], ["fi", "sv", "en"])
    assert [c.code for c in p.countries] == ["core", "fi"]
    assert [lang.code for lang in p.languages] == ["fi", "sv", "en"]


def _alternatives(pattern: str) -> set[str]:
    return set(pattern.removeprefix(r"\b(?:").removesuffix(r")\b").split("|"))


def test_labels_are_the_ones_detection_used_before():
    p = packs.build(["fi"], ["fi", "sv", "en"])
    alternatives = _alternatives
    assert alternatives(p.due_labels.pattern) == alternatives(fields._DUE_LABELS.pattern)
    assert alternatives(p.total_strong.pattern) == alternatives(fields._TOTAL_STRONG.pattern)


def test_months_from_every_language():
    p = packs.build(["fi"], ["fi", "sv", "en"])
    assert p.months["lokakuuta"] == 10 and p.months["lokakuu"] == 10
    assert p.months["kesakuuta"] == 6  # folded: no diacritics
    assert p.months["oktober"] == 10 and p.months["maj"] == 5
    assert p.months["october"] == 10 and p.months["oct"] == 10 and p.months["sept"] == 9
    assert "lokakuuta" not in packs.build([], ["en"]).months


def test_address_zone_of_the_first_country_with_one():
    assert packs.build(["fi"], ["en"]).address_zone == (0.095, 0.135, 0.524, 0.27)
    assert packs.build([], ["en"]).address_zone is None


def test_active_is_the_default_until_another_is_activated():
    assert [c.code for c in packs.active().countries] == ["core", "fi"]
    other = packs.build([], ["en"])
    packs.activate(other)
    assert packs.active() is other


def test_unknown_codes_are_named():
    with pytest.raises(ValueError, match="'zz'"):
        packs.build(["zz"], ["en"])
    with pytest.raises(ValueError, match="'xx'"):
        packs.build([], ["xx"])
