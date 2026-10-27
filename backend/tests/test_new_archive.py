"""Starting an archive from scratch: empty-folder detection, starter layouts, the preview,
creating the folders and undoing them, the special folder names in the settings, New
folder, copying files into the inbox, and the guard that automatic actions still never
create a top-level folder."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from typer.testing import CliRunner

from conftest import needs_dir_fd
from dam import layouts, setup
from dam.api import create_api
from dam.api.setup_mode import create_setup_api
from dam.app import App
from dam.cli.main import app as cli
from dam.config import AppPaths, SpecialFolders, load_settings
from dam.core.foldernames import FolderNameError, check_folder_name
from dam.db.tables import made_folders, operations
from dam.errors import InvalidRequest, TooLarge
from dam.ops.model import GuardError, Op, OpKind, Plan
from dam.ops.primitives import MAX_COPY_BYTES
from dam.rules.model import load_rules
from dam.services.inbox import FileRequest
from fsswap import recreate_dir

BASE = "http://127.0.0.1:8766"
ORIGIN = {"Origin": BASE}
runner = CliRunner()


@pytest.fixture
def blank(tmp_path):
    """An App on an empty archive folder (no special folders, no layout)."""
    archive = tmp_path / "Archive"
    archive.mkdir()
    paths = AppPaths(tmp_path / "data")
    paths.ensure()
    text = (
        (paths.config_dir / "settings.yaml")
        .read_text(encoding="utf-8")
        .replace("ops_throttle_ms: 250", "ops_throttle_ms: 0")
    )
    (paths.config_dir / "settings.yaml").write_text(
        text + f"\narchive_root: {json.dumps(str(archive))}\n", encoding="utf-8"
    )
    application = App.create(paths.data_dir)
    application.test_archive = archive
    yield application
    application.close()


def household(app, numbered=True, drop=()):
    template = next(t for t in app.layout.templates() if t.id == "household")
    rows = [(r.key, r.name) for r in template.folders if r.key not in drop]
    return app.layout.spec("household", numbered, rows)


def names(archive: Path) -> list[str]:
    return sorted(p.name for p in archive.iterdir())


# -- empty-folder detection -----------------------------------------------------------


def test_junk_does_not_make_a_folder_non_empty(tmp_path):
    f = tmp_path / "new"
    f.mkdir()
    assert setup.is_empty_folder(f)
    for junk in (".DS_Store", "Thumbs.db", "desktop.ini", "._x", "THUMBS.DB"):
        (f / junk).write_text("", encoding="utf-8")
    assert setup.is_empty_folder(f) and setup.visible_entries(f) == []
    (f / "a.pdf").write_text("", encoding="utf-8")
    assert not setup.is_empty_folder(f) and setup.visible_entries(f) == ["a.pdf"]
    assert not setup.is_empty_folder(tmp_path / "missing")
    assert not setup.is_empty_folder(f / "a.pdf")


def test_validate_reports_empty_and_item_count(tmp_path):
    paths = AppPaths(tmp_path / "d")
    paths.ensure()
    folder = tmp_path / "F"
    folder.mkdir()
    (folder / ".DS_Store").write_text("", encoding="utf-8")
    api = create_setup_api(paths, None)
    with TestClient(api, base_url=BASE) as c:
        body = c.post("/api/setup/validate", json={"path": str(folder)}, headers=ORIGIN).json()
        assert body["ok"] and body["empty"] is True and body["item_count"] == 0
        (folder / "x.txt").write_text("", encoding="utf-8")
        body = c.post("/api/setup/validate", json={"path": str(folder)}, headers=ORIGIN).json()
        assert body["empty"] is False and body["item_count"] == 1


# -- layouts as data -------------------------------------------------------------------


def test_shipped_layouts_load(tmp_path):
    templates = layouts.load_templates()
    assert [t.id for t in templates] == ["household", "minimal", "empty"]
    household_t = templates[0]
    assert [r.name for r in household_t.folders] == [
        "Finance", "Bills & Receipts", "Insurance", "Taxes", "Home", "Vehicles",
        "Health", "Education", "Work", "Personal", "Other",
    ]  # fmt: skip
    assert [r.name for r in templates[1].folders] == ["Documents", "Receipts", "Other"]
    assert templates[2].folders == ()
    # every key a rule refers to exists in its layout
    for t in templates:
        keys = {r.key for r in t.folders} | {"inbox"}
        for rule in t.rules:
            assert set(layouts._KEY_REF.findall(str(rule))) <= keys, (t.id, rule["id"])


def test_a_broken_layout_file_is_skipped_and_more_can_be_added(tmp_path):
    folder = tmp_path / "layouts"
    folder.mkdir()
    (folder / "bad.yaml").write_text("id: [not a string\n", encoding="utf-8")
    (folder / "odd.yaml").write_text("id: BAD ID\ntitle: x\n", encoding="utf-8")
    (folder / "mine.yaml").write_text(
        "id: mine\ntitle: Mine\norder: 1\nfolders:\n  - {key: a, name: Alpha}\n", encoding="utf-8"
    )
    found = layouts.load_templates(tmp_path)
    assert [t.id for t in found] == ["mine"]


def test_numbering_and_names():
    spec = layouts.Spec(
        "household",
        (layouts.Row("finance", "Finance"), layouts.Row(None, "My things")),
        True,
        SpecialFolders(),
    )
    folders = layouts.build_folders(spec)
    assert [f.path for f in folders] == [
        "##. Organize", "##. Ongoing", "##. Important", "##. To Delete",
        "10. Finance", "11. My things",
    ]  # fmt: skip
    assert [f.role for f in folders[:4]] == ["inbox", "ongoing", "important", "quarantine"]
    plain = layouts.build_folders(layouts.Spec(None, spec.rows, False, SpecialFolders()))
    assert [f.path for f in plain[4:]] == ["Finance", "My things"]


@pytest.mark.parametrize("bad", ["a/b", "Co:n", "CON", "nul.txt", "x.", "##. Mine", ".hidden", ""])
def test_layout_refuses_bad_or_duplicate_names(bad):
    rows = (layouts.Row(None, bad),)
    with pytest.raises(layouts.LayoutError):
        layouts.build_folders(layouts.Spec(None, rows, False, SpecialFolders()))


def test_layout_refuses_duplicates_case_insensitively():
    rows = (layouts.Row(None, "Taxes"), layouts.Row(None, "taxes"))
    with pytest.raises(layouts.LayoutError, match="Two folders"):
        layouts.build_folders(layouts.Spec(None, rows, False, SpecialFolders()))


# -- preview, create, undo ----------------------------------------------------------------


def test_preview_lists_every_folder_and_changes_nothing(blank):
    spec = household(blank)
    pv = blank.layout.preview(spec)
    assert len(pv.folders) == 15 and pv.to_create == 15
    assert pv.label == "Created the archive layout (15 folders)"
    assert [f.path for f in pv.folders][:5] == [
        "##. Organize", "##. Ongoing", "##. Important", "##. To Delete", "10. Finance",
    ]  # fmt: skip
    assert all(not f.exists for f in pv.folders)
    assert [op.kind for op in pv.ops] == [OpKind.MKDIR] * 15
    assert names(blank.test_archive) == []
    with blank.engine.connect() as conn:
        assert conn.execute(select(operations)).first() is None


def test_preview_marks_existing_folders_and_never_touches_them(blank):
    (blank.test_archive / "10. Finance").mkdir()
    (blank.test_archive / "10. Finance" / "keep.txt").write_text("mine", encoding="utf-8")
    pv = blank.layout.preview(household(blank))
    assert pv.to_create == 14
    assert next(f for f in pv.folders if f.path == "10. Finance").exists
    out = blank.layout.apply(household(blank))
    assert out.created == 14
    assert (blank.test_archive / "10. Finance" / "keep.txt").read_text(encoding="utf-8") == "mine"


def test_create_is_one_labelled_batch_and_makes_the_special_folders(blank):
    out = blank.layout.apply(household(blank))
    assert out.batch.failed is None and out.created == 15
    assert "##. Organize" in names(blank.test_archive)
    assert "11. Bills & Receipts" in names(blank.test_archive)
    batch = blank.activity.get(out.batch.batch_id)
    assert batch.label == "Created the archive layout (15 folders)" and batch.undoable
    assert batch.origin == "ui"


def test_nothing_to_create_is_refused(blank):
    blank.layout.apply(household(blank))
    with pytest.raises(InvalidRequest, match="exists already"):
        blank.layout.apply(household(blank))


@needs_dir_fd
def test_undo_removes_only_empty_folders(blank):
    out = blank.layout.apply(household(blank))
    archive = blank.test_archive
    (archive / "10. Finance" / "bank.pdf").write_text("a file arrived", encoding="utf-8")
    (archive / "13. Taxes" / "2025").mkdir()  # a sub folder the user made
    (archive / "14. Home" / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1" + b"\0" * 40)
    result = blank.activity.undo(out.batch.batch_id)
    assert result.batch.failed is None and result.batch.error is None
    assert sorted(result.batch.kept) == ["10. Finance", "13. Taxes"]
    left = names(archive)
    assert left == ["10. Finance", "13. Taxes"]
    assert (archive / "10. Finance" / "bank.pdf").read_text(encoding="utf-8") == "a file arrived"
    assert (archive / "13. Taxes" / "2025").is_dir()
    assert blank.activity.get(out.batch.batch_id).undone


def test_undo_all_empty_removes_every_folder(blank):
    out = blank.layout.apply(household(blank))
    preview = blank.activity.preview_undo(out.batch.batch_id)
    assert len(preview) == 15 and {op.kind for op in preview} == {OpKind.REMOVE_EMPTY_DIR}
    assert blank.activity.undo(out.batch.batch_id).batch.kept == []
    assert names(blank.test_archive) == []


def test_undo_leaves_a_folder_that_was_swapped_for_another(blank):
    out = blank.layout.apply(household(blank, drop=("home",)))
    archive = blank.test_archive
    folder = archive / "14. Vehicles"
    assert folder.is_dir()
    recreate_dir(folder)  # the user deleted it and made a new one with the same name
    result = blank.activity.undo(out.batch.batch_id)
    assert "14. Vehicles" in result.batch.kept and folder.is_dir()


@needs_dir_fd
def test_undo_removes_a_folder_whose_birth_changed_but_inode_is_the_same(blank):
    """Google Drive re-writes a new folder (same inode, later birth): still the app's."""
    out = blank.layout.apply(household(blank, drop=("home",)))
    archive = blank.test_archive
    (archive / "13. Taxes" / "2025").mkdir()  # still refused: not empty
    with blank.engine.begin() as conn:  # simulate the new birth through the stored value
        conn.execute(made_folders.update().values(st_birth="b:1"))
    result = blank.activity.undo(out.batch.batch_id)
    assert result.batch.failed is None and result.batch.error is None
    assert result.batch.kept == ["13. Taxes"]
    assert names(archive) == ["13. Taxes"]


def test_undo_never_removes_a_folder_that_was_not_recorded_as_made(blank):
    out = blank.layout.apply(household(blank))
    with blank.engine.begin() as conn:
        conn.execute(made_folders.delete().where(made_folders.c.rel == "12. Insurance"))
    result = blank.activity.undo(out.batch.batch_id)
    assert (blank.test_archive / "12. Insurance").is_dir()
    assert names(blank.test_archive) == ["12. Insurance"] and result.batch.kept == []


def test_undo_cannot_be_forged_through_apply(blank):
    """A caller cannot ask for the made-folder removal itself: only undo builds it."""
    (blank.test_archive / "10. Finance").mkdir()
    plan = Plan(
        [Op(OpKind.REMOVE_EMPTY_DIR, "10. Finance", None, made=True, identity=(1, 1))], "ui"
    )
    with pytest.raises(GuardError, match="Only an undo"):
        blank.executor.preview(plan)
    plan = Plan([Op(OpKind.REMOVE_EMPTY_DIR, "10. Finance", None)], "ui")
    with pytest.raises(GuardError):  # not inside Ongoing / Important
        blank.executor.preview(plan)
    assert (blank.test_archive / "10. Finance").is_dir()


# -- top-level folders are still never made automatically ----------------------------------


def test_filing_cannot_create_a_top_level_folder(blank):
    archive = blank.test_archive
    blank.layout.apply(blank.layout.spec("empty", False, []))
    (archive / "##. Organize" / "doc.pdf").write_bytes(b"%PDF-1.4 x")
    blank.scan()
    entry = blank.inbox.list()[0]
    request = FileRequest(entry.record.drive_id, "doc.pdf", "Brand New Top")
    with pytest.raises(GuardError, match="top-level"):
        blank.inbox.file_it([request], origin="ui")
    assert not (archive / "Brand New Top").exists()


def test_a_plain_plan_cannot_create_a_top_level_folder(blank):
    for op in (
        Op(OpKind.MKDIR, None, "Top"),
        Op(OpKind.MKDIR, None, "Top/Sub"),
        Op(OpKind.SYMLINK, "x", "Top/link"),
    ):
        with pytest.raises((GuardError, Exception)):
            blank.executor.preview(Plan([op], "ui"))
    assert names(blank.test_archive) == []


def test_a_rule_target_is_not_created_either(blank):
    archive = blank.test_archive
    blank.layout.apply(blank.layout.spec("empty", False, []))
    # rules only suggest a folder; filing it into a top-level folder that does not exist
    # is refused exactly like any other filing
    (archive / "##. Organize" / "r.pdf").write_bytes(b"%PDF-1.4 x")
    blank.scan()
    rec = blank.inbox.list()[0].record
    with pytest.raises(GuardError):
        blank.inbox.preview([FileRequest(rec.drive_id, "r.pdf", "11. Bills & Receipts/2026")])
    assert names(archive) == ["##. Important", "##. Ongoing", "##. Organize", "##. To Delete"]


def test_a_new_folders_plan_holds_only_folder_creations(blank):
    for ops in (
        [Op(OpKind.MKDIR, None, "Ok"), Op(OpKind.RENAME, "Ok", "No")],
        [Op(OpKind.MKDIR, None, "Ok", exact=True)],
        [Op(OpKind.MKDIR, None, "##. Organize/Sub")],
        [Op(OpKind.MKDIR, None, "CON")],
        [Op(OpKind.MKDIR, None, "##. Mine")],
    ):
        with pytest.raises(GuardError):
            blank.executor.preview(Plan(ops, "ui", new_folders=True))
    assert names(blank.test_archive) == []


def test_new_folders_flag_cannot_be_used_by_undo_origin(blank):
    with pytest.raises(GuardError, match="reserved"):
        blank.executor.preview(Plan([Op(OpKind.MKDIR, None, "X")], "undo", new_folders=True))


# -- special folder names in the settings ---------------------------------------------------


def test_special_folder_names_are_written_to_the_settings(tmp_path):
    paths = AppPaths(tmp_path / "data")
    paths.ensure()
    special = SpecialFolders(
        inbox="00 Inbox", ongoing="Ongoing", important="Keep", quarantine="Trash me"
    )
    setup.write_layout_settings(paths, special, ["Health"])
    settings = load_settings(paths)
    assert settings.special_folders == special
    assert settings.protected_paths == ["Keep"]  # Important was renamed: still protected
    assert settings.ai.exclude_folders == ["Health"]
    text = (paths.config_dir / "settings.yaml").read_text(encoding="utf-8")
    assert "# OCR languages" in text  # comments elsewhere are kept
    assert list(paths.config_dir.glob("settings.yaml.bak-*"))


def test_default_names_change_nothing_in_the_settings(tmp_path):
    paths = AppPaths(tmp_path / "data")
    paths.ensure()
    before = (paths.config_dir / "settings.yaml").read_text(encoding="utf-8")
    setup.write_layout_settings(paths, SpecialFolders(), [])
    assert (paths.config_dir / "settings.yaml").read_text(encoding="utf-8") == before


def test_an_existing_ai_section_is_left_alone(tmp_path):
    paths = AppPaths(tmp_path / "data")
    paths.ensure()
    f = paths.config_dir / "settings.yaml"
    f.write_text(
        f.read_text(encoding="utf-8") + "\nai:\n  exclude_folders:\n    - Mine\n", encoding="utf-8"
    )
    setup.write_layout_settings(paths, SpecialFolders(), ["Health"])
    assert load_settings(paths).ai.exclude_folders == ["Mine"]


# -- rules for the layout --------------------------------------------------------------------


def test_example_rules_target_the_layout_and_load(blank):
    out = blank.layout.apply(household(blank))
    assert out.rules_written and "tax-letters" in out.rule_ids
    rules, errors = load_rules(blank.rules_dir)
    assert errors == []
    by_id = {r.id: r for r in rules}
    assert by_id["receipts-and-invoices"].then.folder == "11. Bills & Receipts/{year}"
    assert by_id["tax-letters"].then.folder == "13. Taxes/{year}"
    assert by_id["tax-letters"].when.folder_is == "##. Organize"
    assert {r.id for r in blank.rules} == set(by_id)  # the running app reloaded them
    for rule in rules:  # every target is a folder the layout made
        top = rule.then.folder.split("/")[0]
        assert (blank.test_archive / top).is_dir(), rule.id
    text = (blank.rules_dir / "00-examples.yaml").read_text(encoding="utf-8")
    assert "# - id: apteekki-receipts" in text  # the Finland examples stay, commented out


def test_removed_or_renamed_folders_drop_or_follow_their_rules(blank):
    spec = household(blank, numbered=False, drop=("taxes",))
    rows = [(r.key, "Receipts" if r.key == "bills" else r.name) for r in spec.rows]
    out = blank.layout.apply(blank.layout.spec("household", False, rows))
    rules = {r.id: r for r in load_rules(blank.rules_dir)[0]}
    assert "tax-letters" not in rules
    assert rules["receipts-and-invoices"].then.folder == "Receipts/{year}"
    assert out.rules_written


def test_empty_layout_writes_no_active_rules(blank):
    blank.layout.apply(blank.layout.spec("empty", False, []))
    rules, errors = load_rules(blank.rules_dir)
    assert rules == [] and errors == []


def test_user_rules_are_never_overwritten(blank):
    mine = blank.rules_dir / "00-examples.yaml"
    mine.write_text("# mine\n- id: my-rule\n  then: {folder: Elsewhere}\n", encoding="utf-8")
    out = blank.layout.apply(household(blank))
    assert out.rules_written is False
    assert mine.read_text(encoding="utf-8").startswith("# mine")
    other = blank.rules_dir / "50-mine.yaml"
    mine.write_text(
        (layouts.DEFAULTS_DIR / "rules" / "00-examples.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    other.write_text("- id: another\n", encoding="utf-8")
    (blank.test_archive / "x").mkdir()
    spec = blank.layout.spec("household", True, [(None, "Extra")])
    assert blank.layout.apply(spec).rules_written is False  # another rules file exists
    assert other.read_text(encoding="utf-8") == "- id: another\n"


def test_the_examples_as_shipped_in_0_1_0_are_still_replaced(blank):
    """The examples' comments changed after 0.1.0: an unedited 0.1.0 copy (any line
    endings) still counts as the user's no rules."""
    shipped = (layouts.DEFAULTS_DIR / "rules" / "00-examples.yaml").read_text(encoding="utf-8")
    shipped = shipped.replace(
        "# Rules you make in the app are kept in learned.yaml, which is read first.\n#\n", ""
    )  # added after 0.1.0
    old_line = "#   folder_is:        folder the file currently sits in\n"
    start = shipped.index("#   folder_is:")
    end = shipped.index("# then:")
    old = shipped[:start] + old_line + shipped[end:]
    mine = blank.rules_dir / "00-examples.yaml"
    mine.write_bytes(old.replace("\n", "\r\n").encode("utf-8"))
    assert blank.layout.apply(household(blank)).rules_written is True


# -- New folder ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["", "  ", "a/b", "a\\b", "CON", "nul", "Com1", "lpt9.txt", "end.", ".hid", "##. Mine",
     "a:b", "a*b", "x" * 300, ".."],
)  # fmt: skip
def test_new_folder_refuses_bad_names(blank, name):
    with pytest.raises(InvalidRequest):
        blank.layout.new_folder_preview("", name)
    assert names(blank.test_archive) == []


def test_new_folder_name_rules():
    special = ("##. Organize",)
    assert check_folder_name("  Taxes 2026 ") == "Taxes 2026"
    assert check_folder_name("##. Organize", special) == "##. Organize"
    assert check_folder_name("##. organize", special) == "##. organize"
    with pytest.raises(FolderNameError):
        check_folder_name("##. Other", special)
    assert check_folder_name("Café") == "Café"


def test_new_folder_at_the_top_and_inside_and_undo(blank):
    archive = blank.test_archive
    preview = blank.layout.new_folder_preview("", "Taxes")
    assert [(op.kind, op.dst) for op in preview] == [(OpKind.MKDIR, "Taxes")]
    assert names(archive) == []
    top = blank.layout.new_folder("", "Taxes")
    assert top.failed is None and (archive / "Taxes").is_dir()
    sub = blank.layout.new_folder("Taxes", "2026")
    assert (archive / "Taxes" / "2026").is_dir()
    assert (
        blank.activity.get(top.batch_id).label
        == "Created the folder Taxes at the top of the archive"
    )
    assert blank.activity.get(sub.batch_id).label == "Created the folder 2026 in Taxes"
    (archive / "Taxes" / "2026" / "f.txt").write_text("x", encoding="utf-8")
    undone = blank.activity.undo(sub.batch_id)
    assert undone.batch.kept == ["Taxes/2026"] and (archive / "Taxes" / "2026").is_dir()
    (archive / "Taxes" / "2026" / "f.txt").unlink()
    assert blank.activity.undo(top.batch_id).batch.kept == ["Taxes"]  # it holds 2026 still
    assert (archive / "Taxes").is_dir()


def test_new_folder_undo_when_empty(blank):
    batch = blank.layout.new_folder("", "Temp")
    blank.activity.undo(batch.batch_id)
    assert names(blank.test_archive) == []


def test_new_folder_refuses_existing_and_the_apps_own_folders(blank):
    blank.layout.apply(blank.layout.spec("empty", False, []))
    blank.layout.new_folder("", "Taxes")
    with pytest.raises(InvalidRequest, match="already"):
        blank.layout.new_folder("", "taxes")
    for parent in ("##. Organize", "##. Ongoing", "##. Important", "##. To Delete"):
        with pytest.raises(InvalidRequest, match="not made inside"):
            blank.layout.new_folder(parent, "Sub")
    for parent in ("Nope", "../out", "/abs"):
        with pytest.raises(InvalidRequest):
            blank.layout.new_folder(parent, "Sub")


def test_new_folder_api(blank):
    with TestClient(create_api(blank), base_url=BASE) as c:
        bad = c.post("/api/folders/new/preview", json={"parent": "", "name": "a/b"}, headers=ORIGIN)
        assert bad.status_code == 400 and "one folder at a time" in bad.json()["error"]
        ok = c.post("/api/folders/new", json={"parent": "", "name": "Taxes"}, headers=ORIGIN)
        assert ok.status_code == 200 and ok.json()["done"][0]["dst"] == "Taxes"
        undo = c.post(f"/api/activity/{ok.json()['batch_id']}/undo", headers=ORIGIN, json={})
        assert undo.status_code == 200 and undo.json()["kept"] == []
    assert names(blank.test_archive) == []


def test_layout_api(blank):
    body = {
        "template": "minimal",
        "numbered": True,
        "folders": [{"key": "documents", "name": "Docs"}],
    }
    with TestClient(create_api(blank), base_url=BASE) as c:
        t = c.get("/api/layout/templates").json()
        assert [x["id"] for x in t["templates"]] == ["household", "minimal", "empty"]
        assert [f["role"] for f in t["special_folders"]] == [
            "inbox", "ongoing", "important", "quarantine",
        ]  # fmt: skip
        pv = c.post("/api/layout/preview", json=body, headers=ORIGIN).json()
        assert pv["to_create"] == 5 and pv["folders"][4]["path"] == "10. Docs"
        assert names(blank.test_archive) == []
        done = c.post("/api/layout", json=body, headers=ORIGIN).json()
        assert done["created"] == 5 and done["rules_written"] and done["batch"]["failed"] is None
        again = c.post("/api/layout", json=body, headers=ORIGIN)
        assert again.status_code == 400
        bad = c.post("/api/layout", json={**body, "folders": [{"name": "CON"}]}, headers=ORIGIN)
        assert bad.status_code == 400 and "reserved" in bad.json()["error"]


# -- copying files into the inbox ------------------------------------------------------------------


@pytest.fixture
def started(blank):
    blank.layout.apply(blank.layout.spec("minimal", False, []))
    return blank


def source(tmp_path: Path, name: str = "scan.pdf", data: bytes = b"%PDF-1.4 hello") -> Path:
    p = tmp_path / "elsewhere" / name
    p.parent.mkdir(exist_ok=True)
    p.write_bytes(data)
    return p


def test_add_copies_into_the_inbox_and_keeps_the_original(started, tmp_path):
    src = source(tmp_path)
    result = started.intake.add_files([src])
    assert result.failed is None
    copy = started.test_archive / "##. Organize" / "scan.pdf"
    assert copy.read_bytes() == b"%PDF-1.4 hello" and src.exists()
    assert started.activity.get(result.batch_id).label == "Added scan.pdf to the inbox"
    # indexed at once: the inbox lists it without waiting for the watcher
    assert [e.record.name for e in started.inbox.list()] == ["scan.pdf"]


def test_add_never_overwrites_and_numbers_collisions(started, tmp_path):
    src = source(tmp_path)
    inbox = started.test_archive / "##. Organize"
    (inbox / "scan.pdf").write_bytes(b"mine")
    started.intake.add_files([src, src])
    assert (inbox / "scan.pdf").read_bytes() == b"mine"
    assert (inbox / "scan_2.pdf").read_bytes() == b"%PDF-1.4 hello"
    assert (inbox / "scan_3.pdf").read_bytes() == b"%PDF-1.4 hello"
    preview = started.intake.preview([src])
    assert preview[0].dst == "##. Organize/scan_4.pdf" and preview[0].note


def test_add_undo_moves_the_copy_to_the_quarantine_never_deletes(started, tmp_path):
    result = started.intake.add_files([source(tmp_path)])
    undone = started.activity.undo(result.batch_id)
    assert undone.batch.failed is None
    archive = started.test_archive
    assert not (archive / "##. Organize" / "scan.pdf").exists()
    moved = archive / "##. To Delete" / "##. Organize" / "scan.pdf"
    assert moved.read_bytes() == b"%PDF-1.4 hello"
    assert started.activity.get(result.batch_id).undone


def test_add_undo_refused_when_the_copy_changed(started, tmp_path):
    result = started.intake.add_files([source(tmp_path)])
    (started.test_archive / "##. Organize" / "scan.pdf").write_bytes(b"edited later, longer")
    with pytest.raises(Exception, match="changed since"):
        started.activity.undo(result.batch_id)


def test_add_size_limit(started, tmp_path, monkeypatch):
    big = source(tmp_path, "big.bin", b"x" * 100)
    monkeypatch.setattr("dam.services.intake.MAX_COPY_BYTES", 50)
    with pytest.raises(TooLarge):
        started.intake.add_files([big])
    assert list((started.test_archive / "##. Organize").iterdir()) == []
    assert MAX_COPY_BYTES == 200 * 1024 * 1024


def test_add_needs_regular_files(started, tmp_path):
    folder = tmp_path / "adir"
    folder.mkdir()
    with pytest.raises(InvalidRequest, match="not a file"):
        started.intake.add_files([folder])
    with pytest.raises(InvalidRequest, match="No files"):
        started.intake.add_files([])


def test_add_without_an_inbox_says_so(blank, tmp_path):
    with pytest.raises(InvalidRequest, match="does not exist yet"):
        blank.intake.add_files([source(tmp_path)])


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("a/b/c.pdf", "c.pdf"),
        ("C:\\x\\y.pdf", "y.pdf"),
        ("a:b?.pdf", "a_b_.pdf"),
        ("con.pdf", "_con.pdf"),
        ("trail. ", "trail"),
    ],
)
def test_clean_file_name(raw, clean):
    from dam.services.intake import clean_file_name

    assert clean_file_name(raw) == clean


def test_clean_file_name_refuses_hidden_and_empty():
    from dam.services.intake import clean_file_name

    for bad in (".hidden", ".DS_Store", "", "..."):
        with pytest.raises(InvalidRequest):
            clean_file_name(bad)


def test_upload_endpoint(started, tmp_path, monkeypatch):
    headers = {**ORIGIN, "Content-Type": "application/octet-stream"}
    with TestClient(create_api(started), base_url=BASE) as c:
        r = c.post(
            "/api/inbox/upload?name=Receipt%202026.pdf", content=b"%PDF-1.4 up", headers=headers
        )
        assert r.status_code == 200, r.text
        inbox = started.test_archive / "##. Organize"
        assert (inbox / "Receipt 2026.pdf").read_bytes() == b"%PDF-1.4 up"
        again = c.post(
            "/api/inbox/upload?name=Receipt%202026.pdf", content=b"second", headers=headers
        )
        assert again.json()["done"][0]["dst"] == "##. Organize/Receipt 2026_2.pdf"
        assert (inbox / "Receipt 2026.pdf").read_bytes() == b"%PDF-1.4 up"
        # a name with a path in it keeps only the file name
        r = c.post("/api/inbox/upload?name=..%2F..%2Fevil.pdf", content=b"x", headers=headers)
        assert r.status_code == 200 and (inbox / "evil.pdf").exists()
        assert (
            c.post("/api/inbox/upload?name=e.pdf", content=b"", headers=headers).status_code == 400
        )
        monkeypatch.setattr("dam.api.routers.inbox.MAX_COPY_BYTES", 10)
        big = c.post("/api/inbox/upload?name=big.pdf", content=b"x" * 11, headers=headers)
        assert big.status_code == 413 and not (inbox / "big.pdf").exists()
        # still local-only: no Origin, a foreign Origin, or a plain form type is refused
        no_origin = c.post(
            "/api/inbox/upload?name=a.pdf",
            content=b"x",
            headers={"Content-Type": "application/octet-stream"},
        )
        assert no_origin.status_code == 403
        foreign = c.post(
            "/api/inbox/upload?name=a.pdf",
            content=b"x",
            headers={"Origin": "http://evil.example", "Content-Type": "application/octet-stream"},
        )
        assert foreign.status_code == 403
        form = c.post(
            "/api/inbox/upload?name=a.pdf",
            content=b"x",
            headers={**ORIGIN, "Content-Type": "multipart/form-data; boundary=x"},
        )
        assert form.status_code == 415
        # octet-stream is accepted nowhere else
        other = c.post("/api/folders/new", content=b"{}", headers=headers)
        assert other.status_code == 415
    assert not any((started.app_paths.cache_dir / "uploads").iterdir())


def test_cli_add_and_undo(started, tmp_path):
    src = source(tmp_path, "cli.pdf")
    base = ["--data-dir", str(started.app_paths.data_dir)]
    started.close()
    r = runner.invoke(cli, [*base, "add", str(src), "--yes"])
    assert r.exit_code == 0, r.output
    inbox = started.test_archive / "##. Organize"
    assert (inbox / "cli.pdf").exists() and "dam undo" in r.output
    batch = r.output.split("dam undo ")[1].split()[0]
    r = runner.invoke(cli, [*base, "undo", batch, "--yes"])
    assert r.exit_code == 0, r.output
    assert not (inbox / "cli.pdf").exists()
    assert (started.test_archive / "##. To Delete" / "##. Organize" / "cli.pdf").exists()
    r = runner.invoke(cli, [*base, "add", str(tmp_path / "missing.pdf")])
    assert r.exit_code == 2  # click: the file must exist


# -- first run with a layout ------------------------------------------------------------


def test_setup_with_a_layout_end_to_end(tmp_path):
    paths = AppPaths(tmp_path / "data")
    paths.ensure()
    folder = tmp_path / "Archive"
    folder.mkdir()
    (folder / ".DS_Store").write_text("", encoding="utf-8")
    holder: list[App] = []

    def activate() -> bool:
        holder.append(App.create(paths.data_dir))
        return True

    api = create_setup_api(
        paths, None, on_configured=activate, on_layout=lambda spec: holder[0].layout.apply(spec)
    )
    body = {
        "template": "household",
        "numbered": True,
        "folders": [{"key": "finance", "name": "Money"}, {"key": None, "name": "Pets"}],
        "special": {
            "inbox": "00 In", "ongoing": "01 Doing", "important": "02 Keep", "quarantine": "99 Bin"
        },
    }  # fmt: skip
    try:
        with TestClient(api, base_url=BASE) as c:
            pv = c.post(
                "/api/setup/layout-preview",
                json={"path": str(folder), "layout": body},
                headers=ORIGIN,
            )
            assert pv.status_code == 200, pv.text
            assert pv.json()["to_create"] == 6 and not any(
                f["exists"] for f in pv.json()["folders"]
            )
            assert names(folder) == [".DS_Store"]  # the preview changed nothing
            r = c.post(
                "/api/setup", json={"archive_root": str(folder), "layout": body}, headers=ORIGIN
            )
            assert r.status_code == 200, r.text
            out = r.json()
            assert out["restart_needed"] is False and out["layout"]["created"] == 6
            assert out["layout"]["batch"]["failed"] is None
        assert names(folder) == [
            ".DS_Store", "00 In", "01 Doing", "02 Keep", "10. Money", "11. Pets", "99 Bin",
        ]  # fmt: skip
        settings = load_settings(paths)
        assert settings.special_folders.inbox == "00 In"
        assert settings.protected_paths == ["02 Keep"]
        app = holder[0]
        assert app.paths.inbox == "00 In"
        label = app.activity.recent(1)[0].label
        assert label == "Created the archive layout (6 folders)"
        assert app.activity.undo(app.activity.recent(1)[0].batch_id).batch.kept == []
        assert names(folder) == [".DS_Store"]
    finally:
        for a in holder:
            a.close()


def test_setup_layout_errors_are_refused_before_anything_is_written(tmp_path):
    paths = AppPaths(tmp_path / "data")
    paths.ensure()
    folder = tmp_path / "A"
    folder.mkdir()
    api = create_setup_api(paths, None, on_configured=lambda: True)
    bad = {"template": None, "numbered": False, "folders": [{"name": "a/b"}]}
    with TestClient(api, base_url=BASE) as c:
        r = c.post("/api/setup", json={"archive_root": str(folder), "layout": bad}, headers=ORIGIN)
    assert r.status_code == 400
    assert not setup.is_configured(paths)
    assert load_settings(paths).special_folders == SpecialFolders()


def test_setup_without_a_layout_is_unchanged(tmp_path):
    paths = AppPaths(tmp_path / "data")
    paths.ensure()
    folder = tmp_path / "A"
    folder.mkdir()
    api = create_setup_api(paths, None, on_configured=lambda: True)
    with TestClient(api, base_url=BASE) as c:
        r = c.post("/api/setup", json={"archive_root": str(folder)}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["layout"] is None and list(folder.iterdir()) == []


def test_setup_layout_when_the_app_could_not_switch(tmp_path):
    paths = AppPaths(tmp_path / "data")
    paths.ensure()
    folder = tmp_path / "A"
    folder.mkdir()
    api = create_setup_api(paths, None, on_configured=lambda: False)
    body = {
        "template": "minimal",
        "numbered": False,
        "folders": [{"key": "other", "name": "Other"}],
    }
    with TestClient(api, base_url=BASE) as c:
        r = c.post("/api/setup", json={"archive_root": str(folder), "layout": body}, headers=ORIGIN)
    out = r.json()
    assert out["restart_needed"] and "restarted" in out["layout"]["error"]
    assert list(folder.iterdir()) == [] and setup.is_configured(paths)


# -- dam init -----------------------------------------------------------------------------


def run(paths, *args, input=None):
    return runner.invoke(cli, ["--data-dir", str(paths.data_dir), *map(str, args)], input=input)


def test_init_offers_a_new_archive_in_an_empty_folder(tmp_path):
    paths = AppPaths(tmp_path / "d")
    folder = tmp_path / "Archive"
    folder.mkdir()
    (folder / "Thumbs.db").write_text("", encoding="utf-8")
    # empty: start new (Enter = yes), layout 2 (Minimal), numbered (Enter), no special
    # rename (Enter), no edits (Enter), make the folders (Enter), write (Enter)
    r = run(paths, "init", "--archive", folder, input="\n2\n\n\n\n\n\n")
    assert r.exit_code == 0, r.output
    assert "is empty" in r.output and "Created the archive layout (7 folders)" in r.output
    assert "dam undo" in r.output
    assert names(folder) == [
        "##. Important", "##. Ongoing", "##. Organize", "##. To Delete", "10. Documents",
        "11. Receipts", "12. Other", "Thumbs.db",
    ]  # fmt: skip


def test_init_with_content_defaults_to_use_as_is(tmp_path):
    paths = AppPaths(tmp_path / "d")
    folder = tmp_path / "Archive"
    (folder / "Old").mkdir(parents=True)
    r = run(paths, "init", "--archive", folder, input="\ny\n")  # Enter = no layout; write
    assert r.exit_code == 0, r.output
    assert "will be used as it is" in r.output
    assert names(folder) == ["Old"] and setup.is_configured(paths)


def test_init_can_add_a_layout_to_an_archive_with_content_without_touching_it(tmp_path):
    paths = AppPaths(tmp_path / "d")
    folder = tmp_path / "Archive"
    (folder / "10. Finance").mkdir(parents=True)
    (folder / "10. Finance" / "a.pdf").write_text("keep", encoding="utf-8")
    r = run(paths, "init", "--archive", folder, "--layout", "household", "--yes")
    assert r.exit_code == 0, r.output
    assert (folder / "10. Finance" / "a.pdf").read_text(encoding="utf-8") == "keep"
    assert "11. Bills & Receipts" in names(folder) and "##. Organize" in names(folder)


def test_init_layout_none_and_unknown(tmp_path):
    paths = AppPaths(tmp_path / "d")
    folder = tmp_path / "Archive"
    folder.mkdir()
    assert run(paths, "init", "--archive", folder, "--layout", "none", "--yes").exit_code == 0
    assert names(folder) == []
    r = run(paths, "init", "--archive", folder, "--layout", "nope", "--yes")
    assert r.exit_code == 1 and "Unknown layout" in r.output


def test_init_edit_rename_remove_add_and_special_names(tmp_path):
    paths = AppPaths(tmp_path / "d")
    folder = tmp_path / "Archive"
    folder.mkdir()
    answers = "\n".join(
        [
            "y",  # start a new archive
            "2",  # Minimal
            "n",  # no numbers
            "y",  # change special folder names
            "In", "Doing", "Keep", "Bin",
            "r 1 Papers", "d 3", "a Photos", "",  # edits, then done
            "", "",  # make them, write
        ]
    ) + "\n"  # fmt: skip
    r = run(paths, "init", "--archive", folder, input=answers)
    assert r.exit_code == 0, r.output
    assert names(folder) == ["Bin", "Doing", "In", "Keep", "Papers", "Photos", "Receipts"]
    assert load_settings(paths).special_folders.inbox == "In"


def test_init_refuses_a_bad_edited_name(tmp_path):
    paths = AppPaths(tmp_path / "d")
    folder = tmp_path / "Archive"
    folder.mkdir()
    r = run(paths, "init", "--archive", folder, "--layout", "minimal", "--yes")
    assert r.exit_code == 0
    # the layout options work without prompts; a bad name through the API is refused
    # (see test_layout_api) and the CLI edits go through the same checks
    from dam.cli.newarchive import show_folders

    bad = layouts.Spec(None, (layouts.Row(None, "a/b"),), False, SpecialFolders())
    with pytest.raises(InvalidRequest):
        show_folders(bad, set())
