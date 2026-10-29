"""Renaming the special folders (dam.api.schemas)."""

from typing import Literal

from pydantic import BaseModel

from dam.api.schemas.base import StrictIn


class SpecialFolderRenameIn(StrictIn):
    name: str  # the new folder name
    dry_run: bool = False


class SpecialFolderPlaceOut(BaseModel):
    place: str  # where the name (or a path under it) is stored
    how: Literal["renamed", "rebuilt", "unchanged"]
    what: str  # what happens there, in words


class SpecialFolderRenameOut(BaseModel):
    """What renaming a special folder changes (in a dry run: would change). ``batch_id``:
    the Activity batch to undo it with; None for a dry run."""

    key: Literal["inbox", "ongoing", "important", "quarantine"]
    title: str  # Inbox, Ongoing, Important or To Delete
    old: str
    new: str
    places: list[SpecialFolderPlaceOut]
    warnings: list[str]
    google_drive: bool  # the archive is on Google Drive: the rename must sync
    undo: str
    batch_id: str | None = None
