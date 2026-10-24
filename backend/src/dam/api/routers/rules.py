"""Filing rules: list them with their record, prove one against the past, save, delete,
reorder, explain a document, and the "offer a rule" setting."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from pydantic import ValidationError

from dam.api.deps import UI_ORIGIN, AppDep
from dam.api.schemas import (
    AreaPictureIn,
    AreaPictureOut,
    AreasForIn,
    AreasForOut,
    BatchResultOut,
    ReplayJobOut,
    ReplayOut,
    RuleExplainIn,
    RuleExplainOut,
    RuleIn,
    RuleMoveIn,
    RuleReplayIn,
    RuleReplayJobIn,
    RulesDeclineIn,
    RulesOut,
    RulesStateIn,
    RulesStateOut,
    UnusedPicturesIn,
    ZoneDraftIn,
    ZoneDraftOut,
)
from dam.app import App
from dam.codes.model import format_validation
from dam.rules import state as rules_state
from dam.rules.jobs import ReplayJob
from dam.rules.learned import learned_ids, rule_file
from dam.rules.model import LEARNED_FILE, RESERVED_IDS, Rule
from dam.rules.picture import DEFAULT_MIN_SCORE
from dam.rules.replay import ReplayRun, StaleCursor, explain, folder_of, replay, without_folder
from dam.services.area_pictures import check_pictures_exist
from dam.services.errors import InvalidRequest, NotFound
from dam.services.rule_record import RuleStats

router = APIRouter(prefix="/api/rules", tags=["rules"])

_NO_STATS = RuleStats(suggested=0, changed=0, last_used=None, flagged=False)


def _state_out(app: App, state: rules_state.RulesState | None = None) -> dict:
    state = state or rules_state.load_state(app.app_paths.data_dir)
    return {"offer": state.offer, "declined": len(state.declined)}


def _out(app: App) -> dict:
    stats = app.rule_record.stats()
    samples = app.rule_record.last_documents()
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
                "person_zone": list(r.person_zone) if r.person_zone else None,
                "sender": r.sender,
                "stats": asdict(stats.get(r.id, _NO_STATS)),
                "sample": asdict(samples[r.id]) if r.id in samples else None,
            }
        )
    return {
        "rules": rules,
        "errors": [asdict(e) for e in app.rule_errors],
        "state": _state_out(app),
        "unused_pictures": app.area_pictures.unused(app.rules),
        "default_min_score": DEFAULT_MIN_SCORE,
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
    rule, order = _placed(app, body)
    near = app.repo.get(body.near_drive_id) if body.near_drive_id else None
    try:
        result = replay(
            app.engine,
            rule,
            order,
            app.settings.special_folders,
            inbox_code_of=app.repo.inbox_code_of,
            layouts_for=app.repo.layouts_for,
            want_layouts=app.content.want_layouts,
            layout_blocked=app.content.layout_blocked,
            people=app.settings.people,
            address_zone=app.settings.address_zone,
            assigned_persons=app.assignments.persons,
            sender_ids=app.assignments.with_sender,
            pictures=app.pictures,
            after=body.after,
            near_folder=folder_of(near.path) if near is not None else None,
        )
    except StaleCursor as e:
        raise InvalidRequest(str(e)) from e
    if result.reading:
        app.wake_indexer()  # the layout pass reads what the rule needs next
    return _replay_out(result)


def _placed(app: App, body: RuleReplayIn) -> tuple[Rule, list[Rule]]:
    """The rule of a replay request and the load order with it in its place."""
    rule = _rule(body.rule)
    order = list(app.rules)
    if body.replaces is not None:
        at = next((i for i, r in enumerate(order) if r.id == body.replaces), None)
        if at is None:
            raise NotFound(body.replaces)
        order[at] = rule
    else:
        learned = learned_ids(app.rules_dir)
        above = next((i for i, r in enumerate(order) if r.id == body.place_above), None)
        if above is not None and body.place_above in learned:
            order.insert(above, rule)
        else:
            last = max((i for i, r in enumerate(order) if r.id in learned), default=-1)
            order.insert(last + 1, rule)
    return rule, order


def _replay_out(result) -> dict:
    out = asdict(result)
    out["shadowed"] = [{"drive_id": d, "rule_id": r} for d, r in result.shadowed]
    return out


def _job_out(view, since: int | None = None) -> dict:
    out = {
        "job_id": view.job_id,
        "sheet": view.sheet,
        "state": view.state,
        "version": view.version,
        "looked_at": view.looked_at,
        "total": view.total,
        "waiting": view.waiting,
        "elapsed_s": view.elapsed_s,
        "error": view.error,
        "result": None,
    }
    if view.result is not None and since != view.version:
        out["result"] = _replay_out(view.result)
    return out


def _job(app: App, job_id: str) -> ReplayJob:
    job = app.replay_jobs.get(job_id)
    if job is None:
        raise NotFound(job_id)
    return job


@router.post("/replay/jobs", response_model=ReplayJobOut)
def start_replay_job(app: AppDep, body: RuleReplayJobIn) -> dict:
    """Test a rule against the filed documents in the background: the answer comes at once
    and the test goes on, looking at the likely documents first. Poll it with
    ``GET /api/rules/replay/jobs/{job_id}`` for the result so far, stop it, or drop it when
    the sheet closes. One test per ``sheet`` (an earlier one for it is ended). Read-only.
    404 for an unknown ``replaces``, 400 for an invalid rule."""
    rule, order = _placed(
        app,
        RuleReplayIn(
            rule=body.rule,
            replaces=body.replaces,
            place_above=body.place_above,
        ),
    )
    near = app.repo.get(body.near_drive_id) if body.near_drive_id else None
    near_folder = folder_of(near.path) if near is not None else None

    def want(ids) -> None:
        app.content.want_layouts(ids)
        app.wake_indexer()  # the layout pass reads what the rule needs next

    def make() -> ReplayRun:
        return ReplayRun(
            app.engine,
            rule,
            order,
            app.settings.special_folders,
            inbox_code_of=app.repo.inbox_code_of,
            layouts_for=app.repo.layouts_for,
            want_layouts=want,
            layout_blocked=app.content.layout_blocked,
            people=app.settings.people,
            address_zone=app.settings.address_zone,
            assigned_persons=app.assignments.persons,
            sender_ids=app.assignments.with_sender,
            pictures=app.pictures,
            near_folder=near_folder,
        )

    job = app.replay_jobs.start(body.sheet, make)
    return _job_out(job.view(with_result=False))


@router.get("/replay/jobs/{job_id}", response_model=ReplayJobOut)
def get_replay_job(
    app: AppDep, job_id: str, since: Annotated[int | None, Query(ge=0)] = None
) -> dict:
    """The state of a background test and what it has found so far. Pass the ``version`` you
    already have as ``since`` and ``result`` is null while nothing is new. 404 for a job
    that is gone (dropped, or pushed out by newer ones)."""
    return _job_out(_job(app, job_id).view(), since)


@router.post("/replay/jobs/{job_id}/stop", response_model=ReplayJobOut)
def stop_replay_job(app: AppDep, job_id: str) -> dict:
    """End a background test where it is; what it has found so far stays. Idempotent."""
    job = _job(app, job_id)
    job.stop()
    job.join(1.0)
    return _job_out(job.view())


@router.delete("/replay/jobs/{job_id}", response_model=ReplayJobOut)
def drop_replay_job(app: AppDep, job_id: str) -> dict:
    """End a background test and forget it (its sheet was closed). 404 if it is gone."""
    job = _job(app, job_id)
    view = job.view()
    app.replay_jobs.drop(job_id)
    return _job_out(view)


@router.post("/unused-pictures/quarantine", response_model=BatchResultOut)
def quarantine_unused_pictures(app: AppDep, body: UnusedPicturesIn):
    """Move picture files no loaded rule uses from ``config/rules/areas`` into the
    quarantine folder (``dam rule picture <name>``): ``dry_run`` shows the plan, otherwise
    the move is journaled and the batch can be undone. 400 when a name is used by a rule,
    is not there, or is a link; 409 when it fails. On two disks the picture is copied and
    verified before dam's own copy is removed."""
    return app.area_pictures.quarantine_unused(
        body.names, lambda: app.rules, origin=UI_ORIGIN, dry_run=body.dry_run
    )


@router.post("/draft-zone", response_model=ZoneDraftOut)
def draft_zone(app: AppDep, body: ZoneDraftIn) -> dict:
    """The rule the boxes drawn on page 1 start from (see ``ZoneDraftOut``). 400 when
    page 1 is not read yet, a box is empty or holds no usable word; 404 for an unknown
    document. Changes nothing."""
    return asdict(app.inbox.draft_zone(body.drive_id, body.boxes, body.sender, body.picture_boxes))


@router.post("/area-picture", response_model=AreaPictureOut)
def area_picture(app: AppDep, body: AreaPictureIn) -> dict:
    """The picture of a box drawn on page 1, cut from the document's page-1 picture (in the
    cache: the archive is not read), to show before it is kept. With ``save`` and a
    ``rule_id`` it is also saved as ``areas/<rule-id>-<n>.png`` next to the rules and
    ``image`` names it. 400 when the box is bad or the picture is not made yet (it is queued),
    404 for an unknown document."""
    crop = app.area_pictures.crop(body.drive_id, body.box)
    out = app.area_pictures.preview(crop)
    if body.save:
        if not body.rule_id:
            raise InvalidRequest("A saved picture needs the id of its rule.")
        out["image"] = app.area_pictures.save(body.rule_id, crop)
    return out


@router.get("/areas/{name}", response_class=FileResponse)
def area_file(app: AppDep, name: str) -> FileResponse:
    """A saved picture of a picture area (a file in ``config/rules/areas``)."""
    return FileResponse(app.area_pictures.file(name), media_type="image/png")


@router.post("/explain", response_model=list[RuleExplainOut])
def explain_document(app: AppDep, body: RuleExplainIn) -> list:
    """For one document: which rules match, why (not), and what each one wins."""
    rec, text, alias = app.inbox.rule_context(body.drive_id)
    layout = app.repo.layout_for(rec.drive_id)
    people = app.inbox.people_context(rec.drive_id)
    found = explain(
        rec, text, app.rules, app.settings.special_folders, alias, layout, people, app.pictures
    )
    return [asdict(x) for x in found]


@router.post("/areas-for", response_model=AreasForOut)
def areas_for(app: AppDep, body: AreasForIn) -> dict:
    """The areas of the rule being tested on one document (a document of the test result),
    to draw them on its page 1: matched lines, the best place and score of a picture area.
    The rule's folder condition is left out, as in the test. Reads only the index and the
    cache; changes nothing."""
    rule = without_folder(_rule(body.rule))
    rec, text, alias = app.inbox.rule_context(body.drive_id)
    layout = app.repo.layout_for(rec.drive_id)
    people = app.inbox.people_context(rec.drive_id)
    (found,) = explain(
        rec, text, [rule], app.settings.special_folders, alias, layout, people, app.pictures
    )
    return {"areas": [asdict(a) for a in found.areas]}


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
def save_rule(
    app: AppDep,
    rule_id: str,
    body: RuleIn,
    replaces: str | None = None,
    place_above: str | None = None,
) -> dict:
    """Save a rule: new ones go at the end of ``learned.yaml``, or directly above the
    learned rule ``place_above`` (ignored when it is not in ``learned.yaml``); with
    ``replaces`` that rule is rewritten in place. ``rule_id`` is the rule's (new) id and
    must equal the body's; ``replaces`` is the id being replaced (the old one, for a
    rename). 400 for an invalid, repeated or reserved one."""
    if rule_id != body.id:
        raise InvalidRequest("the rule id in the address and in the body differ")
    if rule_id in RESERVED_IDS:
        raise InvalidRequest(f"\u2018{rule_id}\u2019 is a reserved name")
    rule = _rule(body)
    check_pictures_exist(app.rules_dir, rule)
    app.save_rule(rule, replaces, place_above)
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
