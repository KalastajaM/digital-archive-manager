"""prepare / run: the snapshot rule applied to AI (spec §4).

``prepare`` builds exactly what would be sent and returns it with a token (an HMAC, keyed
per process, over the task, model, texts, files and cache key). ``run`` takes that
token, builds the payload again and sends it only if the HMAC still matches: what the
user saw is what goes out. A token is known only to the process that prepared it and
is consumed by its run, so nothing can be sent without a preview.
"""

import hmac
import json
import logging
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from hashlib import sha256
from typing import TYPE_CHECKING, Any

from dam.ai import cache, guard, keys, log
from dam.ai.provider import AIProvider, AIResult, ProviderError
from dam.ai.tasks import TASKS, AITask, Built
from dam.services.errors import Conflict, InvalidRequest, NotFound
from dam.setup import write_ai_exclude_folders

if TYPE_CHECKING:
    from dam.app import App

logger = logging.getLogger(__name__)

OFF_NO_KEY = "AI is off: add a key with dam ai --set-key"
OFF_SWITCHED = "AI is off: turn it on with dam ai --on"
CHANGED = "This has changed since the preview. Prepare it again."
UNKNOWN_TOKEN = "That preview is no longer available. Prepare it again."
PENDING_MAX = 64  # previews kept per process (the newest; older ones must be redone)
KEY_MEMO_S = 60.0  # how long a Keychain answer (key present or not) is reused

_clock = time.monotonic  # patched in tests


@dataclass(frozen=True)
class Prepared:
    task: str
    model: str
    system: str
    payload_text: str
    files: list[str]
    estimate_eur: float
    # how long a send waits for the answer before giving up (seconds); shown, not signed
    timeout_s: int
    blocked: str | None
    token: str
    cached: dict | None
    # shown with the preview, never sent (what the task left out and why)
    notes: list[str] = field(default_factory=list)


_NOT_BILLED = {
    "connect": "The app could not reach Claude. Check the internet connection and try again. "
    "Nothing was sent or charged.",
    "rate_limit": "Claude is asking to slow down (too many requests). Wait a minute and try "
    "again. Nothing was changed or charged.",
    "overloaded": "Claude is overloaded right now. Try again in a few minutes. Nothing was "
    "changed or charged.",
    "auth": "Claude did not accept the API key. Set it again with dam ai --set-key. "
    "Nothing was changed or charged.",
}


def _failure_message(e: ProviderError) -> str:
    """A failed call, in plain words for the person (the log keeps the technical text)."""
    return _NOT_BILLED.get(e.kind) or f"AI call failed: {e}"


def _unknown_usage_message(e: ProviderError, prepared: Prepared) -> str:
    """A timeout or a connection lost mid-call: it may have been billed, so the month
    counts it at its estimate."""
    counted = (
        f"Up to {guard.euro_text(prepared.estimate_eur)} is counted this month in case it "
        "was charged."
    )
    if e.kind == "timeout":
        limit = guard.duration_text(prepared.timeout_s)
        return (
            f"Claude didn't answer within {limit}, so the app stopped waiting. Nothing was "
            f"changed. Try again. {counted}"
        )
    return (
        "The connection to Claude was lost while waiting for the answer, so the app stopped "
        f"waiting. Nothing was changed. Try again. {counted}"
    )


@dataclass(frozen=True)
class RunResult:
    data: dict
    cost_eur: float
    cached: bool


class AIService:
    """``provider`` is injected for tests and ``DAM_AI_FAKE=1`` (and then counts as a
    key); otherwise the Anthropic provider is built from the Keychain key at ``run``."""

    def __init__(self, app: "App", provider: AIProvider | None = None) -> None:
        self.app = app
        self.provider = provider
        self._hmac_key = secrets.token_bytes(32)
        self._pending: OrderedDict[str, tuple[str, dict]] = OrderedDict()
        self._lock = threading.Lock()  # the pending previews
        # held from the budget check through the call and its log row: two runs can
        # never both pass the check on the same month-to-date figure
        self._send_lock = threading.Lock()
        self._anthropic: tuple[str, AIProvider] | None = None
        self._state_warned: str | None = None  # the ai-state.json problem last logged
        # (has_key, when asked): the Keychain is asked at most once a minute, not on
        # every status call (a lookup can wait up to keys.KEYCHAIN_TIMEOUT)
        self._key_memo: tuple[bool, float] | None = None

    # -- settings and state ----------------------------------------------------------

    @property
    def settings(self):
        return self.app.settings.ai

    @property
    def state_path(self):
        return self.app.app_paths.data_dir / "ai-state.json"

    def _read_state(self) -> tuple[bool, str | None]:
        """The switch and, when the file cannot be trusted, why. It fails closed: a
        missing file is on (the default), but an unreadable or invalid one is off."""
        name = self.state_path.name
        try:
            text = self.state_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return True, None
        except OSError as e:
            return False, self._state_problem(f"{name} could not be read ({type(e).__name__})")
        try:
            state = json.loads(text)
        except ValueError:
            return False, self._state_problem(f"{name} is not valid JSON")
        if not isinstance(state, dict) or not isinstance(state.get("enabled"), bool):
            return False, self._state_problem(f'{name} has no "enabled": true or false')
        self._state_warned = None
        return state["enabled"], None

    def _state_problem(self, problem: str) -> str:
        message = f"{problem}; AI is off until it is switched on again"
        if self._state_warned != message:  # once per problem, not on every status call
            logger.warning("%s (%s)", message, self.state_path)
            self._state_warned = message
        return message

    def switched_on(self) -> bool:
        """The ``dam ai --on/--off`` switch (default on; off if the file is invalid)."""
        return self._read_state()[0]

    def state_error(self) -> str | None:
        """Why the switch reads as off although nobody switched it off, else None."""
        return self._read_state()[1]

    def set_enabled(self, on: bool) -> None:
        """Write the switch, then read it back: ``Conflict`` if it did not stick. A plain
        write to the final path (no temp file and rename: the no-delete pin)."""
        try:
            self.state_path.write_text(json.dumps({"enabled": bool(on)}), encoding="utf-8")
        except OSError as e:
            raise Conflict(
                f"Could not save the AI switch to {self.state_path.name} ({type(e).__name__})"
            ) from None
        if self._read_state() != (bool(on), None):
            raise Conflict(
                f"Could not save the AI switch: {self.state_path.name} does not read back "
                f"as {'on' if on else 'off'}"
            )

    def has_key(self, refresh: bool = False) -> bool:
        """Whether a key is in the Keychain, memoised for ``KEY_MEMO_S`` (a failed
        lookup too: it reads as no key). ``set_key``/``clear_key`` and ``refresh``
        ask again; a change made by another process is seen within a minute."""
        if self.provider is not None:
            return True
        memo = self._key_memo
        if not refresh and memo is not None and _clock() - memo[1] < KEY_MEMO_S:
            return memo[0]
        try:
            present = keys.has_key()
        except keys.KeychainError as e:
            logger.warning("AI key lookup failed: %s", e)
            present = False
        self._key_memo = (present, _clock())
        return present

    def invalidate_key(self) -> None:
        self._key_memo = None

    def set_key(self, key: str) -> None:
        """Store the key in the Keychain (``keys.set_key``) and forget the memo."""
        try:
            keys.set_key(key)
        finally:
            self.invalidate_key()

    def clear_key(self) -> None:
        try:
            keys.clear_key()
        finally:
            self.invalidate_key()

    def set_exclude_folders(self, folders: list[str]) -> None:
        """Save the excluded folders to settings.yaml (``ai.exclude_folders``, replacing
        the defaults) and use them from now on: every task reads the list per call, and a
        payload prepared before is checked again when it is sent. InvalidRequest for a bad
        entry; Conflict when the file cannot be written as asked (it is left as it was)."""
        cleaned = guard.clean_exclude_folders(folders)
        try:
            write_ai_exclude_folders(self.app.app_paths, cleaned)
        except ValueError as e:  # an inline ai: section, or yaml that does not read back
            raise Conflict(f"Could not save the excluded folders: {e}") from None
        except OSError as e:
            raise Conflict(
                f"Could not save the excluded folders to settings.yaml ({type(e).__name__})"
            ) from None
        self.settings.exclude_folders = cleaned

    def enabled(self, has_key: bool | None = None) -> bool:
        has_key = self.has_key() if has_key is None else has_key
        return self.settings.enabled and self.switched_on() and has_key

    def status(self, refresh: bool = False) -> dict:
        """``refresh``: ask the Keychain now (the CLI), not the memo."""
        s = self.settings
        has_key = self.has_key(refresh)  # at most one Keychain lookup
        switched_on, state_error = self._read_state()
        return {
            "enabled": s.enabled and switched_on and has_key,
            "has_key": has_key,
            "switched_on": switched_on,
            "state_error": state_error,
            "month_spend_eur": log.month_spend_eur(self.app.engine),
            "budget_eur": s.monthly_budget_eur,
            "models": {"small": s.models.small, "large": s.models.large},
            "exclude_folders": list(s.exclude_folders),
            "exclude_missing": self._missing(s.exclude_folders),
        }

    def _missing(self, folders: list[str]) -> list[str]:
        """The excluded folders that are not folders in the archive now (a typo, or not
        made yet); none while the archive cannot be listed (that is not the same)."""
        if not self.app.archive_available:
            return []
        return [f for f in folders if not (self.app.paths.root / f).is_dir()]

    def recent(self, limit: int = 50) -> list[dict]:
        return log.recent(self.app.engine, limit)

    def _require_on(self) -> None:
        if not self.has_key():
            raise Conflict(OFF_NO_KEY)
        if not self.settings.enabled:
            raise Conflict(OFF_SWITCHED)
        switched_on, state_error = self._read_state()
        if state_error is not None:
            raise Conflict(f"AI is off: {state_error} (dam ai --on)")
        if not switched_on:
            raise Conflict(OFF_SWITCHED)

    # -- prepare ---------------------------------------------------------------------

    def get_task(self, task_id: str) -> AITask:
        try:
            return TASKS[task_id]
        except KeyError:
            raise NotFound(f"AI task {task_id[:40]}") from None

    def _model_for(self, task: AITask) -> str:
        models = self.settings.models
        if task.model_tier == "small":
            return models.small
        if task.model_tier == "large":
            return models.large
        raise InvalidRequest(f"Task {task.id} has an unknown model tier {task.model_tier}")

    def _excluded(self, files: list[str]) -> str | None:
        for drive_id in files:
            rec = self.app.repo.get(drive_id)
            if rec is None:
                return f"{drive_id} is not in the index"
            folder = guard.excluded_folder(rec.path, self.settings.exclude_folders)
            if folder is not None:
                return f"{rec.name} is in an excluded folder ({folder}) and is never sent"
        return None

    def _token(
        self, task: AITask, model: str, built: Built, max_tokens: int, estimate: float
    ) -> str:
        price = self.settings.prices.get(model)
        covered = {
            "task": task.id,
            "prompt_version": task.prompt_version,
            "model": model,
            "max_tokens": max_tokens,
            "estimate_eur": estimate,
            "price": None if price is None else price.model_dump(),
            "usd_to_eur": self.settings.usd_to_eur,
            "system": built.system,
            "user": built.user,
            "files": list(built.files),
            "sha_key": built.sha_key,
            "schema": self._schema(task, built),
            "notes": list(built.notes),
        }
        msg = json.dumps(covered, sort_keys=True, ensure_ascii=False).encode()
        return hmac.new(self._hmac_key, msg, sha256).hexdigest()

    @staticmethod
    def _schema(task: AITask, built: Built) -> dict:
        """The output schema for this call: the task's, or the one ``build`` made for
        these inputs (suggest-filing: the configured trays' field names)."""
        return built.schema if built.schema is not None else task.schema

    def _build(self, task_id: str, params: dict[str, Any]) -> tuple[Prepared, AITask, Built]:
        task = self.get_task(task_id)
        model = self._model_for(task)
        max_tokens = self.settings.max_tokens.get(task.id, guard.DEFAULT_MAX_TOKENS)
        built = task.build(self.app, params)
        if not isinstance(built, Built):  # a plain (system, user, files, sha_key) tuple
            built = Built(*built)
        blocked = built.blocked or self._excluded(built.files)
        cached = None
        if blocked is None and not params.get("refresh"):
            cached = cache.get(self.app.engine, built.sha_key, task.id, model, task.prompt_version)
        chars = len(built.system) + len(built.user) + len(json.dumps(self._schema(task, built)))
        input_tokens = guard.estimate_tokens(chars)
        try:
            estimate = guard.cost_eur(self.settings, model, input_tokens, max_tokens)
        except KeyError:
            estimate = 0.0
            if blocked is None and cached is None:
                blocked = f"no price for model {model} in ai.prices"
        if blocked is None and cached is None:
            spent = log.month_spend_eur(self.app.engine)
            budget = self.settings.monthly_budget_eur
            if spent + estimate > budget:
                blocked = (
                    f"over budget: €{spent:.2f} spent this month + €{estimate:.4f} "
                    f"estimate > €{budget:.2f} cap"
                )
        prepared = Prepared(
            task=task.id,
            model=model,
            system=built.system,
            payload_text=built.user,
            files=list(built.files),
            estimate_eur=estimate,
            timeout_s=guard.timeout_s(input_tokens, max_tokens),
            blocked=blocked,
            token=self._token(task, model, built, max_tokens, estimate),
            cached=cached,
            notes=list(built.notes),
        )
        return prepared, task, built

    def prepare(self, task_id: str, params: dict[str, Any]) -> Prepared:
        """What would be sent, what it costs, whether it is blocked and why, and the token
        ``run`` needs. Nothing is sent."""
        self._require_on()
        prepared, _, _ = self._build(task_id, dict(params))
        with self._lock:
            self._pending[prepared.token] = (task_id, dict(params))
            while len(self._pending) > PENDING_MAX:
                self._pending.popitem(last=False)
        return prepared

    # -- run ---------------------------------------------------------------------------

    def _provider(self) -> AIProvider:
        if self.provider is not None:
            return self.provider
        try:
            key = keys.get_key()
        except keys.KeychainError as e:
            self.invalidate_key()
            raise Conflict(str(e)) from None
        self._key_memo = (key is not None, _clock())  # what the Keychain just said
        if key is None:
            raise Conflict(OFF_NO_KEY)
        if self._anthropic is None or self._anthropic[0] != key:
            from dam.ai.anthropic import AnthropicProvider

            self._anthropic = (key, AnthropicProvider(key, effort=self.settings.effort))
        self._anthropic[1].effort = self.settings.effort
        return self._anthropic[1]

    def run(self, token: str, task_id: str | None = None) -> RunResult:
        """Send exactly the previewed payload for ``token``, or refuse: unknown or
        already used token, anything changed since the preview, blocked now (an
        excluded file, the budget), no key. ``task_id`` (the route) must match."""
        self._require_on()
        with self._lock:
            pending = self._pending.pop(token, None)
        if pending is None or (task_id is not None and pending[0] != task_id):
            raise InvalidRequest(UNKNOWN_TOKEN)
        task_id, params = pending
        with self._send_lock:
            return self._send(token, task_id, params)

    def _send(self, token: str, task_id: str, params: dict) -> RunResult:
        prepared, task, built = self._build(task_id, params)
        if not hmac.compare_digest(prepared.token, token):
            raise InvalidRequest(CHANGED)
        if prepared.blocked is not None:
            raise InvalidRequest(prepared.blocked)
        common = {"task": task.id, "model": prepared.model, "files": prepared.files}
        if prepared.cached is not None:
            log.record(
                self.app.engine,
                **common,
                input_tokens=0,
                output_tokens=0,
                cost_eur=0.0,
                outcome="cached",
                error=None,
                duration_ms=0,
            )
            return RunResult(data=prepared.cached, cost_eur=0.0, cached=True)
        provider = self._provider()
        demo = getattr(provider, "demo", False) is True
        max_tokens = self.settings.max_tokens.get(task.id, guard.DEFAULT_MAX_TOKENS)
        schema = self._schema(task, built)
        started = time.monotonic()
        try:
            result = provider.complete(
                model=prepared.model,
                system=built.system,
                user=built.user,
                schema=schema,
                max_tokens=max_tokens,
                timeout_s=prepared.timeout_s,
            )
        except ProviderError as e:
            if demo:
                raise Conflict(f"AI call failed: {e}") from None
            # a billed-but-unusable answer (refusal, cut off, not JSON) is priced too
            usage = self._usage(prepared.model, e.input_tokens, e.output_tokens, started)
            if e.usage_unknown:
                # no answer, but it may have been billed: counted at the worst case so
                # the month figure (and the budget check) stays conservative
                usage["cost_eur"] = prepared.estimate_eur
                log.record(self.app.engine, **common, **usage, outcome="error", error=str(e))
                raise Conflict(_unknown_usage_message(e, prepared)) from None
            log.record(self.app.engine, **common, **usage, outcome="error", error=str(e))
            raise Conflict(_failure_message(e)) from None
        except Exception as e:
            # not a provider failure we know: the usage is unknown and the message may
            # carry anything (never logged or shown), so only the type is recorded
            logger.warning("AI provider raised %s", type(e).__name__)
            usage = self._usage(prepared.model, 0, 0, started)
            if not demo:
                # the request may have reached the server (e.g. an unreadable answer):
                # counted at the worst case, as for a timeout
                usage["cost_eur"] = prepared.estimate_eur
            error = f"unexpected error: {type(e).__name__}"
            log.record(self.app.engine, **common, **usage, outcome="error", error=error)
            raise Conflict(f"AI call failed: {type(e).__name__}") from None
        if demo:
            return self._logged_demo(result, prepared, task, built, schema, started)
        usage = self._usage(prepared.model, result.input_tokens, result.output_tokens, started)
        # length and count limits are soft: each task's ``post`` trims what goes over
        problem = guard.validate_output(result.data, schema, soft=True)
        if problem is not None:
            message = f"the AI answer did not match the expected format ({problem})"
            log.record(self.app.engine, **common, **usage, outcome="error", error=message)
            raise Conflict(f"{message}; nothing was applied")
        # the answer was billed: its row is written before anything else can fail
        log.record(self.app.engine, **common, **usage, outcome="ok", error=None)
        try:
            data = task.post(dict(result.data), built)
        except Exception:
            logger.exception("post-processing the %s answer failed", task.id)
            raise Conflict("The AI answer could not be processed; nothing was applied") from None
        try:
            cache.put(
                self.app.engine, built.sha_key, task.id, prepared.model, task.prompt_version, data
            )
        except Exception:
            logger.warning("caching the %s answer failed", task.id, exc_info=True)
        return RunResult(data=data, cost_eur=usage["cost_eur"], cached=False)

    def _logged_demo(
        self,
        result: AIResult,
        prepared: Prepared,
        task: AITask,
        built: Built,
        schema: dict,
        started: float,
    ) -> RunResult:
        """The ``DAM_AI_FAKE=1`` demo provider answered: nothing left the machine, so the
        answer is never cached (a real key would otherwise get a demo answer "from
        earlier") and never priced: logged at cost 0 as outcome "fake", model
        ``fake:<id>``. An invalid answer is still an error with nothing applied."""
        common = {
            "task": task.id,
            "model": f"fake:{prepared.model}",
            "files": prepared.files,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cost_eur": 0.0,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
        problem = guard.validate_output(result.data, schema, soft=True)
        if problem is not None:
            message = f"the AI answer did not match the expected format ({problem})"
            log.record(self.app.engine, **common, outcome="error", error=message)
            raise Conflict(f"{message}; nothing was applied")
        log.record(self.app.engine, **common, outcome="fake", error=None)
        return RunResult(data=task.post(dict(result.data), built), cost_eur=0.0, cached=False)

    def _usage(self, model: str, input_tokens: int, output_tokens: int, started: float) -> dict:
        try:
            cost = guard.cost_eur(self.settings, model, input_tokens, output_tokens)
        except KeyError:  # the price table changed between prepare and the answer
            cost = 0.0
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_eur": cost,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
