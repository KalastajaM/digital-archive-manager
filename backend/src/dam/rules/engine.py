"""Apply rules and field detection to produce a filename/folder/tag suggestion."""

import re
import string
import time
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import PurePosixPath
from typing import Literal

from dam.config import SpecialFolders
from dam.core.naming import fix_mojibake, matches_convention, parse_doc_date
from dam.core.paths import nfc
from dam.extract.layout import ZONE_MARGIN, Box, Line, Page1Layout, lines_in_zone
from dam.index.repo import BARCODE_EXTS, FileRecord
from dam.rules.fields import DetectedFields, detect_fields
from dam.rules.model import Rule, fold
from dam.rules.people import PeopleContext, detect_people, person_line, pick_person
from dam.rules.picture import Match, Pictures
from dam.rules.timings import Timings

_COPY_MARKER = re.compile(r"(?:\s*\(\d{1,3}\))+\s*$")
_ALLOWED_KEYS = frozenset({"doc_date", "year", "stem", "person"})
_REGEX_TIMEOUT = 0.2
_BIG_NUMBER = re.compile(r"\d{4,}")


@dataclass
class CodeHit:
    """A filing code found for a file: by the inbox folder it is in, a pen mark, a QR
    sticker, or given by the owner in the app (``assigned``). ``raw`` is what was read
    (pen, QR); ``unclear``: the reading is uncertain; ``overridden``: an assigned code
    replaces this one, so it sets nothing.

    It belongs with ``dam.codes.apply`` (which re-exports it) and lives here only to
    avoid an import cycle (``dam.codes.model`` imports this module)."""

    code: str
    via: Literal["folder", "pen", "qr", "assigned"]
    raw: str | None = None
    unclear: bool = False
    overridden: bool = False


@dataclass
class Area:
    """An area of page 1 that took part in a rule or in finding the person, for drawing on
    the page. ``kind``: "text" (a rule's words), "image" (a rule's picture) or
    "address" (where people are looked for: ``rule_id`` is "" for the archive's own area).
    ``lines``: boxes of the lines that matched (the person's line for an address area; for a
    picture the place where it fits best).
    ``matched``: the rule matched the document; ``reason``: why this area or its rule did
    not (a short phrase); ``wins``: the rule gave the document its folder or name;
    ``score``: for a picture, how well it matched (0 to 1)."""

    rule_id: str
    index: int
    box: Box
    kind: Literal["text", "image", "address"]
    lines: list[Box] = field(default_factory=list)
    score: float | None = None
    matched: bool = True
    reason: str | None = None
    wins: bool = False


@dataclass
class PersonLine:
    """The line of page 1 where the document's person was found."""

    box: Box


@dataclass
class Suggestion:
    name: str
    folder: str | None = None
    tags: list[str] = field(default_factory=list)
    fields: DetectedFields = field(default_factory=DetectedFields)
    doc_date: date | None = None
    sources: list[str] = field(default_factory=list)
    # from the rule that gives the folder (else the first matching rule naming either)
    tray: str | None = None
    payee: str | None = None
    # where each field came from, for the pick-one chips: "rule:<id>", or "scan" for a
    # name made from the file's own name and date (None: no folder suggested)
    name_source: str = "scan"
    folder_source: str | None = None
    tag_sources: dict[str, str] = field(default_factory=dict)
    # filled by filing codes (``dam.codes.apply``): sources are "code:<CODE>"
    collections: list[str] = field(default_factory=list)
    tray_source: str | None = None
    collection_sources: dict[str, str] = field(default_factory=dict)
    codes: list[CodeHit] = field(default_factory=list)
    # two codes gave different values for the folder, name or tray (the first is kept)
    conflict: bool = False
    # the folder the rules (or similar files) gave before codes were applied; the AI
    # exclusion guard checks it as well as ``folder`` (None: no code was applied)
    folder_before_codes: str | None = None
    # a QR sticker's tick boxes (``dam.codes.apply.apply_ticks``): True when a sticker
    # has the box ticked, False when every boxed sticker has it empty, None when no
    # sticker has boxes or the box could not be read; ``marks_unclear``: a box could not
    # be read (and no other sticker has it ticked)
    star: bool | None = None
    important: bool | None = None
    marks_unclear: bool = False
    # a rule with a page-1 area could not be checked because page 1 has not been read yet
    # (its other conditions matched): the Inbox says "Reading page 1..."
    waiting_for_page1: bool = False
    # why page 1 cannot be read now (no OCR engine, missing, took too long): set by the
    # inbox service instead of ``waiting_for_page1``, which is then false
    page1_unavailable: str | None = None
    # who the document is for: the owner's assignment, else the one person found in the
    # address area of page 1 (or in the person_zone of the rule that gave the folder or
    # name). ``person_source``: "assigned", "address area" or "rule:<id>"; ``people_found``
    # all the people found in the address area (two or more: no person, the UI asks)
    person: str | None = None
    person_source: str | None = None
    people_found: list[str] = field(default_factory=list)
    # the areas of page 1 behind this suggestion: the areas of every rule that matched and
    # the address area used; ``person_line``: the box of the line where the person was found
    areas: list[Area] = field(default_factory=list)
    person_line: PersonLine | None = None


class TemplateError(ValueError):
    pass


class NeedsPerson(TemplateError):
    """The template has ``{person}`` and the document has no person (yet)."""


@dataclass
class PersonResult:
    name: str | None = None
    source: str | None = None
    found: list[str] = field(default_factory=list)
    zone: Box | None = None  # where people were looked for
    line: Box | None = None  # where the person was found in it


def person_for(
    ctx: PeopleContext | None, layout: Page1Layout | None, rule: Rule | None = None
) -> PersonResult:
    """The document's person: the owner's assignment beats what page 1 says. Found in the
    ``person_zone`` of ``rule`` when it has one, else in the archive's address zone."""
    if ctx is None:
        return PersonResult()
    own_zone = rule is not None and rule.person_zone is not None
    zone = rule.person_zone if own_zone else ctx.address_zone
    found = detect_people(layout, zone, ctx.people)
    if ctx.assigned:
        return PersonResult(
            ctx.assigned,
            "assigned",
            found,
            tuple(zone),
            person_line(layout, zone, ctx.people, ctx.assigned) if ctx.assigned in found else None,
        )
    one = pick_person(found)
    if one is None:
        return PersonResult(None, None, found, tuple(zone))
    return PersonResult(
        one,
        f"rule:{rule.id}" if own_zone else "address area",
        found,
        tuple(zone),
        person_line(layout, zone, ctx.people, one),
    )


def template_uses_person(template: str | None) -> bool:
    if template is None:
        return False
    try:
        return any(name == "person" for _, name, _, _ in string.Formatter().parse(template))
    except ValueError:
        return False


def rule_needs_person(rule: Rule) -> bool:
    """The rule's folder or name has ``{person}``, or it only matches one person."""
    return (
        rule.when.person is not None
        or template_uses_person(rule.then.folder)
        or template_uses_person(rule.then.name)
    )


def _no_controls(s: str) -> str:
    return "".join(c for c in s if not unicodedata.category(c).startswith("C"))


def clean_stem(stem: str) -> str:
    s = _COPY_MARKER.sub("", _no_controls(nfc(stem)))
    # characters Windows and cloud drives refuse (guards refuse them in new names)
    s = re.sub(r'[<>:"|?*\\/]', "_", s)
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"^(?:~\$)+", "", s)
    s = re.sub(r"_+", "_", s)
    return s.strip("_.")


def _fit(stem: str, prefix: str, suffix: str) -> str:
    """Truncate ``stem`` so ``prefix + stem + suffix`` fits in 255 UTF-8 bytes."""
    budget = max(1, 255 - len((prefix + suffix).encode()))
    raw = stem.encode()
    if len(raw) <= budget:
        return stem
    return raw[:budget].decode(errors="ignore").rstrip("._ ") or "x"


def parent_folder(rel: str) -> str:
    parent = PurePosixPath(rel).parent.as_posix()
    return "" if parent == "." else parent


@dataclass
class Check:
    matched: bool = False
    timed_out: bool = False
    # every other condition matched but the rule's page-1 area (or the person it needs)
    # could not be checked, because page 1 of this file has not been read yet (or its
    # picture has not been made)
    waiting: bool = False
    # every other condition matched, but ``when.person`` has no person to compare (none
    # found on page 1, or several, or a file with no page 1): neither a match nor a mismatch
    person_unknown: bool = False
    # the lowest score of the rule's picture areas, when they were looked at (also when the
    # rule did not match because of it): the replay shows how well matches and non-matches
    # are told apart
    picture_score: float | None = None
    # the score the failing picture area needed (set only when a picture area is what the
    # rule failed on, every other condition having held): a near miss is judged by it
    picture_needed: float | None = None


def has_text_zones(rule: Rule) -> bool:
    return any(not z.is_picture for z in rule.when.zones)


def has_picture_zones(rule: Rule) -> bool:
    return any(z.is_picture for z in rule.when.zones)


def zone_hits(rule: Rule, index: int, layout: Page1Layout) -> list[Line]:
    """The lines of page 1 in the rule's zone ``index`` that have one of its words."""
    zone = rule.when.zones[index]
    tests = rule._zone_tests[index]
    return [
        line
        for line in lines_in_zone(layout.lines, zone.box, ZONE_MARGIN)
        if line_has_word(tests, fold(line.text))
    ]


def line_has_word(tests, folded_line: str) -> bool:
    """One of a zone's word tests (``Rule._zone_tests``) holds for the folded line."""
    return any(t(folded_line) for t in tests)


def zone_matches(rule: Rule, index: int, layout: Page1Layout) -> bool:
    """Any of the zone's words is in a line of page 1 that lies in the zone's box."""
    return bool(zone_hits(rule, index, layout))


def zones_in_text(rule: Rule, folded_text: str) -> bool:
    """Every text zone has one of its words in the document's text. Page 1's lines are
    part of the indexed text, so a zone whose words are not there cannot match."""
    return all(
        line_has_word(tests, folded_text)
        for zone, tests in zip(rule.when.zones, rule._zone_tests, strict=True)
        if not zone.is_picture
    )


def zones_match(rule: Rule, layout: Page1Layout) -> bool:
    """Every text zone matches page 1."""
    return all(
        zone_matches(rule, i, layout)
        for i, zone in enumerate(rule.when.zones)
        if not zone.is_picture
    )


def picture_match(
    rule: Rule,
    index: int,
    rec: FileRecord,
    pictures: Pictures | None,
    timings: Timings | None = None,
) -> Match | None:
    """How well the picture of the rule's zone ``index`` appears on page 1 of ``rec``;
    None when that cannot be told yet (no page-1 picture made, or no picture support)."""
    zone = rule.when.zones[index]
    if pictures is None or zone.image is None:
        return None
    return pictures.match(zone.image, zone.box, rec.drive_id, rec.sha256, timings)


def rule_areas(
    rule: Rule,
    layout: Page1Layout | None,
    *,
    matched: bool = True,
    wins: bool = False,
    why: str | None = None,
    rec: FileRecord | None = None,
    pictures: Pictures | None = None,
) -> list[Area]:
    """The areas of ``rule`` for drawing: the matched lines of each text zone, the best
    place and the score of each picture zone (``rec`` and ``pictures`` look at the
    document's page-1 picture). For a rule that did not match, ``why`` is the reason shown
    for every area that matched itself; an area that did not match says so itself."""
    out: list[Area] = []
    many = len(rule.when.zones) > 1
    for i, zone in enumerate(rule.when.zones):
        reason = None
        lines: list[Box] = []
        if zone.is_picture:
            found = picture_match(rule, i, rec, pictures) if rec is not None else None
            score = None
            if found is None:
                reason = "the picture of page 1 is not made yet"
            else:
                score = found.score
                lines = [found.box] if found.box is not None else []
                if found.score < zone.threshold:
                    reason = f"picture {found.score:.2f}, needs {zone.threshold:.2f}"
            if reason is None and not matched:
                reason = why
            out.append(
                Area(
                    rule.id,
                    i,
                    zone.box,
                    "image",
                    lines,
                    score=score,
                    matched=matched,
                    reason=reason,
                    wins=wins,
                )
            )
            continue
        if layout is None:
            reason = "page 1 has not been read yet"
        else:
            hits = zone_hits(rule, i, layout)
            lines = [line.box for line in hits]
            if not hits:
                reason = f"no word found in {'area ' + str(i + 1) if many else 'the area'}"
        if reason is None and not matched:
            reason = why
        out.append(
            Area(
                rule.id,
                i,
                zone.box,
                "text",
                lines,
                matched=matched,
                reason=reason,
                wins=wins,
            )
        )
    return out


def check(
    rule: Rule,
    rec: FileRecord,
    folded_text: str,
    inbox_alias: str | None = None,
    layout: Page1Layout | None = None,
    people: PeopleContext | None = None,
    pictures: Pictures | None = None,
    timings: Timings | None = None,
) -> Check:
    """Does ``rule`` match? ``folder_is`` matches the file's real folder, or
    ``inbox_alias`` (the inbox, for a file in a filing code's inbox folder). A rule with a
    ``zones`` need ``layout`` (page 1's lines); without one it does not match, and
    ``waiting`` says whether reading page 1 could change that. A picture zone is looked at
    in ``pictures`` (page-1 pictures from the cache), last, after every cheaper condition
    (the folder, the words, the file name and every text area: a document that fails one of
    those never gets a picture score, so it is never taken for a near miss);
    a document with no page-1 picture yet is waiting for it, like a missing layout."""
    when = rule.when
    score: float | None = None
    if when.folder_is is not None:
        want = nfc(when.folder_is).strip("/").casefold()
        here = {nfc(parent_folder(rec.path)).casefold()}
        if inbox_alias is not None:
            here.add(nfc(inbox_alias).strip("/").casefold())
        if want not in here:
            return Check()
    if rule._folded_terms and not any(t in folded_text for t in rule._folded_terms):
        return Check()
    if rule._regex is not None:
        try:
            if not rule._regex.search(nfc(rec.name or ""), timeout=_REGEX_TIMEOUT):
                return Check()
        except TimeoutError:
            return Check(timed_out=True)
    if when.zones:
        # a zone word that is not in the document's text cannot be on page 1: no match,
        # and nothing to wait for
        if not zones_in_text(rule, folded_text):
            return Check()
        on_page1 = (rec.ext or "").lower() in BARCODE_EXTS
        if has_text_zones(rule):
            if layout is None:
                return Check(waiting=on_page1)
            started = time.perf_counter() if timings is not None else 0.0
            in_areas = zones_match(rule, layout)
            if timings is not None:
                timings.zones += time.perf_counter() - started
            if not in_areas:
                return Check()
        for i, zone in enumerate(when.zones):
            if not zone.is_picture:
                continue
            found = picture_match(rule, i, rec, pictures, timings)
            if found is None:
                return Check(waiting=on_page1)
            score = found.score if score is None else min(score, found.score)
            if found.score < zone.threshold:
                return Check(picture_score=score, picture_needed=zone.threshold)
    if when.person is not None:
        mine = person_for(people, layout, rule)
        if mine.name is None:
            if layout is None and (rec.ext or "").lower() in BARCODE_EXTS:
                return Check(waiting=True)  # who it is for is on page 1, not read yet
            return Check(person_unknown=True, picture_score=score)
        if fold(mine.name) != fold(when.person):
            # the picture passed: it was not what failed, so it reports no score
            return Check()
    return Check(matched=True, picture_score=score)


def rule_matches(
    rule: Rule,
    rec: FileRecord,
    folded_text: str,
    inbox_alias: str | None = None,
    layout: Page1Layout | None = None,
    people: PeopleContext | None = None,
    pictures: Pictures | None = None,
) -> tuple[bool, bool]:
    """Return ``(matched, regex_timed_out)`` (see ``check``)."""
    c = check(rule, rec, folded_text, inbox_alias, layout, people, pictures)
    return c.matched, c.timed_out


def check_template(template: str, allowed: frozenset[str] = _ALLOWED_KEYS) -> None:
    """Allow only plain fields from ``allowed`` (rules: ``{doc_date}``/``{year}``/``{stem}``)
    with a simple format spec: no attribute or index access, no conversions."""
    try:
        parsed = list(string.Formatter().parse(template))
    except ValueError as e:
        raise TemplateError(str(e)) from e
    for _, field_name, spec, conversion in parsed:
        if field_name is None:
            continue
        if conversion is not None:
            raise TemplateError("conversions are not allowed")
        if field_name not in allowed:
            raise TemplateError(f"unknown or unsafe field {field_name!r}")
        spec = spec or ""
        if "{" in spec or "}" in spec or _BIG_NUMBER.search(spec):
            raise TemplateError("unsupported format spec")


def render(template: str, doc_date: date | None, stem: str, person: str | None = None) -> str:
    check_template(template)
    if person is None and template_uses_person(template):
        raise NeedsPerson("the document has no person")
    values: dict[str, object] = {"stem": stem}
    if person is not None:
        values["person"] = person
    if doc_date is not None:
        values["doc_date"] = doc_date
        values["year"] = doc_date.year
    try:
        return template.format_map(values)
    except (KeyError, ValueError, TypeError, IndexError, AttributeError) as e:
        raise TemplateError(str(e)) from e


def render_folder(
    template: str,
    doc_date: date | None,
    stem: str,
    special: SpecialFolders,
    person: str | None = None,
    quarantines: Sequence[str] = (),
) -> str:
    """``quarantines``: every archive folder's To Delete (``ArchivePaths.quarantines``),
    none of which a rule may file into; empty for the main folder's only."""
    folder = render(template, doc_date, stem, person)
    parts = folder.split("/")
    if folder.startswith("/") or any(p in ("", ".", "..") for p in parts) or "\0" in folder:
        raise TemplateError(f"invalid folder {folder!r}")
    folded = nfc(folder).casefold()
    for reserved in (special.inbox, *(quarantines or (special.quarantine,))):
        r = nfc(reserved).strip("/").casefold()
        if folded == r or folded.startswith(r + "/"):
            raise TemplateError(f"folder {folder!r} is a special folder")
    return folder


def render_name(
    template: str, doc_date: date | None, stem: str, ext: str, person: str | None = None
) -> str:
    name = render(template, doc_date, stem, person).strip()
    if ext and name.lower().endswith("." + ext):
        name = name[: -len(ext) - 1]
    if not name or name.startswith((".", "~$")) or "/" in name or _no_controls(name) != name:
        raise TemplateError(f"invalid name {name!r}")
    name = name.rstrip(". ")
    if not name:
        raise TemplateError("empty name")
    return _fit(name, "", "." + ext if ext else "")


def _stem(name: str, suffix: str) -> str:
    raw_stem = name[: -len(suffix)] if suffix and name.lower().endswith(suffix) else name
    return clean_stem(raw_stem) or "document"


def stem_and_ext(rec: FileRecord) -> tuple[str, str, str]:
    """The ``{stem}`` templates see for ``rec``, its lower-case extension (no dot) and
    the file's own name (mojibake fixed), as ``suggest`` computes them. The name is
    what the naming-convention check looks at, never the suggested (dated) name."""
    ext = (rec.ext or "").lower()
    name = fix_mojibake(rec.name or PurePosixPath(rec.path).name)
    return _stem(name, f".{ext}" if ext else ""), ext, name


def suggest(
    rec: FileRecord,
    text: str,
    rules: list[Rule],
    special: SpecialFolders | None = None,
    inbox_alias: str | None = None,
    layout: Page1Layout | None = None,
    people: PeopleContext | None = None,
    pictures: Pictures | None = None,
    quarantines: Sequence[str] = (),
) -> Suggestion:
    """``inbox_alias``: for a file directly in a filing code's inbox folder, the inbox,
    so a rule whose ``folder_is`` is the inbox matches it as well (a rule naming the
    code's folder itself still matches only that folder). ``layout``: page 1's lines,
    for rules with ``zones``. ``people``: the people list, the address zone and the
    document's assigned person, for ``{person}`` and ``when.person``. ``pictures``: the
    page-1 pictures, for rules with picture areas. ``quarantines``: the To Delete folders
    no rule may file into (``render_folder``)."""
    special = special or SpecialFolders()
    name = rec.name or PurePosixPath(rec.path).name
    ext = (rec.ext or "").lower()
    suffix = f".{ext}" if ext else ""
    detected = detect_fields(text)
    sources: list[str] = []

    doc_date = parse_doc_date(name)
    if doc_date is not None:
        sources.append("filename-date")
    elif detected.dates:
        doc_date = detected.dates[0]
        sources.append("text-date")
    elif rec.mtime is not None:
        try:
            doc_date = date.fromtimestamp(rec.mtime)
            sources.append("mtime")
        except (OverflowError, OSError, ValueError):
            doc_date = None

    name = fix_mojibake(name)
    stem = _stem(name, suffix)

    folded_text = fold(text)
    matching: list[Rule] = []
    waiting = False
    for r in rules:
        c = check(r, rec, folded_text, inbox_alias, layout, people, pictures)
        if c.timed_out:
            sources.append(f"rule:{r.id} (regex timeout)")
        elif c.matched:
            matching.append(r)
        elif c.waiting:
            waiting = True

    conventional = matches_convention(name)
    new_name: str | None = None
    folder: str | None = None
    tags: list[str] = []
    tag_sources: dict[str, str] = {}
    collections: list[str] = []
    collection_sources: dict[str, str] = {}
    folder_rule: Rule | None = None
    name_rule: Rule | None = None
    person_rule: Rule | None = None  # a rule that used its own person_zone for what it gave
    for rule in matching:
        errored = False
        mine = person_for(people, layout, rule)
        needs = template_uses_person(rule.then.folder) or template_uses_person(rule.then.name)
        if needs and mine.name is None and layout is None:
            if (rec.ext or "").lower() in BARCODE_EXTS and not (people and people.assigned):
                waiting = True  # who the letter is for is on page 1, not read yet
        if folder is None and rule.then.folder is not None:
            try:
                folder = render_folder(
                    rule.then.folder, doc_date, stem, special, mine.name, quarantines
                )
                folder_rule = rule
                if template_uses_person(rule.then.folder) and rule.person_zone:
                    person_rule = rule
            except NeedsPerson:
                pass  # no person: this rule gives no folder, the next one may
            except TemplateError:
                errored = True
        if new_name is None and not conventional and rule.then.name is not None:
            try:
                new_name = render_name(rule.then.name, doc_date, stem, ext, mine.name)
                name_rule = rule
                if template_uses_person(rule.then.name) and rule.person_zone:
                    person_rule = person_rule or rule
            except NeedsPerson:
                pass
            except TemplateError:
                errored = True
        for tag in rule.then.tags:
            if tag not in tags:
                tags.append(tag)
                tag_sources[tag] = f"rule:{rule.id}"
        for coll in rule.then.collections:
            if coll not in collections:
                collections.append(coll)
                collection_sources[coll] = f"rule:{rule.id}"
        sources.append(f"rule:{rule.id}" + (" (template error)" if errored else ""))

    who = person_for(people, layout, person_rule)

    winners = {r.id for r in (folder_rule, name_rule) if r is not None}
    areas = [
        a
        for r in matching
        for a in rule_areas(r, layout, wins=r.id in winners, rec=rec, pictures=pictures)
    ]
    if layout is not None and people is not None and people.people and who.zone is not None:
        areas.append(
            Area(
                person_rule.id if person_rule is not None else "",
                0,
                who.zone,
                "address",
                [who.line] if who.line is not None else [],
            )
        )

    if conventional:
        final = name[: -len(suffix)] + suffix if suffix and name.lower().endswith(suffix) else name
    elif new_name is not None:
        final = new_name + suffix
    elif matches_convention(stem) or doc_date is None:
        final = _fit(stem, "", suffix) + suffix
    else:
        prefix = f"{doc_date:%Y%m%d}_"
        final = prefix + _fit(stem, prefix, suffix) + suffix

    # tray and payee come from one rule, never mixed: the one that gave the folder,
    # else (no rule gave one) the first matching rule that names a tray or a payee.
    # (A filing code may later replace the tray and keep this payee: ``apply_codes``.)
    tray_rule = folder_rule or next(
        (r for r in matching if r.then.tray is not None or r.then.payee is not None), None
    )

    return Suggestion(
        name=final,
        folder=folder,
        tags=tags,
        fields=detected,
        doc_date=doc_date,
        sources=sources,
        tray=tray_rule.then.tray if tray_rule else None,
        payee=tray_rule.then.payee if tray_rule else None,
        name_source=f"rule:{name_rule.id}" if name_rule is not None else "scan",
        folder_source=f"rule:{folder_rule.id}" if folder_rule is not None else None,
        tag_sources=tag_sources,
        collections=collections,
        collection_sources=collection_sources,
        tray_source=f"rule:{tray_rule.id}" if tray_rule and tray_rule.then.tray else None,
        waiting_for_page1=waiting,
        person=who.name,
        person_source=who.source,
        people_found=who.found,
        areas=areas,
        person_line=PersonLine(who.line) if who.line is not None else None,
    )
