"""Maintenance checks as cancellable jobs, on the runner in ``dam.core.jobs``: a failed
check says so in the check's own words."""

from collections.abc import Callable
from typing import Any

from dam.core.jobs import Job, JobContext, Jobs


def check_failed(exc: Exception) -> str:
    """What a failed check says (its error names the exception type only)."""
    return f"{type(exc).__name__}: the check could not be completed"


class MaintenanceJobs(Jobs):
    """The maintenance checks of this server: the latest of each kind, a few finished
    ones kept."""

    def start(
        self,
        kind: str,
        work: Callable[[JobContext], Any],
        abandon: bool = True,
        describe: Callable[[Exception], str] | None = None,
    ) -> Job:
        return super().start(kind, work, abandon, describe or check_failed)
