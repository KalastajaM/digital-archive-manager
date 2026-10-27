"""Snapshots of the database and settings, and restoring one inside a running server."""

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
import yaml
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

import dam.serve as serve_mod
from conftest import FakeArchive
from dam import setup, snapshots
from dam.app import BATCH_RUNNING
from dam.config import AppPaths
from dam.db.engine import MIGRATIONS_DIR, make_engine, write_tx
from dam.ops.executor import BATCH_HELD
from dam.ops.model import Op, OpKind, Plan
from dam.profiles import ProfileStore, ServeLock
from dam.serve import Host, Switchboard
from dam.services.errors import Conflict
from dam.services.snapshots import SnapshotService
from dam.snapshots import Folders

PORT = 8798
BASE_URL = f"http://127.0.0.1:{PORT}"
ORIGIN = {"Origin": BASE_URL}


def post(c, url, body=None):
    return c.post(url, json=body if body is not None else {}, headers=ORIGIN)


class FakeBackground:
    def __init__(self, events):
        self.events = events

    def stop(self):
        self.events.append("stop")


@pytest.fixture
def events(monkeypatch):
    log = []

    def fake_start(app):
        log.append("start")
        return FakeBackground(log)

    monkeypatch.setattr(serve_mod, "start_background", fake_start)
    return log


@pytest.fixture
def served(tmp_path, events):
    """One archive served by a Host, as ``dam serve`` does it."""
    base = tmp_path / "base"
    paths = AppPaths(base)
    paths.ensure()
    arch = FakeArchive(tmp_path / "arch")
    setup.write_archive_root(paths, arch.root)
    store = ProfileStore(base)
    store.load(persist=True)
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
    yield host, client, paths
    client.close()
    host.shutdown()
    opened.app.close()


def collection_names(c) -> list[str]:
    return [g["name"] for g in c.get("/api/collections").json()]


def test_a_snapshot_holds_the_database_settings_and_state_but_not_cache_or_logs(served):
    host, c, paths = served
    (paths.data_dir / "ai-state.json").write_text('{"enabled": false}', encoding="utf-8")
    (paths.cache_dir / "thumb.bin").write_bytes(b"x")
    (paths.logs_dir / "dam.log").write_text("log", encoding="utf-8")
    r = post(c, "/api/snapshots")
    assert r.status_code == 200, r.text
    made = r.json()
    assert made["kind"] == "manual" and made["problem"] is None
    assert made["revision"] == snapshots.head_revision()
    with zipfile.ZipFile(paths.data_dir / "snapshots" / made["name"]) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json"))
    assert {"dam.sqlite", "config/settings.yaml", "ai-state.json", "manifest.json"} <= names
    assert "config/filing_codes.yaml" in names
    assert any(n.startswith("config/trays/") for n in names)
    assert not any(n.startswith(("cache/", "logs/", "snapshots/")) for n in names)
    assert "serve.lock" not in names and "archives.yaml" not in names
    assert manifest["archive_root"] == str(host.current.app.settings.archive_root)
    listing = c.get("/api/snapshots").json()
    assert listing["can_restore"] is True
    assert [b["name"] for b in listing["snapshots"]] == [made["name"]]
    # no half-made zip or temporary folder is left behind
    assert [p.name for p in (paths.data_dir / "snapshots").iterdir()] == [made["name"]]


def test_restore_needs_the_question_answered(served):
    _, c, _ = served
    name = post(c, "/api/snapshots").json()["name"]
    r = post(c, f"/api/snapshots/{name}/restore", {})
    assert r.status_code in (400, 422)


def test_restore_puts_back_the_database_and_settings_and_moves_the_current_aside(served, events):
    host, c, paths = served
    name = post(c, "/api/snapshots").json()["name"]
    # changes after the snapshot: a collection (database), a new rule file and a state file
    assert post(c, "/api/collections", {"name": "After snapshot"}).status_code == 200
    extra = paths.config_dir / "rules" / "99-after.yaml"
    extra.write_text("rules: []\n", encoding="utf-8")
    (paths.data_dir / "rules-state.json").write_text('{"offer": false}', encoding="utf-8")
    assert "After snapshot" in collection_names(c)
    old_app = host.current.app

    r = post(c, f"/api/snapshots/{name}/restore", {"snapshot_current": True})
    assert r.status_code == 200, r.text
    out = r.json()
    # the archive was closed and opened again
    assert host.current.app is not old_app
    assert events[-2:] == ["stop", "start"]
    # the state before the restore was backed up first
    safety = out["safety_snapshot"]
    assert safety["kind"] == "before-restore" and safety["name"].endswith("-before-restore.zip")
    with zipfile.ZipFile(paths.data_dir / "snapshots" / safety["name"]) as zf:
        assert "config/rules/99-after.yaml" in zf.namelist()
    # the database and the settings are the snapshot's
    assert "After snapshot" not in collection_names(c)
    assert not extra.exists()
    assert not (paths.data_dir / "rules-state.json").exists()
    # nothing was deleted: the replaced settings were moved aside
    replaced = Path(out["replaced_folder"])
    assert replaced.parent == paths.data_dir / "snapshots"
    assert (replaced / "config" / "rules" / "99-after.yaml").is_file()
    assert (replaced / "rules-state.json").read_text(encoding="utf-8") == '{"offer": false}'
    # the safety snapshot restores the later state again
    r = post(c, f"/api/snapshots/{safety['name']}/restore", {"snapshot_current": False})
    assert r.status_code == 200, r.text
    assert r.json()["safety_snapshot"] is None
    assert "After snapshot" in collection_names(c)
    assert extra.is_file()


def _rezip(source: Path, target: Path, change) -> None:
    """Copy snapshot ``source`` to ``target``, passing each (name, data) through ``change``."""
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "x") as dst:
        for name in src.namelist():
            for item in change(name, src.read(name)):
                dst.writestr(*item)


def test_a_snapshot_from_an_older_revision_is_migrated_on_restore(served, tmp_path):
    host, c, paths = served
    name = post(c, "/api/snapshots").json()["name"]
    old_db = tmp_path / "old.sqlite"
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    engine = make_engine(old_db)
    with write_tx(engine) as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0033")
    engine.dispose()
    older = "dam-snapshot-20200101-000000.zip"

    def to_old(member, data):
        if member == "dam.sqlite":
            data = old_db.read_bytes()
        if member == "manifest.json":
            manifest = json.loads(data)
            manifest["revision"] = "0033"
            data = json.dumps(manifest).encode("utf-8")
        yield member, data

    _rezip(paths.data_dir / "snapshots" / name, paths.data_dir / "snapshots" / older, to_old)
    info = {b["name"]: b for b in c.get("/api/snapshots").json()["snapshots"]}[older]
    assert info["revision"] == "0033" and info["problem"] is None
    r = post(c, f"/api/snapshots/{older}/restore", {"snapshot_current": False})
    assert r.status_code == 200, r.text
    assert snapshots.db_revision(paths.db_path) == snapshots.head_revision()
    assert host.current.app is not None and collection_names(c) == []


def test_a_snapshot_from_an_unknown_revision_is_refused_before_anything_changes(served):
    host, c, paths = served
    name = post(c, "/api/snapshots").json()["name"]
    newer = "dam-snapshot-20990101-000000.zip"

    def to_new(member, data):
        if member == "manifest.json":
            manifest = json.loads(data)
            manifest["revision"] = "9999_future"
            data = json.dumps(manifest).encode("utf-8")
        yield member, data

    _rezip(paths.data_dir / "snapshots" / name, paths.data_dir / "snapshots" / newer, to_new)
    info = {b["name"]: b for b in c.get("/api/snapshots").json()["snapshots"]}[newer]
    assert "newer or different version" in info["problem"]
    app = host.current.app
    r = post(c, f"/api/snapshots/{newer}/restore", {"snapshot_current": True})
    assert r.status_code == 409
    assert host.current.app is app  # never closed
    assert not any("before-restore" in p.name for p in (paths.data_dir / "snapshots").iterdir())


@pytest.mark.parametrize("bad", ["../escape.txt", "/abs.txt", "logs/dam.log", "config/../x"])
def test_unsafe_or_unexpected_entries_are_refused(served, bad):
    host, c, paths = served
    name = post(c, "/api/snapshots").json()["name"]
    evil = "dam-snapshot-20200202-000000.zip"

    def add_bad(member, data):
        yield member, data
        if member == "manifest.json":
            yield bad, b"x"

    _rezip(paths.data_dir / "snapshots" / name, paths.data_dir / "snapshots" / evil, add_bad)
    app = host.current.app
    r = post(c, f"/api/snapshots/{evil}/restore", {"snapshot_current": False})
    assert r.status_code in (400, 409), r.text
    assert host.current.app is app
    assert not (paths.data_dir.parent / "escape.txt").exists()


def test_a_damaged_database_is_refused(served):
    host, c, paths = served
    name = post(c, "/api/snapshots").json()["name"]
    broken = "dam-snapshot-20200303-000000.zip"

    def damage(member, data):
        yield member, (b"not a database" * 100 if member == "dam.sqlite" else data)

    _rezip(paths.data_dir / "snapshots" / name, paths.data_dir / "snapshots" / broken, damage)
    r = post(c, f"/api/snapshots/{broken}/restore", {"snapshot_current": False})
    assert r.status_code == 400, r.text


def test_a_snapshot_of_another_archive_folder_needs_a_yes_and_keeps_this_archives_folders(
    served, tmp_path
):
    host, c, paths = served
    name = post(c, "/api/snapshots").json()["name"]
    assert post(c, "/api/collections", {"name": "After snapshot"}).status_code == 200
    other = "dam-snapshot-20200404-000000.zip"
    elsewhere_root = str(tmp_path / "other-computer" / "Archive")

    def elsewhere(member, data):
        if member == "manifest.json":
            manifest = json.loads(data)
            manifest["archive_root"] = elsewhere_root
            data = json.dumps(manifest).encode("utf-8")
        if member == "config/settings.yaml":
            raw = yaml.safe_load(data)
            raw["archive_root"] = elsewhere_root
            data = yaml.safe_dump(raw).encode("utf-8")
        yield member, data

    _rezip(paths.data_dir / "snapshots" / name, paths.data_dir / "snapshots" / other, elsewhere)
    info = {s["name"]: s for s in c.get("/api/snapshots").json()["snapshots"]}
    assert info[other]["other_folder"] is True and info[other]["problem"] is None
    assert info[name]["other_folder"] is False
    root = host.current.app.settings.archive_root
    app = host.current.app
    r = post(c, f"/api/snapshots/{other}/restore", {"snapshot_current": False})
    assert r.status_code == 409 and "another archive folder" in r.json()["error"]
    assert host.current.app is app  # nothing changed
    r = post(
        c, f"/api/snapshots/{other}/restore", {"snapshot_current": False, "other_folder_ok": True}
    )
    assert r.status_code == 200, r.text
    assert r.json()["kept_folders"] is True
    assert host.current.app.settings.archive_root == root
    assert "After snapshot" not in collection_names(c)


def test_export_downloads_the_zip_as_it_is(served):
    _, c, paths = served
    name = post(c, "/api/snapshots").json()["name"]
    r = c.get(f"/api/snapshots/{name}/download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert (
        "attachment" in r.headers["content-disposition"]
        and name in r.headers["content-disposition"]
    )
    assert r.content == (paths.data_dir / "snapshots" / name).read_bytes()
    assert c.get("/api/snapshots/dam-snapshot-20200101-000000.zip/download").status_code == 404


def upload(c, data: bytes):
    return c.post(
        "/api/snapshots/import",
        content=data,
        headers={**ORIGIN, "Content-Type": "application/octet-stream"},
    )


def test_an_exported_snapshot_can_be_imported_and_restored(served):
    host, c, paths = served
    name = post(c, "/api/snapshots").json()["name"]
    exported = c.get(f"/api/snapshots/{name}/download").content
    assert post(c, "/api/collections", {"name": "After snapshot"}).status_code == 200
    r = upload(c, exported)
    assert r.status_code == 200, r.text
    added = r.json()
    assert added["imported"] is True and added["name"].endswith("-imported.zip")
    assert added["name"].startswith(name.removesuffix(".zip"))  # named by when it was taken
    assert added["problem"] is None and added["other_folder"] is False
    assert (paths.data_dir / "snapshots" / added["name"]).read_bytes() == exported
    # importing the same file again gets a new name, nothing is overwritten
    again = upload(c, exported).json()["name"]
    assert again != added["name"] and again.endswith("-imported.zip")
    r = post(c, f"/api/snapshots/{added['name']}/restore", {"snapshot_current": False})
    assert r.status_code == 200, r.text
    assert "After snapshot" not in collection_names(c)


@pytest.mark.parametrize("kind", ["not a zip", "unsafe entry", "damaged database", "empty"])
def test_import_refuses_what_is_not_a_good_snapshot(served, kind):
    _, c, paths = served
    name = post(c, "/api/snapshots").json()["name"]
    good = paths.data_dir / "snapshots" / name
    bad = paths.data_dir.parent / "bad.zip"

    def spoil(member, data):
        if kind == "damaged database" and member == "dam.sqlite":
            data = b"not a database" * 100
        yield member, data
        if kind == "unsafe entry" and member == "manifest.json":
            yield "../escape.txt", b"x"

    if kind == "not a zip":
        data = b"PK but not really"
    elif kind == "empty":
        data = b""
    else:
        _rezip(good, bad, spoil)
        data = bad.read_bytes()
    r = upload(c, data)
    assert r.status_code == 400, r.text
    # nothing was added, and no temporary folder is left behind
    assert [p.name for p in (paths.data_dir / "snapshots").iterdir()] == [name]
    assert not (paths.data_dir.parent / "escape.txt").exists()


def test_names_are_never_paths(served):
    _, c, _ = served
    r = post(c, "/api/snapshots/..%2Fdam.sqlite/restore", {"snapshot_current": False})
    assert r.status_code in (400, 404)
    r = post(
        c, "/api/snapshots/dam-snapshot-20200101-000000.zip/restore", {"snapshot_current": False}
    )
    assert r.status_code == 404


def test_restore_is_refused_without_a_host_or_with_an_interrupted_operation(tmp_path):
    paths = AppPaths(tmp_path / "data")
    paths.ensure()
    sqlite3.connect(paths.db_path).close()
    alone = SnapshotService(paths, Folders(None))
    with pytest.raises(Conflict, match="cannot restore"):
        alone.restore("dam-snapshot-20200101-000000.zip", snapshot_current=False)

    class Reopen:
        def close_and_reopen(self, change):
            return change()

    interrupted = SnapshotService(paths, Folders(None), Reopen(), pending=lambda: True)
    with pytest.raises(Conflict, match="dam recover"):
        interrupted.restore("dam-snapshot-20200101-000000.zip", snapshot_current=False)


def test_restore_waits_for_a_running_batch_and_holds_new_ones(served, monkeypatch):
    """A batch carried out in another request keeps journaling: the database is not
    replaced under it. While the restore runs, no batch starts."""
    host, c, _ = served
    name = post(c, "/api/snapshots").json()["name"]
    assert post(c, "/api/collections", {"name": "After snapshot"}).status_code == 200
    app = host.current.app
    app.executor.batches.begin("running-batch")
    r = post(c, f"/api/snapshots/{name}/restore", {"snapshot_current": False})
    assert r.status_code == 409 and r.json()["error"] == BATCH_RUNNING
    assert host.current.app is app and "After snapshot" in collection_names(c)
    app.executor.batches.end("running-batch")

    seen = []
    real = snapshots.apply_restore

    def restore_and_try_a_batch(*args):
        with pytest.raises(Conflict) as e:
            app.executor.apply(Plan([Op(OpKind.MKDIR, None, "10. Financial/New")], origin="ui"))
        seen.append(str(e.value))
        return real(*args)

    monkeypatch.setattr(snapshots, "apply_restore", restore_and_try_a_batch)
    r = post(c, f"/api/snapshots/{name}/restore", {"snapshot_current": False})
    assert r.status_code == 200, r.text
    assert seen == [BATCH_HELD]
    assert "After snapshot" not in collection_names(c)


def test_import_takes_only_a_raw_file_body(served):
    _, c, _ = served
    # a plain cross-site form can only send these types: refused before any route runs
    for kind in ("text/plain", "multipart/form-data; boundary=x"):
        r = c.post("/api/snapshots/import", content=b"x", headers={**ORIGIN, "Content-Type": kind})
        assert r.status_code == 415
