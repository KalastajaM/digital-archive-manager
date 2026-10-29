import yaml

from dam import packs
from dam.config import DEFAULT_ADDRESS_ZONE, load_settings
from dam.rules.fields import detect_fields
from test_api import LOCAL_ORIGIN, make_client

PUT = {"headers": LOCAL_ORIGIN}


def test_a_fresh_archive_reads_for_finland(app):
    with make_client(app) as c:
        got = c.get("/api/settings/countries").json()
    assert got["chosen"] is False
    (fi,) = [x for x in got["countries"] if x["code"] == "fi"]
    assert fi["enabled"] and fi["name"] == "Finland"
    assert fi["adds"] == ["Payment reference (viitenumero)", "Finland example rules"]
    langs = {x["code"]: x for x in got["languages"]}
    assert [x["code"] for x in got["languages"] if x["enabled"]] == ["fi", "sv", "en"]
    assert langs["en"]["always"] and not langs["fi"]["always"]


def test_choosing_no_country_is_written_and_used(app, app_paths):
    with make_client(app) as c:
        r = c.put("/api/settings/countries", json={"countries": [], "languages": ["en"]}, **PUT)
        assert r.status_code == 200, r.text
        got = c.get("/api/settings/countries").json()
    assert got["chosen"] is True
    assert not any(x["enabled"] for x in got["countries"])
    raw = yaml.safe_load((app_paths.config_dir / "settings.yaml").read_text(encoding="utf-8"))
    assert raw["countries"] == [] and raw["languages"] == ["en"]
    assert [c.code for c in packs.active().countries] == ["core"]
    assert detect_fields("Viitenumero: 1234561").reference is None
    assert load_settings(app_paths).address_zone == DEFAULT_ADDRESS_ZONE


def test_english_is_added_when_left_out(app, app_paths):
    with make_client(app) as c:
        r = c.put("/api/settings/countries", json={"countries": ["fi"], "languages": ["fi"]}, **PUT)
    assert r.status_code == 200
    assert load_settings(app_paths).language_codes() == ["fi", "en"]


def test_an_unknown_code_is_refused_and_nothing_written(app, app_paths):
    before = (app_paths.config_dir / "settings.yaml").read_bytes()
    with make_client(app) as c:
        r = c.put("/api/settings/countries", json={"countries": ["zz"], "languages": ["en"]}, **PUT)
    assert r.status_code == 400 and "zz" in r.text
    assert (app_paths.config_dir / "settings.yaml").read_bytes() == before


def test_a_zone_set_by_the_owner_stays(app, app_paths):
    zone = [0.1, 0.2, 0.6, 0.4]
    with make_client(app) as c:
        c.put("/api/settings/people", json={"people": [], "address_zone": zone}, **PUT)
        c.put("/api/settings/countries", json={"countries": [], "languages": ["en"]}, **PUT)
        people = c.get("/api/settings/people").json()
    assert people["address_zone"] == zone
    assert people["default_address_zone"] == list(DEFAULT_ADDRESS_ZONE)


NL_ZONE = [0.071, 0.135, 0.548, 0.320]


def test_the_zone_follows_the_countries_until_the_owner_sets_one(app, app_paths):
    with make_client(app) as c:
        people = c.get("/api/settings/people").json()
        assert people["address_zone_set"] is False
        # the people saved without a zone: the zone is not pinned
        c.put("/api/settings/people", json={"people": []}, **PUT)
        c.put("/api/settings/countries", json={"countries": ["nl"], "languages": ["nl"]}, **PUT)
        people = c.get("/api/settings/people").json()
    assert people["address_zone"] == NL_ZONE == people["default_address_zone"]
    assert people["address_zone_set"] is False
    assert "address_zone" not in settings_file(app_paths)


def test_default_removes_the_zone_so_it_follows_the_countries_again(app, app_paths):
    zone = [0.1, 0.2, 0.6, 0.4]
    with make_client(app) as c:
        c.put("/api/settings/people", json={"people": [], "address_zone": zone}, **PUT)
        assert c.get("/api/settings/people").json()["address_zone_set"] is True
        c.put("/api/settings/countries", json={"countries": ["nl"], "languages": ["nl"]}, **PUT)
        got = c.put("/api/settings/people", json={"people": [], "address_zone": None}, **PUT)
    assert got.status_code == 200
    assert got.json()["address_zone"] == NL_ZONE
    assert got.json()["address_zone_set"] is False
    assert "address_zone" not in settings_file(app_paths)
    assert not load_settings(app_paths).zone_is_set()


def settings_file(app_paths) -> dict:
    return yaml.safe_load((app_paths.config_dir / "settings.yaml").read_text())
