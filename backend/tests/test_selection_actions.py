"""Several files at once in a collection (Browse's selection actions)."""

import pytest

from test_api import BANKS, LOCAL_ORIGIN, make_client


@pytest.fixture
def client(app, fake_archive):
    for i in (1, 2, 3):
        fake_archive.add(f"{BANKS}/f{i}.pdf", drive_id=f"id-{i}", content=b"%PDF")
    app.scan()
    with make_client(app) as c:
        yield c


def test_remove_many_takes_several_files_out_of_a_collection(client, app):
    c = app.collections.create("House")
    app.collections.add_members(c.id, ["id-1", "id-2", "id-3"])
    r = client.post(
        f"/api/collections/{c.id}/members/remove-many",
        json={"drive_ids": ["id-1", "id-3", "id-9"]},
        headers=LOCAL_ORIGIN,
    )
    assert r.status_code == 200, r.text
    assert [m["drive_id"] for m in r.json()["collection"]["members"]] == ["id-2"]


def test_files_cannot_be_moved_out_of_or_into_starred_or_important(client, app):
    house = app.collections.create("House")
    starred = app.collections.builtin("starred")
    app.collections.add_members(starred.id, ["id-1"])
    app.collections.add_members(house.id, ["id-2"])
    out = client.post(
        f"/api/collections/{starred.id}/members/move",
        json={"to": house.id, "drive_ids": ["id-1"]},
        headers=LOCAL_ORIGIN,
    )
    into = client.post(
        f"/api/collections/{house.id}/members/move",
        json={"to": starred.id, "drive_ids": ["id-2"]},
        headers=LOCAL_ORIGIN,
    )
    assert (out.status_code, into.status_code) == (400, 400), (out.text, into.text)
    assert [m.drive_id for m in app.collections.get(starred.id).members] == ["id-1"]
