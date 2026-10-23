"""The learned-rules settings that live beside the data: ``rules-state.json``."""

import json
from dataclasses import dataclass, field
from pathlib import Path

STATE_FILE = "rules-state.json"


@dataclass
class RulesState:
    offer: bool = True  # offer to make a rule after a manual filing
    declined: list[list[str]] = field(default_factory=list)  # ticked-word sets turned down


def load_state(data_dir: Path) -> RulesState:
    """The saved state; a missing or unreadable file means the defaults."""
    try:
        raw = json.loads((data_dir / STATE_FILE).read_text(encoding="utf-8"))
        offer = raw.get("offer", True)
        declined = raw.get("declined", [])
        if not isinstance(offer, bool) or not isinstance(declined, list):
            return RulesState()
        sets = [sorted(str(w) for w in d) for d in declined if isinstance(d, list)]
        return RulesState(offer, sets)
    except (OSError, ValueError, AttributeError):
        return RulesState()


def save_state(data_dir: Path, state: RulesState) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"offer": state.offer, "declined": state.declined}, ensure_ascii=False)
    (data_dir / STATE_FILE).write_text(text, encoding="utf-8")
