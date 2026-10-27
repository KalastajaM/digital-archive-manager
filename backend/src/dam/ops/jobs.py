"""Moves across disks run in the background: one at a time, with progress and Stop.

The runner is the App's (``dam.core.jobs``, ``App.jobs``), with these differences from a check:
a second move across disks is refused while one runs (it would end the first half way),
a move does not end when nobody polls it (closing the window must not stop it), and a
failed move keeps its reason in the error.

A change that closes the archive (a reopen, a relabel, a change of archive folders)
checks that no job runs and must not have a move start until it is done: it holds
``CopyJobs.held()`` around the check and the change, and a move started then is refused.
"""

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from dam.core.jobs import Job, JobContext, Jobs
from dam.errors import Conflict, InvalidRequest, NotFound
from dam.ops.model import GuardError, OpFailed

COPY_KIND = "copy_across"
COPY_RUNNING = "A move across disks is running. Wait for it to finish or stop it."
COPY_HELD = "The archive is being changed. Try the move again in a moment."
# dam's own refusals say what is wrong in words meant for the owner
_OWN_ERRORS = (GuardError, OpFailed, InvalidRequest, NotFound)


def reason(exc: Exception) -> str:
    """What a failed move says: dam's own refusal as it is, anything else by its type."""
    if isinstance(exc, _OWN_ERRORS):
        return str(exc)
    return f"{type(exc).__name__}: the move could not be completed"


class CopyJobs:
    """The moves across disks, as jobs of kind ``COPY_KIND`` on ``jobs``."""

    def __init__(self, jobs: Jobs) -> None:
        self._jobs = jobs
        self._lock = threading.Lock()
        self._held = 0

    def start(self, work: Callable[[JobContext], Any]) -> Job:
        """Start ``work`` in the background; ``Conflict`` while another move runs or
        while a change that closes the archive holds ``held()``."""
        with self._lock:
            if self._held:
                raise Conflict(COPY_HELD)
            if self._jobs.running(COPY_KIND):
                raise Conflict(COPY_RUNNING)
            return self._jobs.start(COPY_KIND, work, abandon=False, describe=reason)

    @contextmanager
    def held(self) -> Iterator[None]:
        """No move starts while inside (``start`` answers ``Conflict``); may be nested.
        The caller checks ``running()`` inside, so the answer stays true until it is
        done."""
        with self._lock:
            self._held += 1
        try:
            yield
        finally:
            with self._lock:
                self._held -= 1

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def latest(self) -> Job | None:
        return self._jobs.latest(COPY_KIND)

    def running(self) -> bool:
        return self._jobs.running(COPY_KIND)

    def close(self) -> None:
        """End the running move after its current file (the executor's
        ``cancel_copies`` ends a copy in progress)."""
        self._jobs.stop(COPY_KIND)
