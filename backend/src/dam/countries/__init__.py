"""Country packs: what detection knows about one country's documents (payment reference
formats, where the address sits on page 1). The core pack is always on and comes first;
the others are reached only through ``get`` and ``enabled``."""

from collections.abc import Sequence

from dam.countries.core import CORE, find_ibans
from dam.countries.fi import FINLAND
from dam.countries.model import CountryPack, Finder, IdentifierSpec, ReferenceSpec

__all__ = [
    "ALL",
    "DEFAULT_COUNTRIES",
    "PACKS",
    "CountryPack",
    "Finder",
    "IdentifierSpec",
    "ReferenceSpec",
    "enabled",
    "find_ibans",
    "get",
    "signature",
]

PACKS: dict[str, CountryPack] = {FINLAND.code: FINLAND}
ALL: tuple[CountryPack, ...] = (CORE, *PACKS.values())  # every pack, the core first
DEFAULT_COUNTRIES: tuple[str, ...] = ("fi",)


def get(code: str) -> CountryPack:
    try:
        return PACKS[code]
    except KeyError:
        raise ValueError(f"unknown country pack {code!r}") from None


def enabled(codes: Sequence[str] = DEFAULT_COUNTRIES) -> list[CountryPack]:
    """The core pack, then the packs for ``codes`` in that order."""
    return [CORE, *(get(code) for code in codes)]


def signature() -> str:
    """Every pack with its version ("core:1 fi:1"): stored identifiers read with another
    signature are read again."""
    return " ".join(f"{p.code}:{p.version}" for p in ALL)
