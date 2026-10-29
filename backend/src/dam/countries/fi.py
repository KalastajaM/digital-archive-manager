"""Finland: the domestic payment reference (viitenumero) and the address area of a
Finnish business letter."""

import re

from dam.checks import check_731, ytunnus_check
from dam.core.text import fold_indexed
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


# Finnish and Swedish legal forms, matched on folded text. Most end a name ("Vesilaitos
# Oy", "Nordea Bank Abp"; longest first so "Oy Ab" is read whole); a few begin one ("Tmi
# Matti Meikäläinen", "Asunto Oy Kotikatu 5"). Not before a letter or ".fi" (a domain).
_ENDS = re.compile(r"(?<!\w)(?:oyj\s+abp|oy\s+ab|oyj|abp|oy|ab|ky|ay|ry|rf|osk|kb)(?!\w|\.\w)")
_BEGINS = re.compile(r"(?<!\w)(?:tmi|(?:asunto|as\.?|kiinteisto|kiint\.?)\s*oy)(?!\w|\.\w)")
# where a name stops: punctuation that separates fields, or a gap of 2+ spaces (columns)
_SEPARATOR = re.compile(r"[:;,|•·()\t]|\s{2,}")
# words that start the next field, not the name: "VESILAITOS OY Y-TUNNUS 0112038-9"
_FIELD_WORDS = ("y-tunnus", "ytunnus", "alv", "vat", "puh", "tel", "www", "http", "fo-nummer")
_NAME_WORDS = 6
_NEAR_LINES = 2  # how far from the line with the ID a name is looked for


def _name_word(word: str) -> bool:
    """A word that can be part of a company name: capitalised, a short number or "&"."""
    if word == "&" or (word.isdigit() and len(word) <= 4):
        return True
    return word[:1].isupper() and not word.casefold().startswith(_FIELD_WORDS)


def _names_in_line(line: str) -> list[tuple[int, str]]:
    """(offset, name) of every company name in a line, recognised by its legal form."""
    folded, index = fold_indexed(line)
    found: list[tuple[int, str]] = []
    taken: list[tuple[int, int]] = []

    def segment(at: int) -> tuple[int, int]:
        """The field of the line around offset ``at``: between separators."""
        start = max((m.end() for m in _SEPARATOR.finditer(line, 0, at)), default=0)
        stop = _SEPARATOR.search(line, at)
        return start, stop.start() if stop else len(line)

    for m in _BEGINS.finditer(folded):
        start, end = index[m.start()], index[m.end() - 1] + 1
        _, stop = segment(start)
        words: list[str] = []
        for word in line[end:stop].split():
            if not _name_word(word) or len(words) == _NAME_WORDS:
                break
            words.append(word)
        taken.append((start, end))
        if words:
            found.append((start, " ".join([line[start:end], *words])))
    for m in _ENDS.finditer(folded):
        start, end = index[m.start()], index[m.end() - 1] + 1
        if any(a <= start < b for a, b in taken):
            continue  # the "Oy" of "Asunto Oy"
        first, _ = segment(start)
        words = line[first:start].split()
        kept: list[str] = []
        for word in reversed(words):
            if not _name_word(word) or len(kept) == _NAME_WORDS:
                break
            kept.insert(0, word)
        if kept:
            found.append((start, " ".join([*kept, line[start:end]])))
    return found


def ytunnus_name(text: str, value: str) -> str | None:
    """The company name printed on the line of a Y-tunnus ``value`` or the lines next to
    it; the closest one, a name above before one below."""
    digits, check = value.split("-")
    at = re.compile(rf"(?<!\d){digits}-{check}(?!\d)|FI ?{digits}{check}(?!\d)")
    lines = text.split("\n")
    best: tuple[tuple[int, int, int], str] | None = None
    for hit in list(at.finditer(text))[:5]:
        row = text.count("\n", 0, hit.start())
        column = hit.start() - (text.rfind("\n", 0, hit.start()) + 1)
        for n in range(max(0, row - _NEAR_LINES), min(len(lines), row + _NEAR_LINES + 1)):
            for offset, name in _names_in_line(lines[n]):
                key = (abs(n - row), n > row, abs(offset - column) if n == row else offset)
                if best is None or key < best[0]:
                    best = (key, name)
    return best[1] if best else None


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
    identifiers=(
        IdentifierSpec(
            "fi.ytunnus", "Business ID (Y-tunnus)", find_ytunnus, True, name=ytunnus_name
        ),
    ),
    version=2,  # 2: the company name next to a Y-tunnus
)
