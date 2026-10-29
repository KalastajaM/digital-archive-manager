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
class CountryPack:
    code: str  # "core", or ISO 3166-1 alpha-2 in lower case ("fi")
    name: str
    references: tuple[ReferenceSpec, ...] = ()
    # where the addressee sits on page 1 (x0, y0, x1, y1 as fractions of the page); None:
    # the pack has no standard for it
    address_zone: tuple[float, float, float, float] | None = None
    languages: tuple[str, ...] = ()  # the languages of its documents, most likely first
