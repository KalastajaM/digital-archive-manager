import pytest

from dam import countries
from dam.config import DEFAULT_ADDRESS_ZONE
from dam.rules import fields
from dam.rules.fields import detect_fields


def test_enabled_is_core_then_packs():
    assert [p.code for p in countries.enabled()] == ["core", "fi"]
    assert [p.code for p in countries.enabled(())] == ["core"]


def test_unknown_code_is_named():
    with pytest.raises(ValueError, match="'zz'"):
        countries.get("zz")
    with pytest.raises(ValueError, match="'zz'"):
        countries.enabled(["fi", "zz"])


def test_finland_zone_is_sfs_2487():
    assert countries.get("fi").address_zone == (0.095, 0.135, 0.524, 0.27)
    assert DEFAULT_ADDRESS_ZONE == countries.get("fi").address_zone


def test_earliest_reference_wins_across_packs():
    assert detect_fields("Viite 1234561 RF18 1234 5678 9").reference == "1234561"
    assert detect_fields("RF18 1234 5678 9 Viitenumero: 1234561").reference == "RF18123456789"


def test_core_alone_finds_rf_but_not_domestic():
    assert fields._references("Viite 1234561", countries.enabled(())) is None
    assert fields._references("RF18 1234 5678 9", countries.enabled(())) == "RF18123456789"
