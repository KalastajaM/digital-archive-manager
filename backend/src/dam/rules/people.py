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
from dam.core.text import fold
from dam.extract.layout import Box, Line, Page1Layout, lines_in_zone

# The address area is an approximation of the standard (see config.DEFAULT_ADDRESS_ZONE),
# so people detection keeps its own, wider tolerance of 3 % of the page on every side.
PEOPLE_MARGIN = 0.03

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


def _boxed_candidates(lines: list[Line]) -> list[tuple[str, Box]]:
    """Each line, and each two lines one under the other joined with a space, with the box
    that holds the text."""
    ordered = sorted(lines, key=lambda ln: (ln.box[1], ln.box[0]))
    texts = [_norm(ln.text) for ln in ordered]
    out = [(t, ln.box) for t, ln in zip(texts, ordered, strict=True) if t]
    for upper, lower, a, b in zip(ordered, ordered[1:], texts, texts[1:], strict=False):
        height = max(upper.box[3] - upper.box[1], lower.box[3] - lower.box[1])
        gap = lower.box[1] - upper.box[3]
        if a and b and gap <= 1.5 * height:
            box = (
                min(upper.box[0], lower.box[0]),
                min(upper.box[1], lower.box[1]),
                max(upper.box[2], lower.box[2]),
                max(upper.box[3], lower.box[3]),
            )
            out.append((f"{a} {b}", box))
    return out


def _candidates(lines: list[Line]) -> list[str]:
    return [text for text, _ in _boxed_candidates(lines)]


def detect_people(
    layout: Page1Layout | None, zone: Sequence[float], people: Sequence[Person]
) -> list[str]:
    """The names (as in the people list, in its order) of the people found in ``zone`` of
    page 1; ``[]`` for a page that is not read or has none."""
    if layout is None or not people:
        return []
    candidates = _candidates(lines_in_zone(layout.lines, zone, PEOPLE_MARGIN))
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


def person_line(
    layout: Page1Layout | None, zone: Sequence[float], people: Sequence[Person], name: str
) -> Box | None:
    """Where in ``zone`` the person ``name`` was found: the box of the line (or of the two
    lines) that hold one of their ``match`` strings; None when not found."""
    if layout is None:
        return None
    person = next((p for p in people if p.name == name), None)
    if person is None:
        return None
    patterns = [p for p in (_norm(m) for m in person.match) if p]
    for text, box in _boxed_candidates(lines_in_zone(layout.lines, zone, PEOPLE_MARGIN)):
        if any(_found(p, [text]) for p in patterns):
            return box
    return None
