"""Carrying out a move between archive folders on different disks."""

import os

import pytest
from sqlalchemy import select

from dam.db.tables import operations
from dam.ops import executor as executor_module
from dam.ops import primitives
from dam.ops.model import Op, OpKind, Plan
from dam.ops.primitives import TEMP_COPY_PREFIX

BANKS = "10. Financial/Banks"
QUAR = "##. To Delete"
MTIME = 1_500_000_000


@pytest.fixture
def across(extra_folder, app, fake_archive, monkeypatch):
    """Two indexed files in the main folder; the extra folder on another disk."""
    for name, data, drive_id in (("a.pdf", b"aaaa", "id-a"), ("b.pdf", b"bb", "local:b")):
        local = drive_id.startswith("local:")
        path = fake_archive.add(f"{BANKS}/{name}", data, drive_id=None if local else drive_id)
        os.utime(path, (MTIME, MTIME))
    app.scan()
    monkeypatch.setattr(primitives, "same_disk", lambda a, b: False)
    return app


def _move(app, *names, folder="Old years/2010", **kw):
    ops = [Op(OpKind.MOVE, f"{BANKS}/{n}", folder) for n in names]
    return app.executor.apply(Plan(ops, origin="ui", copy_across=True), **kw)


def _journal(app) -> list[tuple[str, str]]:
    with app.engine.connect() as conn:
        rows = conn.execute(select(operations).order_by(operations.c.id)).mappings()
        return [(r["kind"], r["state"]) for r in rows]


def _id_at(app, rel: str) -> str:
    return app.repo.by_path(rel).drive_id


def test_file_moves_across_with_tags_and_note(across, fake_archive, extra_folder):
    across.tags.add("id-a", ["bank"])
    across.notes.set("file", "id-a", "closed account")
    car = across.collections.create("Bank")
    across.collections.add_members(car.id, ["id-a"])
    result = _move(across, "a.pdf")
    assert result.failed is None, result.error
    copy = extra_folder.root / "2010" / "a.pdf"
    assert copy.read_bytes() == b"aaaa" and copy.stat().st_mtime == MTIME
    assert (fake_archive.root / QUAR / BANKS / "a.pdf").read_bytes() == b"aaaa"
    assert not (fake_archive.root / BANKS / "a.pdf").exists()
    assert not [p for p in copy.parent.iterdir() if p.name.startswith(TEMP_COPY_PREFIX)]
    moved = _id_at(across, "Old years/2010/a.pdf")
    assert across.tags.for_file(moved) == ["bank"]
    assert across.notes.get("file", moved) == "closed account"
    assert [c.name for c in across.collections.for_file(moved)] == ["Bank"]
    work = [j for j in _journal(across) if j[0] in ("copy_across", "quarantine")]
    assert work == [("copy_across", "done"), ("quarantine", "done")]


def test_drive_id_source_gets_local_id(across):
    assert _move(across, "a.pdf").failed is None
    assert _id_at(across, "Old years/2010/a.pdf").startswith("local:")
    assert across.repo.get("id-a") is None


def test_local_id_kept(across):
    local = _id_at(across, f"{BANKS}/b.pdf")
    assert _move(across, "b.pdf").failed is None
    assert _id_at(across, "Old years/2010/b.pdf") == local


def test_copy_with_own_drive_id_takes_it(across, monkeypatch):
    real = executor_module.read_drive_id

    def drive_gave_it_one(path):
        return "drv-copy" if "2010" in str(path) else real(path)

    monkeypatch.setattr(executor_module, "read_drive_id", drive_gave_it_one)
    assert _move(across, "a.pdf").failed is None
    assert _id_at(across, "Old years/2010/a.pdf") == "drv-copy"


def test_scan_after_move_gives_original_a_new_row(across):
    across.tags.add("id-a", ["bank"])
    assert _move(across, "a.pdf").failed is None
    across.scan()
    assert across.tags.for_file(_id_at(across, "Old years/2010/a.pdf")) == ["bank"]
    original = across.repo.by_path(f"{QUAR}/{BANKS}/a.pdf")
    assert original.drive_id == "id-a" and across.tags.for_file("id-a") == []


def test_replaced_source_stops_the_batch(across, fake_archive):
    """Another file put in the source's place after the preview is never copied: the
    precheck compares the planned drive id with the disk."""
    from dam.ops.model import BatchResult

    resolved = across.executor.preview(
        Plan([Op(OpKind.MOVE, f"{BANKS}/a.pdf", "Old years/2010")], origin="ui", copy_across=True)
    )
    os.remove(fake_archive.root / BANKS / "a.pdf")
    fake_archive.add(f"{BANKS}/a.pdf", b"zzzz", drive_id="someone-else")
    out = across.executor._run_resolved("ui", resolved, BatchResult("b1", False))
    assert out.failed is not None and out.failed.kind is OpKind.COPY_ACROSS
    assert "changed since the preview" in out.error
    assert (fake_archive.root / BANKS / "a.pdf").read_bytes() == b"zzzz"
    assert not (fake_archive.root / QUAR / BANKS / "a.pdf").exists()


def test_change_during_copy_stops_the_batch(across, fake_archive, monkeypatch):
    real = primitives.file_sha256
    calls = []

    def changing(path):  # the snapshot reads one hash, the copy step another
        calls.append(path)
        return real(path) if len(calls) == 1 else "0" * 64

    monkeypatch.setattr(primitives, "file_sha256", changing)
    result = _move(across, "a.pdf")
    assert result.failed is not None and result.failed.kind is OpKind.COPY_ACROSS
    assert (fake_archive.root / BANKS / "a.pdf").exists()
    assert not (fake_archive.root / QUAR / BANKS / "a.pdf").exists()


def test_stop_finishes_pair(across, fake_archive, extra_folder):
    asked = []

    def stop_after_first_copy() -> bool:
        asked.append(1)
        return any(j == ("copy_across", "done") for j in _journal(across))

    result = _move(across, "a.pdf", "b.pdf", should_stop=stop_after_first_copy)
    assert result.stopped and result.failed is None
    assert (extra_folder.root / "2010" / "a.pdf").exists()
    assert (fake_archive.root / QUAR / BANKS / "a.pdf").exists()
    assert (fake_archive.root / BANKS / "b.pdf").exists()
    assert not (extra_folder.root / "2010" / "b.pdf").exists()


def test_progress_is_reported(across):
    seen = []
    _move(across, "a.pdf", "b.pdf", progress=lambda rop, i, n: seen.append((str(rop.kind), i, n)))
    kinds = [k for k, _, _ in seen]
    assert kinds.count("copy_across") == 2 and kinds.count("quarantine") == 2
    assert seen[-1][1] == seen[-1][2] - 1


def test_cancel_mid_copy_leaves_temp(across, fake_archive, extra_folder):
    across.executor.cancel_copies.set()
    result = _move(across, "a.pdf")
    assert result.failed is not None and TEMP_COPY_PREFIX in result.error
    assert (fake_archive.root / BANKS / "a.pdf").exists()
    assert not (extra_folder.root / "2010" / "a.pdf").exists()
