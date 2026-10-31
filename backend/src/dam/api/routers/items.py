"""Tray items: create (from Browse), edit, done/reopen, renew, files; a file's links."""

from dataclasses import asdict

from fastapi import APIRouter, Response

from dam.api.deps import UI_ORIGIN, AppDep, live_record, require_editable
from dam.api.marks import collections_out, place_rows
from dam.api.schemas import (
    DoneBody,
    DriveIdBody,
    FileLinksOut,
    ItemBarcodeOut,
    ItemCreateBody,
    ItemEventOut,
    ItemFileAddBody,
    ItemFileOut,
    ItemMergeBody,
    ItemMoveBody,
    ItemOut,
    ItemPatchBody,
    QuickBody,
    QuickOut,
    RenewalUndoBody,
    RenewBody,
    RenewCandidateOut,
    RenewOut,
    RenewPreviewOut,
)
from dam.app import App
from dam.bills.barcode import item_barcode
from dam.ops.guards import parent

router = APIRouter(prefix="/api", tags=["items"])


@router.post("/items", response_model=ItemOut)
def create_item(app: AppDep, body: ItemCreateBody):
    for drive_id in body.drive_ids:
        live_record(app, drive_id)
    require_editable(app, body.drive_ids)
    return app.trays.create(body.tray, body.drive_ids, body.fields, body.title)


@router.post("/items/quick", response_model=QuickOut)
def quick(app: AppDep, body: QuickBody):
    """ "Put in <tray>": an item per file with its scan prefill; files that already have
    an open item in that tray are skipped, and a file with an open item in another tray
    gets that item moved here. DB only: the files stay where they are."""
    for drive_id in body.drive_ids:
        live_record(app, drive_id)
    require_editable(app, body.drive_ids)
    result = app.trays.create_quick(body.tray, body.drive_ids, body.fields)
    return {
        "created": result.created,
        "skipped": result.skipped,
        "moved": result.moved,
        "moved_from": {str(k): v for k, v in result.moved_from.items()},
    }


@router.post("/items/{item_id}/move", response_model=ItemOut)
def move_item(app: AppDep, item_id: int, body: ItemMoveBody):
    """Move an open item to another tray (same item; 409 if its file is already there)."""
    return app.trays.move(item_id, body.tray)


@router.post("/items/{item_id}/undo-move", response_model=ItemOut)
def undo_move(app: AppDep, item_id: int):
    """Put a just-moved item back (409 once it was changed since)."""
    return app.trays.undo_move(item_id)


@router.post("/items/{item_id}/remove", status_code=204, response_class=Response)
def remove_item(app: AppDep, item_id: int) -> Response:
    """Remove an item from its tray, open or done (DB only: the files are not touched)."""
    app.trays.delete_item(item_id)
    return Response(status_code=204)


@router.post("/items/{item_id}/discard", status_code=204, response_class=Response)
def discard(app: AppDep, item_id: int) -> Response:
    """Take back an item nobody changed yet (DB only; 409 once it was changed)."""
    app.trays.discard(item_id)
    return Response(status_code=204)


@router.get("/items/{item_id}", response_model=ItemOut)
def get_item(app: AppDep, item_id: int):
    return app.trays.get(item_id)


@router.patch("/items/{item_id}", response_model=ItemOut)
def update_item(app: AppDep, item_id: int, body: ItemPatchBody):
    return app.trays.update(item_id, body.fields, body.title)


@router.get("/items/{item_id}/history", response_model=list[ItemEventOut])
def item_history(app: AppDep, item_id: int) -> list:
    return app.trays.history(item_id)


@router.get("/items/{item_id}/files", response_model=list[ItemFileOut])
def item_files(app: AppDep, item_id: int) -> list:
    """The item's files in order, with their path and state (for previews and badges)."""
    item = app.trays.get(item_id)
    marks = app.marks.marks_for(item.files)
    rows = file_rows(app, item.files, app.today.file_info(item), marks)
    place_rows(app, rows)
    return rows


def file_rows(
    app: App, drive_ids: list[str], info: list, marks: dict[str, list[str]]
) -> list[dict]:
    """``ItemFileOut`` rows for an item's files and their ``file_info``; ``marks``: a
    ``marks_for`` answer holding them (one query for the whole response). The caller
    sets ``folder`` / ``connected`` once over the whole response (``place_rows``)."""
    return [
        {
            "drive_id": drive_id,
            "path": rec.path if rec else None,
            "ext": rec.ext if rec else None,
            "state": state,
            "in_inbox": rec is not None and state == "ok" and app.repo.in_inbox(rec),
            "marks": marks.get(drive_id, []),
        }
        for drive_id, (rec, state) in zip(drive_ids, info, strict=True)
    ]


@router.get("/items/{item_id}/barcode", response_model=ItemBarcodeOut)
def get_item_barcode(app: AppDep, item_id: int) -> dict:
    """The bank barcode built from the item's fields (or why there is none), and the one
    printed on its scans with the fields that disagree with it."""
    item = app.trays.get(item_id)
    printed = (app.repo.barcode_for(drive_id) for drive_id in item.files)
    return item_barcode(item.fields, item.invalid_fields, printed)


@router.post("/items/{item_id}/done", response_model=ItemOut)
def done(app: AppDep, item_id: int, body: DoneBody):
    return app.trays.done(item_id, body.fields)


@router.post("/items/{item_id}/reopen", response_model=ItemOut)
def reopen(app: AppDep, item_id: int):
    return app.trays.reopen(item_id)


def _new_file(app: App, body: RenewBody) -> None:
    if body.drive_id is not None:
        live_record(app, body.drive_id)
        require_editable(app, [body.drive_id])


@router.post("/items/{item_id}/renew/preview", response_model=RenewPreviewOut)
def renew_preview(app: AppDep, item_id: int, body: RenewBody) -> dict:
    """What Renewed… would do: the move of the old file into its folder's Expired
    subfolder, why it is skipped, or the old file when it is locked and this request
    carries no unlock for it (200 with ``locked`` set and no ops). Changes nothing."""
    _new_file(app, body)
    return asdict(app.renewals.preview(item_id, body.drive_id, origin=UI_ORIGIN))


@router.post("/items/{item_id}/renew", response_model=RenewOut)
def renew(app: AppDep, item_id: int, body: RenewBody) -> dict:
    """Renewed…: the new date and, with ``drive_id``, the new first file; the old file
    moves into Expired in the same batch (400 when it is locked without an unlock, or
    the move fails: then nothing is renewed)."""
    _new_file(app, body)
    done = app.renewals.apply(item_id, body.expires, body.drive_id, origin=UI_ORIGIN)
    return {
        "item": done.item,
        "batch_id": done.batch_id,
        "undo": done.undo,
        "skipped": done.skipped,
    }


@router.get("/renewals/open", response_model=list[RenewCandidateOut])
def renewal_candidates(app: AppDep) -> list[dict]:
    """The open items of trays with ``renew``, for the Inbox's "Renews …?": the first
    file of each item (``drive_id``, which the Inbox unlocks for the move), its folder
    and For, and whether that file is locked as stored (an unlock grant does not
    count). The Inbox matches them to the folder and person it files into."""
    renewable = {t.id for t in app.trays.defs() if t.renew is not None}
    out = []
    for item in app.trays.list():
        if item.tray_id not in renewable:
            continue
        first = item.files[0] if item.files else None
        rec = app.repo.get(first) if first else None
        live = rec is not None and not rec.missing and rec.parked_at is None
        out.append(
            {
                "item_id": item.id,
                "title": item.title,
                "drive_id": first,
                "expires": item.date,
                "kind": item.fields.get("kind"),
                "folder": parent(rec.path) if live else None,
                "person": app.assignments.person_of(first) if first else None,
                "locked": live and app.locks.reason(first, rec.path_nfc) is not None,
            }
        )
    return out


@router.post("/renewals/undo", response_model=ItemOut)
def undo_renewal(app: AppDep, body: RenewalUndoBody):
    """Undo a renewal that moved no file (``undo: "renewal"``): the item's old file,
    date and marks come back. 400 for one that moved a file (undo it in Activity), 409
    once undone."""
    item = app.renewals.undo(body.batch_id)
    app.collections.changed()
    return item


@router.post("/items/{item_id}/files", response_model=ItemOut)
def add_file(app: AppDep, item_id: int, body: ItemFileAddBody):
    """Attach a file (DB only); ``position`` puts it back where a removed one was."""
    live_record(app, body.drive_id)
    require_editable(app, [body.drive_id])
    return app.trays.add_file(item_id, body.drive_id, body.position)


@router.post("/items/{item_id}/files/remove", response_model=ItemOut)
def remove_file(app: AppDep, item_id: int, body: DriveIdBody):
    return app.trays.remove_file(item_id, body.drive_id)


@router.post("/items/{item_id}/merge", response_model=ItemOut)
def merge_item(app: AppDep, item_id: int, body: ItemMergeBody):
    """Merge the open item ``body.item_id`` into this open one (DB only): its files, note
    and checklist are added here and it is removed. 400 for itself or a done item, 404
    for an unknown id."""
    return app.trays.merge(item_id, body.item_id)


@router.post("/items/{item_id}/undo-merge", response_model=ItemOut)
def undo_merge(app: AppDep, item_id: int):
    """Bring the item last merged into this one back, as both were (409 once this item
    was changed since)."""
    return app.trays.undo_merge(item_id)


@router.get("/files/{drive_id}/links", response_model=FileLinksOut)
def file_links(app: AppDep, drive_id: str) -> dict:
    """What the file belongs to (for badges): its open items, its collections, its note."""
    live_record(app, drive_id)
    return {
        "items": [i for i in app.trays.for_file(drive_id) if i.state == "open"],
        "collections": collections_out(app, app.collections.for_file(drive_id)),
        "note": app.notes.get("file", drive_id),
    }
