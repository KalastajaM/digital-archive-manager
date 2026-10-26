"""Undo, crash recovery and relabel of a folder moved across disks: the folder comes back
from To Delete with its rows, the copies go to the other disk's To Delete, the made
folders are removed while empty."""

import json
import os

import pytest
import xattr
from sqlalchemy import select, text

from dam import relabel
from dam.app import App
from dam.db.engine import make_engine
from dam.db.tables import operations
from dam.index.driveid import DRIVE_ID_XATTR
from dam.ops import executor as executor_module
from dam.ops import primitives
from dam.ops import undo as journal
from dam.ops.model import OpFailed, OpKind
from dam.ops.primitives import PRESENT
from dam.ops.undo import MANUAL_CHECK

HOME = "20. Home"
SRC = f"{HOME}/2009"
DEST = "Old years"
COPY = f"{DEST}/2009"
QUAR = "##. To Delete"
PATHS = (SRC, f"{SRC}/sub", f"{SRC}/empty", f"{SRC}/a.pdf", f"{SRC}/sub/b.pdf")


def _fill(app, fake_archive, extra_folder) -> dict[str, str]:
    """``20. Home/2009/{a.pdf, sub/b.pdf, empty/}``, a Drive id on the folder, a tag on
    a.pdf and the folder in a collection. Returns each path's row id."""
    fake_archive.add(f"{SRC}/a.pdf", b"aaaa", drive_id="id-a")
    fake_archive.add(f"{SRC}/sub/b.pdf", b"bb", drive_id="id-b")
    (fake_archive.root / SRC / "empty").mkdir()
    xattr.setxattr(fake_archive.root / SRC, DRIVE_ID_XATTR, b"id-dir")
    extra_folder.add("keep.pdf", b"k", drive_id="x1")
    app.scan()
    app.tags.add("id-a", ["bank"])
    col = app.collections.create("Years")
    app.collections.add_members(col.id, ["id-dir"])
    return {p: app.repo.by_path(p).drive_id for p in PATHS}


@pytest.fixture
def ids(extra_folder, app, fake_archive, monkeypatch):
    found = _fill(app, fake_archive, extra_folder)
    monkeypatch.setattr(primitives, "same_disk", lambda a, b: False)
    return found


@pytest.fixture
def across(ids, app):
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


def _stop_after_first(app, monkeypatch):
    """The job stops once its first file is copied."""
    real = app.executor.apply

    def apply(plan, **kw):
        if kw.get("should_stop") is not None:
            ask, progress = kw["should_stop"], kw.get("progress")
            seen = {"copies": 0}

            def on_progress(rop, index, ops):
                if rop.kind is OpKind.COPY_ACROSS:
                    seen["copies"] += 1
                if progress is not None:
                    progress(rop, index, ops)

            kw["progress"] = on_progress
            kw["should_stop"] = lambda: seen["copies"] >= 1 or ask()
        return real(plan, **kw)

    monkeypatch.setattr(app.executor, "apply", apply)
    return real


def _crash_at(monkeypatch, hit):
    """The process dies right before acting on the op ``hit`` picks: its row stays
    ``planned``."""
    real = executor_module.Executor._act

    def act(self, rop, copied=None):
        if hit(rop):
            raise RuntimeError("the computer went off")
        return real(self, rop, copied)

    monkeypatch.setattr(executor_module.Executor, "_act", act)


def _assert_back(app, fake_archive, extra_folder, ids):
    """The source is whole again with its rows and ids; the copies are in Old years' To
    Delete and the made folders are gone."""
    src = fake_archive.root / SRC
    assert (src / "a.pdf").read_bytes() == b"aaaa"
    assert (src / "sub" / "b.pdf").read_bytes() == b"bb"
    assert (src / "empty").is_dir()
    assert not (fake_archive.root / QUAR / SRC).exists()
    aside = extra_folder.root / QUAR / "2009"
    assert (aside / "a.pdf").read_bytes() == b"aaaa"
    assert (aside / "sub" / "b.pdf").read_bytes() == b"bb"
    assert not (extra_folder.root / "2009").exists()
    for path, drive_id in ids.items():
        row = app.repo.by_path(path)
        assert row is not None and row.drive_id == drive_id, path
    assert app.repo.by_path(COPY) is None
    assert app.tags.for_file("id-a") == ["bank"]
    assert [c.name for c in app.collections.for_file("id-dir")] == ["Years"]


def test_undo_folder_move_across(across, ids, fake_archive, extra_folder):
    batch = _move(across).result
    assert batch.failed is None, batch.error
    undone = across.executor.undo(batch.batch_id)
    assert undone.failed is None, undone.error
    assert undone.kept == []
    _assert_back(across, fake_archive, extra_folder, ids)
    states = {e.state for e in _journal(across, batch.batch_id)}
    assert states == {"undone"}


def test_undo_after_scan_keeps_folder_collection(across, ids, fake_archive, extra_folder):
    batch = _move(across).result
    across.scan()  # the original in To Delete and the copy are both indexed
    undone = across.executor.undo(batch.batch_id)
    assert undone.failed is None, undone.error
    _assert_back(across, fake_archive, extra_folder, ids)
    with across.engine.connect() as conn:
        paths = conn.execute(text("SELECT path FROM files")).scalars().all()
    assert len(paths) == len(set(paths))
    assert not [p for p in paths if p.startswith(f"{QUAR}/{SRC}")]
    across.scan()
    assert across.repo.by_path(SRC).drive_id == "id-dir"
    assert [c.name for c in across.collections.for_file("id-dir")] == ["Years"]


def test_undo_keeps_nonempty_made_folder(across, ids, fake_archive, extra_folder):
    batch = _move(across).result
    (extra_folder.root / "2009" / "new.pdf").write_bytes(b"n")
    undone = across.executor.undo(batch.batch_id)
    assert undone.failed is None, undone.error
    assert undone.kept == [COPY]
    assert (extra_folder.root / "2009" / "new.pdf").read_bytes() == b"n"
    assert not (extra_folder.root / "2009" / "a.pdf").exists()
    assert not (extra_folder.root / "2009" / "sub").exists()
    assert not (extra_folder.root / "2009" / "empty").exists()
    assert (fake_archive.root / SRC / "a.pdf").exists()
    assert across.repo.by_path(SRC).drive_id == "id-dir"


def test_undo_of_stopped_batch(across, ids, fake_archive, extra_folder, monkeypatch):
    _stop_after_first(across, monkeypatch)
    batch = _move(across).result
    assert batch.stopped
    undone = across.executor.undo(batch.batch_id)
    assert undone.failed is None, undone.error
    assert (extra_folder.root / QUAR / "2009" / "a.pdf").read_bytes() == b"aaaa"
    assert not (extra_folder.root / "2009").exists()
    assert (fake_archive.root / SRC / "a.pdf").read_bytes() == b"aaaa"
    assert (fake_archive.root / SRC / "sub" / "b.pdf").exists()
    assert (fake_archive.root / SRC / "empty").is_dir()
    for path, drive_id in ids.items():
        assert across.repo.by_path(path).drive_id == drive_id, path
    assert across.tags.for_file("id-a") == ["bank"]


def test_present_has_no_inverse(across, ids, fake_archive, extra_folder, monkeypatch):
    real = _stop_after_first(across, monkeypatch)
    first = _move(across).result
    assert first.stopped
    monkeypatch.setattr(across.executor, "apply", real)
    across.scan()
    second = _move(across).result
    assert second.failed is None, second.error
    undone = across.executor.undo(second.batch_id)
    assert undone.failed is None, undone.error
    copy = extra_folder.root / "2009"
    assert (copy / "a.pdf").read_bytes() == b"aaaa"  # the first batch's copy stays
    assert not (copy / "sub" / "b.pdf").exists()
    assert (extra_folder.root / QUAR / "2009" / "sub" / "b.pdf").exists()
    assert (fake_archive.root / SRC / "a.pdf").exists()
    assert (fake_archive.root / SRC / "sub" / "b.pdf").exists()
    rows = _journal(across, second.batch_id)
    assert {e.state for e in rows if e.method == PRESENT} == {"undone"}
    assert not [e for e in _journal(across, undone.batch_id) if e.src == f"{COPY}/a.pdf"]
    again = across.executor.undo(first.batch_id)
    assert again.failed is None, again.error
    _assert_back(across, fake_archive, extra_folder, ids)


def test_recover_final_quarantine_rows_follow(across, ids, fake_archive, monkeypatch):
    _crash_at(monkeypatch, lambda rop: rop.kind is OpKind.QUARANTINE and rop.tree is not None)
    job = _move(across)
    assert job.state == "error"
    batch_id = journal.pending(across.executor)[0].batch_id
    (final,) = [e for e in _journal(across, batch_id) if e.kind == "quarantine"]
    assert final.state == "planned" and final.followed is None
    os.rename(fake_archive.root / SRC, fake_archive.root / QUAR / SRC)  # it did happen
    result = across.executor.recover()
    assert result.index_errors == []
    (entry,) = [e for e in result.entries if e.kind == "quarantine"]
    assert entry.state == "done"
    (final,) = [e for e in _journal(across, batch_id) if e.kind == "quarantine"]
    assert {f[3] for f in json.loads(final.followed)} == {COPY, f"{COPY}/sub", f"{COPY}/empty"}
    folder = across.repo.by_path(COPY)
    assert folder is not None and folder.is_dir
    assert [c.name for c in across.collections.for_file(folder.drive_id)] == ["Years"]
    assert across.repo.by_path(f"{COPY}/sub").is_dir
    assert across.repo.by_path(SRC) is None


@pytest.mark.parametrize("same", [True, False])
def test_recover_present_row(across, ids, fake_archive, extra_folder, monkeypatch, same):
    real = _stop_after_first(across, monkeypatch)
    assert _move(across).result.stopped
    monkeypatch.setattr(across.executor, "apply", real)
    across.scan()
    _crash_at(monkeypatch, lambda rop: rop.method == PRESENT)
    assert _move(across).state == "error"
    if not same:
        copy = extra_folder.root / "2009" / "a.pdf"
        st = os.stat(copy)
        copy.write_bytes(b"zzzz")
        os.utime(copy, ns=(st.st_atime_ns, st.st_mtime_ns))
    result = across.executor.recover()
    assert result.index_errors == []
    (entry,) = [e for e in result.entries if e.method == PRESENT]
    assert (entry.state, entry.error) == (("done", None) if same else ("failed", MANUAL_CHECK))
    assert (fake_archive.root / SRC / "a.pdf").exists()
    a = across.repo.by_path(f"{COPY}/a.pdf")
    assert across.tags.for_file(a.drive_id) == ["bank"]


def test_relabel_rewrites_copied_to(app_paths, extra_folder, fake_archive, monkeypatch):
    monkeypatch.setattr(primitives, "same_disk", lambda a, b: False)
    app = App.create(app_paths.data_dir)
    try:
        ids = _fill(app, fake_archive, extra_folder)
        batch = _move(app).result
        assert batch.failed is None, batch.error
    finally:
        app.close()
    engine = make_engine(app_paths.db_path)
    try:
        plan = relabel.plan(app_paths, engine, "Old years", "Archive 2000s")
        relabel.apply(app_paths, engine, plan)
        with engine.connect() as conn:
            copied_to, followed = conn.execute(
                select(operations.c.copied_to, operations.c.followed).where(
                    operations.c.batch_id == batch.batch_id, operations.c.kind == "quarantine"
                )
            ).one()
    finally:
        engine.dispose()
    assert copied_to == "Archive 2000s/2009"
    entries = json.loads(followed)
    assert entries and all(e[3].startswith("Archive 2000s/2009") for e in entries)
    assert all(e[2].startswith(SRC) for e in entries)
    app = App.create(app_paths.data_dir)
    try:
        undone = app.executor.undo(batch.batch_id)
        assert undone.failed is None, undone.error
        for path, drive_id in ids.items():
            assert app.repo.by_path(path).drive_id == drive_id, path
        assert [c.name for c in app.collections.for_file("id-dir")] == ["Years"]
        assert app.repo.by_path("Archive 2000s/2009") is None
    finally:
        app.close()
    assert (extra_folder.root / QUAR / "2009" / "a.pdf").exists()
    assert not (extra_folder.root / "2009").exists()


def test_recover_done_quarantine_whose_rows_never_followed(across, ids, monkeypatch):
    """The folder went to To Delete but its index step failed before ``followed`` was
    journaled: recovery plans, journals and applies it."""
    from sqlalchemy.exc import SQLAlchemyError

    def broken(self, src, dst_root):
        raise SQLAlchemyError("disk I/O error")

    monkeypatch.setattr(executor_module.Executor, "_follow_folder_rows", broken)
    batch = _move(across).result
    assert batch.index_error is not None
    (final,) = [e for e in _journal(across, batch.batch_id) if e.kind == "quarantine"]
    assert final.state == "done" and final.followed is None
    monkeypatch.undo()
    monkeypatch.setattr(primitives, "same_disk", lambda a, b: False)
    result = across.executor.recover()
    assert result.index_errors == [] and result.entries == []
    (final,) = [e for e in _journal(across, batch.batch_id) if e.kind == "quarantine"]
    assert len(json.loads(final.followed)) == 3
    folder = across.repo.by_path(COPY)
    assert [c.name for c in across.collections.for_file(folder.drive_id)] == ["Years"]
    assert across.repo.by_path(SRC) is None
    across.executor.recover()  # again: nothing changes
    assert across.repo.by_path(COPY).drive_id == folder.drive_id


def _tree(*roots) -> list[str]:
    return sorted(str(p) for root in roots for p in root.rglob("*"))


def test_undo_of_stopped_batch_refused_while_a_later_move_relies_on_it(
    across, ids, fake_archive, extra_folder, monkeypatch
):
    """The second move found the first batch's copy present and sent the original to To
    Delete: undoing the first batch now would put the only live copy in To Delete too."""
    real = _stop_after_first(across, monkeypatch)
    first = _move(across).result
    assert first.stopped
    monkeypatch.setattr(across.executor, "apply", real)
    across.scan()
    second = _move(across).result
    assert second.failed is None, second.error
    before = _tree(fake_archive.root, extra_folder.root)
    states = [e.state for e in _journal(across, first.batch_id)]
    for attempt in (across.executor.preview_undo, across.executor.undo):
        with pytest.raises(OpFailed) as refused:
            attempt(first.batch_id)
        assert str(refused.value) == "Undo the later move of 2009 first."
    assert _tree(fake_archive.root, extra_folder.root) == before
    assert [e.state for e in _journal(across, first.batch_id)] == states
    assert (extra_folder.root / "2009" / "a.pdf").read_bytes() == b"aaaa"
    undone = across.executor.undo(second.batch_id)
    assert undone.failed is None, undone.error
    again = across.executor.undo(first.batch_id)
    assert again.failed is None, again.error
    _assert_back(across, fake_archive, extra_folder, ids)
