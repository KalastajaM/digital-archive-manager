"""The part of detection that is not tied to a country: always on."""

import re

from dam.checks import valid_rf
from dam.countries.model import CountryPack, ReferenceSpec

_RF = re.compile(r"(?<![A-Za-z0-9])RF\d{2}[0-9A-Z ]{1,21}", re.ASCII)


def find_rf(text: str) -> list[tuple[int, str]]:
    """RF creditor references (ISO 11649), the longest valid run of each match."""
    found: list[tuple[int, str]] = []
    for m in _RF.finditer(text):
        tokens = m[0].split()  # "RF18", "5000", "1", ...
        for k in range(len(tokens), 0, -1):
            compact = "".join(tokens[:k])
            if valid_rf(compact):
                found.append((m.start(), compact))
                break
    return found


CORE = CountryPack(
    code="core",
    name="Core",
    references=(ReferenceSpec("core.rf", find_rf),),
)
