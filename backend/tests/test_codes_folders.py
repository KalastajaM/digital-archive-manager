"""Creating the filing codes' inbox folders: previewed, journaled, undoable."""

import pytest
from fastapi.testclient import TestClient

from dam.api import create_api
from dam.codes.folders import (
    create_inbox_folders,
    create_inbox_folders_plan,
    missing_inbox_folders,
    preview_inbox_folders,
    stray_inbox_folders,
)
from dam.config import SpecialFolders
from dam.ops.model import GuardError, Op, OpKind, Plan
from dam.services.errors import InvalidRequest
from test_api import BASE, LOCAL_ORIGIN

INBOX = SpecialFolders().inbox
CODE_FOLDERS = ["To action", "To pay", "File as suggested"]  # the seeded codes'


def _tree(root) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")}


def test_preview_lists_missing_folders(app, fake_archive):
    assert sorted(missing_inbox_folders(app)) == sorted(CODE_FOLDERS)
    ops = app.executor.preview(create_inbox_folders_plan(app, "ui"))
    assert [op.kind for op in ops] == [OpKind.MKDIR] * 3
    assert sorted(op.dst for op in ops) == sorted(f"{INBOX}/{n}" for n in CODE_FOLDERS)
    assert not (fake_archive.root / INBOX / "To pay").exists()  # preview changes nothing


def test_only_missing_folders_are_planned(app, fake_archive):
    (fake_archive.root / INBOX / "to PAY").mkdir()  # folded match counts as there
    assert sorted(missing_inbox_folders(app)) == ["File as suggested", "To action"]
    plan = create_inbox_folders_plan(app, "ui")
    assert plan.label == f"Created the filing code folders in {INBOX}"
    assert sorted(op.dst for op in plan.ops) == [
        f"{INBOX}/File as suggested",
        f"{INBOX}/To action",
    ]


def test_create_then_undo_removes_them(app, fake_archive):
    fake_archive.add(f"{INBOX}/scan.pdf", drive_id="s1")
    app.scan()
    before = _tree(fake_archive.root)
    batch = app.executor.apply(create_inbox_folders_plan(app, "ui"))
    assert batch.failed is None and batch.error is None
    for name in CODE_FOLDERS:
        assert (fake_archive.root / INBOX / name).is_dir()
    assert missing_inbox_folders(app) == []
    app.activity.undo(batch.batch_id)
    assert _tree(fake_archive.root) == before
    assert sorted(missing_inbox_folders(app)) == sorted(CODE_FOLDERS)


def test_inbox_folders_plan_refuses_deeper(app, fake_archive):
    (fake_archive.root / INBOX / "To pay").mkdir()
    plan = Plan(
        [Op(OpKind.MKDIR, None, f"{INBOX}/To pay/x")],
        origin="ui",
        new_folders=True,
        inbox_folders=True,
    )
    with pytest.raises(GuardError):
        app.executor.preview(plan)
    assert not (fake_archive.root / INBOX / "To pay" / "x").exists()


@pytest.mark.parametrize("area", ["ongoing", "important", "quarantine"])
def test_inbox_folders_plan_refuses_other_special_folders(app, area):
    folder = getattr(SpecialFolders(), area)
    plan = Plan(
        [Op(OpKind.MKDIR, None, f"{folder}/x")],
        origin="ui",
        new_folders=True,
        inbox_folders=True,
    )
    with pytest.raises(GuardError):
        app.executor.preview(plan)


def test_inbox_folders_needs_new_folders(app):
    plan = Plan([Op(OpKind.MKDIR, None, f"{INBOX}/x")], origin="ui", inbox_folders=True)
    with pytest.raises(GuardError):
        app.executor.preview(plan)


def test_plain_new_folder_plan_still_refused_in_inbox(app):
    plan = Plan([Op(OpKind.MKDIR, None, f"{INBOX}/x")], origin="ui", new_folders=True)
    with pytest.raises(GuardError):
        app.executor.preview(plan)


def test_plain_new_folder_still_refused_in_inbox(app):
    with pytest.raises(InvalidRequest):
        app.layout.new_folder_preview(INBOX, "To pay")


def test_stray_lists_own_subfolder(app, fake_archive):
    (fake_archive.root / INBOX / "Old stuff").mkdir()
    (fake_archive.root / INBOX / "To pay").mkdir()
    fake_archive.add(f"{INBOX}/scan.pdf")
    assert stray_inbox_folders(app) == ["Old stuff"]


def test_nothing_missing_previews_nothing_and_creates_nothing(app, fake_archive):
    for name in CODE_FOLDERS:
        (fake_archive.root / INBOX / name).mkdir()
    assert create_inbox_folders_plan(app, "ui").ops == []
    assert preview_inbox_folders(app, "ui") == []
    with pytest.raises(InvalidRequest):
        create_inbox_folders(app, "ui")


@pytest.fixture
def client(app):
    with TestClient(create_api(app, None), base_url=BASE) as c:
        yield c


def test_api_folders(client, app, fake_archive):
    (fake_archive.root / INBOX / "Old stuff").mkdir()
    app.scan()
    r = client.get("/api/filing-codes/folders")
    assert r.status_code == 200, r.text
    assert sorted(r.json()["missing"]) == sorted(CODE_FOLDERS)
    assert r.json()["stray"] == ["Old stuff"]

    r = client.post("/api/filing-codes/folders/preview", json={}, headers=LOCAL_ORIGIN)
    assert r.status_code == 200, r.text
    assert sorted(op["dst"] for op in r.json()) == sorted(f"{INBOX}/{n}" for n in CODE_FOLDERS)
    assert not (fake_archive.root / INBOX / "To pay").exists()

    r = client.post("/api/filing-codes/folders", json={}, headers=LOCAL_ORIGIN)
    assert r.status_code == 200, r.text
    assert len(r.json()["done"]) == 3
    assert (fake_archive.root / INBOX / "To pay").is_dir()
    assert f"{INBOX}/To pay" in app.repo.dir_paths()  # indexed at once
    assert client.get("/api/filing-codes/folders").json()["missing"] == []
