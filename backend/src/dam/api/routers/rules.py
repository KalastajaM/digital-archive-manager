"""Filing rules: list them with their record, prove one against the past, save, delete,
reorder, explain a document, and the "offer a rule" setting."""

from dataclasses import asdict

from fastapi import APIRouter
from pydantic import ValidationError

from dam.api.deps import AppDep
from dam.api.schemas import (
    ReplayOut,
    RuleExplainIn,
    RuleExplainOut,
    RuleIn,
    RuleMoveIn,
    RuleReplayIn,
    RulesDeclineIn,
    RulesOut,
    RulesStateIn,
    RulesStateOut,
)
from dam.app import App
from dam.codes.model import format_validation
from dam.rules import state as rules_state
from dam.rules.learned import rule_file
from dam.rules.model import LEARNED_FILE, Rule
from dam.rules.replay import explain, replay
from dam.services.errors import InvalidRequest, NotFound
from dam.services.rule_record import RuleStats

router = APIRouter(prefix="/api/rules", tags=["rules"])

# Ids that would collide with fixed routes: ``/state`` is routed before ``/{rule_id}``,
# but a rule of that name could never be addressed by a POST/DELETE sibling cleanly.
_RESERVED = {"state", "replay", "explain"}

_NO_STATS = RuleStats(suggested=0, changed=0, last_used=None, flagged=False)


def _state_out(app: App, state: rules_state.RulesState | None = None) -> dict:
    state = state or rules_state.load_state(app.app_paths.data_dir)
    return {"offer": state.offer, "declined": len(state.declined)}


def _out(app: App) -> dict:
    stats = app.rule_record.stats()
    rules = []
    for r in app.rules:
        path = rule_file(app.rules_dir, r.id)
        name = path.name if path is not None else LEARNED_FILE
        rules.append(
            {
                "id": r.id,
                "file": name,
                "learned": name == LEARNED_FILE,
                "when": r.when.model_dump(),
                "then": r.then.model_dump(),
                "stats": asdict(stats.get(r.id, _NO_STATS)),
            }
        )
    return {
        "rules": rules,
        "errors": [asdict(e) for e in app.rule_errors],
        "state": _state_out(app),
    }


def _rule(body: RuleIn) -> Rule:
    try:
        return Rule.model_validate(body.model_dump())
    except ValidationError as e:
        raise InvalidRequest(format_validation(e)) from e


@router.get("", response_model=RulesOut)
def list_rules(app: AppDep) -> dict:
    """The loaded rules in load order (the file each is in, whether it is a learned rule
    and how its suggestions have fared), files that were skipped, and the offer state."""
    return _out(app)


@router.post("/replay", response_model=ReplayOut)
def replay_rule(app: AppDep, body: RuleReplayIn) -> dict:
    """What the rule would have done to the files already filed. ``replaces`` puts it
    where that rule stands, otherwise where a new rule is saved. Changes nothing."""
    rule = _rule(body.rule)
    order = list(app.rules)
    if body.replaces is not None:
        at = next((i for i, r in enumerate(order) if r.id == body.replaces), None)
        if at is None:
            raise NotFound(body.replaces)
        order[at] = rule
    else:
        last = -1
        for i, r in enumerate(order):
            path = rule_file(app.rules_dir, r.id)
            if path is not None and path.name == LEARNED_FILE:
                last = i
        order.insert(last + 1, rule)
    result = replay(
        app.engine,
        rule,
        order,
        app.settings.special_folders,
        inbox_code_of=app.repo.inbox_code_of,
    )
    out = asdict(result)
    out["shadowed"] = [{"drive_id": d, "rule_id": r} for d, r in result.shadowed]
    return out


@router.post("/explain", response_model=list[RuleExplainOut])
def explain_document(app: AppDep, body: RuleExplainIn) -> list:
    """For one document: which rules match, why (not), and what each one wins."""
    rec, text, alias = app.inbox.rule_context(body.drive_id)
    return [asdict(x) for x in explain(rec, text, app.rules, app.settings.special_folders, alias)]


@router.put("/state", response_model=RulesStateOut)
def put_state(app: AppDep, body: RulesStateIn) -> dict:
    """Turn the offer to make a rule on or off; ``clear_declined`` forgets the word
    sets that were turned down."""
    state = rules_state.load_state(app.app_paths.data_dir)
    if body.offer is not None:
        state.offer = body.offer
    if body.clear_declined:
        state.declined = []
    rules_state.save_state(app.app_paths.data_dir, state)
    return _state_out(app, state)


@router.post("/state/decline", response_model=RulesStateOut)
def decline(app: AppDep, body: RulesDeclineIn) -> dict:
    """Remember a set of words the user turned down (not offered again)."""
    words = sorted({w.strip().lower() for w in body.words if w.strip()})
    state = rules_state.load_state(app.app_paths.data_dir)
    if words and words not in state.declined:
        state.declined.append(words)
        rules_state.save_state(app.app_paths.data_dir, state)
    return _state_out(app, state)


@router.put("/{rule_id}", response_model=RulesOut)
def save_rule(app: AppDep, rule_id: str, body: RuleIn, replaces: str | None = None) -> dict:
    """Save a rule: new ones go at the end of ``learned.yaml``; with ``replaces`` that
    rule is rewritten in place. ``rule_id`` is the rule's (new) id and must equal the
    body's; ``replaces`` is the id being replaced (the old one, for a rename). 400 for an
    invalid, repeated or reserved one."""
    if rule_id != body.id:
        raise InvalidRequest("the rule id in the address and in the body differ")
    if rule_id in _RESERVED:
        raise InvalidRequest(f"\u2018{rule_id}\u2019 is a reserved name")
    app.save_rule(_rule(body), replaces)
    return _out(app)


@router.delete("/{rule_id}", response_model=RulesOut)
def delete_rule(app: AppDep, rule_id: str) -> dict:
    app.delete_rule(rule_id)
    return _out(app)


@router.post("/{rule_id}/move", response_model=RulesOut)
def move_rule(app: AppDep, rule_id: str, body: RuleMoveIn) -> dict:
    """Move a learned rule up (negative) or down within ``learned.yaml``."""
    app.move_rule(rule_id, body.delta)
    return _out(app)
