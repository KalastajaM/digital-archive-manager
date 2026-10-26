"""Restore from ``##. To Delete``: plan, preview, apply, undo, collisions, a missing
original folder, refusals, and the read-only rule for files marked for deletion."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from dam.api import create_api
from dam.db.tables import operations
from dam.ops.model import OpKind
from dam.ops.planner import COLLISION_NOTE
from dam.services.errors import InvalidRequest, NotFound

INBOX = "##. Organize"
ONG = "##. Ongoing"
QUAR = "##. To Delete"
BANKS = "10. Financial/Banks"
BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}


def journal(app) -> list:
    with app.engine.connect() as conn:
        return list(conn.execute(select(operations).order_by(operations.c.id)).mappings())


@pytest.fixture
def trashed(app, fake_archive):
    """a.pdf and b.pdf marked for deletion (so both are in To Delete)."""
    fake_archive.add(f"{BANKS}/a.pdf", b"a", drive_id="id-a")
    fake_archive.add(f"{BANKS}/b.pdf", b"b", drive_id="id-b")
    app.scan()
    result = app.browse.quarantine(["id-a", "id-b"], origin="ui")
    assert result.failed is None and result.error is None
    return fake_archive


@pytest.fixture
def client(app):
    with TestClient(create_api(app, None), base_url=BASE) as c:
        yield c


def post(client, url, body):
    return client.post(url, json=body, headers=LOCAL_ORIGIN)


def test_restore_to_the_original_place_and_undo(app, trashed):
    assert app.repo.get("id-a").path == f"{QUAR}/{BANKS}/a.pdf"
    dry = app.browse.restore(["id-a", "id-b"], "original", origin="ui", dry_run=True)
    assert dry.dry_run and [(o.kind, o.dst) for o in dry.done] == [
        (OpKind.MOVE, f"{BANKS}/a.pdf"),
        (OpKind.MOVE, f"{BANKS}/b.pdf"),
    ]
    assert (trashed.root / QUAR / BANKS / "a.pdf").exists()  # a dry run changes nothing

    result = app.browse.restore(["id-a", "id-b"], "original", origin="ui")
    assert result.failed is None and result.error is None and result.index_error is None
    assert (trashed.root / BANKS / "a.pdf").read_bytes() == b"a"
    assert not (trashed.root / QUAR / BANKS / "a.pdf").exists()
    assert app.repo.get("id-b").path == f"{BANKS}/b.pdf"
    rows = [r for r in journal(app) if r["batch_id"] == result.batch_id]
    assert {r["label"] for r in rows} == {"Restored 2 files from To Delete"}
    assert app.activity.get(result.batch_id).undoable

    outcome = app.activity.undo(result.batch_id)
    assert outcome.batch.failed is None and outcome.batch.error is None
    assert (trashed.root / QUAR / BANKS / "a.pdf").read_bytes() == b"a"
    assert not (trashed.root / BANKS / "a.pdf").exists()
    assert app.repo.get("id-a").path == f"{QUAR}/{BANKS}/a.pdf"
    assert app.activity.get(result.batch_id).undone


def test_restore_one_file_names_it(app, trashed):
    result = app.browse.restore(["id-a"], "original", origin="ui")
    assert {r["label"] for r in journal(app) if r["batch_id"] == result.batch_id} == {
        "Restored a.pdf from To Delete"
    }


def test_restore_to_inbox(app, trashed):
    result = app.browse.restore(["id-a"], "inbox", origin="ui")
    assert [(o.kind, o.dst) for o in result.done] == [(OpKind.MOVE, f"{INBOX}/a.pdf")]
    assert (trashed.root / INBOX / "a.pdf").read_bytes() == b"a"
    assert {r["label"] for r in journal(app) if r["batch_id"] == result.batch_id} == {
        "Restored a.pdf from To Delete to the inbox"
    }
    app.activity.undo(result.batch_id)
    assert app.repo.get("id-a").path == f"{QUAR}/{BANKS}/a.pdf"


def test_restore_remakes_a_missing_original_folder(app, trashed):
    # the folder is gone: the plan shows the MKDIR, undo puts the file back in To Delete
    (trashed.root / BANKS).rmdir()
    app.scan()
    preview = app.browse.restore(["id-a"], "original", origin="ui", dry_run=True)
    assert [(o.kind, o.dst) for o in preview.done] == [
        (OpKind.MKDIR, BANKS),
        (OpKind.MOVE, f"{BANKS}/a.pdf"),
    ]
    result = app.browse.restore(["id-a"], "original", origin="ui")
    assert result.failed is None and (trashed.root / BANKS / "a.pdf").read_bytes() == b"a"
    app.activity.undo(result.batch_id)
    assert (trashed.root / QUAR / BANKS / "a.pdf").exists()


def test_restore_remakes_a_missing_top_level_folder(app, fake_archive):
    fake_archive.add("90. Misc/x.pdf", b"x", drive_id="id-x")
    app.scan()
    app.browse.quarantine(["id-x"], origin="ui")
    (fake_archive.root / "90. Misc").rmdir()
    result = app.browse.restore(["id-x"], "original", origin="ui")
    assert [(o.kind, o.dst) for o in result.done] == [
        (OpKind.MKDIR, "90. Misc"),
        (OpKind.MOVE, "90. Misc/x.pdf"),
    ]
    assert (fake_archive.root / "90. Misc" / "x.pdf").exists()


def test_restore_name_taken_gets_a_number_and_the_preview_says_so(app, trashed):
    trashed.add(f"{BANKS}/a.pdf", b"new a", drive_id="id-new")
    app.scan()
    [op] = app.browse.restore(["id-a"], "original", origin="ui", dry_run=True).done
    assert (op.dst, op.note) == (f"{BANKS}/a_2.pdf", COLLISION_NOTE)
    app.browse.restore(["id-a"], "original", origin="ui")
    assert (trashed.root / BANKS / "a.pdf").read_bytes() == b"new a"  # untouched
    assert (trashed.root / BANKS / "a_2.pdf").read_bytes() == b"a"


def test_restore_a_folder_marked_for_deletion(app, fake_archive):
    fake_archive.add(f"{BANKS}/Old/one.pdf", b"1", drive_id="id-1")
    fake_archive.add(f"{BANKS}/Old/two.pdf", b"2", drive_id="id-2")
    app.scan()
    folder = app.repo.by_path(f"{BANKS}/Old")
    app.browse.quarantine([folder.drive_id], origin="ui")
    assert app.repo.get("id-1").path == f"{QUAR}/{BANKS}/Old/one.pdf"
    # the folder and a file inside it selected together: the file comes along with it
    result = app.browse.restore([folder.drive_id, "id-1"], "original", origin="ui")
    assert [(o.kind, o.dst) for o in result.done] == [(OpKind.MOVE, f"{BANKS}/Old")]
    assert (fake_archive.root / BANKS / "Old" / "one.pdf").exists()
    assert app.repo.get("id-2").path == f"{BANKS}/Old/two.pdf"
    app.activity.undo(result.batch_id)
    assert (fake_archive.root / QUAR / BANKS / "Old" / "two.pdf").exists()


def test_restore_refusals(app, trashed, fake_archive):
    fake_archive.add(f"{BANKS}/live.pdf", b"l", drive_id="id-live")
    app.scan()
    with pytest.raises(InvalidRequest, match="not in ##. To Delete"):
        app.browse.restore(["id-live"], "original", origin="ui")
    with pytest.raises(NotFound):
        app.browse.restore(["nope"], "original", origin="ui")
    with pytest.raises(InvalidRequest, match="requested more than once"):
        app.browse.restore(["id-a", "id-a"], "original", origin="ui")
    with pytest.raises(InvalidRequest):
        app.browse.restore([], "original", origin="ui")
    with pytest.raises(InvalidRequest):
        app.browse.restore(["id-a"], "elsewhere", origin="ui")
    with pytest.raises(InvalidRequest):
        app.browse.restore(["id-a"], "original", origin="undo")
    assert journal(app)[-1]["kind"] == "quarantine"  # nothing was journaled by a refusal


def test_restore_of_something_from_the_top_level_goes_to_the_inbox_only(app, fake_archive):
    fake_archive.add("90. Misc/x.pdf", b"x", drive_id="id-x")
    app.scan()
    folder = app.repo.by_path("90. Misc")
    # the mirrored folder in To Delete stands at the top: it has no place but the inbox
    app.browse.quarantine(["id-x"], origin="ui")
    app.scan()
    mirror = app.repo.by_path(f"{QUAR}/90. Misc")
    assert mirror is not None and folder is not None
    with pytest.raises(InvalidRequest, match="top of the archive"):
        app.browse.restore([mirror.drive_id], "original", origin="ui")


def test_restore_endpoint(client, app, trashed):
    r = post(client, "/api/restore", {"drive_ids": ["id-a"], "dry_run": True})
    assert r.status_code == 200 and r.json()["dry_run"] is True
    assert [o["dst"] for o in r.json()["done"]] == [f"{BANKS}/a.pdf"]
    r = post(client, "/api/restore", {"drive_ids": ["id-a"], "to": "inbox"})
    assert r.status_code == 200 and r.json()["done"][0]["dst"] == f"{INBOX}/a.pdf"
    assert post(client, "/api/restore", {"drive_ids": ["id-b"], "to": "nowhere"}).status_code == 422
    assert post(client, "/api/restore", {"drive_ids": ["nope"]}).status_code == 404
    live = post(client, "/api/restore", {"drive_ids": ["id-a"]})  # now in the inbox
    assert live.status_code == 400


def test_activity_groups_a_restore_with_trash(app, trashed):
    result = app.browse.restore(["id-a"], "original", origin="ui")
    kinds = [b.batch_id for b in app.activity.search(kinds=["trash"])]
    assert result.batch_id in kinds


# --- files under To Delete are read-only ---------------------------------------------


def test_changes_to_a_file_in_to_delete_are_refused_and_nothing_is_lost(client, app, trashed):
    app.tags.set_for_file("id-a", ["tax"])
    app.notes.set("file", "id-a", "keep me")
    col = app.collections.create("Trip")
    app.collections.add_members(col.id, ["id-a"])
    app.trays.create_quick("to-pay", ["id-a"], {})
    refusal = "Marked for deletion: restore it first"

    def refused(r):
        assert r.status_code == 400, r.text
        assert refusal in r.json()["error"]

    refused(client.put("/api/files/id-a/tags", json={"tags": ["x"]}, headers=LOCAL_ORIGIN))
    refused(
        client.put(
            "/api/files/id-a/summary",
            json={"source": "user", "summary": "s", "key_facts": []},
            headers=LOCAL_ORIGIN,
        )
    )
    refused(client.put("/api/notes/file/id-a", json={"text": "new"}, headers=LOCAL_ORIGIN))
    refused(post(client, "/api/notes/file/id-a/append", {"text": "more"}))
    refused(post(client, "/api/checklist/file/id-a", {"text": "todo"}))
    refused(post(client, "/api/marks/star", {"drive_ids": ["id-a"]}))
    refused(post(client, "/api/marks/important", {"drive_ids": ["id-a"]}))
    who = {"drive_ids": ["id-a"], "sender": "Kela"}
    refused(client.put("/api/assignments", json=who, headers=LOCAL_ORIGIN))
    refused(post(client, f"/api/collections/{col.id}/members", {"drive_ids": ["id-a"]}))
    refused(post(client, "/api/items/quick", {"tray": "to-read", "drive_ids": ["id-a"]}))
    refused(post(client, "/api/items", {"tray": "to-read", "drive_ids": ["id-a"]}))
    # a batch with one such file is refused whole
    refused(post(client, "/api/marks/star", {"drive_ids": ["id-b", "id-a"]}))

    assert app.tags.for_file("id-a") == ["tax"]
    assert app.notes.get("file", "id-a") == "keep me"
    assert app.marks.marks_for(["id-a"]).get("id-a", []) == []

    # restored, the file is editable again and comes back with what it had
    app.browse.restore(["id-a"], "original", origin="ui")
    assert app.tags.for_file("id-a") == ["tax"]
    ok = client.put("/api/files/id-a/tags", json={"tags": ["tax", "x"]}, headers=LOCAL_ORIGIN)
    assert ok.status_code == 200
    assert post(client, "/api/marks/star", {"drive_ids": ["id-a"]}).status_code == 200


def test_restore_original_in_extra_folder(extra_folder, app):
    src = extra_folder.add("2009/a.pdf", b"a", drive_id="x1")
    app.scan()
    assert app.browse.quarantine(["x1"], origin="ui").failed is None
    assert app.repo.get("x1").path == f"Old years/{QUAR}/2009/a.pdf"
    preview = app.browse.restore(["x1"], to="original", origin="ui", dry_run=True)
    assert [(r.kind, r.src, r.dst) for r in preview.done] == [
        (OpKind.MOVE, f"Old years/{QUAR}/2009/a.pdf", "Old years/2009/a.pdf")
    ]
    result = app.browse.restore(["x1"], to="original", origin="ui")
    assert result.failed is None and result.error is None
    assert src.read_bytes() == b"a"
    assert app.repo.get("x1").path == "Old years/2009/a.pdf"


def test_restore_to_inbox_from_extra_folder_needs_one_disk(extra_folder, app, monkeypatch):
    from dam.ops import primitives
    from dam.ops.model import OpFailed

    extra_folder.add("2009/a.pdf", b"a", drive_id="x1")
    app.scan()
    assert app.browse.quarantine(["x1"], origin="ui").failed is None
    preview = app.browse.restore(["x1"], to="inbox", origin="ui", dry_run=True)
    assert [r.dst for r in preview.done] == [f"{INBOX}/a.pdf"]
    monkeypatch.setattr(primitives, "same_disk", lambda a, b: False)
    with pytest.raises(OpFailed) as e:
        app.browse.restore(["x1"], to="inbox", origin="ui", dry_run=True)
    assert str(e.value) == (
        "'Old years' and the main folder are on different disks, so files cannot be moved"
        " between them yet."
    )
    assert (extra_folder.root / QUAR / "2009" / "a.pdf").exists()
