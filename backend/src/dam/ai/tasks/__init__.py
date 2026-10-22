"""The task registry. A task says what goes out (``build``) and what comes back
(``schema``, ``post``); the service does everything else (exclusions, budget, preview
token, the call, validation, the log and the cache).

Tasks ship in this package (one module each) and call ``register`` on import.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from dam.app import App


@dataclass(frozen=True)
class Built:
    """What a task would send: the system prompt, the user text (shown verbatim in the
    preview), the files involved (drive ids; the service refuses excluded ones), the
    cache key (file sha256 or a digest of the inputs) and, optionally, why the task
    itself refuses (an inbox file whose rules point at an excluded folder)."""

    system: str
    user: str
    files: list[str] = field(default_factory=list)
    sha_key: str = ""
    blocked: str | None = None
    # the output schema for these inputs, when it depends on them (else ``task.schema``)
    schema: dict | None = None
    # what ``post`` needs to check the answer (the allowed folders, the trays, ...)
    context: dict[str, Any] = field(default_factory=dict)
    # shown on the sheet, never sent: what was left out and why (an excluded member)
    notes: list[str] = field(default_factory=list)


class AITask(Protocol):
    id: str
    model_tier: str  # "small" | "large"
    prompt_version: str
    schema: dict

    def build(self, app: "App", params: dict[str, Any]) -> Built: ...

    def post(self, data: dict, built: Built) -> dict:
        """The validated answer, cleaned against ``built.context`` (never raises for
        a schema-valid answer; a raise is reported as "could not be processed").

        The length and count limits of the schema (``maxLength``, ``maxItems``, ...;
        ``guard.SOFT_LIMITS``) are soft service-wide: the service passes an answer
        over them through, so ``post`` must trim, shorten or null every value that goes
        over its own limits (and may say so in a ``rejected`` map). Types, required
        keys, extra keys, enums and number ranges are hard: the service rejects them
        before ``post`` is called. Values the schema cannot check (a folder, tray or
        group id that must be one of this call's, a cited drive id) are ``post``'s to
        check against ``built.context`` too."""
        ...


TASKS: dict[str, AITask] = {}


def register(task: AITask) -> AITask:
    TASKS[task.id] = task
    return task


# the shipped tasks register themselves (after ``register`` exists)
from dam.ai.tasks import (  # noqa: E402, F401
    ask_archive,
    suggest_filing,
    summarize_collection,
    summarize_document,
)
