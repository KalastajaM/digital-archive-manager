"""The owner's order of collections: migration backfill, ordering, move service and API."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import insert, text

from dam.api import create_api
from dam.collections.publishers import PublisherRegistry
from dam.collections.service import CollectionService
from dam.config import SpecialFolders
from dam.db.engine import MIGRATIONS_DIR, migrate, write_tx
from dam.db.tables import files
from dam.index.repo import FileRepo
from dam.services.errors import InvalidRequest, NotFound


@pytest.fixture
def svc(engine):
    return CollectionService(
        engine, FileRepo(engine, "00. Inbox"), PublisherRegistry(), SpecialFolders()
    )


def top(svc):
    return [c.name for c in svc.list("open")]


def test_new_collections_go_at_the_end_of_their_siblings(svc):
    svc.create("Zebra")
    svc.create("Apple")
    assert top(svc) == ["Zebra", "Apple"]  # creation order, not A-Z
    houses = svc.create("Houses")
    svc.create("Sauna", parent_id=houses.id)
    svc.create("Attic", parent_id=houses.id)
    assert top(svc) == ["Zebra", "Apple", "Houses", "Sauna", "Attic"]


def test_move_before_and_after(svc):
    a, b, c = (svc.create(n) for n in "ABC")
    assert svc.move(c.id, before_id=a.id).position == 0
    assert top(svc) == ["C", "A", "B"]
    svc.move(c.id, after_id=b.id)
    assert top(svc) == ["A", "B", "C"]
    svc.move(a.id, after_id=b.id)
    assert top(svc) == ["B", "A", "C"]
    assert [x.position for x in svc.list("open")] == [0, 1, 2]
    svc.move(a.id, after_id=b.id)  # the same place again: nothing changes
    assert top(svc) == ["B", "A", "C"]


def test_move_among_nested_siblings_only(svc):
    houses = svc.create("Houses")
    cars = svc.create("Cars")
    s1 = svc.create("Sauna", parent_id=houses.id)
    s2 = svc.create("Attic", parent_id=houses.id)
    svc.move(s2.id, before_id=s1.id)
    assert top(svc) == ["Houses", "Attic", "Sauna", "Cars"]
    svc.move(houses.id, after_id=cars.id)  # the subtree goes along
    assert top(svc) == ["Cars", "Houses", "Attic", "Sauna"]
    assert top(svc) == ["Cars", "Houses", "Attic", "Sauna"]


def test_move_beside_a_collection_of_another_parent_reparents(svc):
    houses = svc.create("Houses")
    sauna = svc.create("Sauna", parent_id=houses.id)
    attic = svc.create("Attic", parent_id=houses.id)
    cars = svc.create("Cars")
    boat = svc.create("Boat")
    calls = []
    svc.on_change = lambda *a: calls.append(1)
    # out to the top level, right after Houses
    moved = svc.move(sauna.id, after_id=houses.id)
    assert moved.parent_id is None and moved.path == ["Sauna"]
    assert top(svc) == ["Houses", "Attic", "Sauna", "Cars", "Boat"]
    assert len(calls) == 1  # a new parent follows the Ongoing sync
    svc.move(cars.id, before_id=houses.id)
    assert len(calls) == 1  # the same parent: order only, no sync
    # in to Houses, before Attic (a sibling there)
    moved = svc.move(boat.id, before_id=attic.id)
    assert moved.parent_id == houses.id and moved.path == ["Houses", "Boat"]
    assert top(svc) == ["Cars", "Houses", "Boat", "Attic", "Sauna"]
    assert [c.position for c in svc.list("open") if c.parent_id == houses.id] == [0, 1]
    # a subtree goes along
    svc.move(houses.id, before_id=cars.id)
    assert svc.get(attic.id).path == ["Houses", "Attic"]


def test_cross_level_move_refuses_cycles_and_closed_parents(svc):
    houses = svc.create("Houses")
    sauna = svc.create("Sauna", parent_id=houses.id)
    deck = svc.create("Deck", parent_id=sauna.id)
    other = svc.create("Other")
    with pytest.raises(InvalidRequest, match="inside itself"):
        svc.move(houses.id, before_id=deck.id)  # Deck's parent is below Houses
    with pytest.raises(InvalidRequest, match="inside itself"):
        svc.move(sauna.id, after_id=deck.id)
    svc.move(other.id, before_id=deck.id)  # not a cycle: Other is not above Deck
    assert svc.get(other.id).path == ["Houses", "Sauna", "Other"]
    assert svc.get(deck.id).path == ["Houses", "Sauna", "Deck"]


def test_closed_siblings_keep_their_place(svc):
    a, b, c = (svc.create(n) for n in "ABC")
    svc.close(b.id)
    svc.move(c.id, before_id=a.id)
    assert top(svc) == ["C", "A"]
    svc.reopen(b.id)
    assert top(svc) == ["C", "A", "B"]


def test_moving_in_changes_the_parent_and_goes_last(svc):
    houses = svc.create("Houses")
    svc.create("Sauna", parent_id=houses.id)
    attic = svc.create("Attic")
    svc.set_parent(attic.id, houses.id)
    assert top(svc) == ["Houses", "Sauna", "Attic"]


def test_refusals(svc):
    a = svc.create("A")
    b = svc.create("B")
    starred = svc.builtin("starred")
    important = svc.builtin("important")
    with pytest.raises(InvalidRequest, match="built in"):
        svc.move(starred.id, after_id=a.id)
    with pytest.raises(InvalidRequest, match="built in"):
        svc.move(a.id, before_id=important.id)
    with pytest.raises(InvalidRequest, match="itself"):
        svc.move(a.id, after_id=a.id)
    with pytest.raises(InvalidRequest, match="exactly one"):
        svc.move(a.id)
    with pytest.raises(InvalidRequest, match="exactly one"):
        svc.move(a.id, before_id=b.id, after_id=b.id)
    with pytest.raises(NotFound):
        svc.move(a.id, before_id=999)
    with pytest.raises(NotFound):
        svc.move(999, before_id=a.id)
    assert top(svc) == ["A", "B"]


def test_builtins_stay_first_in_every_list(svc):
    svc.create("Zed")
    names = [c.name for c in svc.list("open", include_builtin=True)]
    assert [n for n in names if n != "Zed"] == names[:2] and names[-1] == "Zed"
    assert all(c.kind for c in svc.list("open", include_builtin=True)[:2])


def test_for_file_follows_the_order(svc, engine):
    with engine.begin() as conn:
        conn.execute(
            insert(files).values(drive_id="f1", path="H/f1.pdf", path_nfc="H/f1.pdf", name="f1")
        )
    a, b = svc.create("A"), svc.create("B")
    svc.add_members(a.id, ["f1"])
    svc.add_members(b.id, ["f1"])
    assert [c.name for c in svc.for_file("f1")] == ["A", "B"]
    svc.move(b.id, before_id=a.id)
    assert [c.name for c in svc.for_file("f1")] == ["B", "A"]


def test_migration_0032_backfills_the_name_order_per_parent(tmp_path: Path, new_engine):
    engine = new_engine(tmp_path / "old.sqlite")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with write_tx(engine) as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "0031")
    rows = [(10, "Zebra", None), (11, "apple", None), (12, "Mango", 10), (13, "Kiwi", 10)]
    with write_tx(engine) as conn:
        for cid, name, parent in rows:
            conn.execute(
                text(
                    "INSERT INTO collections(id, name, name_fold, state, created, publish,"
                    " parent_id) VALUES (:i, :n, :f, 'open', 1.0, '{}', :p)"
                ),
                {"i": cid, "n": name, "f": name.casefold(), "p": parent},
            )
    migrate(engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0036"
        got = dict(conn.execute(text("SELECT id, position FROM collections")).all())
        kinds = conn.execute(text("SELECT position FROM collections WHERE kind IS NOT NULL")).all()
    assert (got[11], got[10]) == (0, 1)  # apple, Zebra
    assert (got[13], got[12]) == (0, 1)  # Kiwi, Mango inside Zebra
    assert [k[0] for k in kinds] == [0, 0]
    svc = CollectionService(
        engine, FileRepo(engine, "00. Inbox"), PublisherRegistry(), SpecialFolders()
    )
    assert [c.name for c in svc.list("open")] == ["apple", "Zebra", "Kiwi", "Mango"]
    assert svc.create("New").position == 2


# --- API -----------------------------------------------------------------------------

BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}


@pytest.fixture
def client(app):
    with TestClient(create_api(app), base_url=BASE) as c:
        yield c


def send(client, method, url, body=None):
    return client.request(method, url, json=body if body is not None else {}, headers=LOCAL_ORIGIN)


def test_move_route_and_list_order(client):
    ids = {n: send(client, "POST", "/api/collections", {"name": n}).json()["id"] for n in "ABC"}
    r = send(client, "POST", f"/api/collections/{ids['C']}/move", {"before_id": ids["A"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"collection", "batch", "problems", "ongoing_status"}
    assert body["batch"] is None and body["collection"]["position"] == 0
    rows = client.get("/api/collections").json()
    assert [c["name"] for c in rows] == ["C", "A", "B"]
    assert [c["position"] for c in rows] == [0, 1, 2]
    r = send(client, "POST", f"/api/collections/{ids['C']}/move", {"after_id": ids["B"]})
    assert [c["name"] for c in client.get("/api/collections").json()] == ["A", "B", "C"]


def test_move_route_refusals(client, app):
    a = send(client, "POST", "/api/collections", {"name": "A"}).json()["id"]
    inner = send(client, "POST", "/api/collections", {"name": "In", "parent_id": a}).json()["id"]
    b = send(client, "POST", "/api/collections", {"name": "B"}).json()["id"]
    starred = app.collections.builtin("starred").id
    url = "/api/collections/{}/move"
    assert send(client, "POST", url.format(starred), {"after_id": a}).status_code == 400
    assert send(client, "POST", url.format(a), {"before_id": starred}).status_code == 400
    assert send(client, "POST", url.format(a), {}).status_code == 400
    assert send(client, "POST", url.format(a), {"before_id": a}).status_code == 400
    # another parent is no refusal now: it moves out, to b's level (b is top level)
    r = send(client, "POST", url.format(inner), {"before_id": b})
    assert r.status_code == 200, r.text
    assert r.json()["collection"]["parent_id"] is None
    assert [c["name"] for c in client.get("/api/collections").json()] == ["A", "In", "B"]
    kid = send(client, "POST", "/api/collections", {"name": "Kid", "parent_id": a}).json()["id"]
    assert send(client, "POST", url.format(a), {"before_id": kid}).status_code == 400  # a cycle
    assert send(client, "POST", url.format(a), {"before_id": 999}).status_code == 404
    assert send(client, "POST", url.format(999), {"before_id": a}).status_code == 404
