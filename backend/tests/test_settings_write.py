"""Writing top-level keys of settings.yaml without losing the rest of the file."""

import pytest
import yaml

from dam.config import load_settings
from dam.settings_write import with_keys
from test_api import LOCAL_ORIGIN, make_client

SAMPLE = """# my notes
archive_root: "/x"
indexer_reads_per_minute: 30
# OCR languages
ocr_languages:
  - en-US
people:
- name: Old
  match: [old]
# after people
server_port: 8765
"""


def test_a_new_key_is_added_at_the_end():
    out = with_keys(SAMPLE, {"page1_backfill": False})
    assert out.endswith("server_port: 8765\npage1_backfill: false\n")
    assert out.startswith("# my notes\n")


def test_an_existing_key_is_replaced_in_place_with_comments_kept():
    out = with_keys(SAMPLE, {"people": [{"name": "Tiina", "match": ["Tiina Visser"]}]})
    data = yaml.safe_load(out)
    assert data["people"] == [{"name": "Tiina", "match": ["Tiina Visser"]}]
    assert "# after people\nserver_port: 8765" in out
    assert "# OCR languages\nocr_languages:\n  - en-US" in out
    assert "Old" not in out


def test_a_scalar_is_replaced():
    out = with_keys(SAMPLE, {"indexer_reads_per_minute": 60})
    assert yaml.safe_load(out)["indexer_reads_per_minute"] == 60
    assert out.count("indexer_reads_per_minute") == 1


def test_the_page1_backfill_switch_writes_the_file_and_the_settings(app, app_paths):
    with make_client(app) as c:
        r = c.put("/api/settings/page1-backfill", json={"enabled": False}, headers=LOCAL_ORIGIN)
        assert r.status_code == 200 and r.json() == {"enabled": False}
        assert c.get("/api/status").json()["page1"]["backfill"] is False
        assert load_settings(app_paths).page1_backfill is False
        assert app.settings.page1_backfill is False
        assert list(app_paths.config_dir.glob("settings.yaml.bak-*"))  # the old file is kept
        r = c.put("/api/settings/page1-backfill", json={"enabled": True}, headers=LOCAL_ORIGIN)
        assert r.json() == {"enabled": True}
        assert load_settings(app_paths).page1_backfill is True


def test_a_bad_body_is_refused(app):
    with make_client(app) as c:
        r = c.put("/api/settings/page1-backfill", json={"enabled": "maybe"}, headers=LOCAL_ORIGIN)
        assert r.status_code in (400, 422)


def test_status_carries_the_page1_progress(app, fake_archive):
    from dam.extract.base import ExtractedText
    from dam.extract.layout import Page1Layout

    fake_archive.add("##. Organize/a.pdf", content=b"a", drive_id="a")
    fake_archive.add("##. Organize/b.pdf", content=b"b", drive_id="b")
    app.scan()
    app.repo.save_content(
        "a", "sa", ExtractedText("x", "t", False, Page1Layout([], "text-layer")), "indexed"
    )
    app.repo.save_content("b", "sb", ExtractedText("x", "t"), "indexed")
    with make_client(app) as c:
        assert c.get("/api/status").json()["page1"] == {"read": 1, "total": 2, "backfill": True}


@pytest.mark.parametrize("value", [True, False])
def test_write_keys_restores_the_file_when_the_value_does_not_read_back(app_paths, value):
    from dam.settings_write import write_keys

    before = (app_paths.config_dir / "settings.yaml").read_bytes()
    with pytest.raises(OSError):
        write_keys(app_paths, {"page1_backfill": value}, lambda s: False)
    assert (app_paths.config_dir / "settings.yaml").read_bytes() == before
