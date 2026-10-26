"""The archive-folders API (list, add, detach, attach), ``folder`` / ``connected`` on the
file records, and the running server reopening its App when the set of folders changes."""

import shutil

import pytest
from fastapi.testclient import TestClient

import dam.serve as serve_mod
from conftest import FakeArchive
from dam.api import create_api
from dam.app import JOBS_RUNNING, App
from dam.config import load_settings
from dam.profiles import ProfileStore, ServeLock
from dam.serve import Host, Switchboard
from dam.services.errors import Conflict

PORT = 8798
BASE = f"http://127.0.0.1:{PORT}"
ORIGIN = {"Origin": BASE}
INBOX = "##. Organize"


def post(c, url, body=None):
    return c.post(url, json=body if body is not None else {}, headers=ORIGIN)


def settings_bytes(app_paths) -> bytes:
    return (app_paths.config_dir / "settings.yaml").read_bytes()


class FakeBackground:
    def __init__(self, app, events):
        self.app, self.events = app, events

    def stop(self):
        self.events.append(("stop", id(self.app)))


@pytest.fixture
def events(monkeypatch):
    log = []

    def fake_start(app):
        log.append(("start", id(app)))
        return FakeBackground(app, log)

    monkeypatch.setattr(serve_mod, "start_background", fake_start)
    return log


@pytest.fixture
def served(app_paths, events):
    """The archive of ``app_paths`` served by a ``Host``, as ``dam serve`` runs it."""
    store = ProfileStore(app_paths.data_dir)
    store.load(persist=True)
    host = Host(store, None, PORT)
    main = store.active()
    lock = ServeLock(main.data_dir)
    lock.acquire(PORT)
    host.profile_id, host.first_lock = main.id, lock
    opened = host._open(main, lock)
    host.attach(Switchboard(opened.api), opened)
    host.start_background()
    client = TestClient(host.board, base_url=BASE)
    yield host, client
    client.close()
    host.shutdown()


@pytest.fixture
def disk(tmp_path) -> FakeArchive:
    """A folder on another fake disk, not part of the archive yet."""
    return FakeArchive(tmp_path / "disk" / "Archive 2000-2015")


@pytest.fixture
def client(app):
    """No ``Host``: the API on its own cannot reopen, so changes say ``restart_needed``."""
    with TestClient(create_api(app), base_url=BASE) as c:
        yield c


@pytest.fixture
def xapp(extra_folder, app_paths):
    """An App whose archive has the extra folder "Old years" (``extra_folder``)."""
    application = App.create(app_paths.data_dir)
    yield application
    application.close()


@pytest.fixture
def xclient(xapp):
    with TestClient(create_api(xapp), base_url=BASE) as c:
        yield c


# -- adding -------------------------------------------------------------------------------


def test_adding_a_folder_reopens_the_app_and_browse_shows_it(served, events, disk, fake_archive):
    host, c = served
    disk.add("2009/receipt.pdf", drive_id="old-1")
    fake_archive.add(f"{INBOX}/new.pdf", drive_id="new-1")
    first = host.current.app
    first.scan()
    r = post(c, "/api/archive-folders", {"label": "Old years", "path": str(disk.root)})
    assert r.status_code == 200, r.text
    assert r.json() == {
        "label": "Old years",
        "path": str(disk.root),
        "files": 0,
        "restart_needed": False,
    }
    # a fresh App was opened and swapped in; the old one's background stopped first
    second = host.current.app
    assert second is not first and second.paths.extra_labels == ("Old years",)
    assert events == [("start", id(first)), ("stop", id(first)), ("start", id(second))]
    # the held lock is kept, not taken again or released
    assert host.current.lock is host.first_lock
    assert ServeLock.holder(host.current.paths.data_dir) is not None
    second.scan()  # the background's initial scan (faked here)

    root = {e["name"]: e for e in c.get("/api/browse").json()}
    assert root["Old years"]["folder"] == "Old years" and root["Old years"]["connected"] is True
    assert root[INBOX]["folder"] is None and root[INBOX]["connected"] is True
    inside = c.get("/api/browse", params={"path": "Old years/2009"}).json()
    assert [(e["name"], e["folder"]) for e in inside] == [("receipt.pdf", "Old years")]

    listing = c.get("/api/archive-folders").json()["folders"]
    assert [(f["label"], f["attached"], f["connected"]) for f in listing] == [
        (None, True, True),
        ("Old years", True, True),
    ]
    assert listing[0]["path"] == str(fake_archive.root)
    assert listing[1]["path"] == str(disk.root)
    old_years = second.repo.count_subtree("Old years", live_only=True)
    assert listing[1]["files"] == old_years and old_years >= 2  # folder 2009 and the file
    assert listing[0]["files"] > 0
    assert second.repo.get("new-1") is not None


def test_a_dry_run_writes_nothing_and_does_not_reopen(served, events, app_paths, disk):
    host, c = served
    before, first = settings_bytes(app_paths), host.current.app
    body = {"label": "Old years", "path": str(disk.root), "dry_run": True}
    r = post(c, "/api/archive-folders", body)
    assert r.status_code == 200, r.text
    assert r.json()["label"] == "Old years" and r.json()["restart_needed"] is False
    assert settings_bytes(app_paths) == before
    assert host.current.app is first and events == [("start", id(first))]


def test_without_a_server_a_change_needs_a_restart(client, app_paths, disk):
    r = post(client, "/api/archive-folders", {"label": "Old years", "path": str(disk.root)})
    assert r.status_code == 200, r.text
    assert r.json()["restart_needed"] is True
    assert [e.label for e in load_settings(app_paths).extra_folders] == ["Old years"]
    # the listing reads the settings, so it shows the folder before the restart
    labels = [f["label"] for f in client.get("/api/archive-folders").json()["folders"]]
    assert labels == [None, "Old years"]


def test_a_failed_reopen_keeps_the_app_and_asks_for_a_restart(served, events, disk, monkeypatch):
    host, c = served
    first = host.current.app
    calls = []

    def flaky(app):
        calls.append(app)
        if len(calls) == 1:
            raise RuntimeError("cannot start threads")
        events.append(("start", id(app)))
        return FakeBackground(app, events)

    monkeypatch.setattr(serve_mod, "start_background", flaky)
    r = post(c, "/api/archive-folders", {"label": "Old years", "path": str(disk.root)})
    assert r.status_code == 200, r.text
    assert r.json()["restart_needed"] is True
    # rolled back: the first App serves again, its background restarted, the lock held
    assert host.current.app is first
    assert events[-2:] == [("stop", id(first)), ("start", id(first))]
    assert ServeLock.holder(host.current.paths.data_dir) is not None
    assert c.get("/api/status").status_code == 200


@pytest.mark.parametrize(
    "label, where, message",
    [
        ("", "disk", "Give the folder a label."),
        (
            "Old years",
            "main",
            "That folder is already part of this archive ('the main folder').",
        ),
        (
            "Old years",
            "inside main",
            "That folder is inside 'the main folder', which is already part of this archive.",
        ),
        (
            "Old years",
            "around main",
            "That folder contains 'the main folder', which is already part of this archive.",
        ),
        (
            "10. Financial",
            "disk",
            "'10. Financial' is already the name of a folder in the main folder. "
            "Choose another label.",
        ),
        ("##. Mine", "disk", "Names starting with ##. are kept for the app's own folders."),
        (
            "Old years",
            "missing",
            "That folder cannot be read right now. Check that it exists and is connected.",
        ),
        ("Old years", "relative", "Give the full path of the folder."),
    ],
)
def test_each_refusal_is_a_400_with_its_message(
    client, app_paths, fake_archive, disk, tmp_path, label, where, message
):
    path = {
        "disk": str(disk.root),
        "main": str(fake_archive.root),
        "inside main": str(fake_archive.root / "10. Financial"),
        "around main": str(fake_archive.root.parent),
        "missing": str(tmp_path / "nowhere"),
        "relative": "disk/Archive 2000-2015",
    }[where]
    before = settings_bytes(app_paths)
    r = post(client, "/api/archive-folders", {"label": label, "path": path})
    assert r.status_code == 400, r.text
    assert r.json()["error"] == message
    assert settings_bytes(app_paths) == before


def test_a_label_already_taken_is_refused(xclient, tmp_path):
    other = FakeArchive(tmp_path / "disk2" / "More")
    r = post(xclient, "/api/archive-folders", {"label": "old YEARS", "path": str(other.root)})
    assert r.status_code == 400
    assert r.json()["error"] == (
        "There is already an archive folder labelled 'old YEARS'. Choose another label."
    )


def test_another_archives_folder_is_refused(served, tmp_path):
    host, c = served
    other = FakeArchive(tmp_path / "otherArch")
    test = host.store.add("Test")
    from dam import setup

    setup.write_archive_root(test.paths, other.root)
    r = post(c, "/api/archive-folders", {"label": "Old years", "path": str(other.root)})
    assert r.status_code == 400 and "Test" in r.json()["error"], r.text


# -- detaching and attaching --------------------------------------------------------------


def test_detach_then_attach(xapp, xclient, extra_folder, app_paths):
    extra_folder.add("2009/receipt.pdf", drive_id="old-1")
    xapp.scan()
    live = xapp.repo.count_subtree("Old years", live_only=True)
    assert live >= 2

    before = settings_bytes(app_paths)
    r = post(xclient, "/api/archive-folders/Old years/detach", {"dry_run": True})
    assert r.status_code == 200, r.text
    assert r.json() == {
        "label": "Old years",
        "path": str(extra_folder.root),
        "files": live,
        "restart_needed": False,
    }
    assert settings_bytes(app_paths) == before
    assert xapp.repo.count_subtree("Old years", live_only=True) == live

    r = post(xclient, "/api/archive-folders/Old years/detach", {})
    assert r.status_code == 200, r.text
    assert r.json()["files"] == live and r.json()["restart_needed"] is True
    assert load_settings(app_paths).extra_folders[0].attached is False
    assert xapp.repo.count_subtree("Old years", live_only=True) == 0
    listing = xclient.get("/api/archive-folders").json()["folders"]
    assert [(f["label"], f["attached"], f["files"]) for f in listing][1] == (
        "Old years",
        False,
        0,
    )

    before = settings_bytes(app_paths)
    r = post(xclient, "/api/archive-folders/Old years/attach", {"dry_run": True})
    assert r.status_code == 200 and r.json()["restart_needed"] is False
    assert settings_bytes(app_paths) == before

    r = post(xclient, "/api/archive-folders/Old years/attach", {})
    assert r.status_code == 200, r.text
    assert r.json()["label"] == "Old years" and r.json()["restart_needed"] is True
    assert load_settings(app_paths).extra_folders[0].attached is True


def test_detach_with_forget_counts_and_removes_the_rows(xapp, xclient, extra_folder):
    extra_folder.add("2009/receipt.pdf", drive_id="old-1")
    xapp.scan()
    every = xapp.repo.count_subtree("Old years")
    r = post(xclient, "/api/archive-folders/Old years/detach", {"forget": True, "dry_run": True})
    assert r.status_code == 200 and r.json()["files"] == every
    assert xapp.repo.get("old-1") is not None
    r = post(xclient, "/api/archive-folders/Old years/detach", {"forget": True})
    assert r.status_code == 200 and r.json()["files"] == every
    assert xapp.repo.get("old-1") is None
    labels = [f["label"] for f in xclient.get("/api/archive-folders").json()["folders"]]
    assert labels == [None]  # the folder left the list


def test_forgetting_in_a_server_reopens_before_the_rows_go(served, events, disk):
    host, c = served
    disk.add("2009/receipt.pdf", drive_id="old-1")
    r = post(c, "/api/archive-folders", {"label": "Old years", "path": str(disk.root)})
    assert r.status_code == 200, r.text
    added = host.current.app
    added.scan()
    assert added.repo.get("old-1") is not None
    r = post(c, "/api/archive-folders/Old years/detach", {"forget": True})
    assert r.status_code == 200 and r.json()["restart_needed"] is False
    fresh = host.current.app
    assert fresh is not added and fresh.paths.extra_labels == ()
    assert fresh.repo.get("old-1") is None
    assert [f["label"] for f in c.get("/api/archive-folders").json()["folders"]] == [None]


def test_detaching_in_a_server_reopens(served, events, disk):
    host, c = served
    r = post(c, "/api/archive-folders", {"label": "Old years", "path": str(disk.root)})
    assert r.status_code == 200, r.text
    added = host.current.app
    r = post(c, "/api/archive-folders/Old years/detach", {})
    assert r.status_code == 200 and r.json()["restart_needed"] is False
    assert host.current.app is not added and host.current.app.paths.extra_labels == ()
    r = post(c, "/api/archive-folders/Old years/attach", {})
    assert r.status_code == 200 and r.json()["restart_needed"] is False
    assert host.current.app.paths.extra_labels == ("Old years",)


def test_an_unknown_label_is_404(client):
    assert post(client, "/api/archive-folders/Nope/detach", {}).status_code == 404
    assert post(client, "/api/archive-folders/Nope/attach", {}).status_code == 404


# -- folder and connected on the records --------------------------------------------------


def test_a_search_hit_in_an_offline_folder_is_not_connected(xapp, xclient, extra_folder, tmp_path):
    extra_folder.add("2009/zebra.txt", content=b"an old zebra receipt", drive_id="old-1")
    xapp.scan()
    xapp.index()
    hits = xclient.get("/api/search", params={"q": "zebra"}).json()
    assert [(h["folder"], h["connected"]) for h in hits] == [("Old years", True)]
    shutil.move(extra_folder.root, tmp_path / "unplugged")  # the disk is unplugged
    hits = xclient.get("/api/search", params={"q": "zebra"}).json()
    assert [(h["drive_id"], h["folder"], h["connected"]) for h in hits] == [
        ("old-1", "Old years", False)
    ]


def test_file_detail_and_collection_members_carry_the_folder(xapp, xclient, extra_folder):
    extra_folder.add("2009/receipt.pdf", drive_id="old-1")
    xapp.scan()
    detail = xclient.get("/api/files/old-1").json()
    assert detail["record"]["folder"] == "Old years" and detail["record"]["connected"] is True
    r = post(xclient, "/api/collections", {"name": "Receipts"})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    r = post(xclient, f"/api/collections/{cid}/members", {"drive_ids": ["old-1"]})
    assert r.status_code == 200, r.text
    members = xclient.get(f"/api/collections/{cid}").json()["members"]
    assert [(m["drive_id"], m["folder"], m["connected"]) for m in members] == [
        ("old-1", "Old years", True)
    ]


def test_tray_files_carry_the_folder_with_one_look_per_response(
    xapp, xclient, extra_folder, fake_archive, tmp_path, monkeypatch
):
    extra_folder.add("2009/letter.pdf", drive_id="old-1")
    fake_archive.add(f"{INBOX}/new.pdf", drive_id="new-1")
    xapp.scan()
    r = post(xclient, "/api/items/quick", {"tray": "to-read", "drive_ids": ["old-1", "new-1"]})
    assert r.status_code == 200, r.text
    old_item, new_item = (i["id"] for i in r.json()["created"])
    shutil.move(extra_folder.root, tmp_path / "unplugged")
    looks = []
    real = xapp.paths.disconnected_labels

    def counted():
        looks.append(1)
        return real()

    monkeypatch.setattr(xapp.paths, "disconnected_labels", counted)

    rows = xclient.get("/api/trays/to-read/items").json()
    assert len(looks) == 1
    first = {row["id"]: row["first_file"] for row in rows}
    assert (first[old_item]["folder"], first[old_item]["connected"]) == ("Old years", False)
    assert (first[new_item]["folder"], first[new_item]["connected"]) == (None, True)

    looks.clear()
    files = xclient.get(f"/api/items/{old_item}/files").json()
    assert len(looks) == 1
    assert [(f["drive_id"], f["folder"], f["connected"]) for f in files] == [
        ("old-1", "Old years", False)
    ]


# -- running jobs ---------------------------------------------------------------------


@pytest.mark.parametrize("which", ["maintenance", "replay"])
def test_no_change_while_a_job_runs(xapp, xclient, app_paths, disk, monkeypatch, which):
    jobs = xapp.maintenance.jobs if which == "maintenance" else xapp.replay_jobs
    monkeypatch.setattr(jobs, "running", lambda: True)
    before = settings_bytes(app_paths)
    for url, body in (
        ("/api/archive-folders", {"label": "More", "path": str(disk.root)}),
        ("/api/archive-folders/Old years/detach", {}),
        ("/api/archive-folders/Old years/detach", {"forget": True}),
        ("/api/archive-folders/Old years/attach", {}),
    ):
        r = post(xclient, url, body)
        assert r.status_code == 409, (url, r.text)
        assert r.json()["error"] == JOBS_RUNNING
    assert settings_bytes(app_paths) == before
    assert [e.label for e in load_settings(app_paths).extra_folders] == ["Old years"]


def test_host_reopen_refuses_while_a_job_runs(served, events, monkeypatch):
    host, _ = served
    first = host.current.app
    monkeypatch.setattr(first.replay_jobs, "running", lambda: True)
    with pytest.raises(Conflict, match="rule replay or move across disks is running"):
        host.reopen()
    assert host.current.app is first and events == [("start", id(first))]
