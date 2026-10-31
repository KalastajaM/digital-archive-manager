"""Renaming the special folders (Inbox, Ongoing, Important, To Delete) in Settings: the
preview, the journaled rename through the operation layer, everything that follows the
name (settings, rules, stored paths, the publisher's links), undo, the refusals and an
interruption half way. All on temporary fake archives."""

import json
import os
import shutil

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from typer.testing import CliRunner

import archive_guard
import dam.serve as serve_mod
from conftest import FakeArchive
from dam import special_folders
from dam.config import DEFAULTS_DIR, SpecialFolders, load_settings
from dam.core.fs import readlink
from dam.db.engine import make_engine
from dam.db.tables import collections as collections_table
from dam.db.tables import ongoing_entries, operations, special_folder_renames
from dam.errors import Conflict
from dam.ops.executor import Executor
from dam.ops.model import GuardError, OpKind
from dam.profiles import ProfileStore, ServeLock
from dam.serve import Host, Switchboard

PORT = 8797
BASE = f"http://127.0.0.1:{PORT}"
ORIGIN = {"Origin": BASE}
DEFAULT = SpecialFolders().model_dump()
NEW_NAMES = {
    "inbox": "00. Inbox",
    "ongoing": "Projects",
    "important": "##. Keep",
    "quarantine": "99. Bin",
}


def post(c, url, body=None):
    return c.post(url, json=body if body is not None else {}, headers=ORIGIN)


def rename(c, key, name, dry_run=False):
    return post(c, f"/api/special-folders/{key}/rename", {"name": name, "dry_run": dry_run})


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
def block_settings(app_paths, fake_archive):
    """settings.yaml as a user has it: the shipped file (special_folders spelled out, with
    comments) plus the archive folder."""
    text = (DEFAULTS_DIR / "settings.yaml").read_text(encoding="utf-8")
    text += f"archive_root: {json.dumps(str(fake_archive.root))}\n"  # a Windows path needs escapes
    (app_paths.config_dir / "settings.yaml").write_text(text, encoding="utf-8")
    return text


@pytest.fixture
def extra(tmp_path, block_settings, app_paths):
    """A second archive folder ("Old years") on another fake disk, in the settings file."""
    folder = FakeArchive(tmp_path / "disk" / "Archive 2000-2015")
    with open(app_paths.config_dir / "settings.yaml", "a", encoding="utf-8") as f:
        f.write(f"extra_folders:\n  - label: Old years\n    path: {json.dumps(str(folder.root))}\n")
    return folder


@pytest.fixture
def served(app_paths, events, block_settings):
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


def settings_text(app_paths) -> str:
    return (app_paths.config_dir / "settings.yaml").read_text(encoding="utf-8")


def names_on_disk(root) -> set[str]:
    return {p.name for p in root.iterdir()}


def batch_of(app, batch_id):
    with app.engine.connect() as conn:
        return conn.execute(
            select(operations).where(operations.c.batch_id == batch_id).order_by(operations.c.seq)
        ).all()


# -- the preview -----------------------------------------------------------------------


def test_the_preview_lists_every_place_and_changes_nothing(served, app_paths, fake_archive):
    host, c = served
    fake_archive.add("##. Organize/To pay/bill.pdf", drive_id="b1")
    host.current.app.scan()
    before = settings_text(app_paths)
    r = rename(c, "inbox", "00. Inbox", dry_run=True)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["key"], body["title"], body["old"], body["new"]) == (
        "inbox",
        "Inbox",
        "##. Organize",
        "00. Inbox",
    )
    assert body["batch_id"] is None and body["google_drive"] is False
    places = {p["place"]: p for p in body["places"]}
    assert set(places) >= {
        "Folder on disk",
        "Index",
        "config/settings.yaml",
        "Rules",
        "Filing codes",
        "Ongoing and Important: records",
        "Ongoing and Important: shortcuts",
        "Collections, trays, tags, notes, locks",
        "Earlier entries in Activity",
        "Scanner, watcher, publishers",
    }
    assert places["Folder on disk"]["how"] == "renamed"
    assert places["Index"]["how"] == "renamed" and "3 file and folder paths" in (
        places["Index"]["what"]
    )
    assert places["config/settings.yaml"]["how"] == "renamed"
    assert places["Rules"]["how"] == "renamed"  # the shipped examples use folder_is
    assert places["Filing codes"]["how"] == "unchanged"
    assert places["Collections, trays, tags, notes, locks"]["how"] == "unchanged"
    assert places["Earlier entries in Activity"]["how"] == "unchanged"
    assert places["Scanner, watcher, publishers"]["how"] == "rebuilt"
    assert "Undo in Activity" in body["undo"]
    # nothing moved, nothing written, nothing journaled
    assert settings_text(app_paths) == before
    assert (fake_archive.root / "##. Organize").is_dir()
    assert not (fake_archive.root / "00. Inbox").exists()
    assert host.current.app.activity.recent() == []


def test_the_preview_warns_for_google_drive(app_paths, fake_archive, tmp_path):
    drive = tmp_path / "Library" / "CloudStorage" / "GoogleDrive-me@example.com" / "My Drive"
    assert special_folders.on_google_drive(drive)
    assert not special_folders.on_google_drive(tmp_path / "Documents" / "Archive")
    assert special_folders.on_google_drive(tmp_path / "Google Drive" / "Archive")


# -- renaming each of the four, and undo -------------------------------------------------


@pytest.mark.parametrize("key", special_folders.KEYS)
def test_rename_and_undo_each_special_folder(
    key, extra, served, app_paths, fake_archive, events
):
    host, c = served
    old = DEFAULT[key]
    new = NEW_NAMES[key]
    fake_archive.add(f"{old}/a.pdf", drive_id="f1")
    fake_archive.add("10. Financial/Banks/b.pdf", drive_id="f2")
    host.current.app.scan()
    original = settings_text(app_paths)
    first = host.current.app

    r = rename(c, key, new)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["batch_id"] and body["new"] == new

    # the folder moved on its disk(s); the old name is gone
    assert (fake_archive.root / new / "a.pdf").is_file()
    assert new in names_on_disk(fake_archive.root) and old not in names_on_disk(fake_archive.root)
    if key == "quarantine":
        assert new in names_on_disk(extra.root) and old not in names_on_disk(
            extra.root
        )
    # the settings follow, the old file is kept as a backup copy
    assert getattr(load_settings(app_paths).special_folders, key) == new
    backups = sorted(app_paths.config_dir.glob("settings.yaml.bak-*"))
    assert backups and backups[0].read_text(encoding="utf-8") == original
    # the archive was opened again and knows the new name
    app = host.current.app
    assert app is not first
    assert getattr(app.paths.settings.special_folders, key) == new
    # the index follows the folder
    assert app.repo.get("f1").path == f"{new}/a.pdf"
    # one journaled batch of renames, undoable from Activity
    rows = batch_of(app, body["batch_id"])
    assert [r.kind for r in rows] == [OpKind.RENAME] * (2 if key == "quarantine" else 1)
    assert all(r.state == "done" for r in rows)
    assert rows[0].src == old and rows[0].dst == new
    summary = app.activity.get(body["batch_id"])
    assert summary.undoable
    assert summary.label == f"Renamed the {body['title']} folder from {old} to {new}"
    assert archive_guard.state.violations == []

    u = post(c, f"/api/activity/{body['batch_id']}/undo")
    assert u.status_code == 200, u.text
    assert old in names_on_disk(fake_archive.root) and new not in names_on_disk(fake_archive.root)
    if key == "quarantine":
        assert old in names_on_disk(extra.root)
    assert settings_text(app_paths) == original  # byte for byte, comments included
    app = host.current.app
    assert getattr(app.paths.settings.special_folders, key) == old
    assert app.repo.get("f1").path == f"{old}/a.pdf"
    assert app.activity.get(body["batch_id"]).undone
    with app.engine.connect() as conn:
        state = conn.execute(select(special_folder_renames.c.state)).scalar_one()
    assert state == "undone"
    assert archive_guard.state.violations == []


def test_the_name_with_the_default_settings_file_without_a_block(
    served, app_paths, fake_archive
):
    """A settings.yaml that never spelled special_folders out gets the whole entry."""
    host, c = served
    (app_paths.config_dir / "settings.yaml").write_text(
        yaml.safe_dump({"archive_root": str(fake_archive.root)}), encoding="utf-8"
    )
    r = rename(c, "inbox", "00. Inbox")
    assert r.status_code == 200, r.text
    names = load_settings(app_paths).special_folders.model_dump()
    assert names == {**DEFAULT, "inbox": "00. Inbox"}
    u = post(c, f"/api/activity/{r.json()['batch_id']}/undo")
    assert u.status_code == 200, u.text
    assert load_settings(app_paths).special_folders.model_dump() == DEFAULT


def test_a_change_of_letter_case_alone_is_a_rename(served, app_paths, fake_archive):
    host, c = served
    r = rename(c, "inbox", "##. organize")
    assert r.status_code == 200, r.text
    assert load_settings(app_paths).special_folders.inbox == "##. organize"
    assert "##. organize" in names_on_disk(fake_archive.root)


def test_inbox_files_still_show_in_the_inbox_after_the_rename(served, fake_archive):
    host, c = served
    fake_archive.add("##. Organize/To pay/bill.pdf", drive_id="b1")
    fake_archive.add("##. Organize/note.pdf", drive_id="b2")
    host.current.app.scan()
    listed = {e["record"]["path"] for e in c.get("/api/inbox").json()}
    assert listed == {"##. Organize/To pay/bill.pdf", "##. Organize/note.pdf"}
    assert rename(c, "inbox", "00. Inbox").status_code == 200
    app = host.current.app
    app.scan()  # what the reopened app does when it starts
    assert app.repo.get("b2").path == "00. Inbox/note.pdf"
    assert app.repo.get("b1").path == "00. Inbox/To pay/bill.pdf"
    assert app.repo.inbox_code_of("00. Inbox/To pay/bill.pdf") == "P"  # the code folder follows
    listed = {e["record"]["path"] for e in c.get("/api/inbox").json()}
    assert listed == {"00. Inbox/To pay/bill.pdf", "00. Inbox/note.pdf"}


# -- what stores the name -----------------------------------------------------------------


def test_rules_protected_paths_and_exclude_folders_follow_and_come_back(
    served, app_paths, fake_archive
):
    host, c = served
    rules = app_paths.config_dir / "rules" / "zz-mine.yaml"
    rules.write_text(
        "# my rule\n"
        "- id: mine\n"
        "  when: {folder_is: '##. Important', text_contains: [x]}\n"
        "  then: {folder: '##. Important/Passports', name: x}\n"
        "- id: templated\n"
        "  when: {text_contains: [y]}\n"
        "  then: {folder: '{year}/##. Important'}\n",
        encoding="utf-8",
    )
    settings = app_paths.config_dir / "settings.yaml"
    settings.write_text(
        settings.read_text(encoding="utf-8")
        + 'ai:\n  exclude_folders: ["##. Important/Medical", "70. Work"]\n',
        encoding="utf-8",
    )
    rules_before = rules.read_text(encoding="utf-8")
    examples = app_paths.config_dir / "rules" / "00-examples.yaml"
    examples_before = examples.read_text(encoding="utf-8")
    original = settings_text(app_paths)

    preview = rename(c, "important", "##. Keep", dry_run=True).json()
    places = {p["place"]: p for p in preview["places"]}
    assert places["Rules"]["how"] == "renamed" and "zz-mine.yaml" in places["Rules"]["what"]
    assert "protected or excluded folders" in places["config/settings.yaml"]["what"]

    r = rename(c, "important", "##. Keep")
    assert r.status_code == 200, r.text
    text = rules.read_text(encoding="utf-8")
    assert "# my rule" in text  # comments stay
    assert "folder_is: '##. Keep'" in text and "folder: '##. Keep/Passports'" in text
    assert "{year}/##. Important" in text  # a template whose first part is a placeholder
    assert examples.read_text(encoding="utf-8") == examples_before  # no folder starts there
    loaded = load_settings(app_paths)
    assert loaded.protected_paths == ["##. Keep"]
    assert loaded.ai.exclude_folders == ["##. Keep/Medical", "70. Work"]
    assert host.current.app.paths.is_protected("##. Keep/anything")

    assert post(c, f"/api/activity/{r.json()['batch_id']}/undo").status_code == 200
    assert rules.read_text(encoding="utf-8") == rules_before
    assert settings_text(app_paths) == original
    assert load_settings(app_paths).protected_paths == ["##. Important"]


def test_the_inbox_rules_of_the_shipped_examples_follow_the_inbox(served, app_paths):
    host, c = served
    examples = app_paths.config_dir / "rules" / "00-examples.yaml"
    before = examples.read_text(encoding="utf-8")
    assert "folder_is: \"##. Organize\"" in before
    r = rename(c, "inbox", "00. Inbox")
    assert r.status_code == 200, r.text
    after = examples.read_text(encoding="utf-8")
    assert after == before.replace('folder_is: "##. Organize"', 'folder_is: "00. Inbox"')
    assert host.current.app.rules  # the reopened app loaded them
    assert post(c, f"/api/activity/{r.json()['batch_id']}/undo").status_code == 200
    assert examples.read_text(encoding="utf-8") == before


def test_filing_code_folders_follow_and_inbox_folder_names_stay(served, app_paths):
    host, c = served
    codes = app_paths.filing_codes_path
    codes.write_text(
        "- code: P\n  label: To pay\n  inbox_folder: To pay\n"
        "- code: Q\n  label: Passports\n  folder: '##. Important/Passports'\n",
        encoding="utf-8",
    )
    before = codes.read_text(encoding="utf-8")
    places = {p["place"]: p for p in rename(c, "inbox", "00. Inbox", dry_run=True).json()["places"]}
    assert places["Filing codes"]["how"] == "unchanged"
    assert "stored inside the Inbox by name only" in places["Filing codes"]["what"]
    r = rename(c, "important", "##. Keep")
    assert r.status_code == 200, r.text
    after = codes.read_text(encoding="utf-8")
    assert "inbox_folder: To pay" in after and "folder: '##. Keep/Passports'" in after
    r2 = rename(c, "inbox", "00. Inbox")  # the inbox_folder (relative) is not touched
    assert r2.status_code == 200
    assert "inbox_folder: To pay" in codes.read_text(encoding="utf-8")
    post(c, f"/api/activity/{r2.json()['batch_id']}/undo")
    post(c, f"/api/activity/{r.json()['batch_id']}/undo")
    assert codes.read_text(encoding="utf-8") == before


def test_ignored_maintenance_results_follow(served, app_paths):
    from dam.db.engine import write_tx
    from dam.db.tables import maintenance_ignored

    host, c = served
    with write_tx(host.current.app.engine) as conn:
        conn.execute(
            maintenance_ignored.insert().values(
                kind="bad-name", key="##. Organize/odd.pdf", label="odd.pdf", created=1.0
            )
        )
    r = rename(c, "inbox", "00. Inbox")
    assert r.status_code == 200, r.text
    with host.current.app.engine.connect() as conn:
        assert conn.execute(select(maintenance_ignored.c.key)).scalar_one() == "00. Inbox/odd.pdf"
    post(c, f"/api/activity/{r.json()['batch_id']}/undo")
    with host.current.app.engine.connect() as conn:
        key = conn.execute(select(maintenance_ignored.c.key)).scalar_one()
    assert key == "##. Organize/odd.pdf"


# -- the shortcuts dam manages ------------------------------------------------------------


def _link_ok(fake_archive, rel, target_rel):
    link = fake_archive.root / rel
    return link.is_symlink() and (link.exists()) and readlink(link) == str(
        fake_archive.root.resolve() / target_rel
    )


def _sync(app):
    app.scan()
    app.sync_publishers()
    app.scan()


def _publish(app, fake_archive):
    fake_archive.add("##. Organize/inbox.pdf", drive_id="in1")
    fake_archive.add("10. Financial/Banks/bank.pdf", drive_id="bk1")
    app.scan()
    sauna = app.collections.create("Sauna")
    app.collections.add_members(sauna.id, ["in1", "bk1"])
    app.marks.mark_important(["bk1"])
    _sync(app)


def _entries(app):
    with app.engine.connect() as conn:
        return sorted(
            (r.rel, r.link_value) for r in conn.execute(select(ongoing_entries)).all()
        )


def test_ongoing_links_into_the_renamed_inbox_are_rebuilt_and_valid_after_undo(
    served, fake_archive
):
    host, c = served
    _publish(host.current.app, fake_archive)
    assert _link_ok(fake_archive, "##. Ongoing/Sauna/inbox.pdf", "##. Organize/inbox.pdf")
    places = {
        p["place"]: p for p in rename(c, "inbox", "00. Inbox", dry_run=True).json()["places"]
    }
    assert places["Ongoing and Important: shortcuts"]["how"] == "rebuilt"
    assert places["Ongoing and Important: records"]["how"] == "unchanged"

    r = rename(c, "inbox", "00. Inbox")
    assert r.status_code == 200, r.text
    app = host.current.app
    _sync(app)  # what the reopened app does when it starts
    assert _link_ok(fake_archive, "##. Ongoing/Sauna/inbox.pdf", "00. Inbox/inbox.pdf")
    assert _link_ok(fake_archive, "##. Ongoing/Sauna/bank.pdf", "10. Financial/Banks/bank.pdf")
    assert _link_ok(fake_archive, "##. Important/bank.pdf", "10. Financial/Banks/bank.pdf")
    assert sorted(os.listdir(fake_archive.root / "##. Ongoing" / "Sauna")) == [
        "bank.pdf",
        "inbox.pdf",
    ]  # nothing was published twice as _2

    assert post(c, f"/api/activity/{r.json()['batch_id']}/undo").status_code == 200
    app = host.current.app
    _sync(app)
    assert _link_ok(fake_archive, "##. Ongoing/Sauna/inbox.pdf", "##. Organize/inbox.pdf")
    assert sorted(os.listdir(fake_archive.root / "##. Ongoing" / "Sauna")) == [
        "bank.pdf",
        "inbox.pdf",
    ]


@pytest.mark.parametrize("key", ["ongoing", "important"])
def test_publisher_records_and_links_survive_renaming_ongoing_or_important(
    key, served, fake_archive
):
    host, c = served
    _publish(host.current.app, fake_archive)
    old, new = DEFAULT[key], NEW_NAMES[key]
    entries_before = _entries(host.current.app)
    assert any(rel.startswith(old + "/") for rel, _ in entries_before)

    preview = rename(c, key, new, dry_run=True).json()
    records = next(p for p in preview["places"] if p["place"].endswith("records"))
    assert records["how"] == "renamed"

    r = rename(c, key, new)
    assert r.status_code == 200, r.text
    app = host.current.app
    # the records moved with the folder; the links inside keep their (absolute) targets
    renamed = _entries(app)
    assert renamed == sorted(
        (new + rel[len(old) :] if rel.startswith(old + "/") else rel, value)
        for rel, value in entries_before
    )
    before_sync = sorted(os.listdir(fake_archive.root / new))
    batches_before = len(app.activity.recent(500))
    _sync(app)
    # the sync finds everything in place: no link is made again, nothing gets a _2
    assert sorted(os.listdir(fake_archive.root / new)) == before_sync
    assert len(app.activity.recent(500)) == batches_before
    with app.engine.connect() as conn:
        rels = conn.execute(select(collections_table.c.ongoing_rel)).scalars().all()
    assert all(not (rel or "").startswith(old + "/") and rel != old for rel in rels)
    for rel, _value in renamed:
        link = fake_archive.root / rel
        if link.is_symlink():
            assert link.exists()  # still points at a real file

    assert post(c, f"/api/activity/{r.json()['batch_id']}/undo").status_code == 200
    app = host.current.app
    _sync(app)
    assert _entries(app) == entries_before
    assert sorted(os.listdir(fake_archive.root / old)) == before_sync
    for rel, _ in entries_before:
        link = fake_archive.root / rel
        if link.is_symlink():
            assert link.exists()


def test_other_shortcuts_into_the_folder_are_named_in_a_warning(served, fake_archive):
    host, c = served
    fake_archive.add("##. Organize/doc.pdf", drive_id="d1")
    fake_archive.link("10. Financial/Banks/doc-link.pdf", "##. Organize/doc.pdf")
    host.current.app.scan()
    body = rename(c, "inbox", "00. Inbox", dry_run=True).json()
    assert any("1 shortcut elsewhere" in w for w in body["warnings"])


# -- refusals -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("", "Enter a folder name."),
        ("a/b", "A folder name cannot contain / or \\ . Make one folder at a time."),
        (".hidden", "A folder name cannot start with a dot (it would be hidden)."),
        ("CON", "'CON' is a reserved name on Windows. Choose another."),
        ("##. Organize", "That is already the name of the Inbox folder."),
        (
            "##. ongoing",
            "'##. ongoing' is already the name of the Ongoing folder. Choose another name.",
        ),
        ("10. Financial", None),  # exists on disk
    ],
)
def test_names_that_are_refused(name, message, served):
    _, c = served
    r = rename(c, "inbox", name, dry_run=True)
    assert r.status_code == 400, r.text
    if message is not None:
        assert r.json()["error"] == message
    else:
        assert "There is already a folder or file named '10. Financial'" in r.json()["error"]


def test_a_name_like_an_extra_folder_label_is_refused(extra, served):
    host, c = served
    r = rename(c, "inbox", "old YEARS", dry_run=True)
    assert r.status_code == 400 and "is the name of an archive folder" in r.json()["error"]


def test_unknown_key_and_no_server(served, client_without_host):
    _, c = served
    assert rename(c, "bogus", "X", dry_run=True).status_code == 404
    r = rename(client_without_host, "inbox", "00. Inbox")
    assert r.status_code == 409 and "dam serve" in r.json()["error"]
    # the preview works without a server, applying needs one; nothing changed
    assert rename(client_without_host, "inbox", "00. Inbox", dry_run=True).status_code == 200


@pytest.fixture
def client_without_host(served):
    """The API of the running app on its own, as the tests of the other settings use it."""
    from dam.api import create_api

    host, _ = served
    with TestClient(create_api(host.current.app), base_url=BASE) as c:
        yield c


def test_refused_while_a_job_runs(served, monkeypatch, fake_archive, app_paths):
    host, c = served
    before = settings_text(app_paths)
    monkeypatch.setattr(host.current.app.copy_jobs, "running", lambda: True)
    for dry_run in (True, False):
        r = rename(c, "inbox", "00. Inbox", dry_run=dry_run)
        assert r.status_code == 409, r.text
    assert settings_text(app_paths) == before
    assert (fake_archive.root / "##. Organize").is_dir()


def test_refused_while_a_batch_runs(served, monkeypatch):
    host, c = served
    monkeypatch.setattr(host.current.app.executor.batches, "running", lambda *a: True)
    assert rename(c, "inbox", "00. Inbox").status_code == 409


def test_refused_when_the_disk_is_away(served, fake_archive, monkeypatch):
    host, c = served
    monkeypatch.setattr(
        type(host.current.app.paths), "is_connected", lambda self, label, cached=False: False
    )
    r = rename(c, "inbox", "00. Inbox", dry_run=True)
    assert r.status_code == 409 and "is not connected" in r.json()["error"]


def test_to_delete_needs_every_extra_folder_connected_and_attached(extra, served):
    host, c = served
    host.current.app.scan()
    # detached: its To Delete would keep the old name
    assert post(c, "/api/archive-folders/Old years/detach", {}).status_code == 200
    r = rename(c, "quarantine", "99. Bin", dry_run=True)
    assert r.status_code == 409 and "'Old years' is detached" in r.json()["error"]
    assert post(c, "/api/archive-folders/Old years/attach", {}).status_code == 200
    # unplugged
    shutil.move(str(extra.root), str(extra.root) + "-away")
    try:
        r = rename(c, "quarantine", "99. Bin", dry_run=True)
        assert r.status_code == 409 and "is not connected" in r.json()["error"]
        # the other special folders are on the main disk only
        assert rename(c, "inbox", "00. Inbox", dry_run=True).status_code == 200
    finally:
        shutil.move(str(extra.root) + "-away", str(extra.root))


def test_refused_after_an_interrupted_operation(served):
    host, c = served
    app = host.current.app
    from dam.db.engine import write_tx

    with write_tx(app.engine) as conn:
        conn.execute(
            operations.insert().values(
                batch_id="x", seq=0, kind="move", src="a", dst="b", state="planned",
                origin="ui", created=1.0,
            )
        )
    r = rename(c, "inbox", "00. Inbox", dry_run=True)
    assert r.status_code == 409 and "Run recovery" in r.json()["error"]


def test_refused_when_the_folder_is_not_there(served, fake_archive):
    host, c = served
    shutil.rmtree(fake_archive.root / "##. Ongoing")
    r = rename(c, "ongoing", "Projects", dry_run=True)
    assert r.status_code == 400 and "is not in the archive yet" in r.json()["error"]


def test_a_locked_file_inside_refuses_the_rename(served, fake_archive):
    host, c = served
    fake_archive.add("##. Organize/passport.pdf", drive_id="p1")
    app = host.current.app
    app.scan()
    app.marks.mark_important(["p1"])
    r = rename(c, "inbox", "00. Inbox", dry_run=True)
    assert r.status_code == 400 and "locked" in r.json()["error"]
    assert (fake_archive.root / "##. Organize").is_dir()


def test_a_name_that_appears_before_the_rename_leaves_everything_as_it_was(
    served, app_paths, fake_archive
):
    host, c = served
    before = settings_text(app_paths)
    r = rename(c, "inbox", "00. Inbox", dry_run=True)
    assert r.status_code == 200
    fake_archive.add("00. Inbox/other.pdf", drive_id="o1")  # appears after the preview
    r = rename(c, "inbox", "00. Inbox")
    assert r.status_code == 400 and "There is already a folder or file named" in r.json()["error"]
    assert settings_text(app_paths) == before
    assert (fake_archive.root / "##. Organize").is_dir()


# -- undo from other places ----------------------------------------------------------------


def test_the_plain_undo_service_refuses_a_rename(served):
    host, c = served
    r = rename(c, "inbox", "00. Inbox")
    app = host.current.app
    with pytest.raises(Conflict, match="undo it from Activity in the app"):
        app.activity.undo(r.json()["batch_id"])


def test_undo_twice_is_refused(served):
    host, c = served
    batch = rename(c, "inbox", "00. Inbox").json()["batch_id"]
    assert post(c, f"/api/activity/{batch}/undo").status_code == 200
    assert post(c, f"/api/activity/{batch}/undo").status_code in (400, 409)


# -- an interruption half way ----------------------------------------------------------------


@pytest.fixture
def closed(app_paths, block_settings):
    """No running app: the pieces ``rename_folder`` and ``reconcile`` work with."""
    from dam.app import App

    App.create(app_paths.data_dir).close()  # the database exists and is migrated
    return app_paths


def _batch(app_paths):
    engine = make_engine(app_paths.db_path)
    try:
        with engine.connect() as conn:
            return conn.execute(select(special_folder_renames.c.batch_id)).scalar_one()
    finally:
        engine.dispose()


def _state(app_paths):
    engine = make_engine(app_paths.db_path)
    try:
        with engine.connect() as conn:
            return conn.execute(select(special_folder_renames.c.state)).scalars().all()
    finally:
        engine.dispose()


def test_a_crash_after_the_folder_moved_is_finished_at_the_next_start(
    closed, fake_archive, monkeypatch
):
    def crash(*args, **kwargs):
        raise OSError("power cut")

    monkeypatch.setattr(special_folders, "roll_forward", crash)
    with pytest.raises(OSError, match="power cut"):
        special_folders.rename_folder(closed, "inbox", "00. Inbox")
    monkeypatch.undo()
    # the folder moved, the settings still say the old name
    assert (fake_archive.root / "00. Inbox").is_dir()
    assert load_settings(closed).special_folders.inbox == "##. Organize"
    assert _state(closed) == ["planned"]
    assert special_folders.reconcile(closed) == 1
    assert load_settings(closed).special_folders.inbox == "00. Inbox"
    assert _state(closed) == ["done"]
    assert special_folders.reconcile(closed) == 0  # nothing left to do


def test_starting_the_app_finishes_an_interrupted_rename(closed, fake_archive, monkeypatch):
    from dam.app import App

    monkeypatch.setattr(special_folders, "roll_forward", lambda *a, **k: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        special_folders.rename_folder(closed, "important", "##. Keep")
    monkeypatch.undo()
    # opening the app alone (``dam remind``, a read-only command, which do not hold the
    # archive's lock) leaves the rename alone: it could undo a batch another process runs
    App.create(closed.data_dir).close()
    assert load_settings(closed).special_folders.important == "##. Important"
    assert _state(closed) == ["planned"]
    special_folders.reconcile(closed)  # what ``dam serve`` does before it opens the archive
    app = App.create(closed.data_dir)
    try:
        assert app.paths.important == "##. Keep"
        assert app.settings.protected_paths == ["##. Keep"]
    finally:
        app.close()


def test_a_crash_in_the_undo_after_the_folder_moved_back_is_finished(
    closed, fake_archive, monkeypatch
):
    renamed = special_folders.rename_folder(closed, "inbox", "00. Inbox")
    monkeypatch.setattr(special_folders, "roll_back", lambda *a, **k: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        special_folders.undo(closed, renamed.batch_id)
    monkeypatch.undo()
    assert (fake_archive.root / "##. Organize").is_dir()
    assert load_settings(closed).special_folders.inbox == "00. Inbox"
    assert special_folders.reconcile(closed) == 1
    assert load_settings(closed).special_folders.inbox == "##. Organize"
    assert _state(closed) == ["undone"]


def test_a_rename_that_never_moved_the_folder_is_marked_failed(closed, fake_archive):
    engine = make_engine(closed.db_path)
    try:
        with engine.begin() as conn:
            conn.execute(
                special_folder_renames.insert().values(
                    batch_id="never", key="inbox", old="##. Organize", new="00. Inbox",
                    state="planned", folders=1, created=1.0,
                )
            )
    finally:
        engine.dispose()
    assert special_folders.reconcile(closed) == 1
    assert _state(closed) == ["failed"]
    assert load_settings(closed).special_folders.inbox == "##. Organize"


def test_a_rename_that_stopped_part_way_across_disks_is_put_back(
    extra, closed, fake_archive, monkeypatch
):
    """To Delete is renamed on every disk; when a later disk fails, the earlier ones
    go back and nothing else changes."""
    from dam.ops.executor import Executor

    real = Executor._act
    calls = []

    def fail_on_the_second(self, rop, *args, **kwargs):
        calls.append(rop.src)
        if len(calls) == 2:
            raise OSError("disk unplugged")
        return real(self, rop, *args, **kwargs)

    monkeypatch.setattr(Executor, "_act", fail_on_the_second)
    with pytest.raises(Conflict, match="Nothing was changed"):
        special_folders.rename_folder(closed, "quarantine", "99. Bin")
    monkeypatch.undo()
    assert "##. To Delete" in names_on_disk(fake_archive.root)
    assert "##. To Delete" in names_on_disk(extra.root)
    assert load_settings(closed).special_folders.quarantine == "##. To Delete"
    assert _state(closed) == ["failed"]


# -- the review's findings ----------------------------------------------------------------------


def _locked_once(monkeypatch):
    """The journal cannot record the first op as finished ("database is locked"): the folder
    has moved, the row stays ``planned``."""
    real = Executor._journal_finish
    seen = []

    def finish(self, op_id, state, *args, **kwargs):
        if state == "done" and not seen:
            seen.append(op_id)
            raise OperationalError("UPDATE", {}, Exception("database is locked"))
        return real(self, op_id, state, *args, **kwargs)

    monkeypatch.setattr(Executor, "_journal_finish", finish)


def _recover(app_paths):
    from dam.app import App

    app = App.create(app_paths.data_dir)
    try:
        app.activity.recover()
    finally:
        app.close()


def test_a_moved_folder_is_never_recorded_as_failed(closed, fake_archive, monkeypatch):
    """B1: the folder moved but its journal row could not be finished. The rename is not
    marked failed; after Run recovery the next start finishes it, and Undo works."""
    _locked_once(monkeypatch)
    with pytest.raises(Conflict) as e:
        special_folders.rename_folder(closed, "inbox", "00. Inbox")
    assert "Run recovery" in str(e.value) and "Nothing was changed" not in str(e.value)
    monkeypatch.undo()
    assert (fake_archive.root / "00. Inbox").is_dir()
    assert _state(closed) == ["planned"]  # not "failed"
    assert special_folders.reconcile(closed) == 0  # the journal row waits for recovery
    _recover(closed)
    assert special_folders.reconcile(closed) == 1
    assert load_settings(closed).special_folders.inbox == "00. Inbox"
    assert _state(closed) == ["done"]
    batch = _batch(closed)
    special_folders.undo(closed, batch)
    assert (fake_archive.root / "##. Organize").is_dir()
    assert load_settings(closed).special_folders.inbox == "##. Organize"


def test_recovery_in_the_app_finishes_the_rename_at_once(served, app_paths, monkeypatch):
    """S4: Run recovery reopens the archive, which finishes the rename without a restart."""
    host, c = served
    _locked_once(monkeypatch)
    assert rename(c, "inbox", "00. Inbox").status_code == 409
    monkeypatch.undo()
    assert load_settings(app_paths).special_folders.inbox == "##. Organize"
    r = rename(c, "ongoing", "Projects", dry_run=True)
    assert r.status_code == 409 and "Run recovery" in r.json()["error"]
    r = post(c, "/api/recovery")
    assert r.status_code == 200, r.text
    assert load_settings(app_paths).special_folders.inbox == "00. Inbox"
    assert host.current.app.paths.inbox == "00. Inbox"
    assert rename(c, "ongoing", "Projects", dry_run=True).status_code == 200


def test_a_rename_stopped_by_an_index_error_is_taken_back_not_called_done(
    extra, closed, fake_archive, monkeypatch
):
    """S1: the index update of a folder fails: the half-renamed To Delete is put back, never
    reported as renamed with one disk still on the old name."""
    from dam.index.repo import FileRepo

    real = FileRepo.update_path
    calls = []

    def update_path(self, *args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise OperationalError("UPDATE", {}, Exception("database is locked"))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(FileRepo, "update_path", update_path)
    with pytest.raises(Conflict, match="Nothing was changed"):
        special_folders.rename_folder(closed, "quarantine", "99. Bin")
    monkeypatch.undo()
    assert "##. To Delete" in names_on_disk(fake_archive.root)
    assert "##. To Delete" in names_on_disk(extra.root)
    assert load_settings(closed).special_folders.quarantine == "##. To Delete"
    assert _state(closed) == ["failed"]


def _second_disk_fails(monkeypatch):
    real = Executor._act
    calls = []

    def act(self, rop, *args, **kwargs):
        calls.append(rop.src)
        if len(calls) == 2:
            raise OSError("disk unplugged")
        return real(self, rop, *args, **kwargs)

    monkeypatch.setattr(Executor, "_act", act)


def test_a_failed_take_back_is_not_swallowed(extra, closed, fake_archive, monkeypatch):
    """S2: the second disk fails and the first cannot be put back: the rename is kept as
    ``attention`` with the reason, later renames are refused with it, and Undo takes it."""
    _second_disk_fails(monkeypatch)

    def refuse(self, batch_id):
        raise GuardError("the origin is occupied")

    monkeypatch.setattr(Executor, "undo", refuse)
    with pytest.raises(Conflict, match="could not be taken back"):
        special_folders.rename_folder(closed, "quarantine", "99. Bin")
    assert "99. Bin" in names_on_disk(fake_archive.root)  # the first disk is still renamed
    assert _state(closed) == ["attention"]
    monkeypatch.undo()  # also removes the failing second disk
    assert special_folders.reconcile(closed) == 1  # the next start tries again, and succeeds
    assert "##. To Delete" in names_on_disk(fake_archive.root)
    assert _state(closed) == ["failed"]


def test_an_attention_rename_blocks_later_ones_until_it_is_undone(
    extra, closed, fake_archive, monkeypatch
):
    _second_disk_fails(monkeypatch)
    real_undo = Executor.undo
    monkeypatch.setattr(Executor, "undo", lambda self, b: (_ for _ in ()).throw(GuardError("busy")))
    with pytest.raises(Conflict):
        special_folders.rename_folder(closed, "quarantine", "99. Bin")
    with pytest.raises(Conflict, match="left unfinished"):
        special_folders.rename_folder(closed, "inbox", "00. Inbox")
    monkeypatch.undo()
    batch = _batch(closed)
    assert real_undo  # the real undo is back
    special_folders.undo(closed, batch)  # Undo in Activity clears it
    assert _state(closed) == ["undone"]
    special_folders.rename_folder(closed, "inbox", "00. Inbox")


def test_a_reconcile_that_cannot_settle_does_not_block_for_ever(
    extra, closed, fake_archive, monkeypatch
):
    """S2: a take-back that fails at the next start leaves ``attention`` (Undo clears it),
    not a ``planned`` row nothing can clear."""
    _second_disk_fails(monkeypatch)
    monkeypatch.setattr(special_folders, "_back_out", lambda *a, **k: "nope")
    with pytest.raises(Conflict):
        special_folders.rename_folder(closed, "quarantine", "99. Bin")
    monkeypatch.undo()
    engine = make_engine(closed.db_path)
    try:
        with engine.begin() as conn:
            conn.execute(special_folder_renames.update().values(state="planned"))
    finally:
        engine.dispose()

    def broken(*args, **kwargs):
        raise GuardError("cannot plan the undo")

    monkeypatch.setattr(special_folders, "closed_executor", broken)
    assert special_folders.reconcile(closed) == 0
    assert _state(closed) == ["attention"]


def test_the_settings_must_be_writable_before_anything_moves(closed, fake_archive):
    import stat

    settings = closed.config_dir / "settings.yaml"
    settings.chmod(stat.S_IRUSR)
    try:
        if os.access(settings, os.W_OK):
            pytest.skip("this account can write a read-only file")
        with pytest.raises(Conflict, match="cannot be written"):
            special_folders.rename_folder(closed, "inbox", "00. Inbox")
        assert (fake_archive.root / "##. Organize").is_dir()
        assert _state(closed) == []
    finally:
        settings.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_a_settings_file_without_protected_paths_follows_a_renamed_important(
    served, app_paths, fake_archive
):
    """S5: the built-in default protected path is written out and follows the name."""
    host, c = served
    (app_paths.config_dir / "settings.yaml").write_text(
        yaml.safe_dump({"archive_root": str(fake_archive.root)}), encoding="utf-8"
    )
    preview = rename(c, "important", "##. Keep", dry_run=True).json()
    places = {p["place"]: p for p in preview["places"]}
    assert "protected_paths is written out" in places["config/settings.yaml"]["what"]
    r = rename(c, "important", "##. Keep")
    assert r.status_code == 200, r.text
    assert load_settings(app_paths).protected_paths == ["##. Keep"]
    assert host.current.app.paths.is_protected("##. Keep/x")
    assert post(c, f"/api/activity/{r.json()['batch_id']}/undo").status_code == 200
    assert load_settings(app_paths).protected_paths == ["##. Important"]


def test_a_snapshot_is_taken_first_and_a_restore_keeps_the_current_names(
    served, app_paths, fake_archive, tmp_path
):
    """S6: the rename is preceded by a snapshot, and restoring it does not bring the old
    names back against the folders that now have new ones."""
    from dam import snapshots

    host, c = served
    assert rename(c, "inbox", "00. Inbox").status_code == 200
    taken = [s for s in snapshots.list_snapshots(app_paths) if s.kind == "before-rename"]
    assert len(taken) == 1 and taken[0].name.endswith("-before-rename.zip")
    work = tmp_path / "work"
    work.mkdir()
    snapshots.stage(
        app_paths, taken[0].name, snapshots.Folders(fake_archive.root, ()), True, work
    )
    staged = yaml.safe_load((work / "config" / "settings.yaml").read_text(encoding="utf-8"))
    assert staged["special_folders"]["inbox"] == "00. Inbox"  # not the snapshot's old name


def test_undo_puts_back_only_what_the_rename_changed(served, app_paths, fake_archive):
    """M1: values that already had the new name are not touched by Undo."""
    host, c = served
    rules = app_paths.config_dir / "rules" / "zz-mine.yaml"
    rules.write_text(
        "- id: a\n  when: {folder_is: '##. Organize', text_contains: [x]}\n  then: {name: x}\n"
        "- id: b\n  when: {folder_is: '00. Inbox', text_contains: [y]}\n  then: {name: y}\n",
        encoding="utf-8",
    )
    from dam.db.engine import write_tx
    from dam.db.tables import maintenance_ignored

    with write_tx(host.current.app.engine) as conn:
        for key in ("##. Organize/a.pdf", "00. Inbox/b.pdf"):
            conn.execute(
                maintenance_ignored.insert().values(
                    kind="bad-name", key=key, label=key, created=1.0
                )
            )
    r = rename(c, "inbox", "00. Inbox")
    assert r.status_code == 200, r.text
    assert post(c, f"/api/activity/{r.json()['batch_id']}/undo").status_code == 200
    text = rules.read_text(encoding="utf-8")
    assert "folder_is: '##. Organize'" in text and "folder_is: '00. Inbox'" in text  # b stays
    with host.current.app.engine.connect() as conn:
        keys = sorted(conn.execute(select(maintenance_ignored.c.key)).scalars())
    assert keys == ["##. Organize/a.pdf", "00. Inbox/b.pdf"]


def test_a_partial_undo_is_reported_and_can_be_repeated(extra, closed, fake_archive, monkeypatch):
    """M2: only the first disk can be renamed back: it says so, keeps the settings on the new
    name, and a second Undo finishes."""
    renamed = special_folders.rename_folder(closed, "quarantine", "99. Bin")
    _second_disk_fails(monkeypatch)
    with pytest.raises(Conflict, match="Only 1 of 2 folders were renamed back"):
        special_folders.undo(closed, renamed.batch_id)
    assert load_settings(closed).special_folders.quarantine == "99. Bin"
    assert _state(closed) == ["done"]
    monkeypatch.undo()
    special_folders.undo(closed, renamed.batch_id)
    assert load_settings(closed).special_folders.quarantine == "##. To Delete"
    assert "##. To Delete" in names_on_disk(extra.root) and "##. To Delete" in names_on_disk(
        fake_archive.root
    )
    assert _state(closed) == ["undone"]


def test_windows_line_endings_survive_a_rename_and_its_undo(closed, fake_archive):
    """M3: a CRLF file stays CRLF, and Undo gives it back byte for byte."""
    settings = closed.config_dir / "settings.yaml"
    rules = closed.config_dir / "rules" / "zz-crlf.yaml"
    rules.write_bytes(
        b"- id: a\r\n  when: {folder_is: '##. Organize', text_contains: [x]}\r\n"
        b"  then: {name: x}\r\n"
    )
    settings.write_bytes(settings.read_bytes().replace(b"\n", b"\r\n"))
    before = {p: p.read_bytes() for p in (settings, rules)}
    renamed = special_folders.rename_folder(closed, "inbox", "00. Inbox")
    for p in (settings, rules):
        data = p.read_bytes()
        assert b"00. Inbox" in data and b"\n" not in data.replace(b"\r\n", b"")
    special_folders.undo(closed, renamed.batch_id)
    assert {p: p.read_bytes() for p in (settings, rules)} == before


def test_to_delete_can_be_renamed_when_only_an_extra_folder_has_one(
    extra, closed, fake_archive
):
    """M4."""
    shutil.rmtree(fake_archive.root / "##. To Delete")
    special_folders.rename_folder(closed, "quarantine", "99. Bin")
    assert "99. Bin" in names_on_disk(extra.root)
    assert "99. Bin" not in names_on_disk(fake_archive.root)
    assert load_settings(closed).special_folders.quarantine == "99. Bin"


def test_a_settings_file_with_a_windows_path_is_edited_safely(app_paths):
    """A Windows path in double quotes (backslashes escaped) stays what it was when the
    special_folders entry is written next to it, and the edit reads back."""
    windows = "C:\\Users\\me\\My Drive\\Archive"
    path = app_paths.config_dir / "settings.yaml"
    path.write_text(f"archive_root: {json.dumps(windows)}\nserver_port: 8765\n", encoding="utf-8")
    edits = special_folders.config_edits(app_paths, "inbox", "##. Organize", "00. Inbox", ())
    (change,) = [e for e in edits if e.path == path]
    data = yaml.safe_load(change.written)
    assert data["archive_root"] == windows
    assert data["special_folders"]["inbox"] == "00. Inbox"
    assert data["special_folders"]["ongoing"] == "##. Ongoing"
    assert data["server_port"] == 8765


# -- the second review ----------------------------------------------------------------------------


def test_dam_serve_finishes_an_interrupted_rename_before_it_opens_the_archive(
    closed, fake_archive, monkeypatch
):
    """R1: through the real ``dam serve`` command (the server itself stubbed): the rename that
    stopped after the folder moved is finished, so the app opens with the new name."""
    from dam import serve as dam_serve
    from dam.cli.main import app as cli

    monkeypatch.setattr(special_folders, "roll_forward", lambda *a, **k: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        special_folders.rename_folder(closed, "inbox", "00. Inbox")
    monkeypatch.undo()
    assert load_settings(closed).special_folders.inbox == "##. Organize"
    seen = []
    monkeypatch.setattr(
        dam_serve, "serve", lambda a, *args, **kw: seen.append(a.paths.inbox)
    )
    r = CliRunner().invoke(cli, ["--data-dir", str(closed.data_dir), "serve", "--no-open"])
    assert r.exit_code == 0, r.output
    assert seen == ["00. Inbox"]
    assert load_settings(closed).special_folders.inbox == "00. Inbox"
    assert _state(closed) == ["done"]


def test_a_reconcile_that_fails_never_stops_the_archive_opening(closed, fake_archive, monkeypatch):
    """Errors are contained: per rename (it becomes attention with the reason), and anywhere
    else (logged, nothing raised)."""
    monkeypatch.setattr(special_folders, "roll_forward", lambda *a, **k: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        special_folders.rename_folder(closed, "inbox", "00. Inbox")
    # per rename: finishing it fails again
    assert special_folders.reconcile(closed) == 0
    assert _state(closed) == ["attention"]
    # anywhere else: even looking for renames fails
    monkeypatch.setattr(special_folders, "_unfinished", lambda e: 1 / 0)
    assert special_folders.reconcile(closed) == 0


def test_undo_clears_settings_when_the_take_back_crashed_after_the_folder_moved(
    closed, fake_archive, monkeypatch
):
    """R2: the folder is back and the journal shows nothing acted, but the rule and the
    stored paths still say the new name: the next start puts them back, not 'failed'."""
    rules = closed.config_dir / "rules" / "zz-mine.yaml"
    rules.write_text(
        "- id: a\n  when: {text_contains: [x]}\n  then: {folder: '##. Important/P'}\n",
        encoding="utf-8",
    )
    before = rules.read_bytes()
    renamed = special_folders.rename_folder(closed, "important", "##. Keep")
    assert b"##. Keep/P" in rules.read_bytes()
    monkeypatch.setattr(special_folders, "roll_back", lambda *a, **k: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        special_folders.undo(closed, renamed.batch_id)
    monkeypatch.undo()
    assert (fake_archive.root / "##. Important").is_dir()
    engine = make_engine(closed.db_path)
    try:
        with engine.begin() as conn:  # the app was stopped before it could note anything
            conn.execute(special_folder_renames.update().values(state="attention"))
    finally:
        engine.dispose()
    assert special_folders.reconcile(closed) == 1
    assert rules.read_bytes() == before
    assert load_settings(closed).special_folders.important == "##. Important"
    assert _state(closed) == ["undone"]


def test_undo_finds_a_rule_by_its_id_when_rules_were_added_since(
    closed, fake_archive
):
    """M1: an edit is recorded against the rule's id, not its place in the file."""
    rules = closed.config_dir / "rules" / "zz-mine.yaml"
    rules.write_text(
        "- id: a\n  when: {text_contains: [x]}\n  then: {folder: '##. Organize/A'}\n",
        encoding="utf-8",
    )
    renamed = special_folders.rename_folder(closed, "inbox", "00. Inbox")
    assert "'00. Inbox/A'" in rules.read_text(encoding="utf-8")
    # a rule is added above it, and it already used the new name
    rules.write_text(
        "- id: z\n  when: {text_contains: [y]}\n  then: {folder: '00. Inbox/A'}\n"
        + rules.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    special_folders.undo(closed, renamed.batch_id)
    text = rules.read_text(encoding="utf-8")
    assert "- id: z\n  when: {text_contains: [y]}\n  then: {folder: '00. Inbox/A'}" in text
    assert "folder: '##. Organize/A'" in text


def _make_attention(app_paths):
    engine = make_engine(app_paths.db_path)
    try:
        with engine.begin() as conn:
            conn.execute(special_folder_renames.update().values(state="attention"))
    finally:
        engine.dispose()


def test_undo_of_a_rename_whose_folders_are_already_back_puts_the_settings_back(
    closed, fake_archive, monkeypatch
):
    """Undo in Activity, as the unfinished-rename message says, settles an ``attention``
    rename whose journal has nothing left to undo."""
    renamed = special_folders.rename_folder(closed, "inbox", "00. Inbox")
    monkeypatch.setattr(special_folders, "roll_back", lambda *a, **k: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        special_folders.undo(closed, renamed.batch_id)
    monkeypatch.undo()
    _make_attention(closed)
    assert (fake_archive.root / "##. Organize").is_dir()
    assert load_settings(closed).special_folders.inbox == "00. Inbox"
    special_folders.undo(closed, renamed.batch_id)
    assert load_settings(closed).special_folders.inbox == "##. Organize"
    assert _state(closed) == ["undone"]


def test_a_done_rename_whose_folders_were_undone_blocks_a_new_one(
    closed, fake_archive, monkeypatch
):
    renamed = special_folders.rename_folder(closed, "inbox", "00. Inbox")
    monkeypatch.setattr(special_folders, "roll_back", lambda *a, **k: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        special_folders.undo(closed, renamed.batch_id)
    monkeypatch.undo()
    assert _state(closed) == ["done"]  # folders undone, settings not yet put back
    with pytest.raises(Conflict, match="left unfinished"):
        special_folders.rename_folder(closed, "ongoing", "Projects")
    assert special_folders.reconcile(closed) == 1
    special_folders.rename_folder(closed, "ongoing", "Projects")


def test_migration_0042_makes_the_final_table(new_engine, tmp_path):
    from sqlalchemy import inspect

    from dam.db.engine import migrate

    engine = new_engine(tmp_path / "m.sqlite")
    migrate(engine)
    columns = {c["name"] for c in inspect(engine).get_columns("special_folder_renames")}
    assert columns == {
        "id", "batch_id", "key", "old", "new", "state", "folders", "changes", "note",
        "created", "finished",
    }
