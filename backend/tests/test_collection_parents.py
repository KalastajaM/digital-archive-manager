"""Parent collections (round 2, Task 3): data model, service, migration, API."""

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
from dam.errors import Conflict, InvalidRequest, NotFound
from dam.index.repo import FileRepo
from dam.ops.model import Plan


@pytest.fixture
def svc(engine):
    class Fake:
        id = "ongoing"

        def plan(self, cols):
            return Plan(ops=[], origin="workflow")

    reg = PublisherRegistry()
    reg.register(Fake())
    calls = []
    s = CollectionService(
        engine,
        FileRepo(engine, "00. Inbox"),
        reg,
        SpecialFolders(),
        on_change=lambda: calls.append(1),
    )
    s.calls = calls
    return s


def names(cols):
    return [(c.name, c.path) for c in cols]


# --- service -------------------------------------------------------------------------


def test_create_a_child(svc):
    houses = svc.create("Houses")
    sauna = svc.create("Sauna", parent_id=houses.id)
    assert sauna.parent_id == houses.id
    assert sauna.path == ["Houses", "Sauna"]
    assert houses.parent_id is None and houses.path == ["Houses"]
    deck = svc.create("Deck", parent_id=sauna.id)
    assert svc.get(deck.id).path == ["Houses", "Sauna", "Deck"]
    assert svc.by_name("deck").path == ["Houses", "Sauna", "Deck"]
    assert len(svc.calls) == 3
    with pytest.raises(NotFound):
        svc.create("X", parent_id=999)
    with pytest.raises(InvalidRequest, match="already exists"):
        svc.create("sauna", parent_id=deck.id)  # names stay unique across the tree


def test_create_under_a_closed_parent_is_refused(svc):
    old = svc.create("Old")
    svc.close(old.id)
    with pytest.raises(Conflict, match="closed"):
        svc.create("New", parent_id=old.id)
    assert svc.by_name("New") is None


def test_set_parent_moves_and_returns_to_the_top(svc):
    a = svc.create("A")
    b = svc.create("B")
    calls = len(svc.calls)
    moved = svc.set_parent(b.id, a.id)
    assert moved.parent_id == a.id and moved.path == ["A", "B"]
    assert len(svc.calls) == calls + 1
    top = svc.set_parent(b.id, None)
    assert top.parent_id is None and top.path == ["B"]
    assert len(svc.calls) == calls + 2
    with pytest.raises(NotFound):
        svc.set_parent(999, None)
    with pytest.raises(NotFound):
        svc.set_parent(b.id, 999)


def test_set_parent_notify_false_skips_on_change(svc):
    a = svc.create("A")
    b = svc.create("B")
    calls = len(svc.calls)
    svc.set_parent(b.id, a.id, notify=False)
    assert len(svc.calls) == calls


def test_set_parent_to_the_same_parent_changes_nothing_and_skips_the_sync(svc):
    a = svc.create("A")
    b = svc.create("B", parent_id=a.id)
    top = svc.create("Top")
    calls = len(svc.calls)
    assert svc.set_parent(b.id, a.id).parent_id == a.id  # already there
    assert svc.set_parent(top.id, None).parent_id is None  # already at the top
    assert len(svc.calls) == calls
    with pytest.raises(NotFound):
        svc.set_parent(999, None)
    with pytest.raises(InvalidRequest):  # the checks still run for a no-op move
        svc.set_parent(b.id, b.id)


def test_a_cycle_is_refused(svc):
    a = svc.create("A")
    b = svc.create("B", parent_id=a.id)
    c = svc.create("C", parent_id=b.id)
    calls = len(svc.calls)
    with pytest.raises(InvalidRequest, match="inside itself"):
        svc.set_parent(a.id, a.id)
    with pytest.raises(InvalidRequest, match="inside itself"):
        svc.set_parent(a.id, c.id)
    with pytest.raises(InvalidRequest, match="inside itself"):
        svc.set_parent(b.id, c.id)
    assert svc.get(a.id).parent_id is None
    assert svc.get(c.id).path == ["A", "B", "C"]
    assert len(svc.calls) == calls


def test_a_closed_parent_is_refused(svc):
    a = svc.create("A")
    b = svc.create("B")
    svc.close(a.id)
    with pytest.raises(Conflict, match="closed"):
        svc.set_parent(b.id, a.id)
    svc.close(b.id)
    with pytest.raises(Conflict, match="closed"):
        svc.set_parent(b.id, a.id)  # closed under closed is refused too
    assert svc.get(b.id).parent_id is None


def test_closing_a_parent_with_open_children_is_refused(svc):
    a = svc.create("A")
    b = svc.create("B", parent_id=a.id)
    calls = len(svc.calls)
    with pytest.raises(Conflict, match="Close or move its collections first"):
        svc.close(a.id)
    assert svc.get(a.id).state == "open"
    assert len(svc.calls) == calls
    svc.close(b.id)
    assert svc.close(a.id).state == "closed"  # closed children do not hold it open


def test_close_check_refuses_a_parent_with_open_children(svc):
    """The same refusal before the close is previewed (the API's close/preview)."""
    a = svc.create("A")
    b = svc.create("B", parent_id=a.id)
    with pytest.raises(Conflict, match="Close or move its collections first"):
        svc.check_closable(a.id)
    svc.check_closable(b.id)  # a leaf: fine
    svc.close(b.id)
    svc.check_closable(a.id)  # closed children do not hold it open
    with pytest.raises(NotFound):
        svc.check_closable(999)


def test_closing_works_once_the_child_is_moved_out(svc):
    a = svc.create("A")
    b = svc.create("B", parent_id=a.id)
    svc.set_parent(b.id, None)
    assert svc.close(a.id).state == "closed"


def test_reopening_under_a_closed_parent_is_refused(svc):
    a = svc.create("A")
    b = svc.create("B", parent_id=a.id)
    svc.close(b.id)
    svc.close(a.id)
    calls = len(svc.calls)
    with pytest.raises(Conflict, match="closed"):
        svc.reopen(b.id)
    assert svc.get(b.id).state == "closed"
    assert len(svc.calls) == calls
    svc.reopen(a.id)
    assert svc.reopen(b.id).state == "open"


def test_tree_order(svc):
    houses = svc.create("Houses")
    svc.create("apple")
    sauna = svc.create("Sauna", parent_id=houses.id)
    svc.create("Deck", parent_id=sauna.id)
    svc.create("Attic", parent_id=houses.id)
    svc.create("Zebra")
    svc.create("bench", parent_id=sauna.id)
    # siblings in the order they were made (new ones go last), depth-first
    assert names(svc.list()) == [
        ("Houses", ["Houses"]),
        ("Sauna", ["Houses", "Sauna"]),
        ("Deck", ["Houses", "Sauna", "Deck"]),
        ("bench", ["Houses", "Sauna", "bench"]),
        ("Attic", ["Houses", "Attic"]),
        ("apple", ["apple"]),
        ("Zebra", ["Zebra"]),
    ]


def test_tree_order_with_a_state_filter_keeps_full_paths(svc):
    houses = svc.create("Houses")
    sauna = svc.create("Sauna", parent_id=houses.id)
    attic = svc.create("Attic", parent_id=houses.id)
    svc.close(sauna.id)
    svc.create("Zebra")
    assert names(svc.list("closed")) == [("Sauna", ["Houses", "Sauna"])]
    assert [c.name for c in svc.list()] == ["Houses", "Attic", "Zebra"]
    assert [c.name for c in svc.list(None)] == ["Houses", "Sauna", "Attic", "Zebra"]
    assert svc.get(attic.id).path == ["Houses", "Attic"]


def test_undo_keeps_parent_links(svc, engine):
    with engine.begin() as conn:
        conn.execute(
            insert(files).values(drive_id="f1", path="H/f1.pdf", path_nfc="H/f1.pdf", name="f1")
        )
    parent = svc.create("Houses")
    filed = svc.get_or_create("Sauna")  # as a filing batch creates it: at the top
    assert filed.parent_id is None
    svc.add_members(filed.id, ["f1"], batch_id="b1")
    svc.set_parent(filed.id, parent.id)
    child = svc.create("Deck", parent_id=filed.id)
    assert svc.remove_created_by("b1") == (1, 0)
    assert svc.get(filed.id).path == ["Houses", "Sauna"]
    assert svc.get(child.id).path == ["Houses", "Sauna", "Deck"]


def test_for_file_has_paths(svc, engine):
    with engine.begin() as conn:
        conn.execute(
            insert(files).values(drive_id="f1", path="H/f1.pdf", path_nfc="H/f1.pdf", name="f1")
        )
    a = svc.create("A")
    b = svc.create("B", parent_id=a.id)
    svc.add_members(b.id, ["f1"])
    assert [c.path for c in svc.for_file("f1")] == [["A", "B"]]


# --- migration -----------------------------------------------------------------------


def test_migration_0015_upgrades_a_db_at_0014(tmp_path: Path, new_engine):
    engine = new_engine(tmp_path / "old.sqlite")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with write_tx(engine) as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "0014")
    with write_tx(engine) as conn:
        conn.execute(
            text(
                "INSERT INTO collections(id, name, name_fold, state, created, publish)"
                " VALUES (1, 'Sauna', 'sauna', 'open', 1.0, '{\"ongoing\": true}')"
            )
        )
        conn.execute(text("INSERT INTO collection_members VALUES (1, 'd1', 1.0, NULL, NULL)"))
    migrate(engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0040"
        assert conn.execute(
            text("SELECT name, parent_id FROM collections WHERE kind IS NULL")
        ).one() == (
            "Sauna",
            None,
        )
        assert conn.execute(text("SELECT drive_id FROM collection_members")).scalar() == "d1"
        fks = [
            (r[2], r[3], r[4]) for r in conn.execute(text("PRAGMA foreign_key_list(collections)"))
        ]
    assert fks == [("collections", "parent_id", "id")]
    svc = CollectionService(
        engine, FileRepo(engine, "00. Inbox"), PublisherRegistry(), SpecialFolders()
    )
    child = svc.create("Deck", parent_id=1)
    assert child.path == ["Sauna", "Deck"]
    engine.dispose()


def test_migration_0016_upgrades_a_db_at_0015(tmp_path: Path, new_engine):
    engine = new_engine(tmp_path / "old.sqlite")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with write_tx(engine) as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "0015")
    with write_tx(engine) as conn:
        conn.execute(
            text(
                "INSERT INTO collections(id, name, name_fold, state, created, publish)"
                " VALUES (1, 'Sauna', 'sauna', 'open', 1.0, '{\"ongoing\": true}')"
            )
        )
    migrate(engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0040"
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(ongoing_switched)"))]
        assert cols == ["id", "batch_id", "collection_id", "rel", "link_value", "created"]
        fks = [
            (r[2], r[3], r[4], r[6])
            for r in conn.execute(text("PRAGMA foreign_key_list(ongoing_switched)"))
        ]
        assert fks == [("collections", "collection_id", "id", "CASCADE")]
    engine.dispose()


# --- API -----------------------------------------------------------------------------

BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}


@pytest.fixture
def client(app):
    with TestClient(create_api(app), base_url=BASE) as c:
        yield c


def send(client, method, url, body=None):
    return client.request(method, url, json=body if body is not None else {}, headers=LOCAL_ORIGIN)


def test_parent_routes(client, app):
    r = send(client, "POST", "/api/collections", {"name": "Houses"})
    assert r.status_code == 200, r.text
    houses = r.json()
    assert houses["parent_id"] is None and houses["path"] == ["Houses"]
    r = send(client, "POST", "/api/collections", {"name": "Sauna", "parent_id": houses["id"]})
    assert r.status_code == 200, r.text
    sauna = r.json()
    assert sauna["parent_id"] == houses["id"] and sauna["path"] == ["Houses", "Sauna"]
    attic = send(client, "POST", "/api/collections", {"name": "Attic"}).json()

    r = send(client, "PATCH", f"/api/collections/{attic['id']}/parent", {"parent_id": houses["id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"collection", "batch", "problems", "ongoing_status"}
    assert body["collection"]["path"] == ["Houses", "Attic"]

    rows = client.get("/api/collections").json()
    assert [(c["name"], c["path"]) for c in rows] == [
        ("Houses", ["Houses"]),
        ("Sauna", ["Houses", "Sauna"]),
        ("Attic", ["Houses", "Attic"]),  # moved in last: at the end of its new siblings
    ]

    r = send(client, "PATCH", f"/api/collections/{houses['id']}/parent", {"parent_id": sauna["id"]})
    assert r.status_code == 400, r.text  # a cycle

    r = send(client, "POST", f"/api/collections/{houses['id']}/close")
    assert r.status_code == 409, r.text
    assert "Close or move its collections first" in r.text
    r = send(client, "POST", f"/api/collections/{houses['id']}/close/preview")
    assert r.status_code == 409, r.text  # the preview says so too: no dead-end dialog
    assert "Close or move its collections first" in r.text
    r = send(client, "POST", f"/api/collections/{sauna['id']}/close/preview")
    assert r.status_code == 200, r.text

    r = send(client, "PATCH", f"/api/collections/{attic['id']}/parent", {"parent_id": None})
    assert r.status_code == 200, r.text
    assert r.json()["collection"]["path"] == ["Attic"]

    r = send(client, "PATCH", f"/api/collections/{attic['id']}/parent", {})
    assert r.status_code == 422, r.text  # parent_id is required (null: the top)
