"""Regex detection of dates, amounts, IBAN and reference numbers in extracted text."""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

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
_RF = re.compile(r"(?<![A-Za-z0-9])RF\d{2}[0-9A-Z ]{1,21}", re.ASCII)
_DOMESTIC = re.compile(
    r"\b(?:viitenumero|viite|reference)\b\s*(?:nro\.?\s*)?:?\s*(\d+(?: \d{5})*)(?!\d|[-./]\d)",
    re.ASCII | re.IGNORECASE,
)


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


def _mod97(compact: str) -> int:
    rearranged = compact[4:] + compact[:4]
    digits = "".join(str(int(c, 36)) for c in rearranged)
    return int(digits) % 97


def valid_iban(compact: str) -> bool:
    return _mod97(compact) == 1


def _valid_rf(compact: str) -> bool:
    return 5 <= len(compact) <= 25 and _mod97(compact) == 1


def _check_731(digits: str) -> int:
    """Finnish domestic reference check digit for ``digits`` (without the check digit)."""
    total = sum(int(d) * w for d, w in zip(reversed(digits), _weights(len(digits)), strict=True))
    return (10 - total % 10) % 10


def _weights(n: int) -> list[int]:
    return [(7, 3, 1)[i % 3] for i in range(n)]


def _valid_domestic(digits: str) -> bool:
    if digits.strip("0") == "":
        return False
    return 4 <= len(digits) <= 20 and _check_731(digits[:-1]) == int(digits[-1])


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


def _references(text: str) -> str | None:
    found: list[tuple[int, str]] = []
    for m in _RF.finditer(text):
        tokens = m[0].split()  # "RF18", "5000", "1", ...
        for k in range(len(tokens), 0, -1):
            compact = "".join(tokens[:k])
            if _valid_rf(compact):
                found.append((m.start(), compact))
                break
    for m in _DOMESTIC.finditer(text):
        groups = m[1].split(" ")
        for candidate in ("".join(groups), groups[0]):
            if _valid_domestic(candidate):
                found.append((m.start(), candidate))
                break
    return min(found, key=lambda t: t[0])[1] if found else None


_LABEL_WINDOW = 40
_DUE_LABELS = re.compile(r"erapaiva|erapvm|due date|forfallodag|maksettava|\bdue\b")
# Whole words on folded text, so "subtotal" and "valisumma" are never labels.
_TOTAL_STRONG = re.compile(
    r"\b(?:yhteensa|total|totalt|maksettava|att betala|loppusumma|kokonaissumma)\b"
)
_TOTAL_WEAK = re.compile(r"\bsumma\b")


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
        reference=_references(text),
        due_date=due,
        total=total,
    )
