"""Tray items: create (from Browse), edit, done/reopen, files; a file's links."""

from fastapi import APIRouter, Response

from dam.api.deps import AppDep, live_record
from dam.api.marks import collections_out
from dam.api.schemas import (
    DoneBody,
    DriveIdBody,
    FileLinksOut,
    ItemBarcodeOut,
    ItemCreateBody,
    ItemEventOut,
    ItemFileOut,
    ItemMoveBody,
    ItemOut,
    ItemPatchBody,
    QuickBody,
    QuickOut,
)
from dam.app import App
from dam.bills.barcode import item_barcode

router = APIRouter(prefix="/api", tags=["items"])


@router.post("/items", response_model=ItemOut)
def create_item(app: AppDep, body: ItemCreateBody):
    for drive_id in body.drive_ids:
        live_record(app, drive_id)
    return app.trays.create(body.tray, body.drive_ids, body.fields, body.title)


@router.post("/items/quick", response_model=QuickOut)
def quick(app: AppDep, body: QuickBody):
    """ "Put in <tray>": an item per file with its scan prefill; files that already have
    an open item in that tray are skipped, and a file with an open item in another tray
    gets that item moved here. DB only: the files stay where they are."""
    for drive_id in body.drive_ids:
        live_record(app, drive_id)
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
    return file_rows(app, item.files, app.today.file_info(item), marks)


def file_rows(
    app: App, drive_ids: list[str], info: list, marks: dict[str, list[str]]
) -> list[dict]:
    """``ItemFileOut`` rows for an item's files and their ``file_info``; ``marks``: a
    ``marks_for`` answer holding them (one query for the whole response)."""
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


@router.post("/items/{item_id}/files", response_model=ItemOut)
def add_file(app: AppDep, item_id: int, body: DriveIdBody):
    live_record(app, body.drive_id)
    return app.trays.add_file(item_id, body.drive_id)


@router.post("/items/{item_id}/files/remove", response_model=ItemOut)
def remove_file(app: AppDep, item_id: int, body: DriveIdBody):
    return app.trays.remove_file(item_id, body.drive_id)


@router.get("/files/{drive_id}/links", response_model=FileLinksOut)
def file_links(app: AppDep, drive_id: str) -> dict:
    """What the file belongs to (for badges): its open items, its collections, its note."""
    live_record(app, drive_id)
    return {
        "items": [i for i in app.trays.for_file(drive_id) if i.state == "open"],
        "collections": collections_out(app, app.collections.for_file(drive_id)),
        "note": app.notes.get("file", drive_id),
    }
