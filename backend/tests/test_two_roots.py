"""The two-root publisher (stars, Task 2): ★ members as links at the top of
``##. Ongoing``; ! Important mirrored at the root of ``##. Important`` (members at the
top, groups as subfolders). The same identity, no-adoption, ``_2``, left-alone,
empty-listing and failing-sync rules as for the collections in ``##. Ongoing``; the
deletion exception (app-owned links and app-owned empty folders, identity-checked)
holds under exactly those two roots and nowhere else."""

import os
from pathlib import Path

import pytest
from sqlalchemy import select

from dam.collections.ongoing import _REPLACED, NOT_MANAGED
from dam.config import Settings
from dam.core.fs import readlink
from dam.core.paths import ArchivePaths
from dam.db.tables import ongoing_entries, operations
from dam.ops import primitives
from dam.ops.guards import validate
from dam.ops.model import GuardError, Op, OpFailed, OpKind, Plan
from fsswap import recreate_dir

HOLDS_1 = "contains 1 item not created by the app, so it was left as it is."

ONG = "##. Ongoing"
IMP = "##. Important"
BANKS = "10. Financial/Banks"


# --- helpers -----------------------------------------------------------------------


def listing(path: Path) -> list[str]:
    return sorted(os.listdir(path))


def points_at(link: Path, fake_archive, rel: str) -> bool:
    return link.is_symlink() and readlink(link) == str(fake_archive.root.resolve() / rel)


def journal(app, batch_id: str | None = None):
    q = select(operations).order_by(operations.c.id)
    if batch_id is not None:
        q = q.where(operations.c.batch_id == batch_id)
    with app.engine.connect() as conn:
        return conn.execute(q).all()


def batches(app) -> list[str]:
    seen: list[str] = []
    for row in journal(app):
        if row.batch_id not in seen:
            seen.append(row.batch_id)
    return seen


def kinds(app, batch_id):
    removals = ("unlink_symlink", "remove_empty_dir")
    return [(r.kind, r.src if r.kind in removals else r.dst) for r in journal(app, batch_id)]


def records(app):
    with app.engine.connect() as conn:
        return conn.execute(select(ongoing_entries).order_by(ongoing_entries.c.rel)).all()


def important(app):
    return app.collections.builtin("important")


def starred(app):
    return app.collections.builtin("starred")


@pytest.fixture
def files(app, fake_archive):
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="id-a")
    fake_archive.add(f"{BANKS}/b.pdf", drive_id="id-b")
    fake_archive.add(f"{BANKS}/c.pdf", drive_id="id-c")
    (fake_archive.root / "Home" / "X").mkdir(parents=True)
    import xattr

    from dam.index.driveid import DRIVE_ID_XATTR

    xattr.setxattr(fake_archive.root / "Home" / "X", DRIVE_ID_XATTR, b"d-x")
    app.scan()


# --- ★ at the top of ##. Ongoing ------------------------------------------------------


def test_star_publishes_a_link_at_the_ongoing_top_level(app, fake_archive, files):
    app.marks.star(["id-a"])
    ongoing = fake_archive.root / ONG
    assert listing(ongoing) == ["a.pdf"]
    assert points_at(ongoing / "a.pdf", fake_archive, f"{BANKS}/a.pdf")
    rec = records(app)
    assert [(r.collection_id, r.rel, r.kind) for r in rec] == [
        (starred(app).id, f"{ONG}/a.pdf", "link")
    ]
    assert kinds(app, batches(app)[-1]) == [("symlink", f"{ONG}/a.pdf")]
    # a quiet sync changes nothing
    before = len(journal(app))
    assert app.ongoing.sync().batch is None
    assert len(journal(app)) == before
    app.marks.unstar(["id-a"])
    assert listing(ongoing) == []
    assert records(app) == []
    assert kinds(app, batches(app)[-1]) == [("unlink_symlink", f"{ONG}/a.pdf")]
    assert (fake_archive.root / BANKS / "a.pdf").exists()


def test_star_folder_member_and_a_file_in_a_project_too(app, fake_archive, files):
    c = app.collections.create("Sauna")
    app.collections.add_members(c.id, ["id-a", "id-b"])
    app.marks.star(["id-a", "d-x"])
    ongoing = fake_archive.root / ONG
    assert listing(ongoing) == ["Sauna", "X", "a.pdf"]
    assert points_at(ongoing / "X", fake_archive, "Home/X")
    assert points_at(ongoing / "a.pdf", fake_archive, f"{BANKS}/a.pdf")
    assert points_at(ongoing / "Sauna" / "a.pdf", fake_archive, f"{BANKS}/a.pdf")


def test_star_clashing_with_a_project_folder_gets_a_suffix_stably(app, fake_archive, files):
    c = app.collections.create("a.pdf")  # a project folder named like the file
    app.collections.add_members(c.id, ["id-b", "id-c"])
    ongoing = fake_archive.root / ONG
    assert listing(ongoing) == ["a.pdf"] and (ongoing / "a.pdf").is_dir()
    app.marks.star(["id-a"])
    assert listing(ongoing) == ["a.pdf", "a_2.pdf"]
    assert points_at(ongoing / "a_2.pdf", fake_archive, f"{BANKS}/a.pdf")
    before = len(journal(app))
    for _ in range(3):
        assert app.ongoing.sync().batch is None  # no churn
    assert len(journal(app)) == before
    assert listing(ongoing) == ["a.pdf", "a_2.pdf"]
    # the other way round: a project named like an existing star link
    app.collections.close(c.id)
    assert listing(ongoing) == ["a_2.pdf"]
    app.ongoing.sync()
    assert listing(ongoing) == ["a_2.pdf"]  # a variant of the wanted name is kept
    d = app.collections.create("a_2.pdf")
    app.collections.add_members(d.id, ["id-b", "id-c"])
    assert listing(ongoing) == ["a_2.pdf", "a_2_2.pdf"]
    assert (ongoing / "a_2_2.pdf").is_dir()


def test_star_link_replaced_by_the_user_is_foreign(app, fake_archive, files):
    app.marks.star(["id-a"])
    link = fake_archive.root / ONG / "a.pdf"
    os.unlink(link)
    os.symlink(fake_archive.root / BANKS / "b.pdf", link)
    result = app.ongoing.sync()
    assert result.batch is not None and result.batch.failed is None
    assert listing(fake_archive.root / ONG) == ["a.pdf", "a_2.pdf"]
    assert readlink(link) == str(fake_archive.root / BANKS / "b.pdf")
    s = starred(app)
    assert s.ongoing_status == f"{NOT_MANAGED}{ONG}/a.pdf{_REPLACED}"
    app.marks.unstar(["id-a"])
    assert listing(fake_archive.root / ONG) == ["a.pdf"]  # the user's link stays


def test_star_links_are_managed_entries_for_the_converter(app, fake_archive, files):
    app.marks.star(["id-a"])
    entries = app.convert.entries()
    assert [(e.rel, e.managed) for e in entries] == [(f"{ONG}/a.pdf", True)]


def test_a_star_on_a_file_inside_ongoing_is_not_linked(app, fake_archive):
    fake_archive.add(f"{ONG}/mine.pdf", drive_id="id-m")
    app.scan()
    app.marks.star(["id-m"])
    assert listing(fake_archive.root / ONG) == ["mine.pdf"]
    assert records(app) == []


# --- ! at the root of ##. Important -------------------------------------------------


def test_important_with_nested_groups_gives_nested_folders(app, fake_archive, files):
    app.marks.mark_important(["id-a"], "Houses/Hillside")
    app.marks.mark_important(["id-b"])
    root = fake_archive.root / IMP
    assert listing(root) == ["Houses", "b.pdf"]
    assert listing(root / "Houses") == ["Hillside"]
    assert listing(root / "Houses" / "Hillside") == ["a.pdf"]
    assert points_at(root / "Houses" / "Hillside" / "a.pdf", fake_archive, f"{BANKS}/a.pdf")
    assert points_at(root / "b.pdf", fake_archive, f"{BANKS}/b.pdf")
    imp = important(app)
    assert {(r.collection_id, r.rel, r.kind) for r in records(app)} == {
        (imp.id, f"{IMP}/Houses", "folder"),
        (imp.id, f"{IMP}/Houses/Hillside", "folder"),
        (imp.id, f"{IMP}/Houses/Hillside/a.pdf", "link"),
        (imp.id, f"{IMP}/b.pdf", "link"),
    }
    assert imp.ongoing_rel == IMP and imp.ongoing_status is None
    before = len(journal(app))
    assert app.ongoing.sync().batch is None
    assert len(journal(app)) == before
    # unmark everything and drop the groups: the app's own folders go, deepest
    # first, with their recorded identity; ##. Important itself never
    app.marks.unmark_important(["id-a", "id-b"])
    assert listing(root) == ["Houses"]
    for g in sorted(important(app).groups, key=lambda g: g.parent_id or 0, reverse=True):
        app.collections.remove_group(g.id)
    assert listing(root) == []
    rows = [r for r in journal(app) if r.kind == "remove_empty_dir"]
    assert [r.src for r in rows] == [f"{IMP}/Houses/Hillside", f"{IMP}/Houses"]
    assert all(r.state == "done" for r in rows)
    assert root.is_dir() and records(app) == []


def test_user_file_in_an_important_group_folder_is_left_alone_and_reported(
    app, fake_archive, files
):
    app.marks.mark_important(["id-a"], "Houses")
    root = fake_archive.root / IMP
    user = fake_archive.add(f"{IMP}/Houses/notes.txt", content=b"mine", drive_id="user-1")
    assert app.ongoing.sync().batch is None  # nothing to do: the file is simply there
    assert listing(root / "Houses") == ["a.pdf", "notes.txt"]
    app.marks.unmark_important(["id-a"])
    group = important(app).groups[0]
    app.collections.remove_group(group.id)
    assert listing(root) == ["Houses"]
    assert listing(root / "Houses") == ["notes.txt"]
    assert user.read_bytes() == b"mine"
    assert not any(r.kind == "remove_empty_dir" for r in journal(app))
    imp = important(app)
    assert imp.ongoing_status == f"{NOT_MANAGED}{IMP}/Houses {HOLDS_1}"
    before = len(journal(app))
    assert app.ongoing.sync().batch is None
    assert len(journal(app)) == before
    os.rename(user, fake_archive.root / BANKS / "notes.txt")
    app.ongoing.sync()
    assert listing(root) == []
    assert important(app).ongoing_status is None


def test_symlinked_intermediate_folder_in_important_is_refused(app, fake_archive, files):
    app.marks.mark_important(["id-a"], "Houses/Hillside")
    root = fake_archive.root / IMP
    elsewhere = fake_archive.root / "Home" / "Elsewhere"
    elsewhere.mkdir(parents=True)
    theirs = fake_archive.link("Home/Elsewhere/a.pdf", f"{BANKS}/b.pdf")
    (elsewhere / "Hillside").mkdir()
    os.unlink(root / "Houses" / "Hillside" / "a.pdf")
    os.rmdir(root / "Houses" / "Hillside")
    os.rmdir(root / "Houses")
    os.symlink(elsewhere, root / "Houses")
    result = app.ongoing.sync()
    assert result.batch is not None and result.batch.failed is None, result.problems
    assert readlink(root / "Houses") == str(elsewhere)
    assert theirs.is_symlink() and listing(elsewhere) == ["Hillside", "a.pdf"]
    assert listing(root) == ["Houses", "Houses_2"]
    assert listing(root / "Houses_2" / "Hillside") == ["a.pdf"]
    imp = important(app)
    assert imp.ongoing_status == f"{NOT_MANAGED}{IMP}/Houses{_REPLACED}"
    assert not any(r.rel.startswith(f"{IMP}/Houses/") for r in records(app))
    with pytest.raises(GuardError):
        primitives.remove_empty_dir(root / "Houses" / "Hillside", root)
    assert (elsewhere / "Hillside").is_dir()
    app.marks.unmark_important(["id-a"])
    for g in sorted(important(app).groups, key=lambda g: g.parent_id or 0, reverse=True):
        app.collections.remove_group(g.id)
    assert listing(root) == ["Houses"]
    assert readlink(root / "Houses") == str(elsewhere)
    assert theirs.is_symlink() and listing(elsewhere) == ["Hillside", "a.pdf"]


def test_users_links_in_important_are_never_adopted(app, fake_archive, files):
    root = fake_archive.root / IMP
    mine = fake_archive.link(f"{IMP}/a.pdf", f"{BANKS}/a.pdf")  # the same target, even
    real = fake_archive.add(f"{IMP}/passport.pdf", drive_id="id-p")
    app.marks.mark_important(["id-a"])
    assert listing(root) == ["a.pdf", "a_2.pdf", "passport.pdf"]
    assert points_at(root / "a_2.pdf", fake_archive, f"{BANKS}/a.pdf")
    assert [r.rel for r in records(app)] == [f"{IMP}/a_2.pdf"]
    app.marks.unmark_important(["id-a"])
    assert listing(root) == ["a.pdf", "passport.pdf"]
    assert mine.is_symlink() and real.exists()


def test_a_member_inside_important_is_not_linked(app, fake_archive):
    fake_archive.add(f"{IMP}/passport.pdf", drive_id="id-p")
    app.scan()
    app.marks.mark_important(["id-p"])
    assert listing(fake_archive.root / IMP) == ["passport.pdf"]
    assert records(app) == []


def test_missing_important_folder_does_nothing_and_reports(app, fake_archive, files):
    app.collections.on_change = None
    app.marks.mark_important(["id-a"], "Houses")
    app.ongoing.sync()
    c = app.collections.create("Sauna")
    app.collections.add_members(c.id, ["id-b", "id-c"])
    os.rename(fake_archive.root / IMP, fake_archive.root / "elsewhere")
    before = len(journal(app))
    kept = records(app)
    result = app.ongoing.sync()
    assert any(IMP in p for p in result.problems)
    # the Ongoing root still synced
    assert listing(fake_archive.root / ONG / "Sauna") == ["b.pdf", "c.pdf"]
    assert len(journal(app)) == before + 3
    assert [r for r in records(app) if r.rel.startswith(IMP)] == [
        r for r in kept if r.rel.startswith(IMP)
    ]
    imp = important(app)
    assert imp.ongoing_status is not None and imp.ongoing_status.startswith(NOT_MANAGED)
    os.rename(fake_archive.root / "elsewhere", fake_archive.root / IMP)
    result = app.ongoing.sync()
    assert result.problems == [] and result.batch is None
    assert important(app).ongoing_status is None


def test_empty_important_with_records_skips_that_root_only(app, fake_archive, files, tmp_path):
    app.collections.on_change = None
    app.marks.mark_important(["id-a"], "Houses")
    app.ongoing.sync()
    before = records(app)
    os.rename(fake_archive.root / IMP / "Houses", tmp_path / "away")
    c = app.collections.create("Sauna")
    app.collections.add_members(c.id, ["id-b", "id-c"])
    result = app.ongoing.sync()
    assert any("empty" in p and IMP in p for p in result.problems)
    assert listing(fake_archive.root / IMP) == []
    assert [r for r in records(app) if r.rel.startswith(IMP)] == before
    assert listing(fake_archive.root / ONG / "Sauna") == ["b.pdf", "c.pdf"]


def test_important_only_batches_skip_the_throttle(app, fake_archive, monkeypatch):
    from dam.ops import executor as executor_module

    for i in range(30):
        fake_archive.add(f"{BANKS}/f{i:02}.pdf", drive_id=f"id-{i}")
    app.scan()
    assert app.executor.throttle_ms > 0
    slept = []
    monkeypatch.setattr(executor_module.time, "sleep", lambda s: slept.append(s))
    app.marks.mark_important([f"id-{i}" for i in range(30)], "Many")
    assert len(listing(fake_archive.root / IMP / "Many")) == 30
    app.marks.unmark_important([f"id-{i}" for i in range(30)])
    assert slept == []


def test_a_failing_important_sync_is_throttled_per_root(app, fake_archive, files, monkeypatch):
    app.collections.on_change = None
    app.marks.mark_important(["id-a"])  # one link: the plan stays the same while it fails
    real = primitives.make_symlink

    def broken(target, link):
        if IMP in str(link):
            raise OSError(5, "Input/output error")
        return real(target, link)

    monkeypatch.setattr(primitives, "make_symlink", broken)
    first = app.ongoing.sync()
    assert first.batch is not None and first.batch.failed is not None
    failure = app.ongoing.last_failure
    assert failure and "Input/output error" in failure
    assert app.ongoing.sync().batch is None  # not retried
    # the Ongoing root is not held back by the Important root's failure
    c = app.collections.create("Sauna")
    app.collections.add_members(c.id, ["id-b", "id-c"])
    again = app.ongoing.sync()
    assert listing(fake_archive.root / ONG / "Sauna") == ["b.pdf", "c.pdf"]
    assert again.batch is not None and again.batch.failed is None
    assert any(failure in p for p in again.problems)
    assert len([r for r in journal(app) if r.state == "failed"]) == 1
    # a different plan is applied again, and once it works the failure is cleared
    monkeypatch.undo()
    app.marks.mark_important(["id-c"])
    fixed = app.ongoing.sync()
    assert fixed.batch is not None and fixed.batch.failed is None
    assert listing(fake_archive.root / IMP) == ["a.pdf", "c.pdf"]
    assert app.ongoing.last_failure is None


def test_undo_of_an_important_sync_batch_is_refused(app, fake_archive, files):
    app.marks.mark_important(["id-a"])
    with pytest.raises(OpFailed, match="Undo the collection change instead"):
        app.activity.undo(batches(app)[-1])
    assert listing(fake_archive.root / IMP) == ["a.pdf"]


def test_important_folder_swapped_between_plan_and_act_is_left(
    app, fake_archive, files, monkeypatch
):
    app.collections.on_change = None
    app.marks.mark_important(["id-a"], "Houses")
    app.ongoing.sync()
    root = fake_archive.root / IMP
    app.marks.unmark_important(["id-a"])
    app.collections.remove_group(important(app).groups[0].id)
    real = primitives.remove_empty_dir

    def racing(path, root_dir, identity=None):
        recreate_dir(path)  # the user's folder, same name, new identity
        return real(path, root_dir, identity=identity)

    monkeypatch.setattr(primitives, "remove_empty_dir", racing)
    result = app.ongoing.sync()
    assert result.batch is not None and result.batch.failed is not None
    assert (root / "Houses").is_dir()
    assert "identity changed" in (result.batch.error or "")


# --- the guards: nowhere else ----------------------------------------------------------


def test_remove_empty_dir_is_allowed_under_important(app):
    validate(Op(OpKind.REMOVE_EMPTY_DIR, f"{IMP}/Houses", None), app.paths)
    validate(Op(OpKind.UNLINK_SYMLINK, f"{IMP}/a.pdf", None), app.paths)
    validate(Op(OpKind.REMOVE_EMPTY_DIR, f"{IMP}/Houses/Hillside", None), app.paths)


@pytest.mark.parametrize(
    "src",
    [
        IMP,  # the Important folder itself
        ONG,
        "10. Financial/Banks",
        "20. Legal/x",  # another protected path
        "##. Important-other/x",
        "##. To Delete/x",
    ],
)
def test_guards_refuse_a_removal_outside_both_roots(fake_archive, src):
    settings = Settings(archive_root=str(fake_archive.root), protected_paths=[IMP, "20. Legal"])
    paths = ArchivePaths(fake_archive.root, settings)
    with pytest.raises(GuardError):
        validate(Op(OpKind.REMOVE_EMPTY_DIR, src, None), paths)
    with pytest.raises(GuardError):
        validate(Op(OpKind.UNLINK_SYMLINK, src, None), paths)


def test_a_protected_folder_inside_important_is_still_protected(fake_archive):
    settings = Settings(
        archive_root=str(fake_archive.root), protected_paths=[IMP, f"{IMP}/Passports"]
    )
    paths = ArchivePaths(fake_archive.root, settings)
    validate(Op(OpKind.REMOVE_EMPTY_DIR, f"{IMP}/Houses", None), paths)
    with pytest.raises(GuardError):
        validate(Op(OpKind.REMOVE_EMPTY_DIR, f"{IMP}/Passports", None), paths)
    with pytest.raises(GuardError):
        validate(Op(OpKind.REMOVE_EMPTY_DIR, f"{IMP}/Passports/Old", None), paths)


def test_executor_removes_only_inside_the_two_roots(app, fake_archive):
    fake_archive.add(f"{BANKS}/a.pdf")
    outside = fake_archive.link("10. Financial/l.pdf", f"{BANKS}/a.pdf")
    (fake_archive.root / "10. Financial" / "Empty").mkdir()
    for op in (
        Op(OpKind.UNLINK_SYMLINK, "10. Financial/l.pdf", None),
        Op(OpKind.REMOVE_EMPTY_DIR, "10. Financial/Empty", None),
        Op(OpKind.REMOVE_EMPTY_DIR, IMP, None),
    ):
        with pytest.raises(GuardError):
            app.executor.apply(Plan([op], "workflow"))
    assert outside.is_symlink() and (fake_archive.root / "10. Financial" / "Empty").is_dir()
    inside = fake_archive.link(f"{IMP}/l.pdf", f"{BANKS}/a.pdf")
    (fake_archive.root / IMP / "Empty").mkdir()
    result = app.executor.apply(
        Plan(
            [
                Op(OpKind.UNLINK_SYMLINK, f"{IMP}/l.pdf", None),
                Op(OpKind.REMOVE_EMPTY_DIR, f"{IMP}/Empty", None),
            ],
            "workflow",
        )
    )
    assert result.failed is None, result.error
    assert not inside.is_symlink() and listing(fake_archive.root / IMP) == []
    assert (fake_archive.root / BANKS / "a.pdf").exists()


def test_important_is_still_protected_against_quarantine(app, fake_archive):
    fake_archive.add(f"{IMP}/x.pdf")
    with pytest.raises(GuardError):
        app.executor.preview(Plan([Op(OpKind.QUARANTINE, f"{IMP}/x.pdf", None)], "ui"))
    with pytest.raises(GuardError):
        app.executor.preview(Plan([Op(OpKind.MOVE, f"{IMP}/x.pdf", "##. To Delete")], "ui"))


def test_unlink_symlink_refuses_a_root_that_is_a_link(fake_archive, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    fake_archive.add(f"{BANKS}/a.pdf")
    link = elsewhere / "a.pdf"
    link.symlink_to(fake_archive.root / BANKS / "a.pdf")
    os.rmdir(fake_archive.root / IMP)
    os.symlink(elsewhere, fake_archive.root / IMP)  # the root itself is a link now
    with pytest.raises(GuardError, match="not a real folder"):
        primitives.unlink_symlink(fake_archive.root / IMP / "a.pdf", fake_archive.root / IMP)
    assert link.is_symlink()


def test_nested_roots_leave_important_alone_without_churn(tmp_path, fake_archive):
    import yaml

    from dam.app import App
    from dam.config import AppPaths

    nested = f"{IMP}/Ongoing"
    (fake_archive.root / nested).mkdir()
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="id-a")
    fake_archive.add(f"{BANKS}/b.pdf", drive_id="id-b")
    paths = AppPaths(tmp_path / "data-nested")
    paths.ensure()
    (paths.config_dir / "settings.yaml").write_text(
        yaml.safe_dump(
            {"archive_root": str(fake_archive.root), "special_folders": {"ongoing": nested}}
        ),
        encoding="utf-8",
    )
    app = App.create(paths.data_dir)
    try:
        app.scan()
        app.marks.star(["id-a"])
        app.marks.mark_important(["id-b"], "Houses")
        c = app.collections.create("Sauna")
        app.collections.add_members(c.id, ["id-a", "id-b"])
        ongoing = fake_archive.root / nested
        assert listing(ongoing) == ["Sauna", "a.pdf"]  # the Ongoing root works
        assert listing(fake_archive.root / IMP) == ["Ongoing"]  # Important does nothing
        imp = important(app)
        assert imp.ongoing_status == (
            f"{NOT_MANAGED}{IMP} and {nested} must not be inside each other. "
            "Check the folder settings; nothing was published."
        )
        before = len(journal(app))
        kept = records(app)
        for _ in range(3):
            result = app.ongoing.sync()
            assert result.batch is None
            assert any("must not be inside each other" in p for p in result.problems)
        assert len(journal(app)) == before and records(app) == kept
        assert listing(ongoing) == ["Sauna", "a.pdf"]
    finally:
        app.close()


def test_primitives_take_the_important_root(fake_archive):
    root = fake_archive.root / IMP
    (root / "Houses").mkdir()
    primitives.remove_empty_dir(root / "Houses", root)
    assert listing(root) == []
    with pytest.raises(GuardError):
        primitives.remove_empty_dir(root, root)
    (fake_archive.root / ONG / "x").mkdir()
    with pytest.raises(GuardError):  # one root at a time
        primitives.remove_empty_dir(fake_archive.root / ONG / "x", root)
    assert (fake_archive.root / ONG / "x").is_dir()
