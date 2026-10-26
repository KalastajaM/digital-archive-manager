"""Planning a folder move across disks (the dry run): made folders, a copy per file, one
QUARANTINE of the whole source carrying the planned tree."""

import os

import pytest
import xattr

from dam.index.driveid import DRIVE_ID_XATTR
from dam.ops import primitives
from dam.ops.model import GuardError, Op, OpFailed, OpKind, Plan
from dam.ops.planner import COLLISION_NOTE
from dam.ops.primitives import PRESENT, different_disks_message
from dam.services.errors import InvalidRequest

HOME = "20. Home"
SRC = f"{HOME}/2009"
DEST = "Old years"
QUAR = "##. To Delete"


@pytest.fixture
def across(extra_folder, app, fake_archive, monkeypatch):
    """``20. Home/2009/{a.pdf, sub/b.pdf, empty/}``, indexed; the main folder and Old
    years on different disks."""
    fake_archive.add(f"{SRC}/a.pdf", b"aaaa", drive_id="id-a")
    fake_archive.add(f"{SRC}/sub/b.pdf", b"bb", drive_id="id-b")
    (fake_archive.root / SRC / "empty").mkdir()
    extra_folder.add("keep.pdf", b"k", drive_id="x1")
    app.scan()
    monkeypatch.setattr(primitives, "same_disk", lambda a, b: False)
    return app


def _plan(*ops: Op, copy_across: bool = True) -> Plan:
    return Plan(list(ops), origin="ui", copy_across=copy_across)


def _move(app, folder: str = SRC, dest: str = DEST):
    return app.executor.preview(_plan(Op(OpKind.MOVE, folder, dest)))


def _layout(resolved) -> list[tuple[str, str]]:
    return [(str(r.kind), r.dst if r.kind is OpKind.MKDIR else r.src) for r in resolved]


def _copies(resolved) -> list:
    return [r for r in resolved if r.kind is OpKind.COPY_ACROSS]


def test_layout(across):
    resolved = _move(across)
    assert _layout(resolved) == [
        ("mkdir", f"{DEST}/2009"),
        ("mkdir", f"{DEST}/2009/empty"),
        ("mkdir", f"{DEST}/2009/sub"),
        ("copy_across", f"{SRC}/a.pdf"),
        ("copy_across", f"{SRC}/sub/b.pdf"),
        ("mkdir", f"{QUAR}/{HOME}"),
        ("quarantine", SRC),
    ]
    tree_mkdirs = resolved[:3]
    assert all(r.made for r in tree_mkdirs)
    assert resolved[5].made is False  # the To Delete folder is not one this move made
    a, b = _copies(resolved)
    assert (a.dst, a.size, a.drive_id) == (f"{DEST}/2009/a.pdf", 4, "id-a")
    assert (b.dst, b.size, b.drive_id) == (f"{DEST}/2009/sub/b.pdf", 2, "id-b")
    assert a.method is None and a.cloud_only is False
    quarantine = resolved[-1]
    assert quarantine.dst == f"{QUAR}/{HOME}/2009"
    assert quarantine.copied_to == f"{DEST}/2009"
    assert quarantine.note == f"copied to {DEST}/2009"
    assert quarantine.tree is not None
    assert sorted(quarantine.tree) == ["a.pdf", "empty", "sub", "sub/b.pdf"]
    st = os.lstat(across.executor.paths.abs(f"{SRC}/a.pdf"))
    assert quarantine.tree["a.pdf"] == ("file", 4, st.st_mtime)
    assert quarantine.tree["sub"][0] == "dir" and quarantine.tree["empty"][0] == "dir"


def test_tree_keys_are_folded(across, fake_archive):
    fake_archive.add(f"{SRC}/Sub2/Café.PDF", b"c", drive_id="id-c")
    across.scan()
    tree = _move(across)[-1].tree
    assert "sub2/café.pdf" in tree and "sub2" in tree


def test_merge_into_existing(across, fake_archive, extra_folder):
    src_a = fake_archive.root / SRC / "a.pdf"
    there = extra_folder.add("2009/a.pdf", b"aaaa", drive_id=None)
    st = os.lstat(src_a)
    os.utime(there, ns=(st.st_atime_ns, st.st_mtime_ns))
    (extra_folder.root / "2009" / "sub").mkdir()
    resolved = _move(across)
    mkdirs = [r.dst for r in resolved if r.kind is OpKind.MKDIR]
    assert mkdirs == [f"{DEST}/2009/empty", f"{QUAR}/{HOME}"]
    a, b = _copies(resolved)
    assert a.method == PRESENT and a.dst == f"{DEST}/2009/a.pdf"
    assert b.method is None and b.dst == f"{DEST}/2009/sub/b.pdf"
    assert resolved[-1].copied_to == f"{DEST}/2009"


def test_present_ignores_subsecond_mtime(across, fake_archive, extra_folder):
    st = os.lstat(fake_archive.root / SRC / "a.pdf")
    there = extra_folder.add("2009/a.pdf", b"aaaa", drive_id=None)
    whole = st.st_mtime_ns // 1_000_000_000 * 1_000_000_000
    os.utime(there, ns=(whole, whole))  # exFAT / FAT keep coarser times
    assert _copies(_move(across))[0].method == PRESENT


def test_same_name_other_size_gets_suffix(across, extra_folder):
    extra_folder.add("2009/a.pdf", b"other content", drive_id=None)
    a = _copies(_move(across))[0]
    assert a.method is None
    assert a.dst == f"{DEST}/2009/a_2.pdf" and a.note == COLLISION_NOTE


def test_destination_taken_by_a_file_gets_suffix(across, extra_folder):
    extra_folder.add("2009", b"a file", drive_id=None)
    resolved = _move(across)
    assert resolved[0].dst == f"{DEST}/2009_2" and resolved[0].made
    assert resolved[-1].copied_to == f"{DEST}/2009_2"
    assert _copies(resolved)[0].dst == f"{DEST}/2009_2/a.pdf"


def test_ds_store_not_copied(across, fake_archive):
    (fake_archive.root / SRC / primitives.DS_STORE).write_bytes(b"finder")
    (fake_archive.root / SRC / "sub" / primitives.DS_STORE).write_bytes(b"finder")
    fake_archive.add(f"{SRC}/.hidden", b"h", drive_id=None)
    resolved = _move(across)
    names = [os.path.basename(r.src) for r in _copies(resolved)]
    assert names == [".hidden", "a.pdf", "b.pdf"]
    assert not any(primitives.DS_STORE.casefold() in k for k in resolved[-1].tree)


def test_dam_copy_leftover_refuses(across, fake_archive):
    (fake_archive.root / SRC / "sub" / ".dam-copy-x-a.pdf").write_bytes(b"half")
    with pytest.raises(GuardError) as e:
        _move(across)
    assert str(e.value) == "Remove the unfinished copy .dam-copy-x-a.pdf first."


def test_protected_inside_refuses(across):
    across.executor.paths.settings.protected_paths = [f"{SRC}/sub/b.pdf"]
    with pytest.raises(GuardError) as e:
        _move(across)
    assert str(e.value) == "2009 holds a protected entry, so it is not copied across disks."


def test_not_enough_space(across, extra_folder, fake_archive, monkeypatch):
    seen: list[int] = []

    def room(folder, size):
        seen.append(size)
        return True

    monkeypatch.setattr(primitives, "has_room", room)
    _move(across)
    assert seen == [6]  # a.pdf (4) and b.pdf (2)
    there = extra_folder.add("2009/a.pdf", b"aaaa", drive_id=None)
    st = os.lstat(fake_archive.root / SRC / "a.pdf")
    os.utime(there, ns=(st.st_atime_ns, st.st_mtime_ns))
    seen.clear()
    _move(across)
    assert seen == [2]  # the file already there is not copied again
    monkeypatch.setattr(primitives, "has_room", lambda folder, size: False)
    with pytest.raises(OpFailed) as e:
        _move(across)
    assert str(e.value) == (
        "There is not enough free space on 'Old years' for these files (1 MB needed)."
    )


def test_links_left_behind_noted(across, fake_archive):
    fake_archive.link(f"{SRC}/sub/to-a", f"{SRC}/a.pdf")
    resolved = _move(across)
    assert not any(r.src and r.src.endswith("to-a") for r in resolved[:-1])
    quarantine = resolved[-1]
    assert quarantine.tree["sub/to-a"][0] == "link"
    assert "1 link is not copied; it goes to To Delete with the folder" in quarantine.note
    fake_archive.link(f"{SRC}/to-b", f"{SRC}/sub/b.pdf")
    note = _move(across)[-1].note
    assert "2 links are not copied; they go to To Delete with the folder" in note


def test_cloud_only_flagged(across, monkeypatch):
    monkeypatch.setattr(primitives, "is_dataless", lambda p: p.name == "b.pdf")
    a, b = _copies(_move(across))
    assert (a.cloud_only, b.cloud_only) == (False, True)


def test_plain_plan_still_refused(across):
    with pytest.raises(OpFailed) as e:
        across.executor.preview(_plan(Op(OpKind.MOVE, SRC, DEST), copy_across=False))
    assert str(e.value) == different_disks_message("", DEST)


def test_folder_in_to_delete_still_refused(across, fake_archive):
    fake_archive.add(f"{QUAR}/2008/c.pdf", b"c", drive_id="id-c")
    across.scan()
    with pytest.raises(OpFailed) as e:
        _move(across, f"{QUAR}/2008")
    assert "different disks" in str(e.value)


def test_browse_preview_checks_the_folder_itself(across):
    folder_id = across.repo.by_path(SRC).drive_id
    resolved = across.browse.move_preview([folder_id], DEST)
    assert resolved[-1].kind is OpKind.QUARANTINE and resolved[-1].src == SRC
    assert len(_copies(resolved)) == 2


def test_browse_preview_refuses_a_replaced_folder(across, fake_archive):
    folder_id = across.repo.by_path(SRC).drive_id
    assert folder_id.startswith("local:")
    xattr.setxattr(fake_archive.root / SRC, DRIVE_ID_XATTR, b"someone-else")
    with pytest.raises(InvalidRequest) as e:
        across.browse.move_preview([folder_id], DEST)
    assert "now has Drive id 'someone-else'" in str(e.value)
