"""Moving a whole folder in Browse on one disk: plan, apply, undo, refusals, identity."""

import shutil

import pytest

from dam.ops.model import GuardError, OpKind
from dam.ops.planner import COLLISION_NOTE
from dam.services import check_disk_identity
from dam.services.errors import InvalidRequest

HOME = "20. Home"
MISC = "80. Misc"
FOLDER = f"{HOME}/2009"
INBOX = "##. Organize"
ONG = "##. Ongoing"
IMP = "##. Important"
QUAR = "##. To Delete"


@pytest.fixture
def tree(app, fake_archive):
    fake_archive.add(f"{FOLDER}/a.pdf", b"a", drive_id="id-a")
    fake_archive.add(f"{FOLDER}/sub/b.pdf", b"b", drive_id="id-b")
    fake_archive.add(f"{MISC}/keep.pdf", b"k", drive_id="id-k")
    fake_archive.add(f"{ONG}/x/y.pdf", b"y", drive_id="id-y")
    app.scan()
    return app


def fid(app, rel: str) -> str:
    rec = app.repo.by_path(rel)
    assert rec is not None and rec.is_dir, rel
    return rec.drive_id


def test_moves_a_folder_on_one_disk(tree, fake_archive):
    app = tree
    folder_id = fid(app, FOLDER)
    app.tags.add("id-a", ["bank"])
    col = app.collections.create("Years")
    app.collections.add_members(col.id, [folder_id])
    result = app.browse.move([folder_id], MISC)
    assert result.failed is None and result.error is None
    assert (fake_archive.root / MISC / "2009" / "sub" / "b.pdf").read_bytes() == b"b"
    assert not (fake_archive.root / FOLDER).exists()
    assert app.repo.get(folder_id).path == f"{MISC}/2009"
    assert app.repo.get("id-b").path == f"{MISC}/2009/sub/b.pdf"
    assert app.tags.for_file("id-a") == ["bank"]
    assert [c.name for c in app.collections.for_file(folder_id)] == ["Years"]
    assert app.activity.get(result.batch_id).label == "Moved folder 2009 to 80. Misc"


def test_undo_puts_the_folder_back(tree, fake_archive):
    app = tree
    folder_id = fid(app, FOLDER)
    result = app.browse.move([folder_id], MISC)
    outcome = app.activity.undo(result.batch_id)
    assert outcome.batch.failed is None and outcome.batch.error is None
    assert (fake_archive.root / FOLDER / "sub" / "b.pdf").exists()
    assert not (fake_archive.root / MISC / "2009").exists()
    assert app.repo.get(folder_id).path == FOLDER
    assert app.repo.get("id-a").path == f"{FOLDER}/a.pdf"


def test_taken_name_gets_suffix(tree, fake_archive):
    app = tree
    fake_archive.add(f"{MISC}/2009/other.pdf", b"o", drive_id="id-o")
    app.scan()
    folder_id = fid(app, FOLDER)
    preview = app.browse.move_preview([folder_id], MISC)
    moves = [op for op in preview if op.kind == OpKind.MOVE]
    assert len(moves) == 1 and moves[0].note == COLLISION_NOTE
    result = app.browse.move([folder_id], MISC)
    assert result.failed is None, result.error
    assert (fake_archive.root / MISC / "2009_2" / "a.pdf").exists()
    assert app.repo.get(folder_id).path == f"{MISC}/2009_2"


@pytest.mark.parametrize(
    ("ids", "dest", "message"),
    [
        (["EXTRA"], MISC, None),
        (["ONG"], MISC, None),
        (["IMP"], MISC, None),
        (["QUAR"], MISC, None),
        (["INBOX"], MISC, None),
        (["INONG"], MISC, None),
        (["FOLDER"], FOLDER, None),
        (["FOLDER"], f"{FOLDER}/sub", None),
        (["FOLDER", "id-k"], HOME, "Move one folder at a time, without files"),
        (["FOLDER", "SUB"], MISC, "Move one folder at a time, without files"),
    ],
)
def test_refusals(extra_folder, tree, fake_archive, ids, dest, message):
    app = tree
    special = {
        "EXTRA": "Old years",
        "ONG": ONG,
        "IMP": IMP,
        "QUAR": QUAR,
        "INBOX": INBOX,
        "INONG": f"{ONG}/x",
        "FOLDER": FOLDER,
        "SUB": f"{FOLDER}/sub",
    }
    real = [fid(app, special[i]) if i in special else i for i in ids]
    with pytest.raises(InvalidRequest, match=message or "cannot be moved|keeps|itself"):
        app.browse.move(real, dest)


def test_a_folder_in_to_delete_is_refused(tree, fake_archive):
    app = tree
    fake_archive.add(f"{QUAR}/old/z.pdf", b"z", drive_id="id-z")
    app.scan()
    with pytest.raises(InvalidRequest):
        app.browse.move([fid(app, f"{QUAR}/old")], MISC)


@pytest.mark.parametrize("mode", ["link", "copy"])
def test_link_and_copy_refuse_folders(tree, mode):
    app = tree
    with pytest.raises(InvalidRequest, match="Folders can only be moved"):
        app.browse.move([fid(app, FOLDER)], MISC, mode=mode)


def test_locked_file_inside_refuses(tree):
    app = tree
    app.locks.lock("id-b")
    with pytest.raises(GuardError, match="locked"):
        app.browse.move([fid(app, FOLDER)], MISC)


def test_identity_folder_replaced(tree, fake_archive):
    app = tree
    ids = [fid(app, FOLDER)]
    plan = app.browse._move_ops(ids, MISC, "ui").plan
    resolved = app.executor.preview(plan)
    check_disk_identity(app.executor.paths, app.repo, ids, resolved)  # a folder is fine
    shutil.rmtree(fake_archive.root / FOLDER)
    (fake_archive.root / FOLDER).write_bytes(b"now a file")
    with pytest.raises(InvalidRequest, match="scan and try again"):
        check_disk_identity(app.executor.paths, app.repo, ids, resolved)


def test_identity_folder_with_changed_drive_id(tree, fake_archive):
    import xattr

    from dam.index.driveid import DRIVE_ID_XATTR

    app = tree
    folder = fake_archive.root / FOLDER
    xattr.setxattr(folder, DRIVE_ID_XATTR, b"folder-drive-id")
    app.scan()
    ids = [fid(app, FOLDER)]
    assert ids[0] == "folder-drive-id"
    resolved = app.executor.preview(app.browse._move_ops(ids, MISC, "ui").plan)
    check_disk_identity(app.executor.paths, app.repo, ids, resolved)
    xattr.setxattr(folder, DRIVE_ID_XATTR, b"another-id")
    resolved = app.executor.preview(app.browse._move_ops(ids, MISC, "ui").plan)
    with pytest.raises(InvalidRequest, match="scan and try again"):
        check_disk_identity(app.executor.paths, app.repo, ids, resolved)


def test_warns_about_links_into_folder(tree, fake_archive):
    app = tree
    fake_archive.link("30. Work/to-a.pdf", f"{FOLDER}/a.pdf")
    fake_archive.link(f"{ONG}/also-a.pdf", f"{FOLDER}/a.pdf")  # Ongoing is not counted
    fake_archive.link(f"{MISC}/to-keep.pdf", f"{MISC}/keep.pdf")  # points elsewhere
    app.scan()
    folder_id = fid(app, FOLDER)
    ops = app.browse.move_preview([folder_id], MISC)
    move = next(o for o in ops if o.kind is OpKind.MOVE)
    assert move.note == (
        "1 link elsewhere points into this folder and will point to nothing: to-a.pdf"
    )
    result = app.browse.move([folder_id], MISC, dry_run=True)
    assert any(o.note and o.note.startswith("1 link elsewhere points into") for o in result.done)


def test_warning_lists_up_to_five_names(tree, fake_archive):
    app = tree
    for n in range(2):
        fake_archive.link(f"30. Work/l{n}.pdf", f"{FOLDER}/a.pdf")
    app.scan()
    ops = app.browse.move_preview([fid(app, FOLDER)], MISC)
    move = next(o for o in ops if o.kind is OpKind.MOVE)
    assert move.note == (
        "2 links elsewhere point into this folder and will point to nothing: l0.pdf, l1.pdf"
    )


def test_warning_gives_only_the_count_above_five(tree, fake_archive):
    app = tree
    for n in range(7):
        fake_archive.link(f"30. Work/l{n}.pdf", f"{FOLDER}/a.pdf")
    app.scan()
    ops = app.browse.move_preview([fid(app, FOLDER)], MISC)
    move = next(o for o in ops if o.kind is OpKind.MOVE)
    assert move.note == "7 links elsewhere point into this folder and will point to nothing"


def test_no_warning_for_a_file_move(tree, fake_archive):
    app = tree
    fake_archive.link("30. Work/to-a.pdf", f"{FOLDER}/a.pdf")
    app.scan()
    ops = app.browse.move_preview(["id-a"], MISC)
    assert all(not o.note or "link" not in o.note for o in ops)


def test_inside_link_has_its_own_sentence(tree, fake_archive):
    app = tree
    fake_archive.link(f"{FOLDER}/sub/in.pdf", f"{FOLDER}/a.pdf")
    app.scan()
    ops = app.browse.move_preview([fid(app, FOLDER)], MISC)
    move = next(o for o in ops if o.kind is OpKind.MOVE)
    assert move.note == (
        "1 link inside this folder points into it and will point to nothing: in.pdf"
    )
    assert "elsewhere" not in move.note


def test_across_disks_note_and_inside_link(extra_folder, tree, fake_archive, monkeypatch):
    from dam.ops import primitives

    app = tree
    fake_archive.link("30. Work/to-a.pdf", f"{FOLDER}/a.pdf")
    fake_archive.link(f"{FOLDER}/sub/in.pdf", f"{FOLDER}/a.pdf")
    extra_folder.add("keep.pdf", b"k", drive_id="x1")
    app.scan()
    monkeypatch.setattr(primitives, "same_disk", lambda a, b: False)
    ops = app.browse.move_preview([fid(app, FOLDER)], "Old years")
    final = next(o for o in ops if o.copied_to is not None)
    assert final.kind is OpKind.QUARANTINE
    assert "1 link elsewhere points into this folder and will point to nothing: to-a.pdf" in (
        final.note
    )
    assert "inside this folder" not in final.note


def test_note_added_once(tree, fake_archive):
    app = tree
    fake_archive.link("30. Work/to-a.pdf", f"{FOLDER}/a.pdf")
    app.scan()
    folder_id = fid(app, FOLDER)
    move = app.browse._drop([folder_id], MISC, "ui", "move")
    ops = app.executor.preview(move.plan)
    app.browse._warn_links_elsewhere(move, ops, "move")
    app.browse._warn_links_elsewhere(move, ops, "move")
    folder_op = next(o for o in ops if o.kind is OpKind.MOVE)
    assert folder_op.note.count("will point to nothing") == 1
