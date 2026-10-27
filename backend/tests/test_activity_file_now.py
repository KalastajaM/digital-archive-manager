"""GET /api/activity: where each op's file is now, from the index (``file_now``).

The journal keeps the paths as they were; the file may have moved on, been marked for
deletion or been deleted by hand since. Read-only: nothing in the journal or on disk
changes."""

import time

import pytest

from dam.db.engine import write_tx
from dam.db.tables import operations, reconnects
from dam.index.repo import FileRecord
from test_api import make_client


@pytest.fixture
def client(app):
    with make_client(app) as c:
        yield c


def _op(app, batch_id, kind, src, dst, drive_id=None, state="done", is_file=True):
    with write_tx(app.engine) as conn:
        conn.execute(
            operations.insert().values(
                batch_id=batch_id,
                seq=0,
                kind=kind,
                src=src,
                dst=dst,
                drive_id=drive_id,
                is_file=is_file,
                state=state,
                origin="ui",
                created=time.time(),
            )
        )


def _file_now(client, batch_id):
    r = client.get("/api/activity")
    assert r.status_code == 200, r.text
    (batch,) = [b for b in r.json() if b["batch_id"] == batch_id]
    return batch["ops"][0]["file_now"]


def test_a_file_still_where_the_op_put_it_is_here(client, app):
    app.repo.upsert(FileRecord(drive_id="d1", path="10. Financial/a.pdf"))
    _op(app, "b", "move", "##. Organize/a.pdf", "10. Financial/a.pdf", drive_id="d1")
    assert _file_now(client, "b") == {
        "state": "here",
        "path": "10. Financial/a.pdf",
        "drive_id": "d1",
        "is_dir": False,
    }


def test_a_file_moved_on_since_is_found_by_its_id(client, app):
    app.repo.upsert(FileRecord(drive_id="d1", path="13. Taxes/renamed.pdf"))
    _op(app, "b", "move", "##. Organize/a.pdf", "10. Financial/a.pdf", drive_id="d1")
    now = _file_now(client, "b")
    assert now["state"] == "moved" and now["path"] == "13. Taxes/renamed.pdf"


def test_a_file_marked_for_deletion_since_is_in_to_delete(client, app):
    app.repo.upsert(FileRecord(drive_id="d1", path="##. To Delete/10. Financial/a.pdf"))
    _op(app, "b", "move", "##. Organize/a.pdf", "10. Financial/a.pdf", drive_id="d1")
    now = _file_now(client, "b")
    assert now["state"] == "to_delete" and now["path"] == "##. To Delete/10. Financial/a.pdf"


def test_the_quarantine_op_itself_reads_here_while_the_file_waits_in_to_delete(client, app):
    app.repo.upsert(FileRecord(drive_id="d1", path="##. To Delete/10. Financial/a.pdf"))
    _op(
        app,
        "b",
        "quarantine",
        "10. Financial/a.pdf",
        "##. To Delete/10. Financial/a.pdf",
        drive_id="d1",
    )
    assert _file_now(client, "b")["state"] == "here"


def test_a_file_deleted_by_hand_is_missing(client, app):
    app.repo.upsert(FileRecord(drive_id="d1", path="10. Financial/a.pdf", missing=True))
    _op(app, "b", "move", "##. Organize/a.pdf", "10. Financial/a.pdf", drive_id="d1")
    assert _file_now(client, "b") == {
        "state": "missing",
        "path": None,
        "drive_id": None,
        "is_dir": False,
    }


def test_a_file_the_index_no_longer_knows_is_missing(client, app):
    _op(app, "b", "move", "##. Organize/a.pdf", "10. Financial/a.pdf", drive_id="gone")
    assert _file_now(client, "b")["state"] == "missing"


def test_an_id_row_gone_is_not_matched_by_a_new_file_at_the_same_path(client, app):
    # another file now sits at the path: the op's file (by its id) is still gone
    app.repo.upsert(FileRecord(drive_id="other", path="10. Financial/a.pdf"))
    _op(app, "b", "move", "##. Organize/a.pdf", "10. Financial/a.pdf", drive_id="gone")
    assert _file_now(client, "b")["state"] == "missing"


def test_a_file_reconnected_after_a_move_outside_dam_is_followed(client, app):
    app.repo.upsert(FileRecord(drive_id="local:new", path="Elsewhere/a.pdf"))
    with write_tx(app.engine) as conn:
        conn.execute(
            reconnects.insert().values(
                batch_id="rc",
                old_id="local:old",
                new_id="local:new",
                old_row="{}",
                moved="{}",
                created=time.time(),
            )
        )
    _op(app, "b", "move", "##. Organize/a.pdf", "10. Financial/a.pdf", drive_id="local:old")
    now = _file_now(client, "b")
    assert now["state"] == "moved" and now["path"] == "Elsewhere/a.pdf"
    assert now["drive_id"] == "local:new"


def test_an_undone_reconnect_is_not_followed(client, app):
    app.repo.upsert(FileRecord(drive_id="local:new", path="Elsewhere/a.pdf"))
    with write_tx(app.engine) as conn:
        conn.execute(
            reconnects.insert().values(
                batch_id="rc",
                old_id="local:old",
                new_id="local:new",
                old_row="{}",
                moved="{}",
                created=time.time(),
                undone=time.time(),
            )
        )
    _op(app, "b", "move", "##. Organize/a.pdf", "10. Financial/a.pdf", drive_id="local:old")
    assert _file_now(client, "b")["state"] == "missing"


def test_without_an_id_the_file_is_found_by_its_path(client, app):
    app.repo.upsert(FileRecord(drive_id="d1", path="10. Financial/a.pdf"))
    _op(app, "b", "move", "##. Organize/a.pdf", "10. Financial/a.pdf")
    now = _file_now(client, "b")
    assert now["state"] == "here" and now["drive_id"] == "d1"


def test_an_op_that_did_not_act_looks_for_the_file_where_it_was(client, app):
    app.repo.upsert(FileRecord(drive_id="d1", path="##. Organize/a.pdf"))
    for batch_id, state in (("failed", "failed"), ("undone", "undone")):
        _op(app, batch_id, "move", "##. Organize/a.pdf", "10. Financial/a.pdf", "d1", state=state)
        assert _file_now(client, batch_id)["state"] == "here"


def test_a_link_op_names_its_target_file(client, app):
    app.repo.upsert(FileRecord(drive_id="d1", path="10. Financial/a.pdf"))
    _op(app, "b", "symlink", "10. Financial/a.pdf", "##. Ongoing/Trip/a.pdf", drive_id="d1")
    now = _file_now(client, "b")
    assert now["state"] == "here" and now["path"] == "10. Financial/a.pdf"


def test_a_folder_says_it_is_one(client, app):
    app.repo.upsert(FileRecord(drive_id="f1", path="10. Financial/Banks", is_dir=True))
    _op(app, "b", "move", "Banks", "10. Financial/Banks", drive_id="f1", is_file=False)
    now = _file_now(client, "b")
    assert now["state"] == "here" and now["is_dir"] is True


def test_ops_on_folders_removed_or_links_removed_name_nothing(client, app):
    _op(app, "rm", "remove_empty_dir", "##. Ongoing/Trip", None, is_file=False)
    _op(app, "ul", "unlink_symlink", "##. Ongoing/Trip/a.pdf", "10. Financial/a.pdf")
    for batch_id in ("rm", "ul"):
        assert _file_now(client, batch_id) is None


def _dir(app, path):
    app.repo.upsert(FileRecord(drive_id=f"dir:{path}", path=path, is_dir=True))


def test_a_folder_made_is_here_while_it_is_there(client, app):
    _dir(app, "10. Financial/New")
    _op(app, "mk", "mkdir", None, "10. Financial/New", is_file=False)
    assert _file_now(client, "mk") == {
        "state": "here",
        "path": "10. Financial/New",
        "drive_id": "dir:10. Financial/New",
        "is_dir": True,
    }


def test_a_folder_made_and_deleted_by_hand_is_missing(client, app):
    _op(app, "mk", "mkdir", None, "10. Financial/New", is_file=False)
    now = _file_now(client, "mk")
    assert now["state"] == "missing" and now["path"] is None and now["is_dir"] is True


def test_a_folder_without_an_id_is_followed_through_a_later_rename(client, app):
    _dir(app, "10. Financial/Banks 2026")
    _op(app, "a", "move", "Banks", "10. Financial/Banks", is_file=False)
    _op(app, "b", "rename", "10. Financial/Banks", "10. Financial/Banks 2026", is_file=False)
    now = _file_now(client, "a")
    assert now["state"] == "moved" and now["path"] == "10. Financial/Banks 2026"
    assert now["is_dir"] is True
    assert _file_now(client, "b")["state"] == "here"


def test_a_folder_is_followed_when_a_folder_above_it_moved(client, app):
    _op(app, "a", "move", "Banks", "10. Financial/Banks", is_file=False)
    _op(app, "b", "move", "10. Financial", "20. Home/Financial", is_file=False)
    _op(app, "c", "rename", "20. Home/Financial", "20. Home/Fin", is_file=False)
    _dir(app, "20. Home/Fin/Banks")
    assert _file_now(client, "a")["path"] == "20. Home/Fin/Banks"
    assert _file_now(client, "a")["state"] == "moved"


def test_a_folder_marked_for_deletion_since_is_in_to_delete(client, app):
    _dir(app, "##. To Delete/10. Financial/Banks")
    _op(app, "a", "move", "Banks", "10. Financial/Banks", is_file=False)
    _op(
        app,
        "b",
        "quarantine",
        "10. Financial/Banks",
        "##. To Delete/10. Financial/Banks",
        is_file=False,
    )
    assert _file_now(client, "a")["state"] == "to_delete"
    assert _file_now(client, "b")["state"] == "here"


def test_a_folder_deleted_by_hand_since_is_missing(client, app):
    _op(app, "a", "move", "Banks", "10. Financial/Banks", is_file=False)
    assert _file_now(client, "a")["state"] == "missing"


def test_a_folder_moved_across_disks_names_the_copy(client, app):
    _dir(app, "D2/Banks")
    _op(app, "x", "quarantine", "D1/Banks", "##. To Delete/D1/Banks", is_file=False)
    with write_tx(app.engine) as conn:
        conn.execute(
            operations.update().where(operations.c.batch_id == "x").values(copied_to="D2/Banks")
        )
    now = _file_now(client, "x")
    assert now["state"] == "here" and now["path"] == "D2/Banks"


def test_a_later_relocation_that_was_undone_does_not_count(client, app):
    _dir(app, "10. Financial/Banks")
    _op(app, "a", "move", "Banks", "10. Financial/Banks", is_file=False)
    _op(
        app,
        "b",
        "rename",
        "10. Financial/Banks",
        "10. Financial/Elsewhere",
        is_file=False,
        state="undone",
    )
    assert _file_now(client, "a")["state"] == "here"


def test_recovery_rows_carry_no_file_now(client, app):
    _op(app, "b", "move", "##. Organize/a.pdf", "10. Financial/a.pdf", state="planned")
    r = client.get("/api/recovery")
    assert r.status_code == 200, r.text
    assert r.json()[0]["file_now"] is None
