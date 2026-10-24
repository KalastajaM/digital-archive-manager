"""Writing rule files: the learned rules file and edits to hand-written files."""

from pathlib import Path

import yaml

from dam.codes.configfile import write_config_file
from dam.rules.model import LEARNED_FILE, Rule, _load_file, rule_files


def rules_text(rules: list[Rule]) -> str:
    """The YAML list for ``rules``, defaults left out."""
    return yaml.safe_dump(
        [r.model_dump(exclude_defaults=True, mode="json") for r in rules],
        allow_unicode=True,
        sort_keys=False,
    )


def write_rules_file(path: Path, rules: list[Rule]) -> None:
    """Replace ``path`` with ``rules``. The old file is kept as ``.bak-<time>``; the new
    one is read back and the old one restored if it does not match."""

    def verify() -> bool:
        return _load_file(path) == rules

    write_config_file(path, rules_text(rules), verify)


def rule_file(rules_dir: Path, rule_id: str) -> Path | None:
    """The file that holds the loaded rule ``rule_id`` (the first one in load order)."""
    for path in rule_files(rules_dir):
        try:
            if any(r.id == rule_id for r in _load_file(path)):
                return path
        except (ValueError, RecursionError, MemoryError):
            continue  # a bad file loads nothing
    return None


def learned_ids(rules_dir: Path) -> set[str]:
    """The ids of the rules in ``learned.yaml`` (none when it is missing or does not load)."""
    path = Path(rules_dir) / LEARNED_FILE
    if not path.is_file():
        return set()
    try:
        return {r.id for r in _load_file(path)}
    except (ValueError, RecursionError, MemoryError):
        return set()
