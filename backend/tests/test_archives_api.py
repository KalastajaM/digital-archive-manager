"""The archives API and switching archives inside one running server (``serve.Host``)."""

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import dam.serve as serve_mod
from conftest import FakeArchive
from dam import setup
from dam.api import create_api
from dam.app import App
from dam.config import AppPaths
from dam.profiles import ProfileStore, ServeLock
from dam.serve import Host, Opened, Switchboard

PORT = 8797
BASE_URL = f"http://127.0.0.1:{PORT}"
ORIGIN = {"Origin": BASE_URL}
INBOX = "##. Organize"


def post(c, url, body=None, **headers):
    return c.post(url, json=body if body is not None else {}, headers={**ORIGIN, **headers})


class FakeBackground:
    def __init__(self, app, events):
        self.app, self.events = app, events

    def stop(self):
        self.events.append(("stop", self.app.paths.root.name))


@pytest.fixture
def events(monkeypatch):
    log = []

    def fake_start(app):
        log.append(("start", app.paths.root.name))
        return FakeBackground(app, log)

    monkeypatch.setattr(serve_mod, "start_background", fake_start)
    return log


@pytest.fixture
def world(tmp_path, events):
    """Main (archive 'archA') and Test (archive 'archB'), served by one Host."""
    base = tmp_path / "base"
    paths = AppPaths(base)
    paths.ensure()
    arch_a, arch_b = FakeArchive(tmp_path / "archA"), FakeArchive(tmp_path / "archB")
    arch_a.add(f"{INBOX}/a-only.pdf", drive_id="a-1")
    arch_b.add(f"{INBOX}/b-only.pdf", drive_id="b-1")
    setup.write_archive_root(paths, arch_a.root)
    store = ProfileStore(base)
    store.load(persist=True)
    test = store.add("Test")
    setup.write_archive_root(test.paths, arch_b.root)

    host = Host(store, None, PORT)
    main = store.active()
    lock = ServeLock(main.data_dir)
    lock.acquire(PORT)
    host.profile_id, host.first_lock = main.id, lock
    opened = host._open(main, lock)
    opened.owns_app = False
    board = Switchboard(opened.api)
    host.attach(board, opened)
    host.start_background()
    client = TestClient(board, base_url=BASE_URL)
    yield type("World", (), {})(), host, client, store, arch_a, arch_b
    client.close()
    host.shutdown()
    opened.app.close()


def unpack(world):
    _, host, client, store, arch_a, arch_b = world
    return host, client, store, arch_a, arch_b


def test_status_and_list_name_the_archive_in_use(world):
    host, c, store, *_ = unpack(world)
    status = c.get("/api/status").json()
    assert status["archive"]["id"] == "main" and status["archive"]["name"] == "Main"
    assert status["profiles_count"] == 2
    listing = c.get("/api/archives").json()
    assert listing["current"] == "main" and listing["can_switch"] is True
    by_id = {a["id"]: a for a in listing["archives"]}
    assert by_id["main"]["current"] and not by_id["test"]["current"]
    assert by_id["test"]["configured"] and by_id["test"]["archive_root"].endswith("archB")
    assert Path(by_id["test"]["data_dir"]).parts[-2:] == ("archives", "test")


def test_switching_stops_one_archives_background_before_the_others_starts(world, events):
    host, c, store, arch_a, arch_b = unpack(world)
    assert events == [("start", "archA")]
    old_app = host.current.app
    r = post(c, "/api/archives/test/switch")
    assert r.status_code == 200, r.text
    assert r.json()["archive"]["id"] == "test" and r.json()["restart_needed"] is False
    # never two archives' background work at once
    assert events == [("start", "archA"), ("stop", "archA"), ("start", "archB")]
    assert store.active().id == "test"
    status = c.get("/api/status").json()
    assert status["archive"]["id"] == "test"
    assert host.current.app.paths.root == arch_b.root and host.current.app is not old_app
    # the old archive's App was closed (its indexer accepts no more work)
    assert old_app.content.run_once() == 0
    # requests now see the other archive's files only
    host.current.app.scan()
    names = [row["record"]["name"] for row in c.get("/api/inbox").json()]
    assert "b-only.pdf" in names and "a-only.pdf" not in names
    # and back again
    assert post(c, "/api/archives/main/switch", **{"X-Dam-Archive": "test"}).status_code == 200
    assert events[-2:] == [("stop", "archB"), ("start", "archA")]


def test_a_stale_window_cannot_change_the_other_archive(world):
    host, c, *_ = unpack(world)
    assert post(c, "/api/archives/test/switch").status_code == 200
    # a tab that still thinks Main is open
    r = post(c, "/api/inbox/refresh", {}, **{"X-Dam-Archive": "main"})
    assert r.status_code == 409 and "different archive" in r.json()["error"]
    r = post(c, "/api/collections", {"name": "x"}, **{"X-Dam-Archive": "main"})
    assert r.status_code == 409
    # the right id, or none (curl), is fine; reads are never refused
    assert (
        post(c, "/api/collections", {"name": "x"}, **{"X-Dam-Archive": "test"}).status_code == 200
    )
    assert post(c, "/api/collections", {"name": "y"}).status_code == 200
    assert c.get("/api/status", headers={"X-Dam-Archive": "main"}).status_code == 200
    # the archives routes name their target themselves
    assert post(c, "/api/archives/main/switch", **{"X-Dam-Archive": "main"}).status_code == 200


def test_a_profile_served_by_another_process_is_refused_with_its_port(world, events):
    host, c, store, *_ = unpack(world)
    other = ServeLock(store.find("test").data_dir)
    other.acquire(8123)
    try:
        listing = {a["id"]: a for a in c.get("/api/archives").json()["archives"]}
        assert listing["test"]["in_use_elsewhere"] and listing["test"]["port"] == 8123
        r = post(c, "/api/archives/test/switch")
        assert r.status_code == 409 and "8123" in r.json()["error"]
        assert store.active().id == "main"  # nothing changed
        assert events == [("start", "archA")]
        assert c.get("/api/status").json()["archive"]["id"] == "main"
    finally:
        other.release()
    assert post(c, "/api/archives/test/switch").status_code == 200


def test_a_failed_open_leaves_the_current_archive_running(world, events, tmp_path):
    host, c, store, arch_a, arch_b = unpack(world)
    import shutil

    shutil.move(arch_b.root, tmp_path / "away")  # the archive folder is gone (Drive off)
    r = post(c, "/api/archives/test/switch")
    assert r.status_code == 400 and "not available" in r.json()["error"]
    assert events == [("start", "archA")]
    assert store.active().id == "main"
    assert c.get("/api/status").json()["archive"]["id"] == "main"
    # the lock of the archive that failed to open was released again
    assert ServeLock.holder(store.find("test").data_dir) is None


def test_a_failing_start_puts_the_first_archive_back(world, events, monkeypatch):
    host, c, store, arch_a, arch_b = unpack(world)
    calls = []

    def flaky(app):
        calls.append(app.paths.root.name)
        if app.paths.root.name == "archB":
            raise RuntimeError("cannot start threads")
        events.append(("start", app.paths.root.name))
        return FakeBackground(app, events)

    monkeypatch.setattr(serve_mod, "start_background", flaky)
    with pytest.raises(RuntimeError):
        host.switch("test")
    assert host.current.profile_id == "main"
    assert c.get("/api/status").json()["archive"]["id"] == "main"
    assert store.active().id == "main"
    assert events[-1] == ("start", "archA")  # main's background runs again
    assert ServeLock.holder(store.find("test").data_dir) is None


def test_adding_updating_and_forgetting(world, tmp_path):
    host, c, store, arch_a, arch_b = unpack(world)
    r = post(c, "/api/archives", {"name": "Third", "color": "#112233"})
    assert r.status_code == 200, r.text
    third = r.json()
    assert third["id"] == "third" and third["configured"] is False and third["color"] == "#112233"
    assert post(c, "/api/archives", {"name": "third"}).status_code == 409  # name taken
    assert post(c, "/api/archives", {"name": ""}).status_code == 400
    assert post(c, "/api/archives", {"name": "X", "color": "red"}).status_code == 400
    assert post(c, "/api/archives", {"name": "X", "extra": 1}).status_code == 422
    r = c.patch("/api/archives/third", json={"name": "Renamed", "color": "#445566"}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["name"] == "Renamed" and r.json()["color"] == "#445566"
    assert c.patch("/api/archives/nope", json={"name": "Q"}, headers=ORIGIN).status_code == 404
    # forgetting says where the folders are, and deletes nothing
    data_dir = store.find("third").data_dir
    r = post(c, "/api/archives/third/forget", {})
    assert r.status_code == 200
    assert r.json()["data_dir"] == str(data_dir) and r.json()["forgotten"]["id"] == "third"
    assert data_dir.is_dir()
    assert [p.id for p in store.load()] == ["main", "test"]
    # the archive in use needs another one to open instead
    r = post(c, "/api/archives/main/forget", {})
    assert r.status_code == 409 and "in use" in r.json()["error"]
    assert (arch_a.root / INBOX / "a-only.pdf").is_file()
    r = post(c, "/api/archives/main/forget", {"switch_to": "test"})
    assert r.status_code == 200, r.text
    assert [p.id for p in store.load()] == ["test"] and store.active().id == "test"
    assert (arch_a.root / INBOX / "a-only.pdf").is_file()  # the archive is untouched
    assert (store.base / "config" / "settings.yaml").is_file()  # so is Main's data folder
    # the last one stays
    r = post(c, "/api/archives/test/forget", {"switch_to": "test"})
    assert r.status_code == 409


def test_a_demo_archive_is_built_in_the_chosen_folder(world, tmp_path):
    host, c, store, arch_a, arch_b = unpack(world)
    demo = tmp_path / "demo-archive"
    r = post(c, "/api/archives", {"name": "Demo", "demo_folder": str(demo)})
    assert r.status_code == 200, r.text
    assert r.json()["configured"] and r.json()["archive_root"] == str(demo.resolve())
    assert (demo / INBOX).is_dir() and list((demo / INBOX).glob("*.pdf"))
    settings = yaml.safe_load(
        (store.find("demo").data_dir / "config" / "settings.yaml").read_text(encoding="utf-8")
    )
    assert settings["archive_root"] == str(demo.resolve())
    assert settings["reminders"]["mac"] is False
    # Main's archive was not touched
    assert [p.name for p in arch_a.root.rglob("*.pdf")] == ["a-only.pdf"]


def test_a_demo_folder_must_be_empty_and_clear_of_the_other_archives(world, tmp_path):
    host, c, store, arch_a, arch_b = unpack(world)
    full = tmp_path / "full"
    full.mkdir()
    (full / "x.txt").write_text("x", encoding="utf-8")
    for folder in (full, arch_a.root, arch_a.root / "inside", store.base / "inside"):
        r = post(c, "/api/archives", {"name": "Demo", "demo_folder": str(folder)})
        assert r.status_code == 400, (folder, r.text)
    assert [p.id for p in store.load()] == ["main", "test"]  # nothing half-made
    assert (full / "x.txt").read_text(encoding="utf-8") == "x"


def test_archive_routes_follow_the_local_only_rules(world):
    host, c, *_ = unpack(world)
    body = {"name": "Evil"}
    assert c.post("/api/archives", json=body).status_code == 403
    r = c.post("/api/archives", json=body, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    r = c.post("/api/archives", content="a=b", headers={**ORIGIN, "Content-Type": "text/plain"})
    assert r.status_code == 415
    assert c.get("/api/archives", headers={"Host": "evil.example"}).status_code == 403


def test_reveal_opens_a_folder_from_the_registry_only(world, monkeypatch):
    host, c, store, arch_a, arch_b = unpack(world)
    opened = []
    host.current.archives.runner = lambda args: opened.append(args) or 0
    r = post(c, "/api/archives/test/reveal", {"what": "archive"})
    assert r.status_code == 204
    assert str(arch_b.root.resolve()) in opened[-1][-1]
    r = post(c, "/api/archives/test/reveal", {"what": "data"})
    assert r.status_code == 204 and Path(opened[-1][-1]).parts[-2:] == ("archives", "test")
    assert post(c, "/api/archives/test/reveal", {"what": "/etc"}).status_code == 422


def test_switching_to_an_archive_that_is_not_set_up_opens_setup_then_the_app(world, events):
    host, c, store, arch_a, arch_b = unpack(world)
    fresh = post(c, "/api/archives", {"name": "Fresh"}).json()
    assert post(c, f"/api/archives/{fresh['id']}/switch").status_code == 200
    assert events[-1] == ("stop", "archA")  # nothing starts for an archive with no folder yet
    status = c.get("/api/status").json()
    assert status["configured"] is False and status["archive"]["id"] == "fresh"
    assert c.get("/api/inbox").status_code == 409  # setup mode answers only setup
    # Main's and Test's archive folders are off limits for the new archive
    for folder in (arch_a.root, arch_b.root, arch_a.root / "sub"):
        r = post(c, "/api/setup/validate", {"path": str(folder)})
        assert r.json()["ok"] is False and "archive folder" in r.json()["message"]
    # a stale tab (Main) cannot configure it
    arch_c = FakeArchive(arch_a.root.parent / "archC")
    r = post(c, "/api/setup", {"archive_root": str(arch_c.root)}, **{"X-Dam-Archive": "main"})
    assert r.status_code == 409
    r = post(c, "/api/setup", {"archive_root": str(arch_c.root)}, **{"X-Dam-Archive": "fresh"})
    assert r.status_code == 200 and r.json()["restart_needed"] is False
    assert events[-1] == ("start", "archC")  # its background runs now
    assert c.get("/api/status").json()["configured"] is True
    assert c.get("/api/status").json()["archive"]["id"] == "fresh"
    # Main's settings were never written
    main_root = setup.current_archive_root(AppPaths(store.find("main").data_dir))
    assert main_root == str(arch_a.root)


def test_without_a_host_the_api_cannot_switch(app):
    with TestClient(create_api(app), base_url=BASE_URL) as c:
        assert c.get("/api/archives").json()["can_switch"] is False
        assert c.get("/api/status").json()["archive"]["id"] == "main"
        added = post(c, "/api/archives", {"name": "Other"})
        assert added.status_code == 200
        r = post(c, "/api/archives/other/switch")
        assert r.status_code == 409 and "--archive" in r.json()["error"]


def test_opened_dataclass_defaults():
    o = Opened("x", lambda *a: None, None, True)
    assert o.background is None and o.lock is None


def test_shutdown_stops_the_background_and_releases_the_lock(world, events):
    host, c, store, *_ = unpack(world)
    assert post(c, "/api/archives/test/switch").status_code == 200
    host.shutdown()
    assert events[-1] == ("stop", "archB")
    assert ServeLock.holder(store.find("test").data_dir) is None
    assert ServeLock.holder(store.find("main").data_dir) is None
    with pytest.raises(Exception, match="stopping"):
        host.switch("main")


def test_app_create_still_works_on_a_plain_data_dir(app_paths):
    app = App.create(app_paths.data_dir)
    app.close()
