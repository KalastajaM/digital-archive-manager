"""The background runner (``dam.core.jobs.Jobs``): named workers that run until stopped,
the status list of workers and jobs, and a clean stop when the App closes."""

import threading
import time

import pytest

from dam.core.jobs import DONE, ERROR, RUNNING, STOPPED, Jobs
from dam.serve import EXTRACTION, SCAN, WATCHER, start_background


def _wait_for(cond, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


def _idle(stop: threading.Event, wake: threading.Event, woken: list) -> None:
    while not stop.is_set():
        if wake.wait(5):
            wake.clear()
            woken.append(1)


def test_a_worker_runs_until_stopped_and_wakes_on_request():
    jobs, woken = Jobs(), []
    worker = jobs.run("w", lambda stop, wake: _idle(stop, wake, woken))
    assert worker.thread is not None and worker.thread.name == "dam-w"
    jobs.wake("w")
    assert _wait_for(lambda: woken)
    assert [s.state for s in jobs.status()] == [RUNNING]
    with pytest.raises(ValueError, match="running already"):
        jobs.run("w", lambda stop, wake: None)
    jobs.close()
    assert not worker.thread.is_alive()
    [status] = jobs.status()
    assert (status.name, status.state, status.job_id) == ("w", STOPPED, None)
    jobs.run("w", lambda stop, wake: None).join(2)  # a stopped one is replaced


def test_a_failing_worker_ends_in_error_and_says_why():
    jobs = Jobs()

    def broken(stop, wake):
        raise RuntimeError("boom")

    jobs.run("w", broken).join(2)
    [status] = jobs.status()
    assert status.state == ERROR and status.error == "RuntimeError: boom"
    jobs.close()


def test_status_lists_workers_then_jobs_and_close_stops_both():
    jobs = Jobs()
    jobs.run("w", lambda stop, wake: stop.wait(5))
    done = jobs.start("quick", lambda ctx: 1)
    done.join(2)
    held = jobs.start("slow", lambda ctx: _wait_for(ctx.stopped, 5), abandon=False)
    states = [(s.name, s.state) for s in jobs.status()]
    assert states == [("w", RUNNING), ("quick", DONE), ("slow", RUNNING)]
    began = time.monotonic()
    jobs.close()
    assert time.monotonic() - began < 2
    assert held.view().state == STOPPED
    assert [(s.name, s.state) for s in jobs.status()] == [("w", STOPPED)]


def test_close_waits_at_most_its_timeout_for_a_stuck_worker():
    jobs, release = Jobs(), threading.Event()
    worker = jobs.run("stuck", lambda stop, wake: release.wait(10))
    began = time.monotonic()
    jobs.close(timeout=0.2)
    assert time.monotonic() - began < 1 and worker.state == RUNNING
    release.set()
    worker.join(2)


def test_the_background_runs_on_the_apps_runner_and_stops_with_it(app):
    bg = start_background(app)
    try:
        worker = app.jobs.worker(EXTRACTION)
        assert worker is not None and worker is bg.indexer and worker.state == RUNNING
        assert [s.name for s in app.jobs.status()] == [SCAN, WATCHER, EXTRACTION]
        assert _wait_for(lambda: bg.scan.state == DONE)  # the initial scan ends by itself
        assert bg.watching.state == RUNNING
    finally:
        bg.stop()
    assert worker.state == bg.watching.state == STOPPED
    assert not any(t.is_alive() for t in bg.threads)


def test_closing_the_app_stops_its_workers(app):
    worker = app.jobs.run("w", lambda stop, wake: stop.wait(10))
    app.close()
    assert worker.state == STOPPED
