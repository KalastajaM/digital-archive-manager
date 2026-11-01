"""Versions of a document: the name key, the group from a file's point of view, the Not a
version marks and the move of older versions into the Archive subfolder."""

import os

import pytest
from sqlalchemy import select, update

from dam.config import Settings, SpecialFolders, load_settings
from dam.db.tables import files, related_dismissed, version_dismissed
from dam.errors import InvalidRequest, NotFound
from dam.services.versions import type_family, version_key
from test_api import LOCAL_ORIGIN, make_client


@pytest.mark.parametrize(
    "a,b",
    [
        ("Lease agreement.docx", "Lease agreement final (1).docx"),
        ("FinancialPlanning_RealTime_LATEST.xlsx", "FinancialPlanning_RealTime_LATEST_5.xlsx"),
        ("Report_2017.xlsx", "Report_2017_v2.xlsx"),
        ("20170121_CV_Someone.pages", "20170115_CV_Someone.pages"),
        ("CV_Someone_20180114.docx", "CV_Someone_20180114 copy.docx"),
        ("Copy of Budget.xlsx", "Budget.xlsx"),
        ("Testament_redline.docx", "Testament_updated.docx"),
        ("Sopimus 2024-01-15.docx", "Sopimus 15.01.2024.docx"),
        ("Offer(1).docx", "Offer.docx"),
        ("Sopimus 24-10-2004.docx", "Sopimus 24-10-2004_old.docx"),
        ("Café plan.docx", "Café plan v2.docx"),
    ],
)
def test_same_key(a, b):
    assert version_key(a) is not None
    assert version_key(a) == version_key(b)


@pytest.mark.parametrize(
    "a,b",
    [
        ("Hakemus_20180629_Sponda.docx", "Hakemus_20180729_Lidl.docx"),
        ("Budget.xlsx", "Budget plan.xlsx"),
        ("Plan 2024.docx", "Plan 2025.docx"),
    ],
)
def test_other_key(a, b):
    assert version_key(a) != version_key(b)


@pytest.mark.parametrize("name", ["v2.docx", "final.docx", "20240115.docx", "ab.docx"])
def test_no_key_for_a_name_with_nothing_left(name):
    assert version_key(name) is None


def test_families():
    assert type_family("DOC") == type_family("docx")
    assert type_family("docx") != type_family("xlsx")
    assert type_family("pages") == "pages"
    assert type_family(".docx") == type_family("docx")
    assert type_family("pdf") is None
    assert type_family(None) is None


# --- the group from a file's point of view ------------------------------------------------

F = "30. Home/Legal"
QUAR = "##. To Delete"
INBOX = "##. Organize"


@pytest.fixture
def api(app):
    with make_client(app) as c:
        yield c


def add(fake_archive, rel, drive_id, mtime=None):
    path = fake_archive.add(rel, drive_id.encode(), drive_id=drive_id)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def names(result):
    return [f.name for f in result.files]


def test_group_is_same_folder_family_and_key(app, fake_archive):
    add(fake_archive, f"{F}/a plan.docx", "a", 100)
    add(fake_archive, f"{F}/a plan v2.doc", "b", 200)
    add(fake_archive, f"{F}/a plan.pdf", "c", 300)
    add(fake_archive, f"{F}/other.docx", "d", 400)
    add(fake_archive, "30. Home/a plan.docx", "e", 500)
    app.scan()
    out = app.versions.of("a")
    assert names(out) == ["a plan v2.doc", "a plan.docx"]
    assert out.latest == "b"
    assert [f.latest for f in out.files] == [True, False]


def test_no_group_for_a_file_alone_or_a_pdf(app, fake_archive):
    add(fake_archive, f"{F}/alone.docx", "a")
    add(fake_archive, f"{F}/bill.pdf", "b")
    add(fake_archive, f"{F}/bill 2.pdf", "c")
    app.scan()
    assert app.versions.of("a").files == []
    assert app.versions.of("b").files == []


def test_a_hidden_sidecar_is_not_a_version(app, fake_archive):
    add(fake_archive, f"{F}/Offer.docx", "a", 100)
    add(fake_archive, f"{F}/._Offer.docx", "b", 100)
    app.scan()
    assert app.versions.of("a").files == []
    assert app.versions.of("b").files == []


def test_latest_is_mtime_not_name_date(app, fake_archive):
    add(fake_archive, f"{F}/20170122_Plan.docx", "a", 300)
    add(fake_archive, f"{F}/20170212_Plan.docx", "b", 200)
    app.scan()
    assert app.versions.of("b").latest == "a"


def test_mtime_tie_longer_name_then_path(app, fake_archive):
    add(fake_archive, f"{F}/Plan.docx", "a", 100)
    add(fake_archive, f"{F}/Plan final.docx", "b", 100)
    app.scan()
    assert app.versions.of("a").latest == "b"


def test_null_mtime_is_oldest(app, fake_archive):
    add(fake_archive, f"{F}/Plan.docx", "a", 100)
    add(fake_archive, f"{F}/Plan v2.docx", "b", 50)
    app.scan()
    with app.engine.begin() as conn:
        conn.execute(update(files).where(files.c.drive_id == "a").values(mtime=None))
    out = app.versions.of("a")
    assert out.latest == "b"
    assert out.files[1].mtime is None


def test_archive_and_underscore_archive_join_group(app, fake_archive):
    add(fake_archive, f"{F}/a plan.docx", "a", 300)
    add(fake_archive, f"{F}/Archive/a plan v1.docx", "b", 200)
    add(fake_archive, f"{F}/_Archive/a plan v0.docx", "c", 100)
    app.scan()
    for drive_id in "abc":
        out = app.versions.of(drive_id)
        assert [f.drive_id for f in out.files] == ["a", "b", "c"]
        assert [f.in_archive for f in out.files] == [False, True, True]


def test_subfolder_archive_counts_by_setting(app, fake_archive):
    add(fake_archive, f"{F}/a plan.docx", "a", 300)
    add(fake_archive, f"{F}/Old/a plan v1.docx", "b", 200)
    app.scan()
    assert app.versions.of("a").files == []
    app.settings.versions_folder_name = "old"
    assert len(app.versions.of("a").files) == 2


def test_top_level_archive_is_ordinary_folder(app, fake_archive):
    add(fake_archive, "Archive/a plan.docx", "a", 200)
    add(fake_archive, "Archive/a plan v1.docx", "b", 100)
    add(fake_archive, "a plan.docx", "c", 300)
    app.scan()
    out = app.versions.of("a")
    assert [f.drive_id for f in out.files] == ["a", "b"]
    assert not any(f.in_archive for f in out.files)
    assert out.folder == "Archive/Archive"


def test_no_nesting_from_inside_archive(app, fake_archive):
    add(fake_archive, f"{F}/Archive/a plan.docx", "a", 200)
    add(fake_archive, f"{F}/Archive/a plan v1.docx", "b", 100)
    app.scan()
    out = app.versions.of("a")
    assert len(out.files) == 2
    assert out.movable == []
    assert out.blocked


def test_inbox_to_delete_and_links_are_out(app, fake_archive):
    add(fake_archive, f"{F}/a plan.docx", "a", 300)
    add(fake_archive, f"{F}/a plan v1.docx", "b", 200)
    fake_archive.link(f"{F}/a plan v2.docx", f"{F}/a plan.docx")
    add(fake_archive, f"{INBOX}/x plan.docx", "c", 100)
    add(fake_archive, f"{INBOX}/x plan v2.docx", "d", 100)
    add(fake_archive, f"{QUAR}/x plan.docx", "e", 100)
    add(fake_archive, f"{QUAR}/x plan v2.docx", "f", 100)
    app.scan()
    assert names(app.versions.of("a")) == ["a plan.docx", "a plan v1.docx"]
    assert app.versions.of("c").files == []
    assert app.versions.of("e").files == []


def test_latest_in_to_delete_gives_next_newest(app, api, fake_archive):
    add(fake_archive, f"{F}/a plan.docx", "a", 100)
    add(fake_archive, f"{F}/a plan v1.docx", "b", 200)
    add(fake_archive, f"{F}/a plan v2.docx", "c", 300)
    app.scan()
    assert app.versions.of("a").latest == "c"
    r = api.post("/api/quarantine", json={"drive_ids": ["c"]}, headers=LOCAL_ORIGIN)
    assert r.status_code == 200
    assert app.versions.of("a").latest == "b"
    assert len(app.versions.of("a").files) == 2


@pytest.mark.parametrize("folder", ["100%_done", "a_b", "back\\slash"])
def test_folder_with_like_characters(app, fake_archive, folder):
    add(fake_archive, f"30. Home/{folder}/a plan.docx", "a", 100)
    add(fake_archive, f"30. Home/{folder}/a plan v2.docx", "b", 200)
    add(fake_archive, "30. Home/100x-done/a plan v3.docx", "c", 300)
    add(fake_archive, "30. Home/axb/a plan v3.docx", "d", 300)
    app.scan()
    assert [f.drive_id for f in app.versions.of("a").files] == ["b", "a"]


def test_nfd_name_groups(app, fake_archive):
    add(fake_archive, f"{F}/Café plan.docx", "a", 100)
    add(fake_archive, f"{F}/Café plan v2.docx", "b", 200)
    app.scan()
    assert app.versions.of("a").latest == "b"


def test_unknown_file_is_not_found(app):
    with pytest.raises(NotFound):
        app.versions.of("nope")


# --- Not a version ------------------------------------------------------------------------


@pytest.fixture
def three(app, fake_archive):
    add(fake_archive, f"{F}/a plan.docx", "a", 100)
    add(fake_archive, f"{F}/a plan v1.docx", "b", 200)
    add(fake_archive, f"{F}/a plan v2.docx", "c", 300)
    app.scan()


def test_mark_is_per_pair(app, three):
    app.versions.dismiss("a", "c")
    out = app.versions.of("a")
    assert [f.drive_id for f in out.files] == ["b", "a"]
    assert out.latest == "b" and out.hidden == 1
    # c still sees b, and b sees both
    assert [f.drive_id for f in app.versions.of("c").files] == ["c", "b"]
    assert [f.drive_id for f in app.versions.of("b").files] == ["c", "b", "a"]


def test_mark_of_the_only_other_file_ends_the_group(app, fake_archive):
    add(fake_archive, f"{F}/x plan.docx", "x", 100)
    add(fake_archive, f"{F}/x plan v1.docx", "y", 200)
    app.scan()
    app.versions.dismiss("x", "y")
    out = app.versions.of("x")
    assert out.files == [] and out.latest is None and out.hidden == 1


def test_restore(app, three):
    app.versions.dismiss("a", "c")
    assert [d.drive_id for d in app.versions.dismissed("a")] == ["c"]
    app.versions.restore("c", "a")
    assert app.versions.dismissed("a") == []
    assert app.versions.of("a").latest == "c"


def test_mark_survives_a_move(app, api, three):
    app.versions.dismiss("a", "c")
    r = api.post(
        "/api/browse/move",
        json={"drive_ids": ["c"], "folder": f"{F}/Archive"},
        headers=LOCAL_ORIGIN,
    )
    assert r.status_code == 200 and r.json()["done"]
    assert [f.drive_id for f in app.versions.of("a").files] == ["b", "a"]


def test_mark_does_not_touch_related_dismissed(app, three):
    app.versions.dismiss("a", "c")
    with app.engine.connect() as conn:
        assert conn.execute(select(related_dismissed)).first() is None
        assert conn.execute(select(version_dismissed)).first() is not None


def test_mark_refuses_itself_and_unknown(app, three):
    with pytest.raises(InvalidRequest):
        app.versions.dismiss("a", "a")
    with pytest.raises(NotFound):
        app.versions.dismiss("a", "nope")


def test_api_marks(api, three):
    assert api.get("/api/files/a/versions").json()["latest"] == "c"
    r = api.post("/api/files/a/versions/dismiss", json={"drive_id": "c"}, headers=LOCAL_ORIGIN)
    assert r.status_code == 200 and [d["drive_id"] for d in r.json()["dismissed"]] == ["c"]
    assert api.get("/api/files/a/versions").json()["hidden"] == 1
    assert [d["name"] for d in api.get("/api/files/a/versions/dismissed").json()["dismissed"]] == [
        "a plan v2.docx"
    ]
    r = api.post("/api/files/a/versions/restore", json={"drive_id": "c"}, headers=LOCAL_ORIGIN)
    assert r.json()["dismissed"] == []
    assert api.get("/api/files/nope/versions").status_code == 404


# --- moving older versions ----------------------------------------------------------------


def test_movable_excludes_latest_and_archived(app, fake_archive):
    add(fake_archive, f"{F}/a plan.docx", "a", 100)
    add(fake_archive, f"{F}/a plan v1.docx", "b", 200)
    add(fake_archive, f"{F}/Archive/a plan v0.docx", "c", 50)
    add(fake_archive, f"{F}/a plan v2.docx", "d", 300)
    app.scan()
    out = app.versions.of("a")
    assert out.folder == f"{F}/Archive"
    assert sorted(out.movable) == ["a", "b"]
    assert out.staying == [] and out.blocked is None


def test_locked_older_stays(app, three):
    app.locks.lock("b")
    out = app.versions.of("a")
    assert out.movable == ["a"]
    assert out.staying == [{"name": "a plan v1.docx", "reason": "locked"}]


def test_all_locked_blocked_says_why(app, three):
    app.locks.lock("a")
    app.locks.lock("b")
    out = app.versions.of("a")
    assert out.movable == []
    assert "locked" in out.blocked


def test_latest_locked_changes_nothing(app, three):
    app.locks.lock("c")
    assert sorted(app.versions.of("a").movable) == ["a", "b"]


def test_top_of_archive_blocked(app, fake_archive):
    add(fake_archive, "a plan.docx", "a", 100)
    add(fake_archive, "a plan v1.docx", "b", 200)
    app.scan()
    out = app.versions.of("a")
    assert len(out.files) == 2
    assert out.folder is None and out.movable == []
    assert "top" in out.blocked


def test_uses_existing_underscore_archive(app, fake_archive):
    add(fake_archive, f"{F}/a plan.docx", "a", 100)
    add(fake_archive, f"{F}/a plan v1.docx", "b", 200)
    add(fake_archive, f"{F}/_Archive/older note.txt", "n", 10)
    app.scan()
    assert app.versions.of("a").folder == f"{F}/_Archive"
    add(fake_archive, f"{F}/Archive/older note.txt", "o", 10)
    app.scan()
    assert app.versions.of("a").folder == f"{F}/Archive"


def test_unconnected_stays(app, three, monkeypatch):
    monkeypatch.setattr(app.versions.paths, "label_of", lambda rel: "Elsewhere")
    monkeypatch.setattr(app.versions.paths, "is_connected", lambda label, cached=False: False)
    out = app.versions.of("a")
    assert out.movable == []
    assert {s["reason"] for s in out.staying} == {"not connected"}
    assert "connected" in out.blocked


def test_move_applies_with_undo(app, api, three, fake_archive):
    out = app.versions.of("a")
    body = {"drive_ids": out.movable, "folder": out.folder}
    assert len(api.post("/api/browse/move/preview", json=body, headers=LOCAL_ORIGIN).json()) >= 2
    r = api.post("/api/browse/move", json=body, headers=LOCAL_ORIGIN)
    assert r.status_code == 200
    assert (fake_archive.root / F / "Archive/a plan.docx").exists()
    assert (fake_archive.root / F / "Archive/a plan v1.docx").exists()
    assert (fake_archive.root / F / "a plan v2.docx").exists()
    after = app.versions.of("a")
    assert after.latest == "c" and after.movable == [] and len(after.files) == 3
    assert (
        api.post(
            f"/api/activity/{r.json()['batch_id']}/undo", json={}, headers=LOCAL_ORIGIN
        ).status_code
        == 200
    )
    assert (fake_archive.root / F / "a plan.docx").exists()


# --- the setting --------------------------------------------------------------------------


def test_setting_default_and_put(app, api):
    assert api.get("/api/settings/versions-folder").json() == {"name": "Archive"}
    r = api.put("/api/settings/versions-folder", json={"name": " Vanhat "}, headers=LOCAL_ORIGIN)
    assert r.status_code == 200 and r.json() == {"name": "Vanhat"}
    assert load_settings(app.app_paths).versions_folder_name == "Vanhat"


@pytest.mark.parametrize("bad", ["A/B", "##. Old", "##. To Delete"])
def test_setting_refuses_bad_names(app, api, bad):
    r = api.put("/api/settings/versions-folder", json={"name": bad}, headers=LOCAL_ORIGIN)
    assert r.status_code == 400
    assert load_settings(app.app_paths).versions_folder_name == "Archive"


def test_default_name_does_not_break_a_special_folder_named_archive():
    folders = SpecialFolders(inbox="Archive")
    assert Settings(special_folders=folders).versions_folder_name == "Archive"
    with pytest.raises(ValueError):
        Settings(special_folders=folders, versions_folder_name="archive")
