"""Dropping files on a folder: Move, Link and Copy, rows of ``##. Ongoing`` and
``##. Important`` standing for the file they link to, a restore into a folder, and the
undo of each (a link the app made is removed anywhere; a copy goes to ``##. To Delete``)."""

import os
import stat

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from dam.api import create_api
from dam.db.tables import operations
from dam.errors import InvalidRequest
from dam.ops import primitives
from dam.ops.model import GuardError, Op, OpKind, Plan
from dam.ops.planner import COLLISION_NOTE

INBOX = "##. Organize"
ONG = "##. Ongoing"
IMP = "##. Important"
QUAR = "##. To Delete"
BANKS = "10. Financial/Banks"
HOME = "20. Home"
IMPORTANT_REFUSAL = "This file is marked Important; unmark it first"
BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}


def journal(app) -> list:
    with app.engine.connect() as conn:
        return list(conn.execute(select(operations).order_by(operations.c.id)).mappings())


@pytest.fixture
def filed(app, fake_archive):
    fake_archive.add(f"{BANKS}/a.pdf", b"aaa", drive_id="id-a")
    fake_archive.add(f"{BANKS}/b.pdf", b"bbb", drive_id="id-b")
    (fake_archive.root / HOME).mkdir(exist_ok=True)
    fake_archive.add(f"{HOME}/keep.pdf", b"k", drive_id="id-k")
    app.scan()
    return fake_archive


@pytest.fixture
def client(app):
    with TestClient(create_api(app, None), base_url=BASE) as c:
        yield c


def collect(app, fake_archive, ids, name="Sauna"):
    c = app.collections.create(name)
    app.collections.add_members(c.id, ids)
    app.ongoing.sync()
    app.scan()
    return fake_archive.root / ONG / name


# --- Link -----------------------------------------------------------------------------


def test_link_makes_a_link_and_leaves_the_file(app, filed):
    dry = app.browse.move(["id-a"], HOME, origin="ui", dry_run=True, mode="link")
    assert [(o.kind, o.src, o.dst) for o in dry.done] == [
        (OpKind.SYMLINK, f"{BANKS}/a.pdf", f"{HOME}/a.pdf")
    ]
    assert not os.path.lexists(filed.root / HOME / "a.pdf")  # a dry run changes nothing
    result = app.browse.move(["id-a"], HOME, origin="ui", mode="link")
    assert result.failed is None and result.error is None
    link = filed.root / HOME / "a.pdf"
    assert link.is_symlink() and link.read_bytes() == b"aaa"
    assert (filed.root / BANKS / "a.pdf").read_bytes() == b"aaa"  # the original stays
    assert app.repo.get("id-a").path == f"{BANKS}/a.pdf"
    assert app.repo.by_path(f"{HOME}/a.pdf").is_link  # indexed right away
    rows = [r for r in journal(app) if r["batch_id"] == result.batch_id]
    assert {r["label"] for r in rows} == {f"Linked a.pdf in {HOME}"}
    assert {r["origin"] for r in rows} == {"ui"}


def test_undo_of_link_removes_the_link_the_app_made(app, filed):
    result = app.browse.move(["id-a", "id-b"], HOME, origin="ui", mode="link")
    assert app.activity.get(result.batch_id).undoable
    outcome = app.activity.undo(result.batch_id)
    assert outcome.batch.failed is None and outcome.batch.error is None
    assert not os.path.lexists(filed.root / HOME / "a.pdf")
    assert not os.path.lexists(filed.root / HOME / "b.pdf")
    assert (filed.root / BANKS / "a.pdf").read_bytes() == b"aaa"
    assert app.activity.get(result.batch_id).undone
    assert app.repo.by_path(f"{HOME}/a.pdf").missing  # out of the index at once


def test_undo_of_link_refuses_a_regular_file_in_its_place(app, filed):
    result = app.browse.move(["id-a"], HOME, origin="ui", mode="link")
    link = filed.root / HOME / "a.pdf"
    primitives.unlink_symlink(link, filed.root)  # the user swapped it for their own file
    link.write_bytes(b"mine")
    with pytest.raises(Exception, match="cannot be undone"):
        app.activity.undo(result.batch_id)
    assert link.read_bytes() == b"mine"


def test_undo_of_link_refuses_a_link_the_app_did_not_make(app, filed):
    result = app.browse.move(["id-a"], HOME, origin="ui", mode="link")
    link = filed.root / HOME / "a.pdf"
    primitives.unlink_symlink(link, filed.root)
    link.symlink_to(filed.root / BANKS / "b.pdf")  # somebody's own link, another target
    with pytest.raises(Exception, match="cannot be undone"):
        app.activity.undo(result.batch_id)
    assert link.is_symlink()


def test_a_plain_plan_cannot_remove_a_link_outside_the_publish_roots(app, filed):
    app.browse.move(["id-a"], HOME, origin="ui", mode="link")
    for op in (
        Op(OpKind.UNLINK_SYMLINK, f"{HOME}/a.pdf", None),
        Op(OpKind.UNLINK_SYMLINK, f"{HOME}/a.pdf", f"{BANKS}/a.pdf", exact=True),
    ):
        with pytest.raises(GuardError, match="can be removed"):
            app.executor.apply(Plan([op], origin="ui"))
    assert (filed.root / HOME / "a.pdf").is_symlink()


def test_link_into_the_files_own_folder_needs_no_op(app, filed):
    assert app.browse.move_preview(["id-a"], BANKS, origin="ui", mode="link") == []
    result = app.browse.move(["id-a"], BANKS, origin="ui", mode="link")
    assert result.done == [] and result.unchanged == ["id-a"]


def test_link_with_a_taken_name_gets_a_number(app, filed):
    filed.add(f"{HOME}/a.pdf", b"other", drive_id="id-other")
    app.scan()
    [op] = app.browse.move_preview(["id-a"], HOME, origin="ui", mode="link")
    assert (op.dst, op.note) == (f"{HOME}/a_2.pdf", COLLISION_NOTE)


def test_link_refused_without_the_symlink_privilege(app, filed, monkeypatch):
    monkeypatch.setattr("dam.services.browse.can_make_links", lambda: False)
    with pytest.raises(InvalidRequest, match="Developer Mode"):
        app.browse.move_preview(["id-a"], HOME, origin="ui", mode="link")


# --- Copy -----------------------------------------------------------------------------


def test_copy_makes_a_copy_and_undo_moves_it_to_to_delete(app, filed):
    dry = app.browse.move(["id-a"], HOME, origin="ui", dry_run=True, mode="copy")
    assert [(o.kind, o.src, o.dst) for o in dry.done] == [
        (OpKind.COPY, f"{BANKS}/a.pdf", f"{HOME}/a.pdf")
    ]
    result = app.browse.move(["id-a"], HOME, origin="ui", mode="copy")
    assert result.failed is None and result.error is None
    assert (filed.root / HOME / "a.pdf").read_bytes() == b"aaa"
    assert (filed.root / BANKS / "a.pdf").read_bytes() == b"aaa"
    assert app.repo.by_path(f"{HOME}/a.pdf") is not None  # indexed right away
    rows = [r for r in journal(app) if r["batch_id"] == result.batch_id]
    assert {r["label"] for r in rows} == {f"Copied a.pdf to {HOME}"}
    assert rows[0]["drive_id"] is None  # the row is about the new file, not the original's id

    outcome = app.activity.undo(result.batch_id)
    assert outcome.batch.failed is None and outcome.batch.error is None
    assert not os.path.lexists(filed.root / HOME / "a.pdf")
    assert (filed.root / QUAR / HOME / "a.pdf").read_bytes() == b"aaa"  # moved, never deleted
    assert (filed.root / BANKS / "a.pdf").read_bytes() == b"aaa"
    assert app.activity.get(result.batch_id).undone


def test_copy_into_the_files_own_folder_gets_a_number(app, filed):
    [op] = app.browse.move_preview(["id-a"], BANKS, origin="ui", mode="copy")
    assert (op.kind, op.dst, op.note) == (OpKind.COPY, f"{BANKS}/a_2.pdf", COLLISION_NOTE)
    app.browse.move(["id-a"], BANKS, origin="ui", mode="copy")
    assert (filed.root / BANKS / "a_2.pdf").read_bytes() == b"aaa"


# --- where Link and Copy may go --------------------------------------------------------


@pytest.mark.parametrize("mode", ["link", "copy"])
@pytest.mark.parametrize("folder", [ONG, f"{ONG}/Sauna", IMP, QUAR, f"{QUAR}/{BANKS}", ""])
def test_nothing_is_linked_or_copied_into_the_apps_folders(app, filed, mode, folder):
    with pytest.raises(InvalidRequest):
        app.browse.move_preview(["id-a"], folder, origin="ui", mode=mode)
    assert not os.path.lexists(filed.root / ONG / "a.pdf")


def test_the_guard_refuses_a_copy_into_the_apps_folders_and_from_them(app, filed):
    for dst in (ONG, IMP, QUAR, "", f"{ONG}/x"):
        with pytest.raises(GuardError):
            app.executor.preview(Plan([Op(OpKind.COPY, f"{BANKS}/a.pdf", dst)], origin="ui"))
    with pytest.raises(GuardError):
        app.executor.preview(Plan([Op(OpKind.COPY, f"{QUAR}/x/a.pdf", HOME)], origin="ui"))
    with pytest.raises(GuardError):
        app.executor.preview(
            Plan([Op(OpKind.COPY, f"{BANKS}/a.pdf", HOME, exact=True)], origin="ui")
        )


def test_a_link_or_a_folder_is_not_copied(app, filed):
    app.browse.move(["id-a"], HOME, origin="ui", mode="link")
    link = app.repo.by_path(f"{HOME}/a.pdf")
    folder = app.repo.by_path(BANKS)
    for rec in (link, folder):
        for mode in ("link", "copy"):
            with pytest.raises(InvalidRequest):
                app.browse.move_preview([rec.drive_id], f"{HOME}", origin="ui", mode=mode)


def test_unknown_mode_is_refused(app, filed):
    with pytest.raises(InvalidRequest, match="unknown way"):
        app.browse.move_preview(["id-a"], HOME, origin="ui", mode="teleport")


# --- rows of Ongoing and Important ----------------------------------------------------------


def test_moving_an_ongoing_row_moves_the_real_file_and_the_link_follows(app, filed):
    base = collect(app, filed, ["id-a"])
    row = app.repo.by_path(f"{ONG}/Sauna/a.pdf")
    assert row.is_link
    preview = app.browse.move_preview([row.drive_id], HOME, origin="ui")
    assert [(o.kind, o.src, o.dst) for o in preview] == [
        (OpKind.MOVE, f"{BANKS}/a.pdf", f"{HOME}/a.pdf")
    ]
    result = app.browse.move([row.drive_id], HOME, origin="ui")
    assert result.failed is None and result.error is None
    assert (filed.root / HOME / "a.pdf").read_bytes() == b"aaa"
    assert not (filed.root / BANKS / "a.pdf").exists()
    assert {r["label"] for r in journal(app) if r["batch_id"] == result.batch_id} == {
        f"Moved a.pdf to {HOME}"
    }
    # still a member of its collection: the usual rebuild repoints the link
    app.scan()
    app.ongoing.sync()
    assert (base / "a.pdf").is_symlink() and (base / "a.pdf").read_bytes() == b"aaa"
    assert app.collections.member_paths(app.collections.list()[-1].id)


def test_moving_an_ongoing_row_to_the_real_files_own_folder_changes_nothing(app, filed):
    collect(app, filed, ["id-a"])
    row = app.repo.by_path(f"{ONG}/Sauna/a.pdf")
    assert app.browse.move_preview([row.drive_id], BANKS, origin="ui") == []


def test_two_rows_of_one_file_move_it_once(app, filed):
    collect(app, filed, ["id-a"], "Sauna")
    collect(app, filed, ["id-a"], "Garden")
    rows = [app.repo.by_path(f"{ONG}/{n}/a.pdf").drive_id for n in ("Sauna", "Garden")]
    preview = app.browse.move_preview(rows, HOME, origin="ui")
    assert [(o.kind, o.src) for o in preview] == [(OpKind.MOVE, f"{BANKS}/a.pdf")]


@pytest.mark.parametrize("mode", ["link", "copy"])
def test_link_and_copy_of_an_ongoing_row_act_on_the_original(app, filed, mode):
    collect(app, filed, ["id-a"])
    row = app.repo.by_path(f"{ONG}/Sauna/a.pdf")
    [op] = app.browse.move_preview([row.drive_id], HOME, origin="ui", mode=mode)
    assert (op.src, op.dst) == (f"{BANKS}/a.pdf", f"{HOME}/a.pdf")
    result = app.browse.move([row.drive_id], HOME, origin="ui", mode=mode)
    assert result.error is None
    target = filed.root / HOME / "a.pdf"
    assert target.is_symlink() == (mode == "link")
    assert target.read_bytes() == b"aaa"


def test_an_ongoing_link_that_leads_nowhere_is_refused(app, filed):
    filed.link(f"{ONG}/dead.pdf", "../nowhere/dead.pdf")
    app.scan()
    row = app.repo.by_path(f"{ONG}/dead.pdf")
    for mode in ("move", "link", "copy"):
        with pytest.raises(InvalidRequest, match="points outside the archive or to nothing"):
            app.browse.move_preview([row.drive_id], HOME, origin="ui", mode=mode)


def test_an_important_row_refuses_move_but_allows_link_and_copy(app, filed):
    app.marks.mark_important(["id-a"], None)
    app.scan()
    row = app.repo.by_path(f"{IMP}/a.pdf")
    assert row is not None and row.is_link
    with pytest.raises(InvalidRequest, match=IMPORTANT_REFUSAL):
        app.browse.move_preview([row.drive_id], HOME, origin="ui")
    for mode in ("link", "copy"):
        [op] = app.browse.move_preview([row.drive_id], HOME, origin="ui", mode=mode)
        assert (op.src, op.dst) == (f"{BANKS}/a.pdf", f"{HOME}/a.pdf")
    result = app.browse.move([row.drive_id], HOME, origin="ui", mode="copy")
    assert result.error is None and (filed.root / HOME / "a.pdf").read_bytes() == b"aaa"
    assert (filed.root / BANKS / "a.pdf").exists()


def test_an_ongoing_row_of_an_important_file_refuses_move(app, filed):
    app.marks.mark_important(["id-a"], None)
    collect(app, filed, ["id-a"])
    row = app.repo.by_path(f"{ONG}/Sauna/a.pdf")
    with pytest.raises(InvalidRequest, match=IMPORTANT_REFUSAL):
        app.browse.move_preview([row.drive_id], HOME, origin="ui")
    assert app.browse.move_preview([row.drive_id], HOME, origin="ui", mode="copy")


# --- restore into a folder ---------------------------------------------------------------


@pytest.fixture
def trashed(app, filed):
    assert app.browse.quarantine(["id-a", "id-b"], origin="ui").failed is None
    return filed


def test_restore_into_a_folder_and_undo(app, trashed):
    dry = app.browse.restore(["id-a"], "folder", origin="ui", dry_run=True, folder=HOME)
    assert [(o.kind, o.dst) for o in dry.done] == [(OpKind.MOVE, f"{HOME}/a.pdf")]
    result = app.browse.restore(["id-a", "id-b"], "folder", origin="ui", folder=HOME)
    assert result.failed is None and result.error is None
    assert (trashed.root / HOME / "a.pdf").read_bytes() == b"aaa"
    assert app.repo.get("id-b").path == f"{HOME}/b.pdf"
    assert {r["label"] for r in journal(app) if r["batch_id"] == result.batch_id} == {
        f"Restored 2 files from To Delete to {HOME}"
    }
    app.activity.undo(result.batch_id)
    assert (trashed.root / QUAR / BANKS / "a.pdf").read_bytes() == b"aaa"
    assert app.repo.get("id-a").path == f"{QUAR}/{BANKS}/a.pdf"


def test_restore_into_a_new_folder_and_with_a_taken_name(app, trashed):
    trashed.add(f"{HOME}/Fresh/a.pdf", b"x", drive_id="id-x")
    app.scan()
    [op] = app.browse.restore(
        ["id-a"], "folder", origin="ui", dry_run=True, folder=f"{HOME}/Fresh"
    ).done
    assert (op.dst, op.note) == (f"{HOME}/Fresh/a_2.pdf", COLLISION_NOTE)
    made = app.browse.restore(["id-b"], "folder", origin="ui", dry_run=True, folder=f"{HOME}/New")
    assert [(o.kind, o.dst) for o in made.done] == [
        (OpKind.MKDIR, f"{HOME}/New"),
        (OpKind.MOVE, f"{HOME}/New/b.pdf"),
    ]


def test_restore_into_the_inbox_folder_works_like_any_folder(app, trashed):
    result = app.browse.restore(["id-a"], "folder", origin="ui", folder=INBOX)
    assert result.error is None and (trashed.root / INBOX / "a.pdf").exists()


@pytest.mark.parametrize("folder", [ONG, f"{ONG}/Sauna", IMP, QUAR, f"{QUAR}/{BANKS}", ""])
def test_restore_into_the_apps_folders_is_refused(app, trashed, folder):
    with pytest.raises(InvalidRequest):
        app.browse.restore(["id-a"], "folder", origin="ui", dry_run=True, folder=folder)


def test_restore_folder_argument_rules(app, trashed):
    with pytest.raises(InvalidRequest):
        app.browse.restore(["id-a"], "folder", origin="ui")
    with pytest.raises(InvalidRequest):
        app.browse.restore(["id-a"], "inbox", origin="ui", folder=HOME)
    with pytest.raises(InvalidRequest, match="not in ##. To Delete"):
        app.browse.restore(["id-k"], "folder", origin="ui", folder=HOME)


def test_moving_a_to_delete_row_the_old_way_is_still_refused(app, trashed):
    with pytest.raises(InvalidRequest, match="cannot be moved"):
        app.browse.move_preview(["id-a"], HOME, origin="ui")
    for mode in ("link", "copy"):
        with pytest.raises(InvalidRequest, match="restore it first"):
            app.browse.move_preview(["id-a"], HOME, origin="ui", mode=mode)


# --- the API ---------------------------------------------------------------------------------


def post(client, url, body):
    return client.post(url, json=body, headers=LOCAL_ORIGIN)


def test_move_endpoints_take_a_mode(client, app, filed):
    r = post(client, "/api/browse/move/preview", {"drive_ids": ["id-a"], "folder": HOME})
    assert [o["kind"] for o in r.json()] == ["move"]
    r = post(
        client, "/api/browse/move/preview", {"drive_ids": ["id-a"], "folder": HOME, "mode": "link"}
    )
    assert [o["kind"] for o in r.json()] == ["symlink"]
    r = post(client, "/api/browse/move", {"drive_ids": ["id-a"], "folder": HOME, "mode": "copy"})
    assert r.status_code == 200 and r.json()["done"][0]["kind"] == "copy"
    assert (
        post(
            client, "/api/browse/move", {"drive_ids": ["id-a"], "folder": HOME, "mode": "x"}
        ).status_code
        == 422
    )


def test_restore_endpoint_takes_a_folder(client, app, trashed):
    r = post(
        client,
        "/api/restore",
        {"drive_ids": ["id-a"], "to": "folder", "folder": HOME, "dry_run": True},
    )
    assert r.status_code == 200 and [o["dst"] for o in r.json()["done"]] == [f"{HOME}/a.pdf"]
    assert post(client, "/api/restore", {"drive_ids": ["id-a"], "to": "folder"}).status_code == 400


def test_status_says_whether_links_can_be_made(client):
    assert client.get("/api/status").json()["can_link"] is True


def test_a_copy_is_a_regular_file_with_the_same_bytes_only(app, filed):
    app.browse.move(["id-a"], HOME, origin="ui", mode="copy")
    st = os.lstat(filed.root / HOME / "a.pdf")
    assert stat.S_ISREG(st.st_mode) and st.st_nlink == 1
