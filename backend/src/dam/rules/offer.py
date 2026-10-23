"""The offer to make or update a rule after a manual filing, and the outcome records.

Pure decisions; ``InboxService.file_it`` supplies the suggestion, the request and the
rule files."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dam.core.paths import nfc
from dam.rules.draft import RuleDraft
from dam.rules.engine import Suggestion
from dam.rules.learned import rule_file
from dam.rules.model import LEARNED_FILE

RULE_PREFIX = "rule:"


@dataclass
class RuleOffer:
    kind: Literal["new", "update"]
    rule_id: str | None
    drive_id: str
    draft: RuleDraft


def rule_id_of(source: str | None) -> str | None:
    return source[len(RULE_PREFIX) :] if source and source.startswith(RULE_PREFIX) else None


def same(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return a is b
    return nfc(a) == nfc(b)


def outcomes(
    found: Suggestion, name: str, folder: str, tray: str | None
) -> list[tuple[str, str, bool]]:
    """``(rule_id, field, kept)`` for each field a rule suggested."""
    out = []
    for field_, source, suggested, given in (
        ("folder", found.folder_source, found.folder, folder),
        ("name", found.name_source, found.name, name),
        ("tray", found.tray_source, found.tray, tray),
    ):
        rule_id = rule_id_of(source)
        if rule_id is not None:
            out.append((rule_id, field_, same(suggested, given)))
    return out


def offer_target(
    found: Suggestion, name: str, folder: str, rules_dir: Path
) -> tuple[bool, Literal["new", "update"], str | None]:
    """(whether to offer, kind, rule id). No offer when a rule gave both folder and name
    and both were kept."""
    folder_rule, name_rule = rule_id_of(found.folder_source), rule_id_of(found.name_source)
    if (
        folder_rule is not None
        and name_rule is not None
        and same(found.folder, folder)
        and same(found.name, name)
    ):
        return False, "new", None
    for rule_id in (folder_rule, name_rule):
        if rule_id is None:
            continue
        path = rule_file(rules_dir, rule_id)
        if path is not None and path.name == LEARNED_FILE:
            return True, "update", rule_id
        break
    return True, "new", None


def make_doc_frequency(
    count: Callable[[str], int], total: Callable[[], int]
) -> Callable[[str], float]:
    """Share of filed documents containing a word; each count is made once."""
    cache: dict[str, float] = {}
    size: list[int] = []

    def frequency(word: str) -> float:
        if not size:
            size.append(total())
        if size[0] == 0:
            return 0.0
        if word not in cache:
            cache[word] = count(word) / size[0]
        return cache[word]

    return frequency
