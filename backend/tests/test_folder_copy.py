"""Running a folder move across disks as a background job: the tree is copied, the
source goes to To Delete in one piece, the rows follow; Stop, a second move after a
stop, and a source that changed during the job."""

import json
import os

import pytest
import xattr
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from dam.db.tables import operations
from dam.index.driveid import DRIVE_ID_XATTR
from dam.ops import primitives
from dam.ops import undo as journal
from dam.ops.model import OpKind
from dam.ops.primitives import PRESENT
from dam.services import LOCAL_ID_PREFIX

HOME = "20. Home"
SRC = f"{HOME}/2009"
DEST = "Old years"
COPY = f"{DEST}/2009"
QUAR = "##. To Delete"


@pytest.fixture
def across(extra_folder, app, fake_archive, monkeypatch):
    """``20. Home/2009/{a.pdf, sub/b.pdf, empty/}`` with a Drive id on the folder, a tag on
    a.pdf and the folder in a collection; the main folder and Old years on different
    disks."""
    fake_archive.add(f"{SRC}/a.pdf", b"aaaa", drive_id="id-a")
    fake_archive.add(f"{SRC}/sub/b.pdf", b"bb", drive_id="id-b")
    (fake_archive.root / SRC / "empty").mkdir()
    xattr.setxattr(fake_archive.root / SRC, DRIVE_ID_XATTR, b"id-dir")
    extra_folder.add("keep.pdf", b"k", drive_id="x1")
    app.scan()
    assert app.repo.by_path(SRC).drive_id == "id-dir"
    app.tags.add("id-a", ["bank"])
    col = app.collections.create("Years")
    app.collections.add_members(col.id, ["id-dir"])
    monkeypatch.setattr(primitives, "same_disk", lambda a, b: False)
    return app


def _wait(job, timeout: float = 10.0):
    job.join(timeout)
    assert job.state != "running"
    return job


def _move(app):
    folder_id = app.repo.by_path(SRC).drive_id
    result = app.browse.move([folder_id], DEST, origin="ui")
    assert result.job_id is not None, result.error
    return _wait(app.copy_jobs.get(result.job_id))


def _journal(app, batch_id: str):
    return journal.entries(app.executor, operations.c.batch_id == batch_id)


def _hook(app, monkeypatch, *, stop_after_first=False, after_first=None):
    """Wrap the job's ``apply``: Stop once the first file is copied, or call
    ``after_first`` right after the first COPY_ACROSS completed."""
    real = app.executor.apply

    def apply(plan, **kw):
        if kw.get("should_stop") is None:  # the request's own planning
            return real(plan, **kw)
        ask, progress = kw["should_stop"], kw.get("progress")
        seen = {"copies": 0}

        def on_progress(rop, index, ops):
            if rop.kind is OpKind.COPY_ACROSS:
                seen["copies"] += 1
                if seen["copies"] == 1 and after_first is not None:
                    after_first()
            if progress is not None:
                progress(rop, index, ops)

        kw["progress"] = on_progress
        if stop_after_first:
            kw["should_stop"] = lambda: seen["copies"] >= 1 or ask()
        return real(plan, **kw)

    monkeypatch.setattr(app.executor, "apply", apply)


def _all_names(*roots) -> list[str]:
    return [p.name for root in roots for p in root.rglob("*")]


def test_folder_copied_and_original_to_to_delete(across, fake_archive, extra_folder):
    job = _move(across)
    batch = job.result
    assert job.state == "done" and batch.failed is None and batch.error is None
    copy, aside = extra_folder.root / "2009", fake_archive.root / QUAR / SRC
    assert (copy / "a.pdf").read_bytes() == b"aaaa"
    assert (copy / "sub" / "b.pdf").read_bytes() == b"bb"
    assert (copy / "empty").is_dir()
    for rel in ("a.pdf", "sub/b.pdf"):
        assert os.stat(copy / rel).st_mtime_ns == os.stat(aside / rel).st_mtime_ns
    assert not (fake_archive.root / SRC).exists()
    assert (aside / "a.pdf").read_bytes() == b"aaaa" and (aside / "empty").is_dir()
    a = across.repo.by_path(f"{COPY}/a.pdf")
    assert a is not None and across.tags.for_file(a.drive_id) == ["bank"]
    assert across.repo.by_path(f"{COPY}/sub/b.pdf") is not None
    folder = across.repo.by_path(COPY)
    assert folder is not None and folder.is_dir
    assert folder.drive_id.startswith(LOCAL_ID_PREFIX)  # the original keeps id-dir on disk
    assert across.repo.get("id-dir") is None
    assert [c.name for c in across.collections.for_file(folder.drive_id)] == ["Years"]
    assert across.repo.by_path(f"{COPY}/sub").is_dir
    assert across.repo.by_path(f"{COPY}/empty").is_dir


def test_stop_leaves_source_whole(across, fake_archive, extra_folder, monkeypatch):
    _hook(across, monkeypatch, stop_after_first=True)
    job = _move(across)
    assert job.result.stopped and job.result.failed is None
    assert (fake_archive.root / SRC / "a.pdf").read_bytes() == b"aaaa"
    assert (fake_archive.root / SRC / "sub" / "b.pdf").read_bytes() == b"bb"
    assert (fake_archive.root / SRC / "empty").is_dir()
    assert (extra_folder.root / "2009" / "a.pdf").exists()
    assert not (extra_folder.root / "2009" / "sub" / "b.pdf").exists()
    kinds = [e.kind for e in _journal(across, job.result.batch_id)]
    assert "quarantine" not in kinds
    assert not (fake_archive.root / QUAR / SRC).exists()


def test_second_move_after_stop_merges(across, fake_archive, extra_folder, monkeypatch):
    real = across.executor.apply
    _hook(across, monkeypatch, stop_after_first=True)
    assert _move(across).result.stopped
    monkeypatch.setattr(across.executor, "apply", real)
    across.scan()  # the watcher indexes the bare original and the made folders
    copy = extra_folder.root / "2009" / "a.pdf"
    before = os.stat(copy).st_mtime_ns
    job = _move(across)
    batch = job.result
    assert job.state == "done" and batch.failed is None, batch.error
    rows = [e for e in _journal(across, batch.batch_id) if e.kind == "copy_across"]
    assert [(e.src, e.method, e.state) for e in rows] == [
        (f"{SRC}/a.pdf", PRESENT, "done"),
        (f"{SRC}/sub/b.pdf", None, "done"),
    ]
    assert os.stat(copy).st_mtime_ns == before and copy.read_bytes() == b"aaaa"
    assert (extra_folder.root / "2009" / "sub" / "b.pdf").read_bytes() == b"bb"
    assert not (fake_archive.root / SRC).exists()
    assert (fake_archive.root / QUAR / SRC / "a.pdf").exists()
    assert not [n for n in _all_names(fake_archive.root, extra_folder.root) if "_2" in n]
    a = across.repo.by_path(f"{COPY}/a.pdf")
    assert across.tags.for_file(a.drive_id) == ["bank"]  # the first move's row stays
    folder = across.repo.by_path(COPY)
    assert [c.name for c in across.collections.for_file(folder.drive_id)] == ["Years"]


def test_present_differs_stops(across, fake_archive, extra_folder, monkeypatch):
    real = across.executor.apply
    _hook(across, monkeypatch, stop_after_first=True)
    assert _move(across).result.stopped
    monkeypatch.setattr(across.executor, "apply", real)
    copy = extra_folder.root / "2009" / "a.pdf"
    st = os.stat(copy)
    copy.write_bytes(b"zzzz")  # same size, same time, other bytes
    os.utime(copy, ns=(st.st_atime_ns, st.st_mtime_ns))
    batch = _move(across).result
    assert batch.failed is not None and batch.failed.method == PRESENT
    assert batch.error == (
        "a.pdf at the destination differs from the original; nothing more was moved."
    )
    assert (fake_archive.root / SRC / "a.pdf").exists()
    assert not (fake_archive.root / QUAR / SRC).exists()


def _changed(across, fake_archive, monkeypatch, change) -> str:
    _hook(across, monkeypatch, after_first=change)
    batch = _move(across).result
    assert batch.failed is not None and batch.failed.kind is OpKind.QUARANTINE
    assert (fake_archive.root / SRC / "sub" / "b.pdf").exists()
    assert not (fake_archive.root / QUAR / SRC).exists()
    return batch.error


def test_file_added_during_job_stops_before_quarantine(across, fake_archive, monkeypatch):
    def add():
        (fake_archive.root / SRC / "new.pdf").write_bytes(b"n")

    assert _changed(across, fake_archive, monkeypatch, add) == (
        "2009 changed during the move (new.pdf was added). It stays where it is;"
        " move it again to copy the rest."
    )


def test_file_edited_after_copy_stops(across, fake_archive, monkeypatch):
    def edit():
        (fake_archive.root / SRC / "a.pdf").write_bytes(b"edited")

    assert _changed(across, fake_archive, monkeypatch, edit) == (
        "2009 changed during the move (a.pdf was changed). It stays where it is;"
        " move it again to copy the rest."
    )


def test_file_touched_after_copy_stops(across, fake_archive, monkeypatch):
    def touch():  # same size and bytes, another modification time
        path = fake_archive.root / SRC / "a.pdf"
        st = os.stat(path)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000_000))

    assert "(a.pdf was changed)" in _changed(across, fake_archive, monkeypatch, touch)


def test_file_removed_during_job_stops(across, fake_archive, monkeypatch, tmp_path):
    def take_away():  # moved out of the archive, as the owner might in Finder
        (fake_archive.root / SRC / "a.pdf").rename(tmp_path / "a.pdf")

    assert _changed(across, fake_archive, monkeypatch, take_away) == (
        "2009 changed during the move (a.pdf was removed). It stays where it is;"
        " move it again to copy the rest."
    )


def test_copied_to_journaled(across):
    batch = _move(across).result
    (final,) = [e for e in _journal(across, batch.batch_id) if e.kind == "quarantine"]
    assert final.copied_to == COPY and final.state == "done"
    envelope = json.loads(final.followed)
    assert envelope["applied"] is True
    followed = envelope["rows"]
    folder = across.repo.by_path(COPY)
    assert ["id-dir", folder.drive_id, SRC, COPY] in followed
    assert {f[3] for f in followed} == {COPY, f"{COPY}/sub", f"{COPY}/empty"}
    with across.engine.connect() as conn:
        others = conn.execute(
            select(operations.c.copied_to).where(
                operations.c.batch_id == batch.batch_id, operations.c.kind != "quarantine"
            )
        ).scalars()
        assert set(others) == {None}


def test_job_result_text(across, monkeypatch):
    real = across.executor.apply
    _hook(across, monkeypatch, stop_after_first=True)
    stopped = _move(across).result
    assert stopped.error == "Copied 1 of 2 files; 2009 stays in place until all are copied"
    monkeypatch.setattr(across.executor, "apply", real)
    done = _move(across).result
    assert done.error is None
    assert done.message == "Moved folder 2009 (2 files) to 'Old years'"


def test_empty_folder_moves_and_is_checked(across, fake_archive, extra_folder):
    (fake_archive.root / HOME / "2010").mkdir()
    across.scan()
    folder_id = across.repo.by_path(f"{HOME}/2010").drive_id
    resolved = across.browse.move_preview([folder_id], DEST, origin="ui")
    assert not [r for r in resolved if r.kind == "copy_across"]
    result = across.browse.move([folder_id], DEST, origin="ui")
    assert result.failed is None, result.error
    assert (extra_folder.root / "2010").is_dir()
    assert (fake_archive.root / QUAR / HOME / "2010").is_dir()
    assert across.repo.by_path(f"{DEST}/2010").is_dir


def _final(app, batch_id: str):
    (final,) = [e for e in _journal(app, batch_id) if e.kind == "quarantine"]
    return final


def test_followed_journaled_before_rows_move(across, fake_archive, monkeypatch):
    repo = across.repo
    real = repo.update_path
    calls = {"one_row": 0}

    def fail_on_second_folder(old, new, *, recursive=True):
        if not recursive:
            calls["one_row"] += 1
            if calls["one_row"] == 2:
                raise SQLAlchemyError("disk I/O error")
        return real(old, new, recursive=recursive)

    monkeypatch.setattr(repo, "update_path", fail_on_second_folder)
    batch = _move(across).result
    assert batch.index_error is not None and batch.failed is None
    final = _final(across, batch.batch_id)
    assert final.state == "done"  # the folder is in To Delete
    envelope = json.loads(final.followed)
    assert envelope["applied"] is False  # the index step stopped part way
    followed = envelope["rows"]
    assert [f[2] for f in followed] == [SRC, f"{SRC}/empty", f"{SRC}/sub"]
    assert [f[3] for f in followed] == [COPY, f"{COPY}/empty", f"{COPY}/sub"]
    assert followed[0][0] == "id-dir"
    assert repo.by_path(f"{COPY}/empty") is None  # not moved yet
    monkeypatch.setattr(repo, "update_path", real)
    across.executor._apply_followed(followed)
    across.executor._apply_followed(followed)  # again: nothing changes
    for old_id, new_id, old_path, new_path in followed:
        row = repo.by_path(new_path)
        assert row is not None and row.is_dir and row.drive_id == new_id, new_path
        assert repo.by_path(old_path) is None
        assert old_id == new_id or repo.get(old_id) is None
    folder = repo.by_path(COPY)
    assert [c.name for c in across.collections.for_file(folder.drive_id)] == ["Years"]


def test_apply_followed_after_a_scan_drops_the_scanner_row(across, monkeypatch):
    repo = across.repo
    real = repo.update_path

    def fail_every_folder(old, new, *, recursive=True):
        if not recursive:
            raise SQLAlchemyError("disk I/O error")
        return real(old, new, recursive=recursive)

    monkeypatch.setattr(repo, "update_path", fail_every_folder)
    batch = _move(across).result
    followed = json.loads(_final(across, batch.batch_id).followed)["rows"]
    monkeypatch.setattr(repo, "update_path", real)
    across.scan()  # the made folders get rows of their own meanwhile
    assert repo.by_path(COPY) is not None
    across.executor._apply_followed(followed)
    folder = repo.by_path(COPY)
    assert folder.drive_id == followed[0][1]
    assert [c.name for c in across.collections.for_file(folder.drive_id)] == ["Years"]
