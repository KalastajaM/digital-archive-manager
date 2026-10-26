"""The Ongoing publisher: open collections mirrored as links in ``##. Ongoing``."""

import logging
import os
import threading
import unicodedata
from pathlib import Path

import pytest
import xattr
from sqlalchemy import func, select, update

from conftest import needs_dir_fd, posix_names
from dam.collections.ongoing import _REPLACED, NOT_MANAGED, NOT_SHOWN, Desired, OngoingPublisher
from dam.collections.service import check_name
from dam.core.fs import readlink
from dam.db.engine import write_tx
from dam.db.tables import collection_members, ongoing_entries, operations
from dam.db.tables import collections as collections_table
from dam.index.driveid import DRIVE_ID_XATTR
from dam.ops import identity, primitives
from dam.ops.guards import validate
from dam.ops.model import GuardError, Op, OpFailed, OpKind, Plan
from dam.services.errors import InvalidRequest
from fsswap import recreate_dir

HOLDS_1 = "contains 1 item not created by the app, so it was left as it is."

ONG = "##. Ongoing"
BANKS = "10. Financial/Banks"
FINDER = b"\x00\x00\x00\x01Bud1" + b"\x00" * 24  # Finder's .DS_Store header


# --- helpers -----------------------------------------------------------------------


def folder(fake_archive, rel: str, drive_id: str) -> Path:
    p = fake_archive.root / rel
    p.mkdir(parents=True, exist_ok=True)
    xattr.setxattr(p, DRIVE_ID_XATTR, drive_id.encode())
    return p


def journal(app, batch_id: str | None = None):
    q = select(operations).order_by(operations.c.id)
    if batch_id is not None:
        q = q.where(operations.c.batch_id == batch_id)
    with app.engine.connect() as conn:
        return conn.execute(q).all()


def journal_count(app) -> int:
    with app.engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(operations)).scalar_one()


def batches(app) -> list[str]:
    seen: list[str] = []
    for row in journal(app):
        if row.batch_id not in seen:
            seen.append(row.batch_id)
    return seen


def ongoing(fake_archive) -> Path:
    return fake_archive.root / ONG


def listing(path: Path) -> list[str]:
    return sorted(os.listdir(path))


def points_at(link: Path, fake_archive, rel: str) -> bool:
    return link.is_symlink() and readlink(link) == str(fake_archive.root.resolve() / rel)


@pytest.fixture
def two_files(app, fake_archive):
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="id-a")
    fake_archive.add(f"{BANKS}/b.pdf", drive_id="id-b")
    app.scan()


def sauna(app, members=("id-a", "id-b")):
    c = app.collections.create("Sauna")
    return app.collections.add_members(c.id, list(members))


# --- layouts -----------------------------------------------------------------------


def test_desired_and_plan(app, fake_archive, two_files):
    app.collections.on_change = None
    sauna(app)
    folder(fake_archive, "Home/X", "d-x")
    app.scan()
    x = app.collections.create("X")
    app.collections.add_members(x.id, ["d-x"])
    closed = app.collections.create("Closed")
    app.collections.close(closed.id)
    cols = app.collections.list(None)
    assert app.ongoing.desired(cols) == {
        "Sauna": Desired(
            "folder", f"{ONG}/Sauna", links={"a.pdf": f"{BANKS}/a.pdf", "b.pdf": f"{BANKS}/b.pdf"}
        ),
        "X": Desired("link", f"{ONG}/X", target="Home/X"),
    }
    plan = app.ongoing.sync(dry_run=True).plan
    assert [(op.kind, op.dst) for op in plan] == [
        (OpKind.MKDIR, f"{ONG}/Sauna"),
        (OpKind.SYMLINK, f"{ONG}/Sauna/a.pdf"),
        (OpKind.SYMLINK, f"{ONG}/Sauna/b.pdf"),
        (OpKind.SYMLINK, f"{ONG}/X"),
    ]


def test_publisher_is_registered(app):
    assert app.publishers.get("ongoing") is app.ongoing
    assert isinstance(app.ongoing, OngoingPublisher) and app.ongoing.id == "ongoing"


def test_two_members_get_a_folder_of_links(app, fake_archive, two_files):
    c = sauna(app)
    base = ongoing(fake_archive) / "Sauna"
    assert base.is_dir() and not base.is_symlink()
    assert listing(base) == ["a.pdf", "b.pdf"]
    assert points_at(base / "a.pdf", fake_archive, f"{BANKS}/a.pdf")
    assert points_at(base / "b.pdf", fake_archive, f"{BANKS}/b.pdf")
    c = app.collections.get(c.id)
    assert (c.ongoing_rel, c.ongoing_status) == (f"{ONG}/Sauna", None)
    assert {r.origin for r in journal(app)} == {"workflow"}
    # nothing left to do: the next sync is empty and journals nothing
    before = journal_count(app)
    result = app.ongoing.sync()
    assert (result.plan, result.batch, result.problems) == ([], None, [])
    assert journal_count(app) == before


def test_single_folder_member_is_a_direct_link(app, fake_archive):
    folder(fake_archive, "Home/2026 Sauna", "d-sauna")
    fake_archive.add("Home/2026 Sauna/plan.pdf", drive_id="id-plan")
    app.scan()
    c = sauna(app, ["d-sauna"])
    link = ongoing(fake_archive) / "Sauna"
    assert points_at(link, fake_archive, "Home/2026 Sauna")
    assert app.collections.get(c.id).ongoing_rel == f"{ONG}/Sauna"


def test_a_single_file_member_still_gets_a_folder(app, fake_archive, two_files):
    sauna(app, ["id-a"])
    base = ongoing(fake_archive) / "Sauna"
    assert base.is_dir() and not base.is_symlink()
    assert listing(base) == ["a.pdf"]


def test_member_basename_collision_gets_suffix(app, fake_archive):
    fake_archive.add(f"{BANKS}/plan.pdf", drive_id="id-1")
    fake_archive.add("Home/plan.pdf", drive_id="id-2")
    app.scan()
    sauna(app, ["id-1", "id-2"])
    base = ongoing(fake_archive) / "Sauna"
    assert listing(base) == ["plan.pdf", "plan_2.pdf"]
    assert points_at(base / "plan.pdf", fake_archive, f"{BANKS}/plan.pdf")
    assert points_at(base / "plan_2.pdf", fake_archive, "Home/plan.pdf")


def test_layout_switch_is_one_batch(app, fake_archive, two_files):
    folder(fake_archive, "Home/2026 Sauna", "d-sauna")
    app.scan()
    c = sauna(app, ["d-sauna"])
    assert (ongoing(fake_archive) / "Sauna").is_symlink()
    n_batches = len(batches(app))
    app.collections.add_members(c.id, ["id-a"])
    assert len(batches(app)) == n_batches + 1
    rows = journal(app, batches(app)[-1])
    assert [(r.kind, r.state) for r in rows] == [
        ("unlink_symlink", "done"),
        ("mkdir", "done"),
        ("symlink", "done"),
        ("symlink", "done"),
    ]
    base = ongoing(fake_archive) / "Sauna"
    assert base.is_dir() and not base.is_symlink()
    assert listing(base) == ["2026 Sauna", "a.pdf"]
    # and back: only the folder member left -> a direct link again (one batch)
    app.collections.remove_member(c.id, "id-a")
    assert points_at(base, fake_archive, "Home/2026 Sauna")
    kinds = [r.kind for r in journal(app, batches(app)[-1])]
    assert kinds == ["unlink_symlink", "unlink_symlink", "remove_empty_dir", "symlink"]


# --- Review Focus 1: members move ----------------------------------------------------


def test_renamed_member_link_is_repointed(app, fake_archive, two_files):
    sauna(app)
    os.rename(fake_archive.root / BANKS / "a.pdf", fake_archive.root / BANKS / "a-renamed.pdf")
    app.scan()
    result = app.ongoing.sync()
    assert result.batch is not None and result.batch.failed is None
    base = ongoing(fake_archive) / "Sauna"
    assert listing(base) == ["a-renamed.pdf", "b.pdf"]  # no duplicate, nothing dangling
    assert points_at(base / "a-renamed.pdf", fake_archive, f"{BANKS}/a-renamed.pdf")
    assert all((base / n).exists() for n in listing(base))
    assert app.ongoing.sync().batch is None


def test_moved_member_link_target_is_repointed(app, fake_archive, two_files):
    sauna(app)
    (fake_archive.root / "Home").mkdir()
    os.rename(fake_archive.root / BANKS / "b.pdf", fake_archive.root / "Home" / "b.pdf")
    app.scan()
    app.ongoing.sync()
    base = ongoing(fake_archive) / "Sauna"
    assert listing(base) == ["a.pdf", "b.pdf"]
    assert points_at(base / "b.pdf", fake_archive, "Home/b.pdf")
    rows = journal(app, batches(app)[-1])
    assert [r.kind for r in rows] == ["unlink_symlink", "symlink"]


def test_renamed_folder_member_direct_link_is_repointed(app, fake_archive):
    folder(fake_archive, "Home/Sauna", "d-sauna")
    app.scan()
    sauna(app, ["d-sauna"])
    os.rename(fake_archive.root / "Home/Sauna", fake_archive.root / "Home/2026 Sauna")
    app.scan()
    app.ongoing.sync()
    assert points_at(ongoing(fake_archive) / "Sauna", fake_archive, "Home/2026 Sauna")
    assert listing(ongoing(fake_archive)) == ["Sauna"]


def test_missing_and_quarantined_members_lose_their_link_until_back(
    app, fake_archive, two_files, tmp_path
):
    sauna(app)
    base = ongoing(fake_archive) / "Sauna"
    os.rename(fake_archive.root / BANKS / "a.pdf", tmp_path / "away.pdf")  # gone
    quarantine = fake_archive.root / "##. To Delete" / BANKS
    quarantine.mkdir(parents=True)
    os.rename(fake_archive.root / BANKS / "b.pdf", quarantine / "b.pdf")  # marked for deletion
    app.scan()
    app.ongoing.sync()
    assert not os.path.lexists(base)  # no usable member left: not published at all
    os.rename(tmp_path / "away.pdf", fake_archive.root / BANKS / "a.pdf")
    app.scan()
    app.ongoing.sync()
    assert listing(base) == ["a.pdf"]
    assert points_at(base / "a.pdf", fake_archive, f"{BANKS}/a.pdf")


def test_members_inside_ongoing_are_not_linked(app, fake_archive, two_files):
    fake_archive.add(f"{ONG}/2026_Plan.xlsx", drive_id="id-x")
    app.scan()
    sauna(app, ["id-a", "id-x"])
    assert listing(ongoing(fake_archive) / "Sauna") == ["a.pdf"]


# --- closing, unpublishing, renaming ---------------------------------------------------


@needs_dir_fd
def test_close_removes_links_then_folder_ds_store_tolerated(app, fake_archive, two_files):
    c = sauna(app)
    (ongoing(fake_archive) / "Sauna" / ".DS_Store").write_bytes(FINDER)
    app.collections.close(c.id)
    assert listing(ongoing(fake_archive)) == []
    rows = journal(app, batches(app)[-1])
    assert [r.kind for r in rows] == ["unlink_symlink", "unlink_symlink", "remove_empty_dir"]
    assert {r.state for r in rows} == {"done"}
    c = app.collections.get(c.id)
    assert (c.state, c.ongoing_rel, c.ongoing_status) == ("closed", None, None)
    # reopening publishes again
    app.collections.reopen(c.id)
    assert listing(ongoing(fake_archive) / "Sauna") == ["a.pdf", "b.pdf"]


def test_unpublish_and_republish(app, fake_archive, two_files):
    c = sauna(app)
    app.collections.set_publish(c.id, "ongoing", False)
    assert listing(ongoing(fake_archive)) == []
    assert app.collections.get(c.id).ongoing_rel is None
    app.collections.set_publish(c.id, "ongoing", True)
    assert listing(ongoing(fake_archive) / "Sauna") == ["a.pdf", "b.pdf"]


def test_close_direct_link(app, fake_archive):
    folder(fake_archive, "Home/Sauna", "d-sauna")
    app.scan()
    c = sauna(app, ["d-sauna"])
    app.collections.close(c.id)
    assert listing(ongoing(fake_archive)) == []
    assert (fake_archive.root / "Home/Sauna").is_dir()  # the target is untouched
    assert [r.kind for r in journal(app, batches(app)[-1])] == ["unlink_symlink"]


def test_rename_moves_the_layout_in_one_batch(app, fake_archive, two_files):
    c = sauna(app)
    n = len(batches(app))
    app.collections.set_name(c.id, "Sauna 2026")
    assert len(batches(app)) == n + 1
    assert listing(ongoing(fake_archive)) == ["Sauna 2026"]
    assert listing(ongoing(fake_archive) / "Sauna 2026") == ["a.pdf", "b.pdf"]
    kinds = [r.kind for r in journal(app, batches(app)[-1])]
    assert kinds == [
        "unlink_symlink",
        "unlink_symlink",
        "remove_empty_dir",
        "mkdir",
        "symlink",
        "symlink",
    ]
    assert "move" not in kinds and "rename" not in kinds
    assert app.collections.get(c.id).ongoing_rel == f"{ONG}/Sauna 2026"


def test_case_only_rename_recreates_under_new_spelling(app, fake_archive, two_files):
    c = sauna(app)
    app.collections.set_name(c.id, "sauna")
    assert listing(ongoing(fake_archive)) == ["sauna"]
    assert app.collections.get(c.id).ongoing_rel == f"{ONG}/sauna"


# --- Review Focus 4: the user edits ##. Ongoing --------------------------------------


def test_real_file_at_the_name_gets_suffix_and_is_untouched(app, fake_archive, two_files):
    user = fake_archive.add(f"{ONG}/Sauna", content=b"mine", drive_id="user-1")
    c = sauna(app)
    assert user.is_file() and user.read_bytes() == b"mine"
    assert listing(ongoing(fake_archive) / "Sauna_2") == ["a.pdf", "b.pdf"]
    assert app.collections.get(c.id).ongoing_rel == f"{ONG}/Sauna_2"
    # stable: the suffix is kept, the user file is never touched, close leaves it
    assert app.ongoing.sync().batch is None
    app.collections.close(c.id)
    assert listing(ongoing(fake_archive)) == ["Sauna"]
    assert user.read_bytes() == b"mine"


def test_foreign_folder_and_foreign_link_at_the_name_are_untouched(app, fake_archive, two_files):
    (ongoing(fake_archive) / "Sauna").mkdir()
    fake_archive.add(f"{ONG}/Sauna/own.txt", drive_id="user-1")
    fake_archive.link(f"{ONG}/Sauna_2", "Home")  # a link pointing elsewhere (dangling)
    c = sauna(app)
    assert listing(ongoing(fake_archive)) == ["Sauna", "Sauna_2", "Sauna_3"]
    assert listing(ongoing(fake_archive) / "Sauna") == ["own.txt"]
    assert readlink(ongoing(fake_archive) / "Sauna_2") == str(fake_archive.root / "Home")
    assert app.collections.get(c.id).ongoing_rel == f"{ONG}/Sauna_3"
    app.collections.close(c.id)
    assert listing(ongoing(fake_archive)) == ["Sauna", "Sauna_2"]


def test_existing_link_at_the_name_is_foreign_even_to_the_same_folder(app, fake_archive):
    # Probe P9: a user's own link is never adopted, so a layout switch cannot unlink it.
    folder(fake_archive, "Home/2026 Sauna", "d-sauna")
    user = fake_archive.link(f"{ONG}/Sauna", "Home/2026 Sauna")
    app.scan()
    c = sauna(app, ["d-sauna"])
    assert app.collections.get(c.id).ongoing_rel == f"{ONG}/Sauna_2"
    assert points_at(ongoing(fake_archive) / "Sauna_2", fake_archive, "Home/2026 Sauna")
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="id-a")
    app.scan()
    app.collections.add_members(c.id, ["id-a"])  # layout switch
    app.collections.close(c.id)
    assert listing(ongoing(fake_archive)) == ["Sauna"]
    assert readlink(user) == str(fake_archive.root / "Home/2026 Sauna")


def test_user_file_inside_the_folder_is_kept_and_names_avoid_it(app, fake_archive, two_files):
    c = sauna(app, ["id-a"])
    fake_archive.add(f"{ONG}/Sauna/b.pdf", content=b"mine", drive_id="user-1")
    app.collections.add_members(c.id, ["id-b"])
    base = ongoing(fake_archive) / "Sauna"
    assert listing(base) == ["a.pdf", "b.pdf", "b_2.pdf"]
    assert (base / "b.pdf").read_bytes() == b"mine"
    assert points_at(base / "b_2.pdf", fake_archive, f"{BANKS}/b.pdf")


def test_close_with_user_file_inside_stops_and_reports(app, fake_archive, two_files):
    c = sauna(app)
    user = fake_archive.add(f"{ONG}/Sauna/notes.txt", content=b"mine", drive_id="user-1")
    app.collections.close(c.id)
    base = ongoing(fake_archive) / "Sauna"
    assert listing(base) == ["notes.txt"]  # links gone, the file survives
    assert user.read_bytes() == b"mine"
    rows = journal(app, batches(app)[-1])
    assert [(r.kind, r.state) for r in rows] == [
        ("unlink_symlink", "done"),
        ("unlink_symlink", "done"),
    ]
    c = app.collections.get(c.id)
    assert c.state == "closed"
    assert c.ongoing_rel == f"{ONG}/Sauna"
    assert c.ongoing_status.startswith(NOT_MANAGED) and "1 item" in c.ongoing_status
    # no retry noise: nothing journaled on later syncs while the file is there
    before = journal_count(app)
    assert app.ongoing.sync().batch is None
    assert journal_count(app) == before
    # the user takes the file away: the next sync finishes the job
    os.rename(user, fake_archive.root / BANKS / "notes.txt")
    app.ongoing.sync()
    assert listing(ongoing(fake_archive)) == []
    c = app.collections.get(c.id)
    assert (c.ongoing_rel, c.ongoing_status) == (None, None)


def test_close_with_drive_ds_store_is_not_managed(app, fake_archive, two_files):
    c = sauna(app)
    ds = ongoing(fake_archive) / "Sauna" / ".DS_Store"
    ds.write_bytes(FINDER)
    xattr.setxattr(ds, DRIVE_ID_XATTR, b"drive-ds")
    app.collections.close(c.id)
    assert listing(ongoing(fake_archive) / "Sauna") == [".DS_Store"]
    c = app.collections.get(c.id)
    assert c.ongoing_rel == f"{ONG}/Sauna"
    assert c.ongoing_status.startswith(NOT_MANAGED) and "Finder" in c.ongoing_status


def test_remove_refused_at_act_time_stops_the_batch(app, fake_archive, two_files, monkeypatch):
    c = sauna(app)
    real = primitives.remove_empty_dir

    def racing(path, ongoing_dir, identity=None):
        (path / "late.txt").write_bytes(b"user")  # the user drops a file in, just now
        return real(path, ongoing_dir, identity=identity)

    monkeypatch.setattr(primitives, "remove_empty_dir", racing)
    app.collections.close(c.id)
    base = ongoing(fake_archive) / "Sauna"
    assert listing(base) == ["late.txt"]
    rows = journal(app, batches(app)[-1])
    assert [(r.kind, r.state) for r in rows] == [
        ("unlink_symlink", "done"),
        ("unlink_symlink", "done"),
        ("remove_empty_dir", "failed"),
    ]
    c = app.collections.get(c.id)
    assert c.state == "closed" and c.ongoing_rel == f"{ONG}/Sauna"
    assert c.ongoing_status.startswith(NOT_MANAGED)


def test_foreign_link_inside_the_owned_folder_is_left_alone(app, fake_archive, two_files):
    # Links inside the collection's folder are owned only if the publisher made them.
    c = sauna(app)
    user = fake_archive.link(f"{ONG}/Sauna/extra", f"{BANKS}/a.pdf")
    assert app.ongoing.sync().batch is None
    assert listing(ongoing(fake_archive) / "Sauna") == ["a.pdf", "b.pdf", "extra"]
    app.collections.close(c.id)
    assert listing(ongoing(fake_archive) / "Sauna") == ["extra"]
    assert user.is_symlink()
    c = app.collections.get(c.id)
    assert c.ongoing_rel == f"{ONG}/Sauna" and c.ongoing_status.startswith(NOT_MANAGED)


def test_preview_race_is_reported_and_nothing_runs(app, fake_archive, two_files, monkeypatch):
    app.collections.on_change = None
    c = app.collections.create("Sauna")
    real_apply = app.executor.apply

    def racing(plan, dry_run=False):
        fake_archive.add(f"{ONG}/Sauna", content=b"mine", drive_id="user-1")
        return real_apply(plan, dry_run)

    monkeypatch.setattr(app.executor, "apply", racing)
    app.collections.add_members(c.id, ["id-a"])
    result = app.ongoing.sync()
    assert result.batch is None and result.problems
    assert (ongoing(fake_archive) / "Sauna").read_bytes() == b"mine"
    assert app.collections.get(c.id).ongoing_rel is None
    assert journal_count(app) == 0


# --- ownership by identity ---------------------------------------------------------------


def records(app):
    with app.engine.connect() as conn:
        return conn.execute(select(ongoing_entries).order_by(ongoing_entries.c.rel)).all()


def test_created_entries_are_recorded_with_their_identity(app, fake_archive, two_files):
    c = sauna(app)
    rows = records(app)
    assert [(r.collection_id, r.rel, r.kind) for r in rows] == [
        (c.id, f"{ONG}/Sauna", "folder"),
        (c.id, f"{ONG}/Sauna/a.pdf", "link"),
        (c.id, f"{ONG}/Sauna/b.pdf", "link"),
    ]
    for r in rows:
        assert identity.from_columns(r.st_dev, r.st_ino, r.st_birth) == identity.of_path(
            fake_archive.root / r.rel
        )
    link = rows[1]
    assert link.link_value == readlink(fake_archive.root / link.rel)
    assert rows[0].link_value is None
    app.collections.close(c.id)
    assert records(app) == []


def test_user_recreated_link_at_recorded_rel_is_foreign(app, fake_archive):
    # Probe P7
    folder(fake_archive, "Home/2026 Sauna", "d-sauna")
    (fake_archive.root / "Other").mkdir()
    app.scan()
    c = sauna(app, ["d-sauna"])
    link = ongoing(fake_archive) / "Sauna"
    os.unlink(link)
    os.symlink(fake_archive.root / "Other", link)  # the user's own link, same name
    app.collections.close(c.id)
    assert readlink(link) == str(fake_archive.root / "Other")
    c = app.collections.get(c.id)
    assert c.ongoing_rel is None
    assert (
        c.ongoing_status
        == f"{NOT_MANAGED}{ONG}/Sauna was changed outside the app, so it was left as it is."
    )
    assert records(app) == []
    app.ongoing.sync()  # the explanation stays while the user's entry is there
    assert app.collections.get(c.id).ongoing_status == c.ongoing_status
    os.unlink(link)
    app.ongoing.sync()
    assert app.collections.get(c.id).ongoing_status is None


def test_user_replaced_folder_keeps_their_link_and_file(app, fake_archive, two_files):
    # Probe P2
    c = sauna(app)
    base = ongoing(fake_archive) / "Sauna"
    for n in listing(base):
        os.unlink(base / n)
    recreate_dir(base)  # the user deleted the folder and made another
    os.symlink(fake_archive.root / "10. Financial", base / "my-shortcut")
    (base / "mine.txt").write_text("x", encoding="utf-8")
    before = records(app)
    app.collections.close(c.id)
    assert listing(base) == ["mine.txt", "my-shortcut"]
    # a folder at the recorded rel with a new identity: maybe Drive re-enumerated it,
    # so it is left alone (records kept, never removed, nothing published beside it)
    status = app.collections.get(c.id).ongoing_status
    assert status == NOT_MANAGED + identity_problem(f"{ONG}/Sauna")
    assert records(app) == before
    app.collections.reopen(c.id)
    assert listing(base) == ["mine.txt", "my-shortcut"]
    assert listing(ongoing(fake_archive)) == ["Sauna"]


def test_replaced_link_inside_owned_folder_is_foreign(app, fake_archive, two_files):
    c = sauna(app)
    base = ongoing(fake_archive) / "Sauna"
    os.unlink(base / "a.pdf")
    os.symlink(fake_archive.root / "10. Financial", base / "a.pdf")  # user's, same name
    app.ongoing.sync()
    assert readlink(base / "a.pdf") == str(fake_archive.root / "10. Financial")
    assert points_at(base / "a_2.pdf", fake_archive, f"{BANKS}/a.pdf")
    app.collections.close(c.id)
    assert listing(base) == ["a.pdf"]


def test_returning_member_does_not_rename_other_links(app, fake_archive):
    # Probe P3: names held by correct owned links are reserved first.
    fake_archive.add(f"{BANKS}/plan.pdf", drive_id="id-1")
    fake_archive.add("Home/plan.pdf", drive_id="id-2")
    app.scan()
    sauna(app, ["id-1", "id-2"])
    base = ongoing(fake_archive) / "Sauna"
    quarantine = fake_archive.root / "##. To Delete" / BANKS
    quarantine.mkdir(parents=True)
    os.rename(fake_archive.root / BANKS / "plan.pdf", quarantine / "plan.pdf")
    app.scan()
    app.ongoing.sync()
    assert listing(base) == ["plan_2.pdf"]
    assert points_at(base / "plan_2.pdf", fake_archive, "Home/plan.pdf")
    os.rename(quarantine / "plan.pdf", fake_archive.root / BANKS / "plan.pdf")
    app.scan()
    app.ongoing.sync()
    assert listing(base) == ["plan.pdf", "plan_2.pdf"]
    assert points_at(base / "plan_2.pdf", fake_archive, "Home/plan.pdf")  # unchanged
    assert points_at(base / "plan.pdf", fake_archive, f"{BANKS}/plan.pdf")


def test_member_with_a_reserved_name_is_skipped_and_reported(app, fake_archive):
    # Probe P4
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="id-a")
    fake_archive.add("Home/.ds_store", drive_id="id-ds")
    app.scan()
    c = sauna(app, ["id-a", "id-ds"])
    assert listing(ongoing(fake_archive) / "Sauna") == ["a.pdf"]
    c = app.collections.get(c.id)
    assert c.ongoing_rel == f"{ONG}/Sauna"
    assert c.ongoing_status.startswith(NOT_MANAGED) and "Home/.ds_store" in c.ongoing_status
    assert app.ongoing.sync().problems == []


@pytest.mark.parametrize(
    "foreign", [unicodedata.normalize("NFD", "Ärende"), "äRENDE"], ids=["nfd", "case"]
)
def test_nfd_and_case_variant_foreign_entries(app, fake_archive, two_files, foreign):
    # Probe P5
    (ongoing(fake_archive) / foreign).mkdir()
    (ongoing(fake_archive) / foreign / "u.txt").write_text("u", encoding="utf-8")
    c = app.collections.create("Ärende")
    app.collections.add_members(c.id, ["id-a"])
    assert app.collections.get(c.id).ongoing_rel == f"{ONG}/Ärende_2"
    app.collections.close(c.id)
    assert listing(ongoing(fake_archive)) == [foreign]
    assert listing(ongoing(fake_archive) / foreign) == ["u.txt"]


def test_names_vacated_in_the_same_plan_are_reused(app, fake_archive, two_files):
    app.collections.on_change = None
    y = app.collections.create("Y")  # lower id: planned before X
    x = app.collections.create("X")
    app.collections.add_members(x.id, ["id-a"])
    app.collections.add_members(y.id, ["id-b"])
    app.ongoing.sync()
    app.collections.set_name(x.id, "Z")
    app.collections.set_name(y.id, "X")  # takes the name X vacates in the same sync
    result = app.ongoing.sync()
    assert result.batch is not None and result.batch.failed is None
    assert listing(ongoing(fake_archive)) == ["X", "Z"]
    assert listing(ongoing(fake_archive) / "X") == ["b.pdf"]
    assert listing(ongoing(fake_archive) / "Z") == ["a.pdf"]
    assert app.collections.get(y.id).ongoing_rel == f"{ONG}/X"


def test_ongoing_only_batches_skip_the_throttle(app, fake_archive, monkeypatch):
    from dam.ops import executor as executor_module

    for i in range(30):
        fake_archive.add(f"{BANKS}/f{i:02}.pdf", drive_id=f"id-{i}")
    app.scan()
    assert app.executor.throttle_ms > 0
    slept = []
    monkeypatch.setattr(executor_module.time, "sleep", lambda s: slept.append(s))
    c = sauna(app, [f"id-{i}" for i in range(30)])
    app.collections.close(c.id)
    assert listing(ongoing(fake_archive)) == []
    assert slept == []
    # other batches still throttle
    fake_archive.add("##. Organize/x.pdf", drive_id="id-x")
    fake_archive.add("##. Organize/y.pdf", drive_id="id-y")
    app.executor.apply(
        Plan(
            [
                Op(OpKind.MOVE, "##. Organize/x.pdf", BANKS),
                Op(OpKind.MOVE, "##. Organize/y.pdf", BANKS),
            ],
            "cli",
        )
    )
    assert slept == [app.executor.throttle_ms / 1000]


def test_create_and_undo_cleanup_also_sync(app, fake_archive, two_files):
    c = app.collections.create("Empty")
    app.collections.get_or_create("Other")
    assert listing(ongoing(fake_archive)) == []  # empty collections are not published
    with app.engine.begin() as conn:  # a membership a filing batch created
        conn.execute(
            collection_members.insert().values(
                collection_id=c.id, drive_id="id-a", added=1.0, created_by_batch="b1"
            )
        )
    app.ongoing.sync()
    assert listing(ongoing(fake_archive) / "Empty") == ["a.pdf"]
    app.collections.remove_created_by("b1")
    assert listing(ongoing(fake_archive)) == []  # emptied again: taken down


# --- sync contract ----------------------------------------------------------------------


def test_dry_run_plans_without_touching_anything(app, fake_archive, two_files):
    app.collections.on_change = None
    sauna(app)
    result = app.ongoing.sync(dry_run=True)
    assert [op.kind for op in result.plan] == [OpKind.MKDIR, OpKind.SYMLINK, OpKind.SYMLINK]
    assert result.batch is None
    assert listing(ongoing(fake_archive)) == []
    assert journal_count(app) == 0
    assert app.collections.by_name("Sauna").ongoing_rel is None


def test_nothing_to_do_writes_no_journal_rows(app, fake_archive):
    result = app.ongoing.sync()
    assert (result.plan, result.batch, result.problems) == ([], None, [])
    assert journal_count(app) == 0


def test_preview_for_close_shows_the_plan_only(app, fake_archive, two_files):
    c = sauna(app)
    other = app.collections.create("Other")
    before = journal_count(app)
    ops = app.ongoing.preview_for([c.id], state="closed")
    assert [op.kind for op in ops] == [
        OpKind.UNLINK_SYMLINK,
        OpKind.UNLINK_SYMLINK,
        OpKind.REMOVE_EMPTY_DIR,
    ]
    assert app.ongoing.preview_for([other.id]) == []  # empty: not published
    assert app.ongoing.preview_for([other.id], name="New") == []
    assert [op.kind for op in app.ongoing.preview_for([c.id], publish=False)][-1] is (
        OpKind.REMOVE_EMPTY_DIR
    )
    assert journal_count(app) == before
    assert listing(ongoing(fake_archive) / "Sauna") == ["a.pdf", "b.pdf"]
    assert app.collections.get(c.id).state == "open"


def test_undo_of_a_sync_batch_is_refused(app, fake_archive, two_files):
    c = sauna(app)
    app.collections.remove_member(c.id, "id-b")
    batch = batches(app)[-1]
    with pytest.raises(OpFailed, match="automatic Ongoing update"):
        app.executor.undo(batch)
    with pytest.raises(OpFailed, match="Undo the collection change instead"):
        app.activity.undo(batch)
    assert listing(ongoing(fake_archive) / "Sauna") == ["a.pdf"]
    assert {r.state for r in journal(app, batch)} == {"done"}
    summary = app.activity.get(batch)
    assert summary.origin == "workflow" and summary.undoable is False


def test_undo_of_a_close_sync_is_refused_and_sync_stays_consistent(app, fake_archive, two_files):
    # Probe P8: undoing the close's sync used to leave an orphan folder behind.
    c = sauna(app)
    app.collections.close(c.id)
    with pytest.raises(OpFailed, match="automatic Ongoing update"):
        app.executor.undo(batches(app)[-1])
    assert app.ongoing.sync().batch is None
    app.collections.reopen(c.id)
    assert listing(ongoing(fake_archive)) == ["Sauna"]
    assert listing(ongoing(fake_archive) / "Sauna") == ["a.pdf", "b.pdf"]


def test_missing_ongoing_folder_does_nothing(app, fake_archive, two_files):
    c = sauna(app)
    os.rename(ongoing(fake_archive), fake_archive.root / "elsewhere")
    before = journal_count(app)
    result = app.ongoing.sync()
    assert result.batch is None and result.problems
    assert app.collections.get(c.id).ongoing_rel == f"{ONG}/Sauna"  # not forgotten
    assert journal_count(app) == before


def test_mutation_callback_errors_are_logged_not_raised(app, two_files, caplog):
    def broken():
        raise RuntimeError("boom")

    app.collections.on_change = broken
    with caplog.at_level(logging.ERROR, logger="dam.collections.service"):
        c = sauna(app)
    assert [m.drive_id for m in c.members] == ["id-a", "id-b"]
    assert any(r.exc_info and "boom" in str(r.exc_info[1]) for r in caplog.records)


def test_concurrent_syncs_do_not_duplicate(app, fake_archive, two_files):
    app.collections.on_change = None
    sauna(app)
    results = []
    threads = [threading.Thread(target=lambda: results.append(app.ongoing.sync())) for _ in "ab"]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert sum(r.batch is not None for r in results) == 1
    assert all(r.problems == [] for r in results)
    assert listing(ongoing(fake_archive) / "Sauna") == ["a.pdf", "b.pdf"]


# --- names (Task 7 assumption) -----------------------------------------------------------


@pytest.mark.parametrize(
    "bad", [" ", "x.", ".x", ".DS_Store", "a/b", "a\\b", "a\0b", "a\u200bb", ".", ".."]
)
def test_names_the_guards_would_reject_are_rejected_by_check_name(bad):
    with pytest.raises(InvalidRequest):
        check_name(bad)


def test_trailing_and_leading_spaces_are_trimmed_by_check_name():
    assert check_name(" x \u00a0") == "x"


@pytest.mark.parametrize(
    "good", ["Sauna", "2026 Sauna conversion", "Ärende", "a.b", "x_2", "Ω", " padded "]
)
def test_names_check_name_accepts_pass_the_guards(app, good):
    name = check_name(good)
    validate(Op(OpKind.MKDIR, None, f"{ONG}/{name}"), app.paths)
    validate(Op(OpKind.SYMLINK, BANKS, f"{ONG}/{name}"), app.paths)
    validate(Op(OpKind.SYMLINK, BANKS, f"{ONG}/{name}/{name}"), app.paths)
    validate(Op(OpKind.REMOVE_EMPTY_DIR, f"{ONG}/{name}", None), app.paths)


# --- serve: background syncs ---------------------------------------------------------------


def test_initial_scan_syncs_ongoing(app, fake_archive, two_files):
    from dam.serve import _initial_scan

    app.collections.on_change = None
    sauna(app)
    wake = threading.Event()
    _initial_scan(app, wake)
    assert wake.is_set()
    assert listing(ongoing(fake_archive) / "Sauna") == ["a.pdf", "b.pdf"]


def test_initial_scan_with_archive_gone_does_not_sync(app, fake_archive, tmp_path, monkeypatch):
    from dam.serve import _initial_scan

    calls = []
    monkeypatch.setattr(app.ongoing, "sync", lambda: calls.append(1))
    os.rename(fake_archive.root, tmp_path / "archive-away")
    wake = threading.Event()
    _initial_scan(app, wake)
    assert wake.is_set() and calls == []


def test_background_sync_errors_are_logged_never_raised(app, monkeypatch, caplog):
    from dam.serve import _after_watcher_scan, _initial_scan

    def broken():
        raise RuntimeError("boom")

    monkeypatch.setattr(app, "sync_publishers", broken)
    with caplog.at_level(logging.ERROR, logger="dam.serve"):
        wake = threading.Event()
        _after_watcher_scan(app, wake)
        assert wake.is_set()
        wake = threading.Event()
        _initial_scan(app, wake)
        assert wake.is_set()
    assert sum("ongoing sync failed" in r.message for r in caplog.records) == 2


def test_watcher_scan_repairs_a_moved_member_link(app, fake_archive, two_files):
    import time

    from dam.serve import start_background

    sauna(app)
    bg = start_background(app)
    try:
        bg.scan_thread.join(10)
        new = fake_archive.root / BANKS / "a-renamed.pdf"
        os.rename(fake_archive.root / BANKS / "a.pdf", new)
        bg.watcher._note(str(new))
        link = ongoing(fake_archive) / "Sauna" / "a-renamed.pdf"
        deadline = time.monotonic() + 15
        while not link.is_symlink() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert points_at(link, fake_archive, f"{BANKS}/a-renamed.pdf")
    finally:
        bg.stop()
    assert listing(ongoing(fake_archive) / "Sauna") == ["a-renamed.pdf", "b.pdf"]


def test_create_and_get_or_create_call_on_change(app):
    calls = []
    app.collections.on_change = lambda: calls.append(1)
    app.collections.create("A")
    assert calls == [1]
    app.collections.get_or_create("B")  # creates
    assert calls == [1, 1]
    app.collections.get_or_create("b")  # exists: no change
    assert calls == [1, 1]


def test_preview_for_rename_of_a_published_collection(app, fake_archive, two_files):
    c = sauna(app)
    before = journal_count(app)
    ops = app.ongoing.preview_for([c.id], name="New")
    assert [(op.kind, op.dst) for op in ops] == [
        (OpKind.UNLINK_SYMLINK, f"{ONG}/Sauna/a.pdf"),
        (OpKind.UNLINK_SYMLINK, f"{ONG}/Sauna/b.pdf"),
        (OpKind.REMOVE_EMPTY_DIR, f"{ONG}/Sauna"),
        (OpKind.MKDIR, f"{ONG}/New"),
        (OpKind.SYMLINK, f"{ONG}/New/a.pdf"),
        (OpKind.SYMLINK, f"{ONG}/New/b.pdf"),
    ]
    assert journal_count(app) == before
    assert listing(ongoing(fake_archive)) == ["Sauna"]
    assert app.collections.get(c.id).name == "Sauna"


# --- final fix wave: unknown errors, empty Ongoing, identity changes ---------------------


def lstat_fails(monkeypatch, suffix: str, exc: OSError) -> None:
    """``os.lstat`` of a path ending in ``suffix`` raises ``exc`` (everything else real)."""
    real = os.lstat

    def fake(p, *args, **kwargs):
        if str(p).replace("\\", "/").endswith(suffix):
            raise exc
        return real(p, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", fake)


def test_transient_lstat_error_keeps_the_records_and_plans_nothing(
    app, fake_archive, two_files, monkeypatch
):
    import errno

    app.collections.on_change = None
    c = sauna(app)
    app.ongoing.sync()
    before = records(app)
    app.collections.remove_member(c.id, "id-b")  # a sync would now unlink b.pdf
    with monkeypatch.context() as m:
        lstat_fails(m, f"{ONG}/Sauna", OSError(errno.EIO, "Input/output error"))
        result = app.ongoing.sync()
    assert result.plan == [] and result.batch is None
    assert any(p.startswith("Sauna:") and "could not be read" in p for p in result.problems)
    assert records(app) == before
    assert listing(ongoing(fake_archive) / "Sauna") == ["a.pdf", "b.pdf"]
    # once readable again, the sync goes ahead
    result = app.ongoing.sync()
    assert [(r.kind, r.dst) for r in result.plan] == [(OpKind.UNLINK_SYMLINK, f"{ONG}/Sauna/b.pdf")]


def test_enoent_still_forgets_the_record(app, fake_archive, two_files, monkeypatch):
    app.collections.on_change = None
    sauna(app)
    app.ongoing.sync()
    with monkeypatch.context() as m:
        lstat_fails(m, f"{ONG}/Sauna/a.pdf", FileNotFoundError(2, "No such file"))
        app.ongoing.sync(dry_run=True)  # planning alone forgets nothing
        assert f"{ONG}/Sauna/a.pdf" in [r.rel for r in records(app)]
        app.ongoing.sync()
    assert f"{ONG}/Sauna/a.pdf" not in [r.rel for r in records(app)]


def test_empty_ongoing_with_records_skips_the_sync(app, fake_archive, two_files, tmp_path):
    app.collections.on_change = None
    c = sauna(app)
    app.ongoing.sync()
    before = records(app)
    os.rename(ongoing(fake_archive) / "Sauna", tmp_path / "Sauna-away")
    assert listing(ongoing(fake_archive)) == []
    journal_before = journal_count(app)
    result = app.ongoing.sync()
    assert result.batch is None and result.plan == []
    assert any("empty" in p for p in result.problems)
    assert records(app) == before
    assert listing(ongoing(fake_archive)) == []  # nothing published
    assert journal_count(app) == journal_before
    assert app.collections.get(c.id).ongoing_rel == f"{ONG}/Sauna"


def test_empty_ongoing_without_records_syncs_normally(app, fake_archive, two_files):
    app.collections.on_change = None
    sauna(app)
    assert listing(ongoing(fake_archive)) == [] and records(app) == []
    result = app.ongoing.sync()
    assert result.batch is not None and result.problems == []
    assert listing(ongoing(fake_archive) / "Sauna") == ["a.pdf", "b.pdf"]


def identity_problem(rel: str) -> str:
    return (
        f"{rel} looks different from before (Google Drive may have re-created it),"
        " so it was left as it is."
    )


def set_births(app, birth):
    """Pretend every recorded entry had another birth than it has now (as when Google
    Drive re-writes a new item: same inode, later birth)."""
    with app.engine.begin() as conn:
        conn.execute(update(ongoing_entries).values(st_birth=birth))


def test_a_changed_birth_with_the_same_inode_and_value_is_still_ours(app, fake_archive, two_files):
    app.collections.on_change = None
    sauna(app)
    app.ongoing.sync()
    before = records(app)
    set_births(app, "b:1")
    result = app.ongoing.sync()
    assert result.problems == [] and result.batch is None
    after = records(app)  # folder and both links: the stored birth is the current one
    assert [(r.rel, r.st_dev, r.st_ino) for r in after] == [
        (r.rel, r.st_dev, r.st_ino) for r in before
    ]
    for r in after:
        assert identity.from_columns(r.st_dev, r.st_ino, r.st_birth) == identity.of_path(
            fake_archive.root / r.rel
        )
    assert listing(ongoing(fake_archive) / "Sauna") == ["a.pdf", "b.pdf"]


def test_a_top_link_with_a_changed_birth_is_still_ours(app, fake_archive):
    folder(fake_archive, "Home/2026 Sauna", "d-sauna")
    app.scan()
    c = sauna(app, ["d-sauna"])
    link = ongoing(fake_archive) / "Sauna"
    set_births(app, "b:1")
    assert app.ongoing.sync().problems == []
    rec = records(app)[0]
    assert identity.from_columns(rec.st_dev, rec.st_ino, rec.st_birth) == identity.of_path(link)
    app.collections.close(c.id)  # managed again: the link is taken down
    assert listing(ongoing(fake_archive)) == []


def test_a_link_with_a_changed_target_is_not_ours_even_with_the_same_inode(app, fake_archive):
    folder(fake_archive, "Home/2026 Sauna", "d-sauna")
    folder(fake_archive, "Home/Other", "d-other")
    app.scan()
    sauna(app, ["d-sauna"])
    link = ongoing(fake_archive) / "Sauna"
    other = readlink(link).replace("2026 Sauna", "Other")
    os.unlink(link)
    os.symlink(other, link)
    set_births(app, "b:1")
    app.ongoing.sync()
    assert readlink(link) == other  # the link is never touched
    # the record was not taken as a match: it is forgotten, not refreshed
    assert all(r.rel != f"{ONG}/Sauna" or r.st_birth != "b:1" for r in records(app))
    assert not any(r.st_birth == "b:1" and r.link_value == other for r in records(app))


def test_a_folder_with_a_changed_birth_is_still_ours(app, fake_archive, two_files):
    app.collections.on_change = None
    c = sauna(app)
    app.ongoing.sync()
    set_births(app, "b:1")
    app.collections.close(c.id)
    app.ongoing.sync()
    assert listing(ongoing(fake_archive)) == [] and records(app) == []


def test_link_with_new_identity_but_same_value_is_left_alone(app, fake_archive):
    folder(fake_archive, "Home/2026 Sauna", "d-sauna")
    app.scan()
    c = sauna(app, ["d-sauna"])
    link = ongoing(fake_archive) / "Sauna"
    value = readlink(link)
    before = records(app)
    tmp = ongoing(fake_archive) / "tmp-link"
    os.symlink(value, tmp)  # a new inode with exactly the same value
    os.unlink(link)
    os.rename(tmp, link)
    rec = before[0]
    assert not identity.same(
        identity.from_columns(rec.st_dev, rec.st_ino, rec.st_birth), identity.of_path(link)
    )
    journal_before = journal_count(app)
    result = app.ongoing.sync()
    assert identity_problem(f"{ONG}/Sauna") in [p.split(": ", 1)[1] for p in result.problems]
    assert result.batch is None
    assert records(app) == before
    assert listing(ongoing(fake_archive)) == ["Sauna"]  # no Sauna_2
    app.collections.close(c.id)  # still left alone: not removed
    assert readlink(link) == value and records(app) == before
    assert journal_count(app) == journal_before


def test_inner_link_with_new_identity_but_same_value_is_left_alone(app, fake_archive, two_files):
    sauna(app)
    link = ongoing(fake_archive) / "Sauna" / "a.pdf"
    value = readlink(link)
    before = records(app)
    os.unlink(link)
    (ongoing(fake_archive) / "Sauna" / "pad").write_text(
        "x", encoding="utf-8"
    )  # keep the inode from reuse
    os.symlink(value, link)
    os.unlink(ongoing(fake_archive) / "Sauna" / "pad")
    result = app.ongoing.sync()
    assert any(identity_problem(f"{ONG}/Sauna/a.pdf") in p for p in result.problems)
    assert result.batch is None and records(app) == before
    assert listing(ongoing(fake_archive) / "Sauna") == ["a.pdf", "b.pdf"]


def test_a_persistently_failing_sync_is_journaled_once(app, fake_archive, monkeypatch):
    folder(fake_archive, "Home/2026 Sauna", "d-sauna")
    folder(fake_archive, "Home/Other", "d-other")
    app.scan()
    app.collections.on_change = None
    c = sauna(app, ["d-sauna"])

    def broken(target, link):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(primitives, "make_symlink", broken)

    def failed_rows():
        return [r for r in journal(app) if r.state == "failed"]

    assert app.ongoing.last_failure is None
    first = app.ongoing.sync()
    assert first.batch is not None and first.batch.failed is not None
    failure = app.ongoing.last_failure
    assert failure and "Input/output error" in failure
    for _ in range(2):
        again = app.ongoing.sync()
        assert again.batch is None
        assert any(failure in p for p in again.problems)
    assert len(failed_rows()) == 1
    assert app.ongoing.last_failure == failure
    # a different plan is applied again
    app.collections.add_members(c.id, ["d-other"])
    changed = app.ongoing.sync()
    assert changed.batch is not None and len(failed_rows()) == 2
    # and once it works, the failure is cleared
    monkeypatch.undo()
    assert app.ongoing.sync().batch.failed is None
    assert app.ongoing.last_failure is None


class FakePublisher:
    id = "fake"

    def __init__(self):
        self.calls: list[str] = []

    def sync(self, dry_run: bool = False):
        self.calls.append("sync")

    def preview_for(self, collection_ids, **changes):
        self.calls.append(f"preview {collection_ids} {changes}")
        return []


def test_every_registered_publisher_syncs_on_a_collection_change(app, fake_archive, two_files):
    fake = FakePublisher()
    app.publishers.register(fake)
    c = sauna(app)  # create + add_members: two changes
    assert fake.calls == ["sync", "sync"]
    assert listing(ongoing(fake_archive) / "Sauna") == ["a.pdf", "b.pdf"]  # Ongoing too
    result = app.collections.changed()  # the Ongoing publisher's result is returned
    assert result is not None and result.problems == [] and len(fake.calls) == 3
    assert app.collections.get(c.id).ongoing_rel == f"{ONG}/Sauna"


def test_a_failing_publisher_does_not_stop_the_others(app, fake_archive, two_files, caplog):
    class Broken(FakePublisher):
        id = "broken"

        def sync(self, dry_run: bool = False):
            raise RuntimeError("boom")

    app.publishers.register(Broken())
    with caplog.at_level(logging.ERROR):
        sauna(app)
    assert listing(ongoing(fake_archive) / "Sauna") == ["a.pdf", "b.pdf"]
    assert any("broken" in r.getMessage() for r in caplog.records)


@posix_names
@pytest.mark.parametrize("bad", ["evil‮fdp.pdf", "tab\there.pdf", "bell\x07.pdf"])
def test_member_with_control_characters_in_its_name_is_not_linked(app, fake_archive, bad):
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="id-a")
    fake_archive.add(f"Home/{bad}", drive_id="id-bad")
    app.scan()
    c = sauna(app, ["id-a", "id-bad"])
    assert listing(ongoing(fake_archive) / "Sauna") == ["a.pdf"]
    status = app.collections.get(c.id).ongoing_status
    assert status.startswith(NOT_MANAGED) and "not allowed" in status


def test_an_unchanged_failed_plan_is_retried_after_an_hour(app, fake_archive, monkeypatch):
    folder(fake_archive, "Home/2026 Sauna", "d-sauna")
    app.scan()
    app.collections.on_change = None
    sauna(app, ["d-sauna"])
    clock = [1000.0]
    monkeypatch.setattr(app.ongoing, "_clock", lambda: clock[0])

    def broken(target, link):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(primitives, "make_symlink", broken)

    def failed_rows():
        return [r for r in journal(app) if r.state == "failed"]

    assert app.ongoing.sync().batch is not None
    clock[0] += 3599
    assert app.ongoing.sync().batch is None and len(failed_rows()) == 1
    clock[0] += 2  # an hour has passed: retried once
    assert app.ongoing.sync().batch is not None and len(failed_rows()) == 2
    assert app.ongoing.sync().batch is None and len(failed_rows()) == 2


# --- collection groups as nested folders (mac redesign, Task 8) ---------------------


def grouped(app, fake_archive):
    """Sauna: a.pdf ungrouped, b.pdf in "2025", c.pdf in "2025/Q1". Returns
    (collection, group 2025, group Q1)."""
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="id-a")
    fake_archive.add(f"{BANKS}/b.pdf", drive_id="id-b")
    fake_archive.add(f"{BANKS}/c.pdf", drive_id="id-c")
    app.scan()
    c = app.collections.create("Sauna")
    app.collections.add_members(c.id, ["id-a"])
    y = app.collections.create_group(c.id, "2025")
    q = app.collections.create_group(c.id, "Q1", parent_id=y.id)
    app.collections.set_member_group(c.id, ["id-b"], y.id)
    app.collections.set_member_group(c.id, ["id-c"], q.id)
    return app.collections.get(c.id), y, q


def kinds(app, batch_id):
    """(kind, the path acted on) per journal row of ``batch_id``."""
    removals = ("unlink_symlink", "remove_empty_dir")
    return [(r.kind, r.src if r.kind in removals else r.dst) for r in journal(app, batch_id)]


def test_nested_groups_publish_nested_folders_and_links(app, fake_archive):
    c, y, q = grouped(app, fake_archive)
    assert app.ongoing.desired_one(c) == Desired(
        "folder",
        f"{ONG}/Sauna",
        links={
            "a.pdf": f"{BANKS}/a.pdf",
            "2025/b.pdf": f"{BANKS}/b.pdf",
            "2025/Q1/c.pdf": f"{BANKS}/c.pdf",
        },
        folders=("2025", "2025/Q1"),
    )
    base = ongoing(fake_archive) / "Sauna"
    assert listing(base) == ["2025", "a.pdf"]
    assert (base / "2025").is_dir() and not (base / "2025").is_symlink()
    assert listing(base / "2025") == ["Q1", "b.pdf"]
    assert listing(base / "2025" / "Q1") == ["c.pdf"]
    assert points_at(base / "a.pdf", fake_archive, f"{BANKS}/a.pdf")
    assert points_at(base / "2025" / "b.pdf", fake_archive, f"{BANKS}/b.pdf")
    assert points_at(base / "2025" / "Q1" / "c.pdf", fake_archive, f"{BANKS}/c.pdf")
    assert [(r.rel, r.kind) for r in records(app)] == [
        (f"{ONG}/Sauna", "folder"),
        (f"{ONG}/Sauna/2025", "folder"),
        (f"{ONG}/Sauna/2025/Q1", "folder"),
        (f"{ONG}/Sauna/2025/Q1/c.pdf", "link"),
        (f"{ONG}/Sauna/2025/b.pdf", "link"),
        (f"{ONG}/Sauna/a.pdf", "link"),
    ]
    for r in records(app):
        assert identity.from_columns(r.st_dev, r.st_ino, r.st_birth) == identity.of_path(
            fake_archive.root / r.rel
        )
    c = app.collections.get(c.id)
    assert (c.ongoing_rel, c.ongoing_status) == (f"{ONG}/Sauna", None)
    # settled: nothing more to do
    before = journal_count(app)
    assert app.ongoing.sync().batch is None
    assert journal_count(app) == before


def test_group_name_colliding_with_a_link_gets_a_suffix(app, fake_archive, two_files):
    c = sauna(app)
    g = app.collections.create_group(c.id, "a.pdf")
    app.collections.set_member_group(c.id, ["id-b"], g.id)
    want = app.ongoing.desired_one(app.collections.get(c.id))
    assert want.folders == ("a_2.pdf",)
    assert want.links == {"a.pdf": f"{BANKS}/a.pdf", "a_2.pdf/b.pdf": f"{BANKS}/b.pdf"}
    base = ongoing(fake_archive) / "Sauna"
    assert listing(base) == ["a.pdf", "a_2.pdf"]
    assert points_at(base / "a.pdf", fake_archive, f"{BANKS}/a.pdf")
    assert listing(base / "a_2.pdf") == ["b.pdf"]


def test_moving_a_member_between_groups_moves_its_link(app, fake_archive):
    c, y, q = grouped(app, fake_archive)
    n = len(batches(app))
    app.collections.set_member_group(c.id, ["id-b"], q.id)
    assert len(batches(app)) == n + 1
    base = ongoing(fake_archive) / "Sauna"
    assert listing(base / "2025") == ["Q1"]
    assert listing(base / "2025" / "Q1") == ["b.pdf", "c.pdf"]
    assert kinds(app, batches(app)[-1]) == [
        ("unlink_symlink", f"{ONG}/Sauna/2025/b.pdf"),
        ("symlink", f"{ONG}/Sauna/2025/Q1/b.pdf"),
    ]
    app.collections.set_member_group(c.id, ["id-c"], None)
    assert listing(base) == ["2025", "a.pdf", "c.pdf"]
    assert listing(base / "2025" / "Q1") == ["b.pdf"]
    assert {r.rel for r in records(app)} == {
        f"{ONG}/Sauna",
        f"{ONG}/Sauna/2025",
        f"{ONG}/Sauna/2025/Q1",
        f"{ONG}/Sauna/2025/Q1/b.pdf",
        f"{ONG}/Sauna/a.pdf",
        f"{ONG}/Sauna/c.pdf",
    }


def test_group_rename_recreates_the_subtree_and_the_way_back_resyncs(app, fake_archive):
    c, y, q = grouped(app, fake_archive)
    n = len(batches(app))
    app.collections.rename_group(y.id, "2026")
    assert len(batches(app)) == n + 1  # one journaled batch
    assert kinds(app, batches(app)[-1]) == [
        ("unlink_symlink", f"{ONG}/Sauna/2025/b.pdf"),
        ("unlink_symlink", f"{ONG}/Sauna/2025/Q1/c.pdf"),
        ("remove_empty_dir", f"{ONG}/Sauna/2025/Q1"),
        ("remove_empty_dir", f"{ONG}/Sauna/2025"),
        ("mkdir", f"{ONG}/Sauna/2026"),
        ("mkdir", f"{ONG}/Sauna/2026/Q1"),
        ("symlink", f"{ONG}/Sauna/2026/b.pdf"),
        ("symlink", f"{ONG}/Sauna/2026/Q1/c.pdf"),
    ]
    assert all(r.state == "done" for r in journal(app, batches(app)[-1]))
    assert "move" not in {r.kind for r in journal(app)} and "rename" not in {
        r.kind for r in journal(app)
    }
    base = ongoing(fake_archive) / "Sauna"
    assert listing(base) == ["2026", "a.pdf"]
    assert listing(base / "2026") == ["Q1", "b.pdf"]
    assert listing(base / "2026" / "Q1") == ["c.pdf"]
    assert {r.rel for r in records(app) if "2025" in r.rel} == set()
    # the user's way back (rename it back) re-syncs to the original layout
    app.collections.rename_group(y.id, "2025")
    assert listing(base) == ["2025", "a.pdf"]
    assert listing(base / "2025") == ["Q1", "b.pdf"]
    assert listing(base / "2025" / "Q1") == ["c.pdf"]
    assert not os.path.lexists(base / "2026")
    assert app.collections.get(c.id).ongoing_status is None
    # a sync batch is never undone
    with pytest.raises(OpFailed, match="automatic Ongoing update"):
        app.executor.undo(batches(app)[-1])


def test_case_only_group_rename_recreates_under_new_spelling(app, fake_archive):
    c, y, q = grouped(app, fake_archive)
    app.collections.rename_group(q.id, "q1")
    assert listing(ongoing(fake_archive) / "Sauna" / "2025") == ["b.pdf", "q1"]
    assert {r.rel for r in records(app) if "Q1" in r.rel or "q1" in r.rel} == {
        f"{ONG}/Sauna/2025/q1",
        f"{ONG}/Sauna/2025/q1/c.pdf",
    }


def test_group_folder_with_user_file_is_left(app, fake_archive):
    c, y, q = grouped(app, fake_archive)
    base = ongoing(fake_archive) / "Sauna"
    user = fake_archive.add(f"{ONG}/Sauna/2025/notes.txt", content=b"mine", drive_id="user-1")
    app.collections.remove_group(y.id)  # Q1 moves up, b.pdf becomes ungrouped
    assert listing(base) == ["2025", "Q1", "a.pdf", "b.pdf"]
    assert listing(base / "2025") == ["notes.txt"]  # its link went, the file survives
    assert user.read_bytes() == b"mine"
    assert listing(base / "Q1") == ["c.pdf"]
    rows = journal(app, batches(app)[-1])
    # only the app's own (empty) Q1 went, to come back at the top; 2025 never
    assert [r.src for r in rows if r.kind == "remove_empty_dir"] == [f"{ONG}/Sauna/2025/Q1"]
    assert {r.state for r in rows} == {"done"}
    c = app.collections.get(c.id)
    assert c.ongoing_rel == f"{ONG}/Sauna"
    assert c.ongoing_status == (f"{NOT_MANAGED}{ONG}/Sauna/2025 {HOLDS_1}")
    # still owned (the record matches): no retry noise while the file is there
    assert any(r.rel == f"{ONG}/Sauna/2025" for r in records(app))
    before = journal_count(app)
    assert app.ongoing.sync().batch is None
    assert journal_count(app) == before
    assert app.collections.get(c.id).ongoing_status == c.ongoing_status
    # the user takes the file away: the next sync finishes the job
    os.rename(user, fake_archive.root / BANKS / "notes.txt")
    app.ongoing.sync()
    assert listing(base) == ["Q1", "a.pdf", "b.pdf"]
    assert app.collections.get(c.id).ongoing_status is None


def test_close_with_user_file_in_a_group_folder_keeps_the_path_to_it(app, fake_archive):
    c, y, q = grouped(app, fake_archive)
    base = ongoing(fake_archive) / "Sauna"
    user = fake_archive.add(f"{ONG}/Sauna/2025/Q1/notes.txt", content=b"mine", drive_id="u-1")
    app.collections.close(c.id)
    # every link went, so did nothing else: the folders above the file stay
    assert listing(base) == ["2025"]
    assert listing(base / "2025") == ["Q1"]
    assert listing(base / "2025" / "Q1") == ["notes.txt"]
    assert user.read_bytes() == b"mine"
    assert [r.kind for r in journal(app, batches(app)[-1])] == ["unlink_symlink"] * 3
    c = app.collections.get(c.id)
    assert c.ongoing_rel == f"{ONG}/Sauna"
    assert c.ongoing_status == (f"{NOT_MANAGED}{ONG}/Sauna/2025/Q1 {HOLDS_1}")
    os.rename(user, fake_archive.root / BANKS / "notes.txt")
    app.ongoing.sync()
    assert listing(ongoing(fake_archive)) == []
    assert kinds(app, batches(app)[-1]) == [
        ("remove_empty_dir", f"{ONG}/Sauna/2025/Q1"),
        ("remove_empty_dir", f"{ONG}/Sauna/2025"),
        ("remove_empty_dir", f"{ONG}/Sauna"),
    ]
    assert records(app) == []
    c = app.collections.get(c.id)
    assert (c.ongoing_rel, c.ongoing_status) == (None, None)


@needs_dir_fd
def test_close_removes_the_whole_tree_deepest_first(app, fake_archive):
    c, y, q = grouped(app, fake_archive)
    (ongoing(fake_archive) / "Sauna" / "2025" / ".DS_Store").write_bytes(FINDER)
    app.collections.close(c.id)
    assert listing(ongoing(fake_archive)) == []
    assert kinds(app, batches(app)[-1]) == [
        ("unlink_symlink", f"{ONG}/Sauna/a.pdf"),
        ("unlink_symlink", f"{ONG}/Sauna/2025/b.pdf"),
        ("unlink_symlink", f"{ONG}/Sauna/2025/Q1/c.pdf"),
        ("remove_empty_dir", f"{ONG}/Sauna/2025/Q1"),
        ("remove_empty_dir", f"{ONG}/Sauna/2025"),
        ("remove_empty_dir", f"{ONG}/Sauna"),
    ]
    assert records(app) == []
    for rel in (f"{BANKS}/a.pdf", f"{BANKS}/b.pdf", f"{BANKS}/c.pdf"):
        assert (fake_archive.root / rel).exists()


def test_collection_rename_moves_the_whole_tree(app, fake_archive):
    c, y, q = grouped(app, fake_archive)
    app.collections.set_name(c.id, "Sauna 2026")
    assert listing(ongoing(fake_archive)) == ["Sauna 2026"]
    base = ongoing(fake_archive) / "Sauna 2026"
    assert listing(base) == ["2025", "a.pdf"]
    assert listing(base / "2025" / "Q1") == ["c.pdf"]
    assert {r.rel for r in records(app)} == {
        f"{ONG}/Sauna 2026",
        f"{ONG}/Sauna 2026/2025",
        f"{ONG}/Sauna 2026/2025/Q1",
        f"{ONG}/Sauna 2026/2025/Q1/c.pdf",
        f"{ONG}/Sauna 2026/2025/b.pdf",
        f"{ONG}/Sauna 2026/a.pdf",
    }


def test_group_folder_swapped_for_a_symlink_is_refused(app, fake_archive):
    c, y, q = grouped(app, fake_archive)
    base = ongoing(fake_archive) / "Sauna"
    # the user replaces the group folder by a link to a real archive folder that
    # holds a link of the same name as the group's: nothing in there may be touched
    elsewhere = fake_archive.root / "Home" / "Elsewhere"
    elsewhere.mkdir(parents=True)
    theirs = fake_archive.link("Home/Elsewhere/b.pdf", f"{BANKS}/a.pdf")
    (elsewhere / "Q1").mkdir()
    os.unlink(base / "2025" / "Q1" / "c.pdf")
    os.rmdir(base / "2025" / "Q1")
    os.unlink(base / "2025" / "b.pdf")
    os.rmdir(base / "2025")
    os.symlink(elsewhere, base / "2025")
    result = app.ongoing.sync()
    assert result.batch is not None and result.batch.failed is None, result.problems
    # the user's link is untouched, and so is everything behind it
    assert readlink(base / "2025") == str(elsewhere)
    assert theirs.is_symlink() and listing(elsewhere) == ["Q1", "b.pdf"]
    # the group is published beside it
    assert listing(base) == ["2025", "2025_2", "a.pdf"]
    assert listing(base / "2025_2") == ["Q1", "b.pdf"]
    assert points_at(base / "2025_2" / "b.pdf", fake_archive, f"{BANKS}/b.pdf")
    c = app.collections.get(c.id)
    assert c.ongoing_status == f"{NOT_MANAGED}{ONG}/Sauna/2025{_REPLACED}"
    assert not any(r.rel.startswith(f"{ONG}/Sauna/2025/") for r in records(app))
    # the primitive refuses to remove anything through the link
    with pytest.raises(GuardError):
        primitives.remove_empty_dir(base / "2025" / "Q1", ongoing(fake_archive))
    assert (elsewhere / "Q1").is_dir()
    # closing takes down the app's tree only; the user's link stays
    app.collections.close(c.id)
    assert listing(base) == ["2025"]
    assert readlink(base / "2025") == str(elsewhere)
    assert theirs.is_symlink() and listing(elsewhere) == ["Q1", "b.pdf"]


def test_removing_the_last_group_returns_to_the_single_link_form(app, fake_archive):
    folder(fake_archive, "Home/2026 Sauna", "d-sauna")
    fake_archive.add("Home/2026 Sauna/plan.pdf", drive_id="id-plan")
    app.scan()
    c = app.collections.create("Sauna")
    g = app.collections.create_group(c.id, "Plans")
    app.collections.set_member_group(c.id, ["d-sauna"], g.id)
    base = ongoing(fake_archive) / "Sauna"
    assert base.is_dir() and not base.is_symlink()  # with a group: never a direct link
    assert listing(base / "Plans") == ["2026 Sauna"]
    assert points_at(base / "Plans" / "2026 Sauna", fake_archive, "Home/2026 Sauna")
    app.collections.remove_group(g.id)
    assert points_at(base, fake_archive, "Home/2026 Sauna")
    assert kinds(app, batches(app)[-1]) == [
        ("unlink_symlink", f"{ONG}/Sauna/Plans/2026 Sauna"),
        ("remove_empty_dir", f"{ONG}/Sauna/Plans"),
        ("remove_empty_dir", f"{ONG}/Sauna"),
        ("symlink", f"{ONG}/Sauna"),
    ]
    assert [(r.rel, r.kind) for r in records(app)] == [(f"{ONG}/Sauna", "link")]
    assert (fake_archive.root / "Home/2026 Sauna/plan.pdf").exists()


def test_an_empty_group_is_published_as_an_empty_folder(app, fake_archive, two_files):
    c = sauna(app)
    app.collections.create_group(c.id, "Later")
    base = ongoing(fake_archive) / "Sauna"
    assert listing(base) == ["Later", "a.pdf", "b.pdf"]
    assert listing(base / "Later") == []
    assert any(r.rel == f"{ONG}/Sauna/Later" and r.kind == "folder" for r in records(app))


def test_preview_for_close_of_a_grouped_collection(app, fake_archive):
    c, y, q = grouped(app, fake_archive)
    ops = app.ongoing.preview_for([c.id], state="closed")
    assert [op.kind for op in ops] == [OpKind.UNLINK_SYMLINK] * 3 + [OpKind.REMOVE_EMPTY_DIR] * 3
    assert listing(ongoing(fake_archive) / "Sauna" / "2025" / "Q1") == ["c.pdf"]


def test_app_folder_swapped_for_a_users_folder_between_plan_and_act_is_left(
    app, fake_archive, two_files, monkeypatch
):
    c = sauna(app)
    app.collections.create_group(c.id, "Later")
    later = ongoing(fake_archive) / "Sauna" / "Later"
    assert listing(later) == []
    real = primitives.remove_empty_dir

    def swapping(path, ongoing_dir, identity=None):
        if path == later:  # the user swaps in an empty folder of their own, just now
            recreate_dir(later)
        return real(path, ongoing_dir, identity=identity)

    monkeypatch.setattr(primitives, "remove_empty_dir", swapping)
    app.collections.close(c.id)
    assert later.is_dir() and listing(later) == []
    rows = journal(app, batches(app)[-1])
    assert [(r.kind, r.state) for r in rows] == [
        ("unlink_symlink", "done"),
        ("unlink_symlink", "done"),
        ("remove_empty_dir", "failed"),
    ]
    assert rows[-1].src == f"{ONG}/Sauna/Later" and "identity" in rows[-1].error
    c = app.collections.get(c.id)
    assert c.ongoing_rel == f"{ONG}/Sauna" and c.ongoing_status.startswith(NOT_MANAGED)
    # the next sync finds a folder with a new identity at the recorded rel: left
    # alone and reported (the Phase 2 identity ruling), never removed
    monkeypatch.setattr(primitives, "remove_empty_dir", real)
    before = journal_count(app)
    result = app.ongoing.sync()
    assert later.is_dir() and listing(ongoing(fake_archive) / "Sauna") == ["Later"]
    assert result.batch is None and journal_count(app) == before
    assert app.collections.get(c.id).ongoing_status == (
        NOT_MANAGED + identity_problem(f"{ONG}/Sauna/Later")
    )


def test_remove_empty_dir_is_planned_with_the_recorded_identity(app, fake_archive, two_files):
    c = sauna(app)
    rec = next(r for r in records(app) if r.kind == "folder")
    ops = app.ongoing.preview_for([c.id], state="closed")
    assert ops[-1].kind is OpKind.REMOVE_EMPTY_DIR
    assert ops[-1].identity == identity.from_columns(rec.st_dev, rec.st_ino, rec.st_birth)


def test_a_member_taking_a_group_folders_name_moves_the_group_to_a_suffix(app, fake_archive):
    fake_archive.add(f"{BANKS}/b.pdf", drive_id="id-b")
    folder(fake_archive, "Home/Tax", "d-tax")
    app.scan()
    c = app.collections.create("Sauna")
    g = app.collections.create_group(c.id, "Tax")
    app.collections.set_member_group(c.id, ["id-b"], g.id)
    base = ongoing(fake_archive) / "Sauna"
    assert listing(base) == ["Tax"] and listing(base / "Tax") == ["b.pdf"]
    app.collections.add_members(c.id, ["d-tax"])  # an ungrouped member named Tax
    # a folder is never kept under the name a member wants: the group moves to Tax_2
    assert listing(base) == ["Tax", "Tax_2"]
    assert points_at(base / "Tax", fake_archive, "Home/Tax")
    assert listing(base / "Tax_2") == ["b.pdf"]
    assert kinds(app, batches(app)[-1]) == [
        ("unlink_symlink", f"{ONG}/Sauna/Tax/b.pdf"),
        ("remove_empty_dir", f"{ONG}/Sauna/Tax"),
        ("symlink", f"{ONG}/Sauna/Tax"),
        ("mkdir", f"{ONG}/Sauna/Tax_2"),
        ("symlink", f"{ONG}/Sauna/Tax_2/b.pdf"),
    ]
    assert app.ongoing.sync().batch is None  # settled: Tax_2 serves the group now
    app.collections.remove_member(c.id, "d-tax")
    assert listing(base) == ["Tax_2"]  # a variant of the wanted name: kept
    assert app.ongoing.sync().batch is None
    # two groups literally named Tax and Tax_2 each keep their own folder: a rename
    # of Tax never takes Tax_2's
    two = app.collections.create("Two")
    tax = app.collections.create_group(two.id, "Tax")
    tax2 = app.collections.create_group(two.id, "Tax_2")
    app.collections.set_member_group(two.id, ["id-b"], tax2.id)
    base = ongoing(fake_archive) / "Two"
    assert listing(base) == ["Tax", "Tax_2"] and listing(base / "Tax_2") == ["b.pdf"]
    app.collections.rename_group(tax.id, "Other")
    assert listing(base) == ["Other", "Tax_2"] and listing(base / "Tax_2") == ["b.pdf"]
    assert kinds(app, batches(app)[-1]) == [
        ("remove_empty_dir", f"{ONG}/Two/Tax"),
        ("mkdir", f"{ONG}/Two/Other"),
    ]


# --- parent collections: Ongoing mirrors the tree (round 2, Task 4) ----------------


def tree(app, fake_archive):
    """Houses (a.pdf) > Sauna (b.pdf) > Deck (c.pdf). Returns the three collections."""
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="id-a")
    fake_archive.add(f"{BANKS}/b.pdf", drive_id="id-b")
    fake_archive.add(f"{BANKS}/c.pdf", drive_id="id-c")
    app.scan()
    houses = app.collections.create("Houses")
    app.collections.add_members(houses.id, ["id-a"])
    sauna = app.collections.create("Sauna", parent_id=houses.id)
    app.collections.add_members(sauna.id, ["id-b"])
    deck = app.collections.create("Deck", parent_id=sauna.id)
    app.collections.add_members(deck.id, ["id-c"])
    return tuple(app.collections.get(c.id) for c in (houses, sauna, deck))


def rels(app, collection_id: int) -> set[str]:
    return {r.rel for r in records(app) if r.collection_id == collection_id}


def test_nested_publish(app, fake_archive):
    houses, sauna, deck = tree(app, fake_archive)
    base = ongoing(fake_archive) / "Houses"
    assert listing(ongoing(fake_archive)) == ["Houses"]
    assert listing(base) == ["Sauna", "a.pdf"]
    assert listing(base / "Sauna") == ["Deck", "b.pdf"]
    assert listing(base / "Sauna" / "Deck") == ["c.pdf"]
    assert points_at(base / "Sauna" / "Deck" / "c.pdf", fake_archive, f"{BANKS}/c.pdf")
    # every entry is recorded for the collection it belongs to
    assert rels(app, houses.id) == {f"{ONG}/Houses", f"{ONG}/Houses/a.pdf"}
    assert rels(app, sauna.id) == {f"{ONG}/Houses/Sauna", f"{ONG}/Houses/Sauna/b.pdf"}
    assert rels(app, deck.id) == {f"{ONG}/Houses/Sauna/Deck", f"{ONG}/Houses/Sauna/Deck/c.pdf"}
    for c, rel in ((houses, "Houses"), (sauna, "Houses/Sauna"), (deck, "Houses/Sauna/Deck")):
        c = app.collections.get(c.id)
        assert (c.ongoing_rel, c.ongoing_status) == (f"{ONG}/{rel}", None)
    # the tree's desired state is one nested Desired, keyed by the root
    want = app.ongoing.desired(app.collections.list(None))
    assert list(want) == ["Houses"]
    assert want["Houses"] == Desired(
        "folder",
        f"{ONG}/Houses",
        links={
            "a.pdf": f"{BANKS}/a.pdf",
            "Sauna/b.pdf": f"{BANKS}/b.pdf",
            "Sauna/Deck/c.pdf": f"{BANKS}/c.pdf",
        },
        folders=("Sauna", "Sauna/Deck"),
        owners={"Sauna": sauna.id, "Sauna/Deck": deck.id},
    )
    # settled
    before = journal_count(app)
    assert app.ongoing.sync().batch is None
    assert journal_count(app) == before


def test_a_parent_without_members_is_a_folder_for_its_children(app, fake_archive):
    folder(fake_archive, "Home/2026 Sauna", "d-sauna")
    fake_archive.add("Home/2026 Sauna/plan.pdf", drive_id="id-plan")
    app.scan()
    estate = app.collections.create("Estate")  # no members of its own
    assert listing(ongoing(fake_archive)) == []  # empty: not published
    sauna = app.collections.create("Sauna", parent_id=estate.id)
    app.collections.add_members(sauna.id, ["d-sauna"])
    base = ongoing(fake_archive) / "Estate"
    assert base.is_dir() and not base.is_symlink()
    # the child has one folder member, no groups, no children: a direct link
    assert points_at(base / "Sauna", fake_archive, "Home/2026 Sauna")
    assert app.collections.get(estate.id).ongoing_rel == f"{ONG}/Estate"
    assert app.collections.get(sauna.id).ongoing_rel == f"{ONG}/Estate/Sauna"
    # a parent with one folder member never takes the single-link form itself
    folder(fake_archive, "Home/Estate docs", "d-estate")
    fake_archive.add("Home/Estate docs/deed.pdf", drive_id="id-deed")
    app.scan()
    app.collections.add_members(estate.id, ["d-estate"])
    assert listing(base) == ["Estate docs", "Sauna"]
    assert points_at(base / "Estate docs", fake_archive, "Home/Estate docs")
    assert app.ongoing.sync().batch is None


def test_move_between_parents(app, fake_archive):
    houses, sauna, deck = tree(app, fake_archive)
    fake_archive.add(f"{BANKS}/d.pdf", drive_id="id-d")
    app.scan()
    cars = app.collections.create("Cars")
    app.collections.add_members(cars.id, ["id-d"])
    n = len(batches(app))
    app.collections.set_parent(sauna.id, cars.id)
    assert len(batches(app)) == n + 1  # take-down plus create: one journaled batch
    assert kinds(app, batches(app)[-1]) == [
        ("unlink_symlink", f"{ONG}/Houses/Sauna/b.pdf"),
        ("unlink_symlink", f"{ONG}/Houses/Sauna/Deck/c.pdf"),
        ("remove_empty_dir", f"{ONG}/Houses/Sauna/Deck"),
        ("remove_empty_dir", f"{ONG}/Houses/Sauna"),
        ("mkdir", f"{ONG}/Cars/Sauna"),
        ("mkdir", f"{ONG}/Cars/Sauna/Deck"),
        ("symlink", f"{ONG}/Cars/Sauna/b.pdf"),
        ("symlink", f"{ONG}/Cars/Sauna/Deck/c.pdf"),
    ]
    assert all(r.state == "done" and r.origin == "workflow" for r in journal(app, batches(app)[-1]))
    assert listing(ongoing(fake_archive) / "Houses") == ["a.pdf"]
    assert listing(ongoing(fake_archive) / "Cars") == ["Sauna", "d.pdf"]
    assert listing(ongoing(fake_archive) / "Cars" / "Sauna" / "Deck") == ["c.pdf"]
    assert rels(app, sauna.id) == {f"{ONG}/Cars/Sauna", f"{ONG}/Cars/Sauna/b.pdf"}
    assert rels(app, deck.id) == {f"{ONG}/Cars/Sauna/Deck", f"{ONG}/Cars/Sauna/Deck/c.pdf"}
    assert app.collections.get(sauna.id).ongoing_rel == f"{ONG}/Cars/Sauna"
    assert app.collections.get(deck.id).ongoing_rel == f"{ONG}/Cars/Sauna/Deck"
    assert app.collections.get(houses.id).ongoing_status is None
    assert app.ongoing.sync().batch is None
    # a sync batch is never undone: the way back is to move it back
    with pytest.raises(OpFailed, match="automatic Ongoing update"):
        app.executor.undo(batches(app)[-1])
    app.collections.set_parent(sauna.id, houses.id)
    assert listing(ongoing(fake_archive) / "Houses" / "Sauna") == ["Deck", "b.pdf"]
    assert listing(ongoing(fake_archive) / "Cars") == ["d.pdf"]


def test_move_to_top_level_and_back_inside(app, fake_archive):
    houses, sauna, deck = tree(app, fake_archive)
    app.collections.set_parent(sauna.id, None)
    assert listing(ongoing(fake_archive)) == ["Houses", "Sauna"]
    assert listing(ongoing(fake_archive) / "Houses") == ["a.pdf"]
    assert listing(ongoing(fake_archive) / "Sauna") == ["Deck", "b.pdf"]
    assert listing(ongoing(fake_archive) / "Sauna" / "Deck") == ["c.pdf"]
    assert rels(app, sauna.id) == {f"{ONG}/Sauna", f"{ONG}/Sauna/b.pdf"}
    assert rels(app, deck.id) == {f"{ONG}/Sauna/Deck", f"{ONG}/Sauna/Deck/c.pdf"}
    assert app.collections.get(sauna.id).ongoing_rel == f"{ONG}/Sauna"
    assert app.ongoing.sync().batch is None
    # and back inside Houses: the top-level entry goes, the nested one comes
    app.collections.set_parent(sauna.id, houses.id)
    assert listing(ongoing(fake_archive)) == ["Houses"]
    assert listing(ongoing(fake_archive) / "Houses" / "Sauna" / "Deck") == ["c.pdf"]
    assert rels(app, deck.id) == {f"{ONG}/Houses/Sauna/Deck", f"{ONG}/Houses/Sauna/Deck/c.pdf"}
    assert app.ongoing.sync().batch is None


def test_move_parent_with_user_file_is_left(app, fake_archive):
    houses, sauna, deck = tree(app, fake_archive)
    fake_archive.add(f"{BANKS}/d.pdf", drive_id="id-d")
    app.scan()
    estate = app.collections.create("Estate")
    app.collections.add_members(estate.id, ["id-d"])
    old = ongoing(fake_archive) / "Houses"
    user = fake_archive.add(f"{ONG}/Houses/notes.txt", content=b"mine", drive_id="user-1")
    app.collections.set_parent(houses.id, estate.id)
    # the folder with the user's file stays, untouched, and so does the file
    assert listing(old) == ["notes.txt"]
    assert user.read_bytes() == b"mine"
    rows = journal(app, batches(app)[-1])
    assert {r.state for r in rows} == {"done"}
    assert [r.src for r in rows if r.kind == "remove_empty_dir"] == [
        f"{ONG}/Houses/Sauna/Deck",
        f"{ONG}/Houses/Sauna",
    ]
    # the tree is published at its new place
    new = ongoing(fake_archive) / "Estate" / "Houses"
    assert listing(ongoing(fake_archive) / "Estate") == ["Houses", "d.pdf"]
    assert listing(new) == ["Sauna", "a.pdf"]
    assert listing(new / "Sauna" / "Deck") == ["c.pdf"]
    # and the problem is reported, on the collection whose folder it is
    h = app.collections.get(houses.id)
    assert h.ongoing_status == f"{NOT_MANAGED}{ONG}/Houses {HOLDS_1}"
    assert app.collections.get(estate.id).ongoing_status is None
    # still owned (the record matches): no retry noise while the file is there
    assert f"{ONG}/Houses" in rels(app, houses.id)
    before = journal_count(app)
    assert app.ongoing.sync().batch is None
    assert journal_count(app) == before
    # the user takes the file away: the next sync finishes the job
    os.rename(user, fake_archive.root / BANKS / "notes.txt")
    app.ongoing.sync()
    assert listing(ongoing(fake_archive)) == ["Estate"]
    assert app.collections.get(houses.id).ongoing_status is None
    assert app.collections.get(houses.id).ongoing_rel == f"{ONG}/Estate/Houses"


def test_closing_a_child_with_user_file_keeps_the_path_and_the_parent(app, fake_archive):
    houses, sauna, deck = tree(app, fake_archive)
    user = fake_archive.add(f"{ONG}/Houses/Sauna/Deck/notes.txt", content=b"mine", drive_id="u-1")
    app.collections.close(deck.id)
    base = ongoing(fake_archive) / "Houses"
    assert listing(base / "Sauna") == ["Deck", "b.pdf"]
    assert listing(base / "Sauna" / "Deck") == ["notes.txt"]
    assert user.read_bytes() == b"mine"
    assert [r.kind for r in journal(app, batches(app)[-1])] == ["unlink_symlink"]
    d = app.collections.get(deck.id)
    assert d.ongoing_status == (f"{NOT_MANAGED}{ONG}/Houses/Sauna/Deck {HOLDS_1}")
    assert d.ongoing_rel == f"{ONG}/Houses/Sauna/Deck"
    # the parent that wanted it gone says so too; the grandparent is untouched
    assert app.collections.get(sauna.id).ongoing_status == d.ongoing_status
    assert app.collections.get(houses.id).ongoing_status is None
    assert app.ongoing.sync().batch is None


def test_child_and_member_name_clash_is_stable(app, fake_archive):
    folder(fake_archive, "Home/Sauna", "d-sauna")
    fake_archive.add("Home/Sauna/plan.pdf", drive_id="id-plan")
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="id-a")
    fake_archive.add(f"{BANKS}/b.pdf", drive_id="id-b")
    app.scan()
    houses = app.collections.create("Houses")
    app.collections.add_members(houses.id, ["d-sauna", "id-a"])  # a link named Sauna
    sauna = app.collections.create("Sauna", parent_id=houses.id)  # a child named Sauna
    app.collections.add_members(sauna.id, ["id-b"])
    base = ongoing(fake_archive) / "Houses"
    assert listing(base) == ["Sauna", "Sauna_2", "a.pdf"]
    assert points_at(base / "Sauna", fake_archive, "Home/Sauna")
    assert listing(base / "Sauna_2") == ["b.pdf"]
    assert app.collections.get(sauna.id).ongoing_rel == f"{ONG}/Houses/Sauna_2"
    # stable: the next syncs do nothing, and a change elsewhere keeps Sauna_2
    assert app.ongoing.sync().batch is None
    app.collections.remove_member(houses.id, "id-a")
    assert listing(base) == ["Sauna", "Sauna_2"]
    assert kinds(app, batches(app)[-1]) == [("unlink_symlink", f"{ONG}/Houses/a.pdf")]
    assert app.ongoing.sync().batch is None
    # a group named like the child too: siblings of every kind get a suffix
    g = app.collections.create_group(houses.id, "Sauna")
    assert listing(base) == ["Sauna", "Sauna_2", "Sauna_3"]
    assert listing(base / "Sauna_2") == ["b.pdf"]  # the child keeps its folder
    assert listing(base / "Sauna_3") == []
    assert app.ongoing.sync().batch is None
    app.collections.remove_group(g.id)
    assert listing(base) == ["Sauna", "Sauna_2"]


def test_closing_a_child_removes_only_its_subtree(app, fake_archive):
    houses, sauna, deck = tree(app, fake_archive)
    app.collections.close(deck.id)
    assert kinds(app, batches(app)[-1]) == [
        ("unlink_symlink", f"{ONG}/Houses/Sauna/Deck/c.pdf"),
        ("remove_empty_dir", f"{ONG}/Houses/Sauna/Deck"),
    ]
    base = ongoing(fake_archive) / "Houses"
    assert listing(base) == ["Sauna", "a.pdf"]
    assert listing(base / "Sauna") == ["b.pdf"]
    assert rels(app, deck.id) == set()
    d = app.collections.get(deck.id)
    assert (d.ongoing_rel, d.ongoing_status) == (None, None)
    assert app.collections.get(sauna.id).ongoing_rel == f"{ONG}/Houses/Sauna"
    app.collections.close(sauna.id)
    assert kinds(app, batches(app)[-1]) == [
        ("unlink_symlink", f"{ONG}/Houses/Sauna/b.pdf"),
        ("remove_empty_dir", f"{ONG}/Houses/Sauna"),
    ]
    assert listing(base) == ["a.pdf"]
    assert app.collections.get(houses.id).ongoing_rel == f"{ONG}/Houses"
    # reopening brings it back under its parent
    app.collections.reopen(sauna.id)
    assert listing(base / "Sauna") == ["b.pdf"]


def test_unpublishing_a_parent_takes_its_children_down_too(app, fake_archive):
    houses, sauna, deck = tree(app, fake_archive)
    app.collections.set_publish(houses.id, "ongoing", False)
    assert listing(ongoing(fake_archive)) == []
    assert records(app) == []
    # the hidden subtree says why (a status only: nothing else changes)
    c = app.collections.get(houses.id)
    assert (c.ongoing_rel, c.ongoing_status) == (None, None)
    c = app.collections.get(sauna.id)
    assert (c.ongoing_rel, c.ongoing_status) == (None, f"{NOT_SHOWN}{hidden_by('Houses')}")
    c = app.collections.get(deck.id)
    assert (c.ongoing_rel, c.ongoing_status) == (None, f"{NOT_SHOWN}{hidden_by('Sauna')}")
    assert app.ongoing.sync().batch is None
    app.collections.set_publish(houses.id, "ongoing", True)
    assert listing(ongoing(fake_archive) / "Houses" / "Sauna" / "Deck") == ["c.pdf"]
    for c in (houses, sauna, deck):
        assert app.collections.get(c.id).ongoing_status is None


def hidden_by(parent: str) -> str:
    return f"its parent collection '{parent}' is not shown in {ONG}."


def test_a_hidden_subtree_status_is_only_for_what_would_be_shown(app, fake_archive):
    """A child that is closed, unpublished or empty is not shown for its own
    reasons: no "its parent" status. A "not managed" note is never replaced."""
    houses, sauna, deck = tree(app, fake_archive)
    empty = app.collections.create("Attic", parent_id=sauna.id)
    app.collections.set_publish(deck.id, "ongoing", False)
    app.collections.set_publish(houses.id, "ongoing", False)
    assert app.collections.get(sauna.id).ongoing_status == f"{NOT_SHOWN}{hidden_by('Houses')}"
    assert app.collections.get(deck.id).ongoing_status is None  # unpublished itself
    assert app.collections.get(empty.id).ongoing_status is None  # nothing to show
    # a closed child (stale: the service refuses to close a parent with open
    # children, so Deck is closed first here) gets no status either
    app.collections.set_publish(deck.id, "ongoing", True)
    app.collections.close(deck.id)
    assert app.collections.get(deck.id).ongoing_status is None
    app.collections.reopen(deck.id)
    assert app.collections.get(deck.id).ongoing_status == f"{NOT_SHOWN}{hidden_by('Sauna')}"
    # a leftover of the user's keeps its "not managed" note instead
    app.collections.set_publish(houses.id, "ongoing", True)
    (ongoing(fake_archive) / "Houses" / "Sauna" / "mine.txt").write_text("x", encoding="utf-8")
    app.collections.set_publish(houses.id, "ongoing", False)
    status = app.collections.get(sauna.id).ongoing_status
    assert status.startswith(NOT_MANAGED) and "mine.txt" not in status
    assert f"{ONG}/Houses/Sauna {HOLDS_1}" in status


def test_stale_open_child_under_a_closed_parent_is_taken_down(app, fake_archive):
    houses, sauna, deck = tree(app, fake_archive)
    app.collections.on_change = None
    with write_tx(app.engine) as conn:  # bypass the service's refusal: stale state
        conn.execute(
            update(collections_table)
            .where(collections_table.c.id == sauna.id)
            .values(state="closed")
        )
    app.ongoing.sync()
    assert listing(ongoing(fake_archive) / "Houses") == ["a.pdf"]
    assert rels(app, deck.id) == set() and rels(app, sauna.id) == set()


def test_renaming_a_parent_moves_the_whole_tree(app, fake_archive):
    houses, sauna, deck = tree(app, fake_archive)
    app.collections.set_name(houses.id, "Homes")
    assert listing(ongoing(fake_archive)) == ["Homes"]
    assert listing(ongoing(fake_archive) / "Homes" / "Sauna" / "Deck") == ["c.pdf"]
    assert rels(app, deck.id) == {f"{ONG}/Homes/Sauna/Deck", f"{ONG}/Homes/Sauna/Deck/c.pdf"}
    app.collections.set_name(sauna.id, "Spa")
    assert listing(ongoing(fake_archive) / "Homes") == ["Spa", "a.pdf"]
    assert listing(ongoing(fake_archive) / "Homes" / "Spa" / "Deck") == ["c.pdf"]
    assert app.ongoing.sync().batch is None


def test_preview_for_close_of_a_child_shows_only_its_subtree(app, fake_archive):
    houses, sauna, deck = tree(app, fake_archive)
    ops = app.ongoing.preview_for([sauna.id], state="closed")
    assert [(op.kind, op.src) for op in ops] == [
        (OpKind.UNLINK_SYMLINK, f"{ONG}/Houses/Sauna/b.pdf"),
        (OpKind.UNLINK_SYMLINK, f"{ONG}/Houses/Sauna/Deck/c.pdf"),
        (OpKind.REMOVE_EMPTY_DIR, f"{ONG}/Houses/Sauna/Deck"),
        (OpKind.REMOVE_EMPTY_DIR, f"{ONG}/Houses/Sauna"),
    ]
    rec = next(r for r in records(app) if r.rel == f"{ONG}/Houses/Sauna")
    assert ops[-1].identity == identity.from_columns(rec.st_dev, rec.st_ino, rec.st_birth)
    assert listing(ongoing(fake_archive) / "Houses" / "Sauna") == ["Deck", "b.pdf"]  # read only


def test_a_users_folder_at_the_childs_name_is_untouched(app, fake_archive):
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="id-a")
    fake_archive.add(f"{BANKS}/b.pdf", drive_id="id-b")
    app.scan()
    houses = app.collections.create("Houses")
    app.collections.add_members(houses.id, ["id-a"])
    user = fake_archive.add(f"{ONG}/Houses/Sauna/mine.txt", content=b"mine", drive_id="u-1")
    sauna = app.collections.create("Sauna", parent_id=houses.id)
    app.collections.add_members(sauna.id, ["id-b"])
    base = ongoing(fake_archive) / "Houses"
    assert listing(base) == ["Sauna", "Sauna_2", "a.pdf"]
    assert listing(base / "Sauna") == ["mine.txt"] and user.read_bytes() == b"mine"
    assert listing(base / "Sauna_2") == ["b.pdf"]
    app.collections.close(sauna.id)
    assert listing(base) == ["Sauna", "a.pdf"]
    assert listing(base / "Sauna") == ["mine.txt"]
    assert app.collections.get(houses.id).ongoing_status is None


def test_move_inside_with_user_file_in_the_old_folder_is_left(app, fake_archive):
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="id-a")
    fake_archive.add(f"{BANKS}/b.pdf", drive_id="id-b")
    app.scan()
    houses = app.collections.create("Houses")
    app.collections.add_members(houses.id, ["id-a"])
    sauna = app.collections.create("Sauna")
    app.collections.add_members(sauna.id, ["id-b"])
    old = ongoing(fake_archive) / "Sauna"
    user = fake_archive.add(f"{ONG}/Sauna/notes.txt", content=b"mine", drive_id="user-1")
    app.collections.set_parent(sauna.id, houses.id)
    # the old top-level folder (a stray now) loses its link and stays, with the file
    assert listing(old) == ["notes.txt"] and user.read_bytes() == b"mine"
    assert kinds(app, batches(app)[-1]) == [
        ("unlink_symlink", f"{ONG}/Sauna/b.pdf"),
        ("mkdir", f"{ONG}/Houses/Sauna"),
        ("symlink", f"{ONG}/Houses/Sauna/b.pdf"),
    ]
    assert listing(ongoing(fake_archive) / "Houses" / "Sauna") == ["b.pdf"]
    s = app.collections.get(sauna.id)
    assert s.ongoing_status == f"{NOT_MANAGED}{ONG}/Sauna {HOLDS_1}"
    assert s.ongoing_rel == f"{ONG}/Houses/Sauna"  # its place under its parent, not the stray
    assert app.collections.get(houses.id).ongoing_status is None
    assert app.ongoing.sync().batch is None
    os.rename(user, fake_archive.root / BANKS / "notes.txt")
    app.ongoing.sync()
    assert listing(ongoing(fake_archive)) == ["Houses"]
    s = app.collections.get(sauna.id)
    assert (s.ongoing_rel, s.ongoing_status) == (f"{ONG}/Houses/Sauna", None)
    assert rels(app, sauna.id) == {f"{ONG}/Houses/Sauna", f"{ONG}/Houses/Sauna/b.pdf"}


def test_a_parent_losing_its_last_member_keeps_its_folder_for_its_child(app, fake_archive):
    houses, sauna, deck = tree(app, fake_archive)
    app.collections.remove_member(houses.id, "id-a")
    assert kinds(app, batches(app)[-1]) == [("unlink_symlink", f"{ONG}/Houses/a.pdf")]
    assert listing(ongoing(fake_archive) / "Houses") == ["Sauna"]
    assert app.collections.get(houses.id).ongoing_rel == f"{ONG}/Houses"
    assert app.ongoing.sync().batch is None
    # and once the children are closed, the empty parent goes too (deepest first)
    app.collections.close(deck.id)
    assert listing(ongoing(fake_archive) / "Houses" / "Sauna") == ["b.pdf"]
    app.collections.close(sauna.id)
    assert listing(ongoing(fake_archive)) == []
    assert kinds(app, batches(app)[-1]) == [
        ("unlink_symlink", f"{ONG}/Houses/Sauna/b.pdf"),
        ("remove_empty_dir", f"{ONG}/Houses/Sauna"),
        ("remove_empty_dir", f"{ONG}/Houses"),
    ]
    assert records(app) == []
    h = app.collections.get(houses.id)
    assert (h.ongoing_rel, h.ongoing_status) == (None, None)


def test_move_between_parents_with_user_file_reports_the_leftover(app, fake_archive):
    houses, sauna, deck = tree(app, fake_archive)
    fake_archive.add(f"{BANKS}/d.pdf", drive_id="id-d")
    app.scan()
    cars = app.collections.create("Cars")
    app.collections.add_members(cars.id, ["id-d"])
    old = ongoing(fake_archive) / "Houses" / "Sauna"
    user = fake_archive.add(f"{ONG}/Houses/Sauna/notes.txt", content=b"mine", drive_id="user-1")
    app.collections.set_parent(sauna.id, cars.id)
    # the folder with the user's file is kept (its links and Deck went), and the
    # tree is published under Cars
    assert listing(old) == ["notes.txt"] and user.read_bytes() == b"mine"
    assert listing(ongoing(fake_archive) / "Cars" / "Sauna") == ["Deck", "b.pdf"]
    assert {r.state for r in journal(app, batches(app)[-1])} == {"done"}
    note = f"{NOT_MANAGED}{ONG}/Houses/Sauna {HOLDS_1}"
    s = app.collections.get(sauna.id)
    assert s.ongoing_status == note  # the collection that moved away
    assert s.ongoing_rel == f"{ONG}/Cars/Sauna"  # its place under its parent now
    assert app.collections.get(houses.id).ongoing_status == note  # the old parent
    assert app.collections.get(cars.id).ongoing_status is None
    assert app.collections.get(deck.id).ongoing_status is None
    # quiet while the file is there
    before = journal_count(app)
    assert app.ongoing.sync().batch is None
    assert journal_count(app) == before
    assert app.collections.get(sauna.id).ongoing_status == note
    os.rename(user, fake_archive.root / BANKS / "notes.txt")
    app.ongoing.sync()
    assert listing(ongoing(fake_archive) / "Houses") == ["a.pdf"]
    assert app.collections.get(sauna.id).ongoing_status is None
    assert app.collections.get(houses.id).ongoing_status is None


def test_a_parent_cycle_is_logged_and_left_alone(app, fake_archive, caplog):
    houses, sauna, deck = tree(app, fake_archive)
    app.collections.on_change = None
    with write_tx(app.engine) as conn:  # bypass the service's refusal: corrupt state
        conn.execute(
            update(collections_table)
            .where(collections_table.c.id == houses.id)
            .values(parent_id=deck.id)
        )
    with caplog.at_level(logging.WARNING):
        result = app.ongoing.sync()
    assert result.batch is None and result.plan == []
    assert "parent cycle" in caplog.text and "'Houses'" in caplog.text
    assert listing(ongoing(fake_archive) / "Houses" / "Sauna" / "Deck") == ["c.pdf"]


# --- an extra archive folder that is not connected ---------------------------------------


def _unplug(extra_folder, tmp_path) -> Path:
    away = tmp_path / "unplugged"
    os.rename(extra_folder.root, away)
    return away


def test_ongoing_sync_plans_nothing_for_offline_folder(extra_folder, app, fake_archive, tmp_path):
    extra_folder.add("2009/x.pdf", drive_id="x1")
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="id-a")
    app.scan()
    sauna(app, ["x1", "id-a"])
    base = ongoing(fake_archive) / "Sauna"
    assert listing(base) == ["a.pdf", "x.pdf"]
    away = _unplug(extra_folder, tmp_path)
    app.scan()
    result = app.ongoing.sync(dry_run=True)
    assert (result.plan, result.problems) == ([], [])
    # a change in the main folder is still published; the offline member's link stays
    os.rename(fake_archive.root / BANKS / "a.pdf", fake_archive.root / BANKS / "a2.pdf")
    app.scan()
    plan = app.ongoing.sync(dry_run=True).plan
    assert [op.kind for op in plan] == [OpKind.UNLINK_SYMLINK, OpKind.SYMLINK]
    assert plan[1].dst == f"{ONG}/Sauna/a2.pdf"
    assert not any("x.pdf" in f"{op.src} {op.dst}" for op in plan)
    result = app.ongoing.sync()
    assert result.batch is not None and result.batch.failed is None
    assert result.problems == []
    assert listing(base) == ["a2.pdf", "x.pdf"]
    assert os.path.islink(base / "x.pdf")
    assert app.collections.get(app.collections.list(None)[0].id).ongoing_status is None
    os.rename(away, extra_folder.root)
    app.scan()
    assert app.ongoing.sync().batch is None  # the link was right all along
    assert (base / "x.pdf").exists()


def test_offline_member_gets_its_link_when_back(extra_folder, app, fake_archive, tmp_path):
    extra_folder.add("2009/x.pdf", drive_id="x1")
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="id-a")
    app.scan()
    c = sauna(app, ["id-a"])
    away = _unplug(extra_folder, tmp_path)
    app.collections.add_members(c.id, ["x1"])
    base = ongoing(fake_archive) / "Sauna"
    assert listing(base) == ["a.pdf"]
    result = app.ongoing.sync(dry_run=True)
    assert (result.plan, result.problems) == ([], [])
    assert app.collections.get(c.id).ongoing_status is None
    os.rename(away, extra_folder.root)
    app.ongoing.sync()
    assert listing(base) == ["a.pdf", "x.pdf"]
    assert (base / "x.pdf").exists()


def test_offline_member_link_is_never_taken_down(extra_folder, app, fake_archive, tmp_path):
    folder(extra_folder, "2009/car", "d-car")
    extra_folder.add("2009/x.pdf", drive_id="x1")
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="id-a")
    app.scan()
    c = sauna(app, ["x1", "id-a"])
    car = app.collections.create("Car")
    app.collections.add_members(car.id, ["d-car"])
    base = ongoing(fake_archive) / "Sauna"
    assert os.path.islink(ongoing(fake_archive) / "Car")
    away = _unplug(extra_folder, tmp_path)
    app.scan()
    app.collections.remove_members(c.id, ["x1"])
    app.collections.close(car.id)
    plan = app.ongoing.sync(dry_run=True).plan
    assert plan == []
    app.ongoing.sync()
    assert listing(base) == ["a.pdf", "x.pdf"]
    assert os.path.islink(ongoing(fake_archive) / "Car")
    os.rename(away, extra_folder.root)
    app.ongoing.sync()  # back: now it goes
    assert listing(base) == ["a.pdf"]
    assert not os.path.lexists(ongoing(fake_archive) / "Car")


def test_links_into_a_detached_folder_are_left_alone(extra_folder, app, app_paths, fake_archive):
    from dam.app import App
    from dam.archive_folders import detach_folder

    extra_folder.add("2009/x.pdf", drive_id="x1")
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="id-a")
    app.scan()
    sauna(app, ["x1", "id-a"])
    base = ongoing(fake_archive) / "Sauna"
    assert listing(base) == ["a.pdf", "x.pdf"]
    detach_folder(app_paths, app.repo, "Old years", forget=False, dry_run=False)
    again = App.create(app_paths.data_dir)
    try:
        result = again.ongoing.sync()
        assert (result.plan, result.problems) == ([], [])
        assert listing(base) == ["a.pdf", "x.pdf"]
    finally:
        again.close()
