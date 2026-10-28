"""Renaming the special folders (Inbox, Ongoing, Important, To Delete) in Settings: the
preview, the journaled rename through the operation layer, everything that follows the
name (settings, rules, stored paths, the publisher's links), undo, the refusals and an
interruption half way. All on temporary fake archives."""

import os
import shutil

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

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
from dam.ops.model import OpKind
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
    text += f'archive_root: "{fake_archive.root}"\n'
    (app_paths.config_dir / "settings.yaml").write_text(text, encoding="utf-8")
    return text


@pytest.fixture
def extra(tmp_path, block_settings, app_paths):
    """A second archive folder ("Old years") on another fake disk, in the settings file."""
    folder = FakeArchive(tmp_path / "disk" / "Archive 2000-2015")
    with open(app_paths.config_dir / "settings.yaml", "a", encoding="utf-8") as f:
        f.write(f'extra_folders:\n  - label: "Old years"\n    path: "{folder.root}"\n')
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
