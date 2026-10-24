"""Draft a filing rule from a document that was just filed: pure code, no DB.

The words come from the document's text only (never its file name, which says how it was
scanned, not who it is from). Words that appear in many filed documents are dropped, the
rarest remaining word is ticked, and the folder and name are turned into patterns."""

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import PurePosixPath

from dam.core.paths import nfc
from dam.rules.engine import check_template, clean_stem
from dam.rules.model import RESERVED_IDS
from dam.rules.similar import _tokens

MAX_WORDS = 6
MAX_FREQUENCY = 0.3  # share of filed documents containing a word; above it, it is noise


@dataclass
class DraftWord:
    word: str
    ticked: bool


@dataclass
class RuleDraft:
    id: str
    words: list[DraftWord]
    folder: str | None
    name: str | None
    tags: list[str]
    tray: str | None
    payee: str | None


@dataclass
class ZoneDraftArea:
    """One box of a zone draft: the page-1 ``lines`` in it and its candidate ``words``
    (one ticked)."""

    box: tuple[float, float, float, float]
    words: list[DraftWord]
    lines: list[str]


@dataclass
class ZoneDraftPicture:
    """One picture box of a zone draft: the crop kept for it (``image``, a path under the
    rules' ``areas`` folder), its size and a base64 PNG to show."""

    box: tuple[float, float, float, float]
    image: str
    width: int
    height: int
    png: str


@dataclass
class ZoneDraft(RuleDraft):
    """A draft made from boxes on page 1: the rule's ``when`` is ``folder_is`` (the inbox)
    and one ``zone`` per box, each with its one ticked word. ``sender`` is the sender the
    rule identifies; ``place_above`` the learned rule the new one goes directly above when
    it is saved (a learned rule that matches the document already), else None. The
    draft's own ``words`` are empty: the words are per area."""

    zones: list[ZoneDraftArea] = field(default_factory=list)
    pictures: list[ZoneDraftPicture] = field(default_factory=list)
    folder_is: str | None = None
    sender: str | None = None
    place_above: str | None = None


def _literal(s: str) -> str:
    return s.replace("{", "{{").replace("}", "}}")


def folder_pattern(folder: str, doc_date: date | None, person: str | None = None) -> str:
    """``folder`` as a template: a part that is the year becomes ``{year}``, a part that is
    the document's person becomes ``{person}``."""
    year = str(doc_date.year) if doc_date else None
    who = nfc(person).casefold() if person else None

    def part(p: str) -> str:
        if year and p == year:
            return "{year}"
        if who and nfc(p).casefold() == who:
            return "{person}"
        return _literal(p)

    return "/".join(part(p) for p in folder.split("/"))


def name_pattern(filed_stem: str, original_stem: str, doc_date: date | None) -> str:
    if doc_date:
        prefix = f"{doc_date:%Y%m%d}"
        if filed_stem.startswith(prefix + "_"):
            rest = filed_stem[len(prefix) + 1 :]
            tail = "{stem}" if rest and rest == clean_stem(original_stem) else _literal(rest)
            return "{doc_date:%Y%m%d}_" + tail
    return _literal(filed_stem)


def _slug(word: str) -> str:
    s = unicodedata.normalize("NFKD", word).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "rule"


def _unique(base: str, taken: set[str]) -> str:
    """``base``, or ``base-2``, ``base-3``... : never a taken or a reserved id."""
    taken = taken | RESERVED_IDS
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def filed_patterns(
    filed_name: str | None,
    filed_folder: str | None,
    original_name: str,
    doc_date: date | None,
    person: str | None = None,
) -> tuple[str | None, str | None]:
    """The folder and name templates for a document that is filed already (each None
    without one)."""
    folder = folder_pattern(filed_folder, doc_date, person) if filed_folder else None
    name = (
        name_pattern(PurePosixPath(filed_name).stem, PurePosixPath(original_name).stem, doc_date)
        if filed_name
        else None
    )
    for template in (folder, name):
        if template is not None:
            check_template(template)
    return folder, name


def picture_draft(
    *,
    sender: str | None,
    filed_name: str | None,
    filed_folder: str | None,
    doc_date: date | None,
    tags: list[str],
    taken_ids: set[str],
    person: str | None = None,
) -> RuleDraft:
    """The start of a rule made from picture areas only: it has no words, so its id comes
    from the sender (else "picture")."""
    folder, name = filed_patterns(filed_name, filed_folder, "", doc_date, person)
    return RuleDraft(
        id=_unique(_slug(sender or "picture"), taken_ids),
        words=[],
        folder=folder,
        name=name,
        tags=list(tags),
        tray=None,
        payee=None,
    )


def draft_rule(
    *,
    text: str,
    original_name: str,
    filed_name: str | None,
    filed_folder: str | None,
    doc_date: date | None,
    tags: list[str],
    tray: str | None,
    payee: str | None,
    doc_frequency: Callable[[str], float],
    taken_ids: set[str],
    person: str | None = None,
) -> RuleDraft | None:
    """The rule a click on "make a rule" starts from, or None when no usable word is left.
    Without ``filed_folder`` / ``filed_name`` (a document still in the inbox) the draft has
    no folder / name. ``person``: the document's person, proposed as ``{person}`` where
    the folder path has a part with that name."""
    words = [w for w in _tokens("", text) if doc_frequency(w) <= MAX_FREQUENCY][:MAX_WORDS]
    if not words:
        return None
    pick = min(range(len(words)), key=lambda i: (doc_frequency(words[i]), i))
    folder, name = filed_patterns(filed_name, filed_folder, original_name, doc_date, person)
    return RuleDraft(
        id=_unique(_slug(words[pick]), taken_ids),
        words=[DraftWord(w, i == pick) for i, w in enumerate(words)],
        folder=folder,
        name=name,
        tags=list(tags),
        tray=tray,
        payee=payee,
    )
