import pytest
from sqlalchemy import func, insert, select, update

from dam.collections.publishers import PublisherRegistry
from dam.collections.service import CollectionService
from dam.config import SpecialFolders
from dam.db.tables import collection_members, collections, files
from dam.errors import InvalidRequest, NotFound
from dam.index.repo import PARKED, FileRepo
from dam.ops.model import Plan


@pytest.fixture
def registry():
    class Fake:
        id = "ongoing"

        def plan(self, cols):
            return Plan(ops=[], origin="workflow")

    reg = PublisherRegistry()
    reg.register(Fake())
    return reg


@pytest.fixture
def svc(engine, registry):
    return CollectionService(engine, FileRepo(engine, "00. Inbox"), registry, SpecialFolders())


def add(engine, drive_id, path, *, is_dir=False, missing=False, link=False, parked=False):
    if parked:
        path, missing = f"{PARKED}{drive_id}", True
    with engine.begin() as conn:
        conn.execute(
            insert(files).values(
                drive_id=drive_id,
                path=path,
                path_nfc=path,
                name=path.rsplit("/", 1)[-1],
                is_dir=is_dir,
                is_link=link,
                missing=missing,
                parked_at=1.0 if parked else None,
            )
        )


@pytest.fixture
def tree(engine):
    add(engine, "d-sauna", "Home/Sauna", is_dir=True)
    add(engine, "f1", "Home/Sauna/plan.pdf")
    add(engine, "f2", "Home/Sauna/deep/er/quote.pdf")
    add(engine, "sub", "Home/Sauna/deep", is_dir=True)
    add(engine, "gone", "Home/Sauna/gone.pdf", missing=True)
    add(engine, "park", "x", parked=True)
    add(engine, "lnk", "Home/Sauna/link", link=True)
    add(engine, "d-sib", "Home/Sauna 2", is_dir=True)
    add(engine, "f-sib", "Home/Sauna 2/other.pdf")
    add(engine, "solo", "Elsewhere/solo.pdf")


def test_create_trims_and_roundtrips(svc):
    c = svc.create("  Sauna conversion ")
    assert (c.name, c.state, c.publish, c.members, c.ongoing_rel) == (
        "Sauna conversion",
        "open",
        {"ongoing": True},
        [],
        None,
    )
    assert svc.get(c.id).name == "Sauna conversion"
    assert svc.by_name("sauna CONVERSION").id == c.id
    assert svc.by_name("nope") is None


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "a/b",
        "a\0b",
        "a\nb",
        "a\tb",
        ".hidden",
        ".",
        "..",
        "x" * 121,
        "a\\b",
        "a\u202eb",
        "a\u200bb",
        "name.",
        "name. ",
        "a\u00a0\u200b",
    ],
)
def test_bad_names(svc, bad):
    with pytest.raises(InvalidRequest):
        svc.create(bad)


def test_name_length_boundary(svc):
    assert len(svc.create("x" * 120).name) == 120


def test_unique_fold_case_and_unicode(svc):
    svc.create("Café")
    with pytest.raises(InvalidRequest, match="already exists"):
        svc.create("CAFÉ")  # NFD + upper
    svc.create("Cafe")  # different letters


def test_get_unknown(svc):
    with pytest.raises(NotFound):
        svc.get(99)


def test_rename_keeps_ongoing_rel_and_checks_unique(engine, svc):
    a = svc.create("A")
    svc.create("B")
    with engine.begin() as conn:
        conn.execute(update(collections).where(collections.c.id == a.id).values(ongoing_rel="A"))
    r = svc.set_name(a.id, "a renamed")
    assert (r.name, r.ongoing_rel) == ("a renamed", "A")
    with pytest.raises(InvalidRequest):
        svc.set_name(a.id, "b")
    assert svc.set_name(a.id, "A RENAMED").name == "A RENAMED"  # own fold is fine
    with pytest.raises(NotFound):
        svc.set_name(99, "z")


def test_get_or_create(svc):
    a = svc.get_or_create("Trip")
    assert svc.get_or_create(" trip ").id == a.id
    assert len(svc.list()) == 1


def test_list_by_state_sorted(svc):
    b = svc.create("b")
    svc.create("A")
    svc.close(b.id)
    assert [c.name for c in svc.list()] == ["A"]
    assert [c.name for c in svc.list("closed")] == ["b"]
    assert [c.name for c in svc.list(None)] == ["b", "A"]  # in the order they were made
    with pytest.raises(InvalidRequest):
        svc.list("bogus")


def test_close_reopen(svc):
    c = svc.create("C")
    closed = svc.close(c.id)
    assert closed.state == "closed" and closed.closed_at is not None
    first = closed.closed_at
    assert svc.close(c.id).closed_at == first  # idempotent
    open_again = svc.reopen(c.id)
    assert open_again.state == "open" and open_again.closed_at is None


def test_members_info_and_missing(engine, svc, tree):
    c = svc.create("C")
    svc.add_members(c.id, ["f1", "d-sauna", "gone", "solo"])
    by = {m.drive_id: m for m in svc.get(c.id).members}
    assert (by["f1"].path, by["f1"].is_dir, by["f1"].missing) == (
        "Home/Sauna/plan.pdf",
        False,
        False,
    )
    assert by["d-sauna"].is_dir and not by["d-sauna"].missing
    assert by["gone"].missing and by["gone"].path == "Home/Sauna/gone.pdf"
    # a member whose row disappears or gets parked later
    with engine.begin() as conn:
        conn.execute(
            update(files)
            .where(files.c.drive_id == "solo")
            .values(path=f"{PARKED}solo", path_nfc=f"{PARKED}solo", missing=True, parked_at=1.0)
        )
        conn.execute(files.delete().where(files.c.drive_id == "f1"))
    by = {m.drive_id: m for m in svc.get(c.id).members}
    assert (by["solo"].path, by["solo"].missing) == (None, True)
    assert (by["f1"].path, by["f1"].missing) == (None, True)


def test_members_say_which_are_links(svc, tree):
    """Trash on a link member moves the link, never its target: the UI says so."""
    c = svc.create("C")
    svc.add_members(c.id, ["lnk", "f1"])
    by = {m.drive_id: m for m in svc.get(c.id).members}
    assert by["lnk"].is_link and not by["f1"].is_link


def test_add_members_noop_unknown_and_atomic(engine, svc, tree):
    c = svc.create("C")
    svc.add_members(c.id, ["f1"], batch_id="b1")
    svc.add_members(c.id, ["f1", "f1", "f2"], batch_id="b2")
    assert [m.drive_id for m in svc.get(c.id).members] == ["f1", "f2"]
    with engine.connect() as conn:
        batches = dict(
            conn.execute(
                select(collection_members.c.drive_id, collection_members.c.created_by_batch)
            ).all()
        )
    assert batches == {"f1": "b1", "f2": "b2"}  # existing membership untouched
    with pytest.raises(NotFound):
        svc.add_members(c.id, ["solo", "nope"])
    with pytest.raises(NotFound):
        svc.add_members(c.id, ["park"])
    assert len(svc.get(c.id).members) == 2  # nothing partial
    with pytest.raises(NotFound):
        svc.add_members(99, ["f1"])


def test_remove_member(svc, tree):
    c = svc.create("C")
    svc.add_members(c.id, ["f1", "f2"])
    assert [m.drive_id for m in svc.remove_member(c.id, "f1").members] == ["f2"]
    svc.remove_member(c.id, "f1")  # not a member: no-op


def test_file_in_several_collections(svc, tree):
    a, b = svc.create("A"), svc.create("B")
    svc.add_members(a.id, ["f1"])
    svc.add_members(b.id, ["f1"])
    assert [c.name for c in svc.for_file("f1")] == ["A", "B"]


def test_expand_folder_member(engine, svc, tree):
    c = svc.create("C")
    svc.add_members(c.id, ["d-sauna", "solo", "f1", "gone"])
    paths = [r.path for r in svc.expand(c.id)]
    # nested files included; missing, folders, links and the "Sauna 2" sibling are not;
    # f1 is both direct and via the folder: once
    assert paths == [
        "Elsewhere/solo.pdf",
        "Home/Sauna/deep/er/quote.pdf",
        "Home/Sauna/plan.pdf",
    ]


def test_expand_sees_files_added_later_and_follows_moves(engine, svc, tree):
    c = svc.create("C")
    svc.add_members(c.id, ["d-sauna"])
    assert len(svc.expand(c.id)) == 2
    add(engine, "f3", "Home/Sauna/new.pdf")
    assert "Home/Sauna/new.pdf" in [r.path for r in svc.expand(c.id)]
    with engine.begin() as conn:  # folder renamed: the member follows it
        for did, p in [("d-sauna", "Home/Spa"), ("f1", "Home/Spa/plan.pdf")]:
            conn.execute(update(files).where(files.c.drive_id == did).values(path=p, path_nfc=p))
    assert [r.path for r in svc.expand(c.id)] == ["Home/Spa/plan.pdf"]


def test_expand_special_characters_in_folder_name(engine, svc):
    add(engine, "d", "100%_done", is_dir=True)
    add(engine, "in", "100%_done/a.pdf")
    add(engine, "out", "100xxdone/b.pdf")
    c = svc.create("C")
    svc.add_members(c.id, ["d"])
    assert [r.path for r in svc.expand(c.id)] == ["100%_done/a.pdf"]


def test_expand_skips_missing_folder_and_parked_file_member(engine, svc, tree):
    c = svc.create("C")
    svc.add_members(c.id, ["d-sauna", "solo"])
    with engine.begin() as conn:
        conn.execute(update(files).where(files.c.drive_id == "d-sauna").values(missing=True))
        conn.execute(
            update(files)
            .where(files.c.drive_id == "solo")
            .values(path=f"{PARKED}solo", path_nfc=f"{PARKED}solo", missing=True, parked_at=1.0)
        )
    assert svc.expand(c.id) == []
    with pytest.raises(NotFound):
        svc.expand(99)


def test_for_file_via_folder_member(svc, tree):
    open_c, closed_c, other = svc.create("Zed"), svc.create("alpha"), svc.create("Other")
    svc.add_members(open_c.id, ["d-sauna"])
    svc.add_members(closed_c.id, ["f2"])
    svc.add_members(other.id, ["d-sib"])
    svc.close(closed_c.id)
    assert [c.name for c in svc.for_file("f2")] == ["Zed", "alpha"]  # nested, closed counts
    assert [c.name for c in svc.for_file("f-sib")] == ["Other"]  # not the "Sauna" prefix
    assert svc.for_file("solo") == []
    assert svc.for_file("nope") == []
    assert [c.name for c in svc.for_file("d-sauna")] == ["Zed"]  # a folder member itself


def test_for_file_missing_file_only_direct(engine, svc, tree):
    c, d = svc.create("Direct"), svc.create("Folder")
    svc.add_members(c.id, ["gone"])
    svc.add_members(d.id, ["d-sauna"])
    assert [x.name for x in svc.for_file("gone")] == ["Direct"]


def test_set_publish(svc):
    c = svc.create("C")
    assert svc.set_publish(c.id, "ongoing", False).publish == {"ongoing": False}
    assert svc.set_publish(c.id, "ongoing", True).publish["ongoing"] is True
    with pytest.raises(NotFound):
        svc.set_publish(c.id, "nope", True)
    with pytest.raises(NotFound):
        svc.set_publish(99, "ongoing", True)


def test_remove_created_by_only_members(engine, svc, tree):
    a, b = svc.create("A"), svc.create("B")
    svc.add_members(a.id, ["f1", "f2"], batch_id="x")
    svc.add_members(b.id, ["f1"], batch_id="y")
    svc.add_members(b.id, ["solo"])
    assert svc.remove_created_by("x") == (2, 0)
    assert svc.remove_created_by("x") == (0, 0)
    assert [m.drive_id for m in svc.get(a.id).members] == []
    assert sorted(m.drive_id for m in svc.get(b.id).members) == ["f1", "solo"]
    with engine.connect() as conn:  # collections survive, even emptied ones
        ordinary = select(func.count()).select_from(collections).where(collections.c.kind.is_(None))
        assert conn.execute(ordinary).scalar_one() == 2


def test_publisher_registry(registry):
    assert [p.id for p in registry.all()] == ["ongoing"]
    assert registry.get("ongoing").plan([]).ops == []
    with pytest.raises(NotFound):
        registry.get("export")


TRASH = "##. To Delete"


def move(engine, drive_id, path):
    with engine.begin() as conn:
        conn.execute(
            update(files).where(files.c.drive_id == drive_id).values(path=path, path_nfc=path)
        )


def test_expand_excludes_quarantined_direct_and_nested(engine, svc, tree):
    c = svc.create("C")
    svc.add_members(c.id, ["d-sauna", "solo", "f-sib"])
    move(engine, "solo", f"{TRASH}/solo.pdf")  # direct member
    move(engine, "f2", f"{TRASH}/quote.pdf")  # file under a folder member
    assert [r.path for r in svc.expand(c.id)] == ["Home/Sauna 2/other.pdf", "Home/Sauna/plan.pdf"]
    by = {m.drive_id: m for m in svc.get(c.id).members}
    assert by["solo"].quarantined and not by["solo"].missing
    assert not by["f-sib"].quarantined and not by["d-sauna"].quarantined


def test_expand_excludes_quarantined_folder_member(engine, svc, tree):
    c = svc.create("C")
    svc.add_members(c.id, ["d-sauna", "f-sib"])
    move(engine, "d-sauna", f"{TRASH}/Sauna")
    move(engine, "f1", f"{TRASH}/Sauna/plan.pdf")
    move(engine, "f2", f"{TRASH}/Sauna/deep/er/quote.pdf")
    assert [r.path for r in svc.expand(c.id)] == ["Home/Sauna 2/other.pdf"]
    assert {m.drive_id: m.quarantined for m in svc.get(c.id).members}["d-sauna"]
    # still listed for the file, so the UI can show it
    assert [x.name for x in svc.for_file("f1")] == ["C"]


def test_quarantine_boundary(engine, svc):
    add(engine, "a", f"{TRASH} old/a.pdf")
    c = svc.create("C")
    svc.add_members(c.id, ["a"])
    assert not svc.get(c.id).members[0].quarantined
    assert len(svc.expand(c.id)) == 1


def test_nfd_paths(engine, svc):
    nfd = "Cafe\u0301"
    nfc_ = "Caf\u00e9"
    with engine.begin() as conn:
        for did, path, is_dir in [("d", nfd, True), ("f", f"{nfd}/a.pdf", False)]:
            conn.execute(
                insert(files).values(
                    drive_id=did,
                    path=path,
                    path_nfc=path.replace(nfd, nfc_),
                    name=path,
                    is_dir=is_dir,
                    missing=False,
                )
            )
    c = svc.create("C")
    svc.add_members(c.id, ["d"])
    assert [r.drive_id for r in svc.expand(c.id)] == ["f"]
    assert [x.name for x in svc.for_file("f")] == ["C"]


def test_name_nfd_length_counts_composed(svc):
    name = "e\u0301" * 120  # 240 code points, 120 once composed
    assert len(name) > 120
    assert len(svc.create(name).name) == 120


def test_unknown_collection_not_found(svc):
    with pytest.raises(NotFound):
        svc.remove_member(99, "f1")
    with pytest.raises(NotFound):
        svc.set_publish(99, "ongoing", True)


def test_add_members_unhashable_and_non_str(svc):
    c = svc.create("C")
    with pytest.raises(InvalidRequest):
        svc.add_members(c.id, [["x"]])
    with pytest.raises(InvalidRequest):
        svc.add_members(c.id, [""])


def test_add_members_rolls_back(engine, svc, tree, monkeypatch):
    from dam.collections import service as mod

    c = svc.create("C")
    real = mod.sqlite_insert
    calls = []

    def flaky(table):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("boom")
        return real(table)

    monkeypatch.setattr(mod, "sqlite_insert", flaky)
    with pytest.raises(RuntimeError):
        svc.add_members(c.id, ["f1", "f2"])
    monkeypatch.undo()
    assert svc.get(c.id).members == []
