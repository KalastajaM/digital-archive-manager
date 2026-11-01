"""Relatives: the files a document belongs with (dam.api.schemas)."""

from typing import Literal

from pydantic import BaseModel

from dam.api.schemas.base import StrictIn

RelativeKind = Literal[
    "reference", "sender", "business_id", "collection", "tag", "folder", "iban", "person"
]


class RelativeLinkOut(BaseModel):
    kind: RelativeKind
    value: str
    weight: float


class RelativeOut(BaseModel):
    drive_id: str
    path: str
    name: str
    ext: str | None
    folder: str
    score: float
    links: list[RelativeLinkOut]
    same_month: bool
    in_inbox: bool


class RelativeCommonOut(BaseModel):
    """A value shared with some of the relatives, and how many of them share it."""

    kind: RelativeKind
    value: str
    count: int


class RelativeDismissedOut(BaseModel):
    drive_id: str
    path: str
    name: str


class RelativesOut(BaseModel):
    drive_id: str
    relatives: list[RelativeOut]
    common: list[RelativeCommonOut]
    total: int
    hidden: int


class RelativesDismissedOut(BaseModel):
    dismissed: list[RelativeDismissedOut]


class RelativeMarkIn(StrictIn):
    """The other file of a pair marked (or no longer marked) "Not related"."""

    drive_id: str


class FileTagApplyIn(StrictIn):
    """One tag put on several files as one undoable step."""

    drive_ids: list[str]
    tag: str


class LinkThereBody(StrictIn):
    """Make a link to this file in each of these folders, as one batch (one Undo)."""

    drive_id: str
    folders: list[str]


class VersionFileOut(BaseModel):
    drive_id: str
    path: str
    name: str
    mtime: float | None
    latest: bool
    in_archive: bool


class VersionStayingOut(BaseModel):
    name: str
    reason: str


class VersionsOut(BaseModel):
    files: list[VersionFileOut]
    latest: str | None
    hidden: int
    folder: str | None
    movable: list[str]
    staying: list[VersionStayingOut]
    blocked: str | None
