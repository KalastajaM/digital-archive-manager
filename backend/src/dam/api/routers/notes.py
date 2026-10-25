"""Notes and checklists on files, collections and items."""

from typing import Literal

from fastapi import APIRouter, Response

from dam.api.deps import AppDep, check_target, require_editable
from dam.api.schemas import (
    CheckAddBody,
    ChecklistItemOut,
    CheckMoveBody,
    CheckPatchBody,
    NoteBody,
    NoteOut,
)

router = APIRouter(prefix="/api", tags=["notes"])


def check_writable(app, kind: str, target: str) -> None:
    """``check_target`` for a change: a file marked for deletion is read-only."""
    check_target(app, kind, target)
    if kind == "file":
        require_editable(app, [target])


Kind = Literal["file", "collection", "item"]
_NO_CONTENT = {"status_code": 204, "response_class": Response}


@router.get("/notes/{kind}/{target}", response_model=NoteOut)
def get_note(app: AppDep, kind: Kind, target: str) -> dict:
    check_target(app, kind, target)
    return {"text": app.notes.get(kind, target)}


@router.put("/notes/{kind}/{target}", response_model=NoteOut)
def set_note(app: AppDep, kind: Kind, target: str, body: NoteBody) -> dict:
    """Store the note (trimmed); blank text removes it."""
    check_writable(app, kind, target)
    app.notes.set(kind, target, body.text)
    return {"text": app.notes.get(kind, target)}


@router.post("/notes/{kind}/{target}/append", response_model=NoteOut)
def append_note(app: AppDep, kind: Kind, target: str, body: NoteBody) -> dict:
    """Add the text below the existing note (atomic: no read-modify-write in the client)."""
    check_writable(app, kind, target)
    return {"text": app.notes.append(kind, target, body.text)}


# The routes on one checklist entry come first: ``{check_id:int}`` only matches digits,
# so ``/checklist/file/<drive id>`` never reaches them.


@router.patch("/checklist/{check_id:int}", **_NO_CONTENT)
def set_check(app: AppDep, check_id: int, body: CheckPatchBody) -> None:
    app.notes.set_check(check_id, done=body.done, text=body.text)


@router.post("/checklist/{check_id:int}/remove", **_NO_CONTENT)
def remove_check(app: AppDep, check_id: int) -> None:
    app.notes.remove_check(check_id)


@router.post("/checklist/{check_id:int}/move", **_NO_CONTENT)
def move_check(app: AppDep, check_id: int, body: CheckMoveBody) -> None:
    """Move the entry to ``position`` (0-based, clamped); the others are renumbered."""
    app.notes.move_check(check_id, body.position)


@router.get("/checklist/{kind}/{target}", response_model=list[ChecklistItemOut])
def checklist(app: AppDep, kind: Kind, target: str) -> list:
    check_target(app, kind, target)
    return app.notes.checklist(kind, target)


@router.post("/checklist/{kind}/{target}", response_model=ChecklistItemOut)
def add_check(app: AppDep, kind: Kind, target: str, body: CheckAddBody):
    check_writable(app, kind, target)
    return app.notes.add_check(kind, target, body.text)
