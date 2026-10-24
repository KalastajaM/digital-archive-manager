"""From (sender) and For (person) of documents, set by the owner."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Query

from dam.api.deps import AppDep
from dam.api.schemas import AssignmentOut, AssignmentsIn, SenderOut
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
    nothing is written then. Answers the documents' assignments (a cleared one is absent)."""
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
