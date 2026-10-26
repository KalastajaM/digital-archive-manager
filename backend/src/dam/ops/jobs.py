"""Moves across disks run in the background: one at a time, with progress and Stop.

The runner is the maintenance checks' (``dam.maintenance.jobs``), with two differences:
a second move across disks is refused while one runs (it would end the first half way),
and a move does not end when nobody polls it (closing the window must not stop it).
"""

import threading
from collections.abc import Callable
from typing import Any

from dam.maintenance.jobs import Job, JobContext, MaintenanceJobs
from dam.services.errors import Conflict

COPY_KIND = "copy_across"
COPY_RUNNING = "A move across disks is running. Wait for it to finish or stop it."


class CopyJobs:
    def __init__(self) -> None:
        self._jobs = MaintenanceJobs()
        self._lock = threading.Lock()

    def start(self, work: Callable[[JobContext], Any]) -> Job:
        """Start ``work`` in the background; ``Conflict`` while another move runs."""
        with self._lock:
            if self._jobs.running():
                raise Conflict(COPY_RUNNING)
            return self._jobs.start(COPY_KIND, work, abandon=False)

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def latest(self) -> Job | None:
        return self._jobs.latest(COPY_KIND)

    def running(self) -> bool:
        return self._jobs.running()

    def close(self) -> None:
        """End the running move after its current file (the executor's
        ``cancel_copies`` ends a copy in progress)."""
        self._jobs.close()
