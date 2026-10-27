"""Unused rule pictures moved from config/rules/areas into the quarantine folder through the
operation layer: planned, previewed, journaled and undone; never a delete."""

import hashlib
import sys

import pytest
from sqlalchemy import select, update

from dam.db.tables import operations
from dam.errors import InvalidRequest
from dam.ops import primitives
from dam.ops.model import GuardError, Op, OpFailed, OpKind, Plan
from dam.rules.model import Rule
from test_api import LOCAL_ORIGIN, make_client, post

QUARANTINE = "##. To Delete"
PNG = b"\x89PNG\r\n\x1a\n-test-bytes"
HASH = hashlib.sha256(PNG).hexdigest()


@pytest.fixture
def areas(app):
    folder = app.rules_dir / "areas"
    folder.mkdir(parents=True)
    return folder


def quarantine(fake_archive):
    return fake_archive.root / QUARANTINE


def put(areas, name, data=PNG):
    path = areas / name
    path.write_bytes(data)
    return path


def use(app, image):
    """Load a rule whose picture area uses ``image`` (areas/<name>.png)."""
    app.rules = [
        Rule.model_validate(
            {
                "id": "acme",
                "when": {"zones": [{"box": [0.1, 0.1, 0.3, 0.2], "image": image}]},
                "then": {"folder": "10. Financial"},
            }
        )
    ]


def rows(app):
    with app.engine.connect() as conn:
        return [
            dict(r) for r in conn.execute(select(operations).order_by(operations.c.id)).mappings()
        ]


def move(app, names, dry_run=False):
    return app.area_pictures.quarantine_unused(names, lambda: app.rules, "ui", dry_run=dry_run)


def test_dry_run_plans_the_move_and_changes_nothing(app, areas, fake_archive):
    put(areas, "old-1.png")
    result = move(app, ["old-1.png"], dry_run=True)
    assert result.dry_run and result.error is None
    kinds = [(op.kind, op.dst) for op in result.done]
    assert kinds == [
        (OpKind.PICTURE_TO_QUARANTINE, f"{QUARANTINE}/dam rule picture old-1.png"),
    ]
    assert (areas / "old-1.png").exists()
    assert not list(quarantine(fake_archive).iterdir())
    assert rows(app) == []


def test_a_missing_quarantine_folder_is_made_first(app, areas, fake_archive):
    put(areas, "old-1.png")
    folder = fake_archive.root / QUARANTINE
    folder.rmdir()  # test-only: the empty folder of the fake archive
    plan = move(app, ["old-1.png"], dry_run=True)
    assert [op.kind for op in plan.done] == [OpKind.MKDIR, OpKind.PICTURE_TO_QUARANTINE]
    assert move(app, ["old-1.png"]).error is None
    assert (folder / "dam rule picture old-1.png").read_bytes() == PNG


def test_apply_moves_the_file_journals_it_and_names_it_recognisably(app, areas, fake_archive):
    put(areas, "old-1.png")
    put(areas, "old-2.png", b"other")
    result = move(app, ["old-1.png", "old-2.png"])
    assert result.error is None and result.failed is None
    quarantine = fake_archive.root / QUARANTINE
    assert (quarantine / "dam rule picture old-1.png").read_bytes() == PNG
    assert (quarantine / "dam rule picture old-2.png").read_bytes() == b"other"
    assert not (areas / "old-1.png").exists() and not (areas / "old-2.png").exists()
    moved = [r for r in rows(app) if r["kind"] == "picture_to_quarantine"]
    assert [(r["src"], r["dst"], r["state"], r["origin"]) for r in moved] == [
        ("old-1.png", f"{QUARANTINE}/dam rule picture old-1.png", "done", "ui"),
        ("old-2.png", f"{QUARANTINE}/dam rule picture old-2.png", "done", "ui"),
    ]
    assert moved[0]["label"] == "Moved 2 unused rule pictures to To Delete"
    assert moved[0]["size"] == len(PNG)
    assert app.area_pictures.unused(app.rules) == []


def test_a_picture_a_rule_uses_is_refused_and_nothing_moves(app, areas, fake_archive):
    put(areas, "used-1.png")
    put(areas, "old-1.png")
    use(app, "areas/used-1.png")
    for dry in (True, False):
        with pytest.raises(InvalidRequest, match="used-1.png"):
            move(app, ["old-1.png", "used-1.png"], dry_run=dry)
    assert (areas / "used-1.png").exists() and (areas / "old-1.png").exists()
    assert not list(quarantine(fake_archive).iterdir())
    assert rows(app) == []


def test_nothing_picked_or_a_file_that_is_not_there_is_refused(app, areas):
    with pytest.raises(InvalidRequest):
        move(app, [])
    with pytest.raises(InvalidRequest):
        move(app, ["ghost.png"])
    with pytest.raises(InvalidRequest):
        move(app, ["../escape.png"])


def test_a_taken_name_in_the_quarantine_folder_gets_a_suffix_and_nothing_is_overwritten(
    app, areas, fake_archive
):
    existing = fake_archive.add(f"{QUARANTINE}/dam rule picture old-1.png", b"keep me")
    put(areas, "old-1.png")
    result = move(app, ["old-1.png"])
    assert result.error is None
    assert existing.read_bytes() == b"keep me"
    assert (fake_archive.root / QUARANTINE / "dam rule picture old-1_2.png").read_bytes() == PNG
    note = [op.note for op in result.done if op.kind is OpKind.PICTURE_TO_QUARANTINE]
    assert note == ["renamed to avoid collision"]


@pytest.mark.skipif(sys.platform == "win32", reason="needs symbolic links")
def test_a_symlinked_picture_is_refused(app, areas, fake_archive, tmp_path):
    outside = tmp_path / "outside.png"
    outside.write_bytes(PNG)
    (areas / "link.png").symlink_to(outside)
    with pytest.raises(GuardError, match="not a plain file"):
        move(app, ["link.png"])
    assert (areas / "link.png").is_symlink() and outside.exists()
    assert not list(quarantine(fake_archive).iterdir())


@pytest.mark.skipif(sys.platform == "win32", reason="needs symbolic links")
def test_a_symlinked_areas_folder_is_refused(app, tmp_path, fake_archive):
    real = tmp_path / "elsewhere"
    real.mkdir()
    (real / "old-1.png").write_bytes(PNG)
    app.rules_dir.mkdir(parents=True, exist_ok=True)
    (app.rules_dir / "areas").symlink_to(real, target_is_directory=True)
    with pytest.raises(GuardError, match="not a real folder"):
        move(app, ["old-1.png"])
    assert (real / "old-1.png").exists()


def test_the_guard_takes_only_the_areas_folder_and_the_quarantine_folder(app, areas, tmp_path):
    ex = app.executor
    stray = tmp_path / "stray.png"
    stray.write_bytes(PNG)
    sub = areas / "sub"
    sub.mkdir()
    (sub / "deep.png").write_bytes(PNG)
    put(areas, "ok.png")
    name = "dam rule picture x.png"

    def plan(src, dst=QUARANTINE, **kw):
        return Plan([Op(OpKind.PICTURE_TO_QUARANTINE, f"abs:{src}", dst, name=name, **kw)], "ui")

    with pytest.raises(GuardError, match="areas folder"):
        ex.preview(plan(stray))  # outside the areas folder
    with pytest.raises(GuardError, match="areas folder"):
        ex.preview(plan(sub / "deep.png"))  # not directly inside it
    with pytest.raises(GuardError, match="only moved into"):
        ex.preview(plan(areas / "ok.png", dst="10. Financial"))  # not the quarantine folder
    with pytest.raises(GuardError, match="picture file"):
        ex.preview(
            Plan(
                [
                    Op(
                        OpKind.PICTURE_TO_QUARANTINE,
                        f"abs:{areas / 'ok.png'}",
                        QUARANTINE,
                        name="x.pdf",
                    )
                ],
                "ui",
            )
        )
    with pytest.raises(GuardError):
        ex.preview(plan(areas / "ok.png", exact=True))
    with pytest.raises(GuardError, match="not known"):
        type(ex)(ex.paths, ex.engine, ex.repo).preview(plan(areas / "ok.png"))
    assert (areas / "ok.png").exists() and stray.exists()


def test_putting_a_picture_back_is_for_undo_only(app, areas, fake_archive):
    fake_archive.add(f"{QUARANTINE}/dam rule picture a.png", PNG)
    op = Op(OpKind.PICTURE_BACK, f"{QUARANTINE}/dam rule picture a.png", "a.png", exact=True)
    with pytest.raises(GuardError, match="Only an undo"):
        app.executor.preview(Plan([op], "ui"))
    with pytest.raises(GuardError):
        app.executor.apply(Plan([op], "ui"))
    assert (fake_archive.root / QUARANTINE / "dam rule picture a.png").exists()


def test_a_rename_across_disks_that_fails_at_act_time_leaves_the_file(
    app, areas, fake_archive, monkeypatch
):
    import errno

    from dam.ops import primitives

    put(areas, "old-1.png")

    def refuse(src, dst):
        raise OSError(errno.EXDEV, "cross-device")

    monkeypatch.setattr(primitives, "rename_excl", refuse)
    result = move(app, ["old-1.png"])
    assert result.failed is not None and "different disks" in result.error
    assert (areas / "old-1.png").read_bytes() == PNG
    assert [r["state"] for r in rows(app) if r["kind"] == "picture_to_quarantine"] == ["failed"]


def test_the_journal_records_a_rename_and_the_content_hash(app, areas, fake_archive):
    put(areas, "old-1.png")
    move(app, ["old-1.png"])
    (row,) = [r for r in rows(app) if r["kind"] == "picture_to_quarantine"]
    assert (row["method"], row["content_hash"]) == ("rename", HASH)


# --- across disks (simulated: the same-disk check says no) ---------------------------------


@pytest.fixture
def two_disks(monkeypatch):
    monkeypatch.setattr(primitives, "same_disk", lambda a, b: False)


def copied(archive, name="old-1.png"):
    return archive.root / QUARANTINE / f"dam rule picture {name}"


def test_across_disks_the_preview_says_copied_then_removed_and_changes_nothing(
    app, areas, fake_archive, two_disks
):
    put(areas, "old-1.png")
    result = move(app, ["old-1.png"], dry_run=True)
    assert result.error is None
    assert [op.note for op in result.done] == ["copied, then removed from dam's settings folder"]
    assert (areas / "old-1.png").exists() and not list(quarantine(fake_archive).iterdir())
    assert rows(app) == []


def test_across_disks_the_picture_is_copied_verified_and_then_removed(
    app, areas, fake_archive, two_disks
):
    put(areas, "old-1.png")
    result = move(app, ["old-1.png"])
    assert result.error is None and result.failed is None
    assert copied(fake_archive).read_bytes() == PNG
    assert not (areas / "old-1.png").exists()
    (row,) = [r for r in rows(app) if r["kind"] == "picture_to_quarantine"]
    assert (row["state"], row["method"], row["content_hash"]) == ("done", "copy", HASH)


def test_across_disks_a_taken_name_gets_a_suffix_and_nothing_is_overwritten(
    app, areas, fake_archive, two_disks
):
    existing = fake_archive.add(f"{QUARANTINE}/dam rule picture old-1.png", b"keep me")
    put(areas, "old-1.png")
    assert move(app, ["old-1.png"]).error is None
    assert existing.read_bytes() == b"keep me"
    assert copied(fake_archive, "old-1_2.png").read_bytes() == PNG


def test_a_copy_that_does_not_verify_leaves_both_files(
    app, areas, fake_archive, two_disks, monkeypatch
):
    real = primitives.copy_file

    def bad_copy(src, dst, *a, **kw):
        real(src, dst, *a, **kw)
        dst.write_bytes(b"corrupted on the way")  # test-only: a bad copy
        return len(PNG)

    monkeypatch.setattr(primitives, "copy_file", bad_copy)
    put(areas, "old-1.png")
    result = move(app, ["old-1.png"])
    assert result.failed is not None and "does not match" in result.error
    assert "remove the copy yourself" in result.error
    assert (areas / "old-1.png").read_bytes() == PNG
    assert copied(fake_archive).read_bytes() == b"corrupted on the way"
    assert [r["state"] for r in rows(app) if r["kind"] == "picture_to_quarantine"] == ["failed"]


def test_a_copy_that_stops_part_way_leaves_both_files(
    app, areas, fake_archive, two_disks, monkeypatch
):
    def broken(src, dst, *a, **kw):
        dst.write_bytes(b"\x89PNG")  # test-only: a cut-short copy
        raise OpFailed("The copy stopped part way")

    monkeypatch.setattr(primitives, "copy_file", broken)
    put(areas, "old-1.png")
    result = move(app, ["old-1.png"])
    assert "part way" in result.error and "original stays" in result.error
    assert (areas / "old-1.png").read_bytes() == PNG and copied(fake_archive).exists()


def test_a_source_that_changed_since_the_plan_is_not_copied(
    app, areas, fake_archive, two_disks, monkeypatch
):
    put(areas, "old-1.png")
    real = primitives.file_sha256
    calls = []

    def changing(path, stop=None):
        calls.append(path)
        if len(calls) == 2:  # after the journal snapshot, before the copy
            path.write_bytes(b"edited meanwhile")
        return real(path, stop)

    monkeypatch.setattr(primitives, "file_sha256", changing)
    result = move(app, ["old-1.png"])
    assert result.failed is not None and "changed since" in result.error
    assert (areas / "old-1.png").read_bytes() == b"edited meanwhile"
    assert not copied(fake_archive).exists()


def test_a_failed_removal_after_a_verified_copy_keeps_both_and_says_so(
    app, areas, fake_archive, two_disks, monkeypatch
):
    def refuse(*a, **kw):
        raise OSError("read-only")

    monkeypatch.setattr(primitives, "remove_moved_picture", refuse)
    put(areas, "old-1.png")
    result = move(app, ["old-1.png"])
    assert "Both files exist" in result.error and "was not removed" in result.error
    assert (areas / "old-1.png").read_bytes() == PNG and copied(fake_archive).read_bytes() == PNG
    assert [r["state"] for r in rows(app) if r["kind"] == "picture_to_quarantine"] == ["failed"]


def test_the_removal_refuses_a_hash_mismatch_and_anything_but_a_plain_file_in_the_folder(
    app, areas, fake_archive, tmp_path
):
    source = put(areas, "old-1.png")
    copy = tmp_path / "copy.png"
    copy.write_bytes(PNG)
    with pytest.raises(GuardError, match="not the same content"):
        primitives.remove_moved_picture(source, areas, copy, "0" * 64)  # wrong hash
    copy.write_bytes(b"different")
    with pytest.raises(GuardError, match="not the same content"):
        primitives.remove_moved_picture(source, areas, copy, HASH)  # the copy differs
    copy.write_bytes(PNG)
    outside = tmp_path / "stray.png"
    outside.write_bytes(PNG)
    with pytest.raises(GuardError, match="not directly inside"):
        primitives.remove_moved_picture(outside, areas, copy, HASH)
    sub = areas / "sub"
    sub.mkdir()
    (sub / "deep.png").write_bytes(PNG)
    with pytest.raises(GuardError, match="not directly inside"):
        primitives.remove_moved_picture(sub / "deep.png", areas, copy, HASH)
    with pytest.raises(GuardError, match="same file"):
        primitives.remove_moved_picture(source, areas, source, HASH)
    assert source.exists() and outside.exists() and (sub / "deep.png").exists() and copy.exists()
    primitives.remove_moved_picture(source, areas, copy, HASH)
    assert not source.exists() and copy.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="needs symbolic links")
def test_the_removal_refuses_a_link_and_a_linked_folder(app, areas, tmp_path):
    copy = tmp_path / "copy.png"
    copy.write_bytes(PNG)
    target = tmp_path / "target.png"
    target.write_bytes(PNG)
    (areas / "link.png").symlink_to(target)
    with pytest.raises(GuardError, match="plain files"):
        primitives.remove_moved_picture(areas / "link.png", areas, copy, HASH)
    real = tmp_path / "real"
    real.mkdir()
    (real / "a.png").write_bytes(PNG)
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(GuardError):
        primitives.remove_moved_picture(linked / "a.png", linked, copy, HASH)
    assert target.exists() and (real / "a.png").exists()


# --- undo ---------------------------------------------------------------------------------


def test_undo_puts_the_picture_back_and_marks_the_batch_undone(app, areas, fake_archive):
    put(areas, "old-1.png")
    batch = move(app, ["old-1.png"]).batch_id
    preview = app.activity.preview_undo(batch)
    assert [(op.kind, op.src) for op in preview] == [
        (OpKind.PICTURE_BACK, f"{QUARANTINE}/dam rule picture old-1.png")
    ]
    outcome = app.activity.undo(batch)
    assert outcome.batch.error is None and outcome.batch.failed is None
    assert (areas / "old-1.png").read_bytes() == PNG
    assert not (fake_archive.root / QUARANTINE / "dam rule picture old-1.png").exists()
    states = {r["kind"]: r["state"] for r in rows(app) if r["batch_id"] == batch}
    assert states["picture_to_quarantine"] == "undone"
    back = [r for r in rows(app) if r["kind"] == "picture_back"]
    assert [(r["dst"], r["state"], r["undo_of"]) for r in back] == [("old-1.png", "done", batch)]
    assert app.area_pictures.unused(app.rules) == ["old-1.png"]


def test_undo_refuses_when_the_name_in_the_areas_folder_is_taken(app, areas, fake_archive):
    put(areas, "old-1.png")
    batch = move(app, ["old-1.png"]).batch_id
    put(areas, "old-1.png", b"a newer picture")
    with pytest.raises(GuardError, match="already in the rules' areas folder"):
        app.activity.preview_undo(batch)
    with pytest.raises(GuardError, match="already in the rules' areas folder"):
        app.activity.undo(batch)
    assert (areas / "old-1.png").read_bytes() == b"a newer picture"
    assert (fake_archive.root / QUARANTINE / "dam rule picture old-1.png").read_bytes() == PNG


def test_undo_refuses_when_the_moved_file_has_changed_or_is_gone(app, areas, fake_archive):
    put(areas, "old-1.png")
    put(areas, "old-2.png")
    batch = move(app, ["old-1.png", "old-2.png"]).batch_id
    moved = fake_archive.root / QUARANTINE / "dam rule picture old-1.png"
    moved.write_bytes(b"edited later")
    with pytest.raises(Exception, match="changed since"):
        app.activity.undo(batch)
    assert not (areas / "old-1.png").exists() and not (areas / "old-2.png").exists()


def test_undo_refuses_a_missing_areas_folder(app, areas, fake_archive):
    put(areas, "old-1.png")
    batch = move(app, ["old-1.png"]).batch_id
    areas.rmdir()  # a test-only removal of the emptied temporary folder
    with pytest.raises(GuardError, match="picture folder is gone"):
        app.activity.preview_undo(batch)


# --- API ----------------------------------------------------------------------------------


def test_api_plan_then_apply_then_undo(app, areas, fake_archive):
    put(areas, "old-1.png")
    put(areas, "used-1.png")
    use(app, "areas/used-1.png")
    url = "/api/rules/unused-pictures/quarantine"
    with make_client(app) as c:
        listed = c.get("/api/rules").json()["unused_pictures"]
        assert listed == ["old-1.png"]
        dry = post(c, url, {"names": listed, "dry_run": True})
        assert dry.status_code == 200 and dry.json()["dry_run"] is True
        assert [op["kind"] for op in dry.json()["done"]] == ["picture_to_quarantine"]
        assert (areas / "old-1.png").exists()
        refused = post(c, url, {"names": ["used-1.png"]})
        assert refused.status_code == 400 and "used-1.png" in refused.json()["error"]
        done = post(c, url, {"names": listed})
        assert done.status_code == 200 and done.json()["error"] is None
        assert not (areas / "old-1.png").exists()
        assert c.get("/api/rules").json()["unused_pictures"] == []
        batch = done.json()["batch_id"]
        undo = post(c, f"/api/activity/{batch}/undo/preview", {})
        assert undo.status_code == 200 and undo.json()[0]["kind"] == "picture_back"
        assert post(c, f"/api/activity/{batch}/undo", {}).status_code == 200
        assert (areas / "old-1.png").read_bytes() == PNG
        taken = post(c, url, {"names": listed})
        assert taken.status_code == 200
        put(areas, "old-1.png", b"new")
        blocked = post(c, f"/api/activity/{taken.json()['batch_id']}/undo", {})
        assert blocked.status_code == 400
        assert "already in the rules' areas folder" in blocked.json()["error"]


def test_api_needs_the_local_origin_like_other_posts(app, areas):
    with make_client(app) as c:
        r = c.post("/api/rules/unused-pictures/quarantine", json={"names": ["a.png"]})
    assert r.status_code == 403
    assert LOCAL_ORIGIN


# --- crash recovery -----------------------------------------------------------------------


def _planned(app, batch):
    with app.engine.begin() as conn:
        conn.execute(
            update(operations).where(operations.c.batch_id == batch).values(state="planned")
        )


def test_recovery_settles_an_interrupted_move_from_the_disk(app, areas, fake_archive):
    put(areas, "old-1.png")
    batch = move(app, ["old-1.png"]).batch_id
    _planned(app, batch)  # as if the process stopped after the rename
    result = app.executor.recover()
    assert [(e.state, e.error) for e in result.entries] == [("done", None)]


def test_recovery_sees_a_move_that_never_happened(app, areas, fake_archive):
    put(areas, "old-1.png")
    batch = move(app, ["old-1.png"]).batch_id
    app.activity.undo(batch)  # the file is back in areas, as before the move
    with app.engine.begin() as conn:
        conn.execute(
            update(operations)
            .where(operations.c.batch_id == batch)
            .values(state="planned", undo_of=None)
        )
    result = app.executor.recover()
    assert [(e.state, e.error) for e in result.entries if e.batch_id == batch] == [
        ("failed", "interrupted before execution")
    ]


# --- across disks: undo and recovery ------------------------------------------------------


def test_undo_across_disks_copies_back_and_leaves_the_copy_in_to_delete(
    app, areas, fake_archive, two_disks
):
    put(areas, "old-1.png")
    batch = move(app, ["old-1.png"]).batch_id
    preview = app.activity.preview_undo(batch)
    assert [op.note for op in preview] == ["copied back; the copy in To Delete stays"]
    outcome = app.activity.undo(batch)
    assert outcome.batch.error is None and outcome.batch.failed is None
    assert [op.note for op in outcome.batch.done] == ["copied back; the copy in To Delete stays"]
    assert (areas / "old-1.png").read_bytes() == PNG
    assert copied(fake_archive).read_bytes() == PNG  # an undo never removes an archive file
    by_kind = {r["kind"]: r for r in rows(app)}
    assert by_kind["picture_to_quarantine"]["state"] == "undone"
    assert (by_kind["picture_back"]["method"], by_kind["picture_back"]["content_hash"]) == (
        "copy",
        HASH,
    )
    assert app.area_pictures.unused(app.rules) == ["old-1.png"]


def test_undo_across_disks_refuses_a_taken_name_and_an_edited_copy(
    app, areas, fake_archive, two_disks
):
    put(areas, "old-1.png")
    batch = move(app, ["old-1.png"]).batch_id
    put(areas, "old-1.png", b"a newer picture")
    with pytest.raises(GuardError, match="already in the rules' areas folder"):
        app.activity.undo(batch)
    assert (areas / "old-1.png").read_bytes() == b"a newer picture"
    (areas / "old-1.png").rename(areas / "other.png")  # test-only: free the name again
    copied(fake_archive).write_bytes(PNG[:-1] + b"!")  # same size, different content
    with pytest.raises(OpFailed, match="changed since"):
        app.activity.undo(batch)
    assert not (areas / "old-1.png").exists()


def _after_a_move(app, areas, fake_archive):
    put(areas, "old-1.png")
    batch = move(app, ["old-1.png"]).batch_id
    return batch


def test_recovery_finishes_a_copy_by_removing_the_source_when_the_copy_verifies(
    app, areas, fake_archive, two_disks
):
    batch = _after_a_move(app, areas, fake_archive)
    put(areas, "old-1.png")  # as if the process stopped before the source was removed
    _planned(app, batch)
    result = app.executor.recover()
    assert [(e.state, e.error) for e in result.entries] == [("done", None)]
    assert not (areas / "old-1.png").exists()
    assert copied(fake_archive).read_bytes() == PNG


def test_recovery_leaves_both_when_the_copy_is_partial_or_the_source_differs(
    app, areas, fake_archive, two_disks
):
    batch = _after_a_move(app, areas, fake_archive)
    copied(fake_archive).write_bytes(PNG[:6])  # test-only: a cut-short copy
    put(areas, "old-1.png")
    _planned(app, batch)
    result = app.executor.recover()
    assert [e.state for e in result.entries] == ["failed"]
    assert (areas / "old-1.png").read_bytes() == PNG
    assert copied(fake_archive).read_bytes() == PNG[:6]


def test_recovery_does_not_remove_a_source_that_differs_from_the_verified_copy(
    app, areas, fake_archive, two_disks
):
    batch = _after_a_move(app, areas, fake_archive)
    put(areas, "old-1.png", b"a newer picture of the same name")
    _planned(app, batch)
    result = app.executor.recover()
    assert [e.state for e in result.entries] == ["failed"]
    assert (areas / "old-1.png").read_bytes() == b"a newer picture of the same name"
    assert copied(fake_archive).read_bytes() == PNG


def test_recovery_sees_a_copy_that_never_started_and_one_that_is_complete(
    app, areas, fake_archive, two_disks
):
    batch = _after_a_move(app, areas, fake_archive)
    _planned(app, batch)  # copy verified and source gone: the move did happen
    assert [e.state for e in app.executor.recover().entries] == ["done"]

    put(areas, "old-2.png")
    batch = move(app, ["old-2.png"]).batch_id
    copied(fake_archive, "old-2.png").unlink()  # test-only: the copy never happened
    put(areas, "old-2.png")
    _planned(app, batch)
    entries = [e for e in app.executor.recover().entries if e.batch_id == batch]
    assert [(e.state, e.error) for e in entries] == [("failed", "interrupted before execution")]
    assert (areas / "old-2.png").exists()


def test_recovery_of_a_copy_back_never_removes_the_archive_file(
    app, areas, fake_archive, two_disks
):
    batch = _after_a_move(app, areas, fake_archive)
    app.activity.undo(batch)
    with app.engine.begin() as conn:
        conn.execute(
            update(operations).where(operations.c.kind == "picture_back").values(state="planned")
        )
    entries = [e for e in app.executor.recover().entries if e.kind == "picture_back"]
    assert [e.state for e in entries] == ["done"]
    assert copied(fake_archive).exists() and (areas / "old-1.png").exists()
