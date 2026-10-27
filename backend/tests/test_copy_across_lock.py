"""A copy across disks reads and writes the file without holding ``INDEX_LOCK``: the rest
of the app (scans, other changes) goes on meanwhile, and the copy is checked again under
the lock before it takes its name."""

import hashlib
import os
import threading

import pytest
from sqlalchemy import select

from dam.db.tables import operations
from dam.index.locks import INDEX_LOCK
from dam.ops import primitives
from dam.ops.model import Op, OpKind, Plan
from dam.ops.primitives import TEMP_COPY_PREFIX

BANKS = "10. Financial/Banks"
QUAR = "##. To Delete"
DATA = b"0123456789"


@pytest.fixture
def across(extra_folder, app, fake_archive, monkeypatch):
    fake_archive.add(f"{BANKS}/a.pdf", DATA, drive_id="id-a")
    app.scan()
    monkeypatch.setattr(primitives, "same_disk", lambda a, b: False)
    return app


def _move(app, **kw):
    op = Op(OpKind.MOVE, f"{BANKS}/a.pdf", "Old years/2010")
    return app.executor.apply(Plan([op], origin="ui", copy_across=True), **kw)


def _rows(app) -> list[dict]:
    with app.engine.connect() as conn:
        rows = conn.execute(select(operations).order_by(operations.c.id)).mappings().all()
    return [dict(r) for r in rows if r["kind"] == "copy_across"]


def _temps(folder) -> list[str]:
    return [p.name for p in folder.iterdir() if p.name.startswith(TEMP_COPY_PREFIX)]


def test_others_go_on_while_a_file_is_copied(across, fake_archive, extra_folder, monkeypatch):
    """While the copy is held part way, another thread takes INDEX_LOCK, runs another
    change and scans the archive; the scan leaves the unfinished copy out of the index."""
    monkeypatch.setattr(primitives, "_COPY_CHUNK", 4)
    real = primitives.copy_file
    copying, release = threading.Event(), threading.Event()

    def held_copy(src, dst, *a, on_bytes=None, **kw):
        def hold(n):  # after the first chunk is written
            if not copying.is_set():
                copying.set()
                assert release.wait(10)
            if on_bytes is not None:
                on_bytes(n)

        return real(src, dst, *a, on_bytes=hold, **kw)

    monkeypatch.setattr(primitives, "copy_file", held_copy)
    out = {}
    worker = threading.Thread(target=lambda: out.setdefault("result", _move(across)))
    worker.start()
    try:
        assert copying.wait(10)
        assert INDEX_LOCK.acquire(timeout=10)  # another thread: not held by the copy
        INDEX_LOCK.release()
        other = across.executor.apply(Plan([Op(OpKind.MKDIR, None, f"{BANKS}/New")], "ui"))
        assert other.failed is None, other.error
        (extra_folder.root / "2010" / f"{TEMP_COPY_PREFIX}abcd1234-a.pdf").write_bytes(b"")
        across.scan()
        temps = _temps(extra_folder.root / "2010")
        assert len(temps) == 2  # the copy in progress and an old leftover
        rows = [across.repo.by_path(f"Old years/2010/{n}") for n in temps]
        # the copy in progress has no row; the leftover is indexed as before
        assert [r.name for r in rows if r is not None] == [f"{TEMP_COPY_PREFIX}abcd1234-a.pdf"]
    finally:
        release.set()
        worker.join(10)
    result = out["result"]
    assert result.failed is None, result.error
    assert (extra_folder.root / "2010" / "a.pdf").read_bytes() == DATA
    assert (fake_archive.root / QUAR / BANKS / "a.pdf").exists()
    assert across.repo.by_path("Old years/2010/a.pdf").drive_id != "id-a"  # the row followed


def test_source_read_once_and_hash_journaled(across, monkeypatch):
    """The source is read once (hashed while it is copied); only the copy is read back.
    The journaled hash is the content's, for recovery and undo."""
    real = primitives.file_sha256
    read = []

    def counting(path, stop=None):
        read.append(path.name)
        return real(path, stop)

    monkeypatch.setattr(primitives, "file_sha256", counting)
    assert _move(across).failed is None
    assert [n for n in read if not n.startswith(TEMP_COPY_PREFIX)] == []
    (row,) = _rows(across)
    assert row["content_hash"] == hashlib.sha256(DATA).hexdigest()
    assert row["state"] == "done"


def test_planned_before_the_copy_is_written(across, monkeypatch):
    real = primitives.copy_file
    states = []

    def look(src, dst, *a, **kw):
        states.append([r["state"] for r in _rows(across)])
        return real(src, dst, *a, **kw)

    monkeypatch.setattr(primitives, "copy_file", look)
    assert _move(across).failed is None
    assert states == [["planned"]]


@pytest.mark.parametrize("change", ["edit", "touch", "replace", "remove"])
def test_source_changed_during_copy_is_refused(
    across, fake_archive, extra_folder, monkeypatch, tmp_path, change
):
    """The source changes after it was read: the final check under the lock refuses the
    copy. The original stays, the copy never takes its name, and the unfinished copy is
    left as an interrupted one is (listed in Maintenance; dam never deletes)."""
    src = fake_archive.root / BANKS / "a.pdf"
    real = primitives.copy_file

    def then_change(*a, **kw):
        n = real(*a, **kw)
        if change == "edit":
            src.write_bytes(b"edited....")  # same size
            os.utime(src, (1, 1))
        elif change == "touch":
            st = os.stat(src)
            os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000_000))
        elif change == "replace":
            st = os.stat(src)
            src.rename(tmp_path / "old.pdf")
            src.write_bytes(DATA)
            os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns))
        else:
            src.rename(tmp_path / "old.pdf")
        return n

    monkeypatch.setattr(primitives, "copy_file", then_change)
    result = _move(across)
    assert result.failed is not None and result.failed.kind is OpKind.COPY_ACROSS
    (temp,) = _temps(extra_folder.root / "2010")
    assert temp in result.error
    assert not (extra_folder.root / "2010" / "a.pdf").exists()
    assert not (fake_archive.root / QUAR / BANKS / "a.pdf").exists()
    assert [r["state"] for r in _rows(across)] == ["failed"]
    assert across.executor.pending() == []
    across.scan()  # the leftover is indexed like any other, for Maintenance to list
    assert across.repo.by_path(f"Old years/2010/{temp}") is not None


def test_destination_taken_during_copy_is_refused(across, extra_folder, monkeypatch):
    real = primitives.copy_file

    def then_take(src, dst, *a, **kw):
        n = real(src, dst, *a, **kw)
        (dst.parent / "a.pdf").write_bytes(b"someone else's")
        return n

    monkeypatch.setattr(primitives, "copy_file", then_take)
    result = _move(across)
    assert result.failed is not None and "already exists" in result.error
    assert (extra_folder.root / "2010" / "a.pdf").read_bytes() == b"someone else's"
    assert len(_temps(extra_folder.root / "2010")) == 1


def test_stop_during_the_hashing_copy(across, fake_archive, extra_folder, monkeypatch):
    """Closing the app (``cancel_copies``) ends the copy at its next chunk, also while
    the source is being read and hashed."""
    monkeypatch.setattr(primitives, "_COPY_CHUNK", 4)
    seen = []

    def copied(rop, n):
        seen.append(n)
        across.executor.cancel_copies.set()

    result = _move(across, copied=copied)
    assert seen == [4]
    assert result.failed is not None and "stopped" in result.error
    assert (fake_archive.root / BANKS / "a.pdf").read_bytes() == DATA
    assert not (extra_folder.root / "2010" / "a.pdf").exists()
    assert len(_temps(extra_folder.root / "2010")) == 1
    assert [r["state"] for r in _rows(across)] == ["failed"]


def test_stop_during_the_check_of_the_copy(across, extra_folder, monkeypatch):
    real = primitives.file_sha256

    def then_close(path, stop=None):
        across.executor.cancel_copies.set()
        return real(path, stop)

    monkeypatch.setattr(primitives, "file_sha256", then_close)
    result = _move(across)
    assert result.failed is not None and "stopped" in result.error
    assert not (extra_folder.root / "2010" / "a.pdf").exists()


def test_bytes_reported_through_one_file(across, monkeypatch):
    monkeypatch.setattr(primitives, "_COPY_CHUNK", 3)
    seen = []
    assert _move(across, copied=lambda rop, n: seen.append(n)).failed is None
    assert seen == [3, 6, 9, 10]


def _crash(*a, **k):
    raise SystemExit("simulated crash")


def test_crash_before_the_rename_needs_manual_check(
    across, fake_archive, extra_folder, monkeypatch
):
    from dam.ops.undo import MANUAL_CHECK

    monkeypatch.setattr(primitives, "rename_excl", _crash)
    with pytest.raises(SystemExit):
        _move(across)
    monkeypatch.undo()
    (row,) = _rows(across)
    assert row["state"] == "planned" and row["content_hash"] is not None
    (entry,) = [e for e in across.executor.recover().entries if e.kind == "copy_across"]
    assert (entry.state, entry.error) == ("failed", MANUAL_CHECK)
    assert len(_temps(extra_folder.root / "2010")) == 1
    assert (fake_archive.root / BANKS / "a.pdf").read_bytes() == DATA


def test_crash_after_the_rename_recovers_by_the_journaled_hash(across, extra_folder, monkeypatch):
    from dam.ops.executor import Executor

    real = Executor._verify

    def crash_after_copy(self, rop, snap):
        if rop.kind is OpKind.COPY_ACROSS:
            _crash()
        return real(self, rop, snap)

    monkeypatch.setattr(Executor, "_verify", crash_after_copy)
    with pytest.raises(SystemExit):
        _move(across)
    monkeypatch.undo()
    assert (extra_folder.root / "2010" / "a.pdf").read_bytes() == DATA
    (entry,) = [e for e in across.executor.recover().entries if e.kind == "copy_across"]
    assert (entry.state, entry.error) == ("done", None)
