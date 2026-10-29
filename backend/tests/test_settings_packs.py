import pytest
import yaml
from pydantic import ValidationError

from dam import packs
from dam.config import DEFAULT_ADDRESS_ZONE, AppPaths, Settings

FINLAND_ZONE = (0.095, 0.135, 0.524, 0.27)


def test_unset_means_what_dam_did_before():
    s = Settings()
    assert s.countries is None and s.languages is None
    assert s.country_codes() == ["fi"]
    assert s.language_codes() == ["fi", "sv", "en"]
    assert s.address_zone == FINLAND_ZONE and not s.zone_is_set()


def test_no_country_gives_the_core_and_the_generic_zone():
    s = Settings.model_validate({"countries": []})
    assert s.country_codes() == []
    assert s.language_codes() == ["en"]
    assert s.address_zone == DEFAULT_ADDRESS_ZONE


def test_english_is_always_added_once():
    assert Settings.model_validate({"languages": ["fi"]}).language_codes() == ["fi", "en"]
    assert Settings.model_validate({"languages": ["en", "fi"]}).language_codes() == ["en", "fi"]


def test_a_zone_in_the_file_wins():
    zone = [0.1, 0.2, 0.6, 0.4]
    s = Settings.model_validate({"countries": [], "address_zone": zone})
    assert s.address_zone == tuple(zone) and s.zone_is_set()


@pytest.mark.parametrize(
    "raw, message",
    [
        ({"countries": ["zz"]}, "unknown country 'zz'"),
        ({"languages": ["xx"]}, "unknown language 'xx'"),
        ({"countries": ["fi", "fi"]}, "fi is listed twice"),
    ],
)
def test_bad_codes_are_named(raw, message):
    with pytest.raises(ValidationError, match=message):
        Settings.model_validate(raw)


def test_the_app_activates_its_settings(app_paths: AppPaths, fake_archive):
    from dam.app import App

    raw = yaml.safe_load((app_paths.config_dir / "settings.yaml").read_text(encoding="utf-8"))
    raw["countries"] = []
    (app_paths.config_dir / "settings.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    application = App.create(app_paths.data_dir)
    try:
        assert [c.code for c in packs.active().countries] == ["core"]
        assert [lang.code for lang in packs.active().languages] == ["en"]
    finally:
        application.close()
