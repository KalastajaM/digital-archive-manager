"""Converting the current ``##. Ongoing`` into collections (Phase 2 Task 10)."""

import dataclasses
import os
import threading
from pathlib import Path

import pytest
import xattr
from fastapi.testclient import TestClient
from sqlalchemy import select

from conftest import in_group, needs_dir_fd, old_group, posix_permissions
from dam.api import create_api
from dam.collections.convert import NOT_REMOVED, Entry, EntryItem
from dam.core.fs import readlink, realpath
from dam.db.tables import ongoing_entries, operations
from dam.errors import InvalidRequest
from dam.index.driveid import DRIVE_ID_XATTR
from dam.ops import executor as executor_module
from dam.ops import identity, primitives
from dam.ops.model import BatchResult, GuardError, OpFailed, OpKind, ResolvedOp

ONG = "##. Ongoing"
FAMILY = "40. Family"
TAXES = "13. Taxes"
FINDER = b"\x00\x00\x00\x01Bud1" + b"\x00" * 24  # Finder's .DS_Store header


# --- helpers -----------------------------------------------------------------------


def folder(fake_archive, rel: str, drive_id: str) -> Path:
    p = fake_archive.root / rel
    p.mkdir(parents=True, exist_ok=True)
    xattr.setxattr(p, DRIVE_ID_XATTR, drive_id.encode())
    return p


def ongoing(fake_archive) -> Path:
    return fake_archive.root / ONG


def listing(path: Path) -> list[str]:
    return sorted(os.listdir(path))


def points_at(link: Path, fake_archive, rel: str) -> bool:
    return link.is_symlink() and str(realpath(link)) == str(fake_archive.root.resolve() / rel)


def journal(app, batch_id: str):
    with app.engine.connect() as conn:
        return conn.execute(
            select(operations).where(operations.c.batch_id == batch_id).order_by(operations.c.id)
        ).all()


def batch_ids(app) -> list[str]:
    with app.engine.connect() as conn:
        rows = conn.execute(select(operations.c.batch_id).order_by(operations.c.id)).scalars()
        return list(dict.fromkeys(rows))


def records(app):
    with app.engine.connect() as conn:
        return conn.execute(select(ongoing_entries).order_by(ongoing_entries.c.rel)).all()


def member_ids(app, collection_id: int) -> set[str]:
    return {m.drive_id for m in app.collections.get(collection_id).members}


def convert(app, rel: str, collection: str, destination):
    """Preview, then apply exactly what was previewed."""
    plan = app.convert.preview(rel, collection, destination)
    return app.convert.apply(rel, collection, destination, plan.fingerprint)


@pytest.fixture
def demo(app, fake_archive, tmp_path):
    """A Phase 1 demo-style Ongoing: a link to a folder, a link to a file, a real
    folder (2 files, 1 inner link, 1 subfolder), a real file."""
    folder(fake_archive, f"{FAMILY}/Tilly", "d-tilly")
    fake_archive.add(f"{FAMILY}/Tilly/school.pdf", drive_id="id-school")
    fake_archive.add(f"{TAXES}/2025.pdf", drive_id="id-tax")
    fake_archive.add(f"{FAMILY}/will.pdf", drive_id="id-will")
    fake_archive.link(f"{ONG}/Tilly", f"{FAMILY}/Tilly")
    fake_archive.link(f"{ONG}/Tax 2025.pdf", f"{TAXES}/2025.pdf")
    folder(fake_archive, f"{ONG}/Legal", "d-legal")
    fake_archive.add(f"{ONG}/Legal/contract.pdf", drive_id="id-contract")
    fake_archive.add(f"{ONG}/Legal/letter.pdf", drive_id="id-letter")
    folder(fake_archive, f"{ONG}/Legal/Deed", "d-deed")
    fake_archive.add(f"{ONG}/Legal/Deed/deed.pdf", drive_id="id-deed")
    fake_archive.link(f"{ONG}/Legal/will.pdf", f"{FAMILY}/will.pdf")
    fake_archive.add(f"{ONG}/2026_Plan.xlsx", drive_id="id-plan")
    app.scan()
    return fake_archive


# --- entries() ---------------------------------------------------------------------


def test_entries_classify_the_demo_ongoing(app, demo, tmp_path):
    (ongoing(demo) / ".DS_Store").write_bytes(FINDER)  # housekeeping: not listed
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.symlink(elsewhere, ongoing(demo) / "Outside")
    demo.link(f"{ONG}/Gone", "Home/gone")
    demo.add(f"{FAMILY}/a.pdf", drive_id="id-a")
    app.scan()
    sauna = app.collections.create("Sauna")
    app.collections.add_members(sauna.id, ["id-a"])  # the publisher makes ##. Ongoing/Sauna
    # (the drive ids to open each entry with are pinned in test_entries_carry_drive_ids)
    listed = app.convert.entries()
    # real files at any depth (a link is 0): Legal has contract, letter and Deed/deed
    assert {e.rel: e.real_files for e in listed if e.real_files} == {
        f"{ONG}/2026_Plan.xlsx": 1,
        f"{ONG}/Legal": 3,
    }
    bare = [
        dataclasses.replace(e, drive_id=None, is_dir=False, items=[], real_files=0) for e in listed
    ]
    assert bare == [
        Entry(f"{ONG}/2026_Plan.xlsx", "file", None, False, "2026_Plan"),
        Entry(
            f"{ONG}/Gone",
            "link",
            "Home/gone",
            False,
            "Gone",
            problem="it is broken: Home/gone does not exist",
        ),
        Entry(
            f"{ONG}/Legal",
            "folder",
            None,
            False,
            "Legal",
            ["Deed", "contract.pdf", "letter.pdf", "will.pdf"],
        ),
        Entry(
            f"{ONG}/Outside",
            "link",
            None,
            False,
            "Outside",
            problem=f"it points outside the archive ({elsewhere})",
        ),
        Entry(
            f"{ONG}/Sauna",
            "folder",
            None,
            True,
            "Sauna",
            ["a.pdf"],
            collection_id=sauna.id,
            collection_name="Sauna",
        ),
        Entry(f"{ONG}/Tax 2025.pdf", "link", f"{TAXES}/2025.pdf", False, "Tax 2025"),
        Entry(f"{ONG}/Tilly", "link", f"{FAMILY}/Tilly", False, "Tilly"),
    ]


def test_entries_carry_drive_ids(app, demo, tmp_path):
    """Each entry, and each item listed inside a folder entry, carries the drive id to
    Quick Look, open or show it by: a link's is its target's; an unindexed one has none."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.symlink(elsewhere, ongoing(demo) / "Legal" / "Outside")
    (ongoing(demo) / "Legal" / "new.pdf").write_bytes(b"%PDF-1.4")  # not scanned yet
    entries = {e.rel: e for e in app.convert.entries()}
    assert entries[f"{ONG}/2026_Plan.xlsx"].drive_id == "id-plan"
    assert entries[f"{ONG}/Tax 2025.pdf"].drive_id == "id-tax"  # the link's target
    assert entries[f"{ONG}/Tilly"].drive_id == "d-tilly"
    assert entries[f"{ONG}/Tilly"].is_dir and not entries[f"{ONG}/Tax 2025.pdf"].is_dir
    legal = entries[f"{ONG}/Legal"]
    assert legal.drive_id == "d-legal" and legal.is_dir
    assert legal.items == [
        EntryItem("Deed", "d-deed", True),
        EntryItem("Outside", None, False, True),
        EntryItem("contract.pdf", "id-contract", False),
        EntryItem("letter.pdf", "id-letter", False),
        EntryItem("new.pdf", None, False),
        EntryItem("will.pdf", "id-will", False, True),  # the link's target
    ]
    assert legal.contents == [i.name for i in legal.items]


def test_an_unreadable_folder_item_is_flagged_not_dropped(app, demo, monkeypatch):
    import errno

    lstat_fails(monkeypatch, f"{ONG}/Legal/letter.pdf", OSError(errno.EIO, "Input/output error"))
    legal = {e.rel: e for e in app.convert.entries()}[f"{ONG}/Legal"]
    items = {i.name: i for i in legal.items}
    assert items["letter.pdf"] == EntryItem("letter.pdf", None, False, unreadable=True)
    assert items["contract.pdf"] == EntryItem("contract.pdf", "id-contract", False)


def test_entries_api_carries_drive_ids(app, demo):
    with TestClient(create_api(app), base_url="http://127.0.0.1:8765") as client:
        body = {e["rel"]: e for e in client.get("/api/ongoing/entries").json()}
    assert body[f"{ONG}/Tax 2025.pdf"]["drive_id"] == "id-tax"
    legal = body[f"{ONG}/Legal"]
    assert legal["drive_id"] == "d-legal"
    assert legal["items"][0] == {
        "name": "Deed",
        "drive_id": "d-deed",
        "is_dir": True,
        "is_link": False,
        "unreadable": False,
        "marks": [],
    }


def test_unindexed_and_inner_outside_links_are_not_convertible(app, demo, tmp_path):
    demo.add(f"{ONG}/new.pdf", drive_id="id-new")  # not scanned yet
    os.symlink(tmp_path, ongoing(demo) / "Legal" / "away")
    entries = {e.rel: e for e in app.convert.entries()}
    assert (
        entries[f"{ONG}/new.pdf"].problem == f"{ONG}/new.pdf is not in the index yet (scan first)"
    )
    assert entries[f"{ONG}/Legal"].problem == (
        f"the link away: it points outside the archive ({tmp_path})"
    )


# --- links -----------------------------------------------------------------------


def test_link_to_folder_becomes_the_publishers_direct_link(app, demo):
    plan = app.convert.preview(f"{ONG}/Tilly", "Tilly", None)
    assert [(r.kind, r.src, r.dst) for r in plan.ops] == [
        ("unlink_symlink", f"{ONG}/Tilly", f"{ONG}/Tilly"),
        ("symlink", f"{FAMILY}/Tilly", f"{ONG}/Tilly"),
    ]
    assert plan.members == [f"{FAMILY}/Tilly"]
    result = convert(app, f"{ONG}/Tilly", "Tilly", "ignored/for links")
    assert result.batch.failed is None and result.problems == []
    link = ongoing(demo) / "Tilly"
    assert points_at(link, demo, f"{FAMILY}/Tilly")
    c = app.collections.get(result.collection_id)
    assert c.name == "Tilly" and member_ids(app, c.id) == {"d-tilly"}
    assert (c.ongoing_rel, c.ongoing_status) == (f"{ONG}/Tilly", None)
    rows = journal(app, result.batch.batch_id)
    assert [(r.kind, r.state, r.origin) for r in rows] == [
        ("unlink_symlink", "done", "ui"),
        ("symlink", "done", "ui"),
    ]
    rec = [r for r in records(app) if r.rel == f"{ONG}/Tilly"]
    assert len(rec) == 1 and rec[0].collection_id == c.id
    assert (rec[0].st_ino, rec[0].link_value) == (str(os.lstat(link).st_ino), readlink(link))
    assert result.sync is not None and result.sync.batch is None  # nothing left to do
    assert {e.rel: e.managed for e in app.convert.entries()}[f"{ONG}/Tilly"] is True
    assert batch_ids(app)[-1] == result.batch.batch_id


def test_link_to_file_gets_a_folder_of_links(app, demo):
    result = convert(app, f"{ONG}/Tax 2025.pdf", "Tax 2025", None)
    assert result.batch.failed is None
    assert "Tax 2025.pdf" not in listing(ongoing(demo))
    # the shortcut keeps its own name (stars ruling): not the target's "2025.pdf"
    assert listing(ongoing(demo) / "Tax 2025") == ["Tax 2025.pdf"]
    assert points_at(ongoing(demo) / "Tax 2025" / "Tax 2025.pdf", demo, f"{TAXES}/2025.pdf")
    assert member_ids(app, result.collection_id) == {"id-tax"}
    kinds = [r.kind for r in journal(app, result.batch.batch_id)]
    assert kinds == ["unlink_symlink", "mkdir", "symlink"]
    assert (demo.root / TAXES / "2025.pdf").is_file()  # the target is untouched


def test_undo_of_a_link_conversion_puts_the_users_link_back(app, demo):
    result = convert(app, f"{ONG}/Tilly", "Tilly", None)
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None and outcome.follow_up_error is None
    link = ongoing(demo) / "Tilly"
    assert points_at(link, demo, f"{FAMILY}/Tilly")
    assert member_ids(app, result.collection_id) == set()
    # the publisher's record went with it: not reported as "changed outside the app"
    assert [r for r in records(app) if r.rel == f"{ONG}/Tilly"] == []
    assert app.collections.get(result.collection_id).ongoing_status is None


def _reuse_inode_numbers(monkeypatch):
    """Make every entry look like the recorded object (equal dev and ino), as on ext4,
    which hands the inode number of the entry the undo removed straight to the one it
    puts back."""
    monkeypatch.setattr(identity, "same_object", lambda recorded, current: recorded is not None)


def test_undo_of_a_link_conversion_forgets_the_record_when_the_inode_is_reused(
    app, demo, monkeypatch
):
    result = convert(app, f"{ONG}/Tilly", "Tilly", None)
    _reuse_inode_numbers(monkeypatch)
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None and outcome.follow_up_error is None
    assert [r for r in records(app) if r.rel == f"{ONG}/Tilly"] == []
    app.ongoing.sync()  # the user's link is not mistaken for the app's and removed
    assert points_at(ongoing(demo) / "Tilly", demo, f"{FAMILY}/Tilly")
    _assert_clean_after_undo(app, demo, result.collection_id)


@needs_dir_fd
def test_undo_of_a_folder_conversion_forgets_the_record_when_the_inode_is_reused(
    app, demo, monkeypatch
):
    result = convert(app, f"{ONG}/Legal", "Legal", f"{FAMILY}/Legal papers")
    _reuse_inode_numbers(monkeypatch)
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None and outcome.follow_up_error is None
    assert all(not r.rel.startswith(f"{ONG}/Legal") for r in records(app))
    _assert_clean_after_undo(app, demo, result.collection_id)


# --- real folder -------------------------------------------------------------------


@needs_dir_fd
def test_real_folder_moves_its_contents_and_becomes_a_folder_of_links(app, demo):
    (ongoing(demo) / "Legal" / ".DS_Store").write_bytes(FINDER)  # genuine Finder cache
    dest = f"{FAMILY}/Legal papers"  # created (below an existing top-level folder)
    plan = app.convert.preview(f"{ONG}/Legal", "Legal", dest)
    assert [(r.kind, r.dst) for r in plan.ops] == [
        ("mkdir", dest),
        ("move", f"{dest}/Deed"),
        ("move", f"{dest}/contract.pdf"),
        ("move", f"{dest}/letter.pdf"),
        ("unlink_symlink", f"{ONG}/Legal/will.pdf"),
        ("remove_empty_dir", f"{ONG}/Legal"),
        ("mkdir", f"{ONG}/Legal"),
        ("symlink", f"{ONG}/Legal/Deed"),
        ("symlink", f"{ONG}/Legal/contract.pdf"),
        ("symlink", f"{ONG}/Legal/letter.pdf"),
        ("symlink", f"{ONG}/Legal/will.pdf"),
    ]
    assert plan.members == [
        f"{dest}/Deed",
        f"{dest}/contract.pdf",
        f"{dest}/letter.pdf",
        f"{FAMILY}/will.pdf",
    ]
    assert plan.notes == []
    result = convert(app, f"{ONG}/Legal", "Legal", dest)
    assert result.batch.failed is None and result.problems == []
    assert listing(demo.root / dest) == ["Deed", "contract.pdf", "letter.pdf"]
    assert listing(demo.root / dest / "Deed") == ["deed.pdf"]
    base = ongoing(demo) / "Legal"
    assert base.is_dir() and not base.is_symlink()
    assert listing(base) == ["Deed", "contract.pdf", "letter.pdf", "will.pdf"]
    assert points_at(base / "contract.pdf", demo, f"{dest}/contract.pdf")
    assert points_at(base / "Deed", demo, f"{dest}/Deed")
    assert points_at(base / "will.pdf", demo, f"{FAMILY}/will.pdf")
    # members by Drive ID after the move (never the destination folder itself)
    assert member_ids(app, result.collection_id) == {
        "d-deed",
        "id-contract",
        "id-letter",
        "id-will",
    }
    assert app.repo.get("id-contract").path == f"{dest}/contract.pdf"
    c = app.collections.get(result.collection_id)
    assert (c.ongoing_rel, c.ongoing_status) == (f"{ONG}/Legal", None)
    owned = {r.rel for r in records(app) if r.collection_id == c.id}
    assert owned == {f"{ONG}/Legal", *(f"{ONG}/Legal/{n}" for n in listing(base))}
    assert {r.origin for r in journal(app, result.batch.batch_id)} == {"ui"}
    assert result.sync.batch is None


def test_undo_of_a_folder_conversion_restores_the_folder_and_its_files(app, demo):
    dest = f"{FAMILY}/Legal papers"
    result = convert(app, f"{ONG}/Legal", "Legal", dest)
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None and outcome.follow_up_error is None
    base = ongoing(demo) / "Legal"
    assert base.is_dir() and not base.is_symlink()
    assert listing(base) == ["Deed", "contract.pdf", "letter.pdf", "will.pdf"]
    assert listing(base / "Deed") == ["deed.pdf"]
    assert points_at(base / "will.pdf", demo, f"{FAMILY}/will.pdf")
    assert listing(demo.root / dest) == []  # created folders stay (Phase 1 rule)
    assert app.repo.get("id-contract").path == f"{ONG}/Legal/contract.pdf"
    assert member_ids(app, result.collection_id) == set()
    assert {r.state for r in journal(app, result.batch.batch_id)} == {"undone"}
    c = app.collections.get(result.collection_id)
    assert (c.ongoing_rel, c.ongoing_status) == (None, None)
    assert listing(ongoing(demo)) == DEMO_ONGOING
    # nothing of the collection is in the user's folder any more
    assert all(r.rel != f"{ONG}/Legal" for r in records(app))


def test_undo_preview_of_a_folder_conversion_is_what_undo_applies(app, demo, monkeypatch):
    result = convert(app, f"{ONG}/Legal", "Legal", f"{FAMILY}/Legal papers")
    held = []
    real = app.executor.preview_undo

    def checking(batch_id):
        held.append(app.ongoing.sync_lock.locked())
        return real(batch_id)

    monkeypatch.setattr(app.executor, "preview_undo", checking)
    ids = batch_ids(app)
    preview = app.activity.preview_undo(result.batch.batch_id)
    assert held == [True]  # planned under the sync lock, as undo plans
    assert batch_ids(app) == ids  # nothing journaled
    assert (ongoing(demo) / "Legal").is_dir()
    # the app's folder that replaced the user's is removed, then the user's put back
    kinds = [op.kind for op in preview]
    assert OpKind.REMOVE_EMPTY_DIR in kinds and OpKind.MKDIR in kinds
    assert kinds.index(OpKind.REMOVE_EMPTY_DIR) < kinds.index(OpKind.MKDIR)
    removed = next(op for op in preview if op.kind is OpKind.REMOVE_EMPTY_DIR)
    assert removed.dst == f"{ONG}/Legal"
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None
    assert outcome.batch.done == preview


def test_undo_preview_refuses_an_automatic_sync(app, demo):
    kids = app.collections.create("Kids")
    app.collections.add_members(kids.id, ["d-tilly"])  # the sync links Kids -> Tilly
    sync = batch_ids(app)[-1]
    assert {r.origin for r in journal(app, sync)} == {"workflow"}
    with pytest.raises(OpFailed, match="automatic Ongoing update"):
        app.activity.preview_undo(sync)


def test_undo_is_refused_while_the_apps_folder_holds_user_content(app, demo):
    result = convert(app, f"{ONG}/Legal", "Legal", f"{FAMILY}/Legal papers")
    mine = demo.add(f"{ONG}/Legal/mine.txt", content=b"mine", drive_id="user-1")
    with pytest.raises(GuardError, match="not empty") as refused:
        app.activity.undo(result.batch.batch_id)
    assert str(refused.value).endswith(
        " — undo the later changes to this collection first"
        " (or move out what was added to the folder)"
    )
    assert mine.read_bytes() == b"mine"  # nothing was touched
    assert listing(demo.root / FAMILY / "Legal papers") == ["Deed", "contract.pdf", "letter.pdf"]
    assert {r.state for r in journal(app, result.batch.batch_id)} == {"done"}


def test_failed_move_removes_nothing(app, demo, monkeypatch):
    real = primitives.rename_excl

    def failing(src, dst):
        if Path(src).name == "letter.pdf":
            raise OSError(5, "Input/output error", str(src))
        return real(src, dst)

    monkeypatch.setattr(primitives, "rename_excl", failing)
    dest = f"{FAMILY}/Legal papers"
    result = convert(app, f"{ONG}/Legal", "Legal", dest)
    assert result.batch.failed is not None and result.batch.failed.kind == "move"
    assert any(p.startswith("The conversion stopped at") for p in result.problems)
    base = ongoing(demo) / "Legal"
    assert base.is_dir() and not base.is_symlink()  # the original folder is intact
    assert listing(base) == ["letter.pdf", "will.pdf"]
    assert (base / "will.pdf").is_symlink()
    kinds = [(r.kind, r.state) for r in journal(app, result.batch.batch_id)]
    assert kinds == [
        ("mkdir", "done"),
        ("move", "done"),
        ("move", "done"),
        ("move", "failed"),
    ]
    # what moved is a member (undo takes it back out)
    assert member_ids(app, result.collection_id) == {"d-deed", "id-contract"}
    monkeypatch.setattr(primitives, "rename_excl", real)
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None
    assert listing(base) == ["Deed", "contract.pdf", "letter.pdf", "will.pdf"]
    assert member_ids(app, result.collection_id) == set()


@needs_dir_fd
def test_folder_with_drive_ds_store_stays_and_publisher_uses_suffix(app, demo):
    ds = ongoing(demo) / "Legal" / ".DS_Store"
    ds.write_bytes(FINDER)
    xattr.setxattr(ds, DRIVE_ID_XATTR, b"drive-ds")
    dest = f"{FAMILY}/Legal papers"
    plan = app.convert.preview(f"{ONG}/Legal", "Legal", dest)
    reason = f"{NOT_REMOVED}.DS_Store is a Google Drive item"
    assert reason in plan.notes
    assert "remove_empty_dir" not in [r.kind for r in plan.ops]
    result = convert(app, f"{ONG}/Legal", "Legal", dest)
    assert result.batch.failed is None
    assert reason in result.problems
    assert listing(ongoing(demo) / "Legal") == [".DS_Store"]  # left in place
    assert listing(ongoing(demo) / "Legal_2") == ["Deed", "contract.pdf", "letter.pdf", "will.pdf"]
    c = app.collections.get(result.collection_id)
    assert c.ongoing_rel == f"{ONG}/Legal_2"
    assert len(c.members) == 4
    assert result.sync.batch is None


def test_folder_with_an_outside_inner_link_is_refused_whole(app, demo, tmp_path):
    os.symlink(tmp_path, ongoing(demo) / "Legal" / "away")
    with pytest.raises(InvalidRequest, match="points outside the archive"):
        app.convert.apply(f"{ONG}/Legal", "Legal", f"{FAMILY}/Legal papers", "x")
    assert listing(ongoing(demo) / "Legal") == [
        "Deed",
        "away",
        "contract.pdf",
        "letter.pdf",
        "will.pdf",
    ]
    assert batch_ids(app) == [] and app.collections.by_name("Legal") is None


# --- real file -----------------------------------------------------------------------


def test_real_file_into_an_existing_collection_with_collision(app, demo):
    demo.add(f"{FAMILY}/a.pdf", drive_id="id-a")
    demo.add(f"{FAMILY}/2026_Plan.xlsx", content=b"older", drive_id="id-older")
    app.scan()
    plans = app.collections.create("Plans")
    app.collections.add_members(plans.id, ["id-a", "id-tax"])
    plan = app.convert.preview(f"{ONG}/2026_Plan.xlsx", "plans", FAMILY)
    assert [(r.kind, r.dst) for r in plan.ops] == [
        ("move", f"{FAMILY}/2026_Plan_2.xlsx"),
        ("symlink", f"{ONG}/Plans/2026_Plan_2.xlsx"),
    ]
    assert plan.notes == [
        f"{ONG}/2026_Plan.xlsx will be {FAMILY}/2026_Plan_2.xlsx:"
        " 2026_Plan.xlsx is already taken there"
    ]
    result = convert(app, f"{ONG}/2026_Plan.xlsx", "plans", FAMILY)
    assert result.collection_id == plans.id and result.batch.failed is None
    assert (demo.root / FAMILY / "2026_Plan.xlsx").read_bytes() == b"older"
    assert app.repo.get("id-plan").path == f"{FAMILY}/2026_Plan_2.xlsx"
    assert listing(ongoing(demo) / "Plans") == ["2025.pdf", "2026_Plan_2.xlsx", "a.pdf"]
    assert member_ids(app, plans.id) == {"id-a", "id-tax", "id-plan"}
    assert result.sync.batch is None
    # undo removes only the membership the conversion added
    app.activity.undo(result.batch.batch_id)
    assert (ongoing(demo) / "2026_Plan.xlsx").is_file()
    assert member_ids(app, plans.id) == {"id-a", "id-tax"}
    assert listing(ongoing(demo) / "Plans") == ["2025.pdf", "a.pdf"]


def test_layout_switch_of_an_existing_collection_is_left_to_the_sync(app, demo):
    tilly = app.collections.create("Kids")
    app.collections.add_members(tilly.id, ["d-tilly"])  # a direct link Kids -> Tilly
    assert (ongoing(demo) / "Kids").is_symlink()
    result = convert(app, f"{ONG}/2026_Plan.xlsx", "Kids", FAMILY)
    assert [r.kind for r in journal(app, result.batch.batch_id)] == ["move"]
    assert result.sync.batch is not None  # the switch, origin "workflow"
    assert {r.origin for r in journal(app, result.sync.batch.batch_id)} == {"workflow"}
    assert listing(ongoing(demo) / "Kids") == ["2026_Plan.xlsx", "Tilly"]
    # undoing the conversion: the sync that follows switches back
    app.activity.undo(result.batch.batch_id)
    assert points_at(ongoing(demo) / "Kids", demo, f"{FAMILY}/Tilly")
    assert (ongoing(demo) / "2026_Plan.xlsx").is_file()


# --- refusals and validation ---------------------------------------------------------


def test_managed_entries_are_refused(app, demo):
    first = convert(app, f"{ONG}/Tilly", "Tilly", None)
    assert first.batch.failed is None
    with pytest.raises(InvalidRequest, match="already a collection"):
        app.convert.preview(f"{ONG}/Tilly", "Other", None)


@pytest.mark.parametrize(
    ("destination", "message"),
    [
        (None, "Choose the archive folder"),
        ("", "Choose the archive folder"),
        (f"{ONG}/Somewhere", "inside ##. Ongoing"),
        ("##. To Delete/x", "inside ##. To Delete"),
        ("##. Organize", "inside ##. Organize"),
        ("99. New top", "new top-level folder"),
        (f"{TAXES}/2025.pdf", "is not a folder"),
        ("../outside", "not a usable destination"),
    ],
)
def test_destination_is_validated_before_anything_moves(app, demo, destination, message):
    with pytest.raises(InvalidRequest, match=message):
        app.convert.apply(f"{ONG}/2026_Plan.xlsx", "Plan", destination, "x")
    assert (ongoing(demo) / "2026_Plan.xlsx").is_file()
    assert batch_ids(app) == []


def test_broken_and_outside_links_and_odd_requests_are_refused(app, demo, tmp_path):
    demo.link(f"{ONG}/Gone", "Home/gone")
    os.symlink(tmp_path, ongoing(demo) / "Outside")
    with pytest.raises(InvalidRequest, match="broken"):
        app.convert.preview(f"{ONG}/Gone", "Gone", None)
    with pytest.raises(InvalidRequest, match="outside the archive"):
        app.convert.preview(f"{ONG}/Outside", "Outside", None)
    with pytest.raises(InvalidRequest, match="directly in"):
        app.convert.preview(f"{ONG}/Legal/contract.pdf", "X", FAMILY)
    with pytest.raises(InvalidRequest, match="A collection needs a name"):
        app.convert.preview(f"{ONG}/Tilly", "  ", None)
    closed = app.collections.create("Closed")
    app.collections.close(closed.id)
    with pytest.raises(InvalidRequest, match="closed"):
        app.convert.preview(f"{ONG}/Tilly", "Closed", None)


def test_apply_replans_from_the_current_disk(app, demo):
    plan = app.convert.preview(f"{ONG}/Legal", "Legal", FAMILY)
    demo.link(f"{ONG}/Legal/gone.pdf", "Home/gone.pdf")  # changed after the preview
    with pytest.raises(InvalidRequest, match="broken"):
        app.convert.apply(f"{ONG}/Legal", "Legal", FAMILY, plan.fingerprint)
    assert batch_ids(app) == []
    assert (ongoing(demo) / "Legal" / "contract.pdf").is_file()


# --- fix round 1 -------------------------------------------------------------------------

DEMO_ONGOING = ["2026_Plan.xlsx", "Legal", "Tax 2025.pdf", "Tilly"]


def test_undo_leaves_no_empty_collection_folder_behind(app, demo):
    # review probe A: the emptied collection is not published (no Legal_2, no Tilly_2)
    for rel, name, dest in [
        (f"{ONG}/Legal", "Legal", f"{FAMILY}/LP"),
        (f"{ONG}/Tilly", "Tilly", None),
    ]:
        result = convert(app, rel, name, dest)
        app.activity.undo(result.batch.batch_id)
        c = app.collections.get(result.collection_id)
        assert (c.ongoing_rel, c.ongoing_status) == (None, None)
    assert listing(ongoing(demo)) == DEMO_ONGOING


def test_empty_real_folder_is_refused(app, demo):
    # review probe D
    (ongoing(demo) / "Empty").mkdir()
    (ongoing(demo) / "Empty" / ".DS_Store").write_bytes(FINDER)
    with pytest.raises(InvalidRequest, match="The folder is empty, so there is nothing to convert"):
        app.convert.preview(f"{ONG}/Empty", "Empty", FAMILY)
    assert batch_ids(app) == [] and (ongoing(demo) / "Empty").is_dir()


def test_deep_links_are_unlinked_inside_ongoing_and_never_moved(app, demo):
    # review probe B: no symlink ever moves into the archive proper
    demo.link(f"{ONG}/Legal/Deed/will copy", f"{FAMILY}/will.pdf")
    demo.link(f"{ONG}/Legal/Deed/Old/tax", f"{TAXES}/2025.pdf")
    app.scan()
    plan = app.convert.preview(f"{ONG}/Legal", "Legal", f"{FAMILY}/LP")
    kinds = [(r.kind, r.src) for r in plan.ops]
    first_move = next(i for i, (k, _) in enumerate(kinds) if k == "move")
    deep = [i for i, (k, s) in enumerate(kinds) if k == "unlink_symlink" and "/Deed/" in s]
    assert len(deep) == 2 and max(deep) < first_move
    result = app.convert.apply(f"{ONG}/Legal", "Legal", f"{FAMILY}/LP", plan.fingerprint)
    assert result.batch.failed is None
    links_in_archive = [p for p in (demo.root / FAMILY / "LP").rglob("*") if p.is_symlink()]
    assert links_in_archive == []
    assert {"id-will", "id-tax"} <= member_ids(app, result.collection_id)
    # one member and one link for the will, even though two links pointed at it
    # (named after the file, as one of the two was); "tax" keeps its own name
    assert listing(ongoing(demo) / "Legal") == [
        "Deed",
        "contract.pdf",
        "letter.pdf",
        "tax",
        "will.pdf",
    ]


@pytest.mark.parametrize("kind", ["outside", "broken"])
def test_bad_deep_link_refuses_the_whole_folder(app, demo, tmp_path, kind):
    deep = ongoing(demo) / "Legal" / "Deed" / "x"
    if kind == "outside":
        os.symlink(tmp_path, deep)
    else:
        demo.link(f"{ONG}/Legal/Deed/x", "Home/gone")
    entry = {e.rel: e for e in app.convert.entries()}[f"{ONG}/Legal"]
    assert entry.problem is not None and "Deed/x" in entry.problem
    with pytest.raises(InvalidRequest, match="cannot be converted"):
        app.convert.preview(f"{ONG}/Legal", "Legal", f"{FAMILY}/LP")
    assert batch_ids(app) == []


def test_apply_refuses_what_was_not_previewed(app, demo):
    # review probe C
    plan = app.convert.preview(f"{ONG}/Legal", "Legal", f"{FAMILY}/LP")
    again = app.convert.preview(f"{ONG}/Legal", "Legal", f"{FAMILY}/LP")
    assert plan.fingerprint == again.fingerprint  # stable
    demo.add(f"{ONG}/Legal/late.pdf", drive_id="id-late")
    app.scan()
    with pytest.raises(InvalidRequest, match="Something changed since the preview"):
        app.convert.apply(f"{ONG}/Legal", "Legal", f"{FAMILY}/LP", plan.fingerprint)
    assert batch_ids(app) == []
    assert (ongoing(demo) / "Legal" / "late.pdf").is_file()
    with pytest.raises(InvalidRequest, match="Something changed since the preview"):
        app.convert.apply(f"{ONG}/Legal", "Other name", f"{FAMILY}/LP", plan.fingerprint)


def test_two_links_to_one_target_are_one_member(app, demo):
    # review probe E
    demo.link(f"{ONG}/Legal/will-again.pdf", f"{FAMILY}/will.pdf")
    plan = app.convert.preview(f"{ONG}/Legal", "Legal", f"{FAMILY}/LP")
    assert plan.members.count(f"{FAMILY}/will.pdf") == 1
    result = app.convert.apply(f"{ONG}/Legal", "Legal", f"{FAMILY}/LP", plan.fingerprint)
    assert listing(ongoing(demo) / "Legal") == ["Deed", "contract.pdf", "letter.pdf", "will.pdf"]
    assert result.sync.batch is None
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None
    assert "will-again.pdf" in listing(ongoing(demo) / "Legal")


def test_link_to_quarantined_or_missing_target_is_refused(app, demo, tmp_path):
    # review probes J / J2
    demo.add("##. To Delete/old.pdf", drive_id="id-old")
    demo.link(f"{ONG}/Old.pdf", "##. To Delete/old.pdf")
    app.scan()
    with pytest.raises(InvalidRequest, match="marked for deletion"):
        app.convert.preview(f"{ONG}/Old.pdf", "Old", None)
    os.rename(demo.root / TAXES / "2025.pdf", tmp_path / "away.pdf")
    app.scan()  # the index now says missing
    os.rename(tmp_path / "away.pdf", demo.root / TAXES / "2025.pdf")  # back, not rescanned
    with pytest.raises(InvalidRequest, match="missing"):
        app.convert.preview(f"{ONG}/Tax 2025.pdf", "Tax", None)
    assert batch_ids(app) == []


def test_a_sync_removing_what_the_batch_created_is_reported(app, demo, monkeypatch):
    real = app.ongoing.sync

    def unlinking_sync(dry_run=False):
        result = real(dry_run)
        result.batch = BatchResult(
            "fake",
            False,
            done=[ResolvedOp(OpKind.UNLINK_SYMLINK, f"{ONG}/Tilly", f"{ONG}/Tilly")],
        )
        return result

    monkeypatch.setattr(app.ongoing, "sync", unlinking_sync)
    result = convert(app, f"{ONG}/Tilly", "Tilly", None)
    assert any("removed" in p and f"{ONG}/Tilly" in p for p in result.problems)


def test_destination_under_important_is_allowed(app, demo):
    plan = app.convert.preview(f"{ONG}/2026_Plan.xlsx", "Plan", "##. Important/x")
    assert ("move", "##. Important/x/2026_Plan.xlsx") in [(r.kind, r.dst) for r in plan.ops]
    result = app.convert.apply(f"{ONG}/2026_Plan.xlsx", "Plan", "##. Important/x", plan.fingerprint)
    assert result.batch.failed is None
    assert (demo.root / "##. Important" / "x" / "2026_Plan.xlsx").is_file()


def test_undo_refused_when_the_user_replaced_the_apps_folder(app, demo, tmp_path):
    result = convert(app, f"{ONG}/Legal", "Legal", f"{FAMILY}/LP")
    base = ongoing(demo) / "Legal"
    links = {n: readlink(base / n) for n in listing(base)}
    os.rename(base, tmp_path / "apps-folder")  # the user swaps in a folder of their own
    base.mkdir()
    for n, value in links.items():
        os.symlink(value, base / n)  # with identical links
    ino = os.lstat(base).st_ino
    with pytest.raises(OpFailed, match="cannot be undone"):
        app.activity.undo(result.batch.batch_id)
    assert os.lstat(base).st_ino == ino and listing(base) == sorted(links)


def test_in_ongoing_ops_are_not_throttled(app, fake_archive, monkeypatch):
    folder(fake_archive, f"{ONG}/Many", "d-many")
    for i in range(50):
        fake_archive.add(f"{ONG}/Many/f{i:02}.pdf", drive_id=f"id-{i}")
    app.scan()
    sleeps = []
    monkeypatch.setattr(executor_module.time, "sleep", sleeps.append)
    app.executor.throttle_ms = 5
    result = convert(app, f"{ONG}/Many", "Many", "10. Financial/Many")
    assert result.batch.failed is None
    outside = [r for r in result.batch.done if not r.dst.startswith(f"{ONG}/")]
    inside = [r for r in result.batch.done if r.dst.startswith(f"{ONG}/")]
    # N = 51 outside (the destination MKDIR + 50 MOVEs), M = 52 inside (REMOVE_EMPTY_DIR,
    # MKDIR, 50 SYMLINKs). Rule: a sleep before every outside op except the batch's first.
    assert (len(outside), len(inside)) == (51, 52)
    assert result.batch.done[0] in outside
    assert len(sleeps) == len(outside) - 1


def test_errors_after_the_batch_are_reported_not_raised(app, demo, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(app.ongoing, "record_layout", broken)
    synced = []
    real = app.ongoing.sync
    monkeypatch.setattr(app.ongoing, "sync", lambda dry_run=False: synced.append(1) or real())
    result = convert(app, f"{ONG}/Tilly", "Tilly", None)
    assert result.batch.failed is None and result.batch.done
    assert any("could not be saved" in p for p in result.problems)
    assert synced


@pytest.mark.parametrize(
    "rel", [f"{ONG}/..", f"{ONG}/../{FAMILY}", f"{ONG}/.", f"{ONG}/", "", f"{ONG}/a\0b"]
)
def test_bad_rels_are_invalid_requests(app, demo, rel):
    with pytest.raises(InvalidRequest):
        app.convert.preview(rel, "X", f"{FAMILY}/LP")


def test_case_variant_rel_uses_the_disk_spelling(app, demo):
    plan = app.convert.preview(f"{ONG}/legal", "Legal", f"{FAMILY}/LP")
    assert ("remove_empty_dir", f"{ONG}/Legal") in [(r.kind, r.src) for r in plan.ops]


def test_undo_cleanup_runs_under_the_sync_lock(app, demo, monkeypatch):
    result = convert(app, f"{ONG}/Tilly", "Tilly", None)
    held = []
    real = app.ongoing.forget_undone

    def checking(batch_id):
        held.append(app.ongoing.sync_lock.locked())
        return real(batch_id)

    monkeypatch.setattr(app.ongoing, "forget_undone", checking)
    app.activity.undo(result.batch.batch_id)
    assert held == [True]


def test_relative_user_link_is_noted(app, demo):
    os.unlink(ongoing(demo) / "Tilly")
    os.symlink(f"../{FAMILY}/Tilly", ongoing(demo) / "Tilly")
    plan = app.convert.preview(f"{ONG}/Tilly", "Tilly", None)
    assert f"{ONG}/Tilly is a relative link: after undo the link will be absolute" in plan.notes


def test_undo_after_a_collection_change_says_why(app, demo):
    # review probe L
    result = convert(app, f"{ONG}/Legal", "Legal", f"{FAMILY}/LP")
    app.collections.set_name(result.collection_id, "Legal stuff")
    with pytest.raises(OpFailed, match="The collection changed after the conversion"):
        app.activity.undo(result.batch.batch_id)


# --- fix round 2 -------------------------------------------------------------------------


def _start_sync(app, started: list):
    """Start a sync in another thread (as the watcher would); record whether it is
    still blocked a moment later."""
    t = threading.Thread(target=app.ongoing.sync)
    t.start()
    t.join(0.3)
    started.append((t, t.is_alive()))


def _assert_clean_after_undo(app, demo, collection_id):
    c = app.collections.get(collection_id)
    assert (c.ongoing_rel, c.ongoing_status) == (None, None)
    assert listing(ongoing(demo)) == DEMO_ONGOING
    assert app.ongoing.sync().batch is None


def test_sync_during_a_throttled_undo_move_waits_for_the_undo(app, demo, monkeypatch):
    # review probe R
    result = convert(app, f"{ONG}/Legal", "Legal", f"{FAMILY}/LP")
    app.executor.throttle_ms = 1
    started: list = []

    def sleep(_s):
        if not started:
            _start_sync(app, started)

    monkeypatch.setattr(executor_module.time, "sleep", sleep)
    outcome = app.activity.undo(result.batch.batch_id)
    assert started and started[0][1] is True  # the injected sync was blocked
    started[0][0].join(10)
    assert outcome.batch.failed is None and outcome.follow_up_error is None
    assert listing(ongoing(demo) / "Legal") == ["Deed", "contract.pdf", "letter.pdf", "will.pdf"]
    _assert_clean_after_undo(app, demo, result.collection_id)


def test_sync_between_the_undos_in_ongoing_ops_waits(app, demo, monkeypatch):
    # review probe R2
    result = convert(app, f"{ONG}/Tilly", "Tilly", None)
    real_run = app.executor._run_op
    started: list = []

    def run_op(seq, rop, origin, res, undo_of, *args):
        if undo_of and seq == 1 and not started:
            _start_sync(app, started)
        return real_run(seq, rop, origin, res, undo_of, *args)

    monkeypatch.setattr(app.executor, "_run_op", run_op)
    outcome = app.activity.undo(result.batch.batch_id)
    assert started and started[0][1] is True
    started[0][0].join(10)
    assert outcome.batch.failed is None
    assert points_at(ongoing(demo) / "Tilly", demo, f"{FAMILY}/Tilly")
    _assert_clean_after_undo(app, demo, result.collection_id)


def test_unrecorded_layout_says_undo_is_no_longer_possible(app, demo, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(app.ongoing, "record_layout", broken)
    result = convert(app, f"{ONG}/Legal", "Legal", f"{FAMILY}/LP")
    assert any(
        p.startswith(
            "The new Ongoing entry could not be saved, so this conversion can no longer be undone."
        )
        for p in result.problems
    )


@posix_permissions
def test_unreadable_subfolder_marks_only_that_entry(app, demo):
    deed = ongoing(demo) / "Legal" / "Deed"
    deed.chmod(0)
    try:
        entries = {e.rel: e for e in app.convert.entries()}
    finally:
        deed.chmod(0o755)
    assert entries[f"{ONG}/Legal"].problem.startswith(f"could not read {ONG}/Legal/Deed: ")
    assert entries[f"{ONG}/Tilly"].problem is None


# --- residual fixes: left-alone entries, unreadable entries, publisher fan-out ----------


def lstat_fails(monkeypatch, suffix: str, exc: OSError) -> None:
    real = os.lstat

    def fake(p, *args, **kwargs):
        if str(p).replace("\\", "/").endswith(suffix):
            raise exc
        return real(p, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", fake)


def replace_with_same_link(path: Path) -> None:
    """A new inode with exactly the same readlink value (as a Drive re-enumeration)."""
    value = readlink(path)
    tmp = path.with_name(path.name + ".tmp")
    os.symlink(value, tmp)
    os.unlink(path)
    os.rename(tmp, path)


def test_a_left_alone_entry_is_never_offered_for_conversion(app, demo):
    convert(app, f"{ONG}/Tilly", "Tilly", None)
    replace_with_same_link(ongoing(demo) / "Tilly")
    assert any("looks different from before" in p for p in app.ongoing.sync().problems)
    [tilly] = [e for e in app.convert.entries() if e.rel == f"{ONG}/Tilly"]
    assert tilly.managed is True
    before = app.today.unmanaged_ongoing()
    assert before == app.convert.unmanaged_count()
    assert f"{ONG}/Tilly" not in [
        e.rel for e in app.convert.entries() if not e.managed and e.problem is None
    ]
    with pytest.raises(InvalidRequest, match="already a collection"):
        app.convert.preview(f"{ONG}/Tilly", "Other", None)


def test_unmanaged_count_does_not_count_a_left_alone_entry(app, fake_archive):
    folder(fake_archive, f"{FAMILY}/Tilly", "d-tilly")
    app.scan()
    c = app.collections.create("Tilly")
    app.collections.add_members(c.id, ["d-tilly"])
    assert app.today.unmanaged_ongoing() == 0
    replace_with_same_link(ongoing(fake_archive) / "Tilly")
    assert app.today.unmanaged_ongoing() == 0


def test_an_unreadable_entry_is_a_problem_row_not_a_failure(app, demo, monkeypatch):
    import errno

    lstat_fails(monkeypatch, f"{ONG}/Tax 2025.pdf", OSError(errno.EIO, "Input/output error"))
    entries = {e.rel: e for e in app.convert.entries()}
    assert len(entries) == 4  # the others are still listed
    tax = entries[f"{ONG}/Tax 2025.pdf"]
    assert tax.problem is not None and "Input/output error" in tax.problem
    assert entries[f"{ONG}/Tilly"].problem is None
    with pytest.raises(InvalidRequest, match="Input/output error"):
        app.convert.preview(f"{ONG}/Tax 2025.pdf", "Taxes", None)
    # one unreadable entry skips only itself in the Today count
    assert app.convert.unmanaged_count() == 3


def test_a_left_alone_collection_refuses_conversion_into_it_cleanly(app, demo):
    convert(app, f"{ONG}/Tilly", "Tilly", None)
    replace_with_same_link(ongoing(demo) / "Tilly")
    with pytest.raises(InvalidRequest, match="looks different from before"):
        app.convert.preview(f"{ONG}/Tax 2025.pdf", "Tilly", None)


def test_convert_syncs_every_registered_publisher(app, demo):
    seen = []

    class Fake:
        id = "fake"

        def sync(self, dry_run=False):
            # outside the conversion's lock: a sync could take it
            assert app.ongoing.sync_lock.acquire(blocking=False)
            app.ongoing.sync_lock.release()
            seen.append("sync")

        def preview_for(self, collection_ids, **changes):
            return []

    app.publishers.register(Fake())
    result = convert(app, f"{ONG}/Tax 2025.pdf", "Taxes", f"{FAMILY}")
    assert "sync" in seen
    assert result.sync is not None and result.sync.problems == []


def test_conversion_into_a_grouped_collection_places_members_ungrouped_at_the_top(app, demo):
    demo.add(f"{FAMILY}/a.pdf", drive_id="id-a")
    app.scan()
    plans = app.collections.create("Plans")
    app.collections.add_members(plans.id, ["id-a"])
    g = old_group(app.engine, plans.id, "Later")  # old data: new groups only in Important
    in_group(app.engine, plans.id, ["id-a"], g)
    app.ongoing.sync()
    assert listing(ongoing(demo) / "Plans") == ["Later"]
    plan = app.convert.preview(f"{ONG}/2026_Plan.xlsx", "Plans", FAMILY)
    assert [(r.kind, r.dst) for r in plan.ops] == [
        ("move", f"{FAMILY}/2026_Plan.xlsx"),
        ("symlink", f"{ONG}/Plans/2026_Plan.xlsx"),
    ]
    result = convert(app, f"{ONG}/2026_Plan.xlsx", "Plans", FAMILY)
    assert result.batch.failed is None and result.sync.batch is None
    assert listing(ongoing(demo) / "Plans") == ["2026_Plan.xlsx", "Later"]
    assert listing(ongoing(demo) / "Plans" / "Later") == ["a.pdf"]
    c = app.collections.get(plans.id)
    assert {m.drive_id: m.group_id for m in c.members} == {"id-a": g, "id-plan": None}
    app.activity.undo(result.batch.batch_id)
    assert listing(ongoing(demo) / "Plans") == ["Later"]
    assert listing(ongoing(demo) / "Plans" / "Later") == ["a.pdf"]
    assert (ongoing(demo) / "2026_Plan.xlsx").is_file()


def test_undo_of_a_conversion_into_a_grouped_collection_removes_its_group_folders(app, demo):
    legal = app.collections.create("Legal")
    g = old_group(app.engine, legal.id, "Later")  # old data: new groups only in Important
    app.ongoing.sync()
    dest = f"{FAMILY}/Legal papers"
    result = convert(app, f"{ONG}/Legal", "Legal", dest)
    assert result.batch.failed is None and result.problems == []
    base = ongoing(demo) / "Legal"
    assert listing(base) == ["Deed", "Later", "contract.pdf", "letter.pdf", "will.pdf"]
    assert listing(base / "Later") == []
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None, outcome.batch.error
    kinds = [r.kind for r in journal(app, outcome.batch.batch_id)]
    assert kinds[:5] == ["unlink_symlink"] * 4 + ["remove_empty_dir"]
    removed = [r.src for r in journal(app, outcome.batch.batch_id) if r.kind == "remove_empty_dir"]
    assert removed == [f"{ONG}/Legal/Later", f"{ONG}/Legal"]  # deepest first
    assert base.is_dir() and not base.is_symlink()
    assert listing(base) == ["Deed", "contract.pdf", "letter.pdf", "will.pdf"]
    assert listing(base / "Deed") == ["deed.pdf"]
    assert {r.state for r in journal(app, result.batch.batch_id)} == {"undone"}
    assert member_ids(app, legal.id) == set()
    assert [x.name for x in app.collections.get(legal.id).groups] == ["Later"]  # groups stay
    assert all(not r.rel.startswith(f"{ONG}/Legal") for r in records(app))
    assert g == app.collections.get(legal.id).groups[0].id


# --- conversion into a child collection (round 2, Task 4) ----------------------------


def test_conversion_into_a_child_collection_and_undo(app, demo):
    houses = app.collections.create("Houses")
    app.collections.add_members(houses.id, ["id-will"])
    kids = app.collections.create("Kids", parent_id=houses.id)  # empty: not published yet
    assert listing(ongoing(demo) / "Houses") == ["will.pdf"]
    plan = app.convert.preview(f"{ONG}/Tilly", "Kids", None)
    assert [(str(r.kind), r.src) for r in plan.ops] == [
        ("unlink_symlink", f"{ONG}/Tilly"),
        ("symlink", f"{FAMILY}/Tilly"),
    ]
    assert plan.ops[-1].dst == f"{ONG}/Houses/Kids"
    result = app.convert.apply(f"{ONG}/Tilly", "Kids", None, plan.fingerprint)
    assert result.batch.failed is None and result.problems == []
    assert result.collection_id == kids.id
    # the child is one direct link inside its parent's folder; the original went
    assert listing(ongoing(demo)) == ["2026_Plan.xlsx", "Houses", "Legal", "Tax 2025.pdf"]
    assert listing(ongoing(demo) / "Houses") == ["Kids", "will.pdf"]
    assert points_at(ongoing(demo) / "Houses" / "Kids", demo, f"{FAMILY}/Tilly")
    c = app.collections.get(kids.id)
    assert (c.ongoing_rel, c.ongoing_status) == (f"{ONG}/Houses/Kids", None)
    assert member_ids(app, kids.id) == {"d-tilly"}
    assert [r.collection_id for r in records(app) if r.rel == f"{ONG}/Houses/Kids"] == [kids.id]
    assert app.ongoing.sync().batch is None
    # undo puts the user's link back and takes the app's link out
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None and outcome.follow_up_error is None
    assert points_at(ongoing(demo) / "Tilly", demo, f"{FAMILY}/Tilly")
    assert member_ids(app, kids.id) == set()
    assert listing(ongoing(demo) / "Houses") == ["will.pdf"]
    c = app.collections.get(kids.id)
    assert (c.ongoing_rel, c.ongoing_status) == (None, None)
    assert listing(ongoing(demo)) == ["2026_Plan.xlsx", "Houses", "Legal", "Tax 2025.pdf", "Tilly"]
    assert [r for r in records(app) if r.collection_id == kids.id] == []
    assert app.collections.get(houses.id).ongoing_rel == f"{ONG}/Houses"
    assert app.ongoing.sync().batch is None


def test_conversion_into_a_child_creates_the_parents_folder_and_undo_clears_it(app, demo):
    estate = app.collections.create("Estate")  # nothing of its own: no folder yet
    kids = app.collections.create("Kids", parent_id=estate.id)
    assert listing(ongoing(demo)) == DEMO_ONGOING
    result = convert(app, f"{ONG}/Legal", "Kids", f"{FAMILY}/LP")
    assert result.batch.failed is None and result.problems == []
    rows = journal(app, result.batch.batch_id)
    assert [r.dst for r in rows if r.kind == "mkdir" and r.dst.startswith(ONG)] == [
        f"{ONG}/Estate",
        f"{ONG}/Estate/Kids",
    ]
    assert {r.origin for r in rows} == {"ui"}
    assert listing(ongoing(demo)) == ["2026_Plan.xlsx", "Estate", "Tax 2025.pdf", "Tilly"]
    assert listing(ongoing(demo) / "Estate") == ["Kids"]
    assert listing(ongoing(demo) / "Estate" / "Kids") == [
        "Deed",
        "contract.pdf",
        "letter.pdf",
        "will.pdf",
    ]
    assert (demo.root / FAMILY / "LP" / "contract.pdf").is_file()
    # both folders are the app's, each recorded for its collection
    assert [r.collection_id for r in records(app) if r.rel == f"{ONG}/Estate"] == [estate.id]
    assert [r.collection_id for r in records(app) if r.rel == f"{ONG}/Estate/Kids"] == [kids.id]
    assert app.collections.get(estate.id).ongoing_rel == f"{ONG}/Estate"
    assert app.collections.get(kids.id).ongoing_rel == f"{ONG}/Estate/Kids"
    assert app.ongoing.sync().batch is None
    # undo: the files go back, the user's folder is recreated, the app's folders go
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None and outcome.follow_up_error is None
    assert listing(ongoing(demo) / "Legal") == ["Deed", "contract.pdf", "letter.pdf", "will.pdf"]
    assert member_ids(app, kids.id) == set()
    _assert_clean_after_undo(app, demo, kids.id)
    _assert_clean_after_undo(app, demo, estate.id)
    assert records(app) == []


def test_conversion_into_a_child_waits_for_a_pending_removal(app, demo):
    houses = app.collections.create("Houses")
    app.collections.add_members(houses.id, ["d-tilly", "id-will"])  # a link named Tilly
    tilly = app.collections.create("Tilly", parent_id=houses.id)  # empty child, same name
    assert listing(ongoing(demo) / "Houses") == ["Tilly", "will.pdf"]
    # the member goes but no sync runs yet: the next sync would unlink Houses/Tilly
    app.collections.on_change = None
    app.collections.remove_member(houses.id, "d-tilly")
    assert points_at(ongoing(demo) / "Houses" / "Tilly", demo, f"{FAMILY}/Tilly")
    # converting the user's link into the child would name its link Houses/Tilly,
    # a name only that pending removal frees: refused up front, nothing planned
    with pytest.raises(InvalidRequest, match="Sync Ongoing first"):
        app.convert.preview(f"{ONG}/Tilly", "Tilly", None)
    app.ongoing.sync()
    assert listing(ongoing(demo) / "Houses") == ["will.pdf"]
    plan = app.convert.preview(f"{ONG}/Tilly", "Tilly", None)
    assert plan.ops[-1].dst == f"{ONG}/Houses/Tilly"
    assert tilly.id == app.collections.by_name("Tilly").id


def test_conversion_into_a_child_of_a_single_link_parent_and_undo(app, demo):
    """Houses is one direct link (its only member is a folder); converting an entry
    into its empty child Kids turns Houses into a folder in the same batch (the
    link goes, the folder comes with Houses' own link and Kids' entry), and the
    undo puts the single link back, owned as before."""
    folder(demo, f"{FAMILY}/Cabin", "d-cabin")
    demo.add(f"{FAMILY}/Cabin/plan.pdf", drive_id="id-plan-cabin")
    app.scan()
    houses = app.collections.create("Houses")
    app.collections.add_members(houses.id, ["d-cabin"])
    kids = app.collections.create("Kids", parent_id=houses.id)  # empty: not published yet
    assert points_at(ongoing(demo) / "Houses", demo, f"{FAMILY}/Cabin")
    before = {(r.collection_id, r.rel, r.link_value) for r in records(app)}
    plan = app.convert.preview(f"{ONG}/Tilly", "Kids", None)
    assert [(str(r.kind), r.src) for r in plan.ops] == [
        ("unlink_symlink", f"{ONG}/Tilly"),
        ("unlink_symlink", f"{ONG}/Houses"),
        ("mkdir", None),
        ("symlink", f"{FAMILY}/Cabin"),
        ("symlink", f"{FAMILY}/Tilly"),
    ]
    assert [r.dst for r in plan.ops[2:]] == [
        f"{ONG}/Houses",
        f"{ONG}/Houses/Cabin",
        f"{ONG}/Houses/Kids",
    ]
    assert "Houses becomes a folder" in " ".join(plan.notes)
    result = app.convert.apply(f"{ONG}/Tilly", "Kids", None, plan.fingerprint)
    assert result.batch.failed is None and result.problems == []
    assert result.collection_id == kids.id
    assert {r.origin for r in journal(app, result.batch.batch_id)} == {"ui"}
    assert listing(ongoing(demo)) == ["2026_Plan.xlsx", "Houses", "Legal", "Tax 2025.pdf"]
    assert listing(ongoing(demo) / "Houses") == ["Cabin", "Kids"]
    assert points_at(ongoing(demo) / "Houses" / "Cabin", demo, f"{FAMILY}/Cabin")
    assert points_at(ongoing(demo) / "Houses" / "Kids", demo, f"{FAMILY}/Tilly")
    # every entry is recorded for its own collection
    assert {(r.collection_id, r.rel) for r in records(app)} == {
        (houses.id, f"{ONG}/Houses"),
        (houses.id, f"{ONG}/Houses/Cabin"),
        (kids.id, f"{ONG}/Houses/Kids"),
    }
    c = app.collections.get(kids.id)
    assert (c.ongoing_rel, c.ongoing_status) == (f"{ONG}/Houses/Kids", None)
    assert app.collections.get(houses.id).ongoing_rel == f"{ONG}/Houses"
    assert app.ongoing.sync().batch is None  # the sync has nothing to add
    # undo: Kids' link and Houses' folder go, Houses' single link and the user's
    # link come back, and Houses owns its link again (the sync is quiet)
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None and outcome.follow_up_error is None
    assert listing(ongoing(demo)) == ["2026_Plan.xlsx", "Houses", "Legal", "Tax 2025.pdf", "Tilly"]
    assert points_at(ongoing(demo) / "Houses", demo, f"{FAMILY}/Cabin")
    assert points_at(ongoing(demo) / "Tilly", demo, f"{FAMILY}/Tilly")
    assert member_ids(app, kids.id) == set()
    assert {(r.collection_id, r.rel, r.link_value) for r in records(app)} == before
    assert app.collections.get(houses.id).ongoing_rel == f"{ONG}/Houses"
    c = app.collections.get(kids.id)
    assert (c.ongoing_rel, c.ongoing_status) == (None, None)
    assert app.ongoing.sync().batch is None
    assert listing(ongoing(demo) / "Tilly") == ["school.pdf"]  # never touched


def test_a_removal_of_another_collection_is_still_refused(app, demo):
    """Only an ancestor's own link-to-folder switch joins the batch; a removal of
    another collection's entry that the sync is waiting for still refuses the
    conversion, as before."""
    folder(demo, f"{FAMILY}/Cabin", "d-cabin")
    demo.add(f"{FAMILY}/Cabin/plan.pdf", drive_id="id-plan-cabin")
    app.scan()
    houses = app.collections.create("Houses")
    app.collections.add_members(houses.id, ["d-cabin", "id-will"])  # a folder
    spa = app.collections.create("Kids", parent_id=houses.id)
    app.collections.add_members(spa.id, ["d-tilly"])  # Houses/Kids -> Tilly
    kids = app.collections.create("Sauna", parent_id=houses.id)  # empty
    assert listing(ongoing(demo) / "Houses") == ["Cabin", "Kids", "will.pdf"]
    app.collections.on_change = None  # the renames are not synced yet
    app.collections.set_name(spa.id, "Spa")  # pending: Houses/Kids is unlinked
    app.collections.set_name(kids.id, "Kids")
    with pytest.raises(InvalidRequest, match="Sync Ongoing first"):
        app.convert.preview(f"{ONG}/Tilly", "Kids", None)
    app.ongoing.sync()
    assert listing(ongoing(demo) / "Houses") == ["Cabin", "Spa", "will.pdf"]
    plan = app.convert.preview(f"{ONG}/Tilly", "Kids", None)
    assert plan.ops[-1].dst == f"{ONG}/Houses/Kids"


def test_conversion_into_a_child_of_a_single_link_child_and_undo(app, demo):
    """The same switch one level down: Houses (a folder) > Mid (one direct link,
    Houses/Mid -> Cabin) > Kids (empty). Mid's link becomes a folder inside Houses'
    folder in the batch; the undo puts Mid's link back, owned again."""
    folder(demo, f"{FAMILY}/Cabin", "d-cabin")
    demo.add(f"{FAMILY}/Cabin/plan.pdf", drive_id="id-plan-cabin")
    app.scan()
    houses = app.collections.create("Houses")
    app.collections.add_members(houses.id, ["id-will"])
    mid = app.collections.create("Mid", parent_id=houses.id)
    app.collections.add_members(mid.id, ["d-cabin"])
    kids = app.collections.create("Kids", parent_id=mid.id)
    assert points_at(ongoing(demo) / "Houses" / "Mid", demo, f"{FAMILY}/Cabin")
    before = {(r.collection_id, r.rel, r.link_value) for r in records(app)}
    plan = app.convert.preview(f"{ONG}/Tilly", "Kids", None)
    assert [(str(r.kind), r.src if r.kind != "mkdir" else r.dst) for r in plan.ops] == [
        ("unlink_symlink", f"{ONG}/Tilly"),
        ("unlink_symlink", f"{ONG}/Houses/Mid"),
        ("mkdir", f"{ONG}/Houses/Mid"),
        ("symlink", f"{FAMILY}/Cabin"),
        ("symlink", f"{FAMILY}/Tilly"),
    ]
    result = app.convert.apply(f"{ONG}/Tilly", "Kids", None, plan.fingerprint)
    assert result.batch.failed is None and result.problems == []
    assert listing(ongoing(demo) / "Houses") == ["Mid", "will.pdf"]
    assert listing(ongoing(demo) / "Houses" / "Mid") == ["Cabin", "Kids"]
    assert {(r.collection_id, r.rel) for r in records(app)} == {
        (houses.id, f"{ONG}/Houses"),
        (houses.id, f"{ONG}/Houses/will.pdf"),
        (mid.id, f"{ONG}/Houses/Mid"),
        (mid.id, f"{ONG}/Houses/Mid/Cabin"),
        (kids.id, f"{ONG}/Houses/Mid/Kids"),
    }
    assert app.ongoing.sync().batch is None
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None and outcome.follow_up_error is None
    assert listing(ongoing(demo) / "Houses") == ["Mid", "will.pdf"]
    assert points_at(ongoing(demo) / "Houses" / "Mid", demo, f"{FAMILY}/Cabin")
    assert points_at(ongoing(demo) / "Tilly", demo, f"{FAMILY}/Tilly")
    assert {(r.collection_id, r.rel, r.link_value) for r in records(app)} == before
    assert app.collections.get(mid.id).ongoing_rel == f"{ONG}/Houses/Mid"
    assert app.ongoing.sync().batch is None


# --- sending the files to the inbox ----------------------------------------------------

INBOX = "##. Organize"


def test_a_folder_can_send_its_files_flat_to_the_inbox_and_undo(app, demo):
    demo.add(f"{INBOX}/deed.pdf", drive_id="id-inbox-deed")  # a clash in the inbox
    app.scan()
    plan = app.convert.preview(f"{ONG}/Legal", "Legal", None, to_inbox=True)
    moves = {r.src: r.dst for r in plan.ops if r.kind == "move"}
    assert moves == {
        f"{ONG}/Legal/Deed/deed.pdf": f"{INBOX}/deed_2.pdf",  # flat, unique name
        f"{ONG}/Legal/contract.pdf": f"{INBOX}/contract.pdf",
        f"{ONG}/Legal/letter.pdf": f"{INBOX}/letter.pdf",
    }
    # the emptied subfolder goes first, then the folder itself
    removals = [r.src for r in plan.ops if r.kind == "remove_empty_dir"]
    assert removals == [f"{ONG}/Legal/Deed", f"{ONG}/Legal"]
    result = app.convert.apply(f"{ONG}/Legal", "Legal", None, plan.fingerprint, to_inbox=True)
    assert result.batch.failed is None and result.problems == []
    assert listing(demo.root / INBOX) == ["contract.pdf", "deed.pdf", "deed_2.pdf", "letter.pdf"]
    # members by drive id, wherever they are now (the will.pdf shortcut's target too)
    assert member_ids(app, result.collection_id) == {
        "id-deed",
        "id-contract",
        "id-letter",
        "id-will",
    }
    assert app.repo.get("id-contract").path == f"{INBOX}/contract.pdf"
    base = ongoing(demo) / "Legal"
    assert points_at(base / "contract.pdf", demo, f"{INBOX}/contract.pdf")
    assert points_at(base / "deed_2.pdf", demo, f"{INBOX}/deed_2.pdf")

    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None and outcome.follow_up_error is None
    assert listing(base) == ["Deed", "contract.pdf", "letter.pdf", "will.pdf"]
    assert listing(base / "Deed") == ["deed.pdf"]
    assert listing(demo.root / INBOX) == ["deed.pdf"]
    assert member_ids(app, result.collection_id) == set()
    assert app.repo.get("id-deed").path == f"{ONG}/Legal/Deed/deed.pdf"


def test_a_real_file_can_go_to_the_inbox(app, demo):
    plan = app.convert.preview(f"{ONG}/2026_Plan.xlsx", "Plan", None, to_inbox=True)
    result = app.convert.apply(
        f"{ONG}/2026_Plan.xlsx", "Plan", None, plan.fingerprint, to_inbox=True
    )
    assert result.batch.failed is None
    assert app.repo.get("id-plan").path == f"{INBOX}/2026_Plan.xlsx"
    assert member_ids(app, result.collection_id) == {"id-plan"}


def test_the_inbox_is_still_no_regular_destination(app, demo):
    with pytest.raises(InvalidRequest, match="cannot be inside"):
        app.convert.preview(f"{ONG}/Legal", "Legal", INBOX)
    with pytest.raises(InvalidRequest, match="cannot be inside"):
        app.convert.preview(f"{ONG}/Legal", "Legal", f"{INBOX}/sub")


def test_the_inbox_mode_works_through_the_api(app, demo):
    base = "http://127.0.0.1:8765"
    body = {"rel": f"{ONG}/Legal", "collection": "Legal", "to_inbox": True}
    with TestClient(create_api(app), base_url=base) as client:
        r = client.post("/api/ongoing/preview", json=body, headers={"Origin": base})
        assert r.status_code == 200
        r = client.post(
            "/api/ongoing/convert",
            json={**body, "fingerprint": r.json()["fingerprint"]},
            headers={"Origin": base},
        )
        assert r.status_code == 200
    assert app.repo.get("id-letter").path == f"{INBOX}/letter.pdf"
