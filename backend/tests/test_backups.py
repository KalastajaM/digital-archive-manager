"""Backups of the database and settings, and restoring one inside a running server."""

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

import dam.serve as serve_mod
from conftest import FakeArchive
from dam import backups, setup
from dam.config import AppPaths
from dam.db.engine import MIGRATIONS_DIR, make_engine, write_tx
from dam.profiles import ProfileStore, ServeLock
from dam.serve import Host, Switchboard
from dam.services.backups import BackupService
from dam.services.errors import Conflict

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


def test_a_backup_holds_the_database_settings_and_state_but_not_cache_or_logs(served):
    host, c, paths = served
    (paths.data_dir / "ai-state.json").write_text('{"enabled": false}', encoding="utf-8")
    (paths.cache_dir / "thumb.bin").write_bytes(b"x")
    (paths.logs_dir / "dam.log").write_text("log", encoding="utf-8")
    r = post(c, "/api/backups")
    assert r.status_code == 200, r.text
    made = r.json()
    assert made["kind"] == "manual" and made["problem"] is None
    assert made["revision"] == backups.head_revision()
    with zipfile.ZipFile(paths.data_dir / "backups" / made["name"]) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read("manifest.json"))
    assert {"dam.sqlite", "config/settings.yaml", "ai-state.json", "manifest.json"} <= names
    assert "config/filing_codes.yaml" in names
    assert any(n.startswith("config/trays/") for n in names)
    assert not any(n.startswith(("cache/", "logs/", "backups/")) for n in names)
    assert "serve.lock" not in names and "archives.yaml" not in names
    assert manifest["archive_root"] == str(host.current.app.settings.archive_root)
    listing = c.get("/api/backups").json()
    assert listing["can_restore"] is True
    assert [b["name"] for b in listing["backups"]] == [made["name"]]
    # no half-made zip or temporary folder is left behind
    assert [p.name for p in (paths.data_dir / "backups").iterdir()] == [made["name"]]


def test_restore_needs_the_question_answered(served):
    _, c, _ = served
    name = post(c, "/api/backups").json()["name"]
    r = post(c, f"/api/backups/{name}/restore", {})
    assert r.status_code in (400, 422)


def test_restore_puts_back_the_database_and_settings_and_moves_the_current_aside(served, events):
    host, c, paths = served
    name = post(c, "/api/backups").json()["name"]
    # changes after the backup: a collection (database), a new rule file and a state file
    assert post(c, "/api/collections", {"name": "After backup"}).status_code == 200
    extra = paths.config_dir / "rules" / "99-after.yaml"
    extra.write_text("rules: []\n", encoding="utf-8")
    (paths.data_dir / "rules-state.json").write_text('{"offer": false}', encoding="utf-8")
    assert "After backup" in collection_names(c)
    old_app = host.current.app

    r = post(c, f"/api/backups/{name}/restore", {"backup_current": True})
    assert r.status_code == 200, r.text
    out = r.json()
    # the archive was closed and opened again
    assert host.current.app is not old_app
    assert events[-2:] == ["stop", "start"]
    # the state before the restore was backed up first
    safety = out["safety_backup"]
    assert safety["kind"] == "before-restore" and safety["name"].endswith("-before-restore.zip")
    with zipfile.ZipFile(paths.data_dir / "backups" / safety["name"]) as zf:
        assert "config/rules/99-after.yaml" in zf.namelist()
    # the database and the settings are the backup's
    assert "After backup" not in collection_names(c)
    assert not extra.exists()
    assert not (paths.data_dir / "rules-state.json").exists()
    # nothing was deleted: the replaced settings were moved aside
    replaced = Path(out["replaced_folder"])
    assert replaced.parent == paths.data_dir / "backups"
    assert (replaced / "config" / "rules" / "99-after.yaml").is_file()
    assert (replaced / "rules-state.json").read_text(encoding="utf-8") == '{"offer": false}'
    # the safety backup restores the later state again
    r = post(c, f"/api/backups/{safety['name']}/restore", {"backup_current": False})
    assert r.status_code == 200, r.text
    assert r.json()["safety_backup"] is None
    assert "After backup" in collection_names(c)
    assert extra.is_file()


def _rezip(source: Path, target: Path, change) -> None:
    """Copy backup ``source`` to ``target``, passing each (name, data) through ``change``."""
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "x") as dst:
        for name in src.namelist():
            for item in change(name, src.read(name)):
                dst.writestr(*item)


def test_a_backup_from_an_older_revision_is_migrated_on_restore(served, tmp_path):
    host, c, paths = served
    name = post(c, "/api/backups").json()["name"]
    old_db = tmp_path / "old.sqlite"
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    engine = make_engine(old_db)
    with write_tx(engine) as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0033")
    engine.dispose()
    older = "dam-backup-20200101-000000.zip"

    def to_old(member, data):
        if member == "dam.sqlite":
            data = old_db.read_bytes()
        if member == "manifest.json":
            manifest = json.loads(data)
            manifest["revision"] = "0033"
            data = json.dumps(manifest).encode("utf-8")
        yield member, data

    _rezip(paths.data_dir / "backups" / name, paths.data_dir / "backups" / older, to_old)
    info = {b["name"]: b for b in c.get("/api/backups").json()["backups"]}[older]
    assert info["revision"] == "0033" and info["problem"] is None
    r = post(c, f"/api/backups/{older}/restore", {"backup_current": False})
    assert r.status_code == 200, r.text
    assert backups.db_revision(paths.db_path) == backups.head_revision()
    assert host.current.app is not None and collection_names(c) == []


def test_a_backup_from_an_unknown_revision_is_refused_before_anything_changes(served):
    host, c, paths = served
    name = post(c, "/api/backups").json()["name"]
    newer = "dam-backup-20990101-000000.zip"

    def to_new(member, data):
        if member == "manifest.json":
            manifest = json.loads(data)
            manifest["revision"] = "9999_future"
            data = json.dumps(manifest).encode("utf-8")
        yield member, data

    _rezip(paths.data_dir / "backups" / name, paths.data_dir / "backups" / newer, to_new)
    info = {b["name"]: b for b in c.get("/api/backups").json()["backups"]}[newer]
    assert "newer or different version" in info["problem"]
    app = host.current.app
    r = post(c, f"/api/backups/{newer}/restore", {"backup_current": True})
    assert r.status_code == 409
    assert host.current.app is app  # never closed
    assert not any("before-restore" in p.name for p in (paths.data_dir / "backups").iterdir())


@pytest.mark.parametrize("bad", ["../escape.txt", "/abs.txt", "logs/dam.log", "config/../x"])
def test_unsafe_or_unexpected_entries_are_refused(served, bad):
    host, c, paths = served
    name = post(c, "/api/backups").json()["name"]
    evil = "dam-backup-20200202-000000.zip"

    def add_bad(member, data):
        yield member, data
        if member == "manifest.json":
            yield bad, b"x"

    _rezip(paths.data_dir / "backups" / name, paths.data_dir / "backups" / evil, add_bad)
    app = host.current.app
    r = post(c, f"/api/backups/{evil}/restore", {"backup_current": False})
    assert r.status_code in (400, 409), r.text
    assert host.current.app is app
    assert not (paths.data_dir.parent / "escape.txt").exists()


def test_a_damaged_database_is_refused(served):
    host, c, paths = served
    name = post(c, "/api/backups").json()["name"]
    broken = "dam-backup-20200303-000000.zip"

    def damage(member, data):
        yield member, (b"not a database" * 100 if member == "dam.sqlite" else data)

    _rezip(paths.data_dir / "backups" / name, paths.data_dir / "backups" / broken, damage)
    r = post(c, f"/api/backups/{broken}/restore", {"backup_current": False})
    assert r.status_code == 400, r.text


def test_a_backup_of_another_archive_folder_is_refused(served, tmp_path):
    host, c, paths = served
    name = post(c, "/api/backups").json()["name"]
    other = "dam-backup-20200404-000000.zip"

    def elsewhere(member, data):
        if member == "manifest.json":
            manifest = json.loads(data)
            manifest["archive_root"] = str(tmp_path / "other")
            data = json.dumps(manifest).encode("utf-8")
        yield member, data

    _rezip(paths.data_dir / "backups" / name, paths.data_dir / "backups" / other, elsewhere)
    r = post(c, f"/api/backups/{other}/restore", {"backup_current": False})
    assert r.status_code == 409 and "another archive folder" in r.json()["error"]


def test_names_are_never_paths(served):
    _, c, _ = served
    r = post(c, "/api/backups/..%2Fdam.sqlite/restore", {"backup_current": False})
    assert r.status_code in (400, 404)
    r = post(c, "/api/backups/dam-backup-20200101-000000.zip/restore", {"backup_current": False})
    assert r.status_code == 404


def test_restore_is_refused_without_a_host_or_with_an_interrupted_operation(tmp_path):
    paths = AppPaths(tmp_path / "data")
    paths.ensure()
    sqlite3.connect(paths.db_path).close()
    alone = BackupService(paths, None)
    with pytest.raises(Conflict, match="cannot restore"):
        alone.restore("dam-backup-20200101-000000.zip", backup_current=False)

    class Reopen:
        def reopen(self, change):
            return change()

    interrupted = BackupService(paths, None, Reopen(), pending=lambda: True)
    with pytest.raises(Conflict, match="dam recover"):
        interrupted.restore("dam-backup-20200101-000000.zip", backup_current=False)
