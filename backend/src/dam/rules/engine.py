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
from dam.index.repo import FileRecord
from dam.rules.fields import DetectedFields, detect_fields
from dam.rules.model import Rule, fold

_COPY_MARKER = re.compile(r"(?:\s*\(\d{1,3}\))+\s*$")
_ALLOWED_KEYS = frozenset({"doc_date", "year", "stem"})
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


class TemplateError(ValueError):
    pass


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


def _matches(
    rule: Rule, rec: FileRecord, folded_text: str, inbox_alias: str | None = None
) -> tuple[bool, bool]:
    """Return ``(matched, regex_timed_out)``. ``folder_is`` matches the file's real
    folder, or ``inbox_alias`` (the inbox, for a file in a filing code's inbox folder)."""
    when = rule.when
    if when.folder_is is not None:
        want = nfc(when.folder_is).strip("/").casefold()
        here = {nfc(_parent(rec.path)).casefold()}
        if inbox_alias is not None:
            here.add(nfc(inbox_alias).strip("/").casefold())
        if want not in here:
            return False, False
    if rule._folded_terms and not any(t in folded_text for t in rule._folded_terms):
        return False, False
    if rule._regex is not None:
        try:
            if not rule._regex.search(nfc(rec.name or ""), timeout=_REGEX_TIMEOUT):
                return False, False
        except TimeoutError:
            return False, True
    return True, False


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


def render(template: str, doc_date: date | None, stem: str) -> str:
    check_template(template)
    values: dict[str, object] = {"stem": stem}
    if doc_date is not None:
        values["doc_date"] = doc_date
        values["year"] = doc_date.year
    try:
        return template.format_map(values)
    except (KeyError, ValueError, TypeError, IndexError, AttributeError) as e:
        raise TemplateError(str(e)) from e


def _render_folder(template: str, doc_date: date | None, stem: str, special: SpecialFolders) -> str:
    folder = render(template, doc_date, stem)
    parts = folder.split("/")
    if folder.startswith("/") or any(p in ("", ".", "..") for p in parts) or "\0" in folder:
        raise TemplateError(f"invalid folder {folder!r}")
    folded = nfc(folder).casefold()
    for reserved in (special.inbox, special.quarantine):
        r = nfc(reserved).strip("/").casefold()
        if folded == r or folded.startswith(r + "/"):
            raise TemplateError(f"folder {folder!r} is a special folder")
    return folder


def _render_name(template: str, doc_date: date | None, stem: str, ext: str) -> str:
    name = render(template, doc_date, stem).strip()
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
) -> Suggestion:
    """``inbox_alias``: for a file directly in a filing code's inbox folder, the inbox,
    so a rule whose ``folder_is`` is the inbox matches it as well (a rule naming the
    code's folder itself still matches only that folder)."""
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
    for r in rules:
        ok, timed_out = _matches(r, rec, folded_text, inbox_alias)
        if timed_out:
            sources.append(f"rule:{r.id} (regex timeout)")
        elif ok:
            matching.append(r)

    conventional = matches_convention(name)
    new_name: str | None = None
    folder: str | None = None
    tags: list[str] = []
    tag_sources: dict[str, str] = {}
    folder_rule: Rule | None = None
    name_rule: Rule | None = None
    for rule in matching:
        errored = False
        if folder is None and rule.then.folder is not None:
            try:
                folder = _render_folder(rule.then.folder, doc_date, stem, special)
                folder_rule = rule
            except TemplateError:
                errored = True
        if new_name is None and not conventional and rule.then.name is not None:
            try:
                new_name = _render_name(rule.then.name, doc_date, stem, ext)
                name_rule = rule
            except TemplateError:
                errored = True
        for tag in rule.then.tags:
            if tag not in tags:
                tags.append(tag)
                tag_sources[tag] = f"rule:{rule.id}"
        sources.append(f"rule:{rule.id}" + (" (template error)" if errored else ""))

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
    )
