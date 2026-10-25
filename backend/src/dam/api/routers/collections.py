"""Collections: list, create, rename, members; close/reopen/publish with a preview first.

Previews (``.../preview``) plan what the Ongoing sync would do as if the change were
made, and change nothing. The apply routes make the change (DB), then run the sync and
return its result with the collection as it is afterwards.

The member routes (add/remove) do the same without a preview route: the sync they
trigger only adds or removes links the app owns inside ``##. Ongoing``, the batch is
journaled, and the opposite member action reverses it (as filing into a collection from
the Inbox does). Their answer carries the batch that ran, so the UI shows it.

Parents (``PATCH .../parent``) answer the same way, also without a preview route.

Groups and summaries (``.../groups``, ``.../members/group``, ``.../summary`` and the
``/api/collection-groups/{gid}`` routes in ``groups_router``) answer the same way: they
change the DB, then run the sync (groups do not change what is published yet).
"""

from dataclasses import asdict
from datetime import date
from typing import Literal

from fastapi import APIRouter

from dam.api.deps import AppDep, require_editable
from dam.api.marks import collection_out, collections_out
from dam.api.schemas import (
    CollectionChangeOut,
    CollectionCreateBody,
    CollectionMoveBody,
    CollectionOut,
    CollectionRowOut,
    DriveIdBody,
    DriveIdsBody,
    GroupCreateBody,
    GroupPatchBody,
    MemberAttentionOut,
    MemberGroupBody,
    NameBody,
    ParentBody,
    PublishBody,
    ResolvedOpOut,
    SummaryBody,
)
from dam.app import App
from dam.collections.ongoing import PUBLISHER_ID as ONGOING
from dam.collections.publishers import Publisher
from dam.collections.service import KEEP, check_collection_name

router = APIRouter(prefix="/api/collections", tags=["collections"])
groups_router = APIRouter(prefix="/api/collection-groups", tags=["collections"])

SYNC_FAILED = "Ongoing could not be updated (details are in the log). The next scan will try again."


def _ongoing(app: App) -> Publisher:
    """The Ongoing publisher, looked up in the registry by its id."""
    return app.publishers.get(ONGOING)


def file_phrase(app: App, drive_ids: list[str]) -> str:
    """ "Report.pdf" for one file, "3 files" for several (for an Activity title)."""
    ids = list(dict.fromkeys(drive_ids))
    if len(ids) == 1:
        record = app.repo.get(ids[0])
        return record.name if record is not None and record.name else "1 file"
    return f"{len(ids)} files"


def _name(app: App, collection_id: int) -> str:
    return app.collections.get(collection_id).name


def _synced(app: App, collection_id: int, label: str | None = None) -> dict:
    """Run the Ongoing sync after a change and report it with the collection.
    ``label``: what the user did, which titles the batch the sync journals."""
    result = app.collections.changed(label)
    c = app.collections.get(collection_id)
    if result is None:
        batch, problems = None, [SYNC_FAILED]
    else:
        batch = asdict(result.batch) if result.batch is not None else None
        problems = list(result.problems)
    return {
        "collection": collection_out(app, c),
        "batch": batch,
        "problems": problems,
        "ongoing_status": c.ongoing_status,
    }


@router.get("", response_model=list[CollectionRowOut])
def list_collections(
    app: AppDep, state: Literal["open", "closed", "all"] = "open", builtin: bool = False
) -> list:
    """The collections in tree order; the built-in ★ Ongoing and ! Important only with
    ``builtin`` (the Browse collection filter shows them; the pickers do not)."""
    cols = app.collections.list(None if state == "all" else state, include_builtin=builtin)
    extra = []
    for c in cols:
        files, open_checks = app.today.collection_counts(c.id)
        extra.append({"files": files, "open_checks": open_checks})
    return collections_out(app, cols, extra)


@router.post("", response_model=CollectionOut)
def create(app: AppDep, body: CollectionCreateBody):
    c = app.collections.create(body.name, body.parent_id, notify=False)
    app.collections.changed(f"Created collection {c.name}")
    return collection_out(app, app.collections.get(c.id))


@router.get("/{collection_id}", response_model=CollectionOut)
def get(app: AppDep, collection_id: int):
    return collection_out(app, app.collections.get(collection_id))


@router.get("/{collection_id}/attention", response_model=list[MemberAttentionOut])
def attention(app: AppDep, collection_id: int) -> list:
    """The "Needs attention" strip: per file member (in member order), its open tray
    items and whether it is still in the inbox. Database only: one query for the
    members, one for the items that hold any of them; members with neither are left
    out."""
    c = app.collections.get(collection_id)
    day = date.today()
    files = [m for m in c.members if not m.is_dir]
    by_file: dict[str, list[dict]] = {m.drive_id: [] for m in files}
    for item in app.trays.open_for_files(by_file):
        for drive_id in dict.fromkeys(item.files):
            if drive_id in by_file:
                by_file[drive_id].append({"item": item, "level": app.today.level(item, day)})
    out = []
    for m in files:
        in_inbox = (
            m.path is not None
            and not m.missing
            and not m.quarantined
            and app.repo.in_inbox_path(m.path)
        )
        if in_inbox or by_file[m.drive_id]:
            out.append({"drive_id": m.drive_id, "in_inbox": in_inbox, "items": by_file[m.drive_id]})
    return out


@router.post("/{collection_id}/rename/preview", response_model=list[ResolvedOpOut])
def rename_preview(app: AppDep, collection_id: int, body: NameBody) -> list:
    """Refuses what the rename refuses: a built-in collection, a reserved name."""
    app.collections.check_ordinary(collection_id, "renamed")
    return _ongoing(app).preview_for([collection_id], name=check_collection_name(body.name))


@router.patch("/{collection_id}", response_model=CollectionChangeOut)
def rename(app: AppDep, collection_id: int, body: NameBody) -> dict:
    old = _name(app, collection_id)
    c = app.collections.set_name(collection_id, body.name, notify=False)
    return _synced(app, collection_id, f"Renamed collection {old} to {c.name}")


@router.patch("/{collection_id}/parent", response_model=CollectionChangeOut)
def set_parent(app: AppDep, collection_id: int, body: ParentBody) -> dict:
    """Move the collection inside another (null: to the top). No preview, as for
    members and groups: the sync only moves app-owned entries (journaled), and moving
    it back reverses it. A cycle or a closed parent is refused."""
    c = app.collections.set_parent(collection_id, body.parent_id, notify=False)
    where = f"into {_name(app, body.parent_id)}" if body.parent_id is not None else "to the top"
    return _synced(app, collection_id, f"Moved collection {c.name} {where}")


@router.post("/{collection_id}/move", response_model=CollectionChangeOut)
def move(app: AppDep, collection_id: int, body: CollectionMoveBody) -> dict:
    """Put the collection before or after another (the built-in ★ and ! stay first and
    cannot move or be moved beside). With a sibling only the order changes: no preview,
    no batch and no sync. With a collection of another parent it goes into that parent
    too, as ``PATCH .../parent`` does (cycle 400, closed parent 409, Ongoing sync)."""
    old = app.collections.get(collection_id)
    c = app.collections.move(
        collection_id, before_id=body.before_id, after_id=body.after_id, notify=False
    )
    if c.parent_id != old.parent_id:
        where = f"into {_name(app, c.parent_id)}" if c.parent_id is not None else "to the top"
        return _synced(app, collection_id, f"Moved collection {c.name} {where}")
    return {
        "collection": collection_out(app, c),
        "batch": None,
        "problems": [],
        "ongoing_status": c.ongoing_status,
    }


@router.post("/{collection_id}/members", response_model=CollectionChangeOut)
def add_members(app: AppDep, collection_id: int, body: DriveIdsBody) -> dict:
    """No preview: the sync only links the new members in (app-owned links, journaled;
    removing the member again reverses it). The batch that ran is returned. 400 for a
    file marked for deletion (restore it first)."""
    require_editable(app, body.drive_ids)
    what = file_phrase(app, body.drive_ids)
    c = app.collections.add_members(collection_id, body.drive_ids, notify=False)
    return _synced(app, collection_id, f"Added {what} to {c.name}")


@router.post("/{collection_id}/members/remove", response_model=CollectionChangeOut)
def remove_member(app: AppDep, collection_id: int, body: DriveIdBody) -> dict:
    """No preview: the sync only removes this member's app-owned links (journaled;
    adding the member again reverses it). The batch that ran is returned."""
    what = file_phrase(app, [body.drive_id])
    c = app.collections.remove_member(collection_id, body.drive_id, notify=False)
    return _synced(app, collection_id, f"Removed {what} from {c.name}")


@router.post("/{collection_id}/close/preview", response_model=list[ResolvedOpOut])
def close_preview(app: AppDep, collection_id: int) -> list:
    """409 (as ``close``) while the collection has open child collections."""
    app.collections.check_closable(collection_id)
    return _ongoing(app).preview_for([collection_id], state="closed")


@router.post("/{collection_id}/close", response_model=CollectionChangeOut)
def close(app: AppDep, collection_id: int) -> dict:
    c = app.collections.close(collection_id, notify=False)
    return _synced(app, collection_id, f"Closed collection {c.name}")


@router.post("/{collection_id}/reopen/preview", response_model=list[ResolvedOpOut])
def reopen_preview(app: AppDep, collection_id: int) -> list:
    """Refuses a built-in collection, as ``reopen`` does."""
    app.collections.check_ordinary(collection_id, "reopened")
    return _ongoing(app).preview_for([collection_id], state="open")


@router.post("/{collection_id}/reopen", response_model=CollectionChangeOut)
def reopen(app: AppDep, collection_id: int) -> dict:
    c = app.collections.reopen(collection_id, notify=False)
    return _synced(app, collection_id, f"Reopened collection {c.name}")


@router.post("/{collection_id}/publish/preview", response_model=list[ResolvedOpOut])
def publish_preview(app: AppDep, collection_id: int, body: PublishBody) -> list:
    """Refuses a built-in collection, as ``publish`` does."""
    app.collections.check_ordinary(collection_id, "published or unpublished")
    return _ongoing(app).preview_for([collection_id], publish=body.on)


@router.post("/{collection_id}/publish", response_model=CollectionChangeOut)
def publish(app: AppDep, collection_id: int, body: PublishBody) -> dict:
    c = app.collections.set_publish(collection_id, body.publisher, body.on, notify=False)
    verb = "Started publishing" if body.on else "Stopped publishing"
    return _synced(app, collection_id, f"{verb} collection {c.name}")


@router.patch("/{collection_id}/summary", response_model=CollectionChangeOut)
def set_summary(app: AppDep, collection_id: int, body: SummaryBody) -> dict:
    app.collections.set_summary(collection_id, body.summary, notify=False)
    return _synced(app, collection_id)


@router.post("/{collection_id}/groups", response_model=CollectionChangeOut)
def create_group(app: AppDep, collection_id: int, body: GroupCreateBody) -> dict:
    g = app.collections.create_group(collection_id, body.name, body.parent_id, notify=False)
    return _synced(app, collection_id, f"Created group {g.name} in {_name(app, collection_id)}")


@router.post("/{collection_id}/members/group", response_model=CollectionChangeOut)
def set_member_group(app: AppDep, collection_id: int, body: MemberGroupBody) -> dict:
    """Put files in a group (null: ungrouped), adding the ones not yet members."""
    what = file_phrase(app, body.drive_ids)
    app.collections.set_member_group(collection_id, body.drive_ids, body.group_id, notify=False)
    return _synced(
        app, collection_id, f"Moved {what} between groups in {_name(app, collection_id)}"
    )


@groups_router.patch("/{group_id}", response_model=CollectionChangeOut)
def update_group(app: AppDep, group_id: int, body: GroupPatchBody) -> dict:
    g = app.collections.update_group(
        group_id,
        name=body.name,
        parent_id=body.parent_id if "parent_id" in body.model_fields_set else KEEP,
        position=body.position,
        summary=body.summary,
        notify=False,
    )
    return _synced(app, g.collection_id)


@groups_router.post("/{group_id}/remove", response_model=CollectionChangeOut)
def remove_group(app: AppDep, group_id: int) -> dict:
    """Child groups and members move to the parent; no membership is removed."""
    collection_id = app.collections.group(group_id).collection_id
    app.collections.remove_group(group_id, notify=False)
    return _synced(app, collection_id)
