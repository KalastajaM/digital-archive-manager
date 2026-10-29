"""The answers of the core screens: files, batches, inbox, browse, search, activity and status
(dam.api.schemas)."""

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from dam.api.schemas.base import StrictIn
from dam.api.schemas.rules import AreaOut, RuleDraftOut, RuleErrorOut
from dam.ops.model import OpKind

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
    page1: "Page1SummaryOut"  # how far the page-1 pass has come
    identifiers: "IdentifiersSummaryOut"  # how far business IDs, IBANs and domains are read


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


class MarkBody(StrictIn):
    """``POST /api/marks/{action}``: ``group`` ("Houses/Hillside") only for important."""

    drive_ids: list[str]
    group: str | None = None


class UnlockIn(StrictIn):
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
    # the extra archive folder it lies in (None: the main folder), and whether that
    # folder is connected now (always True for the main folder)
    folder: str | None = None
    connected: bool = True


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


class FileSummaryIn(StrictIn):
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
    """A filing code found for a file: by its inbox folder, a pen mark, a QR sticker, or
    given by the owner in the app (``assigned``). ``raw``: what was read (pen, QR);
    ``unclear``: the reading is uncertain; ``overridden``: an assigned code replaces it,
    so it sets nothing."""

    code: str
    via: Literal["folder", "pen", "qr", "assigned"]
    raw: str | None
    unclear: bool
    overridden: bool


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


class FileTagsIn(StrictIn):
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


class TagSnapshotModel(StrictIn):
    name: str
    pinned_at: float | None = None
    group_id: int | None = None
    last_used_at: float | None = None
    drive_ids: list[str] = Field(default_factory=list)


class TagUnlinkModel(StrictIn):
    name: str
    drive_ids: list[str]


class TagUndoModel(StrictIn):
    """How to put a tag change back; sent to ``POST /api/tags/undo`` unchanged."""

    drop: list[str] = Field(default_factory=list)
    detach: list[TagUnlinkModel] = Field(default_factory=list)
    restore: list[TagSnapshotModel] = Field(default_factory=list)


class TagChangeOut(BaseModel):
    """The result of a tag change and how to undo it."""

    message: str
    undo: TagUndoModel


class TagNameIn(StrictIn):
    name: str = Field(max_length=200)


class TagRenameIn(StrictIn):
    name: str = Field(max_length=200)
    new_name: str = Field(max_length=200)


class TagMergeIn(StrictIn):
    sources: list[str] = Field(max_length=200)
    into: str = Field(max_length=200)
    dry_run: bool = False


class TagMergePlanOut(BaseModel):
    into: str
    gains: int
    removes: list[str]
    message: str
    undo: TagUndoModel | None


class TagPinIn(StrictIn):
    names: list[str] = Field(max_length=200)
    pinned: bool


class TagGroupSetIn(StrictIn):
    names: list[str] = Field(max_length=200)
    group_id: int | None


class TagGroupNameIn(StrictIn):
    name: str = Field(max_length=200)


class TagGroupCreatedOut(BaseModel):
    id: int
    name: str


class TagGroupDeletedOut(BaseModel):
    name: str
    members: list[str]
    message: str


class TagGroupRestoreIn(StrictIn):
    name: str = Field(max_length=200)
    members: list[str] = Field(max_length=2000)


class ScanFieldOut(BaseModel):
    kind: Literal[
        "doc_date", "due_date", "date", "total", "amount", "iban", "reference", "payee", "custom"
    ]
    label: str | None  # the name of a "custom" field, else null
    value: str  # normalised for its kind: ISO date, "84.20", compact IBAN


class ScanFieldIn(StrictIn):
    kind: Literal[
        "doc_date", "due_date", "date", "total", "amount", "iban", "reference", "payee", "custom"
    ]
    label: str | None = None
    value: str


class ScanFieldsIn(StrictIn):
    fields: list[ScanFieldIn]


class ScanFieldsOut(BaseModel):
    fields: list[ScanFieldOut]
    edited: bool  # a saved list (else the detected one)


class IdentifierOut(BaseModel):
    kind: str  # "fi.ytunnus", "core.iban", "core.domain"
    label: str  # "Business ID (Y-tunnus)"
    value: str
    others: int  # other files there that carry it


class IdentifiersOut(BaseModel):
    """What the enabled packs found in the file's current content: business IDs first,
    then IBANs, then domains."""

    identifiers: list[IdentifierOut]


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
    # copy_across: the file's size, and whether it is in the cloud only (downloaded first)
    size: int | None = None
    cloud_only: bool | None = None
    # copy_across of a folder move: "present" when the destination already holds the file
    method: str | None = None


class BatchResultOut(BaseModel):
    batch_id: str
    dry_run: bool
    done: list[ResolvedOpOut]
    failed: ResolvedOpOut | None
    error: str | None
    index_error: str | None
    stopped: bool | None = None  # a background move ended early on Stop (else null)
    # a move across disks started in the background: poll /api/browse/move/jobs/{job_id};
    # this answer is empty and the job's result is the batch
    job_id: str | None = None
    # what a finished batch did, in words, when it says it itself (a folder moved across
    # disks); else null
    message: str | None = None


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
    # the extra archive folder it lies in (None: the main folder), and whether that
    # folder is connected now (always True for the main folder)
    folder: str | None = None
    connected: bool = True


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
    # the extra archive folder it lies in (None: the main folder), and whether that
    # folder is connected now (always True for the main folder)
    folder: str | None = None
    connected: bool = True


class FileNowOut(BaseModel):
    """Where the file an Activity op names is now, from the index."""

    # here: where the op left it; moved: elsewhere since; to_delete: marked for deletion
    # since; missing: deleted, or moved outside dam and not reconnected
    state: Literal["here", "moved", "to_delete", "missing"]
    path: str | None  # None when missing
    drive_id: str | None
    is_dir: bool


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
    # Activity only: where the op's file is now (None: the op names no file, or a
    # recovery row)
    file_now: FileNowOut | None = None


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


class IdentifierFoundOut(BaseModel):
    label: str  # "business IDs", "IBANs", "web or mail domains"
    count: int  # files there whose current content carries one


class IdentifiersProgressOut(BaseModel):
    """The identifiers pass: indexed documents whose text was read with the current
    packs, of all with text."""

    read: int
    total: int


class IdentifiersSummaryOut(IdentifiersProgressOut):
    """With how many files carry each kind (the enabled countries' only)."""

    found: list[IdentifierFoundOut]


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


class Page1SummaryOut(Page1ProgressOut):
    with_text: int  # of those read, how many have text on page 1


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
    identifiers: IdentifiersProgressOut | None = None  # None only from the setup-mode server
    # False only from the setup-mode server (then only ``archive`` and ``profiles_count``
    # are set besides it): no archive folder yet
    configured: bool = True
    archive: ActiveArchiveOut | None = None
    profiles_count: int = 1
