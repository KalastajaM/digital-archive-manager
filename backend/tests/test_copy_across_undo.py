"""Undo and crash recovery of moves between archive folders on different disks."""

import os

import pytest
from sqlalchemy import select, update

from dam.db.tables import operations
from dam.ops import primitives
from dam.ops.model import GuardError, Op, OpFailed, OpKind, Plan
from dam.ops.primitives import TEMP_COPY_PREFIX
from dam.ops.undo import INTERRUPTED, MANUAL_CHECK

BANKS = "10. Financial/Banks"
QUAR = "##. To Delete"


@pytest.fixture
def across(extra_folder, app, fake_archive, monkeypatch):
    fake_archive.add(f"{BANKS}/a.pdf", b"aaaa", drive_id="id-a")
    fake_archive.add(f"{BANKS}/b.pdf", b"bb", drive_id="id-b")
    app.scan()
    monkeypatch.setattr(primitives, "same_disk", lambda a, b: False)
    return app


def _move(app, *names, **kw):
    ops = [Op(OpKind.MOVE, f"{BANKS}/{n}", "Old years/2010") for n in names]
    result = app.executor.apply(Plan(ops, origin="ui", copy_across=True), **kw)
    assert result.failed is None, result.error
    return result


def _states(app, batch_id) -> list[tuple[str, str]]:
    with app.engine.connect() as conn:
        rows = conn.execute(
            select(operations.c.kind, operations.c.state)
            .where(operations.c.batch_id == batch_id)
            .order_by(operations.c.seq)
        ).all()
    return [tuple(r) for r in rows if r[0] != "mkdir"]


def test_undo_puts_original_back_with_tags(across, fake_archive, extra_folder):
    across.tags.add("id-a", ["bank"])
    across.notes.set("file", "id-a", "closed")
    result = _move(across, "a.pdf")
    undone = across.executor.undo(result.batch_id)
    assert undone.failed is None, undone.error
    assert (fake_archive.root / BANKS / "a.pdf").read_bytes() == b"aaaa"
    assert (extra_folder.root / QUAR / "2010" / "a.pdf").read_bytes() == b"aaaa"
    assert not (extra_folder.root / "2010" / "a.pdf").exists()
    rec = across.repo.by_path(f"{BANKS}/a.pdf")
    assert rec.drive_id == "id-a"
    assert across.tags.for_file("id-a") == ["bank"]
    assert across.notes.get("file", "id-a") == "closed"
    assert _states(across, result.batch_id) == [("copy_across", "undone"), ("quarantine", "undone")]


def test_undo_after_scan_keeps_tagged_row(across, fake_archive):
    across.tags.add("id-a", ["bank"])
    result = _move(across, "a.pdf")
    across.scan()  # the original in To Delete gets a row of its own, with id-a
    assert across.executor.undo(result.batch_id).failed is None
    assert across.repo.by_path(f"{BANKS}/a.pdf").drive_id == "id-a"
    assert across.tags.for_file("id-a") == ["bank"]
    across.scan()
    assert across.repo.by_path(f"{BANKS}/a.pdf").drive_id == "id-a"
    assert across.tags.for_file("id-a") == ["bank"]


def test_undo_of_stopped_batch(across, fake_archive, extra_folder):
    def after_first() -> bool:
        with across.engine.connect() as conn:
            return bool(
                conn.execute(
                    select(operations.c.id).where(operations.c.kind == "quarantine")
                ).first()
            )

    result = _move(across, "a.pdf", "b.pdf", should_stop=after_first)
    assert result.stopped
    assert across.executor.undo(result.batch_id).failed is None
    assert (fake_archive.root / BANKS / "a.pdf").exists()
    assert (fake_archive.root / BANKS / "b.pdf").exists()


def test_undo_waits_for_destination(across, fake_archive, extra_folder):
    result = _move(across, "a.pdf")
    os.rename(extra_folder.root, extra_folder.root.with_name("away"))
    with pytest.raises(GuardError) as e:
        across.executor.undo(result.batch_id)
    assert "'Old years' is not connected" in str(e.value)
    assert (fake_archive.root / QUAR / BANKS / "a.pdf").exists()


def test_undo_refused_when_copy_changed(across, extra_folder):
    result = _move(across, "a.pdf")
    copy = extra_folder.root / "2010" / "a.pdf"
    copy.write_bytes(b"edit")  # same size, other content
    with pytest.raises(OpFailed) as e:
        across.executor.undo(result.batch_id)
    assert "has changed since" in str(e.value)


def _planned(app, result) -> None:
    """Make the batch's copy row look interrupted (``planned``), as after a crash."""
    with app.engine.begin() as conn:
        conn.execute(
            update(operations)
            .where(operations.c.batch_id == result.batch_id, operations.c.kind == "copy_across")
            .values(state="planned")
        )
        conn.execute(
            operations.delete().where(
                operations.c.batch_id == result.batch_id, operations.c.kind == "quarantine"
            )
        )


def _recovered(app) -> tuple[str, str | None]:
    (entry,) = [e for e in app.executor.recover().entries if e.kind == "copy_across"]
    return entry.state, entry.error


def test_recover_copy_that_finished(across, fake_archive, extra_folder):
    result = _move(across, "a.pdf")
    _planned(across, result)
    os.rename(fake_archive.root / QUAR / BANKS / "a.pdf", fake_archive.root / BANKS / "a.pdf")
    across.repo.update_path("Old years/2010/a.pdf", f"{BANKS}/a.pdf")  # index as before
    assert _recovered(across) == ("done", None)
    assert across.repo.by_path("Old years/2010/a.pdf") is not None


def test_recover_copy_never_started(across, fake_archive, extra_folder):
    result = _move(across, "a.pdf")
    _planned(across, result)
    os.rename(fake_archive.root / QUAR / BANKS / "a.pdf", fake_archive.root / BANKS / "a.pdf")
    os.rename(extra_folder.root / "2010" / "a.pdf", extra_folder.root / "elsewhere.pdf")
    assert _recovered(across) == ("failed", INTERRUPTED)


def test_recover_only_temp_needs_manual_check(across, fake_archive, extra_folder):
    result = _move(across, "a.pdf")
    _planned(across, result)
    os.rename(fake_archive.root / QUAR / BANKS / "a.pdf", fake_archive.root / BANKS / "a.pdf")
    temp = extra_folder.root / "2010" / f"{TEMP_COPY_PREFIX}abcd1234-a.pdf"
    os.rename(extra_folder.root / "2010" / "a.pdf", temp)
    assert _recovered(across) == ("failed", MANUAL_CHECK)
    assert temp.exists() and (fake_archive.root / BANKS / "a.pdf").exists()
