"""Document naming helpers."""

import re
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from dam.core.paths import nfc

CONVENTION_RE = r"^\d{8}_.+"
_DATE_PREFIX = re.compile(r"^([0-9]{4})([0-9]{2})([0-9]{2})(?=[_\- .])")


def parse_doc_date(name: str) -> date | None:
    m = _DATE_PREFIX.match(name)
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def matches_convention(name: str) -> bool:
    return re.match(CONVENTION_RE, name, re.ASCII) is not None and parse_doc_date(name) is not None


def unique_name(
    directory: Path, name: str, exclude: str | None = None, taken: Iterable[str] = ()
) -> str:
    """Return a free name in `directory` (NFC and case-insensitive comparison).

    `exclude` is an existing entry (on-disk spelling) to ignore, so a case-only
    rename of the same file does not collide with itself. `taken` lists extra
    names to treat as occupied (e.g. entries a planned batch will create). This
    only finds a free name; callers must still create or rename exclusively.
    """

    def key(n: str) -> str:
        return nfc(n).casefold()

    skip = key(exclude) if exclude is not None else None
    existing = (
        {key(e.name) for e in directory.iterdir() if key(e.name) != skip}
        if directory.exists()
        else set()
    ) | {key(t) for t in taken}
    if key(name) not in existing:
        return name
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 2
    while key(f"{stem}_{n}{suffix}") in existing:
        n += 1
    return f"{stem}_{n}{suffix}"


_MOJIBAKE_MARKS = "ÃÂâÅÄ"


def _suspicious(s: str) -> int:
    return sum(s.count(c) for c in _MOJIBAKE_MARKS)


def fix_mojibake(s: str) -> str:
    """Repair UTF-8 bytes that were decoded as Latin-1/cp1252 (``NÃ¤kymÃ¤`` ->
    ``Näkymä``). Conservative: the text is NFC-normalised first, repaired only when
    every character maps back to a byte, the bytes are valid UTF-8 and the result has
    fewer suspicious sequences. Anything else is returned (NFC-normalised) unchanged."""
    s = nfc(s)
    if not any(c in s for c in _MOJIBAKE_MARKS):
        return s
    raw = bytearray()
    for c in s:
        try:
            raw += c.encode("cp1252")
        except UnicodeEncodeError:
            try:
                raw += c.encode("latin-1")
            except UnicodeEncodeError:
                return s
    try:
        fixed = nfc(bytes(raw).decode("utf-8"))
    except UnicodeDecodeError:
        return s
    return fixed if _suspicious(fixed) < _suspicious(s) else s
