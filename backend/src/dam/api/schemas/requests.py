"""The request models of the core screens: filing, moves, marks, tags and the like
(dam.api.schemas)."""

from datetime import date
from typing import Any, Literal

from pydantic import Field

from dam.api.schemas.base import StrictIn

# -- requests ---------------------------------------------------------------


class FileRequestIn(StrictIn):
    drive_id: str
    name: str
    folder: str
    tags: list[str] = []
    # optional follow-ups once the file is filed (see ``FileRequest``)
    tray: str | None = None
    tray_fields: dict[str, Any] = {}
    collections: list[str] = []
    note: str = ""
    # star it / mark it important once filed (a QR sticker's tick boxes); undone with
    # the batch
    star: bool = False
    important: bool = False
    # renew this open item of a tray with ``renew`` with the filed file, its new date
    # ``renew_expires`` (the old file moves into Expired in the same batch; no tray step)
    renews: int | None = None
    renew_expires: date | None = None


class FileBody(StrictIn):
    requests: list[FileRequestIn]
    dry_run: bool = False
    via: Literal["form", "batch", "codes"] = "form"


class QuarantineBody(StrictIn):
    drive_ids: list[str]
    dry_run: bool = False


class RestoreBody(StrictIn):
    """Move these files or folders out of ``##. To Delete`` again: ``to`` ``original``
    (the path they were marked at), ``inbox``, or ``folder`` (the archive folder named in
    ``folder``, e.g. a drag out of To Delete onto it). ``dry_run``: only resolve the plan."""

    drive_ids: list[str]
    to: Literal["original", "inbox", "folder"] = "original"
    folder: str | None = None  # with ``to`` ``folder``: the archive folder to restore into
    dry_run: bool = False


class UnusedPicturesIn(StrictIn):
    """Move these unused rule pictures (names of files in ``config/rules/areas``) into the
    quarantine folder. ``dry_run``: only resolve the plan."""

    names: list[str]
    dry_run: bool = False


class MoveBody(StrictIn):
    """Move these files (drive ids) into ``folder`` (archive-relative), names kept. ``mode``
    ``link``: make a symbolic link in ``folder`` to each file instead (the file stays);
    ``copy``: copy each file there (a taken name gets ``_N``). A row of ``##. Ongoing`` or
    ``##. Important`` stands for the file it links to."""

    drive_ids: list[str]
    folder: str
    mode: Literal["move", "link", "copy"] = "move"


class RenameBody(StrictIn):
    """Give one file ``name`` in ``folder`` (its own folder: a rename; another: a move
    with the new name)."""

    drive_id: str
    name: str
    folder: str


class ItemCreateBody(StrictIn):
    tray: str
    drive_ids: list[str]
    fields: dict[str, Any] = {}
    title: str | None = None


class QuickBody(StrictIn):
    """ "Put in <tray>": one item per file, each with its scan prefill. ``fields`` (one
    file only) are used instead of the prefill: an AI suggestion, exactly as shown."""

    tray: str
    drive_ids: list[str]
    fields: dict[str, Any] | None = None


class ItemPatchBody(StrictIn):
    """Only what is given changes; a blank field value clears that field."""

    fields: dict[str, Any] | None = None
    title: str | None = None


class DoneBody(StrictIn):
    fields: dict[str, Any] = {}


class DriveIdBody(StrictIn):
    drive_id: str


class ItemFileAddBody(StrictIn):
    """Attach a file to an item: at the end, or at ``position`` (an Undo's old place)."""

    drive_id: str
    position: int | None = None


class ItemMergeBody(StrictIn):
    """The item to merge into the one in the path."""

    item_id: int


class RenewBody(StrictIn):
    """Renewed…: the new expiry date and, optionally, the new file that replaces the
    item's first one (the old one moves into its folder's Expired subfolder)."""

    expires: date
    drive_id: str | None = None


class RenewalUndoBody(StrictIn):
    batch_id: str


class DriveIdsBody(StrictIn):
    drive_ids: list[str]


class NameBody(StrictIn):
    name: str


class CollectionCreateBody(StrictIn):
    name: str
    parent_id: int | None = None  # None: at the top


class CollectionMoveBody(StrictIn):
    """Where to put a collection among its siblings: just before ``before_id`` or just
    after ``after_id`` (give exactly one)."""

    before_id: int | None = None
    after_id: int | None = None


class ParentBody(StrictIn):
    """The new parent collection; required, null for the top."""

    parent_id: int | None


class GroupCreateBody(StrictIn):
    name: str
    parent_id: int | None = None


class GroupPatchBody(StrictIn):
    """Any of these; a field left out stays as it is. ``parent_id`` null is the top of
    the collection; a new parent without ``position`` puts the group last there."""

    name: str | None = None
    parent_id: int | None = None
    position: int | None = None
    summary: str | None = None


class MergeBody(StrictIn):
    into: int


class DeleteBody(StrictIn):
    # the collections the preview listed: the delete is refused if the tree differs now
    ids: list[int] | None = None


class MoveMembersBody(StrictIn):
    to: int
    drive_ids: list[str]


class MemberGroupBody(StrictIn):
    drive_ids: list[str]
    group_id: int | None


class SummaryBody(StrictIn):
    summary: str


class PublishBody(StrictIn):
    publisher: Literal["ongoing"]
    on: bool


class NoteBody(StrictIn):
    text: str


class CheckAddBody(StrictIn):
    text: str


class CheckPatchBody(StrictIn):
    done: bool | None = None
    text: str | None = None


class CheckMoveBody(StrictIn):
    position: int


class ConvertBody(StrictIn):
    rel: str
    collection: str = ""  # ignored (may be empty) with ``star``
    destination: str | None = None
    star: bool = False  # "Star it": into the ★ built-in instead of a collection
    to_inbox: bool = False  # real files go flat into the inbox instead of ``destination``


class ConvertApplyBody(ConvertBody):
    fingerprint: str  # from the preview: only that exact plan is applied


class ImportantConvertBody(StrictIn):
    rel: str
    destination: str | None = None  # the archive folder real files move to


class ImportantConvertApplyBody(ImportantConvertBody):
    fingerprint: str  # from the preview: only that exact plan is applied


class ExportBody(StrictIn):
    format: Literal["zip", "pdf"]
    confirm_large: bool = False


class RetryIndexIn(StrictIn):
    drive_ids: list[str] = Field(max_length=10_000)


class ApplyTrayDefaultsIn(StrictIn):
    paths: list[str] = Field(min_length=1, max_length=1000)  # the keys to add
    # the ``current_text`` and ``new_text`` of the diff (for ``paths``) the user saw
    expect_current_text: str
    expect_new_text: str


class DismissTrayDefaultsIn(StrictIn):
    paths: list[str] = Field(min_length=1, max_length=1000)
