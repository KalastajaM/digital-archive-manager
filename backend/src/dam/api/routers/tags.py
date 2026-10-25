"""Tags: the ones in use for the tag field's suggestions, the Tags screen's list and
changes (create, rename, merge, delete, pins, groups, each with an undo record) and the
sidebar's tags."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from dam.api.deps import AppDep
from dam.api.schemas import (
    SidebarTagOut,
    TagChangeOut,
    TagCountOut,
    TagGroupCreatedOut,
    TagGroupDeletedOut,
    TagGroupNameIn,
    TagGroupOut,
    TagGroupRestoreIn,
    TagGroupSetIn,
    TagListOut,
    TagMergeIn,
    TagMergePlanOut,
    TagNameIn,
    TagPinIn,
    TagRenameIn,
    TagUndoModel,
)
from dam.tags import SIDEBAR_TAGS, TagError, TagSnapshot, TagUndo, Unlink

router = APIRouter(prefix="/api/tags", tags=["tags"])

_STATUS = {"exists": 409, "missing": 404, "invalid": 422}


def _guard(call):
    try:
        return call()
    except TagError as e:
        raise HTTPException(_STATUS[e.kind], str(e)) from e


def _undo_out(undo: TagUndo) -> dict:
    return asdict(undo)


def _undo_in(body: TagUndoModel) -> TagUndo:
    return TagUndo(
        drop=list(body.drop),
        detach=[Unlink(u.name, list(u.drive_ids)) for u in body.detach],
        restore=[
            TagSnapshot(s.name, s.pinned_at, s.group_id, s.last_used_at, list(s.drive_ids))
            for s in body.restore
        ],
    )


def _files(n: int) -> str:
    return "1 file" if n == 1 else f"{n} files"


@router.get("", response_model=list[TagCountOut])
def list_tags(
    app: AppDep,
    prefix: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=50)] = 8,
) -> list[dict]:
    """Tags that start with ``prefix`` (case and accents ignored; all when empty), most
    used first, then by name, at most ``limit``."""
    return [{"name": name, "files": n} for name, n in app.tags.popular(prefix, limit)]


@router.get("/all", response_model=TagListOut)
def all_tags(app: AppDep, query: Annotated[str, Query(max_length=200)] = "") -> dict:
    """Every tag (also the ones no file has yet) with its file count, pin and group, and
    the groups; ``query`` keeps tags whose name contains it."""
    return app.tag_admin.listing(query)


@router.get("/sidebar", response_model=list[SidebarTagOut])
def sidebar_tags(app: AppDep) -> list[dict]:
    """The sidebar's tags: pinned first, then the most recently used, eight at most."""
    return app.tag_admin.sidebar(SIDEBAR_TAGS)


@router.post("", response_model=TagChangeOut)
def create_tag(app: AppDep, body: TagNameIn) -> dict:
    undo = _guard(lambda: app.tag_admin.create(body.name))
    return {"message": f"Created '{undo.drop[0]}'", "undo": _undo_out(undo)}


@router.post("/rename", response_model=TagChangeOut)
def rename_tag(app: AppDep, body: TagRenameIn) -> dict:
    """Rename a tag on every file. A name another tag has is refused (409): merge instead."""
    undo = _guard(lambda: app.tag_admin.rename_tag(body.name, body.new_name))
    return {
        "message": f"Renamed '{body.name}' to '{body.new_name.strip()}'",
        "undo": _undo_out(undo),
    }


@router.post("/merge", response_model=TagMergePlanOut)
def merge_tags(app: AppDep, body: TagMergeIn) -> dict:
    """Put ``into`` on the files of ``sources`` and remove the sources. ``dry_run``: say
    what would happen only."""
    plan = _guard(lambda: app.tag_admin.merge(body.sources, body.into, dry_run=body.dry_run))
    gone = ", ".join(f"'{s}'" for s in plan.removes)
    verb = "is" if len(plan.removes) == 1 else "are"
    return {
        "into": plan.into,
        "gains": plan.gains,
        "removes": plan.removes,
        "message": f"{_files(plan.gains)} {'gets' if plan.gains == 1 else 'get'} "
        f"'{plan.into}'; {gone} {verb} removed",
        "undo": _undo_out(plan.undo) if plan.undo else None,
    }


@router.post("/delete", response_model=TagChangeOut)
def delete_tag(app: AppDep, body: TagNameIn) -> dict:
    """Remove the tag from all its files and delete it."""
    undo = _guard(lambda: app.tag_admin.delete(body.name))
    n = len(undo.restore[0].drive_ids)
    return {"message": f"Deleted '{body.name}' (on {_files(n)})", "undo": _undo_out(undo)}


@router.post("/pin", response_model=TagChangeOut)
def pin_tags(app: AppDep, body: TagPinIn) -> dict:
    undo = _guard(lambda: app.tag_admin.pin(body.names, body.pinned))
    what = ", ".join(f"'{n}'" for n in body.names)
    return {"message": f"{'Pinned' if body.pinned else 'Unpinned'} {what}", "undo": _undo_out(undo)}


@router.post("/group", response_model=TagChangeOut)
def group_tags(app: AppDep, body: TagGroupSetIn) -> dict:
    """Move tags into a group, or out of any group (``group_id`` null)."""
    undo = _guard(lambda: app.tag_admin.set_group(body.names, body.group_id))
    what = ", ".join(f"'{n}'" for n in body.names)
    return {"message": f"Moved {what}", "undo": _undo_out(undo)}


@router.post("/undo", response_model=TagChangeOut)
def undo_change(app: AppDep, body: TagUndoModel) -> dict:
    """Put a tag change back, with the ``undo`` record the change returned."""
    undo = _undo_in(body)
    _guard(lambda: app.tag_admin.undo(undo))
    return {"message": "Undone", "undo": _undo_out(TagUndo())}


@router.post("/groups", response_model=TagGroupCreatedOut)
def create_group(app: AppDep, body: TagGroupNameIn) -> dict:
    group_id, _ = _guard(lambda: app.tag_admin.create_group(body.name))
    return {"id": group_id, "name": " ".join(body.name.split())}


@router.post("/groups/restore", response_model=TagGroupCreatedOut)
def restore_group(app: AppDep, body: TagGroupRestoreIn) -> dict:
    """Bring back a deleted group with its tags (Undo of a group delete)."""
    group_id = _guard(lambda: app.tag_admin.restore_group(body.name, body.members))
    return {"id": group_id, "name": " ".join(body.name.split())}


@router.post("/groups/{group_id}/rename", response_model=TagGroupOut)
def rename_group(app: AppDep, group_id: int, body: TagGroupNameIn) -> dict:
    _guard(lambda: app.tag_admin.rename_group(group_id, body.name))
    return {"id": group_id, "name": " ".join(body.name.split())}


@router.post("/groups/{group_id}/delete", response_model=TagGroupDeletedOut)
def delete_group(app: AppDep, group_id: int) -> dict:
    """Delete a group; its tags stay, ungrouped."""
    name, members = _guard(lambda: app.tag_admin.delete_group(group_id))
    return {"name": name, "members": members, "message": f"Deleted the group '{name}'"}
