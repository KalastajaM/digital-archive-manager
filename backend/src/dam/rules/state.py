"""The learned-rules settings that live beside the data: ``rules-state.json``.

Saved backup first: the file it replaces is copied to ``rules-state.json.bak`` and that
copy is on the disk before the file itself is rewritten, so a crash part way leaves one
of the two whole; a file that cannot be read falls back to the backup.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from dam.codes.configfile import to_disk

STATE_FILE = "rules-state.json"
BACKUP_FILE = f"{STATE_FILE}.bak"


@dataclass
class RulesState:
    offer: bool = True  # offer to make a rule after a manual filing
    declined: list[list[str]] = field(default_factory=list)  # ticked-word sets turned down


def _read(path: Path) -> RulesState | None:
    """The state in ``path``; None when it is missing, unreadable or not a state."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        offer = raw.get("offer", True)
        declined = raw.get("declined", [])
        if not isinstance(offer, bool) or not isinstance(declined, list):
            return None
        sets = [sorted(str(w) for w in d) for d in declined if isinstance(d, list)]
        return RulesState(offer, sets)
    except (OSError, ValueError, AttributeError):
        return None


def load_state(data_dir: Path) -> RulesState:
    """The saved state; the backup when the file cannot be read (a crash while it was
    written); the defaults when neither can."""
    return _read(data_dir / STATE_FILE) or _read(data_dir / BACKUP_FILE) or RulesState()


def save_state(data_dir: Path, state: RulesState) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"offer": state.offer, "declined": state.declined}, ensure_ascii=False)
    path = data_dir / STATE_FILE
    if _read(path) is not None:  # only a whole file replaces the backup
        with open(data_dir / BACKUP_FILE, "wb") as fh:
            fh.write(path.read_bytes())
            to_disk(fh)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
        to_disk(f)
