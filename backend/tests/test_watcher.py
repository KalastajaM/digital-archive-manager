import os
import threading
import time
from pathlib import Path

from dam.config import Settings
from dam.core.paths import ArchivePaths
from dam.index import watcher as watcher_mod
from dam.index.repo import FileRepo
from dam.index.watcher import Watcher, _scope


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
    assert w._pending == set()
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
    assert w._pending == set()


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
    assert w._pending == {"Old years/2009/a.pdf"}


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
