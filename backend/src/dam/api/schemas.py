"""Pydantic request and response models (they mirror the service dataclasses).

Request models forbid unknown fields, so a body can never smuggle in e.g. ``origin``.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, field_validator

from dam.ops.model import OpKind
from dam.trays.model import TrayDef


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorBody(BaseModel):
    error: str


# -- requests ---------------------------------------------------------------


class FileRequestIn(_In):
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


class FileBody(_In):
    requests: list[FileRequestIn]
    dry_run: bool = False
    via: Literal["form", "batch", "codes"] = "form"


class QuarantineBody(_In):
    drive_ids: list[str]
    dry_run: bool = False


class RestoreBody(_In):
    """Move these files or folders out of ``##. To Delete`` again: ``to`` ``original``
    (the path they were marked at), ``inbox``, or ``folder`` (the archive folder named in
    ``folder``, e.g. a drag out of To Delete onto it). ``dry_run``: only resolve the plan."""

    drive_ids: list[str]
    to: Literal["original", "inbox", "folder"] = "original"
    folder: str | None = None  # with ``to`` ``folder``: the archive folder to restore into
    dry_run: bool = False


class UnusedPicturesIn(_In):
    """Move these unused rule pictures (names of files in ``config/rules/areas``) into the
    quarantine folder. ``dry_run``: only resolve the plan."""

    names: list[str]
    dry_run: bool = False


class MoveBody(_In):
    """Move these files (drive ids) into ``folder`` (archive-relative), names kept. ``mode``
    ``link``: make a symbolic link in ``folder`` to each file instead (the file stays);
    ``copy``: copy each file there (a taken name gets ``_N``). A row of ``##. Ongoing`` or
    ``##. Important`` stands for the file it links to."""

    drive_ids: list[str]
    folder: str
    mode: Literal["move", "link", "copy"] = "move"


class RenameBody(_In):
    """Give one file ``name`` in ``folder`` (its own folder: a rename; another: a move
    with the new name)."""

    drive_id: str
    name: str
    folder: str


class ItemCreateBody(_In):
    tray: str
    drive_ids: list[str]
    fields: dict[str, Any] = {}
    title: str | None = None


class QuickBody(_In):
    """ "Put in <tray>": one item per file, each with its scan prefill. ``fields`` (one
    file only) are used instead of the prefill: an AI suggestion, exactly as shown."""

    tray: str
    drive_ids: list[str]
    fields: dict[str, Any] | None = None


class ItemPatchBody(_In):
    """Only what is given changes; a blank field value clears that field."""

    fields: dict[str, Any] | None = None
    title: str | None = None


class DoneBody(_In):
    fields: dict[str, Any] = {}


class DriveIdBody(_In):
    drive_id: str


class ItemFileAddBody(_In):
    """Attach a file to an item: at the end, or at ``position`` (an Undo's old place)."""

    drive_id: str
    position: int | None = None


class ItemMergeBody(_In):
    """The item to merge into the one in the path."""

    item_id: int


class DriveIdsBody(_In):
    drive_ids: list[str]


class NameBody(_In):
    name: str


class CollectionCreateBody(_In):
    name: str
    parent_id: int | None = None  # None: at the top


class CollectionMoveBody(_In):
    """Where to put a collection among its siblings: just before ``before_id`` or just
    after ``after_id`` (give exactly one)."""

    before_id: int | None = None
    after_id: int | None = None


class ParentBody(_In):
    """The new parent collection; required, null for the top."""

    parent_id: int | None


class GroupCreateBody(_In):
    name: str
    parent_id: int | None = None


class GroupPatchBody(_In):
    """Any of these; a field left out stays as it is. ``parent_id`` null is the top of
    the collection; a new parent without ``position`` puts the group last there."""

    name: str | None = None
    parent_id: int | None = None
    position: int | None = None
    summary: str | None = None


class MemberGroupBody(_In):
    drive_ids: list[str]
    group_id: int | None


class SummaryBody(_In):
    summary: str


class PublishBody(_In):
    publisher: Literal["ongoing"]
    on: bool


class NoteBody(_In):
    text: str


class CheckAddBody(_In):
    text: str


class CheckPatchBody(_In):
    done: bool | None = None
    text: str | None = None


class CheckMoveBody(_In):
    position: int


class ConvertBody(_In):
    rel: str
    collection: str = ""  # ignored (may be empty) with ``star``
    destination: str | None = None
    star: bool = False  # "Star it": into the ★ built-in instead of a collection
    to_inbox: bool = False  # real files go flat into the inbox instead of ``destination``


class ConvertApplyBody(ConvertBody):
    fingerprint: str  # from the preview: only that exact plan is applied


class ImportantConvertBody(_In):
    rel: str
    destination: str | None = None  # the archive folder real files move to


class ImportantConvertApplyBody(ImportantConvertBody):
    fingerprint: str  # from the preview: only that exact plan is applied


class ExportBody(_In):
    format: Literal["zip", "pdf"]
    confirm_large: bool = False


class RetryIndexIn(_In):
    drive_ids: list[str] = Field(max_length=10_000)


class ApplyTrayDefaultsIn(_In):
    paths: list[str] = Field(min_length=1, max_length=1000)  # the keys to add
    # the ``current_text`` and ``new_text`` of the diff (for ``paths``) the user saw
    expect_current_text: str
    expect_new_text: str


class DismissTrayDefaultsIn(_In):
    paths: list[str] = Field(min_length=1, max_length=1000)


# -- responses --------------------------------------------------------------


class IndexErrorOut(BaseModel):
    drive_id: str
    path: str
    name: str
    state: Literal["error", "unsupported"]
    reason: str | None  # None for files marked before reasons were stored
    retry_at: float | None


class TypeCountOut(BaseModel):
    ext: str | None  # lower-case, no dot; None for files without an extension
    count: int


class IndexErrorsOut(BaseModel):
    rows: list[IndexErrorOut]  # at most ``limit``, newest file first
    total: int  # all matching files, beyond the limit too
    unsupported_by_type: list[TypeCountOut]  # with ``all`` only; most common first


class IndexSummaryOut(BaseModel):
    searchable: int  # text indexed
    waiting: int  # pending or waiting for Drive to download
    not_readable: int  # no reader for the type, or unreadable content
    errors: int
    missing: int
    not_readable_by_type: list[TypeCountOut]  # most common first
    rows: list[IndexErrorOut]  # the not readable files, one page, newest file first
    offset: int
    page1: "Page1ProgressOut"  # how far the page-1 pass has come


class RetryIndexOut(BaseModel):
    queued: int


class TextPreviewOut(BaseModel):
    text: str
    truncated: bool


class TrayDefaultAddedOut(BaseModel):
    path: str  # dotted key path, e.g. "fields.iban"
    value: Any
    problem: str | None  # why the tray would be invalid with only this key added


class TrayDefaultsDiffOut(BaseModel):
    file: str
    added: list[TrayDefaultAddedOut]  # every missing key not dismissed
    paths: list[str]  # the keys ``new_text`` adds
    current_text: str
    new_text: str
    error: str | None  # why ``new_text`` would not be a valid tray
    # with ``?dismissed=1``: the dismissed keys still missing (else empty)
    dismissed: list[str]


class DismissTrayDefaultsOut(BaseModel):
    dismissed: list[str]  # every dismissed key path of the tray


class ApplyTrayDefaultsOut(BaseModel):
    file: str
    backup: str  # the backup's file name, next to the tray file


# a file's marks (stars): ★ Ongoing and ! Important, in that order
Mark = Literal["starred", "important"]


class MarkBody(_In):
    """``POST /api/marks/{action}``: ``group`` ("Houses/Hillside") only for important."""

    drive_ids: list[str]
    group: str | None = None


class UnlockIn(_In):
    """``POST /api/files/{id}/unlock``: ``now`` unlocks until the page lets the file go
    (the answer carries the token to send as ``X-Dam-Unlock``); ``for_good`` removes the
    owner's lock (never for an Important file)."""

    mode: Literal["now", "for_good"]


class LockStateOut(BaseModel):
    """A file's lock. ``locked``: it is locked whatever this request carries; ``reason``
    ``important`` (always locked) or ``file`` (the owner's lock). ``token`` only after an
    unlock "now"; ``unlocked_now``: a live temporary unlock exists."""

    drive_id: str
    locked: bool
    reason: Literal["important", "file"] | None = None
    unlocked_now: bool = False
    token: str | None = None
    expires_after_idle_seconds: int | None = None


class LockedFileOut(BaseModel):
    drive_id: str
    reason: Literal["important", "file"]


class LocksOut(BaseModel):
    """Every locked file, and the folders whose content is locked (a folder marked
    Important): a file inside one has no entry of its own."""

    files: list[LockedFileOut]
    folders: list[str]


class AssignmentOut(BaseModel):
    """Who a document is from (``sender``) and for (``person``), as set by the owner
    (``set_by`` "owner") or recorded by a confirmed filing ("filing")."""

    drive_id: str
    sender: str | None
    person: str | None
    set_by: Literal["owner", "filing"]
    set_at: float


class FileRecordOut(BaseModel):
    drive_id: str
    path: str
    name: str | None
    ext: str | None
    is_dir: bool
    is_link: bool
    link_target: str | None
    size: int | None
    mtime: float | None
    sha256: str | None
    doc_date: date | None
    index_state: str
    retry_at: float | None
    attempts: int
    missing: bool
    last_seen: float | None
    parked_at: float | None
    marks: list[Mark]


class FileDetailOut(BaseModel):
    record: FileRecordOut
    tags: list[str]
    # a link: the indexed file it stands for inside the archive (previews, Open and
    # Show in Finder act on it), else null; ``link_target_inside`` says which
    link_target_id: str | None
    # that file's archive path, or where the link points when it has none (outside
    # the archive, or missing); null for anything that is not a link
    link_target_path: str | None
    link_target_inside: bool
    assignment: AssignmentOut | None = None  # From / For


class SummaryOut(BaseModel):
    """A stored summary; ``outdated``: the file changed since it was written."""

    summary: str
    key_facts: list[str]
    outdated: bool


class FileSummaryOut(BaseModel):
    ai: SummaryOut | None
    user: SummaryOut | None


class FileSummaryIn(_In):
    """``source: "ai"`` is "Use this summary"; ``"user"`` a typed or edited one. A
    current user summary is kept (409) unless ``replace`` (the UI confirmed)."""

    source: Literal["ai", "user"]
    summary: str
    key_facts: list[str] = []
    replace: bool = False


class DetectedFieldsOut(BaseModel):
    dates: list[date]
    amounts: list[Decimal]
    iban: str | None
    reference: str | None


class CodeHitOut(BaseModel):
    """A filing code found for a file: by its inbox folder, a pen mark or a QR sticker.
    ``raw``: what was read (pen, QR); ``unclear``: the reading is uncertain."""

    code: str
    via: Literal["folder", "pen", "qr"]
    raw: str | None
    unclear: bool


class AreaOut(BaseModel):
    """An area of page 1 behind a suggestion or in a rule's explanation, for drawing it:
    ``box`` is [x0, y0, x1, y1] as fractions of page 1, origin top left. ``kind``: "text" (a
    rule's words), "image" (a rule's picture) or "address" (where people are looked for;
    ``rule_id`` "" is the archive's own area). ``index`` is the area's place in its rule's
    ``zones``. ``lines`` are the boxes of the lines that matched in it (for an address area,
    the line where the person was found). ``matched`` is whether the rule matched the
    document, ``reason`` why this area or the rule did not, ``wins`` whether the rule gave
    the folder or name, and ``score`` how well a picture matched (0 to 1)."""

    rule_id: str
    index: int
    box: list[float]
    kind: Literal["text", "image", "address"]
    lines: list[list[float]]
    score: float | None = None
    matched: bool = True
    reason: str | None = None
    wins: bool = False


class PersonLineOut(BaseModel):
    box: list[float]


class SuggestionOut(BaseModel):
    name: str
    folder: str | None
    tags: list[str]
    fields: DetectedFieldsOut
    doc_date: date | None
    sources: list[str]
    # where each field came from (the chips' source tag): "rule:<id>" or "scan"
    name_source: str
    folder_source: str | None
    tag_sources: dict[str, str]
    # from the rules or a filing code ("code:<CODE>"; with a "folder" hit the UI shows
    # it as "from folder <inbox folder>")
    tray: str | None
    tray_source: str | None
    collections: list[str]
    collection_sources: dict[str, str]
    codes: list[CodeHitOut]
    # two codes gave different folders, names or trays (the first is kept)
    conflict: bool
    # a QR sticker's tick boxes: True ticked, False empty, None no boxes or unreadable
    star: bool | None
    important: bool | None
    # a tick box could not be read (the batch row is flagged "unclear")
    marks_unclear: bool
    # a rule with a page-1 area could not be checked: page 1 is being read ("Reading
    # page 1...")
    waiting_for_page1: bool = False
    # page 1 cannot be read now (the reason), so "Reading page 1..." would never end
    page1_unavailable: str | None = None
    # who the document is for: "assigned" (the owner said so), "address area" (page 1) or
    # "rule:<id>" (that rule's own address area); people_found: everyone the address area
    # names (two or more: no person, ask)
    person: str | None = None
    person_source: str | None = None
    people_found: list[str] = []
    # the areas of page 1 behind the suggestion (every matching rule's, and the address
    # area used) and the line where the person was found
    areas: list[AreaOut] = []
    person_line: PersonLineOut | None = None


class FileSuggestionsOut(BaseModel):
    """What the rules and the scan suggest for a file anywhere in the archive ("Edit
    details…"). ``name`` is None when it is the file's name already."""

    name: str | None
    name_source: str | None
    folder: str | None
    folder_source: str | None
    tags: list[str]
    tag_sources: dict[str, str]
    sources: list[str]
    # who the document is for, the areas of page 1 behind the suggestion and the line where
    # the person was found
    person: str | None = None
    areas: list[AreaOut] = []
    person_line: PersonLineOut | None = None


class FileTagsIn(_In):
    """The file's tags, exactly (written directly: no preview, nothing journaled)."""

    tags: list[str]


class FileTagsOut(BaseModel):
    tags: list[str]


class TagCountOut(BaseModel):
    """A tag in use and the number of files that have it."""

    name: str
    files: int


class TagInfoOut(BaseModel):
    """A tag for the Tags screen: also tags no file has yet."""

    name: str
    files: int
    pinned: bool
    group_id: int | None


class TagGroupOut(BaseModel):
    id: int
    name: str


class TagListOut(BaseModel):
    tags: list[TagInfoOut]
    groups: list[TagGroupOut]


class SidebarTagOut(BaseModel):
    name: str
    files: int
    pinned: bool


class TagSnapshotModel(_In):
    name: str
    pinned_at: float | None = None
    group_id: int | None = None
    last_used_at: float | None = None
    drive_ids: list[str] = Field(default_factory=list)


class TagUnlinkModel(_In):
    name: str
    drive_ids: list[str]


class TagUndoModel(_In):
    """How to put a tag change back; sent to ``POST /api/tags/undo`` unchanged."""

    drop: list[str] = Field(default_factory=list)
    detach: list[TagUnlinkModel] = Field(default_factory=list)
    restore: list[TagSnapshotModel] = Field(default_factory=list)


class TagChangeOut(BaseModel):
    """The result of a tag change and how to undo it."""

    message: str
    undo: TagUndoModel


class TagNameIn(_In):
    name: str = Field(max_length=200)


class TagRenameIn(_In):
    name: str = Field(max_length=200)
    new_name: str = Field(max_length=200)


class TagMergeIn(_In):
    sources: list[str] = Field(max_length=200)
    into: str = Field(max_length=200)
    dry_run: bool = False


class TagMergePlanOut(BaseModel):
    into: str
    gains: int
    removes: list[str]
    message: str
    undo: TagUndoModel | None


class TagPinIn(_In):
    names: list[str] = Field(max_length=200)
    pinned: bool


class TagGroupSetIn(_In):
    names: list[str] = Field(max_length=200)
    group_id: int | None


class TagGroupNameIn(_In):
    name: str = Field(max_length=200)


class TagGroupCreatedOut(BaseModel):
    id: int
    name: str


class TagGroupDeletedOut(BaseModel):
    name: str
    members: list[str]
    message: str


class TagGroupRestoreIn(_In):
    name: str = Field(max_length=200)
    members: list[str] = Field(max_length=2000)


class ScanFieldOut(BaseModel):
    kind: Literal[
        "doc_date", "due_date", "date", "total", "amount", "iban", "reference", "payee", "custom"
    ]
    label: str | None  # the name of a "custom" field, else null
    value: str  # normalised for its kind: ISO date, "84.20", compact IBAN


class ScanFieldIn(_In):
    kind: Literal[
        "doc_date", "due_date", "date", "total", "amount", "iban", "reference", "payee", "custom"
    ]
    label: str | None = None
    value: str


class ScanFieldsIn(_In):
    fields: list[ScanFieldIn]


class ScanFieldsOut(BaseModel):
    fields: list[ScanFieldOut]
    edited: bool  # a saved list (else the detected one)


class InboxEntryOut(BaseModel):
    record: FileRecordOut
    suggestion: SuggestionOut
    text_excerpt: str
    # tray field prefills found in the scan, by ``FieldDef.prefill`` key
    prefill: dict[str, str]
    # the scan fields: the user's saved list, else the detected one
    fields: list[ScanFieldOut]
    fields_edited: bool
    # the tray the scan says it belongs in (a rule's then.tray, else the To pay guess)
    tray_guess: str | None
    # the trays the file already has an open item in
    open_trays: list[str]
    # From / For chips: what the owner (or a confirmed filing) said; null when nothing
    assignment: AssignmentOut | None = None


class ResolvedOpOut(BaseModel):
    kind: OpKind
    src: str | None
    dst: str
    drive_id: str | None
    note: str | None


class BatchResultOut(BaseModel):
    batch_id: str
    dry_run: bool
    done: list[ResolvedOpOut]
    failed: ResolvedOpOut | None
    error: str | None
    index_error: str | None


class DraftWordOut(BaseModel):
    word: str
    ticked: bool


class RuleDraftOut(BaseModel):
    id: str
    words: list[DraftWordOut]
    folder: str | None
    name: str | None
    tags: list[str]
    tray: str | None
    payee: str | None


class RuleOfferOut(BaseModel):
    """Offer to make a rule (``new``) or change a learned one (``update``) from a filing."""

    kind: Literal["new", "update"]
    rule_id: str | None
    drive_id: str
    draft: RuleDraftOut


class FileItResultOut(BatchResultOut):
    """The batch, plus tagging and follow-up problems: the files were filed even if
    tagging or creating the items/memberships/notes failed."""

    tag_error: str | None
    untagged: list[str]
    items: list[int]  # tray items created
    follow_up_error: str | None
    offer: RuleOfferOut | None = None


class MoveResultOut(BatchResultOut):
    """The move batch, plus the drive ids that needed no op (already in the folder)."""

    unchanged: list[str]


class UndoResultOut(BatchResultOut):
    """The undo batch, plus the first error removing what the undone batch created
    (tray items, collection entries, notes): the files were restored even then."""

    follow_up_error: str | None
    kept: list[str] = []  # folders the undo left alone because something is in them now


class DirEntryOut(BaseModel):
    name: str
    path: str
    is_dir: bool
    is_link: bool
    size: int | None
    mtime: float | None
    drive_id: str
    marks: list[Mark]


class FlatFilesOut(BaseModel):
    """The Browse Files view: up to ``limit`` rows, plus how many files there are."""

    rows: list[DirEntryOut]
    total: int


class SearchHitOut(BaseModel):
    drive_id: str
    path: str
    name: str
    snippet: str
    rank: float
    size: int | None
    mtime: float | None
    marks: list[Mark]


class JournalEntryOut(BaseModel):
    id: int
    batch_id: str
    seq: int
    kind: str
    src: str | None
    dst: str | None
    drive_id: str | None
    size: int | None
    mtime: float | None
    is_file: bool | None
    state: str
    error: str | None
    origin: str
    undo_of: str | None
    created: float
    finished: float | None
    # the file's marks (★ / !), when the row names one (``drive_id``); [] otherwise
    marks: list[Mark] = []


class BatchSummaryOut(BaseModel):
    batch_id: str
    created: float
    origin: str
    ops: list[JournalEntryOut]
    undone: bool
    is_undo: bool
    undoable: bool
    label: str | None = None
    undo_of: str | None = None
    undoes_label: str | None = None


class RecoveryResultOut(BaseModel):
    entries: list[JournalEntryOut]
    index_errors: list[str]


class RuleErrorOut(BaseModel):
    file: str
    message: str


class SpecialFoldersOut(BaseModel):
    inbox: str
    ongoing: str
    important: str
    quarantine: str


class ActiveArchiveOut(BaseModel):
    """The archive (profile) this server shows."""

    id: str
    name: str
    color: str  # #rrggbb


class Page1BlockedOut(BaseModel):
    reason: str  # "no OCR engine", "page 1 took too long to read", ...
    count: int


class Page1ProgressOut(BaseModel):
    """The page-1 layout pass: documents whose page 1 is read, of all it reads, and
    whether the backfill of documents outside the inbox is on."""

    read: int
    total: int
    backfill: bool
    # of those not read, the ones waiting because they cannot be read now, and why
    blocked: list[Page1BlockedOut] = []
    # reads finished per minute lately (None: too few to say)
    rate_per_min: float | None = None
    # what is left to read, by kind, and how fast each kind is read (a minute's worth of
    # reads): PDFs with a text layer are read quickly, scans and photos (OCR) and slow
    # downloads at the indexer's pace. The time left follows from these.
    text_left: int = 0
    scans_left: int = 0
    text_per_min: int = 0
    scans_per_min: int = 0


class StatusOut(BaseModel):
    files: int
    indexed: int
    pending: int
    cloud_pending: int
    errors: int
    unsupported: int
    missing: int
    inbox_count: int
    rule_errors: list[RuleErrorOut]
    tray_errors: list[RuleErrorOut]
    recovery_pending: int
    archive_available: bool
    special_folders: SpecialFoldersOut  # the configured names of the app's folders
    inbox_exists: bool = True  # the inbox folder is there (False: a new archive, no layout yet)
    # links can be made (False only on Windows without Developer Mode): Link is then off
    can_link: bool = True
    page1: Page1ProgressOut | None = None  # None only from the setup-mode server
    # False only from the setup-mode server (then only ``archive`` and ``profiles_count``
    # are set besides it): no archive folder yet
    configured: bool = True
    archive: ActiveArchiveOut | None = None
    profiles_count: int = 1


# -- first-run setup (only while no archive folder is configured) -----------------


class SetupFolderOut(BaseModel):
    role: str
    title: str
    name: str
    purpose: str


class SetupCandidateOut(BaseModel):
    provider: str
    label: str
    path: str


class SetupCandidatesOut(BaseModel):
    candidates: list[SetupCandidateOut]
    special_folders: list[SetupFolderOut]  # what the app expects (a layout makes them)
    layouts: "list[LayoutTemplateOut]" = []  # the starter layouts


class SetupPathIn(_In):
    path: str = Field(max_length=4096)


class LayoutRowIn(_In):
    key: str | None = Field(default=None, max_length=64)
    name: str = Field(max_length=255)


class SpecialNamesIn(_In):
    inbox: str = Field(max_length=255)
    ongoing: str = Field(max_length=255)
    important: str = Field(max_length=255)
    quarantine: str = Field(max_length=255)


class LayoutIn(_In):
    """The layout the user chose and edited: which template it came from (ties rows to
    its example rules), the numbering and the rows. Inside the running app the special
    folders are the configured ones; in first-run setup ``special`` names them."""

    template: str | None = Field(default=None, max_length=64)
    numbered: bool = True
    folders: list[LayoutRowIn] = Field(max_length=100)
    special: SpecialNamesIn | None = None


class SetupLayoutPreviewIn(_In):
    path: str = Field(max_length=4096)
    layout: LayoutIn


class SetupValidateOut(BaseModel):
    ok: bool
    path: str | None  # the absolute path that was checked
    message: str  # why it cannot be used (empty when ok)
    exists: bool
    can_create: bool  # missing, but the folder above it is writable
    subfolders: list[str]  # folders directly inside, to descend into
    # an existing folder with nothing in it but OS junk (.DS_Store, Thumbs.db, ...): a
    # new archive can start here; ``item_count`` counts what is in it, junk excluded
    empty: bool = False
    item_count: int = 0


class SetupIn(_In):
    archive_root: str = Field(max_length=4096)
    # only when the user confirmed: create this one (missing) folder; its parent must exist
    create: bool = False
    # start a new archive: make these folders (and write the special names to the
    # settings) right after the folder is saved; previewed with /api/setup/layout-preview
    layout: LayoutIn | None = None


class SetupFolderStatusOut(SetupFolderOut):
    exists: bool


class SetupOut(BaseModel):
    archive_root: str
    # True when the app could not switch itself on: stop it and run ``dam serve`` again
    restart_needed: bool
    special_folders: list[SetupFolderStatusOut]
    # set when a layout was asked for: what happened to it
    layout: "LayoutResultOut | None" = None


class LayoutFolderOut(BaseModel):
    path: str
    role: str  # inbox | ongoing | important | quarantine | layout
    title: str
    exists: bool  # already there: left as it is


class LayoutPreviewOut(BaseModel):
    folders: list[LayoutFolderOut]
    to_create: int
    label: str  # the Activity title the batch will get
    ops: list[ResolvedOpOut]
    rule_ids: list[str]  # example rules that would be written
    rules_seedable: bool  # False: the archive has its own rules, which stay as they are


class LayoutResultOut(BaseModel):
    """The layout batch (None when it could not even start: ``error`` says why)."""

    batch: BatchResultOut | None = None
    created: int = 0
    rules_written: bool = False
    rule_ids: list[str] = []
    rules_error: str | None = None
    error: str | None = None


class LayoutRowOut(BaseModel):
    key: str | None
    name: str


class LayoutTemplateOut(BaseModel):
    id: str
    title: str
    description: str
    folders: list[LayoutRowOut]


class LayoutTemplatesOut(BaseModel):
    templates: list[LayoutTemplateOut]
    special_folders: list[SetupFolderOut]  # role, title, name, one-line purpose


class FolderPathIn(_In):
    path: str = Field(default="", max_length=4096)


class NewFolderIn(_In):
    """Make folder ``name`` inside ``parent`` ("" = at the top of the archive)."""

    parent: str = Field(default="", max_length=4096)
    name: str = Field(max_length=255)


# -- Phase 2: trays and items ------------------------------------------------------


class TraysOut(BaseModel):
    trays: list[TrayDef]  # in order; a field's ``copy`` means "show a copy button"
    errors: list[RuleErrorOut]  # tray files that were skipped


class ItemOut(BaseModel):
    id: int
    tray_id: str
    title: str
    # field name -> value: dates as "YYYY-MM-DD", money as "84.20", text, IBAN and
    # reference as text, checkbox as bool; a value named in ``invalid_fields`` is the
    # raw stored value
    fields: dict[str, Any]
    date: date | None
    state: Literal["open", "done"]
    created: float
    done_at: float | None
    done_fields: dict[str, Any] | None
    files: list[str]  # drive ids
    created_by_batch: str | None
    missing_required: list[str]
    invalid_fields: list[str]
    tray_name: str
    tray_removed: bool


class PrintedFieldsOut(BaseModel):
    iban: str
    amount: str | None
    reference: str
    due_date: date | None


class ItemBarcodeOut(BaseModel):
    """The item's Finnish bank barcode, built from its current fields."""

    code: str | None  # the 54 digits; None when it cannot be built (see ``reason``)
    modules: list[int] | None  # Code 128 set C bar/space widths, bar first
    reason: str | None  # one line: why there is no barcode
    printed: str | None  # the barcode read from one of the item's files
    # ``printed``'s values in the item field formats ("FI…" compact, "84.20",
    # "YYYY-MM-DD"); amount/due_date None where the barcode leaves them open
    printed_fields: PrintedFieldsOut | None
    mismatch: list[str]  # field names where ``printed`` disagrees with the fields


class QuickOut(BaseModel):
    created: list[ItemOut]
    skipped: list[str]  # drive ids that already had an open item in that tray
    # open items of other trays moved into this one (a file lives in one tray), and the
    # tray id each came from, by item id (as a string key), for the Undo
    moved: list[ItemOut]
    moved_from: dict[str, str]


class ItemMoveBody(_In):
    """Move an open item to another tray."""

    tray: str


class ItemFileOut(BaseModel):
    drive_id: str
    path: str | None  # None: not in the index
    ext: str | None
    # "missing": gone (or parked); "to_delete": in the quarantine folder
    state: Literal["ok", "missing", "to_delete"]
    # present and directly in the inbox or in a filing code's inbox folder (not filed yet)
    in_inbox: bool
    marks: list[Mark]


class TrayItemOut(ItemOut):
    """An item as a tray list shows it: how urgent (the Today levels; None when done or
    dated later), whether a file is missing or in the quarantine folder, whether the
    item has a note, and its first file (for Quick Look on the list)."""

    level: Literal["overdue", "today", "soon", "undated"] | None
    file_state: Literal["ok", "missing", "to_delete"]
    has_note: bool
    checklist_open: int  # open to-dos on the item's checklist
    checklist_total: int
    # "written": the owner wrote a summary on any of its files, else "ai" if any has one
    summary: Literal["ai", "written"] | None
    first_file: ItemFileOut | None  # None: the item has no files


class ItemEventOut(BaseModel):
    id: int
    at: float
    kind: Literal[
        "created", "edited", "done", "reopened", "file_added", "file_removed", "moved", "merged_in"
    ]
    data: dict[str, Any]


# -- collections ----------------------------------------------------------------------


class MemberOut(BaseModel):
    drive_id: str
    path: str | None
    is_dir: bool
    missing: bool
    quarantined: bool
    group_id: int | None  # None: ungrouped
    marks: list[Mark]
    is_link: bool = False  # a symbolic link: Trash moves the link, never its target


class GroupOut(BaseModel):
    id: int
    collection_id: int
    parent_id: int | None  # None: at the top of the collection
    name: str
    position: int  # among its siblings: 0, 1, ...
    summary: str


class CollectionOut(BaseModel):
    id: int
    name: str
    state: Literal["open", "closed"]
    created: float
    closed_at: float | None
    publish: dict[str, bool]
    ongoing_rel: str | None
    members: list[MemberOut]
    ongoing_status: str | None
    summary: str
    # flat: top level first, then by parent id; siblings by position
    groups: list[GroupOut]
    parent_id: int | None  # the parent collection; None: at the top
    path: list[str]  # the names from the root down to this collection
    # the built-in ★ Ongoing ("starred") or ! Important ("important"); None: ordinary
    kind: Mark | None
    # the owner's order among the collections with the same parent (0, 1, ...)
    position: int


class CollectionRowOut(CollectionOut):
    """A collection as the list shows it: plus its usable file count (folder members
    expanded, missing and quarantined files left out) and open checklist entries."""

    files: int
    open_checks: int


class CollectionChangeOut(BaseModel):
    """A collection change (incl. adding or removing members) and the Ongoing sync that
    followed it. ``batch`` is None
    when the sync had nothing to do (or failed: then ``problems`` says so)."""

    collection: CollectionOut
    batch: BatchResultOut | None
    problems: list[str]
    ongoing_status: str | None


class MemberItemOut(BaseModel):
    item: ItemOut
    level: Literal["overdue", "today", "soon", "undated"] | None  # None: dated later


class MemberAttentionOut(BaseModel):
    """A member that needs attention: its open tray items, and whether it is still
    directly in the inbox or in a filing code's inbox folder (not filed yet)."""

    drive_id: str
    in_inbox: bool
    items: list[MemberItemOut]


class FileLinksOut(BaseModel):
    items: list[ItemOut]  # the file's open items
    collections: list[CollectionOut]  # direct or through a folder member
    note: str


# -- notes and checklists -------------------------------------------------------------


class NoteOut(BaseModel):
    text: str


class ChecklistItemOut(BaseModel):
    id: int
    text: str
    done: bool
    position: int


# -- Ongoing --------------------------------------------------------------------------


class EntryItemOut(BaseModel):
    name: str
    drive_id: str | None
    is_dir: bool
    is_link: bool
    unreadable: bool
    marks: list[Mark] = []  # its file's (``drive_id``); [] when it has none


class EntryOut(BaseModel):
    rel: str
    kind: Literal["link", "folder", "file"]
    target_rel: str | None
    managed: bool
    suggested_name: str
    contents: list[str]
    problem: str | None
    collection_id: int | None
    collection_name: str | None
    drive_id: str | None
    is_dir: bool
    items: list[EntryItemOut]
    real_files: int  # real files (not links) at any depth; 0 for a link
    marks: list[Mark] = []  # its file's (``drive_id``); [] when it has none


class ConvertPlanOut(BaseModel):
    ops: list[ResolvedOpOut]
    members: list[str]
    notes: list[str]
    collection: str
    existing: bool
    existing_members: int
    fingerprint: str
    # per member, the Important group it goes into ("A/B"; "" for none)
    groups: list[str] = []
    # per member, the name its link keeps (a converted shortcut's own; "" for the file's)
    link_names: list[str] = []


class SyncResultOut(BaseModel):
    plan: list[ResolvedOpOut]
    # the last batch applied (kept for compatibility); ``batches`` has one per
    # publish root (##. Ongoing, ##. Important) that changed something
    batch: BatchResultOut | None
    problems: list[str]
    batches: list[BatchResultOut] = []


class ConvertResultOut(BaseModel):
    batch: BatchResultOut
    collection_id: int | None
    problems: list[str]
    sync: SyncResultOut | None


# -- export ---------------------------------------------------------------------------


class NotIncludedOut(BaseModel):
    path: str
    reason: str


class ExportOut(BaseModel):
    """``token`` is None (and ``needs_confirm`` true) when the export is over 200 MB and
    ``confirm_large`` was not set: nothing was built, ``size`` is the estimate."""

    token: str | None
    size: int
    needs_confirm: bool
    not_included: list[NotIncludedOut]


# -- Today ----------------------------------------------------------------------------


class AttentionItemOut(BaseModel):
    item: ItemOut
    tray: str
    level: Literal["overdue", "today", "soon", "undated"]
    missing_required: list[str]
    file_state: Literal["ok", "missing", "to_delete"]
    note_excerpt: str | None  # the item's note on one line, at most 120 chars + "…"


class TrayCountOut(BaseModel):
    tray_id: str
    name: str
    open: int
    overdue: int
    sum: Decimal | None
    waiting_long: int


class CollectionSummaryOut(BaseModel):
    id: int
    name: str
    files: int
    open_checks: int
    note_excerpt: str
    # file members still directly in the inbox or in a filing code's inbox folder
    in_inbox: int


class OverviewOut(BaseModel):
    inbox: int
    trays: list[TrayCountOut]
    collections: list[CollectionSummaryOut]


class InboxStatsOut(BaseModel):
    count: int
    oldest_days: int | None  # local days since the oldest inbox file's mtime
    this_week: int  # under 7 days
    last_week: int  # 7 to 13 days
    older: int  # 14 days or more
    overdue: int  # scanned due date before today


class FoundOut(BaseModel):
    """An inbox document guessed to belong in a tray it has no open item in."""

    drive_id: str
    name: str
    tray: str
    tray_name: str
    due_date: date | None
    total: Decimal | None
    overdue: bool
    marks: list[Mark]


class RemindersStatusOut(BaseModel):
    last_run: datetime | None  # the last completed check (None: none since start)
    errors: dict[str, str] = Field(description="channel id -> error of the last check")
    skipped: str | None  # why the latest check was skipped (another run was busy)


class TrayItemsOut(BaseModel):
    """A tray's first open items for its Today card: by date, undated last."""

    tray_id: str
    items: list[ItemOut]


class TodayOut(BaseModel):
    attention: list[AttentionItemOut]
    overview: OverviewOut
    unmanaged_ongoing: int
    # top-level ``##. Important`` entries not managed by the app yet (Convert Important)
    unmanaged_important: int = 0
    # why the Ongoing sync keeps failing (the same plan is not retried); None when fine
    ongoing_sync_failure: str | None
    reminders: RemindersStatusOut
    tray_errors: list[RuleErrorOut]
    inbox_stats: InboxStatsOut
    found: list[FoundOut]
    open_items: list[TrayItemsOut]  # per tray in tray order, at most 8 each
    # inbox files with a filing code (the File N marked button), flagged ones included
    marked: int = 0
    # inbox files the barcode pass has still to read for QR stickers ("Reading filing
    # codes..."); 0 when the code table is empty
    reading_codes: int = 0


# -- Phase 3: AI ---------------------------------------------------------------


class AIStatusOut(BaseModel):
    """``enabled``: AI can be used (``ai.enabled``, the on/off switch and a key).
    ``switched_on``: the switch alone (``dam ai --on/--off``, Activity → AI).
    ``state_error``: ai-state.json is unreadable or invalid, so the switch reads as off
    (fails closed) until it is switched on again; else null."""

    enabled: bool
    has_key: bool
    switched_on: bool
    state_error: str | None
    month_spend_eur: float
    budget_eur: float
    models: dict[str, str]
    exclude_folders: list[str]
    # the excluded folders that are not folders in the archive (empty while it is away)
    exclude_missing: list[str] = []


class AIStateIn(_In):
    """The on/off switch, stored in ``<data dir>/ai-state.json`` (never settings.yaml)."""

    enabled: StrictBool


class AIExcludeIn(_In):
    """The whole list of excluded folders (archive paths), saved to ``ai.exclude_folders``
    in settings.yaml; it replaces the defaults."""

    folders: list[StrictStr]


class AIPrepareIn(_In):
    """The task's parameters (``drive_id``, ``question``, ...; ``refresh: true`` asks
    again instead of using a cached result)."""

    params: dict[str, Any] = {}


class PreparedOut(BaseModel):
    """Exactly what ``run`` would send (the sheet shows ``payload_text``), the model,
    the worst-case estimate, why it is blocked (or null) and the token for ``run``.
    ``cached`` is an earlier result for the same input (running it costs nothing).
    ``notes`` say what was left out and why (excluded collection members); they are
    shown, never sent. ``timeout_s``: how long a send waits before giving up."""

    task: str
    model: str
    system: str
    payload_text: str
    files: list[str]
    estimate_eur: float
    timeout_s: int
    blocked: str | None
    token: str
    cached: dict[str, Any] | None
    notes: list[str] = []


class AIRunIn(_In):
    token: str


class RunOut(BaseModel):
    data: dict[str, Any]
    cost_eur: float
    cached: bool


class AILogRow(BaseModel):
    id: int
    at: float
    task: str
    model: str
    files: list[str]
    input_tokens: int
    output_tokens: int
    cost_eur: float
    outcome: Literal["ok", "cached", "error", "fake"]
    error: str | None
    duration_ms: int


class AILogOut(BaseModel):
    rows: list[AILogRow]


# -- archives (profiles) -----------------------------------------------------------


class ArchiveOut(BaseModel):
    id: str
    name: str
    color: str
    data_dir: str  # where its settings, index and logs live
    archive_root: str | None  # its archive folder (None: not set up yet)
    configured: bool
    current: bool  # the one this window shows
    in_use_elsewhere: bool  # another dam process serves it
    port: int | None  # ... on this port, when known


class ArchivesOut(BaseModel):
    archives: list[ArchiveOut]
    current: str
    can_switch: bool  # False: this window cannot open another archive (restart instead)


class ArchiveAddIn(_In):
    name: str = Field(max_length=200)
    color: str | None = Field(default=None, max_length=16)
    # build the fictional demo archive in this (new or empty) folder
    demo_folder: str | None = Field(default=None, max_length=4096)


class ArchiveUpdateIn(_In):
    name: str | None = Field(default=None, max_length=200)
    color: str | None = Field(default=None, max_length=16)


class ArchiveForgetIn(_In):
    # forgetting the archive in use: the one to open instead
    switch_to: str | None = Field(default=None, max_length=100)


class ArchiveSwitchOut(BaseModel):
    archive: ArchiveOut
    restart_needed: bool = False


class ArchiveForgetOut(BaseModel):
    forgotten: ArchiveOut
    # nothing is deleted: these folders are still there
    data_dir: str
    archive_root: str | None


class ArchiveRevealIn(_In):
    what: Literal["data", "archive"]


# -- backups ------------------------------------------------------------------


class BackupOut(BaseModel):
    name: str
    created_at: str  # ISO 8601 with the offset
    size: int  # bytes
    kind: Literal["manual", "before-restore"]
    revision: str | None  # the database's migration revision when it was made
    app_version: str | None
    archive_root: str | None
    problem: str | None  # why it cannot be restored here; None when it can


class BackupsOut(BaseModel):
    folder: str  # <data dir>/backups
    backups: list[BackupOut]  # newest first
    can_restore: bool  # False: this window cannot close and reopen the archive


class BackupRestoreIn(_In):
    # required: the user was asked whether to back up the current state first
    backup_current: bool


class BackupRestoreOut(BaseModel):
    restored: str
    safety_backup: BackupOut | None  # the backup of the state before the restore
    replaced_folder: str  # where the replaced settings were moved (nothing is deleted)


# -- filing codes -------------------------------------------------------------


class FilingCodeIn(_In):
    # checked by ``FilingCode`` (and the app) so a bad entry answers 400 with its text
    code: str
    label: str = ""
    tray: str | None = None
    folder: str | None = None
    name: str | None = None
    tags: list[str] = Field(default_factory=list)
    collections: list[str] = Field(default_factory=list)
    as_suggested: bool = False
    inbox_folder: str | None = None


class FilingCodeOut(BaseModel):
    code: str
    label: str
    tray: str | None
    folder: str | None
    name: str | None
    tags: list[str]
    collections: list[str]
    as_suggested: bool
    inbox_folder: str | None


class CodeProblemOut(BaseModel):
    code: str
    message: str


class CodeWarningOut(BaseModel):
    code: str
    confusable_with: list[str]


class FilingCodesOut(BaseModel):
    codes: list[FilingCodeOut]
    problems: list[CodeProblemOut]
    warnings: list[CodeWarningOut]


class SheetLayoutIn(_In):
    # checked by ``SheetLayout`` so a grid that does not fit A4 answers 400 with its text
    name: str
    columns: int
    rows: int
    label_w_mm: float
    label_h_mm: float
    top_mm: float
    left_mm: float
    gap_x_mm: float
    gap_y_mm: float
    cut_lines: bool = False


class SheetLayoutOut(BaseModel):
    id: str
    name: str
    columns: int
    rows: int
    label_w_mm: float
    label_h_mm: float
    top_mm: float
    left_mm: float
    gap_x_mm: float
    gap_y_mm: float
    cut_lines: bool


class StickerSheetIn(_In):
    # the sheet GET's query, parsed
    # how many stickers of each code, in print order (checked by the route: 400)
    codes: dict[str, int]
    layout: str
    start_at: int = 1
    boxes: bool = True
    blank_labels: bool = False
    outlines_only: bool = False


class FilingCodeFoldersOut(BaseModel):
    # code inbox folders not in the inbox yet, and inbox subfolders that are no code's
    missing: list[str]
    stray: list[str]


class FileRequestOut(BaseModel):
    """A filing request as ``POST /api/inbox/file`` takes it (``FileRequestIn``)."""

    drive_id: str
    name: str
    folder: str  # "" when nothing suggests one (the row needs input)
    tags: list[str]
    tray: str | None
    tray_fields: dict[str, str]
    collections: list[str]
    note: str
    star: bool
    important: bool


class BatchRowOut(BaseModel):
    """A row of the File N marked batch: an inbox file with a filing code, the request
    that files it and the tray fields that will be stored. ``flag``: why the row starts
    unticked (``unclear``: a code or a sticker's tick box read uncertainly,
    ``conflict``: codes disagree, ``needs_input``: the filing would be refused);
    ``problem`` says what to fix ("folder", "Tick box unclear: star", a required tray
    field such as "due date", or the refusal)."""

    drive_id: str
    codes: list[CodeHitOut]
    request: FileRequestOut
    tray_fields: dict[str, str]
    flag: Literal["unclear", "conflict", "needs_input"] | None
    problem: str | None


# -- rules --------------------------------------------------------------------


class ZoneIn(_In):
    """An area of page 1: ``box`` is [x0, y0, x1, y1] as fractions of the page, origin top
    left. It has words (``text_contains``) or a picture (``image``, ``areas/<name>.png``
    from ``POST /api/rules/area-picture``): exactly one. ``min_score`` (a picture's, 0 to 1)
    is the score the picture needs; left out, the default (0.85). ``match`` (for words):
    how a word matches, ``word_start`` (begins a word, any ending), ``whole_word`` or
    ``anywhere``. Left out it is ``anywhere`` (how rules written before it matched)."""

    box: list[float] = Field(min_length=4, max_length=4)
    text_contains: list[str] | None = None
    image: str | None = None
    min_score: float | None = None
    match: Literal["word_start", "whole_word", "anywhere"] | None = None


class RuleWhenIn(_In):
    text_contains: list[str] = Field(default_factory=list)
    filename_matches: str | None = None
    folder_is: str | None = None
    # areas of page 1: every one must match, within an area any one of its words
    zones: list[ZoneIn] = Field(default_factory=list)
    person: str | None = None


class RuleThenIn(_In):
    folder: str | None = None
    name: str | None = None
    tags: list[str] = Field(default_factory=list)
    tray: str | None = None
    payee: str | None = None
    collections: list[str] = Field(default_factory=list)


class RuleIn(_In):
    id: str
    when: RuleWhenIn = Field(default_factory=RuleWhenIn)
    then: RuleThenIn = Field(default_factory=RuleThenIn)
    person_zone: list[float] | None = Field(default=None, min_length=4, max_length=4)
    sender: str | None = None


class RuleReplayIn(_In):
    rule: RuleIn
    replaces: str | None = None
    # for a new rule: the learned rule it goes directly above (see ``ZoneDraftOut``)
    place_above: str | None = None
    # continue a replay that stopped at its time budget: the ``next_after`` it gave (an
    # opaque cursor, good for a little while). Only the documents it had not reached are
    # looked at; the counts are for that part.
    after: str | None = None
    # the document the areas were drawn on: the documents in its folder are looked at early
    near_drive_id: str | None = None
    # the document the rule is being made from: left out of every count and list, and
    # judged on its own in ``source`` of the result
    source_drive_id: str | None = None


class RuleReplayJobIn(_In):
    """Start a test of a rule in the background (same placement fields as ``RuleReplayIn``).
    ``sheet`` names the open sheet it is for: starting another test for the same sheet ends
    the first."""

    rule: RuleIn
    sheet: str = Field(min_length=1, max_length=64)
    replaces: str | None = None
    place_above: str | None = None
    near_drive_id: str | None = None
    source_drive_id: str | None = None


class AreasForIn(_In):
    """The rule being tested and the document to draw its areas on."""

    rule: RuleIn
    drive_id: str


class AreasForOut(BaseModel):
    """The rule's areas on this document, as the suggestion has them (``AreaOut``): the
    matched lines of each text area, the best place and score of each picture area, and for
    one that did not match, why. Changes nothing."""

    areas: list[AreaOut]


class RuleMoveIn(_In):
    delta: int


class RuleExplainIn(_In):
    drive_id: str


class RulesStateIn(_In):
    offer: bool | None = None
    clear_declined: bool = False


class RulesDeclineIn(_In):
    words: list[str]


class ZoneOut(BaseModel):
    box: list[float]
    text_contains: list[str] | None
    image: str | None
    min_score: float | None = None
    match: Literal["word_start", "whole_word", "anywhere"] = "anywhere"


class RuleWhenOut(BaseModel):
    text_contains: list[str]
    filename_matches: str | None
    folder_is: str | None
    zones: list[ZoneOut]
    person: str | None


class RuleThenOut(BaseModel):
    folder: str | None
    name: str | None
    tags: list[str]
    tray: str | None
    payee: str | None
    collections: list[str]


class RuleStatsOut(BaseModel):
    suggested: int
    changed: int
    last_used: float | None
    flagged: bool


class RuleSampleOut(BaseModel):
    """A document the rule was last used on (still in the archive): a page to show its
    areas on."""

    drive_id: str
    name: str | None
    ext: str | None


class RuleOut(BaseModel):
    id: str
    file: str
    learned: bool
    when: RuleWhenOut
    then: RuleThenOut
    person_zone: list[float] | None
    sender: str | None
    stats: RuleStatsOut
    sample: RuleSampleOut | None = None


class RuleErrorOut(BaseModel):
    file: str
    message: str


class RulesStateOut(BaseModel):
    offer: bool
    declined: int


class RulesOut(BaseModel):
    rules: list[RuleOut]
    errors: list[RuleErrorOut]
    state: RulesStateOut
    # picture files in config/rules/areas that no loaded rule uses (a deleted rule leaves
    # its pictures)
    unused_pictures: list[str] = []
    # the score a picture area needs when it names none
    default_min_score: float = 0.85


class ReplayHitOut(BaseModel):
    drive_id: str
    path_now: str
    path_rule: str


class ShadowOut(BaseModel):
    drive_id: str
    rule_id: str  # the earlier rule that wins


class PictureScoreOut(BaseModel):
    """How well page 1 of a document matched a rule's picture areas (the lowest score of
    them) and whether the rule matched it."""

    path: str
    drive_id: str
    score: float
    matched: bool
    # for a document the rule did not match: the score its failing area needed (it is only
    # listed when within 0.15 of it)
    needed: float | None = None


class NotCheckedOut(BaseModel):
    """A document the rule could match by its words but whose page 1 could not be looked
    at; ``reason``: "page 1 not read yet", "no OCR engine" or "missing"."""

    path: str
    drive_id: str
    reason: str


class MarkedDocOut(BaseModel):
    path: str
    drive_id: str


class MarkedOut(BaseModel):
    """For a rule with a sender: the documents the owner marked as from that sender.
    ``missed`` are documents whose page 1 was read and the rule does not match (paths);
    ``not_checked`` those that could not be looked at yet (never counted as missed)."""

    total: int
    found: int
    missed: list[MarkedDocOut]
    not_checked: list[NotCheckedOut]


class SourceDocOut(BaseModel):
    """The document the rule is being made from, judged as live filing would (a document in
    the inbox by the rule as written, a filed one without its folder condition, as the test
    does) and left out of every count and list of the test. ``matched`` is null while page 1
    (or its picture) is not read yet, so it cannot be told; ``reason`` says why not, in the
    words of the explanation of a document ("no word found in the area", "the picture in the
    area scores 0.71, needs 0.85")."""

    drive_id: str
    path: str
    matched: bool | None
    reason: str = ""


class ReplayOut(BaseModel):
    matched: int
    same: int
    different: list[ReplayHitOut]
    inbox: int
    shadowed: list[ShadowOut]
    checked: int
    total: int
    truncated: bool
    not_checked: list[NotCheckedOut]
    # how many page-1 reads are queued by this replay (post it again to see them)
    reading: int
    # when ``truncated``: send it as ``after`` to test the rest, from where this stopped (an
    # opaque cursor: the order of the test is remembered for a little while)
    next_after: str | None = None
    # the filed documents gone through, those that could not be checked included
    looked_at: int = 0
    marked: MarkedOut | None = None  # only for a rule with a sender (first call only)
    # only for a rule with picture areas: the lowest scores of its matches and the highest
    # of its near misses (documents where only a picture area failed, within 0.15 of the
    # score it needed), to see how well they are told apart
    scores: list[PictureScoreOut] = []
    # only when the request named a ``source_drive_id`` that is in the index
    source: SourceDocOut | None = None


class ReplayJobOut(BaseModel):
    """A test running in the background. ``state``: "running" (going through the
    documents), "waiting" (all looked at; ``waiting`` of them wait for page 1 to be read and
    are looked at again as it is), "done", "stopped" (by the user, or the sheet was not
    heard from) or "error". ``looked_at`` of ``total`` filed documents are gone through.
    ``result`` is what has been found so far, as a finished test gives it; it is left out
    (null) when nothing changed since the ``version`` the poll said it had."""

    job_id: str
    sheet: str
    state: Literal["running", "waiting", "done", "stopped", "error"]
    version: int
    looked_at: int
    total: int
    waiting: int
    elapsed_s: float
    error: str | None = None
    result: ReplayOut | None = None


class ReadNowOut(BaseModel):
    """How many of a test's documents were queued to have page 1 read now."""

    queued: int


class Page1LineOut(BaseModel):
    text: str
    box: list[float]  # x0, y0, x1, y1 as fractions of page 1, origin top left


class Page1Out(BaseModel):
    """Page 1's lines. ``read`` false: not read yet (a read is queued), or it cannot be
    (``unavailable`` says why: "no OCR engine"; None while it is just waiting)."""

    read: bool
    lines: list[Page1LineOut]
    unavailable: str | None = None


class AreaPictureIn(_In):
    """Cut the picture of ``box`` (fractions of page 1) from the document's page-1 picture.
    With ``save`` (and the rule's id, for the file name) it is also kept in
    ``config/rules/areas`` and the answer names it."""

    drive_id: str
    box: list[float] = Field(min_length=4, max_length=4)
    save: bool = False
    rule_id: str | None = None


class AreaPictureOut(BaseModel):
    """The crop: 8-bit grayscale, its long side at most 300 px; ``png`` is base64.
    ``image`` is the path for a zone's ``image`` once it is saved, else null."""

    width: int
    height: int
    png: str
    image: str | None = None


class Page1BoxIn(_In):
    box: list[float] = Field(min_length=4, max_length=4)


class ZoneDraftIn(_In):
    drive_id: str
    # one box, or several: each is an area of the rule, with one ticked word
    boxes: list[list[float]] = Field(default_factory=list, max_length=8)
    # boxes that become picture areas (the crop is kept as a picture file), after the others
    picture_boxes: list[list[float]] = Field(default_factory=list, max_length=4)
    sender: str | None = None

    @field_validator("boxes", "picture_boxes")
    @classmethod
    def _four_numbers(cls, boxes: list[list[float]]) -> list[list[float]]:
        if any(len(b) != 4 for b in boxes):
            raise ValueError("a box is four numbers: x0, y0, x1, y1")
        return boxes


class ZoneDraftAreaOut(BaseModel):
    """One box of a draft: the page-1 lines in it and its candidate words (one ticked)."""

    box: list[float]
    words: list[DraftWordOut]
    lines: list[str]


class ZoneDraftPictureOut(BaseModel):
    """A picture box of a draft: ``image`` is the saved crop (the zone's ``image``), ``png``
    the same picture in base64 to show."""

    box: list[float]
    image: str
    width: int
    height: int
    png: str


class ZoneDraftOut(RuleDraftOut):
    """The draft boxes drawn on page 1 start from. The rule's ``when`` is ``{folder_is,
    zones: [{box, text_contains: [the ticked word]}, ...]}``; ``zones`` has the candidate
    words and the page-1 lines of each box (``words`` itself is empty). ``place_above``: the
    learned rule that already matches the document; send it back when replaying or saving
    so the new rule is placed directly above it."""

    zones: list[ZoneDraftAreaOut]
    pictures: list[ZoneDraftPictureOut] = []
    folder_is: str | None
    sender: str | None
    place_above: str | None
    # who the document is for (the assignment, else the one person found in the address
    # area) and everyone found in the address area, for the rule sheet's For row
    person: str | None = None
    people_found: list[str] = []


class RuleExplainOut(BaseModel):
    rule_id: str
    matched: bool
    why: str
    wins: list[str]
    zone_lines: list[list[str]] = []  # page-1 lines in each of the rule's zones
    areas: list[AreaOut] = []  # the rule's areas for drawing, matched or not


# -- settings written to settings.yaml ---------------------------------------------


class Page1BackfillIn(_In):
    enabled: bool


class Page1BackfillOut(BaseModel):
    enabled: bool


class Page1SpeedIn(_In):
    """How many PDFs with a text layer have page 1 read per minute (1 to 6000)."""

    reads_per_minute: int


class Page1SpeedOut(BaseModel):
    reads_per_minute: int


class PersonIO(_In):
    name: str
    match: list[str]


class PeopleIn(_In):
    """The people list; ``address_zone`` (x0, y0, x1, y1 of page 1) is left as it is when
    omitted."""

    people: list[PersonIO]
    address_zone: list[float] | None = Field(default=None, min_length=4, max_length=4)


class PeopleOut(BaseModel):
    people: list[PersonIO]
    address_zone: list[float]
    default_address_zone: list[float]


class AssignmentsIn(_In):
    """``PUT /api/assignments``: set From and/or For on documents. A field left out stays
    as it is; an explicit null clears it. ``person`` must be in the people list."""

    drive_ids: list[str] = Field(min_length=1)
    sender: str | None = None
    person: str | None = None


class SenderOut(BaseModel):
    sender: str
    count: int


# -- maintenance ------------------------------------------------------------


class DuplicateEstimateOut(BaseModel):
    """What the duplicate check would read, from the index alone."""

    files: int
    candidates: int
    known: int
    to_read_files: int
    to_read_bytes: int


MaintenanceKindIn = Literal[
    "duplicates", "empty_folders", "broken_links", "references", "names", "waiting"
]


class MaintenanceStartIn(_In):
    kind: MaintenanceKindIn
    days: int | None = None


class MaintenanceForgetOut(BaseModel):
    forgotten: int


IgnoreKindIn = Literal[
    "duplicates", "versions", "empty_folders", "broken_links", "references", "names"
]


class MaintenanceIgnoreIn(_In):
    kind: IgnoreKindIn
    key: str = Field(min_length=1, max_length=2000)
    label: str = Field(min_length=1, max_length=2000)
    members: list[str] = Field(default_factory=list, max_length=10000)


class MaintenanceIgnoredOut(BaseModel):
    id: int
    kind: str
    key: str
    label: str
    created: float


class DupFileOut(BaseModel):
    drive_id: str
    path: str
    name: str
    size: int
    mtime: float | None
    place: Literal["numbered", "inbox", "other"]
    locked: Literal["important", "file"] | None
    why: str | None


class DupGroupOut(BaseModel):
    sha256: str
    size: int
    files: list[DupFileOut]
    keep: str


class NameGroupOut(BaseModel):
    name: str
    files: list[DupFileOut]


class UnreadableOut(BaseModel):
    path: str
    reason: str


class DuplicatesOut(BaseModel):
    groups: list[DupGroupOut]
    groups_total: int
    name_groups: list[NameGroupOut]
    name_groups_total: int
    unreadable: list[UnreadableOut]
    changed: int
    read_files: int
    reused: int
    complete: bool


class EmptyFolderOut(BaseModel):
    drive_id: str
    path: str


class EmptyFoldersOut(BaseModel):
    items: list[EmptyFolderOut]
    total: int


class BrokenLinkOut(BaseModel):
    drive_id: str
    path: str
    target: str | None
    inside: str | None


class BrokenLinksOut(BaseModel):
    items: list[BrokenLinkOut]
    total: int


class BadReferenceOut(BaseModel):
    kind: Literal["collection", "tray"]
    owner_id: str
    owner_name: str
    item_id: int | None
    drive_id: str
    path: str | None
    reason: str


class BadReferencesOut(BaseModel):
    items: list[BadReferenceOut]
    total: int


class BadNameOut(BaseModel):
    drive_id: str
    path: str
    name: str
    folder: str
    suggestion: str | None


class BadNamesOut(BaseModel):
    items: list[BadNameOut]
    total: int


class WaitingFileOut(BaseModel):
    drive_id: str
    path: str
    size: int
    since: float
    days: int
    approximate: bool


class WaitingOut(BaseModel):
    days: int
    items: list[WaitingFileOut]
    total: int
    total_size: int
    in_to_delete: int
    in_to_delete_size: int


class MaintenanceJobOut(BaseModel):
    """A check running (or finished): its progress and, once it has something, its result
    (only the field of its kind is set)."""

    job_id: str
    kind: str
    state: Literal["running", "done", "stopped", "error"]
    version: int
    done: int
    total: int
    bytes_done: int
    bytes_total: int
    current: str | None
    elapsed_s: float
    error: str | None
    duplicates: DuplicatesOut | None = None
    empty_folders: EmptyFoldersOut | None = None
    broken_links: BrokenLinksOut | None = None
    references: BadReferencesOut | None = None
    names: BadNamesOut | None = None
    waiting: WaitingOut | None = None


class DuplicateChoiceIn(_In):
    keep: str
    others: list[str]


class DuplicateResolveIn(_In):
    """What to do with the copies of one or more duplicate groups: ``quarantine`` moves
    each copy in ``others`` to To Delete, ``link`` also leaves a link to ``keep`` where it
    was. ``carry_over`` adds what the removed copies had to the kept one."""

    groups: list[DuplicateChoiceIn]
    action: Literal["quarantine", "link"]
    carry_over: bool = True
    dry_run: bool = False


class CarryOverOut(BaseModel):
    drive_id: str
    name: str
    tags: list[str]
    collections: list[str]
    notes: list[str]
    checklist: list[str]
    items: list[str]
    sender: str | None
    person: str | None


class DuplicateResolveOut(BatchResultOut):
    carry_over: list[CarryOverOut]
    carry_errors: list[str]


class LinkRemoveIn(_In):
    drive_ids: list[str]
    dry_run: bool = False
