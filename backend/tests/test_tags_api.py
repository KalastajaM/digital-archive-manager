"""GET /api/tags: the tags in use with their file counts, for the tag field's suggestions."""

import pytest

from test_api import BANKS, make_client


@pytest.fixture
def client(app, fake_archive):
    for i in (1, 2, 3):
        fake_archive.add(f"{BANKS}/f{i}.pdf", drive_id=f"id-{i}")
    app.scan()
    app.tags.add("id-1", ["bank", "Bills", "tax"])
    app.tags.add("id-2", ["bank", "tax"])
    app.tags.add("id-3", ["bank", "Ääni"])
    with make_client(app) as c:
        yield c


def names(client, **params):
    r = client.get("/api/tags", params=params)
    assert r.status_code == 200, r.text
    return [(t["name"], t["files"]) for t in r.json()]


def test_all_tags_most_used_first_then_by_name(client):
    assert names(client) == [("bank", 3), ("tax", 2), ("Bills", 1), ("Ääni", 1)]


def test_prefix_ignores_case_and_accents(client):
    assert names(client, prefix="b") == [("bank", 3), ("Bills", 1)]
    assert names(client, prefix="BI") == [("Bills", 1)]
    assert names(client, prefix="aa") == [("Ääni", 1)]  # Ä folds to a
    assert names(client, prefix="Aan") == [("Ääni", 1)]
    assert names(client, prefix="  ta ") == [("tax", 2)]
    assert names(client, prefix="zzz") == []


def test_wildcards_are_literal(client):
    assert names(client, prefix="%") == []
    assert names(client, prefix="_") == []


def test_limit(client):
    assert names(client, limit=2) == [("bank", 3), ("tax", 2)]
    assert client.get("/api/tags", params={"limit": 0}).status_code == 422


def test_a_tag_no_file_has_any_more_is_not_listed(client, app):
    app.tags.set_for_file("id-3", [])
    assert ("Ääni", 1) not in names(client)
