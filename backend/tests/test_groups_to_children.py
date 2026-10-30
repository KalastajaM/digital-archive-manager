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
