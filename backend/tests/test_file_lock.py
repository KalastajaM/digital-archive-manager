"""File locks: a safety catch against file changes (dam.locks, the planner, the routes)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from dam.api import create_api
from dam.app import App
from dam.db.tables import file_locks, operations
from dam.locks import IDLE_SECONDS, with_tokens
from dam.ops.model import GuardError, Op, OpKind, Plan
from dam.services.inbox import FileRequest

INBOX = "##. Organize"
BANKS = "10. Financial/Banks"
HOME = "20. Home"
QUAR = "##. To Delete"
BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}
MSG = "This file is locked. Unlock it to change it."


@pytest.fixture
def tree(app, fake_archive):
    fake_archive.add(f"{INBOX}/in1.pdf", drive_id="in1")
    fake_archive.add(f"{BANKS}/s1.pdf", drive_id="s1")
    fake_archive.add(f"{BANKS}/s2.pdf", drive_id="s2")
    fake_archive.add(f"{BANKS}/s3.pdf", drive_id="s3")
    fake_archive.add(f"{HOME}/Deeds/deed.pdf", drive_id="deed")
    (fake_archive.root / HOME / "Docs").mkdir()
    app.scan()
    return fake_archive


@pytest.fixture
def client(app, tree):
    with TestClient(create_api(app), base_url=BASE) as c:
        yield c


def send(client, method, url, body=None, tokens=()):
    headers = dict(LOCAL_ORIGIN)
    if tokens:
        headers["X-Dam-Unlock"] = ", ".join(tokens)
    return client.request(method, url, json=body if body is not None else {}, headers=headers)


def apply_op(app, kind, src, dst):
    return app.executor.apply(Plan([Op(kind, src, dst)], "ui"))


def where(fake_archive, rel):
    return (fake_archive.root / rel).exists()


# --- what a lock refuses and what a grant allows ---------------------------------------


def test_every_kind_of_file_change_is_refused_when_locked_and_allowed_with_a_grant(app, tree):
    app.locks.lock("s1")
    app.locks.lock("in1")
    kinds = {
        "rename": lambda: app.browse.rename_file("s1", "new.pdf", BANKS),
        "move": lambda: app.browse.move(["s1"], HOME),
        "move_and_rename": lambda: app.browse.rename_file("s1", "new.pdf", HOME),
        "quarantine": lambda: app.browse.quarantine(["s1"], origin="ui"),
        "file_it": lambda: app.inbox.file_it([FileRequest("in1", "in1.pdf", BANKS)]),
        "rename_op": lambda: app.executor.apply(
            Plan([Op(OpKind.RENAME, f"{BANKS}/s1.pdf", "q.pdf")], "ui")
        ),
        "move_op": lambda: app.executor.apply(
            Plan([Op(OpKind.MOVE, f"{BANKS}/s1.pdf", HOME)], "ui")
        ),
        "quarantine_op": lambda: app.executor.apply(
            Plan([Op(OpKind.QUARANTINE, f"{BANKS}/s1.pdf", None)], "ui")
        ),
    }
    for name, run in kinds.items():
        with pytest.raises(GuardError, match=MSG):
            run()
        assert where(tree, f"{BANKS}/s1.pdf") and where(tree, f"{INBOX}/in1.pdf"), name
    # previews refuse too
    with pytest.raises(GuardError, match=MSG):
        app.browse.move_preview(["s1"], HOME)
    with pytest.raises(GuardError, match=MSG):
        app.inbox.preview([FileRequest("in1", "in1.pdf", BANKS)])
    with app.engine.connect() as conn:
        assert not conn.execute(select(operations).where(operations.c.kind != "symlink")).all()

    token = app.locks.grant("s1")
    with with_tokens([token]):
        result = app.browse.rename_file("s1", "new.pdf", BANKS)
        assert result.error is None and where(tree, f"{BANKS}/new.pdf")
        # several changes while unlocked
        app.browse.move(["s1"], HOME)
        assert where(tree, f"{HOME}/new.pdf")
    # the lock follows the file (keyed by drive id): the moved file is still locked
    with pytest.raises(GuardError, match=MSG):
        app.browse.move(["s1"], BANKS)
    with with_tokens([token]):
        app.browse.quarantine(["s1"], origin="ui")
    assert where(tree, f"{QUAR}/{HOME}/new.pdf")
    # a token for another file does not help
    other = app.locks.grant("s2")
    with with_tokens([other]), pytest.raises(GuardError, match=MSG):
        app.inbox.file_it([FileRequest("in1", "in1.pdf", BANKS)])


def test_metadata_changes_are_allowed_while_locked(app, tree):
    app.locks.lock("s1")
    app.tags.add("s1", ["tax"])
    app.notes.set("file", "s1", "a note")
    app.marks.star(["s1"])
    app.marks.unstar(["s1"])
    app.assignments.set(["s1"], sender="Nordea", person=None)
    assert app.tags.for_file("s1") == ["tax"]
    assert app.notes.get("file", "s1") == "a note"
    assert app.assignments.get(["s1"])["s1"].sender == "Nordea"
    assert app.repo.get("s1") is not None  # still readable


def test_important_files_are_always_locked(app, tree):
    app.marks.mark_important(["s1"], None)
    assert app.locks.reason("s1", f"{BANKS}/s1.pdf") == "important"
    with pytest.raises(GuardError, match=MSG):
        app.browse.rename_file("s1", "new.pdf", BANKS)
    with pytest.raises(GuardError, match=MSG):
        app.browse.move(["s1"], HOME)
    token = app.locks.grant("s1")
    with with_tokens([token]):
        app.browse.move(["s1"], HOME)
    assert where(tree, f"{HOME}/s1.pdf")
    # the existing quarantine protection still comes first, grant or not
    with with_tokens([token]), pytest.raises(Exception, match="marked Important"):
        app.browse.quarantine(["s1"], origin="ui")
    # unmarking makes it an ordinary, unlocked file
    app.marks.unmark_important(["s1"])
    assert app.locks.reason("s1", f"{HOME}/s1.pdf") is None
    app.browse.move(["s1"], BANKS)


def test_a_file_inside_an_important_folder_is_locked(app, tree):
    folder = app.repo.by_path(f"{HOME}/Deeds").drive_id
    app.marks.mark_important([folder], None)
    assert app.locks.reason("deed", f"{HOME}/Deeds/deed.pdf") == "important"
    with pytest.raises(GuardError, match=MSG):
        app.browse.move(["deed"], BANKS)
    with with_tokens([app.locks.grant("deed")]):
        app.browse.move(["deed"], BANKS)
    assert where(tree, f"{BANKS}/deed.pdf")


def test_a_folder_with_a_locked_file_inside_cannot_be_moved(app, tree):
    app.locks.lock("deed")
    folder_op = Op(OpKind.MOVE, f"{HOME}/Deeds", BANKS)
    with pytest.raises(GuardError, match=MSG):
        app.executor.apply(Plan([folder_op], "ui"))
    assert where(tree, f"{HOME}/Deeds/deed.pdf")
    with with_tokens([app.locks.grant("deed")]):
        app.executor.apply(Plan([folder_op], "ui"))
    assert where(tree, f"{BANKS}/Deeds/deed.pdf")


def test_a_batch_names_every_locked_file_and_does_nothing(app, tree):
    app.locks.lock("s1")
    app.locks.lock("s2")
    with pytest.raises(GuardError) as e:
        app.browse.move(["s1", "s2", "s3"], HOME)
    assert str(e.value) == "These files are locked (s1.pdf, s2.pdf). Unlock them to change them."
    with pytest.raises(GuardError) as e:
        app.browse.move_preview(["s1", "s3"], HOME)
    assert str(e.value) == "This file is locked (s1.pdf). Unlock it to change it."
    assert all(where(tree, f"{BANKS}/s{i}.pdf") for i in (1, 2, 3))
    # unlocking both lets the whole batch through
    with with_tokens([app.locks.grant("s1"), app.locks.grant("s2")]):
        assert app.browse.move(["s1", "s2", "s3"], HOME).error is None
    assert all(where(tree, f"{HOME}/s{i}.pdf") for i in (1, 2, 3))


def test_undo_is_not_blocked_by_a_lock(app, tree):
    batch = app.browse.move(["s1"], HOME).batch_id
    app.locks.lock("s1")
    assert app.executor.undo(batch).error is None
    assert where(tree, f"{BANKS}/s1.pdf")


# --- grants: expiry, renewal, release, restart -----------------------------------------


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_a_grant_expires_after_idle_time_and_each_use_renews_it(app, tree):
    clock = Clock()
    app.locks._clock = clock
    app.locks.lock("s1")
    token = app.locks.grant("s1")
    clock.now += IDLE_SECONDS - 10
    assert app.locks.granted([token]) == {"s1"}  # used: renewed
    clock.now += IDLE_SECONDS - 10
    assert app.locks.granted([token]) == {"s1"}
    clock.now += IDLE_SECONDS + 1  # idle too long
    assert app.locks.granted([token]) == set()
    with with_tokens([token]), pytest.raises(GuardError, match=MSG):
        app.browse.move(["s1"], HOME)
    assert not app.locks.active("s1")


def test_a_release_ends_every_grant_of_the_file(app, tree):
    app.locks.lock("s1")
    a, b = app.locks.grant("s1"), app.locks.grant("s1")
    other = app.locks.grant("s2")
    assert app.locks.release("s1") == 2
    assert app.locks.granted([a, b, other]) == {"s2"}


def test_garbage_and_unknown_tokens_unlock_nothing(app, tree):
    app.locks.lock("s1")
    with with_tokens(["", "nope", "x" * 500]), pytest.raises(GuardError, match=MSG):
        app.browse.move(["s1"], HOME)


def test_no_unlock_survives_a_restart(app, app_paths, tree):
    app.locks.lock("s1")
    app.marks.mark_important(["s2"], None)
    t1, t2 = app.locks.grant("s1"), app.locks.grant("s2")
    again = App.create(app_paths.data_dir)
    try:
        assert again.locks.granted([t1, t2]) == set()
        assert {e.drive_id for e in again.locks.entries()} == {"s1", "s2"}
        with with_tokens([t1, t2]), pytest.raises(GuardError, match=MSG):
            again.browse.move(["s1"], HOME)
    finally:
        again.close()


# --- the storage -----------------------------------------------------------------------


def test_the_table_exists_and_a_lock_is_one_row_per_file(engine):
    assert "file_locks" in inspect(engine).get_table_names()
    assert [c["name"] for c in inspect(engine).get_columns("file_locks")] == [
        "drive_id",
        "locked_at",
    ]


def test_a_lock_survives_a_move_and_is_stored_once(app, tree):
    app.locks.lock("s1")
    app.locks.lock("s1")
    with app.engine.connect() as conn:
        assert conn.execute(select(file_locks.c.drive_id)).scalars().all() == ["s1"]
    app.locks.unlock_for_good("s1")
    assert app.locks.stored() == set()


# --- the routes ------------------------------------------------------------------------


def test_lock_unlock_routes_and_the_token_header(client, app, tree):
    r = send(client, "POST", "/api/files/s1/lock")
    assert r.status_code == 200 and r.json()["locked"] and r.json()["reason"] == "file"
    assert {"drive_id": "s1", "reason": "file"} in send(client, "GET", "/api/locks").json()["files"]
    r = send(
        client, "POST", "/api/browse/rename", {"drive_id": "s1", "name": "n.pdf", "folder": BANKS}
    )
    assert r.status_code == 400 and r.json()["error"] == MSG
    r = send(client, "POST", "/api/browse/move/preview", {"drive_ids": ["s1"], "folder": HOME})
    assert r.status_code == 400 and r.json()["error"] == MSG
    r = send(client, "POST", "/api/quarantine", {"drive_ids": ["s1"]})
    assert r.status_code == 400 and r.json()["error"] == MSG

    r = send(client, "POST", "/api/files/s1/unlock", {"mode": "now"})
    body = r.json()
    assert r.status_code == 200 and body["locked"] and body["unlocked_now"]
    assert body["token"] and body["expires_after_idle_seconds"] == IDLE_SECONDS
    token = body["token"]
    # without the header it is still locked; with it the change is made
    r = send(client, "POST", "/api/browse/move", {"drive_ids": ["s1"], "folder": HOME})
    assert r.status_code == 400
    r = send(client, "POST", "/api/browse/move", {"drive_ids": ["s1"], "folder": HOME}, [token])
    assert r.status_code == 200 and r.json()["error"] is None
    assert where(tree, f"{HOME}/s1.pdf")
    # leaving the file releases it at once
    r = send(client, "DELETE", "/api/files/s1/unlock")
    assert r.status_code == 200 and r.json()["locked"] and not r.json()["unlocked_now"]
    r = send(client, "POST", "/api/browse/move", {"drive_ids": ["s1"], "folder": BANKS}, [token])
    assert r.status_code == 400 and r.json()["error"] == MSG


def test_unlock_for_good_removes_the_lock(client, app, tree):
    send(client, "POST", "/api/files/s1/lock")
    r = send(client, "POST", "/api/files/s1/unlock", {"mode": "for_good"})
    assert r.status_code == 200 and not r.json()["locked"] and r.json()["token"] is None
    assert app.locks.stored() == set()
    assert (
        send(client, "POST", "/api/browse/move", {"drive_ids": ["s1"], "folder": HOME}).status_code
        == 200
    )


def test_an_important_file_unlocks_only_for_now(client, app, tree):
    send(client, "POST", "/api/marks/important", {"drive_ids": ["s1"]})
    r = send(client, "POST", "/api/files/s1/unlock", {"mode": "for_good"})
    assert r.status_code == 409
    assert r.json()["error"] == "An Important file can only be unlocked for now."
    listing = send(client, "GET", "/api/locks").json()
    assert {"drive_id": "s1", "reason": "important"} in listing["files"]
    r = send(client, "POST", "/api/files/s1/unlock", {"mode": "now"})
    assert r.status_code == 200 and r.json()["reason"] == "important" and r.json()["token"]
    # locking an Important file stores nothing
    send(client, "POST", "/api/files/s1/lock")
    assert app.locks.stored() == set()


def test_lock_validation(client, app, tree):
    assert send(client, "POST", "/api/files/nope/lock").status_code == 404
    folder = app.repo.by_path(f"{HOME}/Docs").drive_id
    assert send(client, "POST", f"/api/files/{folder}/lock").status_code == 400
    assert send(client, "POST", "/api/files/s1/unlock", {"mode": "forever"}).status_code == 422
    # unlocking a file that is not locked is harmless
    r = send(client, "POST", "/api/files/s2/unlock", {"mode": "now"})
    assert r.status_code == 200 and not r.json()["locked"] and r.json()["token"] is None


def test_the_locks_list_names_marked_folders(client, app, tree):
    folder = app.repo.by_path(f"{HOME}/Deeds")
    app.marks.mark_important([folder.drive_id], None)
    body = send(client, "GET", "/api/locks").json()
    assert body["folders"] == [f"{HOME}/Deeds"]
