"""The AI calls, their previews and their log (dam.api.schemas)."""

from typing import Any, Literal

from pydantic import BaseModel, StrictBool, StrictStr

from dam.api.schemas.base import StrictIn

# -- Phase 3: AI ---------------------------------------------------------------


class AIStatusOut(BaseModel):
    """``enabled``: AI can be used (``ai.enabled``, the on/off switch and a key).
    ``switched_on``: the switch alone (``dam ai --on/--off``, Activity → AI).
    ``state_error``: ai-state.json is unreadable or invalid, so the switch reads as off
    (fails closed) until it is switched on again; else null."""

    enabled: bool
    has_key: bool
    switched_on: bool
    state_error: str | None
    month_spend_eur: float
    budget_eur: float
    models: dict[str, str]
    exclude_folders: list[str]
    # the excluded folders that are not folders in the archive (empty while it is away)
    exclude_missing: list[str] = []


class AIStateIn(StrictIn):
    """The on/off switch, stored in ``<data dir>/ai-state.json`` (never settings.yaml)."""

    enabled: StrictBool


class AIExcludeIn(StrictIn):
    """The whole list of excluded folders (archive paths), saved to ``ai.exclude_folders``
    in settings.yaml; it replaces the defaults."""

    folders: list[StrictStr]


class AIPrepareIn(StrictIn):
    """The task's parameters (``drive_id``, ``question``, ...; ``refresh: true`` asks
    again instead of using a cached result)."""

    params: dict[str, Any] = {}


class PreparedOut(BaseModel):
    """Exactly what ``run`` would send (the sheet shows ``payload_text``), the model,
    the worst-case estimate, why it is blocked (or null) and the token for ``run``.
    ``cached`` is an earlier result for the same input (running it costs nothing).
    ``notes`` say what was left out and why (excluded collection members); they are
    shown, never sent. ``timeout_s``: how long a send waits before giving up."""

    task: str
    model: str
    system: str
    payload_text: str
    files: list[str]
    estimate_eur: float
    timeout_s: int
    blocked: str | None
    token: str
    cached: dict[str, Any] | None
    notes: list[str] = []


class AIRunIn(StrictIn):
    token: str


class RunOut(BaseModel):
    data: dict[str, Any]
    cost_eur: float
    cached: bool


class AILogRow(BaseModel):
    id: int
    at: float
    task: str
    model: str
    files: list[str]
    input_tokens: int
    output_tokens: int
    cost_eur: float
    outcome: Literal["ok", "cached", "error", "fake"]
    error: str | None
    duration_ms: int


class AILogOut(BaseModel):
    rows: list[AILogRow]
