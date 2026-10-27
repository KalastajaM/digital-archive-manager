"""Settings written to settings.yaml (dam.api.schemas)."""

from pydantic import BaseModel, Field

from dam.api.schemas.base import StrictIn

# -- settings written to settings.yaml ---------------------------------------------


class Page1BackfillIn(StrictIn):
    enabled: bool


class Page1BackfillOut(BaseModel):
    enabled: bool


class Page1SpeedIn(StrictIn):
    """How many PDFs with a text layer have page 1 read per minute (1 to 6000)."""

    reads_per_minute: int


class Page1SpeedOut(BaseModel):
    reads_per_minute: int


class PersonIO(StrictIn):
    name: str
    match: list[str]


class PeopleIn(StrictIn):
    """The people list; ``address_zone`` (x0, y0, x1, y1 of page 1) is left as it is when
    omitted."""

    people: list[PersonIO]
    address_zone: list[float] | None = Field(default=None, min_length=4, max_length=4)


class PeopleOut(BaseModel):
    people: list[PersonIO]
    address_zone: list[float]
    default_address_zone: list[float]


class AssignmentsIn(StrictIn):
    """``PUT /api/assignments``: set From and/or For on documents. A field left out stays
    as it is; an explicit null clears it. ``person`` must be in the people list."""

    drive_ids: list[str] = Field(min_length=1)
    sender: str | None = None
    person: str | None = None


class SenderOut(BaseModel):
    sender: str
    count: int
