"""Text folding shared by every layer (database, index, rules, services)."""

import re
import unicodedata

_NON_ASCII = re.compile(r"[^\x00-\x7f]+")
# the combining marks that Western text has the most (diaeresis, ring, acute, grave, tilde,
# cedilla, caron): removed with one fast pass each before any other mark is looked for
_COMMON_MARKS = "\u0308\u030a\u0301\u0300\u0303\u0327\u030c"
_MARK_CACHE: dict[str, bool] = {}


def _is_mark(c: str) -> bool:
    found = _MARK_CACHE.get(c)
    if found is None:
        found = _MARK_CACHE[c] = unicodedata.combining(c) != 0
    return found


def fold(s: str) -> str:
    """Case- and diacritics-insensitive form: NFKD, drop combining marks, casefold.

    The text of a long document is folded again and again (every rule test), so this does
    its work in C-speed passes: plain ASCII only needs the casefold, and of the decomposed
    text only the combining marks that are really in it are cut out. The result is exactly
    that of dropping every character with a combining class."""
    if s.isascii():
        return s.casefold()
    d = unicodedata.normalize("NFKD", s)
    for mark in _COMMON_MARKS:
        d = d.replace(mark, "")
    if not d.isascii():
        for mark in {c for c in "".join(_NON_ASCII.findall(d)) if _is_mark(c)}:
            d = d.replace(mark, "")
    return d.casefold()


def fold_name(s: str) -> str:
    """A name compared the way the disk does: NFC and case-insensitive. Not the
    accent-insensitive ``fold`` that search uses."""
    return unicodedata.normalize("NFC", s).casefold()
