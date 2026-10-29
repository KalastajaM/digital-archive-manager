"""Regex detection of dates, amounts, IBAN and reference numbers in extracted text."""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from dam import countries, languages
from dam.checks import valid_iban
from dam.countries import CountryPack

_CENT = Decimal("0.01")

_DATE_DMY = re.compile(r"(?<!\d)(?<!\d\.)(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\d)", re.ASCII)
_DATE_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", re.ASCII)

_SEP = r"[ .  ]"
_AMOUNT_SUFFIX = re.compile(
    rf"(?<![\d,.])(\d{{1,3}}(?:{_SEP}\d{{3}})+|\d+),(\d{{2}})(?!\d)\s?(?:€|EUR\b)", re.ASCII
)
_AMOUNT_PREFIX = re.compile(
    r"(?:€|EUR\b)\s?(\d{1,3}(?:,\d{3})+|\d+)[.,](\d{2})(?![\d]|[.,]\d)", re.ASCII
)

_IBAN = re.compile(r"(?<![A-Za-z0-9])FI\d{2}(?: ?\d{4}){3} ?\d{2}(?!\d)", re.ASCII)


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


def _dated(text: str) -> list[tuple[int, date]]:
    latest = _max_date()
    found: list[tuple[int, date]] = []
    for pattern, order in ((_DATE_DMY, (3, 2, 1)), (_DATE_ISO, (1, 2, 3))):
        for m in pattern.finditer(text):
            y, mo, d = (int(m[i]) for i in order)
            try:
                parsed = date(y, mo, d)
            except ValueError:
                continue
            if _MIN_DATE <= parsed <= latest:
                found.append((m.start(), parsed))
    return sorted(found, key=lambda t: t[0])


def _dates(text: str) -> list[date]:
    return _dedupe(_dated(text))


def _priced(text: str) -> list[tuple[int, Decimal]]:
    found: list[tuple[int, Decimal]] = []
    for m in _AMOUNT_SUFFIX.finditer(text):
        whole = re.sub(_SEP, "", m[1])
        found.append((m.start(), Decimal(f"{whole}.{m[2]}").quantize(_CENT)))
    for m in _AMOUNT_PREFIX.finditer(text):
        whole = m[1].replace(",", "")
        found.append((m.start(), Decimal(f"{whole}.{m[2]}").quantize(_CENT)))
    return sorted(found, key=lambda t: t[0])


def _amounts(text: str) -> list[Decimal]:
    return _dedupe(_priced(text))


def _iban(text: str) -> str | None:
    for m in _IBAN.finditer(text):
        compact = m[0].replace(" ", "")
        if valid_iban(compact):
            return compact
    return None


def _references(text: str, packs: Sequence[CountryPack]) -> str | None:
    """The first payment reference in the text, of any format the packs know."""
    found = [hit for pack in packs for spec in pack.references for hit in spec.find(text)]
    return min(found, key=lambda t: t[0])[1] if found else None


_LABEL_WINDOW = 40
_LANGUAGES = languages.enabled()
_DUE_LABELS = languages.label_pattern(w for p in _LANGUAGES for w in p.due_labels)
# Whole words on folded text, so "subtotal" and "valisumma" are never labels.
_TOTAL_STRONG = languages.label_pattern(
    (w for p in _LANGUAGES for w in p.total_strong), whole_words=True
)
_TOTAL_WEAK = languages.label_pattern(
    (w for p in _LANGUAGES for w in p.total_weak), whole_words=True
)


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
    folded, index = _fold(text)
    dated = _dated(text)
    priced = _priced(text)
    amounts = _dedupe(priced)

    due = None
    for end in _label_ends(folded, index, text, _DUE_LABELS):
        due = _first_in_window(end, dated)
        if due is not None:
            break

    # Totals come after subtotals: last strong label wins, else first weak, else largest.
    strong = [
        v
        for end in _label_ends(folded, index, text, _TOTAL_STRONG)
        if (v := _first_in_window(end, priced)) is not None
    ]
    weak = [
        v
        for end in _label_ends(folded, index, text, _TOTAL_WEAK)
        if (v := _first_in_window(end, priced)) is not None
    ]
    total = strong[-1] if strong else weak[0] if weak else max(amounts, default=None)
    return DetectedFields(
        dates=_dedupe(dated),
        amounts=amounts,
        iban=_iban(text),
        reference=_references(text, countries.enabled()),
        due_date=due,
        total=total,
    )
