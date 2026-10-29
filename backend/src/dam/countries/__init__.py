"""Country packs: what detection knows about one country's documents (payment reference
formats, where the address sits on page 1). The core pack is always on and comes first;
the others are reached only through ``get`` and ``enabled``."""

from collections.abc import Sequence

from dam.countries.core import CORE
from dam.countries.fi import FINLAND
from dam.countries.model import CountryPack, Finder, ReferenceSpec

__all__ = ["DEFAULT_COUNTRIES", "PACKS", "CountryPack", "Finder", "ReferenceSpec", "enabled", "get"]

PACKS: dict[str, CountryPack] = {FINLAND.code: FINLAND}
DEFAULT_COUNTRIES: tuple[str, ...] = ("fi",)


def get(code: str) -> CountryPack:
    try:
        return PACKS[code]
    except KeyError:
        raise ValueError(f"unknown country pack {code!r}") from None


def enabled(codes: Sequence[str] = DEFAULT_COUNTRIES) -> list[CountryPack]:
    """The core pack, then the packs for ``codes`` in that order."""
    return [CORE, *(get(code) for code in codes)]
