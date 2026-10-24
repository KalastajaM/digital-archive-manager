"""Who a document is for: the people in the address area of page 1.

A person is found when one of their ``match`` strings is in a line of the area, or in two
lines of it one under the other. Text is folded like rule words (case and diacritics), and
a string of eight or more letters may differ by one character, since OCR misreads one now
and then. The result is never stored: it is computed from the page-1 layout when needed,
so a change to the people list or the zone applies at once.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from dam.config import Person
from dam.extract.layout import Box, Line, Page1Layout, lines_in_zone
from dam.rules.model import fold

FUZZY_MIN_LETTERS = 8  # a match string this long may differ by one character
_SPACES = re.compile(r"\s+")


@dataclass
class PeopleContext:
    """What person detection needs: the list, the archive-wide address zone, and the
    person the owner assigned to this document (None: none)."""

    people: Sequence[Person]
    address_zone: Box
    assigned: str | None = None


def _norm(text: str) -> str:
    return _SPACES.sub(" ", fold(text)).strip()


def _within_one_edit(pattern: str, text: str) -> bool:
    """``pattern`` occurs in ``text`` with at most one inserted, deleted or changed
    character (approximate substring search; the strings are a few dozen characters)."""
    m = len(pattern)
    if m == 0:
        return True
    previous = list(range(m + 1))  # edit distance of each pattern prefix, empty text
    if previous[m] <= 1:
        return True
    for ch in text:
        current = [0]  # a match may start anywhere
        for i in range(1, m + 1):
            cost = 0 if pattern[i - 1] == ch else 1
            current.append(min(previous[i - 1] + cost, previous[i] + 1, current[i - 1] + 1))
        if current[m] <= 1:
            return True
        previous = current
    return False


def _found(pattern: str, candidates: Sequence[str]) -> bool:
    letters = sum(c.isalpha() for c in pattern)
    if any(pattern in c for c in candidates):
        return True
    return letters >= FUZZY_MIN_LETTERS and any(_within_one_edit(pattern, c) for c in candidates)


def _candidates(lines: list[Line]) -> list[str]:
    """Each line, and each two lines one under the other joined with a space."""
    ordered = sorted(lines, key=lambda ln: (ln.box[1], ln.box[0]))
    texts = [_norm(ln.text) for ln in ordered]
    out = [t for t in texts if t]
    for upper, lower, a, b in zip(ordered, ordered[1:], texts, texts[1:], strict=False):
        height = max(upper.box[3] - upper.box[1], lower.box[3] - lower.box[1])
        gap = lower.box[1] - upper.box[3]
        if a and b and gap <= 1.5 * height:
            out.append(f"{a} {b}")
    return out


def detect_people(
    layout: Page1Layout | None, zone: Sequence[float], people: Sequence[Person]
) -> list[str]:
    """The names (as in the people list, in its order) of the people found in ``zone`` of
    page 1; ``[]`` for a page that is not read or has none."""
    if layout is None or not people:
        return []
    candidates = _candidates(lines_in_zone(layout.lines, zone))
    if not candidates:
        return []
    found = []
    for person in people:
        patterns = [p for p in (_norm(m) for m in person.match) if p]
        if any(_found(p, candidates) for p in patterns):
            found.append(person.name)
    return found


def pick_person(found: list[str]) -> str | None:
    """Exactly one person found is the person; none or several: nobody."""
    return found[0] if len(found) == 1 else None
