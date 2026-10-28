"""First-run setup, only while no archive folder is configured (dam.api.schemas)."""

from pydantic import BaseModel, Field

from dam.api.schemas.base import StrictIn
from dam.api.schemas.responses import BatchResultOut, ResolvedOpOut

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


class SetupPathIn(StrictIn):
    path: str = Field(max_length=4096)


class ChooseFolderIn(StrictIn):
    start: str | None = Field(default=None, max_length=4096)  # where the dialog opens


class ChooseFolderOut(BaseModel):
    path: str | None = None  # the chosen folder, absolute
    cancelled: bool = False
    unavailable: str | None = None  # why no dialog could be shown (a plain message)


class LayoutRowIn(StrictIn):
    key: str | None = Field(default=None, max_length=64)
    name: str = Field(max_length=255)


class SpecialNamesIn(StrictIn):
    inbox: str = Field(max_length=255)
    ongoing: str = Field(max_length=255)
    important: str = Field(max_length=255)
    quarantine: str = Field(max_length=255)


class LayoutIn(StrictIn):
    """The layout the user chose and edited: which template it came from (ties rows to
    its example rules), the numbering and the rows. Inside the running app the special
    folders are the configured ones; in first-run setup ``special`` names them."""

    template: str | None = Field(default=None, max_length=64)
    numbered: bool = True
    folders: list[LayoutRowIn] = Field(max_length=100)
    special: SpecialNamesIn | None = None


class SetupLayoutPreviewIn(StrictIn):
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


class SetupIn(StrictIn):
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


class FolderPathIn(StrictIn):
    path: str = Field(default="", max_length=4096)


class NewFolderIn(StrictIn):
    """Make folder ``name`` inside ``parent`` ("" = at the top of the archive)."""

    parent: str = Field(default="", max_length=4096)
    name: str = Field(max_length=255)
