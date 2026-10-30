"""One file: its record and tags, its raw bytes, PDF page previews, Quick Look
thumbnails, a text preview, and open/reveal in macOS."""

import asyncio
import mimetypes
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, FastAPI, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse

from dam import packs
from dam.address_areas import NONE
from dam.api import preview
from dam.api.deps import AppDep, live_record, require_editable
from dam.api.marks import with_record_marks
from dam.api.schemas import (
    AddressAreaIn,
    AddressAreaOut,
    ErrorBody,
    FileDetailOut,
    FileSuggestionsOut,
    FileSummaryIn,
    FileSummaryOut,
    FileTagsIn,
    FileTagsOut,
    IdentifiersOut,
    Page1BoxIn,
    Page1Out,
    RelativeMarkIn,
    RelativesDismissedOut,
    RelativesOut,
    ScanFieldsIn,
    ScanFieldsOut,
    TextPreviewOut,
)
from dam.app import App
from dam.errors import InvalidRequest, NotFound
from dam.extract.layout import check_box, lines_in_zone
from dam.index.repo import BARCODE_EXTS, FileRecord
from dam.services.inbox import normalise_tags
from dam.services.links import NO_LINK_PREVIEW, link_target
from dam.services.preview import (
    TEXT_MAX_BYTES,
    THUMB_DEFAULT_WIDTH,
    THUMB_MAX_WIDTH,
    THUMB_MIN_WIDTH,
)
from dam.services.relatives import MAX_RELATIVES

router = APIRouter(prefix="/api/files", tags=["files"])

# Served bytes may be HTML or SVG from the archive: never sniffed, never run as the app.
RAW_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "sandbox; default-src 'none'",
}


def shown_record(app: App, drive_id: str) -> FileRecord:
    """What a preview of ``drive_id`` shows: the file itself or, for a link, the file
    it stands for inside the archive (``services.links``); NotFound "no preview (link
    to outside the archive)" for a link without one. The preview checks then apply to
    that record (a regular file inside the archive, never a link or a folder)."""
    rec = live_record(app, drive_id)
    if not rec.is_link:
        return rec
    target = link_target(app.paths, app.repo, rec)
    if target is None:
        raise NotFound(NO_LINK_PREVIEW)
    return target


def _page1(app: App, drive_id: str, box: list[float] | None = None) -> dict:
    """Page 1's lines (those in ``box`` when given). A page that is not read yet is queued
    for the layout pass, and the answer says so."""
    rec = shown_record(app, drive_id)
    layout = app.repo.layout_for(rec.drive_id)
    if layout is None:
        why = None
        if (rec.ext or "").lower() in BARCODE_EXTS:
            app.content.want_layouts([rec.drive_id])
            app.wake_indexer()
            why = app.content.layout_blocked(rec.drive_id)
        else:
            why = "no page 1 to read in this kind of file"
        return {"read": False, "lines": [], "unavailable": why}
    lines = layout.lines if box is None else lines_in_zone(layout.lines, check_box(box))
    return {
        "read": True,
        "lines": [{"text": ln.text, "box": list(ln.box)} for ln in lines],
        "unavailable": None,
    }


@router.get("/{drive_id}/page1", response_model=Page1Out)
def page1(app: AppDep, drive_id: str) -> dict:
    """The text of page 1 with where each line sits (fractions of the page, origin top
    left). ``read`` is false while page 1 has not been read: a read is queued, ask again."""
    return _page1(app, drive_id)


@router.post("/{drive_id}/page1/lines", response_model=Page1Out)
def page1_lines(app: AppDep, drive_id: str, body: Page1BoxIn) -> dict:
    """The lines of page 1 that lie in a box (the rule that matching uses). Read only."""
    try:
        check_box(body.box)
    except ValueError as e:
        raise InvalidRequest(str(e)) from e
    return _page1(app, drive_id, body.box)


def _address_area(app: App, drive_id: str) -> dict:
    zone = app.address_areas.of(drive_id)
    if zone is None:
        return {"state": "general", "box": None}
    if zone == NONE:
        return {"state": "none", "box": None}
    return {"state": "document", "box": list(zone)}


@router.get("/{drive_id}/address-area", response_model=AddressAreaOut)
def address_area(app: AppDep, drive_id: str) -> dict:
    """Where people are looked for on this document: the general area, its own, or none."""
    live_record(app, drive_id)
    return _address_area(app, drive_id)


@router.put("/{drive_id}/address-area", response_model=AddressAreaOut)
def put_address_area(app: AppDep, drive_id: str, body: AddressAreaIn) -> dict:
    """Give this document its own address area, used instead of the archive's and a
    rule's; a null box: none, nobody is looked for on it. 400 for a box that is not one."""
    live_record(app, drive_id)
    if body.box is None:
        app.address_areas.set(drive_id, NONE)
    else:
        try:
            app.address_areas.set(drive_id, check_box(body.box))
        except ValueError as e:
            raise InvalidRequest(str(e)) from e
    return _address_area(app, drive_id)


@router.delete("/{drive_id}/address-area", response_model=AddressAreaOut)
def delete_address_area(app: AppDep, drive_id: str) -> dict:
    """The general address area applies to this document again."""
    live_record(app, drive_id)
    app.address_areas.clear(drive_id)
    return _address_area(app, drive_id)


@router.get("/{drive_id}", response_model=FileDetailOut)
def file_detail(app: AppDep, drive_id: str) -> dict:
    """The record and tags; for a link, the file it stands for (``link_target_id`` and
    ``link_target_inside``) or, when that is outside the archive or missing, where it
    points (``link_target_path`` only)."""
    rec = live_record(app, drive_id)
    target = link_target(app.paths, app.repo, rec) if rec.is_link else None
    if target is not None:
        target_path: str | None = target.path
    else:
        target_path = rec.link_target if rec.is_link else None
    detail = {
        "record": asdict(rec),
        "tags": app.tags.for_file(drive_id),
        "assignment": (
            asdict(a) if (a := app.assignments.get([drive_id]).get(drive_id)) is not None else None
        ),
        "link_target_id": target.drive_id if target else None,
        "link_target_path": target_path,
        "link_target_inside": target is not None,
    }
    return with_record_marks(app, [detail])[0]


@router.get("/{drive_id}/suggestions", response_model=FileSuggestionsOut)
def file_suggestions(app: AppDep, drive_id: str) -> dict:
    """What the rules and the scan suggest for the file, wherever it is (each field
    with its source). Nothing is applied: the UI offers each one as a chip."""
    rec = live_record(app, drive_id)
    found = app.inbox.suggestion(drive_id)
    renamed = found.name != rec.name
    return {
        "name": found.name if renamed else None,
        "name_source": found.name_source if renamed else None,
        "folder": found.folder,
        "folder_source": found.folder_source,
        "tags": found.tags,
        "tag_sources": found.tag_sources,
        "sources": found.sources,
        "person": found.person,
        "areas": [asdict(a) for a in found.areas],
        "person_line": asdict(found.person_line) if found.person_line else None,
    }


@router.put("/{drive_id}/tags", response_model=FileTagsOut)
def put_file_tags(app: AppDep, drive_id: str, body: FileTagsIn) -> dict:
    """Set the file's tags exactly (trimmed, empty and repeated ones dropped)."""
    live_record(app, drive_id)
    require_editable(app, [drive_id])
    app.tags.set_for_file(drive_id, normalise_tags(body.tags))
    return {"tags": app.tags.for_file(drive_id)}


@router.get("/{drive_id}/relatives", response_model=RelativesOut)
def file_relatives(
    app: AppDep, drive_id: str, limit: Annotated[int, Query(ge=1, le=MAX_RELATIVES)] = MAX_RELATIVES
) -> dict:
    """The files this one belongs with, best first, each with the links that make it a
    relative (same reference, sender, collection, tag, folder, IBAN or person), plus the
    values they share and how many pairs are marked "Not related". A link in the archive
    is answered as its target. 404 for an unknown, missing or parked file."""
    return asdict(app.relatives.of(drive_id, limit))


@router.get("/{drive_id}/relatives/dismissed", response_model=RelativesDismissedOut)
def file_relatives_dismissed(app: AppDep, drive_id: str) -> dict:
    """The files marked "Not related" to this one (that still exist)."""
    live_record(app, drive_id)
    return {"dismissed": [asdict(d) for d in app.relatives.dismissed(drive_id)]}


@router.post("/{drive_id}/relatives/dismiss", response_model=RelativesDismissedOut)
def dismiss_relative(app: AppDep, drive_id: str, body: RelativeMarkIn) -> dict:
    """Mark the two files "Not related": each is left out of the other's list. Answers
    the files now marked for this one."""
    live_record(app, drive_id)
    app.relatives.dismiss(drive_id, body.drive_id)
    return {"dismissed": [asdict(d) for d in app.relatives.dismissed(drive_id)]}


@router.post("/{drive_id}/relatives/restore", response_model=RelativesDismissedOut)
def restore_relative(app: AppDep, drive_id: str, body: RelativeMarkIn) -> dict:
    """Take the "Not related" mark off the pair again. Answers the files still marked."""
    live_record(app, drive_id)
    app.relatives.restore(drive_id, body.drive_id)
    return {"dismissed": [asdict(d) for d in app.relatives.dismissed(drive_id)]}


@router.get("/{drive_id}/summary", response_model=FileSummaryOut)
def file_summary(app: AppDep, drive_id: str) -> dict:
    """The file's AI and user summaries (each null if none), flagged when outdated."""
    live_record(app, drive_id)
    return app.summaries.get(drive_id)


@router.put(
    "/{drive_id}/summary", response_model=FileSummaryOut, responses={409: {"model": ErrorBody}}
)
def put_file_summary(app: AppDep, drive_id: str, body: FileSummaryIn) -> dict:
    """Save a summary ("Use this summary", or one the user typed). 409 when it would
    overwrite a current user summary without ``replace``."""
    live_record(app, drive_id)
    require_editable(app, [drive_id])
    return app.summaries.put(drive_id, body.source, body.summary, body.key_facts, body.replace)


@router.get("/{drive_id}/identifiers", response_model=IdentifiersOut)
def file_identifiers(app: AppDep, drive_id: str) -> dict:
    """Business IDs, IBANs and domains found in the file, with how many other files
    carry each; the enabled packs' only."""
    live_record(app, drive_id)
    core, *others = packs.active().countries
    order = [s for p in others for s in p.identifiers] + list(core.identifiers)
    rank = {s.kind: i for i, s in enumerate(order)}
    label = {s.kind: s.label for s in order}
    found = [(k, v) for k, v in app.repo.identifiers_for(drive_id) if k in rank]
    found.sort(key=lambda kv: rank[kv[0]])  # stable: in text order within a kind
    counts = app.repo.identifier_counts(found)  # this file is one of them
    profile = packs.active()
    business = set(packs.business_id_kinds(profile))
    return {
        "identifiers": [
            {
                "kind": kind,
                "label": label[kind],
                "value": value,
                "others": max(0, counts.get((kind, value), 1) - 1),
                "business": kind in business,
                "own": kind in business and value in profile.own_ids,
            }
            for kind, value in found
        ]
    }


@router.get("/{drive_id}/fields", response_model=ScanFieldsOut)
def file_fields(app: AppDep, drive_id: str) -> dict:
    """The file's scan fields: the saved list, else the detected one."""
    live_record(app, drive_id)
    return app.scan_fields.get(drive_id)


@router.put("/{drive_id}/fields", response_model=ScanFieldsOut)
def put_file_fields(app: AppDep, drive_id: str, body: ScanFieldsIn) -> dict:
    """Save the whole list; it replaces the detected one for this file."""
    live_record(app, drive_id)
    return app.scan_fields.put(drive_id, [f.model_dump() for f in body.fields])


@router.delete("/{drive_id}/fields", response_model=ScanFieldsOut)
def delete_file_fields(app: AppDep, drive_id: str) -> dict:
    """ "Reset to detected": forget the saved list and return the detected one."""
    live_record(app, drive_id)
    return app.scan_fields.delete(drive_id)


@router.get(
    "/{drive_id}/raw",
    response_class=FileResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
def raw(app: AppDep, drive_id: str) -> FileResponse:
    """The file's bytes (a link's: its target's inside the archive)."""
    rec = shown_record(app, drive_id)
    path = app.paths.abs(rec.path)
    if rec.is_dir or rec.is_link or path.is_symlink() or not path.is_file():
        raise NotFound(drive_id)
    media_type = mimetypes.guess_type(rec.name or "")[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        filename=rec.name,
        content_disposition_type="inline",
        headers=RAW_HEADERS,
    )


@router.get(
    "/{drive_id}/page/{n}.png",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def page_png(app: AppDep, drive_id: str, n: int, w: Annotated[int, Query()] = 900) -> Response:
    """Page ``n`` (1-based) of a PDF as PNG; 404 for other file types (use ``raw``).
    A link shows its target's pages."""
    rec = shown_record(app, drive_id)
    path = app.paths.abs(rec.path)
    if rec.is_dir or rec.is_link or rec.ext != "pdf" or path.is_symlink() or not path.is_file():
        raise NotFound(f"No page preview for {drive_id}")
    png = preview.cached_page(app.app_paths.cache_dir / "pages", rec, path, n, w)
    return Response(png, media_type="image/png", headers={"X-Content-Type-Options": "nosniff"})


THUMB_SLOTS = 2  # thumbnail requests rendering (or reading the cache) at once
THUMB_ACQUIRE_S = 2.0  # longest wait for a slot before answering 503 "busy"


def _thumb_gate(api: FastAPI) -> asyncio.Semaphore:
    """The API's thumbnail slots (one semaphore per API, made on its event loop)."""
    gate = getattr(api.state, "thumb_gate", None)
    if gate is None:
        gate = api.state.thumb_gate = asyncio.Semaphore(THUMB_SLOTS)
    return gate


@router.get(
    "/{drive_id}/thumb.png",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}, 503: {"model": ErrorBody}},
)
async def thumb_png(
    request: Request,
    app: AppDep,
    drive_id: str,
    width: Annotated[int, Query(ge=THUMB_MIN_WIDTH, le=THUMB_MAX_WIDTH)] = THUMB_DEFAULT_WIDTH,
) -> Response:
    """A Quick Look thumbnail of any file type (macOS); 404 "no preview" otherwise, 503
    "busy" when no render slot frees up within 2 s (the client offers a retry). A
    request whose client has gone (the selection moved on) is not rendered. A link
    shows its target's."""
    rec = await run_in_threadpool(shown_record, app, drive_id)
    gate = _thumb_gate(request.app)
    try:
        await asyncio.wait_for(gate.acquire(), THUMB_ACQUIRE_S)
    except TimeoutError:
        return JSONResponse({"error": "busy"}, status_code=503)
    try:
        if await request.is_disconnected():
            return Response(status_code=499)  # client closed the request; nobody reads this
        png = await run_in_threadpool(app.previews.thumbnail, rec, width)
    finally:
        gate.release()
    return Response(png, media_type="image/png", headers={"X-Content-Type-Options": "nosniff"})


@router.get("/{drive_id}/text", response_model=TextPreviewOut)
def text_preview(
    app: AppDep, drive_id: str, max: Annotated[int, Query(ge=1, le=TEXT_MAX_BYTES)] = TEXT_MAX_BYTES
) -> dict:
    """The first ``max`` bytes (at most 200 KB) of a text-like file, as UTF-8 (a
    link: its target's)."""
    text, truncated = app.previews.text(shown_record(app, drive_id), max)
    return {"text": text, "truncated": truncated}


_NOT_MACOS = {501: {"model": ErrorBody}}  # only these routes can answer 501


@router.post("/{drive_id}/open", status_code=204, response_class=Response, responses=_NOT_MACOS)
def open_file(app: AppDep, drive_id: str) -> Response:
    """Open the file in its default macOS app (501 elsewhere). A link opens its target
    inside the archive, with every refusal applied to the target; 409 without one."""
    rec = live_record(app, drive_id)
    if rec.is_link:
        app.launch.open_link(rec, link_target(app.paths, app.repo, rec))
    else:
        app.launch.open(rec)
    return Response(status_code=204)


@router.post("/{drive_id}/reveal", status_code=204, response_class=Response, responses=_NOT_MACOS)
def reveal_file(app: AppDep, drive_id: str) -> Response:
    """Show the file in a Finder window (501 elsewhere). A link shows its target inside
    the archive or, without one, the link itself."""
    rec = live_record(app, drive_id)
    if rec.is_link:
        app.launch.reveal_link(rec, link_target(app.paths, app.repo, rec))
    else:
        app.launch.reveal(rec)
    return Response(status_code=204)
