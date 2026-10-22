"""The Anthropic provider on the official SDK (pinned in pyproject.toml).

Structured output comes from ``output_config.format`` (a JSON schema): the response's
text block is the JSON. (A forced ``tool_choice`` would be refused by the large model.)
The client is built only here, only when a call is made, with no retries: a
retry after a timeout could bill the same call twice, and every call must match one
preview the user confirmed. How long a call may take comes with it (``timeout_s``,
from ``guard.timeout_s``: 60 s for a small call, more for a large one, 3 min at most);
the client's own 60 s is only the default. A timeout (or a connection lost after the request
may have gone out) is a ``ProviderError`` with ``usage_unknown``; the service logs it
at its worst-case estimate. Tests inject a fake client and an autouse fixture makes the
real constructor fail.
"""

import json
import re
from typing import Any

import anthropic
import httpx2

from dam.ai.provider import AIResult, ProviderError

TIMEOUT_S = 60  # the client's default; each call passes its own limit
MAX_RETRIES = 0  # never retried (a retry could bill a timed-out call twice)
TIMEOUT_MESSAGE = "timeout: usage unknown"
LOST_MESSAGE = "connection lost: usage unknown"
MESSAGE_CHARS = 200
_STATUS_KIND = {401: "auth", 403: "auth", 429: "rate_limit", 503: "overloaded", 529: "overloaded"}

_KEY = re.compile(r"sk-ant-[A-Za-z0-9_-]+")

# JSON-schema keywords structured output does not support: dropped from what is sent;
# ``guard.validate_output`` still checks them on the answer (as the SDK's helpers do)
_UNSUPPORTED = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "maxItems",
        "minItems",
    }
)


_LITERAL = frozenset({"enum", "const", "required", "default", "examples", "description"})
_SCHEMA_MAPS = frozenset({"properties", "$defs", "definitions"})


def _limits_text(node: dict) -> list[str]:
    """The dropped constraints of one node, in words (for its ``description``)."""
    out = []
    lo, hi = node.get("minimum"), node.get("maximum")
    if lo is not None and hi is not None:
        out.append(f"between {lo} and {hi}")
    elif lo is not None:
        out.append(f"at least {lo}")
    elif hi is not None:
        out.append(f"at most {hi}")
    if node.get("exclusiveMinimum") is not None:
        out.append(f"more than {node['exclusiveMinimum']}")
    if node.get("exclusiveMaximum") is not None:
        out.append(f"less than {node['exclusiveMaximum']}")
    if node.get("multipleOf") is not None:
        out.append(f"a multiple of {node['multipleOf']}")
    if node.get("minLength") is not None:
        out.append(f"at least {node['minLength']} characters")
    if node.get("maxLength") is not None:
        out.append(f"at most {node['maxLength']} characters")
    if node.get("minItems") not in (None, 0, 1):
        out.append(f"at least {node['minItems']} items")
    if node.get("maxItems") is not None:
        out.append(f"at most {node['maxItems']} items")
    return out


def wire_schema(schema: Any) -> Any:
    """``schema`` as sent to the API (a copy): the constraints structured output does
    not support are dropped and restated in the node's ``description`` ("at most 10
    items", "between 0 and 1"); a type list becomes ``anyOf``. ``guard`` and the
    task's ``post`` still enforce the limits on the answer."""
    if isinstance(schema, list):
        return [wire_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key in _UNSUPPORTED or key == "minItems":
            if key == "minItems" and value in (0, 1):
                out[key] = value
            continue
        if key == "additionalProperties" and isinstance(value, dict):
            # structured output wants closed objects: only the listed keys are offered
            # (``guard`` still accepts typed extras and the task's ``post`` sorts them)
            out[key] = False
        elif key in _SCHEMA_MAPS and isinstance(value, dict):
            out[key] = {name: wire_schema(sub) for name, sub in value.items()}
        elif key in _LITERAL:
            out[key] = value
        else:
            out[key] = wire_schema(value)
    limits = _limits_text(schema)
    if limits:
        text = "; ".join(limits)
        out["description"] = f"{out['description']} ({text})" if out.get("description") else text
    kind = out.get("type")
    if isinstance(kind, list):
        del out["type"]
        out["anyOf"] = [{"type": k} for k in kind]
    return out


def _safe_message(e: Exception) -> str:
    """The API's message, truncated, with anything that looks like a key removed."""
    message = str(getattr(e, "message", "") or "")
    message = _KEY.sub("sk-ant-...", message).replace("\n", " ")
    return message[:MESSAGE_CHARS]


class AnthropicProvider:
    def __init__(self, api_key: str, client: Any | None = None, effort: str = "low") -> None:
        self._api_key = api_key
        self._client = client
        self.effort = effort

    def _get_client(self) -> Any:
        if self._client is None:
            # the key is passed explicitly: no ambient credentials or profiles are read
            self._client = anthropic.Anthropic(
                api_key=self._api_key, timeout=TIMEOUT_S, max_retries=MAX_RETRIES
            )
        return self._client

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
        try:
            response = self._get_client().messages.create(
                timeout=timeout_s if timeout_s is not None else TIMEOUT_S,
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={
                    "format": {"type": "json_schema", "schema": wire_schema(schema)},
                    "effort": self.effort,
                },
            )
        except anthropic.APIStatusError as e:
            detail = _safe_message(e)
            raise ProviderError(
                f"API error {e.status_code}: {type(e).__name__}"
                + (f": {detail}" if detail else ""),
                kind=_STATUS_KIND.get(e.status_code, "other"),
            ) from None
        except anthropic.APITimeoutError:
            # the request may have reached the API and been billed: usage unknown
            raise ProviderError(TIMEOUT_MESSAGE, usage_unknown=True, kind="timeout") from None
        except anthropic.APIConnectionError as e:
            if isinstance(e.__cause__, httpx2.ConnectError):
                # never connected (DNS, refused, TLS): nothing was sent
                raise ProviderError(
                    f"connection failed: {type(e).__name__}", kind="connect"
                ) from None
            raise ProviderError(LOST_MESSAGE, usage_unknown=True, kind="lost") from None
        except anthropic.AnthropicError as e:
            raise ProviderError(f"{type(e).__name__}") from None
        # from here on the response was billed: every error carries its usage
        usage = getattr(response, "usage", None)
        billed = {
            "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        }
        stop = getattr(response, "stop_reason", None)
        if stop == "refusal":
            raise ProviderError("the model declined the request", **billed)
        if stop == "max_tokens":
            raise ProviderError("the answer was cut off (max_tokens)", **billed)
        text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), None)
        if text is None:
            raise ProviderError("no text in the answer", **billed)
        try:
            data = json.loads(text)
        except ValueError:
            raise ProviderError("the answer was not JSON", **billed) from None
        if not isinstance(data, dict):
            raise ProviderError("the answer was not a JSON object", **billed)
        return AIResult(data=data, **billed)
