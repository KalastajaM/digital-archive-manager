"""Scanner and executor share the index: they must not interleave inside one operation."""

import threading

from sqlalchemy import insert, select

from dam.config import Settings
from dam.core.paths import ArchivePaths
from dam.db.tables import file_tags, file_text
from dam.index import scanner
from dam.index.repo import FileRepo, TagRepo
from dam.index.scanner import scan
from dam.ops.executor import Executor
from dam.ops.model import Op, OpKind, Plan


def setup(fake_archive, engine):
    paths = ArchivePaths(fake_archive.root, Settings(archive_root=fake_archive.root))
    repo = FileRepo(engine, inbox=paths.inbox)
    return paths, repo, Executor(paths, engine, repo)


MOVE = Plan(ops=[Op(OpKind.MOVE, "##. Organize/a.pdf", "10. Financial/Banks")], origin="cli")


def test_scan_between_rename_and_index_update_does_not_orphan(fake_archive, engine, monkeypatch):
    fake_archive.add("##. Organize/a.pdf", drive_id=None)
    paths, repo, executor = setup(fake_archive, engine)
    scan(paths, repo)
    old = repo.by_path("##. Organize/a.pdf").drive_id
    with engine.begin() as conn:
        conn.execute(insert(file_text), {"drive_id": old, "text": "hello"})
    TagRepo(engine).add(old, ["keep"])

    scans: list[threading.Thread] = []
    real_act = executor._act

    def act_then_scan(rop, *args):
        real_act(rop, *args)  # the rename is on disk, the index still says the old path
        t = threading.Thread(target=scan, args=(paths, repo, "10. Financial/Banks"))
        t.start()
        scans.append(t)
        t.join(0.5)  # unlocked: the scan lands in the gap; locked: it waits for the op

    monkeypatch.setattr(executor, "_act", act_then_scan)
    result = executor.apply(MOVE)
    for t in scans:
        t.join(30)
    assert result.failed is None and result.index_error is None
    row = repo.by_path("10. Financial/Banks/a.pdf")
    assert row is not None and row.drive_id == old
    assert repo.by_path("##. Organize/a.pdf") is None
    with engine.connect() as conn:
        assert conn.execute(select(file_text).where(file_text.c.drive_id == old)).all()
        assert conn.execute(select(file_tags).where(file_tags.c.drive_id == old)).all()


def test_scan_cannot_apply_stale_data_while_an_op_is_in_flight(fake_archive, engine, monkeypatch):
    fake_archive.add("##. Organize/a.pdf")  # has a Drive id
    paths, repo, executor = setup(fake_archive, engine)
    scan(paths, repo)
    drive_id = repo.by_path("##. Organize/a.pdf").drive_id

    gathered, proceed = threading.Event(), threading.Event()
    real_gather = scanner._Scan.gather

    def slow_gather(self, rel, *args):
        item = real_gather(self, rel, *args)
        if rel.endswith("a.pdf"):
            gathered.set()
            proceed.wait(10)  # the gathered data now goes stale if the op may run
        return item

    monkeypatch.setattr(scanner._Scan, "gather", slow_gather)
    scanner_thread = threading.Thread(target=scan, args=(paths, repo, "##. Organize"))
    scanner_thread.start()
    assert gathered.wait(10)

    op_done = threading.Event()
    results = []

    def run_op():
        results.append(executor.apply(MOVE))
        op_done.set()

    op_thread = threading.Thread(target=run_op)
    op_thread.start()
    assert not op_done.wait(0.5), "executor op ran between the scanner's gather and apply"
    proceed.set()
    scanner_thread.join(30)
    op_thread.join(30)
    assert results and results[0].failed is None and results[0].index_error is None
    row = repo.by_path("10. Financial/Banks/a.pdf")
    assert row is not None and row.drive_id == drive_id
    assert repo.by_path("##. Organize/a.pdf") is None


def test_move_into_already_scanned_directory_is_not_marked_missing(
    fake_archive, engine, monkeypatch
):
    import os

    fake_archive.add("A/keep.pdf")
    fake_archive.add("B/x.pdf")
    paths, repo, executor = setup(fake_archive, engine)
    scan(paths, repo)
    drive_id = repo.by_path("B/x.pdf").drive_id

    real_scandir = os.scandir
    ran = []

    def scandir(path="."):
        # Directory A is already scanned; an op now moves B/x.pdf into it before B is read.
        if os.path.basename(path) == "B" and not ran:
            ran.append(None)  # set first: the op itself lists directories
            ran[0] = executor.apply(Plan(ops=[Op(OpKind.MOVE, "B/x.pdf", "A")], origin="cli"))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)
    scan(paths, repo)
    monkeypatch.undo()
    assert ran and ran[0].failed is None and ran[0].index_error is None
    row = repo.by_path("A/x.pdf")
    assert row is not None and row.drive_id == drive_id and not row.missing
