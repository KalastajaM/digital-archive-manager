"""Prove a rule against the past: what would it have done to the files already filed?

``replay`` runs one rule over every indexed file outside the special folders and
compares the path it would give with the path the file has. ``explain`` says, for one
document, which rules match and which of them wins each field.
"""

import logging
import re
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from time import perf_counter

from sqlalchemy import Engine, select

from dam.config import Person, SpecialFolders
from dam.core.naming import _DATE_PREFIX, parse_doc_date
from dam.core.paths import nfc
from dam.db.tables import file_text, files
from dam.extract.layout import Page1Layout, lines_in_zone
from dam.index.repo import BARCODE_EXTS, FileRecord
from dam.ops.guards import is_under
from dam.rules.engine import (
    Area,
    TemplateError,
    _matches,
    _parent,
    _render_folder,
    _render_name,
    check,
    has_picture_zones,
    has_text_zones,
    person_for,
    picture_match,
    rule_areas,
    rule_needs_person,
    stem_and_ext,
    suggest,
    template_uses_person,
    zone_hits,
    zone_matches,
    zones_in_text,
)
from dam.rules.model import Rule, fold
from dam.rules.people import PeopleContext
from dam.rules.picture import Pictures
from dam.rules.timings import Timings


@dataclass
class ReplayHit:
    drive_id: str
    path_now: str
    path_rule: str  # "" when the rule's template cannot be rendered for this file


NOT_READ = "page 1 not read yet"
PERSON_UNKNOWN = "person unknown"


@dataclass
class NotChecked:
    """A document the rule could match by its words but whose page 1 could not be looked
    at: never counted as a non-match. ``reason``: ``NOT_READ``, "no OCR engine" or
    "missing"."""

    path: str
    reason: str
    drive_id: str = ""


@dataclass
class MarkedDoc:
    """A document the owner marked as from the rule's sender, by path and drive id (to open
    it)."""

    path: str
    drive_id: str


@dataclass
class Marked:
    """The documents the owner marked as from the rule's sender, against what the rule
    matches: how many, how many it finds, the ones it misses (a miss is a document whose
    page 1 was read and does not match), and the ones that could not be checked."""

    total: int = 0
    found: int = 0
    missed: list[MarkedDoc] = field(default_factory=list)
    not_checked: list[NotChecked] = field(default_factory=list)


@dataclass
class PictureScore:
    """How well a document's page 1 matched the rule's picture areas (the lowest score of
    them), and whether the rule matched it. A document that is not matched is only listed
    when a picture area was the one thing that failed (every other condition held) and
    the score is within ``NEAR_MISS`` of ``needed``, the score that area asked for."""

    path: str
    score: float
    matched: bool
    drive_id: str = ""
    needed: float | None = None  # for a non-match: the score the failing area needed


# a picture rule's replay reports the lowest scores of its matches and the highest of the
# documents it did not match but came close to: the two ends that show how well they are
# told apart. A document far below the threshold is no news and is not listed.
SCORES_MATCHED = 20
SCORES_NOT_MATCHED = 10
NEAR_MISS = 0.15


def pick_scores(found: list[PictureScore]) -> list[PictureScore]:
    matched = sorted((x for x in found if x.matched), key=lambda x: (x.score, x.path))
    others = sorted(
        (
            x
            for x in found
            if not x.matched and x.needed is not None and x.needed - x.score <= NEAR_MISS
        ),
        key=lambda x: (-x.score, x.path),
    )
    return matched[:SCORES_MATCHED] + others[:SCORES_NOT_MATCHED]


@dataclass
class SourceDoc:
    """The document the rule is being made from, judged as live filing would: a document in
    the inbox by the rule as written (with its ``folder_is``), a filed one without it, as the
    replay does. It is left out of every count and list of the test. ``matched`` is None
    while page 1 (or its picture) is not read yet, so it cannot be told; ``reason`` says why
    it does not match (or why it cannot be told yet), in the words of ``explain``."""

    drive_id: str
    path: str
    matched: bool | None
    reason: str = ""


@dataclass
class ReplayResult:
    matched: int
    same: int
    different: list[ReplayHit]
    inbox: int
    shadowed: list[tuple[str, str]]  # (drive_id, id of the earlier rule that wins)
    checked: int
    total: int
    truncated: bool
    not_checked: list[NotChecked] = field(default_factory=list)
    reading: int = 0  # of the not checked, how many page 1 reads are queued now
    # when ``truncated``: the path to continue after (pass it as ``after`` to go on)
    next_after: str | None = None
    marked: Marked | None = None  # only for a rule with a ``sender``
    # only for a rule with picture areas: see ``PictureScore``
    scores: list[PictureScore] = field(default_factory=list)
    # the filed documents gone through so far, the ones that could not be checked included
    # (``checked`` leaves those out)
    looked_at: int = 0
    # the document the rule is made from (``source_drive_id``), left out of all the above
    source: SourceDoc | None = None


@dataclass
class RuleExplain:
    rule_id: str
    matched: bool
    why: str
    wins: list[str] = field(default_factory=list)
    # the page-1 lines in each of the rule's zones (one list per zone)
    zone_lines: list[list[str]] = field(default_factory=list)
    # the rule's areas for drawing on page 1: the matched lines of each, and for an area
    # (or rule) that did not match, the reason
    areas: list[Area] = field(default_factory=list)


def without_folder(rule: Rule) -> Rule:
    """``rule`` as if it had no ``folder_is`` (private compiled parts carry over)."""
    if rule.when.folder_is is None:
        return rule
    return rule.model_copy(update={"when": rule.when.model_copy(update={"folder_is": None})})


def _replay_stem(rec: FileRecord) -> str:
    """The ``{stem}`` live filing gives, minus the date prefix and one separator."""
    stem, _, _ = stem_and_ext(rec)
    if _DATE_PREFIX.match(stem):
        stem = stem[8:]
        if stem.startswith(("_", " ", "-", ".")):
            stem = stem[1:]
    return stem or "document"


def _rule_path(
    rule: Rule, rec: FileRecord, special: SpecialFolders, person: str | None = None
) -> str:
    name = rec.name or PurePosixPath(rec.path).name
    ext = (rec.ext or "").lower()
    doc_date = parse_doc_date(name) or rec.doc_date
    stem = _replay_stem(rec)
    if rule.then.folder is not None:
        folder = _render_folder(rule.then.folder, doc_date, stem, special, person)
    else:
        folder = _parent(rec.path)
    if rule.then.name is not None:
        new = _render_name(rule.then.name, doc_date, stem, ext, person) + (f".{ext}" if ext else "")
    else:
        new = name
    return f"{folder}/{new}" if folder else new


def _marked(
    engine: Engine,
    free: Rule,
    ids: list[str],
    layouts_for: Callable[[Collection[str]], dict[str, Page1Layout]] | None,
    layout_blocked: Callable[[str], str | None] | None,
    context: Callable[[str], PeopleContext],
    pictures: Pictures | None = None,
) -> tuple[Marked, list[str]]:
    """``free`` (the rule without ``folder_is``) against the documents ``ids``, which the
    owner marked as from its sender. Returns the comparison and the ids whose page 1 is
    waiting to be read."""
    marked = Marked()
    unread: list[str] = []
    if not ids:
        return marked, unread
    cols = [
        files.c.drive_id,
        files.c.path,
        files.c.name,
        files.c.ext,
        files.c.doc_date,
        files.c.sha256,
    ]
    with engine.connect() as conn:
        rows = conn.execute(
            select(*cols, files.c.index_state, file_text.c.text)
            .select_from(files.outerjoin(file_text, file_text.c.drive_id == files.c.drive_id))
            .where(
                files.c.drive_id.in_(ids),
                files.c.missing.is_not(True),
                files.c.parked_at.is_(None),
                files.c.is_dir.is_not(True),
            )
            .order_by(files.c.path)
        ).all()
    layouts = layouts_for([r.drive_id for r in rows]) if layouts_for is not None else {}
    marked.total = len(rows)
    for row in rows:
        rec = FileRecord(
            drive_id=row.drive_id,
            path=row.path,
            name=row.name,
            ext=row.ext,
            doc_date=row.doc_date,
            sha256=row.sha256,
        )
        if row.index_state != "indexed":
            marked.not_checked.append(NotChecked(row.path, "not indexed yet", row.drive_id))
            continue
        c = check(
            free,
            rec,
            fold(row.text or ""),
            None,
            layouts.get(row.drive_id),
            context(row.drive_id),
            pictures,
        )
        if c.matched:
            marked.found += 1
        elif c.waiting:
            reason = (layout_blocked(row.drive_id) if layout_blocked else None) or NOT_READ
            marked.not_checked.append(NotChecked(row.path, reason, row.drive_id))
            if reason == NOT_READ:
                unread.append(row.drive_id)
        elif c.person_unknown:
            marked.not_checked.append(NotChecked(row.path, PERSON_UNKNOWN, row.drive_id))
        else:
            marked.missed.append(MarkedDoc(row.path, row.drive_id))
    return marked, unread


LAYOUT_CHUNK = 100  # documents whose text and layouts are fetched with one query
log = logging.getLogger(__name__)


class StaleCursor(ValueError):
    """A ``next_after`` cursor of a test that the server no longer remembers."""


# The order of the documents of a test that stopped at its time budget, so that "test the
# rest" goes on in the same order (a few at a time: the cursor is opaque to the caller).
_PLANS: OrderedDict[str, list[str]] = OrderedDict()
_PLANS_LOCK = threading.Lock()
MAX_PLANS = 6
_CURSOR = re.compile(r"r1\.([0-9a-f]{8})\.(\d+)")


def _remember(ids: list[str]) -> str:
    plan_id = secrets.token_hex(4)
    with _PLANS_LOCK:
        _PLANS[plan_id] = ids
        while len(_PLANS) > MAX_PLANS:
            _PLANS.popitem(last=False)
    return plan_id


def _recall(plan_id: str) -> list[str] | None:
    with _PLANS_LOCK:
        ids = _PLANS.get(plan_id)
        if ids is not None:
            _PLANS.move_to_end(plan_id)
        return ids


@dataclass
class PlanRow:
    """A document to look at: the columns a check needs (not its text, which is fetched
    for a chunk of rows at a time, and only for a rule that has words to look for)."""

    drive_id: str
    path: str
    name: str | None
    ext: str | None
    doc_date: object
    sha256: str | None

    def record(self) -> FileRecord:
        return FileRecord(
            drive_id=self.drive_id,
            path=self.path,
            name=self.name,
            ext=self.ext,
            doc_date=self.doc_date,
            sha256=self.sha256,
        )


class ReplayRun:
    """One rule test, done a chunk of documents at a time so that it can stop at a time
    budget (``replay``) or run in the background and publish what it has found so far
    (``dam.rules.jobs``). Read-only: it reads the index and the cache, nothing else.

    Of each document it does the cheapest work first: documents of a kind that cannot
    have a page 1 are settled without their text when the rule has areas; the text is
    fetched and folded only for a rule with words (once per document); a layout is
    loaded only for a document whose text has a word of every text area; a picture is
    looked at last. The result does not depend on the order the documents are taken in."""

    def __init__(
        self,
        engine: Engine,
        rule: Rule,
        rules: list[Rule],
        special: SpecialFolders,
        *,
        inbox_code_of: Callable[[str], str | None] | None = None,
        layouts_for: Callable[[Collection[str]], dict[str, Page1Layout]] | None = None,
        want_layouts: Callable[[Collection[str]], None] | None = None,
        layout_blocked: Callable[[str], str | None] | None = None,
        people: Sequence[Person] = (),
        address_zone: Sequence[float] = (0.0, 0.0, 1.0, 1.0),
        assigned_persons: Callable[[], dict[str, str]] | None = None,
        sender_ids: Callable[[str], Sequence[str]] | None = None,
        pictures: Pictures | None = None,
        after: str | None = None,
        near_folder: str | None = None,
        source_drive_id: str | None = None,
        register: bool = False,
        with_marked: bool = True,
    ) -> None:
        self.engine = engine
        self.rule = rule
        self.special = special
        self.inbox_code_of = inbox_code_of
        self.layouts_for = layouts_for
        self.want_layouts = want_layouts
        self.layout_blocked = layout_blocked
        self.people = people
        self.address_zone = tuple(address_zone)
        self.sender_ids = sender_ids
        self.pictures = pictures
        self.timings = Timings()
        self.free = without_folder(rule)
        earlier: list[Rule] = []
        for r in rules:
            if r is rule:
                break
            earlier.append(r)
        self.earlier = [without_folder(r) for r in earlier if r.then.folder or r.then.name]
        self.needs_person = rule_needs_person(rule)
        self.needs_text = bool(rule._folded_terms) or has_text_zones(rule)
        self.has_zones = bool(rule.when.zones)
        self.needs_layouts = (
            has_text_zones(rule)
            or self.needs_person
            or any(has_text_zones(r) or rule_needs_person(r) for r in self.earlier)
        )
        self.own_layouts = has_text_zones(rule) or self.needs_person
        self.assigned = (
            assigned_persons() if assigned_persons is not None and self.needs_layouts else {}
        )
        self.with_marked = with_marked and bool(rule.sender) and sender_ids is not None
        self.near_folder = None if near_folder is None else nfc(near_folder)
        self.register = register
        self.source_drive_id = source_drive_id
        self.source: SourceDoc | None = None
        # ``after`` is a cursor (``next_after`` of an earlier part of this test) or, from
        # callers older than the cursor, the path to go on after (the path order)
        self.after = after
        self.plan_id: str | None = None
        self.base = 0  # where in the whole order the documents of this run begin
        # what has been found
        self.matched = self.same = self.inbox = self.checked = self.looked_at = 0
        self.different: list[ReplayHit] = []
        self.shadowed: list[tuple[str, str]] = []
        self.not_checked: dict[str, NotChecked] = {}
        self.scores: list[PictureScore] = []
        self.marked: Marked | None = None
        self._unread: dict[str, PlanRow] = {}  # waiting for page 1 (filed or in the inbox)
        self._marked_unread: list[str] = []
        self._wanted_sent: set[str] = set()
        self._first_done = False
        # the documents
        self.rows: list[PlanRow] = []
        self.paths: dict[str, str] = {}
        self.total = 0
        self.pos = 0
        self.last_path: str | None = after
        self._plan()

    # -- the list of documents ---------------------------------------------------------

    def _skipped(self, path: str) -> bool:
        s = self.special
        return any(is_under(path, base) for base in (s.ongoing, s.important, s.quarantine))

    def _plan(self) -> None:
        started = perf_counter()
        where = (
            files.c.index_state == "indexed",
            files.c.is_dir.is_not(True),
            files.c.is_link.is_not(True),
            files.c.missing.is_not(True),
            files.c.parked_at.is_(None),
        )
        cols = (
            files.c.drive_id,
            files.c.path,
            files.c.name,
            files.c.ext,
            files.c.doc_date,
            files.c.sha256,
        )
        joined = files.join(file_text, file_text.c.drive_id == files.c.drive_id)
        with self.engine.connect() as conn:
            found = conn.execute(
                select(*cols).select_from(joined).where(*where).order_by(files.c.path)
            ).all()
        self.timings.sql += perf_counter() - started
        rows = [PlanRow(*r) for r in found if not self._skipped(r.path)]
        if self.source_drive_id is not None:
            rows = [r for r in rows if r.drive_id != self.source_drive_id]
        self.total = sum(1 for r in rows if not is_under(r.path, self.special.inbox))
        self.paths = {r.drive_id: r.path for r in rows}
        cursor = _CURSOR.fullmatch(self.after) if self.after is not None else None
        if cursor is not None:
            ids = _recall(cursor.group(1))
            if ids is None:
                raise StaleCursor("that test is no longer there: run it again")
            self.plan_id, self.base = cursor.group(1), min(int(cursor.group(2)), len(ids))
            by_id = {r.drive_id: r for r in rows}
            rows = [by_id[d] for d in ids[self.base :] if d in by_id]
        elif self.after is not None:
            rows = [r for r in rows if r.path > self.after]  # path order, as before cursors
        else:
            rows = self._ordered(rows)
            if self.register:
                self.plan_id = _remember([r.drive_id for r in rows])
        self.rows = rows

    def _ordered(self, rows: list[PlanRow]) -> list[PlanRow]:
        """The likely documents first: those assigned to the rule's sender, those in the
        folder of the document the areas were drawn on, then (for a picture rule) the rest
        by a rough picture score from thumbnails, best first, then by path. Only the order
        changes, never the result."""
        started = perf_counter()
        rule = self.rule
        mine: set[str] = set()
        if rule.sender and self.sender_ids is not None:
            mine = set(self.sender_ids(rule.sender))
        near = self.near_folder
        scores: dict[str, float] = {}
        if self.pictures is not None and has_picture_zones(rule):
            can = [(r.drive_id, r.sha256) for r in rows if (r.ext or "").lower() in BARCODE_EXTS]
            scores = self.pictures.rank(rule, can)

        def key(r: PlanRow) -> tuple[int, float, str]:
            group = 0 if r.drive_id in mine else 1 if near and nfc(_parent(r.path)) == near else 2
            return (group, -scores.get(r.drive_id, -1.0), r.path)

        if mine or near or scores:
            rows = sorted(rows, key=key)
        self.timings.plan += perf_counter() - started
        return rows

    # -- fetching ----------------------------------------------------------------------

    def _fetch_texts(self, ids: Sequence[str]) -> dict[str, str]:
        if not ids:
            return {}
        started = perf_counter()
        with self.engine.connect() as conn:
            got = conn.execute(
                select(file_text.c.drive_id, file_text.c.text).where(file_text.c.drive_id.in_(ids))
            ).all()
        self.timings.sql += perf_counter() - started
        return {r.drive_id: r.text or "" for r in got}

    def _fold(self, text: str) -> str:
        started = perf_counter()
        out = fold(text)
        self.timings.fold += perf_counter() - started
        self.timings.text_chars += len(text)
        return out

    def _context(self, drive_id: str) -> PeopleContext:
        return PeopleContext(self.people, self.address_zone, self.assigned.get(drive_id))

    def _unreadable(self, drive_id: str) -> str:
        """Why page 1 of this document is not there: waiting for the layout pass, or
        something stops it."""
        return (self.layout_blocked(drive_id) if self.layout_blocked else None) or NOT_READ

    def _wants_layout(self, rec: FileRecord, folded: str, in_inbox: bool) -> bool:
        """Whether this row's layout can change the outcome (the cheap conditions on its
        text first)."""
        if self.own_layouts:
            return zones_in_text(self.rule, folded)
        # only an earlier rule looks at it, and only for a file this rule may match. The
        # picture is not looked at here (that is the expensive part, and it belongs to the
        # main loop under the time budget): "waiting" is every other condition holding.
        if in_inbox:
            return False
        c = check(self.free, rec, folded, None, None, None, None)
        return c.matched or c.waiting

    # -- going through the documents ---------------------------------------------------

    def advance(
        self,
        budget_s: float | None = None,
        stop: Callable[[], bool] | None = None,
        progress: Callable[[], None] | None = None,
    ) -> bool:
        """Look at more documents until the time budget is used (None: no limit) or ``stop()``
        says so; ``progress`` is called after each chunk. True when every document has been
        looked at."""
        started = time.monotonic()
        self._first()
        while self.pos < len(self.rows):
            if stop is not None and stop():
                return False
            if budget_s is not None and time.monotonic() - started >= budget_s:
                return False
            chunk = self.rows[self.pos : self.pos + LAYOUT_CHUNK]
            if not self._chunk(chunk, started, budget_s, stop):
                return False
            if progress is not None:
                progress()
        return True

    @property
    def done(self) -> bool:
        return self.pos >= len(self.rows)

    def _first(self) -> None:
        """The documents the owner marked as from the rule's sender (once)."""
        if self._first_done:
            return
        self._first_done = True
        if self.with_marked and self.after is None:
            self.refresh_marked()
        self._judge_source()

    def _judge_source(self) -> None:
        """Judge the source document (again, while page 1 or its picture is not there)."""
        if self.source_drive_id is None or (self.source and self.source.matched is not None):
            return
        started = perf_counter()
        with self.engine.connect() as conn:
            row = conn.execute(
                select(
                    files.c.drive_id,
                    files.c.path,
                    files.c.name,
                    files.c.ext,
                    files.c.doc_date,
                    files.c.sha256,
                    files.c.index_state,
                    file_text.c.text,
                )
                .select_from(files.outerjoin(file_text, file_text.c.drive_id == files.c.drive_id))
                .where(files.c.drive_id == self.source_drive_id, files.c.missing.is_not(True))
            ).first()
        self.timings.sql += perf_counter() - started
        if row is None:
            self.source = None
            return
        rec = FileRecord(
            drive_id=row.drive_id,
            path=row.path,
            name=row.name,
            ext=row.ext,
            doc_date=row.doc_date,
            sha256=row.sha256,
        )
        if row.index_state != "indexed":
            self.source = SourceDoc(row.drive_id, row.path, None, "the document is not read yet")
            return
        folded = fold(row.text or "")
        layouts = self.layouts_for([row.drive_id]) if self.layouts_for is not None else {}
        layout = layouts.get(row.drive_id)
        ctx = self._context(row.drive_id)
        in_inbox = is_under(row.path, self.special.inbox)
        if in_inbox:
            code = self.inbox_code_of(row.path) if self.inbox_code_of is not None else None
            alias = self.special.inbox if code is not None else None
            rule = self.rule
        else:
            alias, rule = None, self.free
        c = check(rule, rec, folded, alias, layout, ctx, self.pictures)
        if c.matched:
            self.source = SourceDoc(row.drive_id, row.path, True)
            return
        why = _why(rule, rec, folded, alias, self.special, layout, ctx, self.pictures)
        if c.waiting:
            self._want([row.drive_id])
        self.source = SourceDoc(row.drive_id, row.path, None if c.waiting else False, why)

    def refresh_marked(self) -> None:
        assert self.sender_ids is not None and self.rule.sender
        started = perf_counter()
        self.marked, self._marked_unread = _marked(
            self.engine,
            self.free,
            [d for d in self.sender_ids(self.rule.sender) if d != self.source_drive_id],
            self.layouts_for,
            self.layout_blocked,
            self._context,
            self.pictures,
        )
        self.timings.sql += perf_counter() - started
        self._want(self._marked_unread)

    def _want(self, ids: Collection[str]) -> None:
        """Hand documents whose page 1 is not read to the layout pass (each once)."""
        fresh = [i for i in ids if i not in self._wanted_sent]
        if fresh and self.want_layouts is not None:
            self._wanted_sent.update(fresh)
            self.want_layouts(fresh)

    def _chunk(
        self,
        rows: list[PlanRow],
        started: float,
        budget_s: float | None,
        stop: Callable[[], bool] | None,
        recheck: bool = False,
    ) -> bool:
        """Look at ``rows``; False when the budget or ``stop`` ended it part way."""
        t = self.timings
        texts: dict[str, str] = {}
        folded: dict[str, str] = {}
        layouts: dict[str, Page1Layout] = {}
        # a rule with areas cannot match a file that has no page 1: no text needed for it
        looks = [r for r in rows if not self.has_zones or (r.ext or "").lower() in BARCODE_EXTS]
        if self.needs_text:
            texts = self._fetch_texts([r.drive_id for r in looks])
            for r in looks:
                folded[r.drive_id] = self._fold(texts.get(r.drive_id, ""))
        if self.layouts_for is not None and self.needs_layouts:
            ids = []
            for r in looks:
                in_inbox = is_under(r.path, self.special.inbox)
                if self._wants_layout(r.record(), folded.get(r.drive_id, ""), in_inbox):
                    ids.append(r.drive_id)
            if ids:
                started_l = perf_counter()
                layouts = self.layouts_for(ids)
                t.layouts += perf_counter() - started_l
                t.layouts_loaded += len(layouts)
        looking = {r.drive_id for r in looks}
        for row in rows:
            if budget_s is not None and time.monotonic() - started >= budget_s:
                return False
            if stop is not None and stop():
                return False
            if row.drive_id in looking:
                self._row(row, folded.get(row.drive_id, ""), layouts.get(row.drive_id), texts)
            else:
                self._no_page1(row)
            if not recheck:
                self.pos += 1
                self.last_path = row.path
                if not is_under(row.path, self.special.inbox):
                    self.looked_at += 1
                t.rows += 1
        self._want([d for d in self._unread if d not in self._wanted_sent])
        return True

    def _no_page1(self, row: PlanRow) -> None:
        """A file with no page 1, for a rule with areas: not a match, nothing to wait for."""
        if not is_under(row.path, self.special.inbox):
            self.checked += 1

    def _settle(self, drive_id: str) -> None:
        self.not_checked.pop(drive_id, None)
        self._unread.pop(drive_id, None)

    def _not_checked(self, row: PlanRow, reason: str) -> None:
        self.not_checked[row.drive_id] = NotChecked(row.path, reason, row.drive_id)
        if reason == NOT_READ:
            self._unread[row.drive_id] = row
        else:
            self._unread.pop(row.drive_id, None)

    def _row(
        self, row: PlanRow, folded: str, layout: Page1Layout | None, texts: dict[str, str]
    ) -> None:
        rule, special, t = self.rule, self.special, self.timings
        rec = row.record()
        ctx = self._context(row.drive_id)
        if is_under(row.path, special.inbox):
            code = self.inbox_code_of(row.path) if self.inbox_code_of is not None else None
            alias = special.inbox if code is not None else None
            c = check(rule, rec, folded, alias, layout, ctx, self.pictures, t)
            if c.matched:
                self._settle(row.drive_id)
                self.inbox += 1
            elif c.waiting:
                self._unread[row.drive_id] = row
            else:
                self._unread.pop(row.drive_id, None)
            return
        c = check(self.free, rec, folded, None, layout, ctx, self.pictures, t)
        if c.waiting:
            # every other condition holds: only page 1 is missing. Not a non-match.
            self._not_checked(row, self._unreadable(row.drive_id))
            return
        if c.person_unknown:
            self._not_checked(row, PERSON_UNKNOWN)
            return
        if not c.matched:
            self._settle(row.drive_id)
            self.checked += 1
            if c.picture_score is not None:
                self.scores.append(
                    PictureScore(row.path, c.picture_score, False, row.drive_id, c.picture_needed)
                )
            return
        person = None
        if template_uses_person(rule.then.folder) or template_uses_person(rule.then.name):
            person = person_for(ctx, layout, rule).name
            if person is None:
                supported = (row.ext or "").lower() in BARCODE_EXTS
                if layout is None and supported and not ctx.assigned:
                    self._not_checked(row, self._unreadable(row.drive_id))
                else:
                    self._not_checked(row, PERSON_UNKNOWN)
                return
        self._settle(row.drive_id)
        self.checked += 1
        self.matched += 1
        if c.picture_score is not None:
            self.scores.append(PictureScore(row.path, c.picture_score, True, row.drive_id))
        try:
            path_rule = _rule_path(rule, rec, special, person)
        except TemplateError:
            path_rule = ""
        if path_rule and nfc(path_rule).casefold() == nfc(row.path).casefold():
            self.same += 1
        else:
            self.different.append(ReplayHit(row.drive_id, row.path, path_rule))
        if self.earlier:
            if not self.needs_text:  # the earlier rules look at the words: fetched for this one
                folded = self._fold(self._fetch_texts([row.drive_id]).get(row.drive_id, ""))
            for r in self.earlier:
                if _matches(r, rec, folded, None, layout, ctx, self.pictures)[0]:
                    self.shadowed.append((row.drive_id, r.id))
                    break

    # -- documents waiting for page 1 --------------------------------------------------

    def waiting_ids(self) -> list[str]:
        """The documents that wait for page 1 to be read (or its picture to be made)."""
        ids = list(self._unread)
        if self.source is not None and self.source.matched is None:
            ids.append(self.source.drive_id)
        return ids

    def recheck(self) -> int:
        """Look again at the documents that were waiting for page 1, now that some of
        them may be read (or blocked for good); returns how many were settled or changed."""
        waited = self.source is not None and self.source.matched is None
        self._judge_source()
        rows = list(self._unread.values())
        if not rows:
            return int(waited and self.source is not None and self.source.matched is not None)
        before = len(self._unread)
        ready = []
        have_layout = self.layouts_for(self._ids_with_layout(rows)) if self.layouts_for else {}
        for r in rows:
            blocked = self.layout_blocked(r.drive_id) if self.layout_blocked else None
            if blocked is not None and r.drive_id in self.not_checked:
                self.not_checked[r.drive_id].reason = blocked  # it will not be read now
                self._unread.pop(r.drive_id, None)
            elif r.drive_id in have_layout or (
                self.pictures is not None and self.pictures.has_page(r.drive_id, r.sha256)
            ):
                ready.append(r)
        for k in range(0, len(ready), LAYOUT_CHUNK):
            self._chunk(ready[k : k + LAYOUT_CHUNK], time.monotonic(), None, None, recheck=True)
        if self.marked is not None and self._marked_unread:
            self.refresh_marked()
        return before - len(self._unread)

    def _ids_with_layout(self, rows: list[PlanRow]) -> list[str]:
        return [r.drive_id for r in rows]

    # -- the result --------------------------------------------------------------------

    def snapshot(self, truncated: bool = False) -> ReplayResult:
        """What has been found so far, as a result whose lists are in path order (so the
        same documents give the same result in whatever order they were looked at)."""
        by_path = self.paths.get
        marked = self.marked
        if marked is not None:
            marked = Marked(
                marked.total,
                marked.found,
                sorted(marked.missed, key=lambda m: m.path),
                sorted(marked.not_checked, key=lambda n: n.path),
            )
        return ReplayResult(
            matched=self.matched,
            same=self.same,
            different=sorted(self.different, key=lambda h: h.path_now),
            inbox=self.inbox,
            shadowed=sorted(self.shadowed, key=lambda s: (by_path(s[0], ""), s[1])),
            checked=self.checked,
            total=self.total,
            truncated=truncated,
            not_checked=sorted(self.not_checked.values(), key=lambda n: n.path),
            reading=len(self._unread) + len(self._marked_unread),
            next_after=self._cursor() if truncated else None,
            marked=marked,
            scores=pick_scores(self.scores),
            looked_at=self.looked_at,
            source=self.source,
        )

    def _cursor(self) -> str | None:
        """Where to go on: the opaque cursor of this test's order (or, for a test that began
        with a path, the last path)."""
        if self.plan_id is not None:
            return f"r1.{self.plan_id}.{self.base + self.pos}"
        return self.last_path

    def log_summary(self, total_s: float) -> None:
        log.info("%s", self.timings.summary(total_s))


def replay(
    engine: Engine,
    rule: Rule,
    rules: list[Rule],
    special: SpecialFolders,
    budget_s: float = 5.0,
    inbox_code_of: Callable[[str], str | None] | None = None,
    *,
    layouts_for: Callable[[Collection[str]], dict[str, Page1Layout]] | None = None,
    want_layouts: Callable[[Collection[str]], None] | None = None,
    layout_blocked: Callable[[str], str | None] | None = None,
    people: Sequence[Person] = (),
    address_zone: Sequence[float] = (0.0, 0.0, 1.0, 1.0),
    assigned_persons: Callable[[], dict[str, str]] | None = None,
    sender_ids: Callable[[str], Sequence[str]] | None = None,
    pictures: Pictures | None = None,
    after: str | None = None,
    near_folder: str | None = None,
    source_drive_id: str | None = None,
) -> ReplayResult:
    """``rules`` is the load order with ``rule`` in its place. For filed files
    ``folder_is`` is ignored: a rule meant for the inbox is judged on the files it would
    have filed. Inbox files are only counted (``inbox``), when the rule as written, with
    its ``folder_is``, matches them as live filing would; ``inbox_code_of`` tells which
    files sit in a filing code's inbox folder (they count as in the inbox).

    A rule with ``zones`` can only match a document whose text has one of its words
    (``check`` tests that first). Of those, the ones without a page-1 layout are handed to
    ``want_layouts`` and listed in ``not_checked`` with the reason (``layout_blocked``
    says why a read cannot happen now); they are never counted as non-matches. Layouts
    are loaded in chunks of ``LAYOUT_CHUNK`` rows, only for the rows that need one.

    ``{person}`` and ``when.person`` use the document's person: its assignment
    (``assigned_persons``: drive id -> person) if there is one, else the one found in the
    address area of page 1. A document whose person is unknown is not checked
    ("person unknown"), not a mismatch.

    A picture area has no text to look for first, so every filed PDF and image is looked
    at, from its page-1 picture in the cache (``pictures``: nothing is read from the
    archive). One without a picture yet is not checked and is handed to ``want_layouts``
    like one without a layout. The time budget applies as ever. ``scores`` then holds the
    scores of the rule's matches (the lowest) and of its near misses: documents where every
    other condition held and only a picture area failed, within ``NEAR_MISS`` of the score
    it needed (a document that failed a text area, the person or anything else never has a
    picture score).

    The likely documents are taken first, the rest in path order: those assigned to the
    rule's sender, those in ``near_folder`` (the folder of the document the areas were
    drawn on), and for a picture rule the rest best-looking first (a rough score from the
    thumbnails). The order changes when things show up, never the result. A replay that
    stopped at its time budget gives ``next_after``, an opaque cursor: pass it as ``after``
    to go on with the documents not looked at yet (they are counted on their own, and
    ``total`` is still the number of all filed files). It is remembered for a while only
    (``StaleCursor`` after that). The marked documents of the rule's sender are compared on
    the first call only (without ``after``).

    ``source_drive_id`` is the document the rule is made from: it is left out of every
    count and list and judged on its own (``result.source``).

    The time of each step is written to the log (``Timings``)."""
    started = time.monotonic()
    run = ReplayRun(
        engine,
        rule,
        rules,
        special,
        inbox_code_of=inbox_code_of,
        layouts_for=layouts_for,
        want_layouts=want_layouts,
        layout_blocked=layout_blocked,
        people=people,
        address_zone=address_zone,
        assigned_persons=assigned_persons,
        sender_ids=sender_ids,
        pictures=pictures,
        after=after,
        near_folder=near_folder,
        source_drive_id=source_drive_id,
        register=True,
    )
    finished = run.advance(max(0.0, budget_s - (time.monotonic() - started)))
    result = run.snapshot(truncated=not finished)
    run.log_summary(time.monotonic() - started)
    return result


def _area(index: int, total: int) -> str:
    """ "the area", or "area 2" when the rule has several."""
    return "the area" if total == 1 else f"area {index + 1}"


def _why(
    rule: Rule,
    rec: FileRecord,
    folded_text: str,
    inbox_alias: str | None,
    special,
    layout: Page1Layout | None = None,
    people: PeopleContext | None = None,
    pictures: Pictures | None = None,
) -> str:
    when = rule.when
    c = check(rule, rec, folded_text, inbox_alias, layout, people, pictures)
    if c.matched:
        parts = [
            f"word ‘{raw}’"
            for raw, term in zip(when.text_contains, rule._folded_terms, strict=True)
            if term in folded_text
        ][:1]
        if when.filename_matches is not None:
            parts.append(f"file name matches {when.filename_matches}")
        for i, zone in enumerate(when.zones):
            if zone.is_picture:
                found = picture_match(rule, i, rec, pictures)
                if found is not None:
                    parts.append(f"picture {found.score:.2f} in {_area(i, len(when.zones))}")
        if layout is not None:
            for i, zone in enumerate(when.zones):
                if zone.is_picture:
                    continue
                hit = next(
                    (
                        raw
                        for raw, test in zip(
                            zone.text_contains or [], rule._zone_tests[i], strict=True
                        )
                        if any(test(fold(ln.text)) for ln in zone_hits(rule, i, layout))
                    ),
                    None,
                )
                parts.append(f"word ‘{hit}’ in {_area(i, len(when.zones))}")
        if not parts and when.folder_is is not None:
            parts.append(f"in the folder ‘{when.folder_is}’")
        return ", ".join(parts) or "no condition: matches every file"
    if c.timed_out:
        return "file name check took too long"
    if c.waiting:
        if has_picture_zones(rule) and (layout is not None or not has_text_zones(rule)):
            return "the picture of page 1 is not made yet"
        return "page 1 has not been read yet"
    if c.person_unknown:
        return "the document has no single person (address area)"
    if when.folder_is is not None:
        # the folder test is first in _matches: failing it, nothing else was looked at
        here = {nfc(_parent(rec.path)).casefold()}
        if inbox_alias is not None:
            here.add(nfc(inbox_alias).strip("/").casefold())
        want = nfc(when.folder_is).strip("/").casefold()
        if want not in here:
            if want == nfc(special.inbox).strip("/").casefold():
                return "not in the inbox"
            return f"not in the folder ‘{when.folder_is}’"
    if rule._folded_terms and not any(t in folded_text for t in rule._folded_terms):
        return "no word found"
    if when.zones and (rec.ext or "").lower() not in BARCODE_EXTS:
        return "no page 1 to look at in this kind of file"
    if (
        when.filename_matches is not None
        and rule._regex is not None
        and not rule._regex.search(nfc(rec.name or ""))
    ):
        return "file name does not match"
    if when.zones:
        for i, zone in enumerate(when.zones):
            if zone.is_picture:
                continue
            if layout is None or not zone_matches(rule, i, layout):
                return f"no word found in {_area(i, len(when.zones))}"
        for i, zone in enumerate(when.zones):
            if zone.is_picture:
                found = picture_match(rule, i, rec, pictures)
                if found is None or found.score < zone.threshold:
                    got = f"{found.score:.2f}" if found is not None else "not made"
                    return (
                        f"the picture in {_area(i, len(when.zones))} scores {got}, "
                        f"needs {zone.threshold:.2f}"
                    )
    if when.person is not None:
        return f"the document is not for {when.person}"
    return "file name does not match"


def explain(
    rec: FileRecord,
    text: str,
    rules: list[Rule],
    special: SpecialFolders,
    inbox_alias: str | None,
    layout: Page1Layout | None = None,
    people: PeopleContext | None = None,
    pictures: Pictures | None = None,
) -> list[RuleExplain]:
    """For each rule: does it match this document, why (not), and which fields it wins.
    For a rule with zones, the page-1 lines in each zone (so a missed match can be
    explained)."""
    folded = fold(text)
    s = suggest(
        rec, text, rules, special, inbox_alias, layout=layout, people=people, pictures=pictures
    )
    out: list[RuleExplain] = []
    for rule in rules:
        mine = f"rule:{rule.id}"
        matched = _matches(rule, rec, folded, inbox_alias, layout, people, pictures)[0]
        wins = [
            label
            for label, source in (
                ("folder", s.folder_source),
                ("name", s.name_source),
                ("tray", s.tray_source),
            )
            if matched and source == mine
        ]
        if matched and any(src == mine for src in s.tag_sources.values()):
            wins.append("tags")
        zone_lines = [
            [ln.text for ln in lines_in_zone(layout.lines, zone.box)]
            if layout is not None and not zone.is_picture
            else []
            for zone in rule.when.zones
        ]
        why = _why(rule, rec, folded, inbox_alias, special, layout, people, pictures)
        out.append(
            RuleExplain(
                rule.id,
                matched,
                why,
                wins,
                zone_lines,
                rule_areas(
                    rule,
                    layout,
                    matched=matched,
                    wins=bool(wins),
                    why=why,
                    rec=rec,
                    pictures=pictures,
                ),
            )
        )
    return out


def folder_of(path: str) -> str:
    """The folder a document is in (``""`` at the top)."""
    return _parent(path)
