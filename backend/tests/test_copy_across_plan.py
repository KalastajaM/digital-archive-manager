"""Planning a move between archive folders on different disks (the dry run)."""

from types import SimpleNamespace

import pytest

from dam.ops import primitives
from dam.ops.model import GuardError, Op, OpFailed, OpKind, Plan
from dam.ops.planner import COLLISION_NOTE

BANKS = "10. Financial/Banks"
QUAR = "##. To Delete"
INBOX = "##. Organize"


@pytest.fixture
def across(extra_folder, app, fake_archive, monkeypatch):
    """A file in each folder, indexed; the two folders on different disks."""
    fake_archive.add(f"{BANKS}/a.pdf", b"aaaa", drive_id="id-a")
    extra_folder.add("2009/old.pdf", b"old", drive_id="x1")
    app.scan()
    monkeypatch.setattr(primitives, "same_disk", lambda a, b: False)
    return app


def _plan(*ops: Op) -> Plan:
    return Plan(list(ops), origin="ui", copy_across=True)


def _kinds(resolved) -> list[str]:
    return [str(r.kind) for r in resolved]


def _work(resolved) -> list:
    """The ops other than making missing folders (the destination, To Delete)."""
    return [r for r in resolved if r.kind is not OpKind.MKDIR]


def test_file_move_across_disks_plans_copy_and_quarantine(across):
    resolved = across.executor.preview(_plan(Op(OpKind.MOVE, f"{BANKS}/a.pdf", "Old years/2010")))
    assert resolved[0].dst == "Old years/2010"
    assert _kinds(resolved)[-2:] == ["copy_across", "quarantine"]  # always together
    copy, quarantine = _work(resolved)
    assert (copy.src, copy.dst, copy.drive_id) == (f"{BANKS}/a.pdf", "Old years/2010/a.pdf", "id-a")
    assert copy.size == 4 and copy.cloud_only is False
    assert (quarantine.src, quarantine.dst) == (f"{BANKS}/a.pdf", f"{QUAR}/{BANKS}/a.pdf")
    assert quarantine.note == "copied to Old years/2010/a.pdf"


def test_move_into_main_folder_quarantines_in_extra_folder(across):
    resolved = across.executor.preview(_plan(Op(OpKind.MOVE, "Old years/2009/old.pdf", BANKS)))
    copy, quarantine = _work(resolved)
    assert (copy.kind, quarantine.kind) == (OpKind.COPY_ACROSS, OpKind.QUARANTINE)
    assert copy.dst == f"{BANKS}/old.pdf"
    assert quarantine.dst == f"Old years/{QUAR}/2009/old.pdf"


def test_taken_name_gets_suffix(across, extra_folder):
    extra_folder.add("2009/a.pdf", b"other", drive_id="x2")
    resolved = across.executor.preview(_plan(Op(OpKind.MOVE, f"{BANKS}/a.pdf", "Old years/2009")))
    copy = _work(resolved)[0]
    assert copy.dst == "Old years/2009/a_2.pdf" and copy.note == COLLISION_NOTE


def test_new_name_is_kept(across):
    resolved = across.executor.preview(
        _plan(Op(OpKind.MOVE, f"{BANKS}/a.pdf", "Old years/2009", name="2009 bank.pdf"))
    )
    assert _work(resolved)[0].dst == "Old years/2009/2009 bank.pdf"


def test_restore_across_disks_plans_copy_only(across):
    assert across.browse.quarantine(["x1"], origin="ui").failed is None
    resolved = across.executor.preview(
        _plan(Op(OpKind.MOVE, f"Old years/{QUAR}/2009/old.pdf", INBOX))
    )
    assert _kinds(resolved) == ["copy_across"]
    assert resolved[0].dst == f"{INBOX}/old.pdf"
    assert resolved[0].note == "the original stays in To Delete"


def test_plain_plan_still_refused(across):
    with pytest.raises(OpFailed) as e:
        across.executor.preview(
            Plan([Op(OpKind.MOVE, f"{BANKS}/a.pdf", "Old years/2010")], origin="ui")
        )
    assert str(e.value) == (
        "The main folder and 'Old years' are on different disks, so this cannot be moved"
        " between them here."
    )


def test_folder_move_across_disks_refused(across):
    with pytest.raises(OpFailed) as e:
        across.executor.preview(_plan(Op(OpKind.MOVE, "Old years/2009", BANKS)))
    assert "different disks" in str(e.value)


def test_requested_copy_across_refused(across):
    with pytest.raises(GuardError):
        across.executor.preview(_plan(Op(OpKind.COPY_ACROSS, f"{BANKS}/a.pdf", "Old years")))


def test_protected_file_refused(across):
    across.executor.paths.settings.protected_paths = [BANKS]
    with pytest.raises(GuardError) as e:
        across.executor.preview(_plan(Op(OpKind.MOVE, f"{BANKS}/a.pdf", "Old years/2010")))
    assert str(e.value) == "a.pdf is protected, so it is not copied across disks."


def test_not_enough_space_refused(across, monkeypatch):
    monkeypatch.setattr(
        primitives.shutil, "disk_usage", lambda p: SimpleNamespace(total=0, used=0, free=100)
    )
    with pytest.raises(OpFailed) as e:
        across.executor.preview(_plan(Op(OpKind.MOVE, f"{BANKS}/a.pdf", "Old years/2010")))
    assert str(e.value) == (
        "There is not enough free space on 'Old years' for these files (1 MB needed)."
    )


def test_locked_file_refuses_copy_across(across, fake_archive):
    fake_archive.add(f"{BANKS}/b.pdf", b"b", drive_id="id-b")
    across.scan()
    across.locks.lock("id-a")
    across.locks.lock("id-b")
    with pytest.raises(GuardError) as e:
        across.executor.preview(
            _plan(
                Op(OpKind.MOVE, f"{BANKS}/a.pdf", "Old years/2010"),
                Op(OpKind.MOVE, f"{BANKS}/b.pdf", "Old years/2010"),
            )
        )
    assert "a.pdf" in str(e.value) and "b.pdf" in str(e.value)


def test_same_disk_stays_a_move(extra_folder, app, fake_archive):
    fake_archive.add(f"{BANKS}/a.pdf", b"a", drive_id="id-a")
    app.scan()
    resolved = app.executor.preview(_plan(Op(OpKind.MOVE, f"{BANKS}/a.pdf", "Old years/2010")))
    assert _kinds(resolved) == ["mkdir", "move"]


def test_undo_never_copies(across):
    """An undo plan (restore) keeps the refusal: undo is renames only."""
    from dam.ops.planner import Planner

    plan = _plan(Op(OpKind.MOVE, f"{BANKS}/a.pdf", "Old years/2010"))
    with pytest.raises(OpFailed):
        Planner(across.executor.paths).resolve(plan, restore=True)
