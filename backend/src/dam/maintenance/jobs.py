"""Maintenance checks as cancellable jobs: start one, poll it for its progress and the
result so far, stop it. The same pattern as the rule tests (``dam.rules.jobs``): one job
runs in a thread of its own, there is one live job per kind (starting another ends the
first), and a job nobody asks about for a while ends by itself, so a closed window cannot
leave one reading files."""

from __future__ import annotations

import logging
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

ABANDONED_S = 60.0  # a running job nobody has asked about for this long ends
MAX_FINISHED = 12

RUNNING = "running"
DONE = "done"
STOPPED = "stopped"
ERROR = "error"


@dataclass
class JobView:
    """What a poll gets: the state, the progress and the result (a snapshot)."""

    job_id: str
    kind: str
    state: str
    version: int
    done: int
    total: int
    bytes_done: int
    bytes_total: int
    current: str | None
    elapsed_s: float
    error: str | None
    result: Any


class JobContext:
    """What a check's work function sees: whether to stop, and where to report progress."""

    def __init__(self, job: Job) -> None:
        self._job = job

    def stopped(self) -> bool:
        return self._job.should_stop()

    def progress(
        self,
        done: int,
        total: int,
        bytes_done: int = 0,
        bytes_total: int = 0,
        current: str | None = None,
    ) -> None:
        self._job.set_progress(done, total, bytes_done, bytes_total, current)


@dataclass
class Job:
    job_id: str
    kind: str
    work: Callable[[JobContext], Any]
    state: str = RUNNING
    version: int = 0
    done: int = 0
    total: int = 0
    bytes_done: int = 0
    bytes_total: int = 0
    current: str | None = None
    error: str | None = None
    result: Any = None
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None
    seen: float = field(default_factory=time.monotonic)
    # ends by itself when nobody has asked about it for ``ABANDONED_S`` (a check); a
    # move across disks does not (closing the window must not stop it half way)
    abandon: bool = True
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def view(self, with_result: bool = True) -> JobView:
        self.seen = time.monotonic()
        with self._lock:
            end = self.finished if self.finished is not None else time.monotonic()
            return JobView(
                self.job_id,
                self.kind,
                self.state,
                self.version,
                self.done,
                self.total,
                self.bytes_done,
                self.bytes_total,
                self.current,
                round(end - self.started, 1),
                self.error,
                self.result if with_result else None,
            )

    def stop(self) -> None:
        """End the job where it is; what it found so far stays (state ``stopped``)."""
        self._stop.set()

    def should_stop(self) -> bool:
        return self._stop.is_set() or (
            self.abandon and self.state == RUNNING and time.monotonic() - self.seen > ABANDONED_S
        )

    def set_progress(
        self, done: int, total: int, bytes_done: int, bytes_total: int, current: str | None
    ) -> None:
        with self._lock:
            self.done, self.total = done, total
            self.bytes_done, self.bytes_total = bytes_done, bytes_total
            self.current = current
            self.version += 1

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="dam-maintenance", daemon=True)
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        try:
            result = self.work(JobContext(self))
            with self._lock:
                self.result = result
                self.state = STOPPED if self.should_stop() else DONE
                self.current = None
        except Exception as exc:  # a failed check must not take the server down
            log.exception("maintenance check %s failed", self.kind)
            with self._lock:
                self.state = ERROR
                self.error = f"{type(exc).__name__}: the check could not be completed"
        finally:
            with self._lock:
                self.finished = time.monotonic()
                self.version += 1


class MaintenanceJobs:
    """The jobs of this server: the latest of each kind, a few finished ones kept."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._latest: dict[str, str] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, work: Callable[[JobContext], Any], abandon: bool = True) -> Job:
        """Start a job of ``kind``; an earlier live job of the same kind is ended.
        ``abandon``: see ``Job.abandon``."""
        job = Job(secrets.token_hex(8), kind, work, abandon=abandon)
        doomed: list[Job] = []
        with self._lock:
            earlier = self._jobs.get(self._latest.get(kind, ""))
            if earlier is not None and earlier.state == RUNNING:
                doomed.append(earlier)
            self._jobs[job.job_id] = job
            self._latest[kind] = job.job_id
            keep = set(self._latest.values())
            for old in [j for j in self._jobs.values() if j.job_id not in keep]:
                if old.state != RUNNING or len(self._jobs) > MAX_FINISHED:
                    del self._jobs[old.job_id]
                    doomed.append(old)
        for old in doomed:
            old.stop()
        job.start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def latest(self, kind: str) -> Job | None:
        with self._lock:
            return self._jobs.get(self._latest.get(kind, ""))

    def forget(self, kind: str | None = None) -> int:
        """Forget the jobs of ``kind`` (every kind when None), ending one still running,
        so the screen starts again as if no check had run. How many were forgotten."""
        with self._lock:
            gone = [j for j in self._jobs.values() if kind is None or j.kind == kind]
            for job in gone:
                del self._jobs[job.job_id]
            for k in [k for k in self._latest if kind is None or k == kind]:
                del self._latest[k]
        for job in gone:
            job.stop()
        return len(gone)

    def running(self) -> bool:
        with self._lock:
            return any(j.state == RUNNING for j in self._jobs.values())

    def close(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
            self._jobs.clear()
            self._latest.clear()
        for job in jobs:
            job.stop()
        for job in jobs:
            job.join(2.0)
