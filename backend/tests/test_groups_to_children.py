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


def kids(svc, parent_id):
    return [c for c in svc.list(None) if c.parent_id == parent_id]


def members(c):
    return sorted(m.drive_id for m in c.members)


def by_name(svc, name):
    return next(c for c in svc.list(None) if c.name == name)


def test_groups_become_children_with_their_members_and_summary(svc, docs):
    legal = svc.create("Legal")
    mine = svc.create_group(legal.id, "Michiel")
    svc.set_group_summary(mine.id, "Mine")
    wills = svc.create_group(legal.id, "Wills", parent_id=mine.id)
    together = svc.create_group(legal.id, "Together")
    svc.add_members(legal.id, ["d1", "d2", "d3", "d4"])
    svc.set_member_group(legal.id, ["d1"], mine.id)
    svc.set_member_group(legal.id, ["d2"], wills.id)
    svc.set_member_group(legal.id, ["d3"], together.id)

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
    svc.create_group(legal.id, "Michiel")
    [done] = svc.convert_groups()
    assert (done.name, done.renamed) == ("Michiel (Legal)", True)
    assert [c.name for c in kids(svc, legal.id)] == ["Michiel (Legal)"]

    house = svc.create("House")
    svc.create("Michiel (House)")
    svc.create_group(house.id, "Michiel")
    [again] = svc.convert_groups()
    assert again.name == "Michiel (House) 2"


def test_children_of_a_closed_collection_are_closed(svc, docs):
    legal = svc.create("Legal")
    svc.create_group(legal.id, "Michiel")
    svc.close(legal.id)
    svc.convert_groups()
    assert by_name(svc, "Michiel").state == "closed"


def test_order_follows_the_groups_after_existing_children(svc, docs):
    legal = svc.create("Legal")
    svc.create("Car", parent_id=legal.id)
    b = svc.create_group(legal.id, "B")
    svc.create_group(legal.id, "A")
    assert b.position == 0
    svc.convert_groups()
    assert [c.name for c in kids(svc, legal.id)] == ["Car", "B", "A"]


def test_important_keeps_its_groups_and_a_second_run_does_nothing(svc, docs):
    important = svc.builtin("important")
    svc.add_members(important.id, ["d5"])
    svc.set_group_path(important.id, ["d5"], ["Houses", "Hillside"])
    before = [(g.parent_id is None, g.name) for g in svc.get(important.id).groups]
    legal = svc.create("Legal")
    svc.create_group(legal.id, "Michiel")
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
    y = app.collections.create_group(c.id, "2025")
    q = app.collections.create_group(c.id, "Q1", parent_id=y.id)
    app.collections.set_member_group(c.id, ["id-b"], y.id)
    app.collections.set_member_group(c.id, ["id-c"], q.id)
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
