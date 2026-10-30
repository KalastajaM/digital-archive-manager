"""Taking a tag off several files at once (Browse's selection actions), with Undo."""

import pytest

from test_api import BANKS, LOCAL_ORIGIN, make_client


@pytest.fixture
def client(app, fake_archive):
    for i in (1, 2, 3):
        fake_archive.add(f"{BANKS}/f{i}.pdf", drive_id=f"id-{i}", content=b"%PDF")
    app.scan()
    app.tags.add("id-1", ["house"])
    app.tags.add("id-2", ["house", "Kela"])
    with make_client(app) as c:
        yield c


def post(client, url, body):
    return client.post(url, json=body, headers=LOCAL_ORIGIN)


def tagged(app, name):
    return sorted(d for d in ("id-1", "id-2", "id-3") if name in app.tags.for_file(d))


def test_remove_from_takes_it_off_the_files_that_carry_it_and_undo_puts_it_back(client, app):
    r = post(
        client, "/api/tags/remove-from", {"tag": "house", "drive_ids": ["id-1", "id-2", "id-3"]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["message"] == "Removed 'house' from 2 files"
    assert tagged(app, "house") == []
    assert tagged(app, "Kela") == ["id-2"]  # other tags stay
    r = post(client, "/api/tags/undo", r.json()["undo"])
    assert r.status_code == 200, r.text
    assert tagged(app, "house") == ["id-1", "id-2"]  # exactly those, not id-3


def test_remove_from_an_unknown_tag_is_refused(client):
    r = post(client, "/api/tags/remove-from", {"tag": "nope", "drive_ids": ["id-1"]})
    assert r.status_code == 404 and "nope" in r.text, (
        r.text
    )  # the tag is named: not a missing route
