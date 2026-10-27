"""Editing the AI excluded folders from the app: the settings.yaml writer, the cleaning
of entries, and ``PUT /api/ai/exclude-folders`` taking effect without a restart."""

import pytest
import yaml
from fastapi.testclient import TestClient

from dam import setup
from dam.ai import guard
from dam.ai.fake import FakeProvider
from dam.api import create_api
from dam.config import load_settings
from dam.errors import Conflict, InvalidRequest

BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}
NEW = ["50. Medical", "Lääkäri/2026"]


def exclude_of(text: str) -> list[str] | None:
    return (yaml.safe_load(text) or {}).get("ai", {}).get("exclude_folders")


# -- the writer ------------------------------------------------------------------------

SHAPES = {
    # no active section (the seeded file's commented example stays as it is)
    "no ai section": 'archive_root: "/x"\n# ai:\n#   exclude_folders:\n#     - "70. Work"\n',
    "ai without the key": "ai:\n  enabled: true\n  models:\n    small: a\n# after\nother: 1\n",
    "block list": (
        "ai:\n    enabled: true\n    exclude_folders:   # never sent\n"
        "      - A\n      - B\n\n    monthly_budget_eur: 5\nnext: 2\n"
    ),
    "flow list": 'ai:\n  exclude_folders: ["A", "B"]  # x\n  usd_to_eur: 1\n',
    "items at the key's indent": "ai:\n  exclude_folders:\n  - A\n  - B\n  enabled: true\n",
    "last in the file": "ai:\n  exclude_folders:\n    - A\n",
    "a deeper key of the same name": (
        "ai:\n  models:\n    exclude_folders: keep\n  enabled: true\n"
    ),
}


@pytest.mark.parametrize("name", list(SHAPES))
def test_writer_sets_only_the_list_and_keeps_the_rest(name):
    text = SHAPES[name]
    new = setup.with_ai_exclude_folders(text, NEW)
    assert exclude_of(new) == NEW
    before, after = yaml.safe_load(text) or {}, yaml.safe_load(new)
    # every other setting reads back the same
    before_ai, after_ai = dict(before.get("ai") or {}), dict(after["ai"])
    before_ai.pop("exclude_folders", None)
    after_ai.pop("exclude_folders", None)
    assert after_ai == before_ai
    assert {k: v for k, v in after.items() if k != "ai"} == {
        k: v for k, v in before.items() if k != "ai"
    }
    # comments stay: the commented example, and a comment on the key line
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            assert line in new.splitlines()
    if "# never sent" in text:
        assert "    exclude_folders:  # never sent" in new.splitlines()


def test_writer_empty_list_and_inline_section():
    assert exclude_of(setup.with_ai_exclude_folders(SHAPES["flow list"], [])) == []
    with pytest.raises(ValueError, match="inline"):
        setup.with_ai_exclude_folders("ai: {enabled: true}\n", NEW)


def test_write_keeps_a_backup_reads_back_and_keeps_crlf(app_paths):
    target = setup.settings_path(app_paths)
    original = target.read_bytes()
    crlf = original.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    target.write_bytes(crlf)
    setup.write_ai_exclude_folders(app_paths, NEW)
    assert load_settings(app_paths).ai.exclude_folders == NEW
    written = target.read_bytes()
    assert b"\r\n" in written and b"\n" not in written.replace(b"\r\n", b"")
    (backup,) = target.parent.glob("settings.yaml.bak-*")
    assert backup.read_bytes() == crlf
    # the same list again: nothing written, no new backup
    setup.write_ai_exclude_folders(app_paths, NEW)
    assert len(list(target.parent.glob("settings.yaml.bak-*"))) == 1


def test_write_restores_the_file_when_it_does_not_read_back(app_paths, monkeypatch):
    target = setup.settings_path(app_paths)
    original = target.read_bytes()
    real = setup.load_settings

    def wrong(paths):
        s = real(paths)
        s.ai.exclude_folders = ["something else"]
        return s

    monkeypatch.setattr(setup, "load_settings", wrong)
    with pytest.raises(OSError, match="read back"):
        setup.write_ai_exclude_folders(app_paths, NEW)
    assert target.read_bytes() == original


# -- cleaning --------------------------------------------------------------------------


def test_clean_trims_folds_duplicates_and_refuses_paths_outside():
    assert guard.clean_exclude_folders([" 50. Medical/ ", "50. medical", "a//b", "a\\b"]) == [
        "50. Medical",
        "a/b",
    ]
    for bad in ["", "  ", "/", "/Users/me/x", "~/x", "C:\\x", "a/../b", "./a"]:
        with pytest.raises(InvalidRequest):
            guard.clean_exclude_folders([bad])


# -- the service and the API -----------------------------------------------------------


@pytest.fixture
def ai_app(app, fake_archive):
    """A fake provider (counts as a key), one file under Banks and one under Medical."""
    app.ai.provider = FakeProvider(lambda **_: {"name": "x"}, input_tokens=10, output_tokens=10)
    fake_archive.add("10. Financial/Banks/bill.txt", b"Northpower invoice", drive_id="f1")
    fake_archive.add("50. Medical/lab.txt", b"blood test results", drive_id="m1")
    app.scan()
    app.index()
    return app


@pytest.fixture
def client(ai_app):
    with TestClient(create_api(ai_app), base_url=BASE) as c:
        yield c


def test_api_saves_the_list_and_it_applies_at_once(client, ai_app):
    s = client.get("/api/ai/status", headers=LOCAL_ORIGIN).json()
    assert s["exclude_folders"] == ["50. Medical", "70. Work", "90. Other People"]
    assert s["exclude_missing"] == ["70. Work", "90. Other People"]
    blocked = ai_app.ai.prepare("summarize-document", {"drive_id": "m1"})
    assert "excluded folder" in (blocked.blocked or "")

    # Banks prepared while allowed, then excluded: the send is refused
    p = ai_app.ai.prepare("summarize-document", {"drive_id": "f1"})
    assert p.blocked is None
    r = client.put(
        "/api/ai/exclude-folders",
        json={"folders": ["10. financial/", "70. Work"]},
        headers=LOCAL_ORIGIN,
    )
    assert r.status_code == 200, r.text
    assert r.json()["exclude_folders"] == ["10. financial", "70. Work"]
    assert r.json()["exclude_missing"] == ["70. Work"]
    # refused (the rebuilt payload differs from the preview, and is blocked): nothing sent
    with pytest.raises(InvalidRequest):
        ai_app.ai.run(p.token)
    assert ai_app.ai.provider.calls == []
    assert "excluded folder" in (
        ai_app.ai.prepare("summarize-document", {"drive_id": "f1"}).blocked or ""
    )
    # Medical is no longer excluded: it can be prepared (still sent only on Send)
    assert ai_app.ai.prepare("summarize-document", {"drive_id": "m1"}).blocked is None
    # saved: a restart reads the same list
    assert load_settings(ai_app.app_paths).ai.exclude_folders == ["10. financial", "70. Work"]


def test_api_refuses_bad_entries_and_a_loose_body(client, ai_app):
    before = setup.settings_path(ai_app.app_paths).read_bytes()
    r = client.put("/api/ai/exclude-folders", json={"folders": ["../x"]}, headers=LOCAL_ORIGIN)
    assert r.status_code == 400 and ". and .. are not allowed" in r.json()["error"]
    for body in ({}, {"folders": "50. Medical"}, {"folders": [1]}, {"folders": [], "x": 1}):
        r = client.put("/api/ai/exclude-folders", json=body, headers=LOCAL_ORIGIN)
        assert r.status_code == 422, body
    assert setup.settings_path(ai_app.app_paths).read_bytes() == before


def test_an_inline_ai_section_is_a_conflict_and_the_file_stays(ai_app):
    target = setup.settings_path(ai_app.app_paths)
    target.write_text(
        target.read_text(encoding="utf-8") + "ai: {enabled: true}\n", encoding="utf-8"
    )
    before = target.read_bytes()
    with pytest.raises(Conflict, match="inline"):
        ai_app.ai.set_exclude_folders(NEW)
    assert target.read_bytes() == before
    assert ai_app.settings.ai.exclude_folders == ["50. Medical", "70. Work", "90. Other People"]


def test_a_folder_is_found_in_any_case_and_unicode_form(tmp_path):
    """The "not in the archive" check matches names as the exclusion does, also on a
    case-sensitive file system (Linux): any case, NFC or NFD."""
    from dam.ai.service import _folder_exists

    (tmp_path / "10. Financial" / "Pankit ä").mkdir(parents=True)
    assert _folder_exists(tmp_path, "10. Financial")
    assert _folder_exists(tmp_path, "10. financial")
    assert _folder_exists(tmp_path, "10. FINANCIAL/pankit ä")  # NFD ä
    assert not _folder_exists(tmp_path, "10. Financial/Banks")
    assert not _folder_exists(tmp_path, "70. Work")
