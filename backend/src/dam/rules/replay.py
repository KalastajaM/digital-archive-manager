"""Prove a rule against the past: what would it have done to the files already filed?

``replay`` runs one rule over every indexed file outside the special folders and
compares the path it would give with the path the file has. ``explain`` says, for one
document, which rules match and which of them wins each field.
"""

import re
import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from sqlalchemy import Engine, select, text

from dam.config import Person, SpecialFolders
from dam.core.naming import _DATE_PREFIX, parse_doc_date
from dam.core.paths import nfc
from dam.db.tables import file_text, files
from dam.extract.layout import ZONE_MARGIN, Page1Layout, lines_in_zone
from dam.index.repo import BARCODE_EXTS, FileRecord
from dam.ops.guards import is_under
from dam.rules.engine import (
    TemplateError,
    _matches,
    _parent,
    _render_folder,
    _render_name,
    check,
    person_for,
    rule_needs_person,
    stem_and_ext,
    suggest,
    template_uses_person,
    zone_matches,
)
from dam.rules.model import Rule, fold
from dam.rules.people import PeopleContext


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


MAX_CANDIDATES = 20000  # more words hits than this: no narrowing, every file is looked at


def zone_candidates(engine: Engine, rule: Rule) -> set[str] | None:
    """The drive ids whose indexed text can contain one of the zone's words: one FTS
    query over the text column. A line in a zone is part of page 1's text, which is part of
    the indexed text, so no other document can match. None: not narrowed (a word without
    letters or digits cannot be searched, or there are too many hits)."""
    zone = rule.when.zone
    assert zone is not None
    phrases = []
    for term in zone.text_contains:
        tokens = re.findall(r"\w+", term)
        if not tokens:
            return None
        phrases.append('"' + " ".join(t.replace('"', '""') for t in tokens) + '"*')
    match = "text : (" + " OR ".join(phrases) + ")"
    with engine.connect() as conn:
        found = conn.execute(
            text("SELECT drive_id FROM file_fts WHERE file_fts MATCH :q LIMIT :n"),
            {"q": match, "n": MAX_CANDIDATES + 1},
        ).scalars()
        ids = set(found)
    return None if len(ids) > MAX_CANDIDATES else ids


@dataclass
class RuleExplain:
    rule_id: str
    matched: bool
    why: str
    wins: list[str] = field(default_factory=list)
    zone_lines: list[str] = field(default_factory=list)  # page-1 lines in the rule's zone


def _without_folder(rule: Rule) -> Rule:
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
) -> ReplayResult:
    """``rules`` is the load order with ``rule`` in its place. For filed files
    ``folder_is`` is ignored: a rule meant for the inbox is judged on the files it would
    have filed. Inbox files are only counted (``inbox``), when the rule as written, with
    its ``folder_is``, matches them as live filing would; ``inbox_code_of`` tells which
    files sit in a filing code's inbox folder (they count as in the inbox).

    A rule with a ``zone`` is looked at in the documents whose text has one of its words
    (``zone_candidates``, one FTS query). Those among them without a page-1 layout are
    handed to ``want_layouts`` and listed in ``not_checked`` with the reason
    (``layout_blocked`` says why a read cannot happen now); they are never counted as
    non-matches.

    ``{person}`` and ``when.person`` use the document's person: its assignment
    (``assigned_persons``: drive id -> person) if there is one, else the one found in the
    address area of page 1. A document whose person is unknown is not checked
    ("person unknown"), not a mismatch."""
    started = time.monotonic()
    free = _without_folder(rule)
    earlier: list[Rule] = []
    for r in rules:
        if r is rule:
            break
        earlier.append(r)
    earlier = [_without_folder(r) for r in earlier if r.then.folder or r.then.name]
    others = [special.ongoing, special.important, special.quarantine]
    where = (
        files.c.index_state == "indexed",
        files.c.is_dir.is_not(True),
        files.c.is_link.is_not(True),
        files.c.missing.is_not(True),
        files.c.parked_at.is_(None),
    )
    cols = [
        files.c.drive_id,
        files.c.path,
        files.c.name,
        files.c.ext,
        files.c.doc_date,
    ]
    result = ReplayResult(0, 0, [], 0, [], 0, 0, False)
    candidates = zone_candidates(engine, rule) if rule.when.zone is not None else None
    layouts: dict[str, Page1Layout] = {}
    needs_person = rule_needs_person(rule)
    needs_layouts = (
        rule.when.zone is not None
        or needs_person
        or any(r.when.zone is not None or rule_needs_person(r) for r in earlier)
    )
    assigned = assigned_persons() if assigned_persons is not None and needs_layouts else {}

    def context(drive_id: str) -> PeopleContext:
        return PeopleContext(people, tuple(address_zone), assigned.get(drive_id))

    if candidates is not None and layouts_for is not None:
        layouts = layouts_for(candidates)
    unread: list[str] = []  # candidates (filed or in the inbox) to hand to the layout pass
    evaluated = 0

    def layout_of(drive_id: str) -> Page1Layout | None:
        if drive_id not in layouts and layouts_for is not None and needs_layouts:
            layouts.update(layouts_for([drive_id]))
        return layouts.get(drive_id)

    def skipped(path: str) -> bool:
        return any(is_under(path, base) for base in others)

    def unreadable(drive_id: str) -> str:
        """Why page 1 of this document is not there: waiting for the layout pass, or
        something stops it."""
        return (layout_blocked(drive_id) if layout_blocked else None) or NOT_READ

    def not_checked(drive_id: str, path: str, reason: str) -> None:
        result.not_checked.append(NotChecked(path, reason))
        if reason == NOT_READ:
            unread.append(drive_id)

    with engine.connect() as conn:
        # paths only, to say how many filed files there are even when the budget runs out
        joined = files.join(file_text, file_text.c.drive_id == files.c.drive_id)
        for (path,) in conn.execute(select(files.c.path).select_from(joined).where(*where)):
            if not skipped(path) and not is_under(path, special.inbox):
                result.total += 1
        query = select(*cols, file_text.c.text).select_from(joined).where(*where)
        if candidates is not None:
            query = query.where(files.c.drive_id.in_(candidates))
        rows = conn.execute(query.order_by(files.c.path))
        for row in rows:
            if skipped(row.path):
                continue
            if time.monotonic() - started >= budget_s:
                result.truncated = True
                break
            evaluated += 1
            folded = fold(row.text or "")
            rec = FileRecord(
                drive_id=row.drive_id,
                path=row.path,
                name=row.name,
                ext=row.ext,
                doc_date=row.doc_date,
            )
            layout = layout_of(row.drive_id) if needs_layouts else None
            if is_under(row.path, special.inbox):
                code = inbox_code_of(row.path) if inbox_code_of is not None else None
                alias = special.inbox if code is not None else None
                c = check(rule, rec, folded, alias, layout, context(row.drive_id))
                if c.matched:
                    result.inbox += 1
                elif c.waiting:
                    unread.append(row.drive_id)
                continue
            ctx = context(row.drive_id)
            c = check(free, rec, folded, None, layout, ctx)

            if c.waiting:
                # every other condition holds: only page 1 is missing. Not a non-match.
                not_checked(row.drive_id, row.path, unreadable(row.drive_id))
                continue
            if c.person_unknown:
                not_checked(row.drive_id, row.path, PERSON_UNKNOWN)
                continue
            if not c.matched:
                result.checked += 1
                continue
            person = None
            if template_uses_person(rule.then.folder) or template_uses_person(rule.then.name):
                person = person_for(ctx, layout, rule).name
                if person is None:
                    supported = (row.ext or "").lower() in BARCODE_EXTS
                    if layout is None and supported and not ctx.assigned:
                        not_checked(row.drive_id, row.path, unreadable(row.drive_id))
                    else:
                        not_checked(row.drive_id, row.path, PERSON_UNKNOWN)
                    continue
            result.checked += 1
            result.matched += 1
            try:
                path_rule = _rule_path(rule, rec, special, person)
            except TemplateError:
                path_rule = ""
            if path_rule and nfc(path_rule).casefold() == nfc(row.path).casefold():
                result.same += 1
            else:
                result.different.append(ReplayHit(row.drive_id, row.path, path_rule))
            for r in earlier:
                if _matches(r, rec, folded, None, layout, ctx)[0]:
                    result.shadowed.append((row.drive_id, r.id))
                    break
    if candidates is not None:
        # a document without one of the zone's words in its text cannot match: checked
        left = max(0, len(candidates) - evaluated) if result.truncated else 0
        result.checked = max(0, result.total - left - len(result.not_checked))
    result.reading = len(unread)
    if unread and want_layouts is not None:
        want_layouts(unread)
    return result


def _why(
    rule: Rule,
    rec: FileRecord,
    folded_text: str,
    inbox_alias: str | None,
    special,
    layout: Page1Layout | None = None,
    people: PeopleContext | None = None,
) -> str:
    when = rule.when
    c = check(rule, rec, folded_text, inbox_alias, layout, people)
    if c.matched:
        parts = [
            f"word ‘{raw}’"
            for raw, term in zip(when.text_contains, rule._folded_terms, strict=True)
            if term in folded_text
        ][:1]
        if when.filename_matches is not None:
            parts.append(f"file name matches {when.filename_matches}")
        if when.zone is not None and layout is not None:
            hit = next(
                (
                    raw
                    for raw, term in zip(
                        when.zone.text_contains, rule._folded_zone_terms, strict=True
                    )
                    if any(
                        term in fold(ln.text)
                        for ln in lines_in_zone(layout.lines, when.zone.box, ZONE_MARGIN)
                    )
                ),
                None,
            )
            parts.append(f"word ‘{hit}’ in the area")
        if not parts and when.folder_is is not None:
            parts.append(f"in the folder ‘{when.folder_is}’")
        return ", ".join(parts) or "no condition: matches every file"
    if c.timed_out:
        return "file name check took too long"
    if c.waiting:
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
    if when.zone is not None and (rec.ext or "").lower() not in BARCODE_EXTS:
        return "no page 1 to look at in this kind of file"
    if (
        when.filename_matches is not None
        and rule._regex is not None
        and not rule._regex.search(nfc(rec.name or ""))
    ):
        return "file name does not match"
    if when.zone is not None and (layout is None or not zone_matches(rule, layout)):
        return "no word found in the area"
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
) -> list[RuleExplain]:
    """For each rule: does it match this document, why (not), and which fields it wins.
    For a rule with a zone, the page-1 lines in the zone (so a missed match can be
    explained)."""
    folded = fold(text)
    s = suggest(rec, text, rules, special, inbox_alias, layout=layout, people=people)
    out: list[RuleExplain] = []
    for rule in rules:
        mine = f"rule:{rule.id}"
        matched = _matches(rule, rec, folded, inbox_alias, layout, people)[0]
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
        zone = rule.when.zone
        zone_lines = (
            [ln.text for ln in lines_in_zone(layout.lines, zone.box, ZONE_MARGIN)]
            if zone is not None and layout is not None
            else []
        )
        out.append(
            RuleExplain(
                rule.id,
                matched,
                _why(rule, rec, folded, inbox_alias, special, layout, people),
                wins,
                zone_lines,
            )
        )
    return out
