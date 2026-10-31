"""Renaming an ordinary folder in Browse: the preview, the journaled rename with the archive
closed and opened again, everything that stores the folder's path (index, rules, filing
codes, settings, Maintenance), what follows by file id (collections, tray items, the
publisher's links), the refusals and Undo. All on temporary fake archives."""

import json
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import archive_guard
import dam.serve as serve_mod
from dam.config import DEFAULTS_DIR, load_settings
from dam.core.fs import readlink
from dam.db.engine import write_tx
from dam.db.tables import maintenance_ignored, operations, special_folder_renames
from dam.errors import Conflict
from dam.ops.model import OpKind
from dam.profiles import ProfileStore, ServeLock
from dam.serve import Host, Switchboard

PORT = 8798
BASE = f"http://127.0.0.1:{PORT}"
ORIGIN = {"Origin": BASE}
HOME = "20. Home"
FOLDER = f"{HOME}/2009"


def post(c, url, body=None):
    return c.post(url, json=body if body is not None else {}, headers=ORIGIN)


def rename(c, drive_id, name, dry_run=False):
    url = "/api/browse/folder-rename" + ("/preview" if dry_run else "")
    return post(c, url, {"drive_id": drive_id, "name": name})


class FakeBackground:
    def stop(self):
        pass


@pytest.fixture
def served(app_paths, fake_archive, monkeypatch):
    """The archive served by a ``Host``, as ``dam serve`` runs it, with the shipped
    settings file (comments included) and a small tree."""
    monkeypatch.setattr(serve_mod, "start_background", lambda app: FakeBackground())
    text = (DEFAULTS_DIR / "settings.yaml").read_text(encoding="utf-8")
    text += f"archive_root: {json.dumps(str(fake_archive.root))}\n"
    (app_paths.config_dir / "settings.yaml").write_text(text, encoding="utf-8")
    fake_archive.add(f"{FOLDER}/a.pdf", b"a", drive_id="id-a")
    fake_archive.add(f"{FOLDER}/sub/b.pdf", b"b", drive_id="id-b")
    fake_archive.add("80. Misc/keep.pdf", b"k", drive_id="id-k")
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
    host.current.app.scan()
    client = TestClient(host.board, base_url=BASE)
    yield host, client
    client.close()
    host.shutdown()


def fid(app, rel: str) -> str:
    rec = app.repo.by_path(rel)
    assert rec is not None and rec.is_dir, rel
    return rec.drive_id


def settings_text(app_paths) -> str:
    return (app_paths.config_dir / "settings.yaml").read_text(encoding="utf-8")


def places_of(body) -> dict:
    return {p["place"]: p for p in body["places"]}


def undo(c, batch_id):
    r = post(c, f"/api/activity/{batch_id}/undo")
    assert r.status_code == 200, r.text
    return r


# -- the rename and its undo ----------------------------------------------------------------


def test_preview_changes_nothing_and_says_what_follows(served, app_paths, fake_archive):
    host, c = served
    app = host.current.app
    folder_id = fid(app, FOLDER)
    before = settings_text(app_paths)
    r = rename(c, folder_id, "2010", dry_run=True)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["old"], body["new"], body["path"], body["new_path"]) == (
        "2009",
        "2010",
        FOLDER,
        f"{HOME}/2010",
    )
    assert body["batch_id"] is None
    places = places_of(body)
    assert places["Folder on disk"]["how"] == "renamed"
    assert "3 file and folder paths" in places["Index"]["what"]  # 2009, a.pdf, sub, b.pdf
    assert places["Rules"]["how"] == "unchanged"
    assert (fake_archive.root / FOLDER / "a.pdf").is_file()
    assert settings_text(app_paths) == before


def test_renames_the_folder_and_undo_puts_it_back(served, fake_archive):
    host, c = served
    first = host.current.app
    folder_id = fid(first, FOLDER)
    first.tags.add("id-a", ["bank"])
    r = rename(c, folder_id, "2010")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["batch_id"]
    assert (fake_archive.root / HOME / "2010" / "sub" / "b.pdf").read_bytes() == b"b"
    assert not (fake_archive.root / FOLDER).exists()
    app = host.current.app
    assert app is not first  # the archive was opened again
    assert app.repo.get(folder_id).path == f"{HOME}/2010"
    assert app.repo.get("id-b").path == f"{HOME}/2010/sub/b.pdf"
    assert app.tags.for_file("id-a") == ["bank"]
    with app.engine.connect() as conn:
        rows = conn.execute(
            select(operations).where(operations.c.batch_id == body["batch_id"])
        ).all()
    assert [(row.kind, row.src, row.dst) for row in rows] == [
        (OpKind.RENAME, FOLDER, f"{HOME}/2010")
    ]
    summary = app.activity.get(body["batch_id"])
    assert summary.undoable and summary.label == "Renamed folder 2009 to 2010"
    assert archive_guard.state.violations == []

    undo(c, body["batch_id"])
    app = host.current.app
    assert (fake_archive.root / FOLDER / "sub" / "b.pdf").is_file()
    assert not (fake_archive.root / HOME / "2010").exists()
    assert app.repo.get("id-b").path == f"{FOLDER}/sub/b.pdf"
    assert app.activity.get(body["batch_id"]).undone
    with app.engine.connect() as conn:
        assert conn.execute(select(special_folder_renames.c.state)).scalar_one() == "undone"
    assert archive_guard.state.violations == []


def test_a_top_level_folder_can_be_renamed(served, fake_archive):
    host, c = served
    r = rename(c, fid(host.current.app, HOME), "21. House")
    assert r.status_code == 200, r.text
    assert (fake_archive.root / "21. House" / "2009" / "a.pdf").is_file()
    assert host.current.app.repo.get("id-a").path == "21. House/2009/a.pdf"


def test_a_change_of_letter_case_alone_is_a_rename(served, fake_archive):
    host, c = served
    fake_archive.add(f"{HOME}/Bills/x.pdf", b"x", drive_id="id-x")
    host.current.app.scan()
    r = rename(c, fid(host.current.app, f"{HOME}/Bills"), "bills")
    assert r.status_code == 200, r.text
    assert "bills" in os.listdir(fake_archive.root / HOME)
    assert "Bills" not in os.listdir(fake_archive.root / HOME)
    assert host.current.app.repo.get("id-x").path == f"{HOME}/bills/x.pdf"
    undo(c, r.json()["batch_id"])
    assert "Bills" in os.listdir(fake_archive.root / HOME)


# -- what follows the path --------------------------------------------------------------------


def test_rules_codes_and_settings_follow_and_come_back(served, app_paths):
    host, c = served
    rules = app_paths.config_dir / "rules" / "zz-mine.yaml"
    rules.write_text(
        "# my rules\n"
        "- id: here\n"
        f"  when: {{folder_is: '{FOLDER}', text_contains: [x]}}\n"
        f"  then: {{folder: '{FOLDER}/sub', name: x}}\n"
        "- id: there\n"
        "  when: {text_contains: [y]}\n"
        f"  then: {{folder: '{FOLDER}'}}\n"
        "- id: sibling\n"
        "  when: {text_contains: [z]}\n"
        f"  then: {{folder: '{HOME}/2009-old'}}\n"  # starts with the same letters only
        "- id: templated\n"
        "  when: {text_contains: [w]}\n"
        f"  then: {{folder: '{HOME}/{{doc_date:%Y}}'}}\n",
        encoding="utf-8",
    )
    codes = app_paths.filing_codes_path
    codes.write_text(
        f"- code: H\n  label: Home 2009\n  folder: '{FOLDER}'\n"
        "- code: M\n  label: Misc\n  folder: '80. Misc'\n",
        encoding="utf-8",
    )
    settings = app_paths.config_dir / "settings.yaml"
    settings.write_text(
        settings.read_text(encoding="utf-8")
        + f'protected_paths: ["##. Important", "{FOLDER}/sub"]\n'
        + f'ai:\n  exclude_folders: ["{FOLDER}", "70. Work"]\n',
        encoding="utf-8",
    )
    rules_before = rules.read_text(encoding="utf-8")
    codes_before = codes.read_text(encoding="utf-8")
    settings_before = settings_text(app_paths)
    host.current.app.scan()
    folder_id = fid(host.current.app, FOLDER)

    places = places_of(rename(c, folder_id, "2010", dry_run=True).json())
    assert places["Rules"]["how"] == "renamed"
    assert places["Rules"]["what"].startswith("2 rules point here and will follow")
    assert "zz-mine.yaml" in places["Rules"]["what"]
    assert places["Filing codes"]["how"] == "renamed"
    assert places["Filing codes"]["what"].startswith("1 filing code points here")
    assert places["config/settings.yaml"]["how"] == "renamed"
    assert "2 protected or AI-excluded folders" in places["config/settings.yaml"]["what"]

    r = rename(c, folder_id, "2010")
    assert r.status_code == 200, r.text
    text = rules.read_text(encoding="utf-8")
    assert "# my rules" in text
    assert f"folder_is: '{HOME}/2010'" in text and f"folder: '{HOME}/2010/sub'" in text
    assert f"folder: '{HOME}/2010'}}" in text
    assert f"'{HOME}/2009-old'" in text and "{doc_date:%Y}" in text
    assert f"folder: '{HOME}/2010'" in codes.read_text(encoding="utf-8")
    loaded = load_settings(app_paths)
    assert loaded.protected_paths == ["##. Important", f"{HOME}/2010/sub"]
    assert loaded.ai.exclude_folders == [f"{HOME}/2010", "70. Work"]
    app = host.current.app
    assert {r.id: r for r in app.rules}["here"].when.folder_is == f"{HOME}/2010"

    undo(c, r.json()["batch_id"])
    assert rules.read_text(encoding="utf-8") == rules_before
    assert codes.read_text(encoding="utf-8") == codes_before
    assert settings_text(app_paths) == settings_before


def test_an_inbox_folder_of_a_filing_code_follows(served, app_paths, fake_archive):
    host, c = served
    fake_archive.add("##. Organize/To pay/bill.pdf", drive_id="id-bill")
    host.current.app.scan()
    codes = app_paths.filing_codes_path
    codes.write_text("- code: P\n  label: To pay\n  inbox_folder: To pay\n", encoding="utf-8")
    before = codes.read_text(encoding="utf-8")
    folder_id = fid(host.current.app, "##. Organize/To pay")
    places = places_of(rename(c, folder_id, "Pay soon", dry_run=True).json())
    assert places["Filing codes"]["how"] == "renamed"
    r = rename(c, folder_id, "Pay soon")
    assert r.status_code == 200, r.text
    assert "inbox_folder: Pay soon" in codes.read_text(encoding="utf-8")
    undo(c, r.json()["batch_id"])
    assert codes.read_text(encoding="utf-8") == before


def test_ignored_maintenance_results_follow(served):
    host, c = served
    with write_tx(host.current.app.engine) as conn:
        conn.execute(
            maintenance_ignored.insert().values(
                kind="bad-name", key=f"{FOLDER}/odd.pdf", label="odd.pdf", created=1.0
            )
        )
    r = rename(c, fid(host.current.app, FOLDER), "2010")
    assert r.status_code == 200, r.text
    with host.current.app.engine.connect() as conn:
        key = conn.execute(select(maintenance_ignored.c.key)).scalar_one()
    assert key == f"{HOME}/2010/odd.pdf"
    undo(c, r.json()["batch_id"])
    with host.current.app.engine.connect() as conn:
        assert conn.execute(select(maintenance_ignored.c.key)).scalar_one() == f"{FOLDER}/odd.pdf"


def _link_ok(fake_archive, rel, target_rel):
    link = fake_archive.root / rel
    return (
        link.is_symlink()
        and link.exists()
        and readlink(link) == str(fake_archive.root.resolve() / target_rel)
    )


def _sync(app):
    app.scan()
    app.sync_publishers()
    app.scan()


def test_collections_tray_items_and_their_shortcuts_follow(served, fake_archive):
    host, c = served
    app = host.current.app
    folder_id = fid(app, FOLDER)
    years = app.collections.create("Years")
    app.collections.add_members(years.id, [folder_id, "id-b"])
    app.marks.mark_important(["id-k"])
    item = app.trays.create("to-pay", ["id-a"], {}, None)
    _sync(app)
    assert _link_ok(fake_archive, "##. Ongoing/Years/b.pdf", f"{FOLDER}/sub/b.pdf")
    places = places_of(rename(c, folder_id, "2010", dry_run=True).json())
    assert places["Ongoing and Important: shortcuts"]["how"] == "rebuilt"
    assert "1 collection" in places["Collections"]["what"]
    assert "1 open tray item" in places["Tray items"]["what"]

    r = rename(c, folder_id, "2010")
    assert r.status_code == 200, r.text
    app = host.current.app
    _sync(app)
    assert [x.name for x in app.collections.for_file(folder_id)] == ["Years"]
    assert [x.name for x in app.collections.for_file("id-b")] == ["Years"]
    assert _link_ok(fake_archive, "##. Ongoing/Years/b.pdf", f"{HOME}/2010/sub/b.pdf")
    assert _link_ok(fake_archive, "##. Ongoing/Years/2010", f"{HOME}/2010")
    assert app.trays.get(item.id).files == ["id-a"]
    assert app.repo.get("id-a").path == f"{HOME}/2010/a.pdf"

    undo(c, r.json()["batch_id"])
    app = host.current.app
    _sync(app)
    assert _link_ok(fake_archive, "##. Ongoing/Years/b.pdf", f"{FOLDER}/sub/b.pdf")


def test_other_shortcuts_into_the_folder_are_named_in_a_warning(served, fake_archive):
    host, c = served
    fake_archive.link("80. Misc/a-link.pdf", f"{FOLDER}/a.pdf")
    host.current.app.scan()
    body = rename(c, fid(host.current.app, FOLDER), "2010", dry_run=True).json()
    assert any("1 shortcut elsewhere" in w for w in body["warnings"])


# -- refusals -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("", "Enter a folder name."),
        ("a/b", "A folder name cannot contain / or \\ . Make one folder at a time."),
        (".hidden", "A folder name cannot start with a dot (it would be hidden)."),
        ("CON", "'CON' is a reserved name on Windows. Choose another."),
        ("##. Mine", "Names starting with ##. are kept for the app's own folders."),
        ("2009", "That is already the folder's name."),
        ("SUB", None),  # taken, whatever its letter case
    ],
)
def test_names_that_are_refused(name, message, served, fake_archive):
    host, c = served
    fake_archive.add(f"{HOME}/Sub/c.pdf", b"c", drive_id="id-c")
    host.current.app.scan()
    r = rename(c, fid(host.current.app, FOLDER), name, dry_run=True)
    assert r.status_code == 400, r.text
    if message is not None:
        assert r.json()["error"] == message
    else:
        assert "There is already a folder or file named 'Sub'" in r.json()["error"]
    assert (fake_archive.root / FOLDER).is_dir()


@pytest.mark.parametrize(
    "rel", ["##. Organize", "##. Ongoing", "##. Important", "##. To Delete", "##. Ongoing/x"]
)
def test_the_app_folders_are_refused(rel, served, fake_archive):
    host, c = served
    fake_archive.add(f"{rel}/y.pdf", b"y", drive_id=None)
    host.current.app.scan()
    r = rename(c, fid(host.current.app, rel), "Other", dry_run=True)
    assert r.status_code == 400, r.text
    assert "keeps" in r.json()["error"]


def test_a_file_is_refused(served):
    _, c = served
    r = rename(c, "id-a", "b.pdf", dry_run=True)
    assert r.status_code == 400 and "not a folder" in r.json()["error"]


def test_an_unknown_id_is_404(served):
    _, c = served
    assert rename(c, "nope", "x", dry_run=True).status_code == 404


def test_an_important_file_inside_refuses(served, fake_archive):
    host, c = served
    app = host.current.app
    app.marks.mark_important(["id-b"])
    r = rename(c, fid(app, FOLDER), "2010", dry_run=True)
    assert r.status_code == 400 and "Important" in r.json()["error"]
    assert (fake_archive.root / FOLDER).is_dir()


def test_a_locked_file_inside_refuses(served, fake_archive):
    host, c = served
    app = host.current.app
    app.locks.lock("id-b")
    r = rename(c, fid(app, FOLDER), "2010", dry_run=True)
    assert r.status_code == 400 and "locked" in r.json()["error"]


def test_a_name_taken_after_the_preview_changes_nothing(served, app_paths, fake_archive):
    host, c = served
    folder_id = fid(host.current.app, FOLDER)
    before = settings_text(app_paths)
    assert rename(c, folder_id, "2010", dry_run=True).status_code == 200
    fake_archive.add(f"{HOME}/2010/other.pdf", b"o", drive_id="id-o")
    r = rename(c, folder_id, "2010")
    assert r.status_code == 400 and "There is already a folder or file named" in r.json()["error"]
    assert (fake_archive.root / FOLDER).is_dir()
    assert not (fake_archive.root / HOME / "2010_2").exists()  # never a silent _2
    assert settings_text(app_paths) == before


def test_refused_while_a_job_runs(served, monkeypatch, fake_archive):
    host, c = served
    folder_id = fid(host.current.app, FOLDER)
    monkeypatch.setattr(host.current.app.copy_jobs, "running", lambda: True)
    assert rename(c, folder_id, "2010").status_code == 409
    assert (fake_archive.root / FOLDER).is_dir()


def test_applying_needs_the_server(served):
    from dam.api import create_api

    host, _ = served
    folder_id = fid(host.current.app, FOLDER)
    with TestClient(create_api(host.current.app), base_url=BASE) as c:
        r = rename(c, folder_id, "2010")
        assert r.status_code == 409 and "dam serve" in r.json()["error"]
        assert rename(c, folder_id, "2010", dry_run=True).status_code == 200


def test_the_plain_undo_service_refuses_the_rename(served):
    host, c = served
    r = rename(c, fid(host.current.app, FOLDER), "2010")
    with pytest.raises(Conflict, match="undo it from Activity"):
        host.current.app.activity.undo(r.json()["batch_id"])


def test_a_crash_after_the_folder_moved_is_finished_at_the_next_start(
    app_paths, fake_archive, monkeypatch
):
    from dam import folder_rename, special_folders
    from dam.app import App

    text = (DEFAULTS_DIR / "settings.yaml").read_text(encoding="utf-8")
    text += f"archive_root: {json.dumps(str(fake_archive.root))}\n"
    (app_paths.config_dir / "settings.yaml").write_text(text, encoding="utf-8")
    rules = app_paths.config_dir / "rules" / "zz-mine.yaml"
    rules.write_text(
        f"- id: here\n  when: {{text_contains: [x]}}\n  then: {{folder: '{FOLDER}'}}\n",
        encoding="utf-8",
    )
    fake_archive.add(f"{FOLDER}/a.pdf", b"a", drive_id="id-a")
    app = App.create(app_paths.data_dir)
    app.scan()
    folder_id = fid(app, FOLDER)
    app.close()

    def crash(*args, **kwargs):
        raise OSError("power cut")

    monkeypatch.setattr(special_folders, "roll_forward", crash)
    with pytest.raises(OSError, match="power cut"):
        folder_rename.rename_folder(app_paths, folder_id, "2010")
    monkeypatch.undo()
    assert (fake_archive.root / HOME / "2010" / "a.pdf").is_file()
    assert f"'{FOLDER}'" in rules.read_text(encoding="utf-8")
    assert special_folders.reconcile(app_paths) == 1
    assert f"'{HOME}/2010'" in rules.read_text(encoding="utf-8")
    assert special_folders.reconcile(app_paths) == 0
