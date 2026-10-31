"""The Expired folder's name: a setting with a default, checked like any folder name."""

import pytest

from dam.config import load_settings
from test_api import LOCAL_ORIGIN, make_client


@pytest.fixture
def api(app):
    with make_client(app) as c:
        yield c


def test_default_is_expired(app, api):
    assert app.settings.expired_folder_name == "Expired"
    r = api.get("/api/settings/expired-folder")
    assert r.status_code == 200 and r.json() == {"name": "Expired"}


def test_put_writes_settings_yaml(app, api):
    r = api.put("/api/settings/expired-folder", json={"name": "  Lapsed "}, headers=LOCAL_ORIGIN)
    assert r.status_code == 200 and r.json() == {"name": "Lapsed"}
    assert app.settings.expired_folder_name == "Lapsed"
    assert load_settings(app.app_paths).expired_folder_name == "Lapsed"
    assert api.get("/api/settings/expired-folder").json() == {"name": "Lapsed"}


@pytest.mark.parametrize("bad", ["A/B", "##. Old"])
def test_refuses_bad_folder_names(app, api, bad):
    r = api.put("/api/settings/expired-folder", json={"name": bad}, headers=LOCAL_ORIGIN)
    assert r.status_code == 400
    assert app.settings.expired_folder_name == "Expired"
    assert load_settings(app.app_paths).expired_folder_name == "Expired"


def test_refuses_special_prefix(app, api):
    r = api.put("/api/settings/expired-folder", json={"name": "##. Old"}, headers=LOCAL_ORIGIN)
    assert r.status_code == 400 and "##." in r.json()["error"]


def test_refuses_special_folder_name(app, api):
    inbox = app.settings.special_folders.inbox
    for name in (inbox, inbox.upper()):
        r = api.put("/api/settings/expired-folder", json={"name": name}, headers=LOCAL_ORIGIN)
        assert r.status_code == 400
    assert app.settings.expired_folder_name == "Expired"
