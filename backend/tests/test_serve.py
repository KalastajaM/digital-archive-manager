"""Stopping the background work: bounded, so a reopen inside a request cannot hang."""

import threading
import time

from dam import serve
from dam.core.jobs import Jobs


class _Content:
    def close(self) -> None:
        pass


class _App:
    content = _Content()


class _Watcher:
    def __init__(self) -> None:
        self.timeouts: list[float | None] = []

    def stop(self, timeout: float | None = None) -> None:
        self.timeouts.append(timeout)


def test_stopping_the_background_waits_at_most_the_stop_timeout(monkeypatch):
    monkeypatch.setattr(serve, "STOP_TIMEOUT_S", 0.3)
    hold = threading.Event()
    threads = [threading.Thread(target=hold.wait, daemon=True) for _ in range(2)]
    for t in threads:
        t.start()
    jobs, watcher = Jobs(), _Watcher()
    workers = [
        jobs.run("watcher", lambda stop, _wake: serve._watch(watcher, stop)),  # type: ignore[arg-type]
        jobs.run("stuck", lambda stop, _wake: hold.wait()),
    ]
    began = time.monotonic()
    serve._shutdown(_App(), threading.Event(), threading.Event(), threads, workers)  # type: ignore[arg-type]
    assert time.monotonic() - began < 2  # not 3 x 5 s
    assert watcher.timeouts == [0.3]  # the watcher's worker stopped it, bounded too
    hold.set()
