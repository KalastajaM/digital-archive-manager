"""Merging a collection into another: its files and collections join the target, its note,
checklist and summary are added to the target's, it goes; ##. Ongoing follows."""

import os

import pytest

from dam.errors import InvalidRequest
from test_api import BANKS, LOCAL_ORIGIN, make_client

ONG = "##. Ongoing"


@pytest.fixture
def files(app, fake_archive):
    for x in "abcd":
        fake_archive.add(f"{BANKS}/{x}.pdf", drive_id=f"id-{x}", content=b"%PDF")
    app.scan()


def members(app, cid):
    return sorted(m.drive_id for m in app.collections.get(cid).members)


def test_merge_moves_files_and_collections_and_adds_the_texts(app, files):
    a = app.collections.create("Old house")
    b = app.collections.create("House")
    kid = app.collections.create("Garden", parent_id=a.id)
    app.collections.add_members(a.id, ["id-a", "id-b"])
    app.collections.add_members(b.id, ["id-b", "id-c"])
    app.collections.set_summary(a.id, "Sold in 2025.")
    app.collections.set_summary(b.id, "The house we live in.")
    app.notes.set("collection", str(a.id), "Keys with the agent.")
    app.notes.set("collection", str(b.id), "Insurance renews in May.")
    x = app.notes.add_check("collection", str(a.id), "Hand over keys")
    app.notes.set_check(x.id, done=True)
    app.notes.add_check("collection", str(a.id), "Cancel power")
    app.notes.add_check("collection", str(b.id), "Paint the fence")

    app.merge_collections(a.id, b.id)

    assert members(app, b.id) == ["id-a", "id-b", "id-c"]
    assert all(c.id != a.id for c in app.collections.list(None))
    assert app.collections.get(kid.id).parent_id == b.id
    assert app.collections.get(b.id).summary == "The house we live in.\n\nSold in 2025."
    assert (
        app.notes.get("collection", str(b.id))
        == "Insurance renews in May.\n\nFrom Old house:\nKeys with the agent."
    )
    assert app.notes.get("collection", str(a.id)) == ""
    checks = [(c.text, c.done) for c in app.notes.checklist("collection", str(b.id))]
    assert checks == [("Paint the fence", False), ("Hand over keys", True), ("Cancel power", False)]
    assert app.notes.checklist("collection", str(a.id)) == []


def test_merge_is_refused_where_it_cannot_be_done(app, files):
    a = app.collections.create("A")
    inner = app.collections.create("Inner", parent_id=a.id)
    shut = app.collections.create("Shut")
    app.collections.close(shut.id)
    starred = app.collections.builtin("starred")
    assert app.collections.merge_check(a.id, a.id)
    assert app.collections.merge_check(a.id, inner.id)  # into its own collection: a cycle
    assert app.collections.merge_check(a.id, shut.id) == ["Shut is closed: reopen it first"]
    assert app.collections.merge_check(starred.id, a.id)
    assert app.collections.merge_check(a.id, starred.id)
    with pytest.raises(InvalidRequest):
        app.merge_collections(a.id, inner.id)


def test_merge_is_refused_when_the_note_would_be_too_long(app, files):
    a = app.collections.create("A")
    b = app.collections.create("B")
    app.notes.set("collection", str(a.id), "x" * 6000)
    app.notes.set("collection", str(b.id), "y" * 6000)
    [problem] = app.collections.merge_check(a.id, b.id)
    assert problem.startswith("The note would be ") and problem.endswith(
        " characters too long: shorten one first"
    )


def test_merge_moves_the_links_in_ongoing_and_takes_a_snapshot_first(app, files, fake_archive):
    from dam.snapshots import BEFORE_MERGE, list_snapshots

    a = app.collections.create("Old house")
    b = app.collections.create("House")
    app.collections.add_members(a.id, ["id-a", "id-b"])
    app.collections.add_members(b.id, ["id-c", "id-d"])
    app.sync_publishers()
    root = fake_archive.root / ONG
    assert sorted(os.listdir(root / "Old house")) == ["a.pdf", "b.pdf"]

    with make_client(app) as client:
        preview = client.post(
            f"/api/collections/{a.id}/merge/preview", json={"into": b.id}, headers=LOCAL_ORIGIN
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["problems"] == []
        r = client.post(f"/api/collections/{a.id}/merge", json={"into": b.id}, headers=LOCAL_ORIGIN)
    assert r.status_code == 200, r.text
    assert r.json()["collection"]["id"] == b.id
    assert sorted(os.listdir(root / "House")) == ["a.pdf", "b.pdf", "c.pdf", "d.pdf"]
    assert not (root / "Old house").exists()
    assert [s.kind for s in list_snapshots(app.app_paths)] == [BEFORE_MERGE]
