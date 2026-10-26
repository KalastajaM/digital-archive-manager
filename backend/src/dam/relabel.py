"""Change an extra archive folder's label: the name its paths start with.

Nothing on disk changes. Every stored path under the old label is rewritten: the index
(``files`` and its search rows), the journal (so earlier changes stay undoable), the
folders the app made, the maintenance entries set aside, the settings (the folder's
entry, protected paths, folders kept from AI) and the rules' ``folder`` and
``folder_is`` values. The YAML files are edited value by value (``dam.core.yamledit``),
so comments and layout stay. A snapshot of the database and the settings is taken
first; if writing the files fails after the database changed, the database is put back.

The archive must be closed while this runs (``Host.close_and_reopen``), or the scanner
would write paths under the old label back.
"""

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from sqlalchemy import Connection, Engine, select, text, update

from dam.codes.configfile import write_config_file
from dam.config import AppPaths, load_settings
from dam.core.yamledit import YamlEditError, replace_values
from dam.db.tables import files, made_folders, maintenance_ignored, operations
from dam.maintenance.ignored import GROUPS
from dam.ops.model import ABS_TARGET, OpFailed, OpKind
from dam.rules.model import _load_file as load_rule_file
from dam.rules.model import rule_files
from dam.snapshots import BEFORE_RELABEL, create_snapshot

INTERRUPTED = "An operation was interrupted. Run dam recover first, then change the label."
# journal sources that are a file's name only (it came from outside the archive)
_NAME_ONLY_SRC = {str(OpKind.COPY), str(OpKind.PICTURE_TO_QUARANTINE)}
_NAME_ONLY_DST = {str(OpKind.PICTURE_BACK)}  # the name in the rules' picture folder


def _fold(s: str) -> str:
    return unicodedata.normalize("NFC", s).casefold()


def swap(value: str | None, old: str, new: str) -> str | None:
    """``value`` with its first component ``old`` (folded) replaced by ``new``, or None
    when it does not start with ``old`` (an ``abs:`` path never does)."""
    if not value or value.startswith(ABS_TARGET):
        return None
    head, sep, rest = value.partition("/")
    return new + sep + rest if _fold(head) == _fold(old) else None


@dataclass
class FileChange:
    path: Path
    lines: list[int]
    text: str  # the new content
    before: str  # the content now


@dataclass
class RelabelPlan:
    old: str
    new: str
    counts: dict[str, int] = field(default_factory=dict)
    files: list[FileChange] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _expected(data, change: Callable, path: tuple = ()):
    """``data`` (a loaded YAML document) with ``change`` applied, to check an edit."""
    if isinstance(data, dict):
        return {k: _expected(v, change, (*path, k)) for k, v in data.items()}
    if isinstance(data, list):
        return [_expected(v, change, (*path, i)) for i, v in enumerate(data)]
    if isinstance(data, str):
        new = change(path, data)
        return data if new is None else new
    return data


def _edit(path: Path, change: Callable) -> FileChange | None:
    before = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    try:
        after, lines = replace_values(before, change)
    except YamlEditError as e:
        raise YamlEditError(f"{path.name}, {e}") from None
    if not lines:
        return None
    if yaml.safe_load(after) != _expected(yaml.safe_load(before), change):
        raise YamlEditError(f"{path.name}: the edit could not be checked; change it by hand")
    return FileChange(path, lines, after, before)


def _settings_change(old: str, new: str) -> Callable:
    def change(path: tuple, value: str) -> str | None:
        match path:
            case ("extra_folders", int(), "label"):
                return new if _fold(value) == _fold(old) else None
            case ("protected_paths", int()) | ("ai", "exclude_folders", int()):
                return swap(value, old, new)
        return None

    return change


def _rule_change(old: str, new: str) -> Callable:
    def change(path: tuple, value: str) -> str | None:
        if not path or path[-1] not in ("folder", "folder_is"):
            return None
        if "{" in value.partition("/")[0]:  # a template whose first part is a placeholder
            return None
        return swap(value, old, new)

    return change


def _db(conn: Connection, old: str, new: str, write: bool) -> dict[str, int]:
    """Rewrite (or, without ``write``, count) the stored paths under ``old``."""
    counts = {"files": 0, "operations": 0, "made_folders": 0, "maintenance_ignored": 0}
    # the search rows by their rowid (drive_id is not indexed there: one scan, not one each)
    fts = dict(conn.execute(text("SELECT drive_id, rowid FROM file_fts")).all()) if write else {}
    for drive_id, path in conn.execute(select(files.c.drive_id, files.c.path)).all():
        moved = swap(path, old, new)
        if moved is None:
            continue
        counts["files"] += 1
        if not write:
            continue
        values = {"path": moved, "path_nfc": unicodedata.normalize("NFC", moved)}
        top = "/" not in moved
        if top:
            values["name"] = moved
        conn.execute(update(files).where(files.c.drive_id == drive_id).values(**values))
        if drive_id in fts:
            conn.execute(
                text(
                    "UPDATE file_fts SET path = :p"
                    + (", name = :p" if top else "")
                    + " WHERE rowid = :r"
                ),
                {"p": values["path_nfc"], "r": fts[drive_id]},
            )
    journal = (operations.c.id, operations.c.kind, operations.c.src, operations.c.dst)
    rows = conn.execute(select(*journal))
    for op_id, kind, src, dst in rows.all():
        new_src = None if kind in _NAME_ONLY_SRC and "/" not in (src or "") else swap(src, old, new)
        new_dst = None if kind in _NAME_ONLY_DST else swap(dst, old, new)
        if new_src is None and new_dst is None:
            continue
        counts["operations"] += 1
        if write:
            values = {}
            if new_src is not None:
                values["src"] = new_src
            if new_dst is not None:
                values["dst"] = new_dst
            conn.execute(update(operations).where(operations.c.id == op_id).values(**values))
    for row_id, rel in conn.execute(select(made_folders.c.id, made_folders.c.rel)).all():
        moved = swap(rel, old, new)
        if moved is not None:
            counts["made_folders"] += 1
            if write:
                conn.execute(
                    update(made_folders).where(made_folders.c.id == row_id).values(rel=moved)
                )
    ignored = conn.execute(
        select(maintenance_ignored.c.id, maintenance_ignored.c.kind, maintenance_ignored.c.key)
    )
    for row_id, kind, key in ignored.all():
        moved = None if kind in GROUPS else swap(key, old, new)
        if moved is not None:
            counts["maintenance_ignored"] += 1
            if write:
                conn.execute(
                    update(maintenance_ignored)
                    .where(maintenance_ignored.c.id == row_id)
                    .values(key=moved)
                )
    return counts


def plan(app_paths: AppPaths, engine: Engine, old: str, new: str) -> RelabelPlan:
    """What changing the label ``old`` (as the settings spell it) to ``new`` (already
    checked by ``archive_folders``) would change. Nothing is written. ``YamlEditError``
    when a rule or settings value cannot be edited safely, ``OpFailed`` while a journal
    row is still ``planned``."""
    with engine.connect() as conn:
        planned = conn.execute(
            select(operations.c.id).where(operations.c.state == "planned")
        ).first()
        if planned is not None:
            raise OpFailed(INTERRUPTED)
        out = RelabelPlan(old, new, counts=_db(conn, old, new, write=False))
    edits = [_edit(app_paths.config_dir / "settings.yaml", _settings_change(old, new))]
    edits += [_edit(p, _rule_change(old, new)) for p in rule_files(app_paths.config_dir / "rules")]
    if app_paths.filing_codes_path.is_file():  # each code's ``folder``, as in the rules
        edits.append(_edit(app_paths.filing_codes_path, _rule_change(old, new)))
    out.files = [e for e in edits if e is not None]
    root = load_settings(app_paths).archive_root
    try:
        hidden = any(_fold(p.name) == _fold(old) for p in Path(root).iterdir())
    except OSError:
        hidden = False
    if hidden and _fold(old) != _fold(new):
        out.warnings.append(
            f"The main folder has an entry named '{old}'. It was hidden behind the label and"
            " is indexed after the change."
        )
    return out


def _verify(change: FileChange, app_paths: AppPaths) -> Callable[[], bool]:
    def check() -> bool:
        try:
            if change.path.name == "settings.yaml":
                load_settings(app_paths)
            elif change.path == app_paths.filing_codes_path:
                yaml.safe_load(change.path.read_text(encoding="utf-8"))
            else:
                load_rule_file(change.path)
            return change.path.read_bytes().decode("utf-8") == change.text
        except (ValueError, yaml.YAMLError, OSError):
            return False

    return check


def apply(app_paths: AppPaths, engine: Engine, plan: RelabelPlan) -> None:
    """Carry out ``plan``: snapshot, database (one transaction), then the files. If a file
    cannot be written, the files already written get their old content back, the
    database is rewritten back, and the error is raised."""
    create_snapshot(app_paths, kind=BEFORE_RELABEL)
    with engine.begin() as conn:
        _db(conn, plan.old, plan.new, write=True)
    written: list[FileChange] = []
    try:
        for change in plan.files:
            write_config_file(change.path, change.text, _verify(change, app_paths))
            written.append(change)
    except Exception:
        for change in reversed(written):
            change.path.write_text(change.before, encoding="utf-8", newline="\n")
        with engine.begin() as conn:
            _db(conn, plan.new, plan.old, write=True)
        raise
