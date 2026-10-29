"""Finland: the domestic payment reference (viitenumero) and the address area of a
Finnish business letter."""

import re

from dam.checks import check_731, ytunnus_check
from dam.countries.model import CountryPack, IdentifierSpec, ReferenceSpec

_DOMESTIC = re.compile(
    r"\b(?:viitenumero|viite|reference)\b\s*(?:nro\.?\s*)?:?\s*(\d+(?: \d{5})*)(?!\d|[-./]\d)",
    re.ASCII | re.IGNORECASE,
)


def valid_reference(digits: str) -> bool:
    if digits.strip("0") == "":
        return False
    return 4 <= len(digits) <= 20 and check_731(digits[:-1]) == int(digits[-1])


def find_reference(text: str) -> list[tuple[int, str]]:
    """Domestic references after a label; a grouped number is tried whole, then its
    first group."""
    found: list[tuple[int, str]] = []
    for m in _DOMESTIC.finditer(text):
        groups = m[1].split(" ")
        for candidate in ("".join(groups), groups[0]):
            if valid_reference(candidate):
                found.append((m.start(), candidate))
                break
    return found


_YTUNNUS = re.compile(r"(?<![\dA-Za-z-])(\d{7})-(\d)(?![\d-])", re.ASCII)
_VAT = re.compile(r"(?<![A-Za-z0-9])FI ?(\d{7})(\d)(?!\d)", re.ASCII)


def find_ytunnus(text: str) -> list[str]:
    """Business IDs (Y-tunnus) with a valid check digit, also in the VAT form FI01120389,
    as ``0112038-9``, in text order, each once."""
    hits = sorted(
        (m.start(), f"{m[1]}-{m[2]}")
        for p in (_YTUNNUS, _VAT)
        for m in p.finditer(text)
        if ytunnus_check(m[1]) == int(m[2])
    )
    return list(dict.fromkeys(v for _, v in hits))


# Where the addressee sits on page 1 of a Finnish business letter (SFS 2487, window
# envelope), as fractions of an A4 page (210 x 297 mm), origin top left: about 20 mm from
# the left edge, 90 mm wide, from roughly 40 to 80 mm from the top. This is an
# approximation from memory of the standard, to be checked against real letters; lines
# are matched with a 3 % margin around the field, which absorbs most of the difference.
ADDRESS_ZONE = (0.095, 0.135, 0.524, 0.27)  # 20-110 mm across, 40-80 mm down

FINLAND = CountryPack(
    code="fi",
    name="Finland",
    references=(ReferenceSpec("fi.reference", find_reference),),
    address_zone=ADDRESS_ZONE,
    languages=("fi", "sv"),
    # only what turning Finland off changes: its address zone is also the default for now
    adds=("Payment reference (viitenumero)", "Finland example rules"),
    identifiers=(IdentifierSpec("fi.ytunnus", "Business ID (Y-tunnus)", find_ytunnus, True),),
)
