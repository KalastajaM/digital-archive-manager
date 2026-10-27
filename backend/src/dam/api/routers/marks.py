"""The ★ Ongoing and ! Important marks: one-click member changes on the two built-in
collections.

No preview and no confirm, as for every member change: the sync that follows only adds
or removes links the app owns, and the opposite action reverses it. The answer is the
built-in collection after the change and the sync that ran (``CollectionChangeOut``).
"""

from typing import Literal

from fastapi import APIRouter

from dam.api.deps import AppDep, require_editable
from dam.api.marks import collection_out
from dam.api.routers.collections import file_phrase, synced
from dam.api.schemas import CollectionChangeOut, CollectionOut, MarkBody
from dam.errors import InvalidRequest

router = APIRouter(prefix="/api/marks", tags=["marks"])


def _no_group(body: MarkBody) -> None:
    if body.group is not None and body.group.strip():
        raise InvalidRequest("Only Important has groups")


@router.get("/collection/{kind}", response_model=CollectionOut)
def builtin(app: AppDep, kind: Literal["starred", "important"]) -> dict:
    """The built-in ★ Ongoing (``starred``) or ! Important collection, with its members
    and groups: the Today Starred card and the Important page read it."""
    return collection_out(app, app.collections.builtin(kind))


@router.post("/star", response_model=CollectionChangeOut)
def star(app: AppDep, body: MarkBody) -> dict:
    _no_group(body)
    require_editable(app, body.drive_ids)
    what = file_phrase(app, body.drive_ids)
    c = app.marks.star(body.drive_ids, notify=False)
    return synced(app, c.id, f"Starred {what}")


@router.post("/unstar", response_model=CollectionChangeOut)
def unstar(app: AppDep, body: MarkBody) -> dict:
    _no_group(body)
    what = file_phrase(app, body.drive_ids)
    c = app.marks.unstar(body.drive_ids, notify=False)
    return synced(app, c.id, f"Removed the star from {what}")


@router.post("/important", response_model=CollectionChangeOut)
def important(app: AppDep, body: MarkBody) -> dict:
    """Mark as important, in the group at ``group`` ("Houses/Hillside", created as
    needed; a file already in another group moves there). Without ``group``, new ones
    are ungrouped and marked ones keep their group."""
    require_editable(app, body.drive_ids)
    what = file_phrase(app, body.drive_ids)
    c = app.marks.mark_important(body.drive_ids, body.group, notify=False)
    return synced(app, c.id, f"Marked {what} as important")


@router.post("/unimportant", response_model=CollectionChangeOut)
def unimportant(app: AppDep, body: MarkBody) -> dict:
    _no_group(body)
    what = file_phrase(app, body.drive_ids)
    c = app.marks.unmark_important(body.drive_ids, notify=False)
    return synced(app, c.id, f"Removed {what} from Important")
