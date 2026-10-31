"""Collections, notes and checklists, the Ongoing converter and export (dam.api.schemas)."""

from typing import Literal

from pydantic import BaseModel

from dam.api.schemas.responses import BatchResultOut, Mark, ResolvedOpOut
from dam.api.schemas.trays import ItemOut

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
    # the extra archive folder it lies in (None: the main folder), and whether that
    # folder is connected now (always True for the main folder)
    folder: str | None = None
    connected: bool = True


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


class MergePreviewOut(BaseModel):
    problems: list[str]  # why it cannot be merged; empty: it can
    snapshot: bool  # a snapshot is taken first (not when the merge loses nothing)


class DeleteRowOut(BaseModel):
    id: int
    name: str
    state: Literal["open", "closed"]
    files: int  # members (files and folders) it holds itself


class DeletePreviewOut(BaseModel):
    collections: list[DeleteRowOut]  # the collection first, then those inside it
    snapshot: bool  # a snapshot is taken first (not when they hold nothing)


class DeleteOut(BaseModel):
    deleted: int  # how many collections went
    batch: BatchResultOut | None
    problems: list[str]
