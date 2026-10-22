"""The provider protocol: one structured completion, nothing else.

Only ``AIService.run`` may call ``complete`` (a test pins this): every call is preceded
by a preview the user confirmed.
"""

from dataclasses import dataclass
from typing import Protocol


class ProviderError(Exception):
    """The provider could not answer (network, API error, unusable response). When a
    response did arrive (refusal, cut off, not JSON), it was billed: its usage is
    carried here so the call log can price it. ``usage_unknown``: the request may have
    reached the API but no answer came back (a timeout, a connection lost mid-call), so
    it may have been billed for an unknown amount; the service counts it at its
    worst-case estimate. ``kind`` names the failure for a plain message: ``timeout``,
    ``lost`` (connection lost mid-call), ``connect`` (never connected), ``rate_limit``,
    ``overloaded``, ``auth`` or ``other``."""

    def __init__(
        self,
        message: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        usage_unknown: bool = False,
        kind: str = "other",
    ) -> None:
        super().__init__(message)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.usage_unknown = usage_unknown
        self.kind = kind


@dataclass(frozen=True)
class AIResult:
    data: dict
    input_tokens: int
    output_tokens: int


class AIProvider(Protocol):
    def complete(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: dict,
        max_tokens: int,
        timeout_s: float | None = None,
    ) -> AIResult:
        """One call: ``system`` and ``user`` text in, a JSON object shaped by ``schema``
        out (the caller validates it again), with the real token usage. ``timeout_s``:
        how long to wait for the answer (the limit the preview showed)."""
        ...
