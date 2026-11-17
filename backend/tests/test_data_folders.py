"""Choosing an archive's data folder, and moving an archive's main folder."""

import sqlite3

import pytest

from dam import setup
from dam.archive_folders import change_main_folder
from dam.config import AppPaths
from dam.data_folders import check_data_folder
from dam.errors import InvalidRequest
from dam.profiles import ProfileStore
from dam.services.archives import ArchiveService


@pytest.fixture
def store(tmp_path):
    base = tmp_path / "base"
    AppPaths(base).ensure()
    s = ProfileStore(base)
    s.load(persist=True)
    return s


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


def service(store, home):
    return ArchiveService(store, "main", home=home)


def make_data(folder, root):
    """A data folder as a finished archive leaves it (``root``: its documents folder)."""
    root.mkdir(exist_ok=True)
    paths = AppPaths(folder)
    paths.ensure()
    setup.write_archive_root(paths, root)
    return folder


def test_a_new_or_empty_folder_is_new(store, tmp_path, home):
    assert check_data_folder(str(tmp_path / "fresh"), store, home).state == "new"
    (tmp_path / "empty").mkdir()
    assert check_data_folder(str(tmp_path / "empty"), store, home).state == "new"


def test_a_folder_of_something_else_is_refused(store, tmp_path, home):
    other = tmp_path / "photos"
    other.mkdir()
    (other / "a.jpg").write_bytes(b"x")
    check = check_data_folder(str(other), store, home)
    assert check.state == "refused" and "does not hold dam data" in check.message


def test_a_synced_folder_is_refused(store, tmp_path, home):
    synced = tmp_path / "Library" / "CloudStorage" / "GoogleDrive-x" / "dam"
    check = check_data_folder(str(synced), store, home)
    assert check.state == "refused" and "synced" in check.message


def test_existing_data_is_offered_with_its_documents_folder(store, tmp_path, home):
    root = tmp_path / "docs"
    root.mkdir()
    data = make_data(tmp_path / "copy", root)
    check = check_data_folder(str(data), store, home)
    assert check.state == "dam_data"
    assert check.archive_root == str(root) and check.archive_root_exists is True
    root.rmdir()
    assert check_data_folder(str(data), store, home).archive_root_exists is False


def test_a_folder_of_another_archive_or_its_documents_is_refused(store, tmp_path, home):
    main = store.active()
    assert check_data_folder(str(main.data_dir), store, home).state == "refused"
    assert check_data_folder(str(main.data_dir / "sub"), store, home).state == "refused"
    assert check_data_folder(str(store.base), store, home).state == "refused"
    root = tmp_path / "docs"
    root.mkdir()
    setup.write_archive_root(main.paths, root)
    assert check_data_folder(str(root / "data"), store, home).state == "refused"


def test_data_whose_documents_folder_belongs_to_another_archive_is_refused(store, tmp_path, home):
    root = tmp_path / "docs"
    root.mkdir()
    setup.write_archive_root(store.active().paths, root)
    data = make_data(tmp_path / "copy", root)
    check = check_data_folder(str(data), store, home)
    assert check.state == "refused" and "documents folder" in check.message


def test_data_in_use_by_a_window_is_refused(store, tmp_path, home, monkeypatch):
    data = make_data(tmp_path / "copy", tmp_path / "docs-of-copy")
    monkeypatch.setattr("dam.data_folders.ServeLock.holder", lambda p: {"port": 8766})
    check = check_data_folder(str(data), store, home)
    assert check.state == "refused" and "8766" in check.message


def test_data_from_a_newer_dam_or_another_build_is_refused(store, tmp_path, home):
    data = make_data(tmp_path / "copy", tmp_path / "docs-of-copy")
    con = sqlite3.connect(AppPaths(data).db_path)
    con.execute("CREATE TABLE alembic_version (version_num TEXT)")
    con.execute("INSERT INTO alembic_version VALUES ('9999')")
    con.commit()
    con.close()
    assert check_data_folder(str(data), store, home).state == "refused"
    other = make_data(tmp_path / "other", tmp_path / "docs-of-other")
    con = sqlite3.connect(AppPaths(other).db_path)
    con.execute("CREATE TABLE dam_meta (key TEXT, value TEXT)")
    con.execute("INSERT INTO dam_meta VALUES ('app', 'dam-private')")
    con.commit()
    con.close()
    check = check_data_folder(str(other), store, home)
    assert check.state == "refused" and "another build" in check.message


def test_adding_with_a_data_folder_of_its_own(store, home, tmp_path):
    out = service(store, home).add("Second", None, data_folder=str(tmp_path / "second-data"))
    assert out["data_dir"] == str((tmp_path / "second-data").resolve())
    assert (tmp_path / "second-data" / "config" / "settings.yaml").exists()  # seeded
    assert store.find("second").data_dir == (tmp_path / "second-data").resolve()


def test_existing_data_is_used_only_when_confirmed_and_is_not_changed(store, home, tmp_path):
    data = make_data(tmp_path / "copy", tmp_path / "docs-of-copy")
    before = (data / "config" / "settings.yaml").read_bytes()
    names = sorted(p.name for p in (data / "config").iterdir())
    with pytest.raises(InvalidRequest, match="already holds dam data"):
        service(store, home).add("Moved", None, data_folder=str(data))
    assert [p.name for p in store.load()] == ["Main"]
    out = service(store, home).add("Moved", None, data_folder=str(data), use_existing_data=True)
    assert out["archive_root"] == str(tmp_path / "docs-of-copy")
    assert (data / "config" / "settings.yaml").read_bytes() == before
    assert sorted(p.name for p in (data / "config").iterdir()) == names  # nothing seeded in


def test_a_refused_folder_adds_nothing(store, home, tmp_path):
    with pytest.raises(InvalidRequest, match="synced"):
        service(store, home).add("X", None, data_folder=str(tmp_path / "Dropbox" / "dam"))
    assert [p.name for p in store.load()] == ["Main"]


def test_a_demo_archive_cannot_take_a_data_folder(store, home, tmp_path):
    with pytest.raises(InvalidRequest, match="demo"):
        service(store, home).add(
            "D", None, demo_folder=str(tmp_path / "demo"), data_folder=str(tmp_path / "d")
        )


# -- moving the main folder ---------------------------------------------------------------


def test_changing_the_main_folder(app, app_paths, fake_archive, tmp_path):
    fake_archive.add("Banks/a.pdf", drive_id="a1")
    fake_archive.add("Legal/b.pdf", drive_id="b1")
    app.scan()
    moved = tmp_path / "moved"
    (moved / "Banks").mkdir(parents=True)
    store = ProfileStore(app_paths.data_dir)
    kw = {"store": store, "current_id": "main", "home": tmp_path / "home"}
    dry = change_main_folder(app_paths, app.repo, str(moved), True, **kw)
    assert dry.known >= 2 and dry.missing > 0 and "##. Organize" in dry.examples
    assert setup.current_archive_root(app_paths) == str(fake_archive.root)  # dry: unchanged
    done = change_main_folder(app_paths, app.repo, str(moved), False, **kw)
    assert done.reopen and setup.current_archive_root(app_paths) == str(moved.resolve())


def test_the_main_folder_cannot_be_itself_or_clash(app, app_paths, fake_archive, tmp_path):
    store = ProfileStore(app_paths.data_dir)
    kw = {"store": store, "current_id": "main", "home": tmp_path / "home"}
    with pytest.raises(InvalidRequest, match="already the main folder"):
        change_main_folder(app_paths, app.repo, str(fake_archive.root), False, **kw)
    with pytest.raises(InvalidRequest):  # inside the app's data folder
        change_main_folder(app_paths, app.repo, str(app_paths.data_dir / "x"), False, **kw)
    with pytest.raises(InvalidRequest):
        change_main_folder(app_paths, app.repo, str(tmp_path / "nope"), False, **kw)
    assert setup.current_archive_root(app_paths) == str(fake_archive.root)
