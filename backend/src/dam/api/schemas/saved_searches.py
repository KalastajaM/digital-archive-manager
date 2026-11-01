"""Saved searches (dam.api.schemas)."""

from typing import Literal

from pydantic import BaseModel, Field

from dam.api.schemas.base import StrictIn


class SavedSearchIn(StrictIn):
    name: str = Field(max_length=400)
    query: str = Field(max_length=4000)
    tag_mode: Literal["all", "any"] = "all"
    replace: bool = False


class SavedSearchRenameIn(StrictIn):
    name: str = Field(max_length=400)


class SavedSearchOut(BaseModel):
    id: int
    name: str
    query: str
    tag_mode: Literal["all", "any"]


class SavedSearchRowOut(SavedSearchOut):
    count: int | None
    more: bool
    error: str | None


class SavedSearchDeletedOut(BaseModel):
    deleted: int
