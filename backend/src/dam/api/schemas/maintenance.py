"""The Maintenance checks and what they change (dam.api.schemas)."""

from typing import Literal

from pydantic import BaseModel, Field

from dam.api.schemas.base import StrictIn
from dam.api.schemas.responses import BatchResultOut

# -- maintenance ------------------------------------------------------------


class DuplicateEstimateOut(BaseModel):
    """What the duplicate check would read, from the index alone."""

    files: int
    candidates: int
    known: int
    to_read_files: int
    to_read_bytes: int


MaintenanceKindIn = Literal[
    "duplicates",
    "empty_folders",
    "broken_links",
    "references",
    "names",
    "waiting",
    "label_clashes",
    "unfinished_copies",
    "moved",
    "remounted",
]


class MaintenanceStartIn(StrictIn):
    kind: MaintenanceKindIn
    days: int | None = None


class MaintenanceForgetOut(BaseModel):
    forgotten: int


IgnoreKindIn = Literal[
    "duplicates", "versions", "empty_folders", "broken_links", "references", "names", "moved"
]


class MaintenanceIgnoreIn(StrictIn):
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
    # broken: the target is gone; otherwise it is in an extra folder that is not
    # connected now, or that is detached
    reason: Literal["broken", "folder_not_connected", "folder_detached"]


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
    folder: str | None  # the extra folder whose To Delete it is in (None: the main one)


class WaitingOut(BaseModel):
    days: int
    items: list[WaitingFileOut]
    total: int
    total_size: int
    in_to_delete: int
    in_to_delete_size: int


class LabelClashesOut(BaseModel):
    """The archive folders whose label a top-level entry of the main folder also has."""

    items: list[str]
    total: int


class UnfinishedCopyOut(BaseModel):
    drive_id: str
    path: str
    size: int


class UnfinishedCopiesOut(BaseModel):
    """Temporary copies a move across disks left (``.dam-copy-*``); the owner removes
    them."""

    items: list[UnfinishedCopyOut]
    total: int
    total_size: int


class MovedPairOut(BaseModel):
    """A file moved or renamed outside dam: its old, missing index row (with what the
    owner gave it) and the new row the scan made where it is now. ``moves``: what would
    move to the new row, counted by kind (tags, collections, tray_items, lock, from_for,
    filing_code, summaries, fields, rule_outcomes, note, checklist). ``ambiguous``: the
    content matches more than one file, so it is only listed."""

    old_id: str
    old_path: str
    new_id: str
    new_path: str
    size: int
    same_ext: bool
    ambiguous: bool
    moves: dict[str, int]


class MovedOut(BaseModel):
    """``unhashed``: missing files with something given whose content was never read,
    so they cannot be compared; ``unreadable``: new files that could not be read;
    ``complete`` false: the check was stopped before it read every candidate."""

    items: list[MovedPairOut]
    total: int
    unhashed: int
    unreadable: int
    complete: bool


class RemountedEntryOut(BaseModel):
    """An entry dam made in ``##. Ongoing`` or ``##. Important`` whose device number
    changed: ``old_dev`` recorded, ``new_dev`` now (as text: a Windows file index does not
    fit an integer)."""

    id: int
    rel: str
    kind: Literal["link", "folder"]
    st_ino: str
    old_dev: str
    new_dev: str


class RemountedRootOut(BaseModel):
    """A publish root with entries left alone after a Drive restart. ``offered``: only the
    device number changed, the same way for each of them, so it can be taken over; else
    ``reason`` says why the root stays left alone."""

    root: str
    entries: list[RemountedEntryOut]
    offered: bool
    reason: str | None


class RemountedOut(BaseModel):
    roots: list[RemountedRootOut]


class ReadoptIn(StrictIn):
    """The roots (``##. Ongoing``, ``##. Important``) whose new device number to take over;
    ``dry_run`` lists what would be, changing nothing."""

    roots: list[str] = Field(min_length=1, max_length=10)
    dry_run: bool = False


class ReadoptOut(BaseModel):
    """What was taken over (or would be, for a dry run) and the roots that could not be.
    Database only, so not in Activity; ``undo_id`` (None for a dry run or when nothing was
    taken over) undoes it with ``POST /api/maintenance/remounted/undo``. As the answer to
    that undo: the entries put back, by root, and the ones that could not be."""

    dry_run: bool
    roots: list[RemountedRootOut]
    errors: list[str]
    undo_id: str | None = None


class ReadoptUndoIn(StrictIn):
    """The ``undo_id`` a take-over returned."""

    undo_id: str = Field(max_length=100)


class MovedChoiceIn(StrictIn):
    old: str
    new: str


class ReconnectIn(StrictIn):
    """The pairs of "Moved outside dam" to reconnect; ``dry_run`` checks and lists them
    with what would move, changing nothing."""

    pairs: list[MovedChoiceIn] = Field(max_length=10000)
    dry_run: bool = False


class ReconnectOut(BaseModel):
    """What was reconnected (or would be, for a dry run) and the pairs that could not be.
    Database only, so not in Activity; ``undo_id`` (None for a dry run or when nothing was
    reconnected) undoes it with ``POST /api/maintenance/moved/undo``. As the answer to
    that undo: the pairs put back, with what moved back, and the ones that could not be."""

    dry_run: bool
    pairs: list[MovedPairOut]
    errors: list[str]
    undo_id: str | None = None


class ReconnectUndoIn(StrictIn):
    """The ``undo_id`` a reconnect returned."""

    undo_id: str = Field(max_length=100)


class CopyJobOut(BaseModel):
    """A move across disks running in the background (or finished): files and bytes
    copied so far, the file being copied, and once it is over the batch (with its
    ``batch_id`` for Undo; ``stopped`` and ``error`` when it ended early)."""

    job_id: str
    state: Literal["running", "done", "stopped", "error"]
    version: int
    done: int
    total: int
    bytes_done: int
    bytes_total: int
    current: str | None
    elapsed_s: float
    error: str | None
    result: BatchResultOut | None = None


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
    label_clashes: LabelClashesOut | None = None
    unfinished_copies: UnfinishedCopiesOut | None = None
    moved: MovedOut | None = None
    remounted: RemountedOut | None = None


class DuplicateChoiceIn(StrictIn):
    keep: str
    others: list[str]
    # those of ``others`` replaced with a link whatever ``action`` says (one copy to To
    # Delete and another replaced with a link, in one batch)
    links: list[str] = Field(default_factory=list)
    # ``name``: the files share a name, not their content (versions of one document,
    # chosen after comparing them); ``content`` needs the check to have found them the same
    same: Literal["content", "name"] = "content"


class DuplicateResolveIn(StrictIn):
    """What to do with the copies of one or more duplicate groups: ``quarantine`` moves
    each copy in ``others`` to To Delete, ``link`` also leaves a link to ``keep`` where it
    was; a copy in a group's ``links`` is replaced with a link either way. ``carry_over``
    adds what the removed copies had to the kept one."""

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


class LinkRemoveIn(StrictIn):
    drive_ids: list[str]
    dry_run: bool = False
