"""Collection groups (nested, per collection) and summaries: service, migration, API, CLI."""

import os
from datetime import date, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, text

from dam.api import create_api
from dam.collections.publishers import PublisherRegistry
from dam.collections.service import SUMMARY_MAX, CollectionService
from dam.config import SpecialFolders
from dam.db.engine import MIGRATIONS_DIR, migrate, write_tx
from dam.db.tables import collection_groups, collection_members, files
from dam.index.repo import FileRepo
from dam.ops.model import Plan
from dam.services.errors import InvalidRequest, NotFound


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


@pytest.fixture
def docs(engine):
    with engine.begin() as conn:
        for d in ("f1", "f2", "f3"):
            conn.execute(
                insert(files).values(
                    drive_id=d, path=f"Home/{d}.pdf", path_nfc=f"Home/{d}.pdf", name=f"{d}.pdf"
                )
            )
    return ["f1", "f2", "f3"]


def tree(c):
    """{(parent_id, position): name} -> a readable outline of the groups."""
    return [(g.parent_id, g.position, g.name) for g in c.groups]


# --- create, rename, nesting -------------------------------------------------------


def test_create_rename_and_nest(svc):
    c = svc.create("Sauna")
    assert (c.summary, c.groups) == ("", [])
    plans = svc.create_group(c.id, "  Plans ")
    quotes = svc.create_group(c.id, "Quotes")
    draft = svc.create_group(c.id, "Drafts", parent_id=plans.id)
    assert (plans.name, plans.parent_id, plans.position, plans.summary) == ("Plans", None, 0, "")
    assert (quotes.position, draft.parent_id, draft.position) == (1, plans.id, 0)
    renamed = svc.rename_group(draft.id, "Old drafts")
    assert renamed.name == "Old drafts" and renamed.parent_id == plans.id
    got = svc.get(c.id)
    assert tree(got) == [(None, 0, "Plans"), (None, 1, "Quotes"), (plans.id, 0, "Old drafts")]
    assert svc.group(draft.id).collection_id == c.id


def test_every_group_change_notifies_after_commit(svc, docs):
    c = svc.create("Sauna")
    svc.calls.clear()
    g = svc.create_group(c.id, "A")
    h = svc.create_group(c.id, "B")
    svc.rename_group(g.id, "A2")
    svc.move_group(h.id, g.id, 0)
    svc.set_member_group(c.id, ["f1"], g.id)
    svc.set_summary(c.id, "x")
    svc.set_group_summary(g.id, "y")
    svc.remove_group(h.id)
    assert len(svc.calls) == 8
    svc.create_group(c.id, "C", notify=False)
    svc.set_member_group(c.id, ["f2"], None, notify=False)
    assert len(svc.calls) == 8


def test_group_names_are_checked(svc):
    c = svc.create("Sauna")
    for bad in ("", "  ", "a/b", ".hidden", "x" * 121, None):
        with pytest.raises(InvalidRequest):
            svc.create_group(c.id, bad)
    g = svc.create_group(c.id, "Ok")
    with pytest.raises(InvalidRequest):
        svc.rename_group(g.id, "trail.")


def test_unknown_ids(svc):
    c = svc.create("Sauna")
    other = svc.create("Other")
    foreign = svc.create_group(other.id, "Theirs")
    with pytest.raises(NotFound):
        svc.create_group(999, "A")
    with pytest.raises(NotFound):
        svc.rename_group(999, "A")
    with pytest.raises(NotFound):
        svc.remove_group(999)
    with pytest.raises(NotFound):
        svc.group(999)
    with pytest.raises(InvalidRequest):  # a parent from another collection
        svc.create_group(c.id, "A", parent_id=foreign.id)
    with pytest.raises(InvalidRequest):
        svc.set_member_group(c.id, [], foreign.id)


# --- sibling names -----------------------------------------------------------------


def test_sibling_names_are_unique_after_folding(svc):
    c = svc.create("Sauna")
    plans = svc.create_group(c.id, "Plans")
    with pytest.raises(InvalidRequest, match="already"):
        svc.create_group(c.id, "PLANS")
    svc.create_group(c.id, "plans", parent_id=plans.id)  # another parent: fine
    other = svc.create("Other")
    svc.create_group(other.id, "Plans")  # another collection: fine
    quotes = svc.create_group(c.id, "Quotes")
    with pytest.raises(InvalidRequest, match="already"):
        svc.rename_group(quotes.id, "plans")
    svc.rename_group(plans.id, "PLANS")  # its own name, other case
    inner = svc.create_group(c.id, "Quotes", parent_id=plans.id)
    with pytest.raises(InvalidRequest, match="already"):  # moving into a clash
        svc.move_group(inner.id, None, 0)


# --- moving ------------------------------------------------------------------------


def test_move_reorders_and_reparents(svc):
    c = svc.create("Sauna")
    a, b, d = (svc.create_group(c.id, n) for n in ("A", "B", "D"))
    svc.move_group(d.id, None, 0)
    assert tree(svc.get(c.id)) == [(None, 0, "D"), (None, 1, "A"), (None, 2, "B")]
    svc.move_group(d.id, None, 99)  # clamped to the end
    assert tree(svc.get(c.id)) == [(None, 0, "A"), (None, 1, "B"), (None, 2, "D")]
    moved = svc.move_group(a.id, b.id, 0)
    assert (moved.parent_id, moved.position) == (b.id, 0)
    assert tree(svc.get(c.id)) == [(None, 0, "B"), (None, 1, "D"), (b.id, 0, "A")]
    with pytest.raises(InvalidRequest):
        svc.move_group(a.id, None, -1)


def test_move_refuses_a_cycle(svc):
    c = svc.create("Sauna")
    a = svc.create_group(c.id, "A")
    b = svc.create_group(c.id, "B", parent_id=a.id)
    d = svc.create_group(c.id, "D", parent_id=b.id)
    for parent in (a.id, b.id, d.id):
        with pytest.raises(InvalidRequest, match="inside itself"):
            svc.move_group(a.id, parent, 0)
    other = svc.create("Other")
    with pytest.raises(InvalidRequest):
        svc.move_group(a.id, svc.create_group(other.id, "X").id, 0)
    assert tree(svc.get(c.id)) == [(None, 0, "A"), (a.id, 0, "B"), (b.id, 0, "D")]


# --- removing ----------------------------------------------------------------------


def test_remove_moves_children_and_members_up(svc, docs):
    c = svc.create("Sauna")
    top = svc.create_group(c.id, "Top")
    after = svc.create_group(c.id, "After")
    mid = svc.create_group(c.id, "Mid", parent_id=top.id)
    svc.create_group(c.id, "Kid1", parent_id=mid.id)
    svc.create_group(c.id, "Kid2", parent_id=mid.id)
    svc.set_member_group(c.id, ["f1"], mid.id)
    svc.set_member_group(c.id, ["f2"], top.id)
    svc.remove_group(mid.id)
    got = svc.get(c.id)
    assert tree(got) == [
        (None, 0, "Top"),
        (None, 1, "After"),
        (top.id, 0, "Kid1"),
        (top.id, 1, "Kid2"),
    ]
    assert {m.drive_id: m.group_id for m in got.members} == {"f1": top.id, "f2": top.id}
    svc.remove_group(top.id)  # to the top level: ungrouped
    got = svc.get(c.id)
    assert {m.drive_id: m.group_id for m in got.members} == {"f1": None, "f2": None}
    assert tree(got) == [(None, 0, "Kid1"), (None, 1, "Kid2"), (None, 2, "After")]
    assert after.id in {g.id for g in got.groups}


def test_remove_refuses_a_name_clash_with_the_new_siblings(svc):
    c = svc.create("Sauna")
    a = svc.create_group(c.id, "A")
    svc.create_group(c.id, "B")
    svc.create_group(c.id, "b", parent_id=a.id)
    with pytest.raises(InvalidRequest, match="already"):
        svc.remove_group(a.id)
    assert len(svc.get(c.id).groups) == 3


def test_removing_groups_never_removes_a_membership(svc, docs):
    c = svc.create("Sauna")
    a = svc.create_group(c.id, "A")
    b = svc.create_group(c.id, "B", parent_id=a.id)
    svc.set_member_group(c.id, docs, b.id)
    svc.remove_group(a.id)
    svc.remove_group(b.id)
    got = svc.get(c.id)
    assert got.groups == []
    assert [(m.drive_id, m.group_id) for m in got.members] == [(d, None) for d in docs]


# --- members -----------------------------------------------------------------------


def test_set_member_group_moves_and_adds(svc, docs):
    c = svc.create("Sauna")
    a = svc.create_group(c.id, "A")
    b = svc.create_group(c.id, "B")
    svc.add_members(c.id, ["f1"])
    got = svc.set_member_group(c.id, ["f1", "f2"], a.id)  # f2 is not a member yet
    assert {m.drive_id: m.group_id for m in got.members} == {"f1": a.id, "f2": a.id}
    got = svc.set_member_group(c.id, ["f2"], b.id)  # one group per collection
    assert {m.drive_id: m.group_id for m in got.members} == {"f1": a.id, "f2": b.id}
    got = svc.set_member_group(c.id, ["f1"], None)
    assert {m.drive_id: m.group_id for m in got.members} == {"f1": None, "f2": b.id}
    with pytest.raises(NotFound):
        svc.set_member_group(c.id, ["nope"], a.id)
    with pytest.raises(NotFound):
        svc.set_member_group(c.id, ["f1"], 999)
    # another collection keeps its own (ungrouped) membership of the same file
    o = svc.add_members(svc.create("Other").id, ["f2"])
    assert [m.group_id for m in o.members] == [None]


def test_re_adding_a_member_keeps_its_group(svc, docs):
    c = svc.create("Sauna")
    a = svc.create_group(c.id, "A")
    svc.set_member_group(c.id, ["f1"], a.id)
    got = svc.add_members(c.id, ["f1"])
    assert [m.group_id for m in got.members] == [a.id]


def test_undo_removes_members_and_their_group_but_never_groups(svc, docs):
    c = svc.create("Sauna")
    a = svc.create_group(c.id, "A")
    svc.add_members(c.id, ["f1"], batch_id="b1")
    svc.set_member_group(c.id, ["f1", "f2"], a.id)
    assert svc.remove_created_by("b1") == (1, 0)
    got = svc.get(c.id)
    assert [(m.drive_id, m.group_id) for m in got.members] == [("f2", a.id)]
    assert [g.name for g in got.groups] == ["A"]
    svc.add_members(c.id, ["f1"])
    assert {m.drive_id: m.group_id for m in svc.get(c.id).members} == {"f1": None, "f2": a.id}


def test_a_collection_going_takes_its_groups(svc, engine, docs):
    c = svc.create("Sauna")
    g = svc.create_group(c.id, "A")
    svc.create_group(c.id, "B", parent_id=g.id)
    with write_tx(engine) as conn:
        conn.execute(text("DELETE FROM collections WHERE id = :i"), {"i": c.id})
    with engine.connect() as conn:
        assert conn.execute(select(collection_groups)).all() == []
        assert conn.execute(select(collection_members)).all() == []


# --- summaries ---------------------------------------------------------------------


def test_summaries_are_stripped_and_limited(svc):
    c = svc.create("Sauna")
    g = svc.create_group(c.id, "A")
    assert svc.set_summary(c.id, "  The sauna build.\n").summary == "The sauna build."
    assert svc.set_group_summary(g.id, " Plans ").summary == "Plans"
    assert svc.get(c.id).groups[0].summary == "Plans"
    assert svc.set_summary(c.id, "x" * SUMMARY_MAX).summary == "x" * SUMMARY_MAX
    assert SUMMARY_MAX == 4000
    for setter, target in ((svc.set_summary, c.id), (svc.set_group_summary, g.id)):
        with pytest.raises(InvalidRequest, match="4000"):
            setter(target, "x" * (SUMMARY_MAX + 1))
        with pytest.raises(InvalidRequest):
            setter(target, 5)
    assert svc.set_summary(c.id, "").summary == ""
    with pytest.raises(NotFound):
        svc.set_summary(999, "x")
    with pytest.raises(NotFound):
        svc.set_group_summary(999, "x")


# --- migration ---------------------------------------------------------------------


def test_migration_0011_upgrades_a_db_at_0010(tmp_path: Path, new_engine):
    engine = new_engine(tmp_path / "old.sqlite")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with write_tx(engine) as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "0010")
    with write_tx(engine) as conn:
        conn.execute(
            text(
                "INSERT INTO collections(id, name, name_fold, state, created, publish)"
                " VALUES (1, 'Sauna', 'sauna', 'open', 1.0, '{\"ongoing\": true}')"
            )
        )
        conn.execute(text("INSERT INTO collection_members VALUES (1, 'd1', 1.0, NULL)"))
    migrate(engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0026"
        assert conn.execute(text("SELECT summary FROM collections")).scalar() == ""
        assert conn.execute(text("SELECT drive_id, group_id FROM collection_members")).one() == (
            "d1",
            None,
        )
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(collection_groups)"))]
    assert cols == [
        "id", "collection_id", "parent_id", "name", "name_fold", "position", "summary",
        "created_by_batch",  # stars (0018)
    ]  # fmt: skip
    svc = CollectionService(
        engine, FileRepo(engine, "00. Inbox"), PublisherRegistry(), SpecialFolders()
    )
    g = svc.create_group(1, "Plans")
    assert svc.get(1).groups[0].id == g.id
    engine.dispose()


# --- API and CLI -------------------------------------------------------------------

BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}
BANKS = "10. Financial/Banks"


@pytest.fixture
def client(app):
    with TestClient(create_api(app), base_url=BASE) as c:
        yield c


def send(client, method, url, body=None):
    return client.request(method, url, json=body if body is not None else {}, headers=LOCAL_ORIGIN)


@pytest.fixture
def api_files(app, fake_archive):
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="f1")
    fake_archive.add(f"{BANKS}/b.pdf", drive_id="f2")
    app.scan()


def test_group_routes(client, app, api_files, fake_archive):
    cid = send(client, "POST", "/api/collections", {"name": "Sauna"}).json()["id"]
    r = send(client, "POST", f"/api/collections/{cid}/groups", {"name": "Plans", "parent_id": None})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"collection", "batch", "problems", "ongoing_status"}
    plans = body["collection"]["groups"][0]
    assert {k: plans[k] for k in ("name", "parent_id", "position", "summary")} == {
        "name": "Plans",
        "parent_id": None,
        "position": 0,
        "summary": "",
    }
    r = send(
        client, "POST", f"/api/collections/{cid}/groups", {"name": "Old", "parent_id": plans["id"]}
    )
    old = next(g for g in r.json()["collection"]["groups"] if g["name"] == "Old")
    assert old["parent_id"] == plans["id"]
    assert (
        send(client, "POST", f"/api/collections/{cid}/groups", {"name": "plans"}).status_code == 400
    )
    assert send(client, "POST", "/api/collections/999/groups", {"name": "X"}).status_code == 404

    r = send(
        client,
        "POST",
        f"/api/collections/{cid}/members/group",
        {"drive_ids": ["f1", "f2"], "group_id": old["id"]},
    )
    assert r.status_code == 200, r.text
    members = r.json()["collection"]["members"]
    assert {m["drive_id"]: m["group_id"] for m in members} == {"f1": old["id"], "f2": old["id"]}
    # groups are nested folders in Ongoing (Task 8): Sauna/Plans/Old/{a,b}.pdf
    ongoing = fake_archive.root / "##. Ongoing" / "Sauna"
    assert sorted(os.listdir(ongoing)) == ["Plans"]
    assert sorted(os.listdir(ongoing / "Plans")) == ["Old"]
    assert sorted(os.listdir(ongoing / "Plans" / "Old")) == ["a.pdf", "b.pdf"]

    # PATCH: rename, summary, move to top level in one go; parent_id null is meaningful
    r = send(
        client,
        "PATCH",
        f"/api/collection-groups/{old['id']}",
        {"name": "Archive", "summary": " Older plans ", "parent_id": None, "position": 0},
    )
    assert r.status_code == 200, r.text
    groups = {g["id"]: g for g in r.json()["collection"]["groups"]}
    assert {k: groups[old["id"]][k] for k in ("name", "summary", "parent_id", "position")} == {
        "name": "Archive",
        "summary": "Older plans",
        "parent_id": None,
        "position": 0,
    }
    assert groups[plans["id"]]["position"] == 1
    # leaving parent_id out keeps the parent
    r = send(client, "PATCH", f"/api/collection-groups/{old['id']}", {"position": 5})
    g = next(x for x in r.json()["collection"]["groups"] if x["id"] == old["id"])
    assert (g["parent_id"], g["position"]) == (None, 1)
    bad = send(client, "PATCH", f"/api/collection-groups/{plans['id']}", {"summary": "x" * 4001})
    assert bad.status_code == 400
    bad = send(client, "PATCH", f"/api/collection-groups/{plans['id']}", {"name": "Plans", "x": 1})
    assert bad.status_code == 422
    assert send(client, "PATCH", "/api/collection-groups/999", {"name": "A"}).status_code == 404

    r = send(client, "POST", f"/api/collection-groups/{old['id']}/remove")
    assert r.status_code == 200, r.text
    c = r.json()["collection"]
    assert [g["name"] for g in c["groups"]] == ["Plans"]
    assert [m["group_id"] for m in c["members"]] == [None, None]
    assert send(client, "POST", "/api/collection-groups/999/remove").status_code == 404

    r = send(client, "PATCH", f"/api/collections/{cid}/summary", {"summary": "Sauna build"})
    assert r.status_code == 200, r.text
    assert r.json()["collection"]["summary"] == "Sauna build"
    assert client.get(f"/api/collections/{cid}").json()["summary"] == "Sauna build"
    row = client.get("/api/collections").json()[0]
    assert row["summary"] == "Sauna build" and [g["name"] for g in row["groups"]] == ["Plans"]


def test_collection_attention(client, app, api_files, fake_archive):
    """Per member, in one request: its open tray items (with their urgency) and whether
    it is still in the inbox. Members with neither are left out."""
    fake_archive.add("##. Organize/scan.pdf", drive_id="f3")
    fake_archive.add("##. Organize/Sub/deep.pdf", drive_id="f4")
    fake_archive.add("10. Financial/quiet.pdf", drive_id="f5")
    app.scan()
    cid = send(client, "POST", "/api/collections", {"name": "Estate"}).json()["id"]
    send(
        client,
        "POST",
        f"/api/collections/{cid}/members",
        {"drive_ids": ["f1", "f2", "f3", "f4", "f5"]},
    )
    due = (date.today() - timedelta(days=2)).isoformat()
    item = send(
        client,
        "POST",
        "/api/items",
        {"tray": "to-pay", "drive_ids": ["f1"], "fields": {"due_date": due}},
    ).json()
    done = send(client, "POST", "/api/items", {"tray": "to-pay", "drive_ids": ["f2"]}).json()
    send(client, "POST", f"/api/items/{done['id']}/done", {"fields": {}})

    r = client.get(f"/api/collections/{cid}/attention")
    assert r.status_code == 200, r.text
    rows = {row["drive_id"]: row for row in r.json()}
    assert set(rows) == {"f1", "f3"}  # f2: only a done item; f4: in a subfolder; f5: quiet
    assert rows["f1"]["in_inbox"] is False
    [a] = rows["f1"]["items"]
    got = (a["item"]["id"], a["item"]["tray_name"], a["level"])
    assert got == (item["id"], "To pay", "overdue")
    assert rows["f3"] == {"drive_id": "f3", "in_inbox": True, "items": []}
    assert client.get("/api/collections/999/attention").status_code == 404
