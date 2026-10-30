"""Archives (profiles) and snapshots (dam.api.schemas)."""

from typing import Literal

from pydantic import BaseModel, Field

from dam.api.schemas.base import StrictIn

# -- archives (profiles) -----------------------------------------------------------


class ArchiveExtraFolderOut(BaseModel):
    label: str
    path: str
    attached: bool  # False: detached (kept in the settings, not part of the archive)


class ArchiveOut(BaseModel):
    id: str
    name: str
    color: str
    data_dir: str  # where its settings, index and logs live
    archive_root: str | None  # its archive folder (None: not set up yet)
    extra_folders: list[ArchiveExtraFolderOut] = []  # its other archive folders, if any
    configured: bool
    current: bool  # the one this window shows
    in_use_elsewhere: bool  # another dam process serves it
    port: int | None  # ... on this port, when known


class ArchivesOut(BaseModel):
    archives: list[ArchiveOut]
    current: str
    can_switch: bool  # False: this window cannot open another archive (restart instead)


class ArchiveAddIn(StrictIn):
    name: str = Field(max_length=200)
    color: str | None = Field(default=None, max_length=16)
    # build the fictional demo archive in this (new or empty) folder
    demo_folder: str | None = Field(default=None, max_length=4096)


class ArchiveUpdateIn(StrictIn):
    name: str | None = Field(default=None, max_length=200)
    color: str | None = Field(default=None, max_length=16)


class ArchiveForgetIn(StrictIn):
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


class ArchiveRevealIn(StrictIn):
    what: Literal["data", "archive", "extra"]
    label: str | None = Field(default=None, max_length=255)  # which extra folder


# -- snapshots ----------------------------------------------------------------


class SnapshotOut(BaseModel):
    name: str
    created_at: str  # ISO 8601 with the offset
    size: int  # bytes
    kind: Literal[
        "manual",
        "before-restore",
        "before-relabel",
        "before-rename",
        "before-groups",
        "before-merge",
        "before-delete",
    ]
    imported: bool  # added with Import
    revision: str | None  # the database's migration revision when it was taken
    app_version: str | None
    archive_root: str | None
    # taken for another archive folder: a restore keeps this archive's folders
    other_folder: bool
    problem: str | None  # why it cannot be restored here; None when it can


class SnapshotsOut(BaseModel):
    folder: str  # <data dir>/snapshots
    snapshots: list[SnapshotOut]  # newest first
    can_restore: bool  # False: this window cannot close and reopen the archive


class SnapshotRestoreIn(StrictIn):
    # required: the user was asked whether to keep the current state as a snapshot first
    snapshot_current: bool
    # the user confirmed restoring a snapshot of another archive folder
    other_folder_ok: bool = False


class SnapshotRestoreOut(BaseModel):
    restored: str
    safety_snapshot: SnapshotOut | None  # the snapshot of the state before the restore
    replaced_folder: str  # where the replaced settings were moved (nothing is deleted)
    kept_folders: bool  # the snapshot's folder settings were replaced by this archive's


class ArchiveFolderOut(BaseModel):
    label: str | None  # None: the main folder
    path: str
    attached: bool  # False: detached (kept in the settings, offered to attach again)
    connected: bool  # the folder can be read now
    files: int  # index rows in it, not counting missing ones


class ArchiveFoldersOut(BaseModel):
    folders: list[ArchiveFolderOut]  # the main folder first


class ArchiveFolderAddIn(StrictIn):
    label: str = Field(max_length=255)
    path: str = Field(max_length=4096)
    dry_run: bool = False


class ArchiveFolderDetachIn(StrictIn):
    forget: bool = False  # also remove its index entries (tags, notes and the rest)
    dry_run: bool = False


class ArchiveFolderAttachIn(StrictIn):
    dry_run: bool = False


class ArchiveFolderRelabelIn(StrictIn):
    label: str  # the new label
    dry_run: bool = False


class RelabelFileOut(BaseModel):
    name: str
    lines: list[int]


class RelabelOut(BaseModel):
    """What changing a folder's label changes (in a dry run: would change). ``counts``:
    index entries (``files``), journal entries (``operations``), made folders and
    maintenance entries set aside; ``files``: the settings and rule files edited, with
    the lines that change. Nothing on disk changes."""

    label: str
    new_label: str
    counts: dict[str, int]
    files: list[RelabelFileOut]
    warnings: list[str]
    restart_needed: bool = False


class FolderChangeOut(BaseModel):
    """What adding, detaching or attaching a folder did (or, in a dry run, would do)."""

    label: str
    path: str
    files: int  # rows a detach marks missing, or a forget removes
    # True when the server could not reopen the archive itself: restart ``dam serve``
    restart_needed: bool
