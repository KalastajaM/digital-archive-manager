"""Browse with a collection filter, and the flat Files view (round 2, task 6)."""

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, text

from dam.api import create_api
from dam.db.tables import files
from dam.services.errors import NotFound

ONG = "##. Ongoing"
QUAR = "##. To Delete"
HOME = "20. Home"
BASE = "http://127.0.0.1:8765"


@pytest.fixture
def tree(app, fake_archive):
    """20. Home/{Sauna/{a,b,deep/c}, Garden/{g1,g2}, Attic/x, top.pdf}, 10. Financial/Banks/s."""
    fake_archive.add(f"{HOME}/Sauna/a.pdf", drive_id="a")
    fake_archive.add(f"{HOME}/Sauna/b.pdf", drive_id="b")
    fake_archive.add(f"{HOME}/Sauna/deep/c.pdf", b"ccc", drive_id="c")
    fake_archive.add(f"{HOME}/Garden/g1.pdf", b"gg", drive_id="g1")
    fake_archive.add(f"{HOME}/Garden/g2.pdf", drive_id="g2")
    fake_archive.add(f"{HOME}/Attic/x.pdf", drive_id="x")
    fake_archive.add(f"{HOME}/top.pdf", drive_id="top")
    fake_archive.add("10. Financial/Banks/s.pdf", drive_id="s")
    app.scan()


def folder_id(app, rel: str) -> str:
    rec = app.repo.by_path(rel)
    assert rec is not None and rec.is_dir
    return rec.drive_id


@pytest.fixture
def coll(app, tree):
    """Members: the Sauna folder and Garden/g1.pdf."""
    c = app.collections.create("House")
    app.collections.add_members(c.id, [folder_id(app, f"{HOME}/Sauna"), "g1"])
    return c


def names(entries) -> list[str]:
    return [e.name for e in entries]


# --- folders view, filtered ----------------------------------------------------------


def test_filtered_listing_shows_only_the_way_to_members(app, coll):
    assert names(app.browse.list_dir("", collection_id=coll.id)) == ["20. Home"]
    assert names(app.browse.list_dir(HOME, collection_id=coll.id)) == ["Garden", "Sauna"]
    assert names(app.browse.list_dir(f"{HOME}/Garden", collection_id=coll.id)) == ["g1.pdf"]
    assert names(app.browse.list_dir(f"{HOME}/Attic", collection_id=coll.id)) == []


def test_folder_member_shows_all_its_contents(app, coll):
    assert names(app.browse.list_dir(f"{HOME}/Sauna", collection_id=coll.id)) == [
        "deep",
        "a.pdf",
        "b.pdf",
    ]
    assert names(app.browse.list_dir(f"{HOME}/Sauna/deep", collection_id=coll.id)) == ["c.pdf"]


def test_unfiltered_listing_unchanged(app, coll):
    assert names(app.browse.list_dir(HOME)) == ["Attic", "Garden", "Sauna", "top.pdf"]


def test_filter_unknown_collection_is_not_found(app, tree):
    with pytest.raises(NotFound):
        app.browse.list_dir(HOME, collection_id=999)


def test_filter_leaves_out_quarantined_and_missing_members(app, fake_archive, coll):
    app.browse.quarantine(["g1"], origin="ui")
    app.scan()
    assert names(app.browse.list_dir(HOME, collection_id=coll.id)) == ["Sauna"]


# --- flat files view -------------------------------------------------------------------


def flat(app, rel="", **kw):
    rows, total = app.browse.files_below(rel, **kw)
    return [r.name for r in rows], total


def test_flat_lists_every_file_below_the_folder(app, tree):
    got, total = flat(app, HOME)
    assert got == ["a.pdf", "b.pdf", "c.pdf", "g1.pdf", "g2.pdf", "top.pdf", "x.pdf"]
    assert total == 7
    # a prefix is a whole component: "20. Home" never matches "20. Homework"
    assert flat(app, f"{HOME}/Sauna")[1] == 3


def test_flat_root_leaves_out_ongoing_and_quarantine(app, coll):
    app.browse.quarantine(["x"], origin="ui")
    app.scan()
    got, total = flat(app)
    assert "x.pdf" not in got and total == 7  # 6 home files + s.pdf; no Ongoing links
    assert flat(app, QUAR)[0] == ["x.pdf"]  # inside the quarantine itself: listed


def test_flat_collection_filter(app, coll):
    assert flat(app, collection_id=coll.id) == (["a.pdf", "b.pdf", "c.pdf", "g1.pdf"], 4)
    assert flat(app, f"{HOME}/Garden", collection_id=coll.id) == (["g1.pdf"], 1)
    assert flat(app, f"{HOME}/Sauna/deep", collection_id=coll.id) == (["c.pdf"], 1)


@pytest.mark.parametrize(
    ("sort", "desc", "want"),
    [
        ("name", True, ["x.pdf", "top.pdf", "g2.pdf", "g1.pdf", "c.pdf", "b.pdf", "a.pdf"]),
        ("size", True, ["c.pdf", "g1.pdf", "a.pdf", "b.pdf", "g2.pdf", "top.pdf", "x.pdf"]),
        # by folder, then name: "20. Home" itself first
        ("folder", False, ["top.pdf", "x.pdf", "g1.pdf", "g2.pdf", "a.pdf", "b.pdf", "c.pdf"]),
        ("folder", True, ["c.pdf", "b.pdf", "a.pdf", "g2.pdf", "g1.pdf", "x.pdf", "top.pdf"]),
    ],
)
def test_flat_sorting(app, tree, sort, desc, want):
    assert flat(app, HOME, sort=sort, desc=desc)[0] == want


def test_flat_date_sort(app, fake_archive, tree):
    import os

    os.utime(fake_archive.root / HOME / "Garden/g2.pdf", (1, 1))
    app.scan()
    got, _ = flat(app, HOME, sort="date")
    assert got[0] == "g2.pdf"
    assert flat(app, HOME, sort="date", desc=True)[0][-1] == "g2.pdf"


def test_flat_bad_sort_refused(app, tree):
    from dam.services.errors import InvalidRequest

    with pytest.raises(InvalidRequest):
        app.browse.files_below(HOME, sort="colour")


def bulk(app, n: int, folder: str, prefix: str = "bulk") -> None:
    rows = [
        {
            "drive_id": f"{prefix}-{i}",
            "path": f"{folder}/sub{i % 50}/f{i:05}.pdf",
            "path_nfc": f"{folder}/sub{i % 50}/f{i:05}.pdf",
            "name": f"f{i:05}.pdf",
            "ext": "pdf",
            "is_dir": False,
            "is_link": False,
            "size": i,
            "mtime": float(i),
            "index_state": "indexed",
            "missing": False,
        }
        for i in range(n)
    ]
    with app.engine.begin() as conn:
        conn.execute(insert(files), rows)


def test_flat_10000_files_gives_500_rows_and_total_fast(app, tree):
    """Review Focus 4."""
    bulk(app, 10_000, "30. Big")
    flat(app, "30. Big")  # warm up
    start = time.perf_counter()
    rows, total = app.browse.files_below("30. Big", sort="name")
    took = time.perf_counter() - start
    assert len(rows) == 500 and total == 10_000
    assert rows[0].name == "f00000.pdf" and rows[-1].name == "f00499.pdf"
    assert took < 2.0, took
    rows, total = app.browse.files_below("30. Big", sort="size", desc=True)
    assert rows[0].size == 9999 and total == 10_000


@pytest.mark.parametrize(
    ("rel", "filtered"),
    [("30. Big", False), ("30. Big", True), ("", True), (QUAR, False)],
)
@pytest.mark.parametrize("sort", ["name", "folder"])
def test_flat_queries_use_the_path_index(app, coll, rel, filtered, sort):
    """The statements files_below really runs (the excludes, the filtered OR): every
    one reads ``files`` through ``ix_files_path_nfc`` (or the primary key, for member
    files), never a full scan."""
    bulk(app, 200, "30. Big")
    # most of a real archive is elsewhere: without that, scanning everything is the
    # cheapest plan and newer SQLite versions rightly pick it
    bulk(app, 2000, "40. Elsewhere", prefix="other")
    with app.engine.begin() as conn:
        conn.execute(text("ANALYZE"))  # the planner with statistics, as a used database has
    statements = app.browse.files_below_sql(rel, coll.id if filtered else None, sort=sort)
    assert len(statements) == 2
    with app.engine.connect() as conn:
        for sql in statements:
            plan = [r[-1] for r in conn.execute(text(f"EXPLAIN QUERY PLAN {sql}"))]
            reads = [step for step in plan if " files" in step]
            assert reads and all("SCAN files" not in step for step in reads), plan
            assert any("ix_files_path_nfc" in step for step in reads), plan


def test_flat_and_listing_ignore_a_trailing_slash(app, coll):
    assert flat(app, f"{HOME}/Sauna/") == flat(app, f"{HOME}/Sauna")
    assert names(app.browse.list_dir(f"{HOME}/", collection_id=coll.id)) == ["Garden", "Sauna"]
    assert names(app.browse.list_dir(f"{HOME}/")) == names(app.browse.list_dir(HOME))


# --- a parent collection: its descendants' members count (coordinator ruling) ----------


@pytest.fixture
def family(app, tree):
    """Houses (no members of its own) > House (Garden/g1.pdf) > Shed (the Attic folder)."""
    houses = app.collections.create("Houses")
    house = app.collections.create("House", parent_id=houses.id)
    shed = app.collections.create("Shed", parent_id=house.id)
    app.collections.add_members(house.id, ["g1"])
    app.collections.add_members(shed.id, [folder_id(app, f"{HOME}/Attic")])
    return houses, house, shed


def test_parent_filter_includes_child_and_grandchild_members(app, family):
    houses, house, shed = family
    assert names(app.browse.list_dir(HOME, collection_id=houses.id)) == ["Attic", "Garden"]
    assert names(app.browse.list_dir(f"{HOME}/Attic", collection_id=houses.id)) == ["x.pdf"]
    assert flat(app, collection_id=houses.id) == (["g1.pdf", "x.pdf"], 2)
    # a child: itself and below, never its parent's or a sibling's
    assert flat(app, collection_id=house.id) == (["g1.pdf", "x.pdf"], 2)
    assert flat(app, collection_id=shed.id) == (["x.pdf"], 1)
    assert names(app.browse.list_dir(HOME, collection_id=shed.id)) == ["Attic"]


def test_member_in_parent_and_child_is_listed_once(app, family):
    houses, house, _ = family
    app.collections.add_members(houses.id, ["g1"])
    assert flat(app, collection_id=houses.id) == (["g1.pdf", "x.pdf"], 2)


def test_api_parent_filter(client, family):
    houses = family[0]
    r = client.get("/api/browse", params={"path": HOME, "collection": houses.id})
    assert [e["name"] for e in r.json()] == ["Attic", "Garden"]
    body = client.get("/api/browse/files", params={"collection": houses.id}).json()
    assert body["total"] == 2 and [e["name"] for e in body["rows"]] == ["g1.pdf", "x.pdf"]


# --- API -----------------------------------------------------------------------------


@pytest.fixture
def client(app):
    with TestClient(create_api(app, None), base_url=BASE) as c:
        yield c


def test_api_browse_with_collection(client, coll):
    r = client.get("/api/browse", params={"path": HOME, "collection": coll.id})
    assert [e["name"] for e in r.json()] == ["Garden", "Sauna"]
    assert client.get("/api/browse", params={"path": HOME, "collection": 999}).status_code == 404
    assert len(client.get("/api/browse", params={"path": HOME}).json()) == 4


def test_api_browse_files(client, app, coll):
    r = client.get("/api/browse/files", params={"path": HOME, "sort": "size", "dir": "desc"})
    body = r.json()
    assert body["total"] == 7 and body["rows"][0]["name"] == "c.pdf"
    assert set(body["rows"][0]) >= {"name", "path", "is_dir", "is_link", "size", "mtime"}
    r = client.get("/api/browse/files", params={"collection": coll.id, "limit": 2})
    assert r.json()["total"] == 4 and len(r.json()["rows"]) == 2
    assert client.get("/api/browse/files", params={"limit": 501}).status_code == 422
    assert client.get("/api/browse/files", params={"sort": "colour"}).status_code == 422
    assert client.get("/api/browse/files", params={"dir": "up"}).status_code == 422


# --- a folder member brings everything inside it, at any depth ------------------------


def test_folder_member_includes_its_files_at_any_depth_but_not_a_lookalike_sibling(
    app, fake_archive, coll
):
    fake_archive.add(f"{HOME}/Sauna 2/other.pdf", drive_id="other")
    fake_archive.add(f"{HOME}/Sauna/deep/deeper/d.pdf", drive_id="d")
    app.scan()
    # Folders view: the member folder and its parents, its contents browsable, no sibling
    assert names(app.browse.list_dir(HOME, collection_id=coll.id)) == ["Garden", "Sauna"]
    assert names(app.browse.list_dir(f"{HOME}/Sauna/deep", collection_id=coll.id)) == [
        "deeper",
        "c.pdf",
    ]
    assert names(app.browse.list_dir(f"{HOME}/Sauna/deep/deeper", collection_id=coll.id)) == [
        "d.pdf"
    ]
    # Files view: the member folder's files with the member file, one query per count/rows
    assert flat(app, collection_id=coll.id) == (["a.pdf", "b.pdf", "c.pdf", "d.pdf", "g1.pdf"], 5)


def test_api_folder_member_contents(client, app, fake_archive, coll):
    fake_archive.add(f"{HOME}/Sauna/new.pdf", drive_id="new")
    app.scan()
    r = client.get("/api/browse", params={"path": f"{HOME}/Sauna", "collection": coll.id})
    assert [e["name"] for e in r.json()] == ["deep", "a.pdf", "b.pdf", "new.pdf"]
    body = client.get("/api/browse/files", params={"collection": coll.id}).json()
    assert body["total"] == 5
