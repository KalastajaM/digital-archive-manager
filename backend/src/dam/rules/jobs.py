"""Rule tests that run in the background: start one, poll it for the documents looked at
so far and what was found, stop it, or drop it when the sheet that asked for it closes.

A job is one ``ReplayRun`` in a thread of its own. It only reads the index and the cache:
it changes nothing in the archive and writes nothing. There is one job per open sheet
(starting another for the same sheet ends the first), a few at most, and a job that is
not polled for a while ends by itself, so a closed window cannot leave one running."""

from __future__ import annotations

import logging
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field

from dam.rules.replay import ReplayResult, ReplayRun

log = logging.getLogger(__name__)

MAX_JOBS = 4
PUBLISH_EVERY_S = 0.4  # how often the result so far is made ready for polling
RECHECK_EVERY_S = 2.0  # how often documents waiting for page 1 are looked at again
ABANDONED_S = 120.0  # a running job nobody has asked about for this long ends
WAIT_LIMIT_S = 1800.0  # waiting for page 1 reads with nothing new for this long ends the job
KEEP_FINISHED_S = 600.0

RUNNING = "running"  # going through the documents
WAITING = "waiting"  # all looked at; some wait for page 1 to be read
DONE = "done"
STOPPED = "stopped"
ERROR = "error"
LIVE = (RUNNING, WAITING)


@dataclass
class JobView:
    """What a poll gets: the state and the result so far (a copy, safe to read anywhere)."""

    job_id: str
    sheet: str
    state: str
    version: int
    looked_at: int
    total: int
    waiting: int  # documents waiting for page 1 to be read
    elapsed_s: float
    error: str | None
    result: ReplayResult | None


@dataclass
class ReplayJob:
    job_id: str
    sheet: str
    make_run: Callable[[], ReplayRun]
    state: str = RUNNING
    version: int = 0
    error: str | None = None
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None
    seen: float = field(default_factory=time.monotonic)
    _result: ReplayResult | None = None
    _waiting: int = 0
    _waiting_ids: list[str] = field(default_factory=list)
    _run: ReplayRun | None = None
    _published: float = 0.0
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # -- what the caller sees -------------------------------------------------------

    def view(self, with_result: bool = True) -> JobView:
        self.seen = time.monotonic()
        with self._lock:
            end = self.finished if self.finished is not None else time.monotonic()
            result = self._result
            return JobView(
                self.job_id,
                self.sheet,
                self.state,
                self.version,
                result.looked_at if result is not None else 0,
                result.total if result is not None else 0,
                self._waiting,
                round(end - self.started, 1),
                self.error,
                result if with_result else None,
            )

    def stop(self) -> None:
        """End the job where it is; what it found so far stays (state ``stopped``)."""
        self._stop.set()

    def waiting_ids(self) -> list[str]:
        """The documents the test waits for page 1 of, as of the last publish."""
        with self._lock:
            return list(self._waiting_ids) if self.state in LIVE else []

    # -- the thread ---------------------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._work, name="dam-replay", daemon=True)
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _publish(self, run: ReplayRun, state: str | None = None) -> None:
        result = run.snapshot()
        with self._lock:
            self._result = result
            self._waiting_ids = run.waiting_ids()
            self._waiting = len(self._waiting_ids)
            self.version += 1
            if state is not None:
                self.state = state
        self._published = time.monotonic()

    def _progress(self, run: ReplayRun) -> None:
        if time.monotonic() - self._published >= PUBLISH_EVERY_S:
            self._publish(run)

    def _abandoned(self) -> bool:
        return time.monotonic() - self.seen > ABANDONED_S

    def _should_stop(self) -> bool:
        return self._stop.is_set() or self._abandoned()

    def _work(self) -> None:
        started = time.monotonic()
        try:
            run = self.make_run()
            with self._lock:
                self._run = run
            self._publish(run)
            run.advance(None, stop=self._should_stop, progress=lambda: self._progress(run))
            run.log_summary(time.monotonic() - started)
            if not run.done:
                self._finish(run, STOPPED)
                return
            self._publish(run, WAITING if run.waiting_ids() else DONE)
            quiet_since = time.monotonic()
            while self.state == WAITING and not self._should_stop():
                self._stop.wait(RECHECK_EVERY_S)
                if self._should_stop():
                    break
                if run.recheck():
                    quiet_since = time.monotonic()
                    self._publish(run, WAITING if run.waiting_ids() else DONE)
                elif time.monotonic() - quiet_since > WAIT_LIMIT_S:
                    break
            ended = self._stop.is_set() or self._abandoned()
            self._finish(run, STOPPED if ended and self.state == WAITING else DONE)
        except Exception as exc:  # a failed test must not take the server down
            log.exception("rule test failed")
            with self._lock:
                self.state = ERROR
                self.error = f"{type(exc).__name__}: the test could not be completed"
                self.version += 1
                self.finished = time.monotonic()
                self._run = None
        finally:
            if self.finished is None:
                self.finished = time.monotonic()

    def _finish(self, run: ReplayRun, state: str) -> None:
        self._publish(run, state)
        with self._lock:
            self.finished = time.monotonic()
            self._run = None  # the documents and their order are not kept


class ReplayJobs:
    """The jobs of this server: at most ``MAX_JOBS``, the oldest finished ones go first."""

    def __init__(self) -> None:
        self._jobs: OrderedDict[str, ReplayJob] = OrderedDict()
        self._lock = threading.Lock()

    def start(self, sheet: str, make_run: Callable[[], ReplayRun]) -> ReplayJob:
        """Start a job for ``sheet``; the sheet's earlier job (if any) is ended."""
        job = ReplayJob(secrets.token_hex(8), sheet, make_run)
        doomed: list[ReplayJob] = []
        with self._lock:
            for old in list(self._jobs.values()):
                if old.sheet == sheet:
                    doomed.append(old)
                    del self._jobs[old.job_id]
            self._jobs[job.job_id] = job
            now = time.monotonic()
            for old in list(self._jobs.values()):
                if old.state not in LIVE and old.finished and now - old.finished > KEEP_FINISHED_S:
                    del self._jobs[old.job_id]
            while len(self._jobs) > MAX_JOBS:
                victim = next(
                    (j for j in self._jobs.values() if j.state not in LIVE),
                    next(iter(self._jobs.values())),
                )
                doomed.append(victim)
                del self._jobs[victim.job_id]
        for old in doomed:
            old.stop()
        job.start()
        return job

    def get(self, job_id: str) -> ReplayJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def drop(self, job_id: str) -> bool:
        """End a job and forget it (its sheet was closed)."""
        with self._lock:
            job = self._jobs.pop(job_id, None)
        if job is None:
            return False
        job.stop()
        return True

    def close(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
            self._jobs.clear()
        for job in jobs:
            job.stop()
        for job in jobs:
            job.join(2.0)
