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
# Matti Meikäläinen", "Asunto Oy Kotikatu 5"). Not before a letter, a hyphen ("AY-jäsen")
# or ".fi" (a domain).
_ENDS = re.compile(
    r"(?<!\w)(?:oyj\s+abp|oy\s+ab|oyj|abp|oy|ab|ky|ay|ry|rf|osk|kb|tmi)(?![\w-]|\.\w)"
)
_BEGINS = re.compile(r"(?<!\w)(?:tmi|(?:asunto|as\.?|kiinteisto|kiint\.?)\s*oy)(?![\w-]|\.\w)")
# where a name stops: punctuation that separates fields, or a gap of 2+ spaces (columns)
_SEPARATOR = re.compile(r"[:;,|•·()/\t]|\s{2,}")
# words that are not part of a name: the next field's label ("VESILAITOS OY Y-TUNNUS
# 0112038-9") or a label before it without a colon ("Laskuttaja Elisa Oyj"); compared
# whole, without case and a trailing ":" or "."
_STOP_WORDS = frozenset(
    "y-tunnus ytunnus alv alv-nro vat puh tel fax fo-nummer org.nr laskuttaja myyjä "
    "lähettäjä saaja vastaanottaja maksaja yhteystiedot kotipaikka avsändare mottagare "
    "säljare sender seller from".split()
)
# lower-case words that may join two parts of a name ("Fortum Power and Heat Oy")
_JOINS = frozenset({"&", "ja", "and", "och", "und"})
_NAME_WORDS = 6
# how many lines with text, above and below the line with the ID, a name is looked for in:
# a footer block puts the name a few lines above the ID
_LINES_ABOVE = 4
_LINES_BELOW = 2


def _name_word(word: str) -> bool:
    """A word that can be part of a company name: capitalised or a short number."""
    if word.isdigit() and len(word) <= 4:
        return True
    plain = word.casefold().rstrip(":.")
    if plain in _STOP_WORDS or plain.startswith(("www", "http")):
        return False
    return word[:1].isupper()


def _names_in_line(line: str) -> list[tuple[int, str]]:
    """(offset, name) of every company name in a line, recognised by its legal form."""
    folded, index = fold_indexed(line)
    seps = [(m.start(), m.end()) for m in _SEPARATOR.finditer(line)]
    found: list[tuple[int, str]] = []
    taken: list[tuple[int, int]] = []
    for m in _BEGINS.finditer(folded):
        start, end = index[m.start()], index[m.end() - 1] + 1
        stop = next((a for a, _ in seps if a >= end), len(line))
        words: list[str] = []
        for word in line[end:stop].split():
            if not (_name_word(word) or word in _JOINS) or len(words) == _NAME_WORDS:
                break
            words.append(word)
        while words and words[-1] in _JOINS:
            words.pop()
        if words:
            taken.append((start, end))
            found.append((start, " ".join([line[start:end], *words])))
    for m in _ENDS.finditer(folded):
        start, end = index[m.start()], index[m.end() - 1] + 1
        if any(a <= start < b for a, b in taken):
            continue  # the "Oy" of "Asunto Oy"
        first = max((b for _, b in seps if b <= start), default=0)
        kept: list[str] = []
        for word in reversed(line[first:start].split()):
            if not (_name_word(word) or word in _JOINS) or len(kept) == _NAME_WORDS:
                break
            kept.insert(0, word)
        while kept and kept[0] in _JOINS:
            kept.pop(0)
        if kept:
            found.append((start, " ".join([*kept, line[start:end]])))
    return found


def _near(lines: list[str], row: int, step: int, count: int) -> list[tuple[int, int]]:
    """(line number, distance) of up to ``count`` lines with text from ``row`` on, going
    by ``step``; blank lines are skipped and not counted."""
    out: list[tuple[int, int]] = []
    n = row + step
    while 0 <= n < len(lines) and len(out) < count and abs(n - row) <= 3 * count:
        if lines[n].strip():
            out.append((n, len(out) + 1))
        n += step
    return out


def ytunnus_name(text: str, value: str) -> str | None:
    """The company name printed on the line of a Y-tunnus ``value`` or the lines with text
    next to it; the closest one, a name above before one below."""
    digits, check = value.split("-")
    at = re.compile(rf"(?<!\d){digits}-{check}(?!\d)|FI ?{digits}{check}(?!\d)")
    lines = text.split("\n")
    read: dict[int, list[tuple[int, str]]] = {}
    best: tuple[tuple[int, int, int], str] | None = None
    for hit in list(at.finditer(text))[:5]:
        row = text.count("\n", 0, hit.start())
        column = hit.start() - (text.rfind("\n", 0, hit.start()) + 1)
        near = [(row, 0), *_near(lines, row, -1, _LINES_ABOVE), *_near(lines, row, 1, _LINES_BELOW)]
        for n, distance in near:
            if n not in read:
                read[n] = _names_in_line(lines[n])
            for offset, name in read[n]:
                key = (distance, n > row, abs(offset - column) if n == row else offset)
                if best is None or key < best[0]:
                    best = (key, name)
    return " ".join(best[1].split()) if best else None


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
