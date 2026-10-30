"""Deleting a collection: it and every collection inside it go, with their memberships,
notes, checklists and links in ##. Ongoing. The files themselves are never touched."""

import os

import pytest

from dam.errors import InvalidRequest
from test_api import BANKS, LOCAL_ORIGIN, make_client

ONG = "##. Ongoing"


@pytest.fixture
def tree(app, fake_archive):
    for x in "abcd":
        fake_archive.add(f"{BANKS}/{x}.pdf", drive_id=f"id-{x}", content=b"%PDF")
    app.scan()
    top = app.collections.create("Legal")
    kid = app.collections.create("Michiel", parent_id=top.id)
    grand = app.collections.create("Wills", parent_id=kid.id)
    shut = app.collections.create("Old", parent_id=top.id)
    app.collections.add_members(top.id, ["id-a"])
    app.collections.add_members(kid.id, ["id-b"])
    app.collections.add_members(grand.id, ["id-c"])
    app.collections.add_members(shut.id, ["id-d"])
    app.collections.close(shut.id)
    app.notes.set("collection", str(kid.id), "A note")
    app.notes.add_check("collection", str(grand.id), "A check")
    other = app.collections.create("Car")
    app.collections.add_members(other.id, ["id-a"])
    app.sync_publishers()
    return {"top": top, "kid": kid, "grand": grand, "shut": shut, "other": other}


def test_the_preview_lists_the_whole_subtree_with_its_files(app, tree):
    with make_client(app) as client:
        r = client.get(f"/api/collections/{tree['top'].id}/delete/preview")
    assert r.status_code == 200, r.text
    rows = {c["name"]: (c["state"], c["files"]) for c in r.json()["collections"]}
    assert rows == {
        "Legal": ("open", 1),
        "Michiel": ("open", 1),
        "Wills": ("open", 1),
        "Old": ("closed", 1),
    }


def test_delete_takes_the_subtree_and_its_links_and_never_a_file(app, tree, fake_archive):
    from dam.snapshots import BEFORE_DELETE, list_snapshots

    root = fake_archive.root / ONG
    assert (root / "Legal" / "Michiel" / "Wills" / "c.pdf").is_symlink()
    (root / "Legal" / "mine.txt").write_text("my own note", encoding="utf-8")  # a file of the user's
    with make_client(app) as client:
        r = client.post(f"/api/collections/{tree['top'].id}/delete", json={}, headers=LOCAL_ORIGIN)
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 4
    names = [c.name for c in app.collections.list(None)]
    assert names == ["Car"]
    assert [m.drive_id for m in app.collections.get(tree["other"].id).members] == ["id-a"]
    assert app.notes.get("collection", str(tree["kid"].id)) == ""
    assert app.notes.checklist("collection", str(tree["grand"].id)) == []
    for x in "abcd":
        assert (fake_archive.root / BANKS / f"{x}.pdf").is_file()  # no file touched
    # the links went, the user's file stayed
    assert sorted(os.listdir(root / "Legal")) == ["mine.txt"]
    assert [s.kind for s in list_snapshots(app.app_paths)] == [BEFORE_DELETE]


def test_built_in_collections_cannot_be_deleted(app, tree):
    with pytest.raises(InvalidRequest):
        app.delete_collection(app.collections.builtin("starred").id)
