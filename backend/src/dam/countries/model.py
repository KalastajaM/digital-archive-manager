"""What a country pack holds. Packs are data: they are reached through ``dam.countries``,
never imported one by one."""

from collections.abc import Callable
from dataclasses import dataclass

# (offset in the text, compact value) for each match, in text order
Finder = Callable[[str], list[tuple[int, str]]]


@dataclass(frozen=True)
class ReferenceSpec:
    """A payment reference format: ``kind`` is namespaced by its pack ("fi.reference")."""

    kind: str
    find: Finder


@dataclass(frozen=True)
class IdentifierSpec:
    """Values in a document that name an organisation or an account: ``kind`` namespaced
    by its pack ("fi.ytunnus"), ``label`` for people, ``find`` the normalised values in
    text order, each once. ``names_sender``: a value belongs to one organisation. ``name``:
    the organisation's name as printed next to a value in a text, or None."""

    kind: str
    label: str
    find: Callable[[str], list[str]]
    names_sender: bool
    name: Callable[[str, str], str | None] | None = None


@dataclass(frozen=True)
class CountryPack:
    code: str  # "core", or ISO 3166-1 alpha-2 in lower case ("fi")
    name: str
    references: tuple[ReferenceSpec, ...] = ()
    # where the addressee sits on page 1 (x0, y0, x1, y1 as fractions of the page); None:
    # the pack has no standard for it
    address_zone: tuple[float, float, float, float] | None = None
    languages: tuple[str, ...] = ()  # the languages of its documents, most likely first
    # what the pack adds to reading documents, in plain words (Settings lists them)
    adds: tuple[str, ...] = ()
    identifiers: tuple[IdentifierSpec, ...] = ()
    # raise when what the pack finds changes: stored identifiers are read again
    version: int = 1
