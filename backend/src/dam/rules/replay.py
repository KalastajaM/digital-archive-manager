"""Prove a rule against the past: what would it have done to the files already filed?

``replay`` runs one rule over every indexed file outside the special folders and
compares the path it would give with the path the file has. ``explain`` says, for one
document, which rules match and which of them wins each field.
"""

import time
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


def _replay_stem(name: str, ext: str) -> str:
    stem = name[: -len(ext) - 1] if ext and name.lower().endswith("." + ext) else name
    if _DATE_PREFIX.match(stem):
        stem = stem[8:]
        if stem.startswith(("_", " ", "-", ".")):
            stem = stem[1:]
    return stem or "document"


def _rule_path(rule: Rule, rec: FileRecord, special: SpecialFolders) -> str:
    name = rec.name or PurePosixPath(rec.path).name
    ext = (rec.ext or "").lower()
    doc_date = rec.doc_date or parse_doc_date(name)
    stem = _replay_stem(name, ext)
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
) -> ReplayResult:
    """``rules`` is the load order with ``rule`` in its place. ``folder_is`` is ignored:
    a rule meant for the inbox is judged on the files it would have filed."""
    started = time.monotonic()
    free = _without_folder(rule)
    earlier: list[Rule] = []
    for r in rules:
        if r is rule:
            break
        earlier.append(r)
    earlier = [_without_folder(r) for r in earlier if r.then.folder or r.then.name]
    others = [special.ongoing, special.important, special.quarantine]
    cols = [files.c.drive_id, files.c.path, files.c.name, files.c.ext, files.c.doc_date]
    result = ReplayResult(0, 0, [], 0, [], 0, 0, False)
    with engine.connect() as conn:
        rows = [
            r
            for r in conn.execute(
                select(*cols)
                .join(file_text, file_text.c.drive_id == files.c.drive_id)
                .where(
                    files.c.index_state == "indexed",
                    files.c.is_dir.is_not(True),
                    files.c.is_link.is_not(True),
                    files.c.missing.is_not(True),
                    files.c.parked_at.is_(None),
                )
                .order_by(files.c.path)
            )
            if not any(is_under(r.path, base) for base in others)
        ]
        result.total = len(rows)
        for row in rows:
            if time.monotonic() - started >= budget_s:
                result.truncated = True
                break
            result.checked += 1
            if is_under(row.path, special.inbox):
                result.inbox += 1
                continue
            text = conn.execute(
                select(file_text.c.text).where(file_text.c.drive_id == row.drive_id)
            ).scalar()
            folded = fold(text or "")
            rec = FileRecord(
                drive_id=row.drive_id,
                path=row.path,
                name=row.name,
                ext=row.ext,
                doc_date=row.doc_date,
            )
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
        for raw, term in zip(when.text_contains, rule._folded_terms, strict=True):
            if term in folded_text:
                return f"word ‘{raw}’"
        if when.filename_matches is not None:
            return f"file name matches {when.filename_matches}"
        return "no condition: matches every file"
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
