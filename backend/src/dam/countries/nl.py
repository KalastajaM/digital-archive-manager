"""The Netherlands: the betalingskenmerk, the btw-id, the KvK-nummer and the RSIN, and the
address area of a Dutch letter. The sources are listed in docs/reference.md, Countries
and languages.

The label words below are not from a source: they are the usual ones, to be checked on
real Dutch letters and bills."""

import re

from dam.checks import elfproef, mod97_10, valid_kenmerk
from dam.countries.model import CountryPack, IdentifierSpec, ReferenceSpec

_KENMERK = re.compile(
    r"\b(?:betalingskenmerk|betaalkenmerk|kenmerk)\b\s*:?\s*(\d+(?: \d+)*)(?!\d)",
    re.ASCII | re.IGNORECASE,
)
# "Ons kenmerk" and "Uw kenmerk" name a letter, not a payment
_LETTER_REF = re.compile(r"\b(?:ons|onze|uw)\s+$", re.IGNORECASE)


def find_kenmerk(text: str) -> list[tuple[int, str]]:
    """Betalingskenmerken after a label; a grouped number is tried whole, then without its
    last groups (the next number on the line may follow it)."""
    found: list[tuple[int, str]] = []
    for m in _KENMERK.finditer(text):
        if _LETTER_REF.search(text, max(0, m.start() - 8), m.start()):
            continue
        # the grouped number from its start, at most 16 digits (no kenmerk is longer)
        prefixes, compact = [], ""
        for group in m[1].split(" "):
            compact += group
            if len(compact) > 16:
                break
            prefixes.append(compact)
        for candidate in reversed(prefixes):
            if valid_kenmerk(candidate):
                found.append((m.start(), candidate))
                break
    return found


def _once(values) -> list[str]:
    return list(dict.fromkeys(values))


def _rsin(nine: str) -> bool:
    """Nine digits that can be an RSIN: the elfproef, and the start RSINs have (00, or 80
    to 89). The start is a heuristic, not checked against an RSIN numbering source: the
    Belastingdienst states it only in passing ("Specificatie Betalingskenmerk bepaling"
    1.5). The BSN, a personal number, passes the same elfproef; the start leaves most BSNs
    out, not all (a BSN may start with 0)."""
    return elfproef(nine) and nine.startswith(("00", "8"))


_BTW = re.compile(r"(?<![A-Za-z0-9])NL[ .]?((?:\d[ .]?){9})B[ .]?(\d{2})(?!\d)", re.ASCII)


def find_btw(text: str) -> list[str]:
    """Btw-identificatienummers (NL + 9 digits + B + 2 digits) as ``NL002455799B11``.
    Valid when the nine digits are an RSIN (legal entities) or the whole number passes ISO
    7064 mod 97-10 (sole proprietors since 2020), as python-stdnum checks it. Before 2020 a
    sole proprietor's number held their BSN; those are not read."""
    out = []
    for m in _BTW.finditer(text):
        nine = re.sub(r"\D", "", m[1])
        value = f"NL{nine}B{m[2]}"
        if nine.strip("0") and (_rsin(nine) or mod97_10(value) == 1):
            out.append(value)
    return _once(out)


_KVK_LABEL = re.compile(
    r"\b(?:kvk|k\.v\.k\.?|kamer\s+van\s+koophandel|handelsregister)(?![a-z])", re.IGNORECASE
)
_EIGHT = re.compile(r"(?<![\d.,/-])\d{8}(?!\d|[.,/-]\d)", re.ASCII)
_KVK_WINDOW = 40  # as the labels of due dates and totals (rules/fields.py)


def find_kvk(text: str) -> list[str]:
    """KvK-nummers: 8 digits with no check digit, so only the first one that starts within
    40 characters after a label."""
    out = []
    for label in _KVK_LABEL.finditer(text):
        # no end position: the lookahead must see the digit after an 8-digit run
        m = _EIGHT.search(text, label.end())
        if m is not None and m.start() - label.end() <= _KVK_WINDOW:
            out.append(m[0])
    return _once(out)


# not after "BSN/" ("BSN/RSIN: ..." is a personal number or a company's, unknown which)
_RSIN = re.compile(
    r"(?<!BSN/)(?<!BSN /)\bRSIN(?:-?nummer|-?nr\.?)?\s*:?\s*((?:\d[ .]?){8}\d)(?!\d)",
    re.ASCII | re.IGNORECASE,
)


def find_rsin(text: str) -> list[str]:
    """RSINs right after the label "RSIN". A nine-digit number without it is never read:
    the BSN shares the check."""
    return _once(v for m in _RSIN.finditer(text) if _rsin(v := re.sub(r"\D", "", m[1])))


# Where the addressee sits on page 1 of a Dutch letter, as fractions of an A4 page (210 x
# 297 mm), origin top left: 15 to 115 mm across, 40 to 95 mm down. An estimate, to be
# checked on real letters:
# - PostNL, Vormgevingsvoorwaarden 2026 (pages 4 to 9): on the envelope the address zone is
#   at least 40 mm below the top and 15 mm from the other edges. A letter sits a few mm
#   inside its envelope, so that is the outer bound.
# - Left-window practice (not PostNL): the LaTeX letter class that follows NEN 1026 puts
#   the address 33 mm from the left, its first line 59 mm down; retail EA5/6 envelopes
#   have a 110 x 40 mm window on the left; Postbird's "Adrespositie (NL)" drawing puts its
#   address box at 20 to 95 mm across and about 56 to 76 mm down.
# - The right edge stays at 115 mm so the reference block that Dutch letters print to the
#   right of the address is left out.
# People matching adds its own 3 % margin around it.
ADDRESS_ZONE = (0.071, 0.135, 0.548, 0.320)

NETHERLANDS = CountryPack(
    code="nl",
    name="Netherlands",
    references=(ReferenceSpec("nl.kenmerk", find_kenmerk),),
    address_zone=ADDRESS_ZONE,
    languages=("nl",),
    adds=(
        "Payment reference (betalingskenmerk)",
        "KvK-nummer, btw-id and RSIN",
        "Address area of a Dutch letter, when Finland is off",
        "Netherlands example rules",
    ),
    identifiers=(
        IdentifierSpec("nl.btw", "VAT ID (btw-id)", find_btw, True),
        IdentifierSpec("nl.kvk", "Chamber of Commerce number (KvK-nummer)", find_kvk, True),
        IdentifierSpec("nl.rsin", "Legal entity number (RSIN)", find_rsin, True),
    ),
)
