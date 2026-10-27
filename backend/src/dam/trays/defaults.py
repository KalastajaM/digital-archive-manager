"""Tray defaults update: add what a newer default tray file has and the user's copy lacks.

Only missing keys are added, at any depth of nested mappings (a new field, a new
``done.fields``, a new ``summary``). The user's values are never removed or changed,
and lists (``reminders``) are the user's own: they are never merged.

The user's text is kept: each missing key is inserted as YAML text after the last
entry of its mapping, at that mapping's indentation (block style), so comments and
layout stay. A flow-style mapping (``done: { label: Paid }``) that gains keys is
rewritten as one flow mapping (comments inside its braces would be lost). If the
edited text does not load back as exactly "the user's data plus the missing keys"
(anchors, odd keys), the whole file is re-dumped with PyYAML instead, which loses
its comments; the diff shows that before anything is written. The result must load
as a valid tray (the same validation ``load_trays`` uses) or nothing is offered.

Each missing key is offered on its own: the user chooses which to add (``paths``),
and the text and its validation are computed for that choice, so one key that would
make the tray invalid (reported as its ``problem``) never blocks the others. Keys the
user dismisses are stored per tray in a small JSON file in the data dir (never in the
tray file) and are not offered again.

Writes go only to the tray file under the data dir's ``config/trays/``, after a
byte-for-byte backup ``<file>.bak-YYYYMMDD-HHMMSS`` next to it, and only when the file
is still the text the user was shown (``expect_current_text``) and the result is the
text they approved (``expect_new_text``). The file is rewritten in place (no temp file
and rename: renames are pinned to ``dam/ops`` by tests/test_no_delete.py); if that
write fails, the original bytes are written back and the error names the backup.

The dismissal store is written whole and read back; if it does not read back as what
was written, its previous content is put back. Apply, dismiss and undismiss hold one
module-level lock, so two requests never interleave their read-modify-write.
"""

import copy
import json
import logging
import threading
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from dam.errors import Conflict, InvalidRequest, NotFound, StalePreview
from dam.rules.model import MAX_CONFIG_BYTES, read_yaml
from dam.trays.model import load_tray_text

log = logging.getLogger(__name__)

_WIDE = 10**6  # never fold long lines
# apply, dismiss and undismiss: one at a time (each reads, decides, then writes)
_LOCK = threading.RLock()


def _write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` in place (replaced in tests to simulate failures)."""
    with open(path, "wb") as fh:
        fh.write(data)


@dataclass
class AddedKey:
    path: str  # dotted, e.g. "fields.iban"
    value: object
    problem: str | None = None  # why the tray would be invalid with only this added


@dataclass
class DefaultsDiff:
    file: str  # the tray file's name in config/trays
    added: list[AddedKey]  # every missing, not dismissed key
    paths: list[str]  # the keys ``new_text`` adds
    current_text: str
    new_text: str
    error: str | None = None  # why ``new_text`` would not be a valid tray
    dismissed: list[str] = field(default_factory=list)  # filled by ``dismissed_paths``


def _tray_files(trays_dir: Path) -> list[Path]:
    """The files ``load_trays`` reads, in its order."""
    if not trays_dir.is_dir():
        return []
    return sorted(
        (p for p in trays_dir.iterdir() if p.suffix.lower() in (".yaml", ".yml") and p.is_file()),
        key=lambda p: p.name,
    )


def find_tray_file(trays_dir: Path, tray_id: str) -> Path:
    """The first tray file (by name, like ``load_trays``) whose ``id`` is ``tray_id``."""
    for path in _tray_files(trays_dir):
        try:
            _, data = read_yaml(path)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("id") == tray_id:
            return path
    raise NotFound(f"Tray {tray_id}")


def _read_text(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_CONFIG_BYTES:
            raise InvalidRequest(f"{path.name} is too large")
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise InvalidRequest(f"Cannot read {path.name}: {e}") from e


def missing_keys(user: dict, default: dict, path: tuple = ()) -> list[tuple[tuple, object]]:
    """(key path, default value) for every key of ``default`` that ``user`` lacks,
    looking into mappings both have; in the defaults' order."""
    out: list[tuple[tuple, object]] = []
    for key, value in default.items():
        if key not in user:
            out.append(((*path, key), value))
        elif isinstance(value, dict) and isinstance(user[key], dict):
            out.extend(missing_keys(user[key], value, (*path, key)))
    return out


def merge_missing(user: dict, default: dict) -> dict:
    """A copy of ``user`` with the missing keys of ``default`` added."""
    merged = copy.deepcopy(user)
    for path, value in missing_keys(user, default):
        target = merged
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = copy.deepcopy(value)
    return merged


def _dump(data: dict, flow: bool | None) -> str:
    return yaml.safe_dump(
        data, default_flow_style=flow, sort_keys=False, allow_unicode=True, width=_WIDE
    )


def _last_mark(node: yaml.Node) -> yaml.Mark:
    """The end of the last scalar or flow collection inside a block collection (a block
    collection's own end mark lies past any comments that follow it)."""
    while not getattr(node, "flow_style", True) and node.value:
        if isinstance(node, yaml.MappingNode):
            node = node.value[-1][1]
        else:
            node = node.value[-1]
    return node.end_mark


def _line_after(text: str, mark: yaml.Mark) -> int:
    """The offset of the start of the line after the one ``mark`` ends on."""
    if mark.column == 0:
        return mark.index
    newline = text.find("\n", mark.index)
    return len(text) if newline < 0 else newline + 1


class _Edits:
    def __init__(self, text: str) -> None:
        self.text = text
        self.edits: list[tuple[int, int, int, str]] = []  # start, end, depth, new text

    def walk(self, node: yaml.MappingNode, user: dict, default: dict, depth: int = 0) -> None:
        if node.flow_style:
            if missing_keys(user, default):
                flow = _dump(merge_missing(user, default), True).strip()
                self.edits.append((node.start_mark.index, node.end_mark.index, depth, flow))
            return
        nodes = {k.value: v for k, v in node.value if isinstance(k, yaml.ScalarNode)}
        new: dict = {}
        for key, value in default.items():
            if key not in user:
                new[key] = value
            elif (
                isinstance(value, dict)
                and isinstance(user[key], dict)
                and isinstance(nodes.get(key), yaml.MappingNode)
            ):
                self.walk(nodes[key], user[key], value, depth + 1)
        if not new:
            return
        indent = " " * node.value[0][0].start_mark.column
        at = _line_after(self.text, _last_mark(node))
        block = "".join(indent + line for line in _dump(new, None).splitlines(keepends=True))
        if at == len(self.text) and self.text and not self.text.endswith("\n"):
            block = "\n" + block
        self.edits.append((at, at, depth, block))

    def apply(self) -> str:
        text = self.text
        # from the end backwards; at one offset the outer mapping's keys go in first,
        # so the inner mapping's keys end up before them
        for start, end, _, new in sorted(self.edits, key=lambda e: (-e[0], e[2])):
            text = text[:start] + new + text[end:]
        return text


def _new_text(text: str, user: dict, default: dict, file: str) -> str:
    expected = merge_missing(user, default)
    try:
        root = yaml.compose(text, Loader=yaml.SafeLoader)
        if not isinstance(root, yaml.MappingNode):
            raise ValueError("top level is not a mapping")
        edits = _Edits(text)
        edits.walk(root, user, default)
        new_text = edits.apply()
        if yaml.safe_load(new_text) == expected:
            return new_text
        log.warning("tray defaults for %s: text edit did not round-trip; re-dumping", file)
    except (yaml.YAMLError, ValueError, KeyError, IndexError, TypeError):
        log.warning("tray defaults for %s: text edit failed; re-dumping", file, exc_info=True)
    return _dump(expected, None)


def _subset(missing: list[tuple[tuple, object]], chosen: set[str] | None) -> dict:
    """A nested mapping holding only the ``chosen`` missing keys (all when None)."""
    out: dict = {}
    for keys, value in missing:
        if chosen is not None and _dotted(keys) not in chosen:
            continue
        target = out
        for key in keys[:-1]:
            target = target.setdefault(key, {})
        target[keys[-1]] = value
    return out


def _dotted(keys: tuple) -> str:
    return ".".join(str(k) for k in keys)


def _problem(text: str, tray_id: str) -> str | None:
    """Why ``text`` would not be a valid tray ``tray_id`` (None if it would)."""
    try:
        tray = load_tray_text(text)
    except ValueError as e:
        return str(e)
    return None if tray.id == tray_id else "the id would change"


@dataclass
class _Compared:
    path: Path
    current: str
    user: dict
    missing: list[tuple[tuple, object]]  # offered: missing and not dismissed


def _compare(
    trays_dir: Path, defaults_dir: Path, tray_id: str, dismissed: Collection[str]
) -> _Compared:
    path = find_tray_file(trays_dir, tray_id)
    current = _read_text(path)
    default_path = defaults_dir / path.name
    if not default_path.is_file():
        return _Compared(path, current, {}, [])
    try:
        _, default = read_yaml(default_path)
        _, user = read_yaml(path)
    except ValueError as e:
        raise Conflict(f"Cannot compare {path.name} with its defaults: {e}") from e
    if not isinstance(default, dict) or not isinstance(user, dict):
        return _Compared(path, current, {}, [])
    gone = set(dismissed)
    missing = [(k, v) for k, v in missing_keys(user, default) if _dotted(k) not in gone]
    return _Compared(path, current, user, missing)


def _text_for(c: _Compared, chosen: set[str] | None) -> str:
    subset = _subset(c.missing, chosen)
    return _new_text(c.current, c.user, subset, c.path.name) if subset else c.current


def defaults_diff(
    trays_dir: Path,
    defaults_dir: Path,
    tray_id: str,
    paths: Collection[str] | None = None,
    dismissed: Collection[str] = (),
) -> DefaultsDiff:
    """What the default tray file of the same name adds to the user's tray ``tray_id``:
    every missing key not in ``dismissed`` (empty when nothing is missing, or there is
    no such default file).

    Each added key carries ``problem``: why the tray would be invalid with that key
    alone added (None if it is fine). ``new_text`` adds the keys in ``paths`` (default:
    every added key without a problem) and ``error`` says why that text would not be
    a valid tray (None if it would)."""
    c = _compare(trays_dir, defaults_dir, tray_id, dismissed)
    added = [
        AddedKey(_dotted(k), v, _problem(_text_for(c, {_dotted(k)}), tray_id)) for k, v in c.missing
    ]
    offered = {a.path for a in added}
    if paths is None:
        chosen = {a.path for a in added if a.problem is None}
    else:
        chosen = set(paths)
        unknown = chosen - offered
        if unknown:
            raise StalePreview(
                f"no longer missing from {c.path.name}: {', '.join(sorted(unknown))}"
            )
    new_text = _text_for(c, chosen)
    error = _problem(new_text, tray_id) if chosen else None
    return DefaultsDiff(
        c.path.name,
        added,
        sorted(chosen, key=[a.path for a in added].index),
        c.current,
        new_text,
        error,
    )


def apply_defaults(
    trays_dir: Path,
    defaults_dir: Path,
    tray_id: str,
    paths: Collection[str],
    expect_current_text: str,
    expect_new_text: str,
    dismissed: Collection[str] = (),
    now: datetime | None = None,
) -> tuple[str, Path]:
    """Add only the missing keys in ``paths`` to the tray file, if the file is still
    ``expect_current_text`` and the result still ``expect_new_text`` (else
    ``StalePreview``), after a byte-for-byte backup next to it. Returns the tray
    file's name and the backup's path; the caller reloads the trays."""
    with _LOCK:
        if not paths:
            raise InvalidRequest("Choose at least one setting to add")
        diff = defaults_diff(trays_dir, defaults_dir, tray_id, paths, dismissed)
        if diff.current_text != expect_current_text or diff.new_text != expect_new_text:
            raise StalePreview("the tray file or its defaults changed: review the update again")
        if diff.error is not None:
            raise Conflict(f"Cannot add that to {diff.file}: {diff.error}")
        path = trays_dir / diff.file
        if path.is_symlink():
            raise InvalidRequest(f"{diff.file} is a link: update it by hand")
        try:
            original = path.read_bytes()
        except OSError as e:
            raise InvalidRequest(f"Cannot read {diff.file}: {e}") from e
        if (
            original.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
            != diff.current_text
        ):
            raise StalePreview("the tray file changed: review the update again")
        stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"{path.name}.bak-{stamp}")
        try:
            with open(backup, "xb") as fh:  # exclusive: never overwrites a backup
                fh.write(original)  # byte for byte
        except FileExistsError:
            raise Conflict(f"A backup {backup.name} exists already: try again") from None
        # Written in place, not via a temp file + os.replace: renames are pinned to
        # dam/ops (tests/test_no_delete.py). The backup above is the way back.
        try:
            _write_bytes(path, diff.new_text.encode("utf-8"))
        except OSError as e:
            try:
                _write_bytes(path, original)
            except OSError:
                log.exception("could not put %s back after a failed write", diff.file)
                raise Conflict(
                    f"Could not write {diff.file} ({e}) nor put it back: restore it from "
                    f"{backup.name}"
                ) from e
            raise Conflict(
                f"Could not write {diff.file} ({e}); it was put back as it was "
                f"(the backup is {backup.name})"
            ) from e
        return diff.file, backup


# -- dismissed defaults --------------------------------------------------------------


def load_dismissed(store: Path) -> dict[str, list[str]]:
    """tray id -> the default key paths the user chose not to add (``store`` is a small
    JSON file in the data dir; unreadable or absent = none)."""
    try:
        data = json.loads(store.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        k: [p for p in v if isinstance(p, str)]
        for k, v in data.items()
        if isinstance(k, str) and isinstance(v, list)
    }


def _save_dismissed(store: Path, everything: dict[str, list[str]]) -> None:
    """Write the whole store, then read it back; if it does not read back as written,
    put its previous bytes back (none: an empty file) and raise ``Conflict``."""
    try:
        previous = store.read_bytes()
    except FileNotFoundError:
        previous = b""
    except OSError as e:
        raise Conflict(f"Could not save the dismissed settings: {e}") from e
    text = json.dumps(everything, indent=2, ensure_ascii=False) + "\n"
    problem: str | None = None
    try:
        store.parent.mkdir(parents=True, exist_ok=True)
        _write_bytes(store, text.encode("utf-8"))
        if json.loads(store.read_text(encoding="utf-8")) != everything:
            problem = "it did not read back as written"
    except (OSError, ValueError) as e:
        problem = str(e)
    if problem is None:
        return
    try:
        _write_bytes(store, previous)
    except OSError:
        log.exception("could not put %s back", store)
    raise Conflict(f"Could not save the dismissed settings ({problem}); nothing changed")


def dismiss(
    store: Path, trays_dir: Path, defaults_dir: Path, tray_id: str, paths: Collection[str]
) -> list[str]:
    """Stop offering ``paths`` (those currently offered) for ``tray_id``; returns every
    dismissed path of that tray."""
    with _LOCK:
        everything = load_dismissed(store)
        mine = everything.get(tray_id, [])
        offered = {a.path for a in defaults_diff(trays_dir, defaults_dir, tray_id, (), mine).added}
        new = [p for p in dict.fromkeys(paths) if p in offered and p not in mine]
        if new:
            everything[tray_id] = [*mine, *new]
            _save_dismissed(store, everything)
        return everything.get(tray_id, mine)


def dismissed_paths(store: Path, trays_dir: Path, defaults_dir: Path, tray_id: str) -> list[str]:
    """The dismissed paths of ``tray_id`` that are still missing from its file (a key
    the user has since added by hand is no longer listed), in dismissal order."""
    mine = load_dismissed(store).get(tray_id, [])
    if not mine:
        return []
    still = {_dotted(k) for k, _ in _compare(trays_dir, defaults_dir, tray_id, ()).missing}
    return [p for p in mine if p in still]


def undismiss(store: Path, tray_id: str, paths: Collection[str]) -> list[str]:
    """Offer ``paths`` again for ``tray_id``; returns the tray's remaining dismissed
    paths (paths that were not dismissed are ignored)."""
    with _LOCK:
        everything = load_dismissed(store)
        mine = everything.get(tray_id, [])
        drop = set(paths)
        left = [p for p in mine if p not in drop]
        if left != mine:
            if left:
                everything[tray_id] = left
            else:
                everything.pop(tray_id, None)
            _save_dismissed(store, everything)
        return left
