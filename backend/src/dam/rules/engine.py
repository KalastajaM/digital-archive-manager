"""Apply rules and field detection to produce a filename/folder/tag suggestion."""

import re
import string
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import PurePosixPath
from typing import Literal

from dam.config import SpecialFolders
from dam.core.naming import fix_mojibake, matches_convention, parse_doc_date
from dam.core.paths import nfc
from dam.extract.layout import ZONE_MARGIN, Page1Layout, lines_in_zone
from dam.index.repo import BARCODE_EXTS, FileRecord
from dam.rules.fields import DetectedFields, detect_fields
from dam.rules.model import Rule, fold
from dam.rules.people import PeopleContext, detect_people, pick_person

_COPY_MARKER = re.compile(r"(?:\s*\(\d{1,3}\))+\s*$")
_ALLOWED_KEYS = frozenset({"doc_date", "year", "stem", "person"})
_REGEX_TIMEOUT = 0.2
_BIG_NUMBER = re.compile(r"\d{4,}")


@dataclass
class CodeHit:
    """A filing code found for a file: by the inbox folder it is in, a pen mark or a QR
    sticker. ``raw`` is what was read (pen, QR); ``unclear``: the reading is uncertain.

    It belongs with ``dam.codes.apply`` (which re-exports it) and lives here only to
    avoid an import cycle (``dam.codes.model`` imports this module)."""

    code: str
    via: Literal["folder", "pen", "qr"]
    raw: str | None = None
    unclear: bool = False


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


class TemplateError(ValueError):
    pass


class NeedsPerson(TemplateError):
    """The template has ``{person}`` and the document has no person (yet)."""


@dataclass
class PersonResult:
    name: str | None = None
    source: str | None = None
    found: list[str] = field(default_factory=list)


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
        return PersonResult(ctx.assigned, "assigned", found)
    one = pick_person(found)
    if one is None:
        return PersonResult(None, None, found)
    return PersonResult(one, f"rule:{rule.id}" if own_zone else "address area", found)


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


def _parent(rel: str) -> str:
    parent = PurePosixPath(rel).parent.as_posix()
    return "" if parent == "." else parent


@dataclass
class Check:
    matched: bool = False
    timed_out: bool = False
    # every other condition matched but the rule's page-1 area (or the person it needs)
    # could not be checked, because page 1 of this file has not been read yet
    waiting: bool = False
    # every other condition matched, but ``when.person`` has no person to compare (none
    # found on page 1, or several, or a file with no page 1): neither a match nor a mismatch
    person_unknown: bool = False


def zone_matches(rule: Rule, layout: Page1Layout) -> bool:
    """Any of the zone's words is in a line of page 1 that lies in the zone's box."""
    zone = rule.when.zone
    assert zone is not None
    for line in lines_in_zone(layout.lines, zone.box, ZONE_MARGIN):
        folded = fold(line.text)
        if any(t in folded for t in rule._folded_zone_terms):
            return True
    return False


def check(
    rule: Rule,
    rec: FileRecord,
    folded_text: str,
    inbox_alias: str | None = None,
    layout: Page1Layout | None = None,
    people: PeopleContext | None = None,
) -> Check:
    """Does ``rule`` match? ``folder_is`` matches the file's real folder, or
    ``inbox_alias`` (the inbox, for a file in a filing code's inbox folder). A rule with a
    ``zone`` needs ``layout`` (page 1's lines); without one it does not match, and
    ``waiting`` says whether reading page 1 could change that."""
    when = rule.when
    if when.folder_is is not None:
        want = nfc(when.folder_is).strip("/").casefold()
        here = {nfc(_parent(rec.path)).casefold()}
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
    if when.zone is not None:
        # page 1's lines are part of the indexed text, so a zone word that is not in the
        # document's text cannot be on page 1: no match, and nothing to wait for
        if not any(t in folded_text for t in rule._folded_zone_terms):
            return Check()
        if layout is None:
            return Check(waiting=(rec.ext or "").lower() in BARCODE_EXTS)
        if not zone_matches(rule, layout):
            return Check()
    if when.person is not None:
        mine = person_for(people, layout, rule)
        if mine.name is None:
            if layout is None and (rec.ext or "").lower() in BARCODE_EXTS:
                return Check(waiting=True)  # who it is for is on page 1, not read yet
            return Check(person_unknown=True)
        if fold(mine.name) != fold(when.person):
            return Check()
    return Check(matched=True)


def _matches(
    rule: Rule,
    rec: FileRecord,
    folded_text: str,
    inbox_alias: str | None = None,
    layout: Page1Layout | None = None,
    people: PeopleContext | None = None,
) -> tuple[bool, bool]:
    """Return ``(matched, regex_timed_out)`` (see ``check``)."""
    c = check(rule, rec, folded_text, inbox_alias, layout, people)
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


def _render_folder(
    template: str,
    doc_date: date | None,
    stem: str,
    special: SpecialFolders,
    person: str | None = None,
) -> str:
    folder = render(template, doc_date, stem, person)
    parts = folder.split("/")
    if folder.startswith("/") or any(p in ("", ".", "..") for p in parts) or "\0" in folder:
        raise TemplateError(f"invalid folder {folder!r}")
    folded = nfc(folder).casefold()
    for reserved in (special.inbox, special.quarantine):
        r = nfc(reserved).strip("/").casefold()
        if folded == r or folded.startswith(r + "/"):
            raise TemplateError(f"folder {folder!r} is a special folder")
    return folder


def _render_name(
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
) -> Suggestion:
    """``inbox_alias``: for a file directly in a filing code's inbox folder, the inbox,
    so a rule whose ``folder_is`` is the inbox matches it as well (a rule naming the
    code's folder itself still matches only that folder). ``layout``: page 1's lines,
    for rules with a ``zone``. ``people``: the people list, the address zone and the
    document's assigned person, for ``{person}`` and ``when.person``."""
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
        c = check(r, rec, folded_text, inbox_alias, layout, people)
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
                folder = _render_folder(rule.then.folder, doc_date, stem, special, mine.name)
                folder_rule = rule
                if template_uses_person(rule.then.folder) and rule.person_zone:
                    person_rule = rule
            except NeedsPerson:
                pass  # no person: this rule gives no folder, the next one may
            except TemplateError:
                errored = True
        if new_name is None and not conventional and rule.then.name is not None:
            try:
                new_name = _render_name(rule.then.name, doc_date, stem, ext, mine.name)
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
        sources.append(f"rule:{rule.id}" + (" (template error)" if errored else ""))

    who = person_for(people, layout, person_rule)

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
        tray_source=f"rule:{tray_rule.id}" if tray_rule and tray_rule.then.tray else None,
        waiting_for_page1=waiting,
        person=who.name,
        person_source=who.source,
        people_found=who.found,
    )
