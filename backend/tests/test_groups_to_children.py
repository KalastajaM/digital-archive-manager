"""Groups of ordinary collections become child collections (Important keeps its groups)."""

import pytest
from sqlalchemy import insert

from dam.collections.publishers import PublisherRegistry
from dam.collections.service import CollectionService
from dam.config import SpecialFolders
from dam.db.tables import files
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
    return CollectionService(engine, FileRepo(engine, "00. Inbox"), reg, SpecialFolders())


@pytest.fixture
def docs(engine):
    ids = [f"d{i}" for i in range(1, 6)]
    with engine.begin() as conn:
        for d in ids:
            conn.execute(
                insert(files).values(
                    drive_id=d, path=f"Home/{d}.pdf", path_nfc=f"Home/{d}.pdf", name=f"{d}.pdf"
                )
            )
    return ids


def old_group(engine, collection_id, name, parent=None, summary=""):
    """A group as this version found it (only Important may make new ones)."""
    from sqlalchemy import func, select

    from dam.core.text import fold_name
    from dam.db.tables import collection_groups as g

    with engine.begin() as conn:
        position = conn.execute(
            select(func.count()).where(
                g.c.collection_id == collection_id,
                g.c.parent_id.is_(parent) if parent is None else g.c.parent_id == parent,
            )
        ).scalar_one()
        return conn.execute(
            insert(g).values(
                collection_id=collection_id,
                parent_id=parent,
                name=name,
                name_fold=fold_name(name),
                position=position,
                summary=summary,
            )
        ).inserted_primary_key[0]


def in_group(engine, collection_id, drive_ids, group_id):
    from sqlalchemy import update

    from dam.db.tables import collection_members as m

    with engine.begin() as conn:
        conn.execute(
            update(m)
            .where(m.c.collection_id == collection_id, m.c.drive_id.in_(drive_ids))
            .values(group_id=group_id)
        )


def kids(svc, parent_id):
    return [c for c in svc.list(None) if c.parent_id == parent_id]


def members(c):
    return sorted(m.drive_id for m in c.members)


def by_name(svc, name):
    return next(c for c in svc.list(None) if c.name == name)


def test_groups_become_children_with_their_members_and_summary(svc, docs):
    legal = svc.create("Legal")
    mine = old_group(svc.engine, legal.id, "Michiel", summary="Mine")
    wills = old_group(svc.engine, legal.id, "Wills", parent=mine)
    together = old_group(svc.engine, legal.id, "Together")
    svc.add_members(legal.id, ["d1", "d2", "d3", "d4"])
    in_group(svc.engine, legal.id, ["d1"], mine)
    in_group(svc.engine, legal.id, ["d2"], wills)
    in_group(svc.engine, legal.id, ["d3"], together)

    done = svc.convert_groups()

    legal = svc.get(legal.id)
    assert members(legal) == ["d4"] and legal.groups == []
    assert [c.name for c in kids(svc, legal.id)] == ["Michiel", "Together"]
    michiel = by_name(svc, "Michiel")
    assert michiel.summary == "Mine" and members(michiel) == ["d1"]
    assert members(by_name(svc, "Together")) == ["d3"]
    assert [c.name for c in kids(svc, michiel.id)] == ["Wills"]
    assert members(by_name(svc, "Wills")) == ["d2"]
    assert sorted((d.name, d.renamed) for d in done) == [
        ("Michiel", False),
        ("Together", False),
        ("Wills", False),
    ]


def test_a_taken_name_gets_the_parent_in_brackets(svc, docs):
    svc.create("Michiel")
    legal = svc.create("Legal")
    old_group(svc.engine, legal.id, "Michiel")
    [done] = svc.convert_groups()
    assert (done.name, done.renamed) == ("Michiel (Legal)", True)
    assert [c.name for c in kids(svc, legal.id)] == ["Michiel (Legal)"]

    house = svc.create("House")
    svc.create("Michiel (House)")
    old_group(svc.engine, house.id, "Michiel")
    [again] = svc.convert_groups()
    assert again.name == "Michiel (House) 2"


def test_children_of_a_closed_collection_are_closed(svc, docs):
    legal = svc.create("Legal")
    old_group(svc.engine, legal.id, "Michiel")
    svc.close(legal.id)
    svc.convert_groups()
    assert by_name(svc, "Michiel").state == "closed"


def test_order_follows_the_groups_after_existing_children(svc, docs):
    legal = svc.create("Legal")
    svc.create("Car", parent_id=legal.id)
    old_group(svc.engine, legal.id, "B")
    old_group(svc.engine, legal.id, "A")
    svc.convert_groups()
    assert [c.name for c in kids(svc, legal.id)] == ["Car", "B", "A"]


def test_important_keeps_its_groups_and_a_second_run_does_nothing(svc, docs):
    important = svc.builtin("important")
    svc.add_members(important.id, ["d5"])
    svc.set_group_path(important.id, ["d5"], ["Houses", "Hillside"])
    before = [(g.parent_id is None, g.name) for g in svc.get(important.id).groups]
    legal = svc.create("Legal")
    old_group(svc.engine, legal.id, "Michiel")
    assert svc.ordinary_groups() == [legal.id]

    assert len(svc.convert_groups()) == 1
    assert [(g.parent_id is None, g.name) for g in svc.get(important.id).groups] == before
    assert svc.ordinary_groups() == []
    assert svc.convert_groups() == []


# --- on open: nothing moves in ##. Ongoing ---------------------------------------------

ONG = "##. Ongoing"
BANKS = "10. Financial/Banks"


def grouped(app, fake_archive):
    """Sauna (published): a.pdf ungrouped, b.pdf in "2025", c.pdf in "2025/Q1"."""
    for x in "abc":
        fake_archive.add(f"{BANKS}/{x}.pdf", drive_id=f"id-{x}")
    app.scan()
    c = app.collections.create("Sauna")
    app.collections.add_members(c.id, ["id-a", "id-b", "id-c"])
    y = old_group(app.engine, c.id, "2025")
    q = old_group(app.engine, c.id, "Q1", parent=y)
    in_group(app.engine, c.id, ["id-b"], y)
    in_group(app.engine, c.id, ["id-c"], q)
    return app.collections.get(c.id)


def ongoing_tree(fake_archive) -> list[tuple[str, str]]:
    """(path under ##. Ongoing, "dir" or the link's target) for everything there."""
    import os

    root = fake_archive.root / ONG
    out = []
    for here, dirs, names in os.walk(root):
        for n in dirs + names:
            p = os.path.join(here, n)
            rel = os.path.relpath(p, root)
            out.append((rel, os.readlink(p) if os.path.islink(p) else "dir"))
    return sorted(out)


def batch_count(app) -> int:
    from sqlalchemy import func, select

    from dam.db.tables import operations

    with app.engine.connect() as conn:
        return conn.execute(select(func.count(func.distinct(operations.c.batch_id)))).scalar_one()


def test_converting_moves_nothing_in_ongoing(app, fake_archive):
    grouped(app, fake_archive)
    app.sync_publishers()
    before, batches = ongoing_tree(fake_archive), batch_count(app)
    assert ("Sauna/2025/Q1/c.pdf", str(fake_archive.root.resolve() / BANKS / "c.pdf")) in before

    done = app.convert_collection_groups()

    assert [d.name for d in done] == ["2025", "Q1"]
    app.sync_publishers()
    assert ongoing_tree(fake_archive) == before
    assert batch_count(app) == batches  # no sync batch: nothing to do


def test_a_renamed_group_is_named_and_its_folder_follows(app, fake_archive):
    from sqlalchemy import select

    from dam.db.tables import operations

    app.collections.create("2025")
    grouped(app, fake_archive)
    app.sync_publishers()
    [first, _] = app.convert_collection_groups()
    assert first.name == "2025 (Sauna)"
    tree = dict(ongoing_tree(fake_archive))
    assert "Sauna/2025 (Sauna)/b.pdf" in tree and "Sauna/2025 (Sauna)/Q1/c.pdf" in tree
    assert "Sauna/2025" not in tree
    with app.engine.connect() as conn:
        labels = {r[0] for r in conn.execute(select(operations.c.label)) if r[0]}
    assert any("2025 is now 2025 (Sauna)" in label for label in labels)


def test_conversion_takes_a_snapshot_first(app, fake_archive):
    from dam.snapshots import BEFORE_GROUPS, list_snapshots

    assert app.convert_collection_groups() == []
    assert list_snapshots(app.app_paths) == []
    grouped(app, fake_archive)
    app.convert_collection_groups()
    assert [s.kind for s in list_snapshots(app.app_paths)] == [BEFORE_GROUPS]


def test_conversion_without_the_archive_still_hands_over_the_records(app, fake_archive):
    grouped(app, fake_archive)
    app.sync_publishers()
    before, batches = ongoing_tree(fake_archive), batch_count(app)
    away = fake_archive.root.with_name(fake_archive.root.name + "-away")
    fake_archive.root.rename(away)
    try:
        app.convert_collection_groups()
    finally:
        away.rename(fake_archive.root)
    app.sync_publishers()
    assert ongoing_tree(fake_archive) == before
    assert batch_count(app) == batches


def test_an_unpublished_collection_is_converted_and_nothing_is_published(app, fake_archive):
    c = grouped(app, fake_archive)
    app.collections.set_publish(c.id, "ongoing", False)
    app.sync_publishers()
    assert len(app.convert_collection_groups()) == 2
    app.sync_publishers()
    assert ongoing_tree(fake_archive) == []


def test_only_important_takes_groups(svc, docs):
    from dam.errors import InvalidRequest

    legal = svc.create("Legal")
    with pytest.raises(InvalidRequest, match="Only Important has groups"):
        svc.create_group(legal.id, "Michiel")
    with pytest.raises(InvalidRequest):
        svc.create_group(svc.builtin("starred").id, "x")
    assert svc.create_group(svc.builtin("important").id, "Houses").name == "Houses"


def test_the_group_route_refuses_an_ordinary_collection(app):
    from fastapi.testclient import TestClient

    from dam.api import create_api

    base = "http://127.0.0.1:8765"
    c = app.collections.create("Legal")
    with TestClient(create_api(app), base_url=base) as client:
        r = client.post(
            f"/api/collections/{c.id}/groups",
            json={"name": "Michiel", "parent_id": None},
            headers={"Origin": base},
        )
    assert r.status_code == 400 and "Only Important has groups" in r.text


# --- moving a file between collections ---------------------------------------------------


def added_at(svc, collection_id, drive_id):
    from sqlalchemy import select

    from dam.db.tables import collection_members as m

    with svc.engine.connect() as conn:
        return conn.execute(
            select(m.c.added).where(m.c.collection_id == collection_id, m.c.drive_id == drive_id)
        ).scalar_one()


def test_move_members_between_siblings(svc, docs):
    legal = svc.create("Legal")
    mine = svc.create("Michiel", parent_id=legal.id)
    both = svc.create("Together", parent_id=legal.id)
    svc.add_members(mine.id, ["d1", "d2"])
    added = added_at(svc, mine.id, "d1")
    target = svc.move_members(mine.id, both.id, ["d1", "d9"])  # d9 is not in Michiel: ignored
    assert target.id == both.id and members(target) == ["d1"]
    assert members(svc.get(mine.id)) == ["d2"]
    assert added_at(svc, both.id, "d1") == added  # when it was first added stays


def test_move_to_a_closed_collection_is_refused(svc, docs):
    from dam.errors import InvalidRequest

    a = svc.create("A")
    b = svc.create("B")
    svc.add_members(a.id, ["d1"])
    svc.close(b.id)
    with pytest.raises(InvalidRequest, match="closed"):
        svc.move_members(a.id, b.id, ["d1"])
    assert members(svc.get(a.id)) == ["d1"]


def test_move_route_syncs_and_moves_the_link(app, fake_archive):
    import os

    from fastapi.testclient import TestClient

    from dam.api import create_api

    fake_archive.add(f"{BANKS}/a.pdf", drive_id="id-a")
    fake_archive.add(f"{BANKS}/b.pdf", drive_id="id-b")
    app.scan()
    legal = app.collections.create("Legal")
    mine = app.collections.create("Michiel", parent_id=legal.id)
    both = app.collections.create("Together", parent_id=legal.id)
    app.collections.add_members(mine.id, ["id-a", "id-b"])
    app.collections.add_members(both.id, ["id-b"])
    app.sync_publishers()
    base = "http://127.0.0.1:8765"
    with TestClient(create_api(app), base_url=base) as client:
        r = client.post(
            f"/api/collections/{mine.id}/members/move",
            json={"to": both.id, "drive_ids": ["id-a"]},
            headers={"Origin": base},
        )
    assert r.status_code == 200, r.text
    assert r.json()["collection"]["id"] == both.id
    root = fake_archive.root / ONG / "Legal"
    assert os.path.islink(root / "Together" / "a.pdf")
    assert not os.path.exists(root / "Michiel" / "a.pdf")


def test_a_failed_hand_over_undoes_the_conversion_and_the_next_open_tries_again(
    app, fake_archive, monkeypatch
):
    grouped(app, fake_archive)
    app.sync_publishers()
    before = ongoing_tree(fake_archive)

    def broken(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(app.ongoing, "reown", broken)
    with pytest.raises(RuntimeError):
        app.convert_collection_groups()
    assert app.collections.ordinary_groups() != []  # nothing was converted
    assert [c.name for c in app.collections.list(None)] == ["Sauna"]

    monkeypatch.undo()
    assert len(app.convert_collection_groups()) == 2
    app.sync_publishers()
    assert ongoing_tree(fake_archive) == before


def test_moving_into_the_same_collection_is_refused(svc, docs):
    from dam.errors import InvalidRequest

    a = svc.create("A")
    svc.add_members(a.id, ["d1", "d2"])
    with pytest.raises(InvalidRequest):
        svc.move_members(a.id, a.id, ["d1"])
    assert members(svc.get(a.id)) == ["d1", "d2"]
