"""Phase 3 Task 1: the AI core (provider, guardrails, prepare/run, call log, cache,
the Keychain key and the CLI). Nothing here ever reaches the network: the provider is
a fake, the keyring is in memory (conftest) and the real client cannot be built."""

import ast
import hashlib
import json
import math
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, update
from typer.testing import CliRunner

from dam.ai import guard, keys
from dam.ai.anthropic import AnthropicProvider
from dam.ai.fake import FakeProvider
from dam.ai.provider import AIResult, ProviderError
from dam.ai.tasks import TASKS, Built, register
from dam.api import create_api
from dam.cli.main import app as cli
from dam.db.engine import write_tx
from dam.db.tables import ai_cache, ai_calls, file_text
from dam.errors import Conflict, InvalidRequest, NotFound

BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}
BANKS = "10. Financial/Banks"
OFF_MESSAGE = "AI is off: add a key with dam ai --set-key"

ECHO_SCHEMA = {
    "type": "object",
    "properties": {
        "echo": {"type": "string"},
        "words": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
    },
    "required": ["echo"],
    "additionalProperties": False,
}


class EchoTask:
    """Sends a file's indexed text (or ``params["text"]``) and expects it back."""

    id = "echo"
    model_tier = "small"
    prompt_version = "v1"
    schema = ECHO_SCHEMA

    def build(self, app, params: dict) -> Built:
        drive_id = params.get("drive_id")
        files: list[str] = []
        if drive_id:
            files.append(drive_id)
            with app.engine.connect() as conn:
                text = conn.execute(
                    select(file_text.c.text).where(file_text.c.drive_id == drive_id)
                ).scalar_one()
        else:
            text = params["text"]
        return Built(
            system="Echo the document back. " + guard.DATA_PREAMBLE,
            user=guard.delimited("document", text),
            files=files,
            sha_key=hashlib.sha256(text.encode()).hexdigest(),
        )

    def post(self, data: dict, built: Built) -> dict:
        return {**data, "posted": True}


def echo_reply(*, model, system, user, schema, max_tokens) -> dict:
    return {"echo": user}


@pytest.fixture
def echo():
    task = register(EchoTask())
    yield task
    TASKS.pop("echo", None)


@pytest.fixture
def ai_app(app, echo, fake_archive):
    """An app with the echo task, a fake provider (counts as a key) and one indexed
    file ``f1`` under the Banks folder plus ``m1`` under ``50. medical`` (case variant)."""
    app.ai.provider = FakeProvider(echo_reply, input_tokens=1000, output_tokens=200)
    fake_archive.add(f"{BANKS}/bill.txt", b"Northpower Oy invoice 84,20 EUR", drive_id="f1")
    fake_archive.add("50. medical/lab.txt", b"blood test results", drive_id="m1")
    app.scan()
    app.index()
    return app


@pytest.fixture
def client(ai_app):
    with TestClient(create_api(ai_app), base_url=BASE) as c:
        yield c


def rows(app) -> list:
    with app.engine.connect() as conn:
        return list(conn.execute(select(ai_calls).order_by(ai_calls.c.id)).mappings())


def set_text(app, drive_id: str, text: str) -> None:
    with write_tx(app.engine) as conn:
        conn.execute(update(file_text).where(file_text.c.drive_id == drive_id).values(text=text))


# -- keys -----------------------------------------------------------------------------


def test_keys_set_clear_and_status(fake_keyring):
    assert keys.has_key() is False
    keys.set_key("sk-ant-test-123")
    assert keys.has_key() is True
    assert keys.get_key() == "sk-ant-test-123"
    assert fake_keyring.store == {("dam-anthropic", "api-key"): "sk-ant-test-123"}
    keys.clear_key()
    assert keys.has_key() is False
    keys.clear_key()  # clearing twice is fine
    assert keys.get_key() is None


def test_set_key_rejects_blank_and_multiline():
    for bad in ("", "   ", "a\nb", "a b"):
        with pytest.raises(InvalidRequest):
            keys.set_key(bad)


# -- status and the off states ---------------------------------------------------------


def test_status_without_key_and_endpoints_409(app, echo):
    status = app.ai.status()
    assert status["has_key"] is False and status["enabled"] is False
    assert status["budget_eur"] == 5 and status["month_spend_eur"] == 0
    assert status["models"] == {"small": "claude-haiku-5-5", "large": "claude-sonnet-5-5"}
    assert status["exclude_folders"] == ["50. Medical", "70. Work", "90. Other People"]
    with pytest.raises(Conflict, match=OFF_MESSAGE):
        app.ai.prepare("echo", {"text": "hi"})
    with pytest.raises(Conflict, match=OFF_MESSAGE):
        app.ai.run("0" * 64)
    with TestClient(create_api(app), base_url=BASE) as c:
        assert c.get("/api/ai/status", headers=LOCAL_ORIGIN).json()["has_key"] is False
        r = c.post("/api/ai/echo/prepare", json={"params": {"text": "hi"}}, headers=LOCAL_ORIGIN)
        assert (r.status_code, r.json()["error"]) == (409, OFF_MESSAGE)
        r = c.post("/api/ai/echo/run", json={"token": "x"}, headers=LOCAL_ORIGIN)
        assert (r.status_code, r.json()["error"]) == (409, OFF_MESSAGE)
        assert c.get("/api/ai/log", headers=LOCAL_ORIGIN).json() == {"rows": []}


def test_key_in_keyring_enables_without_building_a_client(app, echo):
    keys.set_key("sk-ant-test")
    assert app.ai.status()["has_key"] is True
    assert app.ai.status()["enabled"] is True
    # the key never reaches the status payload
    assert "sk-ant" not in json.dumps(app.ai.status())


def test_on_off_state_file(ai_app):
    assert ai_app.ai.status()["enabled"] is True
    ai_app.ai.set_enabled(False)
    assert (ai_app.app_paths.data_dir / "ai-state.json").read_text(
        encoding="utf-8"
    ) == '{"enabled": false}'
    assert ai_app.ai.status()["enabled"] is False
    with pytest.raises(Conflict, match="AI is off: turn it on with dam ai --on"):
        ai_app.ai.prepare("echo", {"text": "hi"})
    ai_app.ai.set_enabled(True)
    assert ai_app.ai.status()["enabled"] is True


def test_api_state_switch(client, ai_app):
    """The UI's on/off switch (Activity, AI): ``POST /api/ai/state`` writes
    ai-state.json, as ``dam ai --on/--off`` does, and answers the new status."""
    s = client.get("/api/ai/status", headers=LOCAL_ORIGIN).json()
    assert s["switched_on"] is True
    r = client.post("/api/ai/state", json={"enabled": False}, headers=LOCAL_ORIGIN)
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is False and r.json()["switched_on"] is False
    assert r.json()["has_key"] is True
    assert (ai_app.app_paths.data_dir / "ai-state.json").read_text(
        encoding="utf-8"
    ) == '{"enabled": false}'
    r = client.post("/api/ai/echo/prepare", json={"params": {"text": "hi"}}, headers=LOCAL_ORIGIN)
    assert r.status_code == 409 and "dam ai --on" in r.json()["error"]
    r = client.post("/api/ai/state", json={"enabled": True}, headers=LOCAL_ORIGIN)
    assert r.json()["enabled"] is True and r.json()["switched_on"] is True
    # a strict body: no other fields, and enabled is required
    assert client.post("/api/ai/state", json={}, headers=LOCAL_ORIGIN).status_code == 422
    assert (
        client.post(
            "/api/ai/state", json={"enabled": True, "key": "x"}, headers=LOCAL_ORIGIN
        ).status_code
        == 422
    )


def test_fake_env_switch_counts_as_key(app_paths, monkeypatch):
    from dam.app import App

    monkeypatch.setenv("DAM_AI_FAKE", "1")
    a = App.create(app_paths.data_dir)
    try:
        assert isinstance(a.ai.provider, FakeProvider)
        assert a.ai.status()["has_key"] is True
    finally:
        a.close()


# -- prepare ---------------------------------------------------------------------------


def test_prepare_shows_exact_payload_model_and_estimate(ai_app):
    p = ai_app.ai.prepare("echo", {"drive_id": "f1"})
    assert p.task == "echo" and p.model == "claude-haiku-5-5"
    assert "Northpower Oy invoice 84,20 EUR" in p.payload_text
    assert p.system.startswith("Echo the document back.")
    assert p.files == ["f1"] and p.blocked is None and p.cached is None
    assert len(p.token) == 64
    chars = len(p.system) + len(p.payload_text) + len(json.dumps(ECHO_SCHEMA))
    in_tokens = math.ceil(chars / 3.5)
    expected = (in_tokens * 0.10 + 700 * 0.50) / 1_000_000 * 0.92
    assert p.estimate_eur == pytest.approx(expected)
    # a task without a max_tokens entry gets the 700 default (output priced at worst case)
    assert "echo" not in ai_app.settings.ai.max_tokens


def test_unknown_task_and_model_without_price(ai_app):
    with pytest.raises(NotFound):
        ai_app.ai.prepare("nope", {})
    ai_app.settings.ai.models.small = "claude-unknown"
    p = ai_app.ai.prepare("echo", {"text": "x"})
    assert p.blocked and "no price" in p.blocked
    with pytest.raises(InvalidRequest, match="no price"):
        ai_app.ai.run(p.token)


def test_excluded_folder_blocked_everywhere(ai_app):
    p = ai_app.ai.prepare("echo", {"drive_id": "m1"})
    assert p.blocked == "lab.txt is in an excluded folder (50. Medical) and is never sent"
    with pytest.raises(InvalidRequest, match="excluded folder"):
        ai_app.ai.run(p.token)
    assert ai_app.ai.provider.calls == []
    # the guard folds case and NFC: "ä" composed vs decomposed
    assert guard.is_excluded("50. medical/x.txt", ["50. Medical"])
    assert guard.is_excluded("Lääkäri/2026/x.pdf", ["Lääkäri"])
    assert guard.is_excluded("70. Work", ["70. Work"])
    assert not guard.is_excluded("70. Workshop/x.pdf", ["70. Work"])
    assert guard.excluded_folder("90. other people/a/b.pdf", ["70. Work", "90. Other People"]) == (
        "90. Other People"
    )


# -- run -------------------------------------------------------------------------------


def test_run_refuses_changed_payload(ai_app):
    p = ai_app.ai.prepare("echo", {"drive_id": "f1"})
    set_text(ai_app, "f1", "Northpower Oy invoice 99,00 EUR")
    with pytest.raises(InvalidRequest, match="changed since the preview"):
        ai_app.ai.run(p.token)
    assert ai_app.ai.provider.calls == []
    # a settings change (the model) also invalidates the preview
    p = ai_app.ai.prepare("echo", {"drive_id": "f1"})
    ai_app.settings.ai.models.small = "claude-haiku-5-5-other"
    ai_app.settings.ai.prices["claude-haiku-5-5-other"] = ai_app.settings.ai.prices[
        "claude-haiku-5-5"
    ]
    with pytest.raises(InvalidRequest, match="changed since the preview"):
        ai_app.ai.run(p.token)
    # a token that was never prepared (or a forged one) is refused too
    with pytest.raises(InvalidRequest, match="Prepare it again"):
        ai_app.ai.run("ab" * 32)
    with pytest.raises(InvalidRequest):
        ai_app.ai.run("not-a-token")
    assert ai_app.ai.provider.calls == []
    assert [r["outcome"] for r in rows(ai_app)] == []


def test_run_sends_exactly_the_preview_and_logs(ai_app):
    p = ai_app.ai.prepare("echo", {"drive_id": "f1"})
    r = ai_app.ai.run(p.token)
    assert r.cached is False and r.data == {"echo": p.payload_text, "posted": True}
    (call,) = ai_app.ai.provider.calls
    assert call == {
        "model": "claude-haiku-5-5",
        "system": p.system,
        "user": p.payload_text,
        "schema": ECHO_SCHEMA,
        "max_tokens": 700,
    }
    expected_cost = (1000 * 0.10 + 200 * 0.50) / 1_000_000 * 0.92
    assert r.cost_eur == pytest.approx(expected_cost)
    (row,) = rows(ai_app)
    assert row["task"] == "echo" and row["model"] == "claude-haiku-5-5"
    assert row["files"] == ["f1"]
    assert (row["input_tokens"], row["output_tokens"]) == (1000, 200)
    assert row["cost_eur"] == pytest.approx(expected_cost)
    assert row["outcome"] == "ok" and row["error"] is None
    assert row["duration_ms"] >= 0
    assert abs(row["at"] - time.time()) < 60
    assert ai_app.ai.status()["month_spend_eur"] == pytest.approx(expected_cost)
    # the same token cannot be run twice (it was consumed)
    with pytest.raises(InvalidRequest, match="Prepare it again"):
        ai_app.ai.run(p.token)


def test_cache_hit_costs_nothing_and_is_logged(ai_app):
    p = ai_app.ai.prepare("echo", {"drive_id": "f1"})
    ai_app.ai.run(p.token)
    p2 = ai_app.ai.prepare("echo", {"drive_id": "f1"})
    assert p2.cached == {"echo": p.payload_text, "posted": True}
    r = ai_app.ai.run(p2.token)
    assert r.cached is True and r.cost_eur == 0 and r.data == p2.cached
    assert len(ai_app.ai.provider.calls) == 1
    assert [x["outcome"] for x in rows(ai_app)] == ["ok", "cached"]
    assert rows(ai_app)[1]["cost_eur"] == 0
    # "Ask again" bypasses the cache
    p3 = ai_app.ai.prepare("echo", {"drive_id": "f1", "refresh": True})
    assert p3.cached is None
    ai_app.ai.run(p3.token)
    assert len(ai_app.ai.provider.calls) == 2
    # a different prompt version or model is a different cache entry
    with ai_app.engine.connect() as conn:
        keys_ = conn.execute(select(ai_cache.c.task, ai_cache.c.prompt_version)).all()
    assert keys_ == [("echo", "v1")]
    # the file changed: no cache hit
    set_text(ai_app, "f1", "something else")
    assert ai_app.ai.prepare("echo", {"drive_id": "f1"}).cached is None


def test_budget_edge_and_cache(ai_app):
    ai_app.settings.ai.monthly_budget_eur = 0.001
    p = ai_app.ai.prepare("echo", {"drive_id": "f1"})
    assert p.blocked is None  # the estimate is far below 0.1 cent
    ai_app.ai.run(p.token)
    # month-to-date just under the cap: this estimate takes it over
    spent = ai_app.ai.status()["month_spend_eur"]
    with write_tx(ai_app.engine) as conn:
        conn.execute(
            insert(ai_calls).values(
                at=time.time(),
                task="echo",
                model="claude-haiku-5-5",
                files=[],
                input_tokens=0,
                output_tokens=0,
                cost_eur=0.001 - spent - p.estimate_eur / 2,
                outcome="ok",
                error=None,
                duration_ms=1,
            )
        )
    assert ai_app.ai.status()["month_spend_eur"] < 0.001
    blocked = ai_app.ai.prepare("echo", {"text": "new text"})
    assert blocked.blocked is not None and "budget" in blocked.blocked
    with pytest.raises(InvalidRequest, match="budget"):
        ai_app.ai.run(blocked.token)
    assert len(ai_app.ai.provider.calls) == 1
    # a cached result is not blocked by the budget and costs 0
    cached = ai_app.ai.prepare("echo", {"drive_id": "f1"})
    assert cached.cached is not None and cached.blocked is None
    assert ai_app.ai.run(cached.token).cost_eur == 0
    # exactly at the cap is still allowed ("would go over" means strictly more)
    ai_app.settings.ai.monthly_budget_eur = (
        ai_app.ai.status()["month_spend_eur"] + blocked.estimate_eur
    )
    assert ai_app.ai.prepare("echo", {"text": "new text"}).blocked is None


def test_blocked_prepare_skips_the_cache_and_prices_are_in_the_token(ai_app):
    p = ai_app.ai.prepare("echo", {"drive_id": "f1"})
    ai_app.ai.run(p.token)
    assert ai_app.ai.prepare("echo", {"drive_id": "f1"}).cached is not None
    ai_app.settings.ai.exclude_folders.append("10. Financial")
    blocked = ai_app.ai.prepare("echo", {"drive_id": "f1"})
    assert blocked.blocked and blocked.cached is None
    ai_app.settings.ai.exclude_folders.pop()
    p = ai_app.ai.prepare("echo", {"text": "priced"})
    ai_app.settings.ai.prices["claude-haiku-5-5"].output_usd_per_mtok = 1.0
    with pytest.raises(InvalidRequest, match="changed since the preview"):
        ai_app.ai.run(p.token)
    p = ai_app.ai.prepare("echo", {"text": "priced"})
    ai_app.settings.ai.usd_to_eur = 1.0
    with pytest.raises(InvalidRequest, match="changed since the preview"):
        ai_app.ai.run(p.token)


def test_budget_is_rechecked_at_run(ai_app):
    p = ai_app.ai.prepare("echo", {"text": "x"})
    ai_app.settings.ai.monthly_budget_eur = 0
    with pytest.raises(InvalidRequest, match="budget"):
        ai_app.ai.run(p.token)
    assert ai_app.ai.provider.calls == []


def test_month_boundary_is_the_local_calendar_month(ai_app):
    # noon on the last day of last month, local time: a naive date, so a DST change
    # between then and now cannot move it into this month near midnight
    noon = datetime.now().replace(day=1, hour=12, minute=0, second=0, microsecond=0)
    last_month = (noon - timedelta(days=1)).astimezone().timestamp()
    with write_tx(ai_app.engine) as conn:
        conn.execute(
            insert(ai_calls).values(
                at=last_month,
                task="echo",
                model="m",
                files=[],
                input_tokens=1,
                output_tokens=1,
                cost_eur=4.0,
                outcome="ok",
                error=None,
                duration_ms=1,
            )
        )
    assert ai_app.ai.status()["month_spend_eur"] == 0
    assert ai_app.ai.prepare("echo", {"text": "x"}).blocked is None


def test_invalid_output_rejected(ai_app):
    for bad in ({"echo": 1}, {"echo": "x", "action": "delete"}, {"words": ["a"]}, "text"):
        ai_app.ai.provider.reply = lambda **_kw: bad  # noqa: B023 - read before the next loop
        p = ai_app.ai.prepare("echo", {"text": f"doc {bad!r}"})
        with pytest.raises(Conflict, match="did not match"):
            ai_app.ai.run(p.token)
    assert [r["outcome"] for r in rows(ai_app)] == ["error"] * 4
    assert all("did not match" in r["error"] for r in rows(ai_app))
    # the failed calls are still paid for and counted
    assert ai_app.ai.status()["month_spend_eur"] > 0
    with ai_app.engine.connect() as conn:
        assert conn.execute(select(ai_cache)).all() == []


def test_soft_limits_are_the_tasks_post_to_enforce(ai_app, echo, monkeypatch):
    """Lengths and counts are soft service-wide: an over-long list is not rejected
    (the call is ``ok``); what is done with it is the task's ``post``'s duty."""
    words = [f"w{i}" for i in range(7)]  # the schema allows 5
    ai_app.ai.provider.reply = lambda **_kw: {"echo": "x", "words": words}
    r = ai_app.ai.run(ai_app.ai.prepare("echo", {"text": "a"}).token)
    # the echo task's post does not trim: the service passed all 7 through untouched
    assert r.data["words"] == words
    assert [row["outcome"] for row in rows(ai_app)] == ["ok"]
    # a post that owns the limit trims it
    monkeypatch.setattr(echo, "post", lambda data, built: {**data, "words": data["words"][:5]})
    r = ai_app.ai.run(ai_app.ai.prepare("echo", {"text": "b"}).token)
    assert r.data["words"] == words[:5]


def test_provider_failure_is_logged(ai_app):
    def explode(**_kw):
        raise ProviderError("rate limited")

    ai_app.ai.provider.reply = explode
    p = ai_app.ai.prepare("echo", {"text": "x"})
    with pytest.raises(Conflict, match="AI call failed: rate limited"):
        ai_app.ai.run(p.token)
    (row,) = rows(ai_app)
    assert (row["outcome"], row["error"], row["cost_eur"]) == ("error", "rate limited", 0)


def test_output_validator():
    schema = {
        "type": "object",
        "properties": {
            "n": {"type": "number", "minimum": 0, "maximum": 1},
            "k": {"type": "string", "enum": ["a", "b"]},
            "o": {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
            "s": {"type": ["string", "null"], "maxLength": 3},
        },
        "required": ["n"],
    }
    assert guard.validate_output({"n": 0.5}, schema) is None
    assert guard.validate_output({"n": 1, "k": "a", "o": {"x": 2}, "s": None}, schema) is None
    for bad in (
        {},
        {"n": 2},
        {"n": 0, "k": "c"},
        {"n": 0, "o": {}},
        {"n": 0, "o": {"x": 1.5}},
        {"n": 0, "s": "long"},
        {"n": 0, "extra": 1},
        {"n": True},
        [],
    ):
        assert guard.validate_output(bad, schema) is not None
    # soft: lengths and counts are the task's to trim; types, keys and ranges stay fatal
    assert guard.validate_output({"n": 0, "s": "long"}, schema, soft=True) is None
    for bad in ({"n": 2}, {"n": 0, "extra": 1}, {"n": 0, "s": 5}, {}):
        assert guard.validate_output(bad, schema, soft=True) is not None


def test_text_limits_and_estimate():
    assert guard.cut("abcdef", 3) == "abc"
    assert guard.cut("ab", 3) == "ab"
    assert guard.estimate_input_tokens("") == 0
    assert guard.estimate_input_tokens("a" * 35) == 10
    assert guard.estimate_input_tokens("a" * 36) == 11
    assert guard.delimited("document", "x") == "<document>\nx\n</document>"


# -- API --------------------------------------------------------------------------------


def test_api_prepare_run_and_log(client, ai_app):
    s = client.get("/api/ai/status", headers=LOCAL_ORIGIN).json()
    assert s["has_key"] is True and s["enabled"] is True and s["budget_eur"] == 5
    r = client.post(
        "/api/ai/echo/prepare", json={"params": {"drive_id": "f1"}}, headers=LOCAL_ORIGIN
    )
    assert r.status_code == 200, r.text
    p = r.json()
    assert set(p) >= {
        "task",
        "model",
        "system",
        "payload_text",
        "files",
        "estimate_eur",
        "blocked",
        "token",
        "cached",
    }
    assert p["blocked"] is None and p["cached"] is None
    r = client.post("/api/ai/echo/run", json={"token": p["token"]}, headers=LOCAL_ORIGIN)
    assert r.status_code == 200, r.text
    assert r.json()["cached"] is False and r.json()["data"]["echo"] == p["payload_text"]
    r = client.post("/api/ai/echo/run", json={"token": p["token"]}, headers=LOCAL_ORIGIN)
    assert r.status_code == 400 and "Prepare it again" in r.json()["error"]
    log = client.get("/api/ai/log?limit=5", headers=LOCAL_ORIGIN).json()["rows"]
    assert len(log) == 1 and log[0]["outcome"] == "ok" and log[0]["files"] == ["f1"]
    assert set(log[0]) == {
        "id",
        "at",
        "task",
        "model",
        "files",
        "input_tokens",
        "output_tokens",
        "cost_eur",
        "outcome",
        "error",
        "duration_ms",
    }
    assert (
        client.post("/api/ai/nope/prepare", json={"params": {}}, headers=LOCAL_ORIGIN).status_code
        == 404
    )
    r = client.post(
        "/api/ai/echo/prepare", json={"params": {"drive_id": "m1"}}, headers=LOCAL_ORIGIN
    )
    assert r.status_code == 200 and "excluded folder" in r.json()["blocked"]
    r = client.post("/api/ai/echo/run", json={"token": r.json()["token"]}, headers=LOCAL_ORIGIN)
    assert r.status_code == 400 and "excluded folder" in r.json()["error"]
    # unknown body fields are refused
    assert (
        client.post(
            "/api/ai/echo/run", json={"token": "x", "params": {}}, headers=LOCAL_ORIGIN
        ).status_code
        == 422
    )


def test_api_log_is_newest_first_and_limited(client, ai_app):
    for i in range(3):
        p = ai_app.ai.prepare("echo", {"text": f"t{i}"})
        ai_app.ai.run(p.token)
    log = client.get("/api/ai/log?limit=2", headers=LOCAL_ORIGIN).json()["rows"]
    assert [r["id"] for r in log] == [3, 2]
    assert client.get("/api/ai/log?limit=0", headers=LOCAL_ORIGIN).status_code == 422


# -- CLI --------------------------------------------------------------------------------


def test_cli_status_and_log(app_paths, echo, fake_keyring):
    runner = CliRunner()
    data = ["--data-dir", str(app_paths.data_dir)]
    r = runner.invoke(cli, [*data, "ai", "--status"])
    assert r.exit_code == 0, r.output
    assert "key: missing" in r.output and "AI: off" in r.output
    assert "€0.00 of €5.00" in r.output
    r = runner.invoke(cli, [*data, "ai", "--set-key"], input="sk-ant-secret\nsk-ant-secret\n")
    assert r.exit_code == 0, r.output
    assert "stored in the Keychain" in r.output and "sk-ant-secret" not in r.output
    assert fake_keyring.store[("dam-anthropic", "api-key")] == "sk-ant-secret"
    r = runner.invoke(cli, [*data, "ai", "--status"])
    assert "key: present" in r.output and "AI: on" in r.output
    assert "sk-ant" not in r.output
    r = runner.invoke(cli, [*data, "ai", "--off"])
    assert r.exit_code == 0 and "AI: off" in r.output
    assert (app_paths.data_dir / "ai-state.json").read_text(
        encoding="utf-8"
    ) == '{"enabled": false}'
    r = runner.invoke(cli, [*data, "ai", "--on"])
    assert r.exit_code == 0 and "AI: on" in r.output
    r = runner.invoke(cli, [*data, "ai", "--log"])
    assert r.exit_code == 0 and "no AI calls" in r.output
    r = runner.invoke(cli, [*data, "ai", "--clear-key"])
    assert r.exit_code == 0 and "removed" in r.output
    assert fake_keyring.store == {}
    r = runner.invoke(cli, [*data, "ai", "--status", "--log"])
    assert r.exit_code == 2


def test_cli_log_prints_rows(app_paths, echo, monkeypatch):
    monkeypatch.setenv("DAM_AI_FAKE", "1")
    from dam.app import App

    a = App.create(app_paths.data_dir)
    try:
        a.ai.run(a.ai.prepare("echo", {"text": "hello"}).token)
    finally:
        a.close()
    r = CliRunner().invoke(cli, ["--data-dir", str(app_paths.data_dir), "ai", "--log"])
    assert r.exit_code == 0, r.output
    # the DAM_AI_FAKE=1 demo provider: logged as "fake", model "fake:<id>", at no cost
    assert "echo" in r.output and "fake" in r.output and "fake:claude-haiku-5-5" in r.output


# -- the provider and the no-network guard ---------------------------------------------


class FakeUsage:
    input_tokens = 321
    output_tokens = 45


class FakeBlock:
    def __init__(self, type: str, text: str = "") -> None:
        self.type = type
        self.text = text


class FakeResponse:
    def __init__(self, content, stop_reason="end_turn") -> None:
        self.content = content
        self.stop_reason = stop_reason
        self.usage = FakeUsage()


class FakeMessages:
    def __init__(self, response) -> None:
        self.response = response
        self.requests: list[dict] = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FakeClient:
    def __init__(self, response) -> None:
        self.messages = FakeMessages(response)


def test_anthropic_provider_structured_output_with_fake_client():
    client = FakeClient(FakeResponse([FakeBlock("text", '{"echo": "hi"}')]))
    provider = AnthropicProvider(api_key="sk-ant-x", client=client)
    result = provider.complete(
        model="claude-haiku-5-5", system="S", user="U", schema=ECHO_SCHEMA, max_tokens=700
    )
    assert result == AIResult(data={"echo": "hi"}, input_tokens=321, output_tokens=45)
    (req,) = client.messages.requests
    assert req["model"] == "claude-haiku-5-5" and req["max_tokens"] == 700
    assert req["system"] == "S"
    assert req["messages"] == [{"role": "user", "content": "U"}]
    # maxItems is not sent (the API refuses it) but restated; the answer is still checked
    wire = {**ECHO_SCHEMA, "properties": {**ECHO_SCHEMA["properties"]}}
    wire["properties"]["words"] = {
        "type": "array",
        "items": {"type": "string"},
        "description": "at most 5 items",
    }
    assert req["output_config"] == {
        "format": {"type": "json_schema", "schema": wire},
        "effort": "low",
    }
    assert "tools" not in req and "tool_choice" not in req
    provider.effort = "medium"
    provider.complete(model="m", system="S", user="U", schema=ECHO_SCHEMA, max_tokens=7)
    assert client.messages.requests[1]["output_config"]["effort"] == "medium"


def test_anthropic_provider_builds_the_client_with_timeout_and_no_retry(monkeypatch):
    import anthropic

    built: list[dict] = []

    def fake_init(self, **kwargs):
        built.append(kwargs)
        self.messages = FakeMessages(FakeResponse([FakeBlock("text", '{"echo": "x"}')]))

    monkeypatch.setattr(anthropic.Anthropic, "__init__", fake_init)
    provider = AnthropicProvider(api_key="sk-ant-x")
    provider.complete(model="m", system="s", user="u", schema=ECHO_SCHEMA, max_tokens=5)
    provider.complete(model="m", system="s", user="u", schema=ECHO_SCHEMA, max_tokens=5)
    # never retried: a retry after a timeout could bill the call twice
    assert built == [{"api_key": "sk-ant-x", "timeout": 60, "max_retries": 0}]  # built once


def test_billed_but_unusable_answers_carry_their_usage():
    for response in (
        FakeResponse([], stop_reason="refusal"),
        FakeResponse([FakeBlock("text", '{"a":')], stop_reason="max_tokens"),
        FakeResponse([FakeBlock("thinking")]),
        FakeResponse([FakeBlock("text", "not json")]),
        FakeResponse([FakeBlock("text", "[1]")]),
    ):
        provider = AnthropicProvider(api_key="k", client=FakeClient(response))
        with pytest.raises(ProviderError) as info:
            provider.complete(model="m", system="s", user="u", schema=ECHO_SCHEMA, max_tokens=5)
        assert (info.value.input_tokens, info.value.output_tokens) == (321, 45)


def test_api_error_message_is_truncated_and_key_free():
    import anthropic
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(400, request=request)
    message = "invalid x-api-key sk-ant-api03-SECRET" + "y" * 500
    error = anthropic.BadRequestError(message, response=response, body=None)
    provider = AnthropicProvider(api_key="k", client=FakeClient(error))
    with pytest.raises(ProviderError) as info:
        provider.complete(model="m", system="s", user="u", schema=ECHO_SCHEMA, max_tokens=5)
    text = str(info.value)
    assert text.startswith("API error 400: BadRequestError: invalid x-api-key sk-ant-...")
    assert "SECRET" not in text and len(text) < 260
    assert (info.value.input_tokens, info.value.output_tokens) == (0, 0)


def test_cut_off_answer_is_logged_with_its_usage(ai_app):
    def cut_off(**_kw):
        raise ProviderError(
            "the answer was cut off (max_tokens)", input_tokens=900, output_tokens=400
        )

    ai_app.ai.provider.reply = cut_off
    p = ai_app.ai.prepare("echo", {"text": "x"})
    with pytest.raises(Conflict, match="cut off"):
        ai_app.ai.run(p.token)
    (row,) = rows(ai_app)
    expected = (900 * 0.10 + 400 * 0.50) / 1_000_000 * 0.92
    assert (row["outcome"], row["input_tokens"], row["output_tokens"]) == ("error", 900, 400)
    assert row["cost_eur"] == pytest.approx(expected)
    assert ai_app.ai.status()["month_spend_eur"] == pytest.approx(expected)


def test_concurrent_runs_share_one_budget(ai_app):
    """Two runs that both passed the preview: the second waits for the first's log row
    and is then refused because the budget is now used up."""
    import threading

    started, release = threading.Event(), threading.Event()

    def slow(**_kw):
        started.set()
        assert release.wait(10)
        return {"echo": "ok"}

    ai_app.ai.provider.reply = slow
    ai_app.ai.provider.output_tokens = 4000  # the real cost exceeds the estimate
    p1 = ai_app.ai.prepare("echo", {"text": "one"})
    p2 = ai_app.ai.prepare("echo", {"text": "two"})
    ai_app.settings.ai.monthly_budget_eur = p1.estimate_eur * 1.5  # room for one call
    results: dict[str, object] = {}

    def run(name, token):
        try:
            results[name] = ai_app.ai.run(token)
        except Exception as e:  # noqa: BLE001 - inspected below
            results[name] = e

    t1 = threading.Thread(target=run, args=("one", p1.token))
    t1.start()
    assert started.wait(10)
    t2 = threading.Thread(target=run, args=("two", p2.token))
    t2.start()
    t2.join(0.3)
    assert t2.is_alive() and "two" not in results  # waiting for the send lock
    release.set()
    t1.join(10)
    t2.join(10)
    assert results["one"].data == {"echo": "ok", "posted": True}
    assert isinstance(results["two"], InvalidRequest) and "budget" in str(results["two"])
    assert len(ai_app.ai.provider.calls) == 1
    assert [r["outcome"] for r in rows(ai_app)] == ["ok"]


def test_month_start_is_local_midnight_on_the_first(monkeypatch):
    import time as time_mod

    if not hasattr(time_mod, "tzset"):
        pytest.skip("sets the process time zone through TZ and time.tzset, which Windows lacks")
    from zoneinfo import ZoneInfo

    from dam.ai import log as ai_log

    monkeypatch.setenv("TZ", "Europe/Helsinki")
    time_mod.tzset()
    try:
        # after the DST change (2026-10-25): the 1st is still at +03:00, not +02:00
        now = datetime(2026, 10, 31, 12, 0)
        expected = datetime(2026, 10, 1, tzinfo=ZoneInfo("Europe/Helsinki")).timestamp()
        assert ai_log.month_start(now) == expected
        # an aware "now" from another zone is read by its own calendar fields
        assert ai_log.month_start(now.astimezone(ZoneInfo("UTC"))) == expected
    finally:
        monkeypatch.delenv("TZ")
        time_mod.tzset()


def test_log_record_refuses_unknown_outcome(engine):
    from dam.ai import log as ai_log

    with pytest.raises(ValueError):
        ai_log.record(
            engine,
            task="t",
            model="m",
            files=[],
            input_tokens=0,
            output_tokens=0,
            cost_eur=0,
            outcome="blocked",
            error=None,
            duration_ms=0,
        )


def test_anthropic_provider_errors_become_provider_errors():
    import anthropic

    for response in (
        FakeResponse([FakeBlock("text", "not json")]),
        FakeResponse([FakeBlock("text", "[1]")]),
        FakeResponse([], stop_reason="refusal"),
        FakeResponse([FakeBlock("text", '{"a":')], stop_reason="max_tokens"),
        anthropic.APIConnectionError(request=None),
    ):
        provider = AnthropicProvider(api_key="k", client=FakeClient(response))
        with pytest.raises(ProviderError):
            provider.complete(model="m", system="s", user="u", schema=ECHO_SCHEMA, max_tokens=5)


def test_real_client_is_never_built_in_tests():
    provider = AnthropicProvider(api_key="sk-ant-x")
    with pytest.raises(AssertionError, match="never construct"):
        provider.complete(model="m", system="s", user="u", schema=ECHO_SCHEMA, max_tokens=5)


def test_key_from_keyring_builds_provider_lazily(app, echo):
    keys.set_key("sk-ant-test")
    p = app.ai.prepare("echo", {"text": "x"})  # no client yet: prepare never calls
    # run builds it, which the autouse guard refuses (an unexpected error: logged)
    with pytest.raises(Conflict, match="AI call failed: AssertionError"):
        app.ai.run(p.token)
    assert [r["error"] for r in rows(app)] == ["unexpected error: AssertionError"]


def test_only_run_calls_the_provider():
    """No code path calls ``provider.complete`` outside ``AIService.run`` (spec §2.1)."""
    src = Path(__file__).parents[1] / "src" / "dam"
    hits: list[tuple[str, str]] = []
    for path in src.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                for sub in ast.walk(node):
                    if (
                        isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "complete"
                    ):
                        hits.append((path.relative_to(src).as_posix(), node.name))
    # ``_send`` is the body of ``run``, under its send lock
    assert hits == [("ai/service.py", "_send")]


def test_ai_provider_fake_default_reply_matches_schema():
    fake = FakeProvider()
    r = fake.complete(model="m", system="s", user="u", schema=ECHO_SCHEMA, max_tokens=5)
    assert guard.validate_output(r.data, ECHO_SCHEMA) is None
    assert r.input_tokens > 0 and r.output_tokens > 0


# -- final fix wave: output limits leave room for thinking ------------------------------


def test_max_tokens_defaults_leave_room_for_thinking():
    """``effort: low`` still thinks, and thinking counts against ``max_tokens``: the
    defaults are sized so a short answer is not cut off."""
    from dam.config import AISettings

    assert AISettings().max_tokens == {
        "suggest-filing": 2500,
        "summarize-document": 1500,
        "summarize-collection": 3000,
        "ask-archive": 3000,
    }
    assert AISettings().effort == "low"


def test_estimate_scales_with_max_tokens(ai_app):
    small = ai_app.ai.prepare("echo", {"text": "same"}).estimate_eur
    ai_app.settings.ai.max_tokens["echo"] = 3000
    large = ai_app.ai.prepare("echo", {"text": "same"}).estimate_eur
    # the output is priced at max_tokens: 2300 more tokens at $0.50/MTok
    assert large - small == pytest.approx((3000 - 700) * 0.50 / 1_000_000 * 0.92)


def test_no_thinking_parameter_is_sent():
    client = FakeClient(FakeResponse([FakeBlock("text", '{"echo": "hi"}')]))
    provider = AnthropicProvider(api_key="sk-ant-x", client=client)
    provider.complete(model="m", system="S", user="U", schema=ECHO_SCHEMA, max_tokens=2500)
    (req,) = client.messages.requests
    assert "thinking" not in req and req["max_tokens"] == 2500
    assert req["output_config"]["effort"] == "low"


# -- final fix wave: a timeout is not retried and is counted at its estimate ------------


def _timeout_error():
    import anthropic
    import httpx2

    return anthropic.APITimeoutError(
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    )


def _connection_error(cause: Exception):
    import anthropic
    import httpx2

    error = anthropic.APIConnectionError(
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    error.__cause__ = cause
    return error


def test_timeout_and_maybe_sent_connection_errors_have_unknown_usage():
    import httpx2

    cases = [
        (_timeout_error(), True, "timeout: usage unknown"),
        (_connection_error(httpx2.ReadError("reset")), True, "connection lost: usage unknown"),
        (_connection_error(httpx2.RemoteProtocolError("eof")), True, "connection lost"),
        # never connected: nothing was sent, nothing can have been billed
        (_connection_error(httpx2.ConnectError("refused")), False, "connection failed"),
    ]
    for error, unknown, message in cases:
        provider = AnthropicProvider(api_key="k", client=FakeClient(error))
        with pytest.raises(ProviderError) as info:
            provider.complete(model="m", system="s", user="u", schema=ECHO_SCHEMA, max_tokens=5)
        assert info.value.usage_unknown is unknown, error
        assert str(info.value).startswith(message)
        assert (info.value.input_tokens, info.value.output_tokens) == (0, 0)


def test_timeout_is_logged_at_its_estimate(ai_app):
    """A call that timed out may still have been billed: the month figure counts it at
    the worst-case estimate (conservative), and the provider is called exactly once."""
    client = FakeClient(_timeout_error())
    ai_app.ai.provider = AnthropicProvider(api_key="k", client=client)
    p = ai_app.ai.prepare("echo", {"text": "x"})
    assert p.estimate_eur > 0
    with pytest.raises(Conflict) as info:
        ai_app.ai.run(p.token)
    # plain words: the limit this call had, nothing changed, the counted amount
    message = str(info.value)
    assert message.startswith(f"Claude didn't answer within {guard.duration_text(p.timeout_s)}")
    assert "Nothing was changed. Try again." in message
    assert f"Up to {guard.euro_text(p.estimate_eur)} is counted this month" in message
    assert "timeout" not in message and "Conflict" not in message
    assert len(client.messages.requests) == 1
    assert client.messages.requests[0]["timeout"] == p.timeout_s
    (row,) = rows(ai_app)
    assert (row["outcome"], row["error"]) == ("error", "timeout: usage unknown")
    assert row["cost_eur"] == pytest.approx(p.estimate_eur)
    assert ai_app.ai.status()["month_spend_eur"] == pytest.approx(p.estimate_eur)


def test_connection_refused_costs_nothing(ai_app):
    import httpx2

    client = FakeClient(_connection_error(httpx2.ConnectError("refused")))
    ai_app.ai.provider = AnthropicProvider(api_key="k", client=client)
    p = ai_app.ai.prepare("echo", {"text": "x"})
    with pytest.raises(Conflict, match="could not reach Claude"):
        ai_app.ai.run(p.token)
    (row,) = rows(ai_app)
    assert row["cost_eur"] == 0


# -- final fix wave: ai-state.json fails closed ----------------------------------------


def test_missing_state_file_means_on(ai_app):
    assert not ai_app.ai.state_path.exists()
    s = ai_app.ai.status()
    assert s["switched_on"] is True and s["enabled"] is True and s["state_error"] is None


@pytest.mark.parametrize(
    "content",
    ["", "{not json", "[true]", '"on"', "{}", '{"enabled": "yes"}', '{"enabled": 1}'],
)
def test_invalid_state_file_means_off(ai_app, content, caplog):
    ai_app.ai.state_path.write_text(content, encoding="utf-8")
    with caplog.at_level("WARNING", logger="dam.ai.service"):
        s = ai_app.ai.status()
    assert s["switched_on"] is False and s["enabled"] is False
    assert s["state_error"] and "ai-state.json" in s["state_error"]
    assert any("ai-state.json" in r.getMessage() for r in caplog.records)
    with pytest.raises(Conflict, match="dam ai --on"):
        ai_app.ai.prepare("echo", {"text": "hi"})
    # switching on again rewrites the file and clears the error
    ai_app.ai.set_enabled(True)
    s = ai_app.ai.status()
    assert s["switched_on"] is True and s["state_error"] is None


def test_unreadable_state_file_means_off(ai_app):
    ai_app.ai.state_path.mkdir()  # reading a directory fails (IsADirectoryError)
    s = ai_app.ai.status()
    assert s["switched_on"] is False and "ai-state.json" in s["state_error"]


def test_set_enabled_reads_back_and_raises_when_it_does_not_stick(ai_app, monkeypatch):
    from pathlib import Path

    real_write = Path.write_text

    def lossy(self, data, *a, **kw):  # a write that lands as something else
        return real_write(self, data[:-3], *a, **kw)

    monkeypatch.setattr(Path, "write_text", lossy)
    with pytest.raises(Conflict, match="ai-state.json"):
        ai_app.ai.set_enabled(False)


def test_set_enabled_write_failure_is_reported(ai_app, monkeypatch):
    from pathlib import Path

    def fail(self, *a, **kw):
        raise PermissionError("read-only")

    monkeypatch.setattr(Path, "write_text", fail)
    with pytest.raises(Conflict, match="Could not save"):
        ai_app.ai.set_enabled(False)


def test_api_state_body_is_a_strict_bool(client):
    for bad in ("false", 0, 1, "true", None):
        r = client.post("/api/ai/state", json={"enabled": bad}, headers=LOCAL_ORIGIN)
        assert r.status_code == 422, bad
    r = client.post("/api/ai/state", json={"enabled": False}, headers=LOCAL_ORIGIN)
    assert r.status_code == 200 and r.json()["state_error"] is None


def test_cli_status_shows_state_error(app_paths, echo, fake_keyring):
    (app_paths.data_dir / "ai-state.json").write_text("{broken", encoding="utf-8")
    r = CliRunner().invoke(cli, ["--data-dir", str(app_paths.data_dir), "ai", "--status"])
    assert r.exit_code == 0, r.output
    assert "AI: off" in r.output and "ai-state.json" in r.output


# -- final fix wave: the Keychain is not asked on every status call --------------------


@pytest.fixture
def keychain_lookups(monkeypatch):
    real = keys.get_key
    calls: list[int] = []

    def counting():
        calls.append(1)
        return real()

    monkeypatch.setattr(keys, "get_key", counting)
    return calls


@pytest.fixture
def clock(monkeypatch):
    from dam.ai import service

    now = [1000.0]
    monkeypatch.setattr(service, "_clock", lambda: now[0])
    return now


def test_has_key_is_memoised_for_60_seconds(app, echo, keychain_lookups, clock):
    keys.set_key("sk-ant-test")
    for _ in range(5):
        assert app.ai.status()["has_key"] is True
    assert len(keychain_lookups) == 1
    keys.clear_key()  # behind the service's back (another process): seen after 60 s
    clock[0] += 59
    assert app.ai.status()["has_key"] is True and len(keychain_lookups) == 1
    clock[0] += 2
    assert app.ai.status()["has_key"] is False and len(keychain_lookups) == 2


def test_set_and_clear_key_invalidate_the_memo(app, echo, keychain_lookups, clock):
    assert app.ai.status()["has_key"] is False
    app.ai.set_key("sk-ant-test")
    assert app.ai.status()["has_key"] is True
    app.ai.clear_key()
    assert app.ai.status()["has_key"] is False
    assert keys.get_key() is None


def test_refresh_asks_the_keychain_again(app, echo, keychain_lookups, clock):
    assert app.ai.status()["has_key"] is False
    keys.set_key("sk-ant-test")
    assert app.ai.status()["has_key"] is False  # memoised
    assert app.ai.status(refresh=True)["has_key"] is True
    assert len(keychain_lookups) == 2


def test_a_keychain_error_is_memoised_too(app, echo, monkeypatch, clock):
    calls: list[int] = []

    def broken():
        calls.append(1)
        raise keys.KeychainError("the Keychain did not answer")

    monkeypatch.setattr(keys, "get_key", broken)
    assert app.ai.status()["has_key"] is False
    assert app.ai.status()["has_key"] is False
    assert len(calls) == 1  # a hung Keychain costs one timeout per minute, not per call


def test_run_without_a_key_clears_the_memo(app, echo, keychain_lookups, clock):
    keys.set_key("sk-ant-test")
    p = app.ai.prepare("echo", {"text": "x"})
    keys.clear_key()  # gone before Send
    with pytest.raises(Conflict, match="add a key"):
        app.ai.run(p.token)
    assert app.ai.status()["has_key"] is False  # without waiting for the 60 s


def test_cli_ai_commands_refresh_the_key(app_paths, echo, monkeypatch):
    from dam.ai.service import AIService

    seen: list[bool] = []
    real = AIService.status

    def spy(self, refresh=False):
        seen.append(refresh)
        return real(self, refresh=refresh)

    monkeypatch.setattr(AIService, "status", spy)
    r = CliRunner().invoke(cli, ["--data-dir", str(app_paths.data_dir), "ai", "--status"])
    assert r.exit_code == 0, r.output
    assert seen == [True]


# -- the limit scales with the request, and failures read plainly ----------------------


def test_timeout_limit_grows_with_the_request_and_is_capped():
    assert guard.timeout_s(0, 0) == 60
    assert guard.timeout_s(1_000, 700) == 80  # 60 + 2 + 14, rounded up to 10 s
    assert guard.timeout_s(9_100, 3_000) == 140  # a 40-file collection summary
    assert guard.timeout_s(10_000_000, 700) == 180  # capped
    assert guard.timeout_s(0, 100_000) == 180
    limits = [guard.timeout_s(n, 700) for n in range(0, 200_000, 5_000)]
    assert limits == sorted(limits) and all(60 <= x <= 180 for x in limits)


def test_duration_and_euro_text():
    assert guard.duration_text(120) == "2 minutes"
    assert guard.duration_text(60) == "1 minute"
    assert guard.duration_text(140) == "2 minutes 20 seconds"
    assert guard.duration_text(45) == "45 seconds"
    assert guard.euro_text(0.0024) == "0,0024 €"
    assert guard.euro_text(1.25) == "1,25 €"
    assert guard.euro_text(0) == "0,00 €"


def test_prepare_carries_the_limit_and_run_gives_it_to_the_provider(ai_app):
    p = ai_app.ai.prepare("echo", {"text": "x"})
    assert 60 <= p.timeout_s <= 180
    ai_app.ai.run(p.token)
    assert ai_app.ai.provider.timeouts == [p.timeout_s]


def test_the_anthropic_client_gets_the_per_call_limit():
    client = FakeClient(FakeResponse([FakeBlock("text", '{"echo": "x"}')]))
    provider = AnthropicProvider(api_key="k", client=client)
    provider.complete(
        model="m", system="s", user="u", schema=ECHO_SCHEMA, max_tokens=5, timeout_s=150
    )
    provider.complete(model="m", system="s", user="u", schema=ECHO_SCHEMA, max_tokens=5)
    assert [r["timeout"] for r in client.messages.requests] == [150, 60]


@pytest.mark.parametrize(
    ("kind", "words"),
    [
        ("connect", "could not reach Claude"),
        ("rate_limit", "slow down"),
        ("overloaded", "overloaded"),
        ("auth", "API key"),
    ],
)
def test_failures_not_billed_read_plainly(ai_app, kind, words):
    def fail(**_kw):
        raise ProviderError("API error 429: RateLimitError", kind=kind)

    ai_app.ai.provider.reply = fail
    p = ai_app.ai.prepare("echo", {"text": "x"})
    with pytest.raises(Conflict) as info:
        ai_app.ai.run(p.token)
    assert words in str(info.value) and "API error" not in str(info.value)


def test_connection_lost_reads_plainly_and_is_counted(ai_app):
    def lost(**_kw):
        raise ProviderError("connection lost: usage unknown", usage_unknown=True, kind="lost")

    ai_app.ai.provider.reply = lost
    p = ai_app.ai.prepare("echo", {"text": "x"})
    with pytest.raises(Conflict, match="connection to Claude was lost") as info:
        ai_app.ai.run(p.token)
    assert "is counted this month" in str(info.value)
