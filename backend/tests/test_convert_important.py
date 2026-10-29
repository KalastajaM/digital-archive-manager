"""Converting ``##. Important`` (stars, Task 3), and "Star it" in Convert Ongoing.

The one place the app may remove the user's own links: inside ``##. Important`` or
``##. Ongoing``, during a previewed conversion (fingerprint), each link recreated as
the app's at the same place or left untouched with a reason, and all of it undoable.
"""

import os
from pathlib import Path

import pytest
import xattr
from fastapi.testclient import TestClient
from sqlalchemy import select

from conftest import posix_names
from dam.api import create_api
from dam.collections.convert_important import NOT_REMOVED
from dam.core.fs import readlink, realpath
from dam.db.tables import collection_groups, ongoing_entries, operations
from dam.errors import InvalidRequest, StalePreview
from dam.index.driveid import DRIVE_ID_XATTR, read_drive_id
from dam.ops import identity
from dam.ops.model import GuardError

IMP = "##. Important"
ONG = "##. Ongoing"
FAMILY = "40. Family"
TAXES = "13. Taxes"
PAPERS = f"{FAMILY}/Papers"
FINDER = b"\x00\x00\x00\x01Bud1" + b"\x00" * 24  # Finder's .DS_Store header
BASE = "http://127.0.0.1:8765"


# --- helpers -----------------------------------------------------------------------


def folder(fake_archive, rel: str, drive_id: str) -> Path:
    p = fake_archive.root / rel
    p.mkdir(parents=True, exist_ok=True)
    xattr.setxattr(p, DRIVE_ID_XATTR, drive_id.encode())
    return p


def listing(path: Path) -> list[str]:
    return sorted(os.listdir(path))


def points_at(link: Path, fake_archive, rel: str) -> bool:
    return link.is_symlink() and str(realpath(link)) == str(fake_archive.root.resolve() / rel)


def journal(app, batch_id: str):
    with app.engine.connect() as conn:
        return conn.execute(
            select(operations).where(operations.c.batch_id == batch_id).order_by(operations.c.id)
        ).all()


def batch_ids(app) -> list[str]:
    with app.engine.connect() as conn:
        rows = conn.execute(select(operations.c.batch_id).order_by(operations.c.id)).scalars()
        return list(dict.fromkeys(rows))


def records(app):
    with app.engine.connect() as conn:
        return conn.execute(select(ongoing_entries).order_by(ongoing_entries.c.rel)).all()


def group_rows(app):
    with app.engine.connect() as conn:
        return conn.execute(select(collection_groups).order_by(collection_groups.c.id)).all()


def important(app):
    return app.collections.builtin("important")


def starred(app):
    return app.collections.builtin("starred")


def members(app) -> dict[str, str]:
    """drive id -> group path ("" for ungrouped) of the Important members."""
    c = important(app)
    by_id = {g.id: g for g in c.groups}

    def path(gid):
        parts = []
        while gid is not None:
            parts.append(by_id[gid].name)
            gid = by_id[gid].parent_id
        return "/".join(reversed(parts))

    return {m.drive_id: path(m.group_id) for m in c.members}


def snapshot(root: Path) -> dict[str, tuple]:
    """Everything under ``root``: links by target, files by drive id, folders."""
    out: dict[str, tuple] = {}
    for base, dirs, files in os.walk(root):
        for n in [*dirs, *files]:
            p = Path(base) / n
            rel = str(p.relative_to(root))
            if p.is_symlink():
                out[rel] = ("link", readlink(p))
            elif p.is_dir():
                out[rel] = ("dir",)
            else:
                out[rel] = ("file", read_drive_id(p))
        dirs[:] = [d for d in dirs if not (Path(base) / d).is_symlink()]
    return out


def convert(app, rel: str, destination):
    plan = app.convert_important.preview(rel, destination)
    return app.convert_important.apply(rel, destination, plan.fingerprint)


@pytest.fixture
def demo(app, fake_archive):
    """A hand-made ``##. Important``: a folder ``Houses`` (a link and a file at its
    top, a subfolder ``Hillside`` with a link and a file), a link to a file, a link to
    a folder and a real file at the top."""
    folder(fake_archive, f"{FAMILY}/Tilly", "d-tilly")
    fake_archive.add(f"{FAMILY}/Tilly/school.pdf", drive_id="id-school")
    fake_archive.add(f"{FAMILY}/deed.pdf", drive_id="id-deed")
    fake_archive.add(f"{FAMILY}/will.pdf", drive_id="id-will")
    fake_archive.add(f"{TAXES}/2025.pdf", drive_id="id-tax")
    folder(fake_archive, f"{IMP}/Houses", "d-houses")
    folder(fake_archive, f"{IMP}/Houses/Hillside", "d-hillside")
    fake_archive.link(f"{IMP}/Houses/Hillside/deed.pdf", f"{FAMILY}/deed.pdf")
    fake_archive.add(f"{IMP}/Houses/Hillside/survey.pdf", drive_id="id-survey")
    fake_archive.link(f"{IMP}/Houses/will.pdf", f"{FAMILY}/will.pdf")
    fake_archive.add(f"{IMP}/Houses/notes.pdf", drive_id="id-notes")
    fake_archive.link(f"{IMP}/Tax 2025.pdf", f"{TAXES}/2025.pdf")
    fake_archive.add(f"{IMP}/passport.pdf", drive_id="id-passport")
    fake_archive.link(f"{IMP}/Tilly", f"{FAMILY}/Tilly")
    app.scan()
    return fake_archive


@pytest.fixture
def client(app):
    with TestClient(create_api(app), base_url=BASE) as c:
        yield c


def post(client, url, body):
    return client.request("POST", url, json=body, headers={"Origin": BASE})


# --- entries -------------------------------------------------------------------------


def test_entries_classify_important(app, demo):
    (demo.root / IMP / ".DS_Store").write_bytes(FINDER)  # housekeeping: not listed
    app.marks.mark_important(["id-school"], "School")  # the app's own folder: managed
    got = {
        e.rel: (e.kind, e.managed, e.suggested_name, e.problem)
        for e in app.convert_important.entries()
    }
    assert got == {
        f"{IMP}/Houses": ("folder", False, "Houses", None),
        f"{IMP}/School": ("folder", True, "School", None),
        f"{IMP}/Tax 2025.pdf": ("link", False, "Tax 2025", None),
        f"{IMP}/Tilly": ("link", False, "Tilly", None),
        f"{IMP}/passport.pdf": ("file", False, "passport", None),
    }
    school = next(e for e in app.convert_important.entries() if e.rel == f"{IMP}/School")
    assert (school.collection_id, school.collection_name) == (important(app).id, "Important")
    assert app.convert_important.unmanaged_count() == 4


# --- a folder entry ------------------------------------------------------------------


def test_convert_important_keeps_every_shortcut(app, demo):
    root = demo.root / IMP
    before = [f"{IMP}/Houses/Hillside/deed.pdf", f"{IMP}/Houses/will.pdf"]
    plan = app.convert_important.preview(f"{IMP}/Houses", PAPERS)
    assert [(r.kind, r.dst) for r in plan.ops] == [
        ("unlink_symlink", f"{IMP}/Houses/Hillside/deed.pdf"),
        ("unlink_symlink", f"{IMP}/Houses/will.pdf"),
        ("mkdir", PAPERS),
        ("mkdir", f"{PAPERS}/Houses"),
        ("mkdir", f"{PAPERS}/Houses/Hillside"),
        ("move", f"{PAPERS}/Houses/Hillside/survey.pdf"),
        ("move", f"{PAPERS}/Houses/notes.pdf"),
        ("remove_empty_dir", f"{IMP}/Houses/Hillside"),
        ("remove_empty_dir", f"{IMP}/Houses"),
        ("mkdir", f"{IMP}/Houses"),
        ("mkdir", f"{IMP}/Houses/Hillside"),
        ("symlink", f"{IMP}/Houses/will.pdf"),
        ("symlink", f"{IMP}/Houses/notes.pdf"),
        ("symlink", f"{IMP}/Houses/Hillside/deed.pdf"),
        ("symlink", f"{IMP}/Houses/Hillside/survey.pdf"),
    ]
    assert plan.members == [
        f"{FAMILY}/deed.pdf",
        f"{FAMILY}/will.pdf",
        f"{PAPERS}/Houses/Hillside/survey.pdf",
        f"{PAPERS}/Houses/notes.pdf",
    ]
    assert plan.groups == ["Houses/Hillside", "Houses", "Houses/Hillside", "Houses"]
    assert (plan.collection, plan.existing, plan.existing_members) == ("Important", True, 0)
    assert plan.notes == []
    result = app.convert_important.apply(f"{IMP}/Houses", PAPERS, plan.fingerprint)
    assert result.batch.failed is None and result.problems == []
    assert result.collection_id == important(app).id
    # every user shortcut is the app's link now, at the same place, to the same target
    for rel in before:
        assert (demo.root / rel).is_symlink()
    assert points_at(root / "Houses/Hillside/deed.pdf", demo, f"{FAMILY}/deed.pdf")
    assert points_at(root / "Houses/will.pdf", demo, f"{FAMILY}/will.pdf")
    # the real files moved, mirroring their subfolder path, and are linked from there
    assert (demo.root / PAPERS / "Houses/Hillside/survey.pdf").is_file()
    assert (demo.root / PAPERS / "Houses/notes.pdf").is_file()
    assert points_at(root / "Houses/notes.pdf", demo, f"{PAPERS}/Houses/notes.pdf")
    assert points_at(
        root / "Houses/Hillside/survey.pdf", demo, f"{PAPERS}/Houses/Hillside/survey.pdf"
    )
    assert listing(root / "Houses") == ["Hillside", "notes.pdf", "will.pdf"]
    assert listing(root / "Houses/Hillside") == ["deed.pdf", "survey.pdf"]
    assert app.repo.get("id-survey").path == f"{PAPERS}/Houses/Hillside/survey.pdf"
    assert members(app) == {
        "id-deed": "Houses/Hillside",
        "id-survey": "Houses/Hillside",
        "id-will": "Houses",
        "id-notes": "Houses",
    }
    imp = important(app)
    assert (imp.ongoing_rel, imp.ongoing_status) == (IMP, None)
    owned = {r.rel for r in records(app) if r.collection_id == imp.id}
    assert owned == {
        f"{IMP}/Houses",
        f"{IMP}/Houses/Hillside",
        f"{IMP}/Houses/will.pdf",
        f"{IMP}/Houses/notes.pdf",
        f"{IMP}/Houses/Hillside/deed.pdf",
        f"{IMP}/Houses/Hillside/survey.pdf",
    }
    rows = journal(app, result.batch.batch_id)
    assert {r.origin for r in rows} == {"ui"} and {r.state for r in rows} == {"done"}
    assert result.sync is not None and result.sync.batches == []  # nothing left to do
    assert app.convert_important.unmanaged_count() == 3
    assert {e.rel: e.managed for e in app.convert_important.entries()}[f"{IMP}/Houses"] is True
    assert [b for b in batch_ids(app)] == [result.batch.batch_id]


def test_undo_restores_everything(app, demo):
    root = demo.root / IMP
    kept = app.collections.create_group(important(app).id, "Kept")  # a group of the user's
    before = snapshot(root)
    result = convert(app, f"{IMP}/Houses", PAPERS)
    assert result.batch.failed is None
    assert len(group_rows(app)) == 3
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None and outcome.follow_up_error is None
    assert snapshot(root) == before
    assert app.repo.get("id-survey").path == f"{IMP}/Houses/Hillside/survey.pdf"
    assert members(app) == {}
    assert [g.name for g in important(app).groups] == ["Kept"]  # the batch's groups went
    assert important(app).groups[0].id == kept.id
    assert {r.state for r in journal(app, result.batch.batch_id)} == {"undone"}
    assert not any(r.rel.startswith(f"{IMP}/Houses") for r in records(app))
    assert [r.rel for r in records(app)] == [f"{IMP}/Kept"]  # the user's group's folder
    imp = important(app)
    assert imp.ongoing_status is None
    # the folders the moves created stay (Phase 1 rule), empty
    assert listing(demo.root / PAPERS / "Houses" / "Hillside") == []


def test_undo_is_refused_while_the_apps_group_folder_holds_later_links(app, demo):
    demo.add(f"{FAMILY}/extra.pdf", drive_id="id-extra")
    app.scan()
    result = convert(app, f"{IMP}/Houses", PAPERS)
    app.marks.mark_important(["id-extra"], "Houses")  # a later link in the app's folder
    with pytest.raises(GuardError, match="undo the later changes"):
        app.activity.undo(result.batch.batch_id)
    assert members(app)["id-extra"] == "Houses"
    assert points_at(demo.root / IMP / "Houses/extra.pdf", demo, f"{FAMILY}/extra.pdf")


def test_removing_what_a_batch_created_keeps_a_group_used_since(app, demo):
    """``remove_created_by``: the batch's memberships go; its groups go only while
    still empty (no member, no subgroup), deepest first; the user's groups stay."""
    imp = important(app)
    app.collections.set_group_path(imp.id, ["id-deed"], ["Houses", "Hillside"], batch_id="b1")
    app.collections.set_group_path(imp.id, ["id-will"], ["Houses"], batch_id="b1")
    app.collections.set_group_path(imp.id, [], ["Houses", "Lahti"], batch_id="b1")
    app.marks.mark_important(["id-tax"], "Houses")  # the user's own, later
    assert {g.name: g.created_by_batch for g in group_rows(app)} == {
        "Houses": "b1",
        "Hillside": "b1",
        "Lahti": "b1",
    }
    assert app.collections.remove_created_by("b1") == (2, 2)  # members; Hillside, Lahti
    assert members(app) == {"id-tax": "Houses"}
    assert [(g.name, g.position) for g in important(app).groups] == [("Houses", 0)]
    app.marks.unmark_important(["id-tax"])
    assert app.collections.remove_created_by("b1") == (0, 1)
    assert important(app).groups == []


def test_duplicate_shortcut_is_left_untouched_with_a_reason(app, demo):
    root = demo.root / IMP
    demo.link(f"{IMP}/Houses/Hillside/deed-copy.pdf", f"{FAMILY}/deed.pdf")
    ino = os.lstat(root / "Houses/Hillside/deed.pdf").st_ino
    plan = app.convert_important.preview(f"{IMP}/Houses", PAPERS)
    reason = (
        f"{IMP}/Houses/Hillside/deed.pdf is left untouched: same file as"
        f" {IMP}/Houses/Hillside/deed-copy.pdf (already in Important)"
    )
    assert reason in plan.notes
    assert plan.members.count(f"{FAMILY}/deed.pdf") == 1
    assert not any(r.src == f"{IMP}/Houses/Hillside/deed.pdf" for r in plan.ops)
    # the folder holding it stays, and so does the one above it
    assert f"{IMP}/Houses/Hillside{NOT_REMOVED}it still holds 'deed.pdf'" in plan.notes
    assert f"{IMP}/Houses{NOT_REMOVED}it still holds 'Hillside'" in plan.notes
    assert not any(r.kind == "remove_empty_dir" for r in plan.ops)
    assert (
        f"The group folder {IMP}/Houses will be named {IMP}/Houses_2, because that name is taken."
        in plan.notes
    )
    assert plan.link_names == ["deed-copy.pdf", "", "", ""]
    result = app.convert_important.apply(f"{IMP}/Houses", PAPERS, plan.fingerprint)
    assert result.batch.failed is None
    assert os.lstat(root / "Houses/Hillside/deed.pdf").st_ino == ino
    assert points_at(root / "Houses/Hillside/deed.pdf", demo, f"{FAMILY}/deed.pdf")
    assert listing(root / "Houses/Hillside") == ["deed.pdf"]
    assert members(app)["id-deed"] == "Houses/Hillside"
    # the app's group folder lives beside the user's folder
    assert listing(root) == ["Houses", "Houses_2", "Tax 2025.pdf", "Tilly", "passport.pdf"]
    assert listing(root / "Houses_2/Hillside") == ["deed-copy.pdf", "survey.pdf"]  # its name
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None, outcome.batch.error
    assert listing(root / "Houses/Hillside") == ["deed-copy.pdf", "deed.pdf", "survey.pdf"]
    app.ongoing.sync()  # the app's now empty folder goes with the next sync
    assert "Houses_2" not in listing(root)


def test_a_link_to_a_file_already_important_is_left_untouched(app, demo):
    app.marks.mark_important(["id-will"], "Legal")
    assert points_at(demo.root / IMP / "Legal/will.pdf", demo, f"{FAMILY}/will.pdf")
    plan = app.convert_important.preview(f"{IMP}/Houses", PAPERS)
    assert (
        f"{IMP}/Houses/will.pdf is left untouched: same file as {IMP}/Legal/will.pdf"
        " (already in Important)"
    ) in plan.notes
    assert f"{FAMILY}/will.pdf" not in plan.members
    result = app.convert_important.apply(f"{IMP}/Houses", PAPERS, plan.fingerprint)
    assert result.batch.failed is None
    assert points_at(demo.root / IMP / "Houses/will.pdf", demo, f"{FAMILY}/will.pdf")
    assert members(app)["id-will"] == "Legal"


def test_mirrored_destination_takes_a_suffix_on_a_clash(app, demo):
    demo.add(f"{PAPERS}/Houses/notes.pdf", drive_id="id-other")
    app.scan()
    plan = app.convert_important.preview(f"{IMP}/Houses", PAPERS)
    assert ("move", f"{PAPERS}/Houses/notes_2.pdf") in [(r.kind, r.dst) for r in plan.ops]
    assert f"{PAPERS}/Houses/notes_2.pdf" in plan.members
    assert any("notes.pdf is already taken there" in n for n in plan.notes)
    result = app.convert_important.apply(f"{IMP}/Houses", PAPERS, plan.fingerprint)
    assert result.batch.failed is None
    assert app.repo.get("id-notes").path == f"{PAPERS}/Houses/notes_2.pdf"
    assert points_at(demo.root / IMP / "Houses/notes_2.pdf", demo, f"{PAPERS}/Houses/notes_2.pdf")


@posix_names
def test_emptied_subfolder_is_removed_and_one_with_a_leftover_is_kept(app, demo):
    root = demo.root / IMP
    folder(demo, f"{IMP}/Houses/Lahti", "d-lahti")
    demo.add(f"{IMP}/Houses/Lahti/plan.pdf", drive_id="id-lahti")
    (root / "Houses/Lahti/Icon\r").write_bytes(b"")  # a leftover the app never moves
    (root / "Houses/Hillside/.DS_Store").write_bytes(FINDER)  # Finder's cache: fine
    app.scan()
    plan = app.convert_important.preview(f"{IMP}/Houses", PAPERS)
    removed = [r.dst for r in plan.ops if r.kind == "remove_empty_dir"]
    assert removed == [f"{IMP}/Houses/Hillside"]
    assert f"{IMP}/Houses/Lahti{NOT_REMOVED}it still holds 'Icon\\r'" in plan.notes
    result = app.convert_important.apply(f"{IMP}/Houses", PAPERS, plan.fingerprint)
    assert result.batch.failed is None
    assert listing(root / "Houses") == ["Lahti"]
    assert listing(root / "Houses/Lahti") == ["Icon\r"]
    assert (demo.root / PAPERS / "Houses/Lahti/plan.pdf").is_file()
    assert members(app)["id-lahti"] == "Houses/Lahti"
    assert listing(root / "Houses_2") == ["Hillside", "Lahti", "notes.pdf", "will.pdf"]
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None, outcome.batch.error
    assert listing(root / "Houses") == ["Hillside", "Lahti", "notes.pdf", "will.pdf"]
    assert listing(root / "Houses/Hillside") == ["deed.pdf", "survey.pdf"]  # not the cache


def test_a_shortcut_keeps_its_own_name(app, demo):
    """Two shortcuts to two different ``passport.pdf`` files keep their names; the
    sync that follows has nothing to do, and the undo puts the shortcuts back."""
    root = demo.root / IMP
    demo.add(f"{FAMILY}/Jess/passport.pdf", drive_id="id-jess")
    demo.add(f"{FAMILY}/Tilly/passport.pdf", drive_id="id-tilly-pp")
    demo.link(f"{IMP}/Houses/Passport Jess.pdf", f"{FAMILY}/Jess/passport.pdf")
    demo.link(f"{IMP}/Houses/Passport Tilly.pdf", f"{FAMILY}/Tilly/passport.pdf")
    app.scan()
    before = snapshot(root)
    plan = app.convert_important.preview(f"{IMP}/Houses", PAPERS)
    assert plan.notes == []
    assert dict(zip(plan.members, plan.link_names, strict=True)) == {
        f"{FAMILY}/deed.pdf": "",
        f"{FAMILY}/will.pdf": "",
        f"{FAMILY}/Jess/passport.pdf": "Passport Jess.pdf",
        f"{FAMILY}/Tilly/passport.pdf": "Passport Tilly.pdf",
        f"{PAPERS}/Houses/Hillside/survey.pdf": "",
        f"{PAPERS}/Houses/notes.pdf": "",
    }
    result = app.convert_important.apply(f"{IMP}/Houses", PAPERS, plan.fingerprint)
    assert result.batch.failed is None and result.problems == []
    assert listing(root / "Houses") == [
        "Hillside",
        "Passport Jess.pdf",
        "Passport Tilly.pdf",
        "notes.pdf",
        "will.pdf",
    ]
    assert points_at(root / "Houses/Passport Jess.pdf", demo, f"{FAMILY}/Jess/passport.pdf")
    assert points_at(root / "Houses/Passport Tilly.pdf", demo, f"{FAMILY}/Tilly/passport.pdf")
    assert {m.drive_id: m.link_name for m in important(app).members if m.link_name} == {
        "id-jess": "Passport Jess.pdf",
        "id-tilly-pp": "Passport Tilly.pdf",
    }
    assert result.sync.batches == []
    before_sync = len(batch_ids(app))
    assert app.ongoing.sync().batches == [] and len(batch_ids(app)) == before_sync
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None, outcome.batch.error
    assert snapshot(root) == before


def test_a_name_the_publisher_cannot_use_falls_back_and_a_collision_is_noted(app, demo):
    odd = "plan\u200b.pdf"  # a format character: not a name the app gives a link
    demo.add(f"{FAMILY}/plan.pdf", drive_id="id-plan")
    demo.link(f"{IMP}/Houses/{odd}", f"{FAMILY}/plan.pdf")
    demo.add(f"{IMP}/Houses/plan.pdf", drive_id="id-planfile")
    app.scan()
    plan = app.convert_important.preview(f"{IMP}/Houses", PAPERS)
    assert f"{IMP}/Houses/{odd} becomes {IMP}/Houses/plan.pdf" in plan.notes
    assert f"{PAPERS}/Houses/plan.pdf is linked as {IMP}/Houses/plan_2.pdf" in plan.notes
    result = app.convert_important.apply(f"{IMP}/Houses", PAPERS, plan.fingerprint)
    assert result.batch.failed is None
    assert points_at(demo.root / IMP / "Houses/plan.pdf", demo, f"{FAMILY}/plan.pdf")
    assert points_at(demo.root / IMP / "Houses/plan_2.pdf", demo, f"{PAPERS}/Houses/plan.pdf")


def test_a_file_that_became_a_member_during_the_batch_is_left_as_it_was(app, demo, monkeypatch):
    real = app.executor.apply

    def marking(plan):
        batch = real(plan)  # marked, in the same group, while the batch runs
        app.collections.set_group_path(important(app).id, ["id-will"], ["Houses"], notify=False)
        return batch

    monkeypatch.setattr(app.executor, "apply", marking)
    plan = app.convert_important.preview(f"{IMP}/Houses", PAPERS)
    result = app.convert_important.apply(f"{IMP}/Houses", PAPERS, plan.fingerprint)
    assert result.batch.failed is None
    assert [p for p in result.problems if "member already" in p] == [
        f"{FAMILY}/will.pdf was a member already; left as it was (not the conversion's to undo)"
    ]
    with app.engine.connect() as conn:
        from dam.db.tables import collection_members

        rows = {
            r.drive_id: r.created_by_batch for r in conn.execute(select(collection_members)).all()
        }
    assert rows["id-will"] is None and rows["id-deed"] == result.batch.batch_id
    assert result.sync.batches == []  # the link is where both want it
    monkeypatch.setattr(app.executor, "apply", real)
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None, outcome.batch.error
    assert members(app) == {"id-will": "Houses"}  # the user's membership and group stay
    assert [g.name for g in important(app).groups] == ["Houses"]


def test_a_target_that_left_the_index_is_a_refusal(app, demo, monkeypatch):
    monkeypatch.setattr(app.convert_important, "_indexed", lambda rel: None)
    with pytest.raises(InvalidRequest, match="cannot be converted"):
        app.convert_important.preview(f"{IMP}/Tax 2025.pdf", None)
    assert batch_ids(app) == []


# --- top-level entries ---------------------------------------------------------------


def test_top_level_link_file_and_folder_link(app, demo):
    root = demo.root / IMP
    plan = app.convert_important.preview(f"{IMP}/Tax 2025.pdf", None)
    assert [(r.kind, r.dst) for r in plan.ops] == [
        ("unlink_symlink", f"{IMP}/Tax 2025.pdf"),
        ("symlink", f"{IMP}/Tax 2025.pdf"),  # the shortcut keeps its own name
    ]
    assert plan.members == [f"{TAXES}/2025.pdf"] and plan.groups == [""]
    assert plan.link_names == ["Tax 2025.pdf"] and plan.notes == []
    result = app.convert_important.apply(
        f"{IMP}/Tax 2025.pdf", "ignored for links", plan.fingerprint
    )
    assert result.batch.failed is None
    assert points_at(root / "Tax 2025.pdf", demo, f"{TAXES}/2025.pdf")
    assert "2025.pdf" not in listing(root)

    plan = app.convert_important.preview(f"{IMP}/passport.pdf", PAPERS)
    assert [(r.kind, r.dst) for r in plan.ops] == [
        ("mkdir", PAPERS),
        ("move", f"{PAPERS}/passport.pdf"),
        ("symlink", f"{IMP}/passport.pdf"),
    ]
    result = app.convert_important.apply(f"{IMP}/passport.pdf", PAPERS, plan.fingerprint)
    assert result.batch.failed is None
    assert points_at(root / "passport.pdf", demo, f"{PAPERS}/passport.pdf")

    result = convert(app, f"{IMP}/Tilly", None)
    assert result.batch.failed is None
    assert points_at(root / "Tilly", demo, f"{FAMILY}/Tilly")
    assert members(app) == {"id-tax": "", "id-passport": "", "d-tilly": ""}
    for e in app.convert_important.entries():
        assert e.managed or e.rel == f"{IMP}/Houses", e.rel
    assert important(app).ongoing_status is None


def test_undo_of_a_top_level_link_puts_the_users_link_back(app, demo):
    result = convert(app, f"{IMP}/Tax 2025.pdf", None)
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None and outcome.follow_up_error is None
    root = demo.root / IMP
    assert points_at(root / "Tax 2025.pdf", demo, f"{TAXES}/2025.pdf")
    assert "2025.pdf" not in listing(root)
    assert members(app) == {} and records(app) == []


def test_undo_of_a_top_level_link_forgets_the_record_when_the_inode_is_reused(
    app, demo, monkeypatch
):
    # ext4 gives the restored link the inode number of the app's link the undo removed
    result = convert(app, f"{IMP}/Tax 2025.pdf", None)
    monkeypatch.setattr(identity, "same_object", lambda recorded, current: recorded is not None)
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None and outcome.follow_up_error is None
    assert records(app) == []
    app.ongoing.sync()
    assert points_at(demo.root / IMP / "Tax 2025.pdf", demo, f"{TAXES}/2025.pdf")


# --- refusals ------------------------------------------------------------------------


def test_outside_broken_and_root_links_are_refused(app, demo, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.symlink(elsewhere, demo.root / IMP / "Outside")
    demo.link(f"{IMP}/Gone", "Home/gone")
    demo.add(f"{ONG}/plan.xlsx", drive_id="id-plan")
    demo.link(f"{IMP}/Plan", f"{ONG}/plan.xlsx")
    app.scan()
    with pytest.raises(InvalidRequest, match="points outside the archive"):
        app.convert_important.preview(f"{IMP}/Outside", None)
    with pytest.raises(InvalidRequest, match="is broken"):
        app.convert_important.preview(f"{IMP}/Gone", None)
    with pytest.raises(InvalidRequest, match=f"points into {ONG}"):
        app.convert_important.preview(f"{IMP}/Plan", None)
    demo.link(f"{IMP}/Houses/Hillside/Outside", str(elsewhere))
    with pytest.raises(InvalidRequest, match="points outside the archive"):
        app.convert_important.preview(f"{IMP}/Houses", PAPERS)
    assert batch_ids(app) == []
    problems = {e.rel: e.problem for e in app.convert_important.entries()}
    assert problems[f"{IMP}/Gone"] == "it is broken: Home/gone does not exist"
    assert (
        problems[f"{IMP}/Houses"]
        == "the link Hillside/Outside: it points outside the archive (" + str(elsewhere) + ")"
    )
    # the cheap count looks at top-level entries only: the folder with the deep
    # outside link still counts (``preview`` refuses it)
    assert app.convert_important.unmanaged_count() == 4


def test_managed_entries_and_bad_destinations_are_refused(app, demo):
    app.marks.mark_important(["id-school"], "School")
    synced = batch_ids(app)  # the mark's own sync batch
    with pytest.raises(InvalidRequest, match="already a collection"):
        app.convert_important.preview(f"{IMP}/School", PAPERS)
    with pytest.raises(InvalidRequest, match=f"cannot be inside {IMP}"):
        app.convert_important.preview(f"{IMP}/passport.pdf", f"{IMP}/x")
    with pytest.raises(InvalidRequest, match=f"cannot be inside {ONG}"):
        app.convert_important.preview(f"{IMP}/passport.pdf", f"{ONG}/x")
    with pytest.raises(InvalidRequest, match="Choose the archive folder"):
        app.convert_important.preview(f"{IMP}/Houses", None)
    with pytest.raises(InvalidRequest, match="not an item directly inside"):
        app.convert_important.preview(f"{IMP}/Houses/Hillside", PAPERS)
    with pytest.raises(InvalidRequest, match="not an item directly inside"):
        app.convert_important.preview(f"{ONG}/x", PAPERS)
    assert batch_ids(app) == synced


def test_stale_preview_is_refused(app, demo):
    plan = app.convert_important.preview(f"{IMP}/Houses", PAPERS)
    assert plan.fingerprint == app.convert_important.preview(f"{IMP}/Houses", PAPERS).fingerprint
    demo.add(f"{IMP}/Houses/late.pdf", drive_id="id-late")
    app.scan()
    with pytest.raises(StalePreview, match="Preview again"):
        app.convert_important.apply(f"{IMP}/Houses", PAPERS, plan.fingerprint)
    with pytest.raises(StalePreview):
        app.convert_important.apply(f"{IMP}/Houses", f"{FAMILY}/Other", plan.fingerprint)
    assert batch_ids(app) == [] and members(app) == {}
    assert (demo.root / IMP / "Houses/late.pdf").is_file()
    assert (demo.root / IMP / "Houses/will.pdf").is_symlink()


def test_apply_runs_under_the_sync_lock(app, demo, monkeypatch):
    real = app.executor.apply

    def checking(plan):
        assert app.ongoing.sync_lock.locked()
        return real(plan)

    monkeypatch.setattr(app.executor, "apply", checking)
    assert convert(app, f"{IMP}/Tax 2025.pdf", None).batch.failed is None


# --- "Star it" in Convert Ongoing ------------------------------------------------------


@pytest.fixture
def ongoing_demo(app, fake_archive):
    fake_archive.add(f"{TAXES}/2025.pdf", drive_id="id-tax")
    folder(fake_archive, f"{FAMILY}/Tilly", "d-tilly")
    fake_archive.add(f"{FAMILY}/Tilly/school.pdf", drive_id="id-school")
    fake_archive.link(f"{ONG}/Tax 2025.pdf", f"{TAXES}/2025.pdf")
    fake_archive.link(f"{ONG}/Tilly", f"{FAMILY}/Tilly")
    fake_archive.add(f"{ONG}/2026_Plan.xlsx", drive_id="id-plan")
    folder(fake_archive, f"{ONG}/Legal", "d-legal")
    fake_archive.add(f"{ONG}/Legal/contract.pdf", drive_id="id-contract")
    app.scan()
    return fake_archive


def test_star_it_for_a_link_and_undo(app, ongoing_demo):
    ong = ongoing_demo.root / ONG
    plan = app.convert.preview(f"{ONG}/Tax 2025.pdf", "", None, star=True)
    assert [(r.kind, r.dst) for r in plan.ops] == [
        ("unlink_symlink", f"{ONG}/Tax 2025.pdf"),
        ("symlink", f"{ONG}/Tax 2025.pdf"),  # "Star it" keeps the shortcut's name
    ]
    assert plan.link_names == ["Tax 2025.pdf"]
    assert (plan.collection, plan.existing, plan.members) == (
        "Ongoing",
        True,
        [f"{TAXES}/2025.pdf"],
    )
    result = app.convert.apply(f"{ONG}/Tax 2025.pdf", "", None, plan.fingerprint, star=True)
    assert result.batch.failed is None and result.problems == []
    assert result.collection_id == starred(app).id
    assert points_at(ong / "Tax 2025.pdf", ongoing_demo, f"{TAXES}/2025.pdf")
    assert app.marks.marks_for(["id-tax"]) == {"id-tax": ["starred"]}
    rec = [r for r in records(app) if r.rel == f"{ONG}/Tax 2025.pdf"]
    assert len(rec) == 1 and rec[0].collection_id == starred(app).id
    assert result.sync.batches == []
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None and outcome.follow_up_error is None
    assert points_at(ong / "Tax 2025.pdf", ongoing_demo, f"{TAXES}/2025.pdf")
    assert "2025_2.pdf" not in listing(ong) and listing(ong).count("Tax 2025.pdf") == 1
    assert app.marks.marks_for(["id-tax"]) == {"id-tax": []}
    assert records(app) == [] and starred(app).ongoing_status is None


def test_star_it_for_a_file_and_undo(app, ongoing_demo):
    ong = ongoing_demo.root / ONG
    plan = app.convert.preview(f"{ONG}/2026_Plan.xlsx", "", FAMILY, star=True)
    assert [(r.kind, r.dst) for r in plan.ops] == [
        ("move", f"{FAMILY}/2026_Plan.xlsx"),
        ("symlink", f"{ONG}/2026_Plan.xlsx"),
    ]
    result = app.convert.apply(f"{ONG}/2026_Plan.xlsx", "", FAMILY, plan.fingerprint, star=True)
    assert result.batch.failed is None and result.problems == []
    assert (ongoing_demo.root / FAMILY / "2026_Plan.xlsx").is_file()
    assert points_at(ong / "2026_Plan.xlsx", ongoing_demo, f"{FAMILY}/2026_Plan.xlsx")
    assert app.marks.marks_for(["id-plan"]) == {"id-plan": ["starred"]}
    # a star link and a project folder share the name space: the project gets _2
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None and outcome.follow_up_error is None
    assert (ong / "2026_Plan.xlsx").is_file() and read_drive_id(ong / "2026_Plan.xlsx") == "id-plan"
    assert app.marks.marks_for(["id-plan"]) == {"id-plan": []}
    assert records(app) == []


def test_star_it_for_a_folder_link(app, ongoing_demo):
    result = app.convert.apply(
        f"{ONG}/Tilly",
        "",
        None,
        app.convert.preview(f"{ONG}/Tilly", "", None, star=True).fingerprint,
        star=True,
    )
    assert result.batch.failed is None
    assert points_at(ongoing_demo.root / ONG / "Tilly", ongoing_demo, f"{FAMILY}/Tilly")
    assert app.marks.marks_for(["d-tilly"]) == {"d-tilly": ["starred"]}


def test_star_it_refuses_a_folder_and_an_already_starred_file(app, ongoing_demo):
    with pytest.raises(InvalidRequest, match="cannot be starred"):
        app.convert.preview(f"{ONG}/Legal", "", FAMILY, star=True)
    app.marks.star(["id-tax"])
    with pytest.raises(InvalidRequest, match="already starred"):
        app.convert.preview(f"{ONG}/Tax 2025.pdf", "", None, star=True)
    with pytest.raises(InvalidRequest, match="needs a name"):
        app.convert.preview(f"{ONG}/Tax 2025.pdf", "", None)
    assert len(batch_ids(app)) == 1  # only the star's own sync batch


def test_star_it_stale_preview_is_refused(app, ongoing_demo):
    plan = app.convert.preview(f"{ONG}/Tax 2025.pdf", "", None, star=True)
    with pytest.raises(StalePreview):
        app.convert.apply(f"{ONG}/Tax 2025.pdf", "Taxes", None, plan.fingerprint)
    with pytest.raises(StalePreview):
        app.convert.apply(f"{ONG}/Tax 2025.pdf", "", None, "stale", star=True)
    assert batch_ids(app) == [] and app.marks.marks_for(["id-tax"]) == {"id-tax": []}


# --- a kept name survives an unmark ----------------------------------------------------


def test_star_it_unstar_star_keeps_the_name_and_undo_works(app, ongoing_demo):
    ong = ongoing_demo.root / ONG
    plan = app.convert.preview(f"{ONG}/Tax 2025.pdf", "", None, star=True)
    result = app.convert.apply(f"{ONG}/Tax 2025.pdf", "", None, plan.fingerprint, star=True)
    app.marks.unstar(["id-tax"])
    assert "Tax 2025.pdf" not in listing(ong)
    app.marks.star(["id-tax"])
    assert points_at(ong / "Tax 2025.pdf", ongoing_demo, f"{TAXES}/2025.pdf")  # its name again
    assert [m.link_name for m in starred(app).members] == ["Tax 2025.pdf"]
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None, outcome.batch.error
    assert points_at(ong / "Tax 2025.pdf", ongoing_demo, f"{TAXES}/2025.pdf")  # the user's
    # the star is the user's own (marked again): it stays, its link beside the user's
    assert app.marks.marks_for(["id-tax"]) == {"id-tax": ["starred"]}
    assert points_at(ong / "Tax 2025_2.pdf", ongoing_demo, f"{TAXES}/2025.pdf")


def test_unmark_and_mark_again_keeps_the_name_and_undo_works(app, demo):
    root = demo.root / IMP
    result = convert(app, f"{IMP}/Tax 2025.pdf", None)
    app.marks.unmark_important(["id-tax"])
    assert "Tax 2025.pdf" not in listing(root)
    app.marks.mark_important(["id-tax"])
    assert points_at(root / "Tax 2025.pdf", demo, f"{TAXES}/2025.pdf")
    app.marks.unmark_important(["id-tax"])
    app.marks.mark_important(["id-tax"], "Later")  # another group: the name still
    assert points_at(root / "Later/Tax 2025.pdf", demo, f"{TAXES}/2025.pdf")
    app.collections.set_group_path(important(app).id, ["id-tax"], None)
    app.marks.unmark_important(["id-tax"])
    app.marks.mark_important(["id-tax"])
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None, outcome.batch.error
    assert points_at(root / "Tax 2025.pdf", demo, f"{TAXES}/2025.pdf")  # the user's
    assert members(app) == {"id-tax": ""}  # marked again by the user: stays
    assert points_at(root / "Tax 2025_2.pdf", demo, f"{TAXES}/2025.pdf")
    # an explicit name on a later add wins over the remembered one
    app.marks.unmark_important(["id-tax"])
    app.collections.add_members(important(app).id, ["id-tax"], link_names={"id-tax": "Tax.pdf"})
    assert points_at(root / "Tax.pdf", demo, f"{TAXES}/2025.pdf")


def test_check_link_name_refuses_separators_and_line_breaks():
    from dam.collections.service import check_link_name

    assert check_link_name("Passport Jess.pdf") == "Passport Jess.pdf"
    for bad in ("a/b", "a\\b", "a\u2028b", "a\u2029b", "a\u200bb", "", ".", ".DS_Store"):
        with pytest.raises(InvalidRequest):
            check_link_name(bad)


# --- API -----------------------------------------------------------------------------


def test_important_routes(client, app, demo):
    entries = client.get("/api/important/entries").json()
    assert {e["rel"]: e["kind"] for e in entries} == {
        f"{IMP}/Houses": "folder",
        f"{IMP}/Tax 2025.pdf": "link",
        f"{IMP}/Tilly": "link",
        f"{IMP}/passport.pdf": "file",
    }
    body = {"rel": f"{IMP}/Houses", "destination": PAPERS}
    plan = post(client, "/api/important/preview", body).json()
    assert plan["collection"] == "Important" and plan["existing"] is True
    assert plan["groups"] == ["Houses/Hillside", "Houses", "Houses/Hillside", "Houses"]
    r = post(client, "/api/important/convert", {**body, "fingerprint": "stale"})
    assert r.status_code == 400 and r.json()["code"] == "stale_preview"
    r = post(client, "/api/important/convert", {**body, "fingerprint": plan["fingerprint"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["collection_id"] == important(app).id and out["problems"] == []
    assert {e["rel"]: e["managed"] for e in client.get("/api/important/entries").json()}[
        f"{IMP}/Houses"
    ] is True
    r = post(client, "/api/important/convert", body)
    assert r.status_code == 422


def test_star_it_route(client, app, ongoing_demo):
    body = {"rel": f"{ONG}/Tax 2025.pdf", "collection": "", "destination": None, "star": True}
    r = post(client, "/api/ongoing/preview", {**body, "star": False})
    assert r.status_code == 400 and "needs a name" in r.json()["error"]
    plan = post(client, "/api/ongoing/preview", body).json()
    assert plan["collection"] == "Ongoing" and plan["members"] == [f"{TAXES}/2025.pdf"]
    r = post(client, "/api/ongoing/convert", {**body, "fingerprint": plan["fingerprint"]})
    assert r.status_code == 200, r.text
    assert r.json()["collection_id"] == starred(app).id
    assert client.get("/api/files/id-tax").json()["record"]["marks"] == ["starred"]


# --- marks on the convert screens, Activity and Today (stars, Task 4) ---------------


def test_entries_and_items_carry_marks(client, app, demo):
    app.marks.star(["id-tax", "id-notes"])
    app.marks.mark_important(["id-survey"], None)
    entries = {e["rel"]: e for e in client.get("/api/important/entries").json()}
    assert entries[f"{IMP}/Tax 2025.pdf"]["marks"] == ["starred"]
    assert entries[f"{IMP}/passport.pdf"]["marks"] == []
    houses = {i["name"]: i["marks"] for i in entries[f"{IMP}/Houses"]["items"]}
    assert houses["notes.pdf"] == ["starred"]
    assert houses["will.pdf"] == []


def test_ongoing_entries_carry_marks(client, app, ongoing_demo):
    app.marks.star(["id-plan"])
    entries = {e["rel"]: e for e in client.get("/api/ongoing/entries").json()}
    assert entries[f"{ONG}/2026_Plan.xlsx"]["marks"] == ["starred"]
    assert entries[f"{ONG}/Tax 2025.pdf"]["marks"] == []
    assert all(i["marks"] == [] for i in entries[f"{ONG}/Legal"]["items"])


def test_activity_ops_carry_marks_in_one_query(client, app, demo):
    from test_marks import counted, mark_queries

    plan = app.convert_important.preview(f"{IMP}/Houses", PAPERS)
    app.convert_important.apply(f"{IMP}/Houses", PAPERS, plan.fingerprint)
    with counted(app.engine) as seen:
        batches = client.get("/api/activity").json()
    assert len(mark_queries(seen)) == 1
    ops = [op for b in batches for op in b["ops"]]
    moved = [op for op in ops if op["drive_id"] == "id-notes"]
    assert moved and all(op["marks"] == ["important"] for op in moved)
    assert all("marks" in op for op in ops)


def test_today_counts_unmanaged_important(client, app, demo):
    assert client.get("/api/today").json()["unmanaged_important"] == 4
    plan = app.convert_important.preview(f"{IMP}/Houses", PAPERS)
    app.convert_important.apply(f"{IMP}/Houses", PAPERS, plan.fingerprint)
    assert client.get("/api/today").json()["unmanaged_important"] == 3


def test_today_unmanaged_important_is_zero_without_the_folder(client, app, fake_archive):
    app.scan()
    assert client.get("/api/today").json()["unmanaged_important"] == 0


def test_builtin_collection_route(client, app, demo):
    app.marks.star(["id-tax"])
    app.marks.mark_important(["id-deed"], "Houses/Hillside")
    star = client.get("/api/marks/collection/starred").json()
    assert (star["kind"], star["name"]) == ("starred", "Ongoing")
    assert [(m["drive_id"], m["marks"]) for m in star["members"]] == [("id-tax", ["starred"])]
    imp = client.get("/api/marks/collection/important").json()
    assert imp["kind"] == "important" and [g["name"] for g in imp["groups"]] == [
        "Houses",
        "Hillside",
    ]
    assert imp["members"][0]["marks"] == ["important"]
    assert client.get("/api/marks/collection/other").status_code == 422


# --- folders holding no real files need no destination ---------------------------------


@pytest.fixture
def shortcuts_only(app, demo):
    """``Cottages``: subfolders full of shortcuts and no real file."""
    folder(demo, f"{IMP}/Cottages", "d-cottages")
    folder(demo, f"{IMP}/Cottages/Lahti", "d-lahti")
    demo.link(f"{IMP}/Cottages/Lahti/will.pdf", f"{FAMILY}/will.pdf")
    demo.link(f"{IMP}/Cottages/2025.pdf", f"{TAXES}/2025.pdf")
    app.scan()
    return demo


def test_entries_count_the_real_files_below(app, shortcuts_only):
    counts = {e.rel: e.real_files for e in app.convert_important.entries()}
    assert counts[f"{IMP}/Cottages"] == 0
    assert counts[f"{IMP}/Houses"] > 0


def test_a_folder_without_real_files_converts_with_no_destination(app, shortcuts_only):
    link = shortcuts_only.root / IMP / "Cottages" / "Lahti" / "will.pdf"
    plan = app.convert_important.preview(f"{IMP}/Cottages", None)
    assert not [r for r in plan.ops if r.kind == "move"]
    result = app.convert_important.apply(f"{IMP}/Cottages", None, plan.fingerprint)
    assert result.batch.failed is None
    assert {"id-will", "id-tax"} <= set(members(app))
    outcome = app.activity.undo(result.batch.batch_id)
    assert outcome.batch.failed is None
    assert points_at(link, shortcuts_only, f"{FAMILY}/will.pdf")


def test_a_folder_with_real_files_still_needs_a_destination(app, demo):
    with pytest.raises(InvalidRequest, match="Choose the archive folder"):
        app.convert_important.preview(f"{IMP}/Houses", None)
