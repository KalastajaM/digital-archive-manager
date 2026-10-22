"""A deterministic provider for tests and demos (``DAM_AI_FAKE=1``): no network."""

import re
from collections.abc import Callable
from typing import Any

from dam.ai.provider import AIResult

Reply = Callable[..., Any]


def _example(schema: dict) -> Any:
    """A value that fits ``schema`` (required keys only, plain placeholders)."""
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = kind[0]
    if kind == "object":
        props = schema.get("properties", {})
        return {k: _example(props.get(k, {})) for k in schema.get("required", [])}
    if kind == "array":
        return []
    if kind == "integer":
        return int(schema.get("minimum", 0))
    if kind == "number":
        return float(schema.get("minimum", 0))
    if kind == "boolean":
        return False
    if kind == "null":
        return None
    return "fake"


class FakeProvider:
    """Answers with ``reply(**call)`` (a dict, or raise), or a schema-shaped placeholder.
    Every call is recorded in ``calls`` with exactly what was sent."""

    def __init__(
        self,
        reply: Reply | None = None,
        *,
        input_tokens: int = 100,
        output_tokens: int = 50,
        demo: bool = False,
    ) -> None:
        self.reply = reply
        # the DAM_AI_FAKE=1 demo provider: its answers are never cached or priced as
        # real (tests leave this off to stand in for the real provider)
        self.demo = demo
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.calls: list[dict] = []
        self.timeouts: list[float | None] = []  # the limit each call was given

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
        self.timeouts.append(timeout_s)
        call = {
            "model": model,
            "system": system,
            "user": user,
            "schema": schema,
            "max_tokens": max_tokens,
        }
        self.calls.append(call)
        data = self.reply(**call) if self.reply is not None else _example(schema)
        return AIResult(data=data, input_tokens=self.input_tokens, output_tokens=self.output_tokens)


# -- demo answers (``DAM_AI_FAKE=1``) ---------------------------------------------------
# Plausible, deterministic answers read from the payload itself, so a demo shows what a
# real answer fills in. Still no network; tests that need exact answers pass their own
# ``reply``.

_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
_AMOUNT = re.compile(r"\b(\d{1,6})[,.](\d{2})\s*(?:€|EUR)")


def _block(user: str, label: str) -> str:
    """The text of the ``<label>`` block of a payload (``guard.delimited``), or ""."""
    m = re.search(rf"<{label}>\n(.*?)\n</{label}>", user, re.S)
    return m.group(1) if m else ""


def _demo_filing(user: str, schema: dict) -> dict:
    text = _block(user, "document")
    folders = [f for f in _block(user, "folders").splitlines() if f and f != "(none)"]
    trays = [line.split(" ", 1)[0] for line in _block(user, "trays").splitlines() if line]
    field_names = set(schema["properties"]["tray_fields"].get("properties", {}))
    date = _DATE.search(text)
    amount = _AMOUNT.search(text)
    iso = f"{date.group(3)}-{int(date.group(2)):02d}-{int(date.group(1)):02d}" if date else None
    words = re.findall(r"[^\W\d_]{3,}", text)[:2] or ["Document"]
    bill = amount is not None and "to-pay" in trays
    tray_fields = {}
    if bill:
        if iso and "due_date" in field_names:
            tray_fields["due_date"] = iso
        if "amount" in field_names:
            tray_fields["amount"] = f"{amount.group(1)}.{amount.group(2)}"
    financial = [f for f in folders if "financial" in f.casefold()]
    nested = [f for f in financial if "/" in f]
    folder = (nested or financial or folders or [None])[0]
    return {
        "name": f"{(iso or '2026-10-21').replace('-', '')}_{' '.join(words)}",
        "folder": folder,
        "tags": ["bill"] if bill else ["demo"],
        "tray": "to-pay" if bill else None,
        "tray_fields": tray_fields,
        "summary": (
            f"Demo answer (DAM_AI_FAKE=1, nothing was sent): a document about {' '.join(words)}."
        ),
        "confidence": {"name": 0.8, "folder": 0.6, "tags": 0.5, "tray": 0.9, "tray_fields": 0.7},
        "reason": "Demo: the fake provider read the amount and date from the text.",
    }


def _demo_collection(user: str) -> dict:
    about = _block(user, "collection")
    name = next((ln[6:] for ln in about.splitlines() if ln.startswith("name: ")), "this collection")
    members = len(re.findall(r"^<member>$", user, re.M))
    per_group = {}
    for line in _block(user, "groups").splitlines():
        gid, sep, rest = line.partition(": ")
        if sep and gid.isdigit():
            group = rest.split(" (in ", 1)[0].split("; current summary:", 1)[0]
            per_group[gid] = f"Demo summary of the group {group} (DAM_AI_FAKE=1)."
    plural = "member" if members == 1 else "members"
    return {
        "summary": (
            f"Demo summary (DAM_AI_FAKE=1, nothing was sent): {name}, with {members} {plural} read."
        ),
        "per_group": per_group,
    }


_SOURCE = re.compile(
    r"<source>\ndrive_id: (.*?)\nname: (.*?)\nfolder: .*?\n\n(.*?)\n</source>", re.S
)


def _demo_ask(user: str) -> dict:
    sources = _SOURCE.findall(user)[:2]
    citations = [
        {"drive_id": drive_id, "quote": " ".join(text.split())[:120]}
        for drive_id, _name, text in sources
    ]
    if not sources:
        return {"answer": "Demo answer (DAM_AI_FAKE=1): no sources.", "citations": []}
    refs = " and ".join(f"{name} [{i}]" for i, (_d, name, _t) in enumerate(sources, 1))
    return {
        "answer": f"Demo answer (DAM_AI_FAKE=1, nothing was sent): the best matches are {refs}.",
        "citations": citations,
    }


def demo_reply(*, model: str, system: str, user: str, schema: dict, max_tokens: int) -> Any:
    """The ``DAM_AI_FAKE=1`` provider's answers, read from the payload: a filing, a
    document summary, a collection summary with a line per group, and an answer that
    cites the first sources sent; anything else gets the schema placeholder."""
    props = schema.get("properties", {})
    if "per_group" in props:
        return _demo_collection(user)
    if "citations" in props:
        return _demo_ask(user)
    if "tray_fields" in props and "confidence" in props:
        return _demo_filing(user, schema)
    if "key_facts" in props:
        text = _block(user, "document")
        facts = [m.group(0) for m in (*_DATE.finditer(text), *_AMOUNT.finditer(text))][:5]
        return {"summary": "Demo summary (DAM_AI_FAKE=1, nothing was sent).", "key_facts": facts}
    return _example(schema)
