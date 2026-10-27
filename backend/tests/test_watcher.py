import os
import threading
import time
from pathlib import Path

from watchdog.events import DirCreatedEvent, DirModifiedEvent, FileMovedEvent

from dam.config import Settings
from dam.core.paths import ArchivePaths
from dam.index import watcher as watcher_mod
from dam.index.own_changes import OwnChanges
from dam.index.repo import FileRepo
from dam.index.watcher import Watcher, _Handler, _scope, _scopes
from dam.ops.executor import Executor
from dam.ops.model import Op, OpKind, Plan


def setup(fake_archive, engine):
    paths = ArchivePaths(fake_archive.root, Settings(archive_root=fake_archive.root))
    return paths, FileRepo(engine, inbox=paths.inbox)


def wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    done = threading.Event()
    while time.monotonic() < deadline:
        if predicate():
            return True
        done.wait(0.05)
    return predicate()


def test_scope_is_deepest_common_folder():
    assert _scope(["a/b/c.pdf", "a/b/d.pdf"]) == "a/b"
    assert _scope(["a/b/c.pdf", "a/x/d.pdf"]) == "a"
    assert _scope(["a/b"]) == "a/b"
    assert _scope(["a/b/c", "a/b"]) == "a/b"
    assert _scope(["a/b.pdf", "c/d.pdf"]) == ""
    assert _scope(["x.pdf", "y.pdf"]) == ""
    assert _scope(["x.pdf"]) == "x.pdf"


def test_new_inbox_file_is_scanned(fake_archive, engine):
    paths, repo = setup(fake_archive, engine)
    changed = threading.Event()
    w = Watcher(paths, repo, on_change=changed.set, debounce_s=0.2)
    w.start()
    try:
        fake_archive.add("##. Organize/new.pdf")
        assert wait_for(lambda: repo.by_path("##. Organize/new.pdf") is not None, 5)
        assert changed.wait(5)
    finally:
        w.stop()


def test_stop_is_clean(fake_archive, engine):
    paths, repo = setup(fake_archive, engine)
    w = Watcher(paths, repo, debounce_s=0.1, reconcile_every_s=60)
    before = threading.active_count()
    w.start()
    w.stop()
    assert threading.active_count() <= before
    w.stop()  # idempotent


def test_ignored_names_never_reach_pending_or_scan(fake_archive, engine, monkeypatch):
    paths, repo = setup(fake_archive, engine)
    calls = []
    monkeypatch.setattr(watcher_mod, "scan", lambda *a, **k: calls.append((a, k)))
    w = Watcher(paths, repo, debounce_s=0.1, reconcile_every_s=3600)
    for name in (".DS_Store", "x.tmp", "~$doc.docx", ".tmp.driveupload/part"):
        w._note(str(fake_archive.root / "##. Organize" / name))
    assert not w._pending
    w.start()
    try:
        fake_archive.add("##. Organize/.DS_Store", drive_id=None)
        fake_archive.add("##. Organize/x.tmp", drive_id=None)
        fake_archive.add("##. Organize/real.pdf")
        assert wait_for(lambda: bool(calls))
    finally:
        w.stop()
    for _, k in calls:
        assert not any(bad in k["subtree"] for bad in (".DS_Store", ".tmp", "~$"))
    assert not w._pending


def test_scan_exception_does_not_kill_watcher(fake_archive, engine, monkeypatch, caplog):
    paths, repo = setup(fake_archive, engine)
    real = watcher_mod.scan
    state = {"raised": False}

    def flaky(*args, **kwargs):
        if not state["raised"]:
            state["raised"] = True
            raise RuntimeError("boom")
        return real(*args, **kwargs)

    monkeypatch.setattr(watcher_mod, "scan", flaky)
    w = Watcher(paths, repo, debounce_s=0.1, reconcile_every_s=3600)
    w.start()
    try:
        fake_archive.add("##. Organize/first.pdf")
        assert wait_for(lambda: state["raised"])
        fake_archive.add("##. Organize/second.pdf")
        assert wait_for(lambda: repo.by_path("##. Organize/second.pdf") is not None)
    finally:
        w.stop()
    assert any("boom" in (r.exc_text or "") for r in caplog.records)


def test_reconcile_timer_runs_full_scan(fake_archive, engine, monkeypatch):
    paths, repo = setup(fake_archive, engine)
    calls = []
    monkeypatch.setattr(watcher_mod, "scan", lambda *a, **k: calls.append((a, k)))
    w = Watcher(paths, repo, debounce_s=0.1, reconcile_every_s=0.1)
    w.start()
    try:
        assert wait_for(lambda: len(calls) >= 2)
    finally:
        w.stop()
    assert all(not k.get("subtree") for _, k in calls)


def test_continuous_events_do_not_starve_scans(fake_archive, engine, monkeypatch):
    paths, repo = setup(fake_archive, engine)
    scanned = threading.Event()
    monkeypatch.setattr(watcher_mod, "scan", lambda *a, **k: scanned.set())
    w = Watcher(paths, repo, debounce_s=0.5, reconcile_every_s=3600, max_wait_s=1.5)
    w.start()
    try:
        start = time.monotonic()
        i = 0
        while not scanned.is_set() and time.monotonic() - start < 6:
            w._note(str(fake_archive.root / "##. Organize" / f"f{i}.pdf"))  # faster than debounce
            i += 1
            scanned.wait(0.1)
        assert scanned.is_set()
        assert time.monotonic() - start < 4
    finally:
        w.stop()


def test_default_max_wait(fake_archive, engine):
    paths, repo = setup(fake_archive, engine)
    assert Watcher(paths, repo, debounce_s=1.0).max_wait_s == 30.0
    assert Watcher(paths, repo, debounce_s=5.0).max_wait_s == 50.0
    assert Watcher(paths, repo, debounce_s=1.0, max_wait_s=7).max_wait_s == 7


def test_failed_batch_is_retried_without_new_events(fake_archive, engine, monkeypatch):
    paths, repo = setup(fake_archive, engine)
    real = watcher_mod.scan
    state = {"raised": False}

    def flaky(*args, **kwargs):
        if not state["raised"]:
            state["raised"] = True
            raise RuntimeError("boom")
        return real(*args, **kwargs)

    monkeypatch.setattr(watcher_mod, "scan", flaky)
    fake_archive.add("##. Organize/late.pdf")  # on disk before the watcher exists
    w = Watcher(paths, repo, debounce_s=0.1, reconcile_every_s=3600)
    w.start()
    try:
        w._note(str(fake_archive.root / "##. Organize" / "late.pdf"))  # the only event
        assert wait_for(lambda: repo.by_path("##. Organize/late.pdf") is not None)
    finally:
        w.stop()
    assert state["raised"]


def test_on_change_failure_is_logged_and_not_requeued(fake_archive, engine, monkeypatch, caplog):
    paths, repo = setup(fake_archive, engine)
    scans = []
    called = threading.Event()
    monkeypatch.setattr(watcher_mod, "scan", lambda *a, **k: scans.append(1))

    def bad_on_change():
        called.set()
        raise RuntimeError("callback boom")

    w = Watcher(paths, repo, on_change=bad_on_change, debounce_s=0.05, reconcile_every_s=3600)
    w.start()
    try:
        w._note(str(fake_archive.root / "##. Organize" / "a.pdf"))
        assert called.wait(5)
        threading.Event().wait(0.5)  # a (wrong) requeue would rescan within this time
    finally:
        w.stop()
    assert len(scans) == 1
    assert any("callback boom" in (r.exc_text or "") for r in caplog.records)


def test_failing_batch_backs_off_and_logs_traceback_once(fake_archive, engine, monkeypatch, caplog):
    paths, repo = setup(fake_archive, engine)
    times = []

    def always_fails(*a, **k):
        times.append(w._backoff)  # the retry delay scheduled after the previous failure
        raise RuntimeError("still broken")

    monkeypatch.setattr(watcher_mod, "scan", always_fails)
    w = Watcher(paths, repo, debounce_s=0.05, reconcile_every_s=3600)
    w.start()
    try:
        w._note(str(fake_archive.root / "##. Organize" / "a.pdf"))
        assert wait_for(lambda: len(times) >= 4)
    finally:
        w.stop()
    # the delay doubles while the batch keeps failing (a scheduled value, not wall clock)
    assert times[:4] == [0.0, 0.05, 0.1, 0.2]
    with_tb = [r for r in caplog.records if r.exc_info]
    assert len(with_tb) == 1
    assert any(
        r.levelname == "WARNING" and "still broken" in r.getMessage() for r in caplog.records
    )


def test_reconcile_with_archive_gone_warns_and_keeps_index(fake_archive, engine, tmp_path, caplog):
    import logging

    fake_archive.add("##. Organize/a.pdf", drive_id="id-a")
    paths, repo = setup(fake_archive, engine)
    watcher_mod.scan(paths, repo)
    os.rename(fake_archive.root, tmp_path / "archive-away")
    changed = threading.Event()
    w = Watcher(paths, repo, on_change=changed.set, debounce_s=0.1, reconcile_every_s=0.1)
    with caplog.at_level(logging.WARNING, logger="dam.index.watcher"):
        w._started = True  # no observer on a vanished folder; run only the reconcile loop
        t = threading.Thread(target=w._reconcile_loop, daemon=True)
        t.start()
        try:
            assert wait_for(lambda: any("not available" in r.message for r in caplog.records))
        finally:
            w._stop.set()
            t.join(5)
    assert repo.get("id-a").missing is False
    assert not changed.is_set()


def test_file_dropped_into_a_code_folder_shows_in_the_inbox_with_its_code(app, fake_archive):
    folder = fake_archive.root / "##. Organize" / "To pay"
    folder.mkdir(parents=True)
    w = Watcher(app.paths, app.repo, debounce_s=0.2, reconcile_every_s=3600)
    w.start()
    try:
        fake_archive.add("##. Organize/To pay/bill.pdf", drive_id="b1")
        assert wait_for(lambda: app.repo.by_path("##. Organize/To pay/bill.pdf") is not None, 5)
    finally:
        w.stop()
    [entry] = app.inbox.list()
    assert entry.record.drive_id == "b1"
    assert [h.code for h in entry.suggestion.codes] == ["P"]
    assert entry.suggestion.tray == "to-pay"


# --- extra archive folders ----------------------------------------------------


def setup_with_extra(fake_archive, engine, tmp_path):
    from dam.config import ExtraFolder

    extra = tmp_path / "disk" / "Archive 2000-2015"
    (extra / "2009").mkdir(parents=True)
    settings = Settings(
        archive_root=fake_archive.root,
        extra_folders=[ExtraFolder(label="Old years", path=extra)],
    )
    paths = ArchivePaths(fake_archive.root, settings)
    return paths, FileRepo(engine, inbox=paths.inbox), extra


def _watched(w):
    return sorted(str(Path(watch.path).resolve()) for watch in w._watches.values())


def test_refresh_watches_follows_connect_and_disconnect(fake_archive, engine, tmp_path):
    paths, repo, extra = setup_with_extra(fake_archive, engine, tmp_path)
    w = Watcher(paths, repo)
    try:
        # Starting the observer is not needed: scheduling works on a stopped one.
        assert w.refresh_watches() == []  # the first call only sets up the initial watches
        both = sorted([str(paths.root), str(extra.resolve())])
        assert _watched(w) == both
        assert w.refresh_watches() == []

        gone = extra.with_name("away")
        os.rename(extra, gone)
        assert w.refresh_watches() == []
        assert _watched(w) == [str(paths.root)]

        os.rename(gone, extra)
        assert w.refresh_watches() == ["Old years"]
        assert _watched(w) == both
        assert w.refresh_watches() == []
    finally:
        w.stop()


def test_change_in_extra_folder_is_noted(fake_archive, engine, tmp_path):
    paths, repo, extra = setup_with_extra(fake_archive, engine, tmp_path)
    w = Watcher(paths, repo)
    w._note(str(extra.resolve() / "2009" / "a.pdf"))
    assert set(w._pending) == {"Old years/2009/a.pdf"}


def test_refresh_watches_survives_events_while_toggling(fake_archive, engine, tmp_path):
    paths, repo, extra = setup_with_extra(fake_archive, engine, tmp_path)
    w = Watcher(paths, repo, debounce_s=0.05, reconcile_every_s=3600, folder_check_s=3600)
    w.start()
    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            (fake_archive.root / "##. Organize").mkdir(exist_ok=True)
            (fake_archive.root / "##. Organize" / f"f{i}.txt").write_bytes(b"x")
            i += 1

    def toggle():
        gone = extra.with_name("away")
        for _ in range(15):
            os.rename(extra, gone)
            w.refresh_watches()
            os.rename(gone, extra)
            w.refresh_watches()

    t = threading.Thread(target=writer, daemon=True)
    worker = threading.Thread(target=toggle, daemon=True)
    t.start()
    worker.start()
    worker.join(30)
    stop.set()
    t.join(5)
    hung = worker.is_alive()
    w.stop()
    assert not hung, "refresh_watches deadlocked against event delivery"


def test_unschedule_failure_does_not_abort_or_leak(fake_archive, engine, tmp_path, monkeypatch):
    paths, repo, extra = setup_with_extra(fake_archive, engine, tmp_path)
    w = Watcher(paths, repo)
    w.refresh_watches()

    def boom(watch):
        raise RuntimeError("boom")

    monkeypatch.setattr(w._observer, "unschedule", boom)
    gone = extra.with_name("away")
    os.rename(extra, gone)
    assert w.refresh_watches() == []
    assert "Old years" not in w._watches


def test_folders_loop_rescans_a_folder_that_comes_back(fake_archive, engine, tmp_path):
    paths, repo, extra = setup_with_extra(fake_archive, engine, tmp_path)
    changed = threading.Event()
    w = Watcher(
        paths,
        repo,
        on_change=changed.set,
        debounce_s=0.1,
        reconcile_every_s=3600,
        folder_check_s=0.1,
    )
    w.start()
    try:
        gone = extra.with_name("away")
        os.rename(extra, gone)
        assert wait_for(lambda: "Old years" not in w._watches, 5)
        (gone / "2009" / "a.pdf").write_bytes(b"x")
        os.rename(gone, extra)
        assert wait_for(lambda: repo.by_path("Old years/2009/a.pdf") is not None, 5)
        assert changed.wait(5)
    finally:
        w.stop()


def test_a_stopped_watcher_calls_no_on_change(fake_archive, engine):
    paths, repo = setup(fake_archive, engine)
    calls = []
    w = Watcher(paths, repo, on_change=lambda: calls.append(1))
    w._call_on_change()
    assert calls == [1]
    w.stop()
    w._call_on_change()  # a scan that finished after stop(), as after a reopen
    assert calls == [1]


def test_a_folder_that_cannot_be_watched_is_tried_again_less_often(
    fake_archive, engine, tmp_path, monkeypatch
):
    """A failed watch (on Linux: no inotify watches left) is not retried every check."""
    paths, repo, extra = setup_with_extra(fake_archive, engine, tmp_path)
    w = Watcher(paths, repo, folder_check_s=30)
    real = w._observer.schedule
    tries = []

    def schedule(handler, path, recursive):
        if Path(path).resolve() == extra.resolve():
            tries.append(path)
            if len(tries) < 3:
                raise OSError(28, "inotify watch limit reached")
        return real(handler, path, recursive=recursive)

    monkeypatch.setattr(w._observer, "schedule", schedule)
    try:
        assert w.refresh_watches() == []
        assert w._watch_retry["Old years"][1] == 30
        assert w.refresh_watches() == []
        assert len(tries) == 1  # still waiting
        w._watch_retry["Old years"] = (0.0, 30)  # the wait is over
        assert w.refresh_watches() == []
        assert len(tries) == 2
        assert w._watch_retry["Old years"][1] == 60  # waits twice as long now
        w._watch_retry["Old years"] = (0.0, 60)
        assert w.refresh_watches() == ["Old years"]
        assert "Old years" not in w._watch_retry
        assert "Old years" in w._watches
    finally:
        w.stop()


def test_a_folder_that_comes_back_is_read_again_without_waiting(fake_archive, engine, tmp_path):
    """Files that could not be read while the folder was away lose their retry wait."""
    from dam.index.repo import FileRecord

    paths, repo, extra = setup_with_extra(fake_archive, engine, tmp_path)
    (extra / "2009" / "a.pdf").write_bytes(b"x")
    st = (extra / "2009" / "a.pdf").stat()
    later = time.time() + 3600
    repo.upsert(
        FileRecord(
            drive_id="x1",
            path="Old years/2009/a.pdf",
            size=st.st_size,
            mtime=st.st_mtime,
            index_state="cloud_pending",
            retry_at=later,
            attempts=5,
        )
    )
    repo.upsert(
        FileRecord(drive_id="m1", path="elsewhere.pdf", index_state="cloud_pending", retry_at=later)
    )
    w = Watcher(paths, repo, debounce_s=0.1, reconcile_every_s=3600, folder_check_s=0.1)
    w.start()
    try:
        gone = extra.with_name("away")
        os.rename(extra, gone)
        assert wait_for(lambda: "Old years" not in w._watches, 5)
        os.rename(gone, extra)
        assert wait_for(lambda: repo.get("x1").retry_at is None, 5)
        assert repo.get("x1").attempts == 0
        assert repo.get("m1").retry_at == later  # other folders keep their wait
    finally:
        w.stop()


def test_stop_waits_at_most_the_timeout_in_all(fake_archive, engine):
    paths, repo = setup(fake_archive, engine)
    w = Watcher(paths, repo)
    hold = threading.Event()
    w._threads = [threading.Thread(target=hold.wait, daemon=True) for _ in range(3)]
    for t in w._threads:
        t.start()
    began = time.monotonic()
    w.stop(timeout=0.3)
    assert time.monotonic() - began < 2
    hold.set()


# --- scoped scans and the app's own moves -------------------------------------


def _main(rel):
    return ""


def _old_years(rel):
    return "Old years" if rel.split("/")[0] == "Old years" else ""


def test_scopes_scan_each_changed_path_not_their_common_folder():
    assert _scopes(["##. Organize/a.pdf", "10. Financial/Banks/a.pdf"], _main) == [
        "##. Organize/a.pdf",
        "10. Financial/Banks/a.pdf",
    ]
    # a path inside another changed path is covered by that path's scan
    assert _scopes(["a/b", "a/b/c.pdf", "a/b c.pdf", "a/b"], _main) == ["a/b", "a/b c.pdf"]
    assert _scopes(["x.pdf"], _main) == ["x.pdf"]
    assert _scopes(["x.pdf", "Old years/2009/a.pdf"], _old_years) == [
        "Old years/2009/a.pdf",
        "x.pdf",
    ]


def test_scopes_fall_back_per_root_for_many_paths():
    many = [f"a/{i}/f.pdf" for i in range(51)]
    assert _scopes(many, _main) == ["a"]
    assert len(_scopes(many[:50], _main)) == 50
    # spread over the main folder's top level: each top-level entry, never the whole archive
    spread = [f"{i % 3}/{i}/f.pdf" for i in range(51)]
    assert _scopes(spread, _main) == ["0", "1", "2"]
    # two folders: each gets its own fallback, never one scan of every folder
    both = [f"a/{i}.pdf" for i in range(30)] + [f"Old years/2009/{i}.pdf" for i in range(30)]
    assert _scopes(both, _old_years) == ["Old years/2009", "a"]
    assert "" not in _scopes([f"{i}.pdf" for i in range(60)], _main)


def _unwatched(w):
    """No folder watches: only the events a test notes itself reach the watcher."""
    w.refresh_watches = lambda: []
    return w


def _recording(monkeypatch):
    subtrees = []
    monkeypatch.setattr(watcher_mod, "scan", lambda *a, **k: subtrees.append(k["subtree"]))
    return subtrees


def test_changes_in_two_top_level_folders_scan_two_scopes_not_the_root(
    fake_archive, engine, monkeypatch
):
    paths, repo = setup(fake_archive, engine)
    subtrees = _recording(monkeypatch)
    fake_archive.add("10. Financial/Banks/a.pdf")  # the destination exists, the source not
    w = _unwatched(Watcher(paths, repo, debounce_s=0.05, reconcile_every_s=3600))
    w._note(str(fake_archive.root / "##. Organize" / "a.pdf"))
    w._note(str(fake_archive.root / "10. Financial" / "Banks" / "a.pdf"))
    w.start()
    try:
        assert wait_for(lambda: len(subtrees) >= 2)
    finally:
        w.stop()
    # the path still on disk first, so a moved row is re-pathed before its old path's
    # scan could mark it missing
    assert subtrees == ["10. Financial/Banks/a.pdf", "##. Organize/a.pdf"]


def test_changes_in_two_archive_folders_never_scan_every_folder(
    fake_archive, engine, tmp_path, monkeypatch
):
    paths, repo, extra = setup_with_extra(fake_archive, engine, tmp_path)
    subtrees = _recording(monkeypatch)
    (extra / "2009" / "a.pdf").write_bytes(b"x")
    w = _unwatched(Watcher(paths, repo, debounce_s=0.05, reconcile_every_s=3600))
    w._note(str(fake_archive.root / "##. Organize" / "a.pdf"))
    w._note(str(extra.resolve() / "2009" / "a.pdf"))
    w.start()
    try:
        assert wait_for(lambda: len(subtrees) >= 2)
    finally:
        w.stop()
    assert subtrees == ["Old years/2009/a.pdf", "##. Organize/a.pdf"]


def test_filing_across_top_level_folders_keeps_the_index_right(fake_archive, engine):
    fake_archive.add("##. Organize/a.pdf", drive_id="id-a")
    paths, repo = setup(fake_archive, engine)
    watcher_mod.scan(paths, repo)
    (fake_archive.root / "20. Home").mkdir()
    root = fake_archive.root
    os.rename(root / "##. Organize" / "a.pdf", root / "20. Home" / "a.pdf")
    w = _unwatched(Watcher(paths, repo, debounce_s=0.05, reconcile_every_s=3600))
    w._note(str(root / "##. Organize" / "a.pdf"))
    w._note(str(root / "20. Home" / "a.pdf"))
    w._note(str(root / "20. Home"))
    w.start()
    try:
        assert wait_for(lambda: repo.get("id-a").path == "20. Home/a.pdf")
    finally:
        w.stop()
    assert repo.get("id-a").missing is False
    assert repo.by_path("20. Home").is_dir


def test_own_changes_expire():
    now = [100.0]
    own = OwnChanges(ttl_s=10, clock=lambda: now[0])
    own.add(["##. Organize/a.pdf", "10. Financial/Banks/a.pdf"])
    assert own.covers("##. Organize/a.pdf")
    assert own.covers("10. Financial/Banks/a.pdf")
    assert not own.covers("10. Financial/Banks/b.pdf")
    assert not own.covers("10. Financial/Banks/a.pdf/inner")  # a file has nothing below it
    # a folder whose listing changed only because of our own change
    assert own.covers("10. Financial/Banks", dir_modified=True)
    assert own.covers("##. Organize", dir_modified=True)
    assert not own.covers("10. Financial/Banks")  # anything else that happened to it
    assert not own.covers("10. Financial", dir_modified=True)
    now[0] = 111.0
    assert not own.covers("##. Organize/a.pdf")
    assert not own.covers("##. Organize", dir_modified=True)


def test_own_changes_of_a_folder_cover_its_subtree_only():
    own = OwnChanges()
    own.add(["10. Financial/Banks", "20. Old/Banks"], tree=True)
    assert own.covers("20. Old/Banks/2019/a.pdf")
    assert own.covers("10. Financial/Banks/a.pdf")
    assert not own.covers("20. Old/Banks 2/a.pdf")
    assert not own.covers("20. Old/Bank")
    assert not own.covers("20. Old/other.pdf")
    assert own.covers("20. Old", dir_modified=True)


def test_handler_flags_only_a_bare_folder_listing_change(fake_archive, engine):
    paths, repo = setup(fake_archive, engine)
    noted = []
    w = Watcher(paths, repo)
    w._note = lambda path, dir_modified=False: noted.append((path, dir_modified))
    h = _Handler(w)
    h.on_any_event(DirModifiedEvent("/x/folder"))
    h.on_any_event(DirCreatedEvent("/x/new"))
    h.on_any_event(FileMovedEvent("/x/a.pdf", "/y/a.pdf"))
    assert noted == [
        ("/x/folder", True),
        ("/x/new", False),
        ("/x/a.pdf", False),
        ("/y/a.pdf", False),
    ]


def test_executor_registers_the_paths_it_moved(fake_archive, engine):
    fake_archive.add("##. Organize/a.pdf", drive_id="id-a")
    paths, repo = setup(fake_archive, engine)
    watcher_mod.scan(paths, repo)
    own = OwnChanges()
    executor = Executor(paths, engine, repo, own_changes=own)
    result = executor.apply(
        Plan(ops=[Op(OpKind.MOVE, "##. Organize/a.pdf", "10. Financial")], origin="cli")
    )
    assert result.failed is None
    assert own.covers("##. Organize/a.pdf")
    assert own.covers("10. Financial/a.pdf")
    assert own.covers("10. Financial", dir_modified=True)
    assert not own.covers("10. Financial/b.pdf")


def test_executor_registers_a_moved_folder_with_everything_below_it(fake_archive, engine):
    fake_archive.add("##. Organize/Statements/2019/a.pdf")
    fake_archive.add("10. Financial/Statements 2/b.pdf")
    paths, repo = setup(fake_archive, engine)
    watcher_mod.scan(paths, repo)
    own = OwnChanges()
    executor = Executor(paths, engine, repo, own_changes=own)
    result = executor.apply(
        Plan(ops=[Op(OpKind.MOVE, "##. Organize/Statements", "10. Financial")], origin="cli")
    )
    assert result.failed is None
    assert repo.by_path("10. Financial/Statements/2019/a.pdf") is not None
    assert own.covers("10. Financial/Statements/2019/a.pdf")
    assert own.covers("##. Organize/Statements/2019/a.pdf")
    assert not own.covers("10. Financial/Statements 2/b.pdf")


def test_executor_does_not_register_paths_it_leaves_to_the_scan(fake_archive, engine):
    paths, repo = setup(fake_archive, engine)
    own = OwnChanges()
    executor = Executor(paths, engine, repo, own_changes=own)
    result = executor.apply(Plan(ops=[Op(OpKind.MKDIR, None, "10. Financial/Home")], origin="cli"))
    assert result.failed is None
    assert not own.covers("10. Financial/Home")  # the index learns of it only from a scan
    assert not own.covers("10. Financial", dir_modified=True)


def test_events_for_own_moves_do_not_scan(fake_archive, engine, monkeypatch):
    paths, repo = setup(fake_archive, engine)
    subtrees = _recording(monkeypatch)
    own = OwnChanges()
    w = _unwatched(Watcher(paths, repo, debounce_s=0.05, reconcile_every_s=3600, own_changes=own))
    own.add(["##. Organize/a.pdf", "10. Financial/Banks/a.pdf"])
    own.add(["##. Organize/Folder", "10. Financial/Folder"], tree=True)
    root = fake_archive.root
    w._note(str(root / "##. Organize" / "a.pdf"))
    w._note(str(root / "10. Financial" / "Banks" / "a.pdf"))
    w._note(str(root / "##. Organize"), dir_modified=True)
    w._note(str(root / "10. Financial" / "Banks"), dir_modified=True)
    w._note(str(root / "10. Financial" / "Folder" / "sub" / "b.pdf"))  # moved with it
    w.start()
    try:
        w._wake.set()
        threading.Event().wait(0.5)
    finally:
        w.stop()
    assert subtrees == []
    assert not w._pending


def test_events_noted_before_the_move_was_registered_are_dropped_too(
    fake_archive, engine, monkeypatch
):
    paths, repo = setup(fake_archive, engine)
    subtrees = _recording(monkeypatch)
    own = OwnChanges()
    w = _unwatched(Watcher(paths, repo, debounce_s=0.2, reconcile_every_s=3600, own_changes=own))
    root = fake_archive.root
    w._note(str(root / "##. Organize" / "a.pdf"))  # the event can beat the registration
    w._note(str(root / "##. Organize"), dir_modified=True)
    own.add(["##. Organize/a.pdf", "10. Financial/a.pdf"])
    w.start()
    try:
        w._wake.set()
        threading.Event().wait(0.6)
    finally:
        w.stop()
    assert subtrees == []


def test_external_changes_next_to_own_moves_are_still_scanned(fake_archive, engine, monkeypatch):
    paths, repo = setup(fake_archive, engine)
    subtrees = _recording(monkeypatch)
    own = OwnChanges()
    w = _unwatched(Watcher(paths, repo, debounce_s=0.05, reconcile_every_s=3600, own_changes=own))
    own.add(["##. Organize/a.pdf", "10. Financial/Banks/a.pdf"])
    root = fake_archive.root
    w._note(str(root / "##. Organize" / "a.pdf"))  # own: dropped
    w._note(str(root / "10. Financial" / "Banks" / "b.pdf"))  # a sibling someone added
    w._note(str(root / "##. Organize"), dir_modified=True)  # own: dropped
    w._note(str(root / "10. Financial" / "Banks"), dir_modified=True)  # own listing change ...
    w._note(str(root / "10. Financial" / "Banks"))  # ... but also something else happened to it
    w.start()
    try:
        assert wait_for(lambda: bool(subtrees))
    finally:
        w.stop()
    assert subtrees == ["10. Financial/Banks"]


def test_external_change_is_indexed_while_own_moves_are_skipped(fake_archive, engine, monkeypatch):
    fake_archive.add("##. Organize/a.pdf", drive_id="id-a")
    paths, repo = setup(fake_archive, engine)
    watcher_mod.scan(paths, repo)
    real_scan, subtrees = watcher_mod.scan, []

    def recording_scan(*a, **k):
        subtrees.append(k["subtree"])
        return real_scan(*a, **k)

    monkeypatch.setattr(watcher_mod, "scan", recording_scan)
    own = OwnChanges()
    executor = Executor(paths, engine, repo, own_changes=own)
    w = Watcher(paths, repo, debounce_s=0.2, reconcile_every_s=3600, own_changes=own)
    w.start()
    try:
        result = executor.apply(
            Plan(ops=[Op(OpKind.MOVE, "##. Organize/a.pdf", "10. Financial")], origin="cli")
        )
        assert result.failed is None
        fake_archive.add("##. Organize/new.pdf", drive_id="id-new")
        assert wait_for(lambda: repo.by_path("##. Organize/new.pdf") is not None, 5)
    finally:
        w.stop()
    assert repo.get("id-a").path == "10. Financial/a.pdf"
    assert repo.get("id-a").missing is False
    assert "" not in subtrees
    assert "##. Organize/a.pdf" not in subtrees
    assert "10. Financial/a.pdf" not in subtrees
