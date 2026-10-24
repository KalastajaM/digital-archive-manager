"""Prove a rule against the past: what would it have done to the files already filed?

``replay`` runs one rule over every indexed file outside the special folders and
compares the path it would give with the path the file has. ``explain`` says, for one
document, which rules match and which of them wins each field.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from sqlalchemy import Engine, select

from dam.config import SpecialFolders
from dam.core.naming import _DATE_PREFIX, parse_doc_date
from dam.core.paths import nfc
from dam.db.tables import file_text, files
from dam.index.repo import FileRecord
from dam.ops.guards import is_under
from dam.rules.engine import (
    TemplateError,
    _matches,
    _parent,
    _render_folder,
    _render_name,
    stem_and_ext,
    suggest,
)
from dam.rules.model import Rule, fold


@dataclass
class ReplayHit:
    drive_id: str
    path_now: str
    path_rule: str  # "" when the rule's template cannot be rendered for this file


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


@dataclass
class RuleExplain:
    rule_id: str
    matched: bool
    why: str
    wins: list[str] = field(default_factory=list)


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


def _rule_path(rule: Rule, rec: FileRecord, special: SpecialFolders) -> str:
    name = rec.name or PurePosixPath(rec.path).name
    ext = (rec.ext or "").lower()
    doc_date = parse_doc_date(name) or rec.doc_date
    stem = _replay_stem(rec)
    if rule.then.folder is not None:
        folder = _render_folder(rule.then.folder, doc_date, stem, special)
    else:
        folder = _parent(rec.path)
    if rule.then.name is not None:
        new = _render_name(rule.then.name, doc_date, stem, ext) + (f".{ext}" if ext else "")
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
) -> ReplayResult:
    """``rules`` is the load order with ``rule`` in its place. For filed files
    ``folder_is`` is ignored: a rule meant for the inbox is judged on the files it would
    have filed. Inbox files are only counted (``inbox``), when the rule as written, with
    its ``folder_is``, matches them as live filing would; ``inbox_code_of`` tells which
    files sit in a filing code's inbox folder (they count as in the inbox)."""
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
    cols = [files.c.drive_id, files.c.path, files.c.name, files.c.ext, files.c.doc_date]
    result = ReplayResult(0, 0, [], 0, [], 0, 0, False)

    def skipped(path: str) -> bool:
        return any(is_under(path, base) for base in others)

    with engine.connect() as conn:
        # paths only, to say how many filed files there are even when the budget runs out
        joined = files.join(file_text, file_text.c.drive_id == files.c.drive_id)
        for (path,) in conn.execute(select(files.c.path).select_from(joined).where(*where)):
            if not skipped(path) and not is_under(path, special.inbox):
                result.total += 1
        rows = conn.execute(
            select(*cols, file_text.c.text).select_from(joined).where(*where).order_by(files.c.path)
        )
        for row in rows:
            if skipped(row.path):
                continue
            if time.monotonic() - started >= budget_s:
                result.truncated = True
                break
            folded = fold(row.text or "")
            rec = FileRecord(
                drive_id=row.drive_id,
                path=row.path,
                name=row.name,
                ext=row.ext,
                doc_date=row.doc_date,
            )
            if is_under(row.path, special.inbox):
                code = inbox_code_of(row.path) if inbox_code_of is not None else None
                alias = special.inbox if code is not None else None
                if _matches(rule, rec, folded, alias)[0]:
                    result.inbox += 1
                continue
            result.checked += 1
            if not _matches(free, rec, folded)[0]:
                continue
            result.matched += 1
            try:
                path_rule = _rule_path(rule, rec, special)
            except TemplateError:
                path_rule = ""
            if path_rule and nfc(path_rule).casefold() == nfc(row.path).casefold():
                result.same += 1
            else:
                result.different.append(ReplayHit(row.drive_id, row.path, path_rule))
            for r in earlier:
                if _matches(r, rec, folded)[0]:
                    result.shadowed.append((row.drive_id, r.id))
                    break
    return result


def _why(rule: Rule, rec: FileRecord, folded_text: str, inbox_alias: str | None, special) -> str:
    when = rule.when
    ok, timed_out = _matches(rule, rec, folded_text, inbox_alias)
    if ok:
        parts = [
            f"word ‘{raw}’"
            for raw, term in zip(when.text_contains, rule._folded_terms, strict=True)
            if term in folded_text
        ][:1]
        if when.filename_matches is not None:
            parts.append(f"file name matches {when.filename_matches}")
        if not parts and when.folder_is is not None:
            parts.append(f"in the folder ‘{when.folder_is}’")
        return ", ".join(parts) or "no condition: matches every file"
    if timed_out:
        return "file name check took too long"
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
    return "file name does not match"


def explain(
    rec: FileRecord,
    text: str,
    rules: list[Rule],
    special: SpecialFolders,
    inbox_alias: str | None,
) -> list[RuleExplain]:
    """For each rule: does it match this document, why (not), and which fields it wins."""
    folded = fold(text)
    s = suggest(rec, text, rules, special, inbox_alias)
    out: list[RuleExplain] = []
    for rule in rules:
        mine = f"rule:{rule.id}"
        matched = _matches(rule, rec, folded, inbox_alias)[0]
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
        out.append(
            RuleExplain(rule.id, matched, _why(rule, rec, folded, inbox_alias, special), wins)
        )
    return out
