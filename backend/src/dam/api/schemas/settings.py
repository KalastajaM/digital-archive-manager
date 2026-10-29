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


class IdentifierNameOut(BaseModel):
    """A business ID found on two or more documents (or named), for Settings, Senders:
    ``suggested`` is the company name printed next to it most often, ``name`` the owner's
    confirmed name, ``filled`` how many of its ``files`` have that name as From."""

    kind: str
    label: str
    value: str
    files: int
    suggested: str | None
    name: str | None
    set_at: float | None
    filled: int


class IdentifierNamesOut(BaseModel):
    names: list[IdentifierNameOut]


class IdentifierNameIn(StrictIn):
    """Name a business ID (From on every document that carries it), or clear its name
    (``null``: the senders it gave are taken back)."""

    kind: str
    value: str
    name: str | None


class IdentifierNameDoneOut(BaseModel):
    changed: int  # documents whose From changed


class CountryOut(BaseModel):
    code: str
    name: str
    enabled: bool
    adds: list[str]  # what it adds to reading documents, in plain words
    languages: list[str]  # its documents' languages


class LanguageOut(BaseModel):
    code: str
    name: str
    enabled: bool
    always: bool  # English: always on


class CountriesOut(BaseModel):
    """The country and language packs, and which are on. ``chosen``: the settings name the
    countries (else Finland is on, as before there was a choice)."""

    chosen: bool
    countries: list[CountryOut]
    languages: list[LanguageOut]


class CountriesIn(StrictIn):
    """The countries and languages to read documents with; English is always added."""

    countries: list[str]
    languages: list[str]
