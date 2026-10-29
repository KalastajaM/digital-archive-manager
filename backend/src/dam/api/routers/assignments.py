"""From (sender) and For (person) of documents, set by the owner."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Query

from dam.api.deps import AppDep, require_editable
from dam.api.schemas import (
    AssignmentOut,
    AssignmentsIn,
    IdentifierNameDoneOut,
    IdentifierNameIn,
    IdentifierNamesOut,
    SenderOut,
)
from dam.services.assignments import UNSET

router = APIRouter(prefix="/api", tags=["assignments"])

MAX_QUERY_IDS = 500


@router.get("/assignments", response_model=list[AssignmentOut])
def get_assignments(
    app: AppDep,
    drive_id: Annotated[list[str], Query(max_length=MAX_QUERY_IDS)] = [],  # noqa: B006
) -> list:
    """The assignments of these documents (one ``drive_id`` query parameter each);
    documents with none are left out."""
    return [asdict(a) for a in app.assignments.get(drive_id).values()]


@router.put("/assignments", response_model=list[AssignmentOut])
def put_assignments(app: AppDep, body: AssignmentsIn) -> list:
    """Set From and/or For on documents (the owner's word: it beats what page 1 says and
    is not overwritten by a filing). A field left out is unchanged, null clears it.
    400 for a blank sender or a person not in the people list, 404 for an unknown document;
    nothing is written then (also 400 for a file marked for deletion). Answers the documents'
    assignments (a cleared one is absent)."""
    require_editable(app, body.drive_ids)
    given = body.model_fields_set
    done = app.assignments.set(
        body.drive_ids,
        sender=body.sender if "sender" in given else UNSET,
        person=body.person if "person" in given else UNSET,
    )
    return [asdict(a) for a in done]


@router.get("/senders", response_model=list[SenderOut])
def senders(app: AppDep) -> list:
    """The senders in use, by name, with the number of documents each has."""
    return [{"sender": name, "count": n} for name, n in app.assignments.senders()]


@router.get("/identifier-names", response_model=IdentifierNamesOut)
def identifier_names(app: AppDep) -> dict:
    """Settings, Senders: every business ID on two or more documents, and every named one,
    most documents first, with the name printed next to it most often."""
    return {"names": [asdict(r) for r in app.sender_names.list()]}


@router.put("/identifier-names", response_model=IdentifierNameDoneOut)
def put_identifier_name(app: AppDep, body: IdentifierNameIn) -> dict:
    """Name a business ID: From becomes the name on every document that carries it, except
    where the owner set From or For. ``null`` clears the name and takes those senders
    back. Answers how many documents changed and the name as kept (spelled as another
    name already is). 400 for a blank name, or a kind or value that cannot be named."""
    if body.name is None:
        changed = app.sender_names.clear(body.kind, body.value)
    else:
        changed = app.sender_names.confirm(body.kind, body.value, body.name)
    return {"changed": changed, "name": app.sender_names.name_of(body.kind, body.value)}
