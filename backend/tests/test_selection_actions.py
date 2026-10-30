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
