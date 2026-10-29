"""Regex detection of dates, amounts, IBAN and reference numbers in extracted text."""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from dam import packs
from dam.checks import IBAN_LENGTHS, valid_iban
from dam.countries import CountryPack

_CENT = Decimal("0.01")

_DATE_DMY = re.compile(r"(?<!\d)(?<!\d\.)(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\d)", re.ASCII)
_DATE_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", re.ASCII)
# day first with dashes or slashes ("15-10-2026", "15/10/2026"), never a run of digits
_DATE_DMY_SEP = re.compile(
    r"(?<!\d)(?<!\d[-/])(\d{1,2})([-/])(\d{1,2})\2(\d{4})(?![\d/-])", re.ASCII
)
# a month name, on folded text: "15 oktober 2026", "15. lokakuuta 2026", "October 15, 2026"
_DATE_DAY_MONTH = re.compile(r"(?<!\d)(\d{1,2})\.?\s+([a-z]+)\.?\s+(\d{4})(?!\d)")
_DATE_MONTH_DAY = re.compile(r"\b([a-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})(?!\d)")

_SEP = r"[ .  ]"
_AMOUNT_SUFFIX = re.compile(
    rf"(?<![\d,.])(\d{{1,3}}(?:{_SEP}\d{{3}})+|\d+),(\d{{2}})(?!\d)\s?(?:€|EUR\b)", re.ASCII
)
_AMOUNT_PREFIX = re.compile(
    r"(?:€|EUR\b)\s?(?:(\d{1,3}(?:[.  ]\d{3})+),(\d{2})|(\d{1,3}(?:,\d{3})+|\d+)[.,](\d{2}))"
    r"(?![\d]|[.,]\d)",
    re.ASCII,
)

# a country code and check digits, then what may follow; a lookahead, so a run that is no
# IBAN does not hide one that starts inside it
_IBAN = re.compile(r"(?<![A-Za-z0-9])(?=([A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}))", re.ASCII)


@dataclass
class DetectedFields:
    dates: list[date] = field(default_factory=list)
    amounts: list[Decimal] = field(default_factory=list)
    iban: str | None = None
    reference: str | None = None
    due_date: date | None = None
    total: Decimal | None = None


def _dedupe[T](found: list[tuple[int, T]]) -> list[T]:
    out: list[T] = []
    for _, value in sorted(found, key=lambda t: t[0]):
        if value not in out:
            out.append(value)
    return out


_MIN_DATE = date(1950, 1, 1)


def _max_date() -> date:
    today = date.today()
    return date(today.year + 2, today.month, min(today.day, 28))


def _dated(text: str, folded: tuple[str, list[int]] | None = None) -> list[tuple[int, date]]:
    """Dates in text order; ``folded``: ``_fold(text)`` when the caller has it already."""
    latest = _max_date()
    found: list[tuple[int, date]] = []

    def add(start: int, y: int, mo: int, d: int) -> None:
        try:
            parsed = date(y, mo, d)
        except ValueError:
            return
        if _MIN_DATE <= parsed <= latest:
            found.append((start, parsed))

    for pattern, order in ((_DATE_DMY, (3, 2, 1)), (_DATE_ISO, (1, 2, 3))):
        for m in pattern.finditer(text):
            add(m.start(), *(int(m[i]) for i in order))
    for m in _DATE_DMY_SEP.finditer(text):
        add(m.start(), int(m[4]), int(m[3]), int(m[1]))
    months = packs.active().months
    if months:
        folded_text, index = folded if folded is not None else _fold(text)
        for m in _DATE_DAY_MONTH.finditer(folded_text):
            if (mo := months.get(m[2])) is not None:
                add(index[m.start()], int(m[3]), mo, int(m[1]))
        for m in _DATE_MONTH_DAY.finditer(folded_text):
            if (mo := months.get(m[1])) is not None:
                add(index[m.start()], int(m[3]), mo, int(m[2]))
    return sorted(found, key=lambda t: t[0])


def _dates(text: str) -> list[date]:
    return _dedupe(_dated(text))


def _priced(text: str) -> list[tuple[int, Decimal]]:
    found: list[tuple[int, Decimal]] = []
    for m in _AMOUNT_SUFFIX.finditer(text):
        whole = re.sub(_SEP, "", m[1])
        found.append((m.start(), Decimal(f"{whole}.{m[2]}").quantize(_CENT)))
    for m in _AMOUNT_PREFIX.finditer(text):
        if m[1] is not None:  # dot or space thousands, decimal comma: "€ 1.234,56"
            whole, cents = re.sub(_SEP, "", m[1]), m[2]
        else:
            whole, cents = m[3].replace(",", ""), m[4]
        found.append((m.start(), Decimal(f"{whole}.{cents}").quantize(_CENT)))
    return sorted(found, key=lambda t: t[0])


def _amounts(text: str) -> list[Decimal]:
    return _dedupe(_priced(text))


def _iban_end(text: str, start: int, length: int) -> int:
    """Where an IBAN of ``length`` characters (spaces between them) starting at ``start``
    ends in ``text``."""
    pos, seen = start, 0
    while seen < length:
        if text[pos] != " ":
            seen += 1
        pos += 1
    return pos


def _iban(text: str) -> str | None:
    """The first valid IBAN of a SEPA country: its country's length, and no letter or
    digit right after it."""
    for m in _IBAN.finditer(text):
        compact = m[1].replace(" ", "")
        length = IBAN_LENGTHS.get(compact[:2])
        if length is None or len(compact) < length or not valid_iban(compact[:length]):
            continue
        end = _iban_end(text, m.start(), length)
        if end < len(text) and text[end].isalnum():
            continue
        return compact[:length]
    return None


def _references(text: str, packs: Sequence[CountryPack]) -> str | None:
    """The first payment reference in the text, of any format the packs know."""
    found = [hit for pack in packs for spec in pack.references for hit in spec.find(text)]
    return min(found, key=lambda t: t[0])[1] if found else None


_LABEL_WINDOW = 40


def _fold(text: str) -> tuple[str, list[int]]:
    """Fold for label matching (NFKD, no combining marks, casefold).

    Returns the folded text and, for each folded character, the index of the
    original character it came from.
    """
    chars: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        for out in unicodedata.normalize("NFKD", ch):
            if unicodedata.combining(out):
                continue
            for c in out.casefold():
                chars.append(c)
                index.append(i)
    return "".join(chars), index


def _label_ends(folded: str, index: list[int], text: str, labels: re.Pattern[str]) -> list[int]:
    """Original-text offsets just after each label match (trailing combining marks included)."""
    return [index[m.end()] if m.end() < len(index) else len(text) for m in labels.finditer(folded)]


def _first_in_window[T](end: int, candidates: list[tuple[int, T]]) -> T | None:
    for start, value in candidates:
        if 0 <= start - end <= _LABEL_WINDOW:
            return value
    return None


# Limitation (by design): in a table whose header row holds the labels and whose
# values sit on a later row, the value is usually beyond the window and is missed.


def detect_fields(text: str) -> DetectedFields:
    profile = packs.active()
    folded, index = _fold(text)
    dated = _dated(text, (folded, index))
    priced = _priced(text)
    amounts = _dedupe(priced)

    due = None
    for end in _label_ends(folded, index, text, profile.due_labels):
        due = _first_in_window(end, dated)
        if due is not None:
            break

    # Totals come after subtotals: last strong label wins, else first weak, else largest.
    strong = [
        v
        for end in _label_ends(folded, index, text, profile.total_strong)
        if (v := _first_in_window(end, priced)) is not None
    ]
    weak = [
        v
        for end in _label_ends(folded, index, text, profile.total_weak)
        if (v := _first_in_window(end, priced)) is not None
    ]
    total = strong[-1] if strong else weak[0] if weak else max(amounts, default=None)
    return DetectedFields(
        dates=_dedupe(dated),
        amounts=amounts,
        iban=_iban(text),
        reference=_references(text, profile.countries),
        due_date=due,
        total=total,
    )
