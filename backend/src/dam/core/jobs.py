"""The background runner: cancellable jobs and named workers.

A job is started, polled for its progress and the result so far, and stopped. The same
pattern as the rule tests (``dam.rules.jobs``): one job runs in a thread of its own,
there is one live job per kind (starting another ends the first), and a job nobody asks
about for a while ends by itself, so a closed window cannot leave one reading files. The
maintenance checks (``dam.maintenance.jobs``) and the moves across disks
(``dam.ops.jobs``) run on it.

A worker is background work that runs until it is stopped, in a thread of its own named
after it: the content indexer (``extraction``). It gets a stop event and a wake event
(setting it ends an idle wait early). ``Jobs.status`` lists every worker and job;
``Jobs.close`` stops them all and waits for them, briefly. The App has one runner
(``App.jobs``) and closes it when it closes."""

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
    """What a job's work function sees: whether to stop, and where to report progress."""

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
    # what the error says when the work raises (a move keeps its reason); None: a generic
    # text naming the exception type
    describe: Callable[[Exception], str] | None = None
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
        self._thread = threading.Thread(target=self._run, name="dam-job", daemon=True)
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
        except Exception as exc:  # a failed job must not take the server down
            log.exception("job %s failed", self.kind)
            with self._lock:
                self.state = ERROR
                self.error = (
                    f"{type(exc).__name__}: the job could not be completed"
                    if self.describe is None
                    else self.describe(exc)
                )
        finally:
            with self._lock:
                self.finished = time.monotonic()
                self.version += 1


@dataclass(frozen=True)
class JobStatus:
    """One line of ``Jobs.status``: a worker (``job_id`` None) or a job."""

    name: str  # the worker's name or the job's kind
    state: str  # running | done | stopped | error
    job_id: str | None
    elapsed_s: float
    error: str | None = None


@dataclass(eq=False)
class Worker:
    """Background work that runs until stopped: ``loop(stop, wake)`` returns once
    ``stop`` is set. A loop that raises ends in state ``error`` (logged)."""

    name: str
    loop: Callable[[threading.Event, threading.Event], None]
    stop_event: threading.Event = field(default_factory=threading.Event)
    wake_event: threading.Event = field(default_factory=threading.Event)
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None
    error: str | None = None
    thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, name=f"dam-{self.name}", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        try:
            self.loop(self.stop_event, self.wake_event)
        except Exception as exc:  # a failed worker must not take the server down
            log.exception("background work %s failed", self.name)
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            self.finished = time.monotonic()

    def wake(self) -> None:
        self.wake_event.set()

    def stop(self) -> None:
        """Ask the loop to end (it notices at once even when idle); does not wait."""
        self.stop_event.set()
        self.wake_event.set()

    def join(self, timeout: float | None = None) -> None:
        if self.thread is not None:
            self.thread.join(timeout)

    @property
    def state(self) -> str:
        """running; error (it raised); stopped (asked to) or done (it ended by itself,
        as the initial scan does)."""
        if self.finished is None and self.thread is not None:
            return RUNNING
        if self.error is not None:
            return ERROR
        return STOPPED if self.stop_event.is_set() or self.thread is None else DONE

    def status(self) -> JobStatus:
        end = self.finished if self.finished is not None else time.monotonic()
        return JobStatus(self.name, self.state, None, round(end - self.started, 1), self.error)


class Jobs:
    """A set of jobs (the latest of each kind, a few finished ones kept) and of named
    workers."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._latest: dict[str, str] = {}
        self._workers: dict[str, Worker] = {}
        self._lock = threading.Lock()

    def run(
        self,
        name: str,
        loop: Callable[[threading.Event, threading.Event], None],
        wake: threading.Event | None = None,
    ) -> Worker:
        """Start the worker ``name`` (``wake``: its wake event, when others set it too);
        ``ValueError`` while one of that name still runs. A stopped one is replaced."""
        worker = Worker(name, loop) if wake is None else Worker(name, loop, wake_event=wake)
        with self._lock:
            earlier = self._workers.get(name)
            if earlier is not None and earlier.state == RUNNING:
                raise ValueError(f"{name} is running already")
            self._workers[name] = worker
        worker.start()
        return worker

    def worker(self, name: str) -> Worker | None:
        with self._lock:
            return self._workers.get(name)

    def wake(self, name: str) -> None:
        """End the idle wait of the worker ``name`` (nothing when there is none)."""
        worker = self.worker(name)
        if worker is not None:
            worker.wake()

    def status(self) -> list[JobStatus]:
        """Every worker, then every job (oldest first), as it is now."""
        with self._lock:
            workers = list(self._workers.values())
            jobs = sorted(self._jobs.values(), key=lambda j: j.started)
        out = [w.status() for w in workers]
        for job in jobs:
            view = job.view(with_result=False)
            out.append(JobStatus(view.kind, view.state, view.job_id, view.elapsed_s, view.error))
        return out

    def start(
        self,
        kind: str,
        work: Callable[[JobContext], Any],
        abandon: bool = True,
        describe: Callable[[Exception], str] | None = None,
    ) -> Job:
        """Start a job of ``kind``; an earlier live job of the same kind is ended.
        ``abandon`` and ``describe``: see ``Job``."""
        job = Job(secrets.token_hex(8), kind, work, abandon=abandon, describe=describe)
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
        so the screen starts again as if none had run. How many were forgotten."""
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
        """A job runs (workers run all the time and do not count)."""
        with self._lock:
            return any(j.state == RUNNING for j in self._jobs.values())

    def close(self, timeout: float = 2.0) -> None:
        """Stop every worker and job, then wait for each, at most ``timeout`` in all
        for the workers; one still running after that is left behind (a daemon thread)
        and logged."""
        with self._lock:
            jobs = list(self._jobs.values())
            workers = list(self._workers.values())
            self._jobs.clear()
            self._latest.clear()
        for worker in workers:
            worker.stop()
        for job in jobs:
            job.stop()
        deadline = time.monotonic() + timeout
        for worker in workers:
            worker.join(max(0.0, deadline - time.monotonic()))
            if worker.state == RUNNING:
                log.warning("background work %s still running after close()", worker.name)
        for job in jobs:
            job.join(2.0)
