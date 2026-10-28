"""Rename one of the app's special folders: Inbox, Ongoing, Important or To Delete.

The folder is renamed on disk by the operation layer (a journaled ``RENAME`` batch on one
disk, so it shows in Activity and can be undone). Everything that stores the old name
follows it, in one go:

* the index: the executor re-paths the folder's rows (and the search rows) itself;
* ``config/settings.yaml``: ``special_folders.<key>``, and the ``protected_paths`` and
  ``ai.exclude_folders`` entries that start with the old name (a backup copy is kept);
* the rules (``folder`` and ``folder_is`` values) and the filing codes' ``folder`` values;
* the paths the Ongoing/Important publisher records (``ongoing_entries.rel``,
  ``collections.ongoing_rel``) and the paths Maintenance was told to ignore.

Filing codes' ``inbox_folder`` names (``To pay``) are stored relative to the inbox, so they
need no change. Collections, trays, tags, notes and locks are keyed by file id, not by
path. The journal and the folders it made stay as history. A managed shortcut keeps
pointing at the same file: the ones inside a renamed Ongoing/Important stay valid, and the
ones that point into the renamed folder are rebuilt by the publisher's next sync (it
compares each link with where the file is now).

The rename runs with the archive closed (``Host.close_and_reopen``): the scanner must not
write old paths back, and the reopened app reads the new names. A rename is recorded in
``special_folder_renames`` before the folder moves; ``reconcile`` finishes (or rolls back)
one an interruption left half done, at the next start. Undo (``undo``) runs the executor's
undo of the batch and then puts the settings, rules and stored paths back.
"""

import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import yaml
from sqlalchemy import Connection, Engine, func, insert, inspect, select, update

from dam.codes.configfile import write_config_file
from dam.config import AppPaths, Settings, SpecialFolders, load_settings
from dam.core.foldernames import FolderNameError, check_folder_name
from dam.core.paths import ArchivePaths, fold_name, nfc
from dam.core.yamledit import YamlEditError, replace_values
from dam.db.engine import make_engine, write_tx
from dam.db.tables import (
    collections,
    files,
    maintenance_ignored,
    ongoing_entries,
    operations,
    special_folder_renames,
)
from dam.errors import Conflict, InvalidRequest, NotFound
from dam.index.repo import FileRepo
from dam.index.repo.model import at_or_below
from dam.maintenance.ignored import GROUPS
from dam.ops.executor import Executor
from dam.ops.model import ABS_TARGET, GuardError, Op, OpKind, Plan
from dam.ops.undo import ACTED
from dam.rules.model import load_rule_file, rule_files
from dam.rules.picture import AREAS_DIR
from dam.settings_write import with_keys
from dam.snapshots import BEFORE_RENAME, create_snapshot

log = logging.getLogger(__name__)

KEYS = ("inbox", "ongoing", "important", "quarantine")
TITLES = {
    "inbox": "Inbox",
    "ongoing": "Ongoing",
    "important": "Important",
    "quarantine": "To Delete",
}
RENAMED, REBUILT, UNCHANGED = "renamed", "rebuilt", "unchanged"
INTERRUPTED = (
    "An operation was interrupted. Run recovery first (Run recovery in the app, or "
    "dam recover), then rename the folder."
)
UNDO_HOW = "Undo in Activity puts every one of these back."
SYNC_NOTE = (
    "The folder is on Google Drive. The rename has to sync to every device before they "
    "see it; keep Google Drive running until it has finished."
)
UNFINISHED = (
    "An earlier rename of a special folder was left unfinished{why}. Run recovery if the app "
    "offers it and restart dam, so it can finish it, or undo that change in Activity."
)
# planned: started, finishes or is taken back at the next start; done; undone; failed: the
# folder never moved (nothing to undo); attention: some of it is done and dam could not finish
# or take it back by itself (Undo in Activity retries, ``note`` says why)
_DONE, _UNDONE, _PLANNED, _FAILED = "done", "undone", "planned", "failed"
_ATTENTION = "attention"


@dataclass
class Place:
    """One place that stores the folder's name or a path under it, and what happens."""

    place: str
    how: str  # renamed | rebuilt | unchanged
    what: str


@dataclass
class Preview:
    key: str
    title: str
    old: str
    new: str
    places: list[Place] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    google_drive: bool = False
    undo: str = UNDO_HOW


@dataclass
class Renamed:
    batch_id: str
    key: str
    old: str
    new: str


@dataclass
class FileChange:
    """One config file with some values changed. ``text`` and ``before`` use ``\\n``;
    ``crlf``: the file has Windows line endings, which are kept. ``edits``: each value
    changed as ``[yaml path, old value, new value]``, what an undo puts back."""

    path: Path
    lines: list[int]
    text: str  # the new content
    before: str  # the content now
    edits: list[list] = field(default_factory=list)
    crlf: bool = False

    @property
    def written(self) -> str:
        return self.text.replace("\n", "\r\n") if self.crlf else self.text


# --- names -----------------------------------------------------------------------------


def swap(value: str | None, old: str, new: str, labels: tuple[str, ...] = ()) -> str | None:
    """``value`` (an archive path) with its first component ``old`` (folded) replaced by
    ``new``, or None when it does not start with ``old``. ``labels``: the extra folders'
    labels, so ``Old years/<old>`` follows too (the To Delete of every folder)."""
    if not value or value.startswith(ABS_TARGET):
        return None
    head, sep, rest = value.partition("/")
    if fold_name(head) == fold_name(old):
        return new + sep + rest
    if labels and fold_name(head) in {fold_name(x) for x in labels}:
        second, sep2, rest2 = rest.partition("/")
        if second and fold_name(second) == fold_name(old):
            return f"{head}/{new}{sep2}{rest2}"
    return None


def _labels(key: str, settings) -> tuple[str, ...]:
    """The extra folders whose paths also carry the name: only To Delete exists in each."""
    return tuple(e.label for e in settings.extra_folders) if key == "quarantine" else ()


def on_google_drive(root: Path) -> bool:
    flat = str(root).lower().replace(" ", "").replace("-", "")
    return "googledrive" in flat or "mydrive" in flat


def check_name(key: str, raw: str, paths: ArchivePaths) -> str:
    """The new name as it will be used, or ``InvalidRequest`` with the reason. Same rules
    as any folder name, and a name starting with ``##.`` is fine (it is the app's marker)."""
    if key not in KEYS:
        raise NotFound(f"special folder {key}")
    settings = paths.settings
    old = getattr(settings.special_folders, key)
    try:
        clean = check_folder_name(raw, (raw if isinstance(raw, str) else "",))
    except FolderNameError as e:
        raise InvalidRequest(str(e)) from None
    if clean == nfc(old):
        raise InvalidRequest(f"That is already the name of the {TITLES[key]} folder.")
    for other in KEYS:
        if other != key and fold_name(clean) == fold_name(getattr(settings.special_folders, other)):
            raise InvalidRequest(
                f"'{clean}' is already the name of the {TITLES[other]} folder. Choose another name."
            )
    if any(fold_name(e.label) == fold_name(clean) for e in settings.extra_folders):
        raise InvalidRequest(f"'{clean}' is the name of an archive folder. Choose another name.")
    if fold_name(clean) != fold_name(old):  # a change of letter case alone is the same folder
        for root in _roots(key, paths):
            if _taken(root, clean):
                raise InvalidRequest(
                    f"There is already a folder or file named '{clean}' in {root}. "
                    "Choose another name."
                )
    return clean


def _roots(key: str, paths: ArchivePaths) -> list[Path]:
    """The folders the special folder lives in: the main folder, and for To Delete each
    attached extra folder too."""
    folders = paths.folders if key == "quarantine" else paths.folders[:1]
    return [f.root for f in folders]


def _taken(root: Path, name: str) -> bool:
    try:
        with os.scandir(root) as entries:
            return any(fold_name(e.name) == fold_name(name) for e in entries)
    except OSError:
        return False


def targets(key: str, paths: ArchivePaths) -> list[str]:
    """The archive paths of the special folder that exist on disk now, the main folder's
    first."""
    old = getattr(paths.settings.special_folders, key)
    rels = [old] if key != "quarantine" else [old, *(f"{x}/{old}" for x in paths.extra_labels)]
    return [r for r in rels if _is_real_folder(paths, r)]


def _is_real_folder(paths: ArchivePaths, rel: str) -> bool:
    p = paths.abs(rel)
    return p.is_dir() and not p.is_symlink()


def _refusals(key: str, paths: ArchivePaths, engine: Engine) -> None:
    """``Conflict`` when the folder's disk is away or an operation was interrupted."""
    settings = paths.settings
    if key == "quarantine":
        for extra in settings.extra_folders:
            if not extra.attached:
                raise Conflict(
                    f"The archive folder '{extra.label}' is detached, and it has its own To "
                    "Delete folder. Attach it first, so every To Delete folder is renamed."
                )
    for folder in paths.folders if key == "quarantine" else paths.folders[:1]:
        if not paths.is_connected(folder.label):
            where = f"'{folder.label}'" if folder.label else "The archive folder"
            raise Conflict(
                f"{where} is not connected ({folder.root}). Connect it and try again."
            )
    with engine.connect() as conn:
        if conn.execute(
            select(operations.c.id).where(operations.c.state == "planned").limit(1)
        ).first():
            raise Conflict(INTERRUPTED)
        unfinished = conn.execute(
            select(special_folder_renames.c.note)
            .where(special_folder_renames.c.state.in_((_PLANNED, _ATTENTION)))
            .limit(1)
        ).first()
    if unfinished is not None:
        why = f" ({unfinished[0]})" if unfinished[0] else ""
        raise Conflict(UNFINISHED.format(why=why))


def _nothing_to_rename(key: str, rels: list[str], old: str) -> bool:
    """No folder to rename: none of them is there, or (for the folders that live in the main
    folder only) the main one is not. To Delete may exist in an extra folder alone."""
    if not rels:
        return True
    return key != "quarantine" and fold_name(rels[0]) != fold_name(old)


def _plan(key: str, rels: list[str], new: str, title: str, old: str) -> Plan:
    ops = [
        Op(OpKind.RENAME, rel, new, allow_top_level="/" not in rel) for rel in rels
    ]
    return Plan(ops, origin="ui", label=f"Renamed the {title} folder from {old} to {new}")


# --- what stores the name: config files -------------------------------------------------


def _settings_change(key: str, old: str, new: str, labels: tuple[str, ...]) -> Callable:
    def change(path: tuple, value: str) -> str | None:
        if path == ("special_folders", key):
            return new if fold_name(value) == fold_name(old) else None
        if (len(path) == 2 and path[0] == "protected_paths") or (
            len(path) == 3 and path[:2] == ("ai", "exclude_folders")
        ):
            return swap(value, old, new, labels)
        return None

    return change


def _folder_change(old: str, new: str, labels: tuple[str, ...]) -> Callable:
    """Rules and filing codes: the ``folder`` and ``folder_is`` values."""

    def change(path: tuple, value: str) -> str | None:
        if not path or path[-1] not in ("folder", "folder_is"):
            return None
        if "{" in value.partition("/")[0]:  # a template whose first part is a placeholder
            return None
        return swap(value, old, new, labels)

    return change


def _expected(data, change: Callable, path: tuple = ()):
    if isinstance(data, dict):
        return {k: _expected(v, change, (*path, k)) for k, v in data.items()}
    if isinstance(data, list):
        return [_expected(v, change, (*path, i)) for i, v in enumerate(data)]
    if isinstance(data, str):
        new = change(path, data)
        return data if new is None else new
    return data


def _read(path: Path) -> tuple[str, bool]:
    """The file's text with ``\\n`` line ends, and whether it had Windows ones."""
    raw = path.read_bytes().decode("utf-8")
    return raw.replace("\r\n", "\n"), "\r\n" in raw


def _edit(path: Path, change: Callable) -> FileChange | None:
    before, crlf = _read(path)
    applied: list[list] = []

    def recording(at: tuple, value: str) -> str | None:
        new = change(at, value)
        if new is not None and new != value:
            applied.append([list(at), value, new])
        return new

    try:
        after, lines = replace_values(before, recording)
    except YamlEditError as e:
        raise YamlEditError(f"{path.name}, {e}") from None
    if not lines:
        return None
    if yaml.safe_load(after) != _expected(yaml.safe_load(before), change):
        raise YamlEditError(f"{path.name}: the edit could not be checked; change it by hand")
    return FileChange(path, lines, after, before, applied, crlf)


def _settings_edit(
    app_paths: AppPaths, key: str, old: str, new: str, labels: tuple[str, ...]
) -> FileChange | None:
    """The settings file with the name changed. What the file does not spell out, because
    the built-in default is in use, is written out: the ``special_folders`` entry, and for
    Important the default ``protected_paths`` (which has to follow the name)."""
    path = app_paths.config_dir / "settings.yaml"
    edit = _edit(path, _settings_change(key, old, new, labels))
    before, crlf = (edit.before, edit.crlf) if edit else _read(path)
    text = edit.text if edit else before
    edits = list(edit.edits) if edit else []
    lines = list(edit.lines) if edit else []
    data = yaml.safe_load(text) or {}
    written = (data.get("special_folders") or {}).get(key)
    if not (isinstance(written, str) and fold_name(written) == fold_name(new)):
        names = SpecialFolders().model_dump()
        names.update(data.get("special_folders") or {})
        names[key] = new
        text = with_keys(text, {"special_folders": names})
        edits.append([["special_folders", key], old, new])
    if key == "important" and "protected_paths" not in (yaml.safe_load(before) or {}):
        default = Settings().protected_paths
        moved = [swap(v, old, new, labels) or v for v in default]
        if moved != default:
            text = with_keys(text, {"protected_paths": moved})
            edits += [
                [["protected_paths", i], v, m]
                for i, (v, m) in enumerate(zip(default, moved, strict=True))
                if v != m
            ]
    if text == before:
        return None
    return FileChange(path, lines, text, before, edits, crlf)


def config_edits(
    app_paths: AppPaths, key: str, old: str, new: str, labels: tuple[str, ...]
) -> list[FileChange]:
    """The config files with ``old`` replaced by ``new``, those that change only. Nothing
    is written. ``YamlEditError`` when a value cannot be edited safely."""
    out = [_settings_edit(app_paths, key, old, new, labels)]
    rule_change = _folder_change(old, new, labels)
    out += [_edit(p, rule_change) for p in rule_files(app_paths.config_dir / "rules")]
    if app_paths.filing_codes_path.is_file():
        out.append(_edit(app_paths.filing_codes_path, rule_change))
    return [e for e in out if e is not None]


def _verify(change: FileChange, app_paths: AppPaths) -> Callable[[], bool]:
    def check() -> bool:
        try:
            if change.path.name == "settings.yaml":
                load_settings(app_paths)
            elif change.path == app_paths.filing_codes_path:
                yaml.safe_load(change.path.read_text(encoding="utf-8"))
            else:
                load_rule_file(change.path)
            return change.path.read_bytes().decode("utf-8") == change.written
        except (ValueError, yaml.YAMLError, OSError):
            return False

    return check


def _check_writable(changes: list[FileChange]) -> None:
    """``Conflict`` before anything moves when a file that has to change cannot be written
    (a rename that stops half way on this would leave the folder and the settings apart)."""
    for change in changes:
        if not os.access(change.path, os.W_OK) or not os.access(change.path.parent, os.W_OK):
            raise Conflict(
                f"{change.path.name} cannot be written ({change.path.parent}). Make it "
                "writable and try again; nothing was changed."
            )


def _write_config(app_paths: AppPaths, changes: list[FileChange]) -> None:
    """Write the files, settings last (the file the next start reads first); a file that
    cannot be written gets its old content back and the error is raised. Each replaced file
    is kept as ``.bak-<time>`` (``write_config_file``)."""
    ordered = sorted(changes, key=lambda c: c.path.name == "settings.yaml")
    for change in ordered:
        write_config_file(change.path, change.written, _verify(change, app_paths))


# --- what stores the name: the database --------------------------------------------------


_DB_COLUMNS = {
    "ongoing_entries": (ongoing_entries, "rel"),
    "collections": (collections, "ongoing_rel"),
    "maintenance_ignored": (maintenance_ignored, "key"),
}


def _db_changes(
    conn: Connection, old: str, new: str, labels: tuple[str, ...]
) -> dict[str, list[list]]:
    """The stored paths under ``old`` that are state, not history (the publisher's records
    and Maintenance's ignored results), as ``[row id, old value, new value]`` per table.
    Nothing is written."""
    out: dict[str, list[list]] = {t: [] for t in _DB_COLUMNS}
    for row_id, rel in conn.execute(select(ongoing_entries.c.id, ongoing_entries.c.rel)).all():
        if (moved := swap(rel, old, new, labels)) is not None:
            out["ongoing_entries"].append([row_id, rel, moved])
    for row_id, rel in conn.execute(select(collections.c.id, collections.c.ongoing_rel)).all():
        if (moved := swap(rel, old, new, labels)) is not None:
            out["collections"].append([row_id, rel, moved])
    ignored = conn.execute(
        select(maintenance_ignored.c.id, maintenance_ignored.c.kind, maintenance_ignored.c.key)
    )
    for row_id, kind, found in ignored.all():
        if kind not in GROUPS and (moved := swap(found, old, new, labels)) is not None:
            out["maintenance_ignored"].append([row_id, found, moved])
    return out


def _db_set(conn: Connection, changes: dict[str, list[list]], forward: bool) -> None:
    """Apply (or take back) recorded ``changes``: a row is only changed while it still has
    the value the change started from, so what else was written since stays."""
    for table, rows in changes.items():
        t, column = _DB_COLUMNS[table]
        for row_id, was, now in rows:
            start, end = (was, now) if forward else (now, was)
            conn.execute(
                update(t).where(t.c.id == row_id, t.c[column] == start).values({column: end})
            )


def _links_into(conn: Connection, paths: ArchivePaths, rels: list[str]) -> tuple[int, int]:
    """(managed links, other links) whose target lies at or inside one of the folders
    ``rels``: the publisher's records say where each link points (the readlink value), the
    index lists every other link by its target."""
    areas = [fold_name(str(paths.abs(r))) for r in rels]

    def inside(value: str | None) -> bool:
        v = fold_name(value or "")
        return any(v == a or v.startswith(a + os.sep) for a in areas)

    managed = {
        rel
        for rel, value in conn.execute(
            select(ongoing_entries.c.rel, ongoing_entries.c.link_value).where(
                ongoing_entries.c.kind == "link"
            )
        ).all()
        if inside(value)
    }
    total = 0
    for rel in rels:
        total += conn.execute(
            select(func.count())
            .select_from(files)
            .where(files.c.is_link.is_(True), _target_under(nfc(rel)))
        ).scalar_one()
    return len(managed), max(0, total - len(managed))


def _target_under(folder_nfc: str):
    return (files.c.link_target == folder_nfc) | (
        files.c.link_target.like(folder_nfc.replace("%", "\\%").replace("_", "\\_") + "/%", "\\")
    )


# --- preview -----------------------------------------------------------------------------


def preview(
    app_paths: AppPaths,
    paths: ArchivePaths,
    engine: Engine,
    executor: Executor,
    key: str,
    raw_name: str,
) -> Preview:
    """Everything renaming ``key`` to ``raw_name`` would change, read only. The refusals
    are the real ones: ``InvalidRequest`` (400) for a name or setting that cannot be used,
    ``Conflict`` (409) for a disk that is away or an interrupted operation, and the
    executor's own (a locked file, a guard) as ``GuardError``."""
    new = check_name(key, raw_name, paths)
    settings = paths.settings
    old = getattr(settings.special_folders, key)
    title = TITLES[key]
    _refusals(key, paths, engine)
    rels = targets(key, paths)
    if _nothing_to_rename(key, rels, old):
        raise InvalidRequest(
            f"The {title} folder '{old}' is not in the archive yet, so there is nothing to "
            "rename. Create it first (Settings, or the first-run layout)."
        )
    resolved = executor.preview(_plan(key, rels, new, title, old))
    for rop, rel in zip(resolved, rels, strict=True):
        wanted = rel.rpartition("/")[0]
        wanted = f"{wanted}/{new}" if wanted else new
        if rop.dst != wanted:
            raise GuardError(f"'{wanted}' is taken, so the folder cannot be renamed to it.")
    labels = _labels(key, settings)
    try:
        edits = config_edits(app_paths, key, old, new, labels)
    except (YamlEditError, OSError, yaml.YAMLError) as e:
        raise InvalidRequest(
            f"A setting or rule that holds the name cannot be edited safely: {e}"
        ) from None
    _check_writable(edits)
    out = Preview(key, title, old, new, google_drive=on_google_drive(paths.root))
    places = out.places
    where = "" if len(rels) == 1 else f" in each of the {len(rels)} archive folders"
    places.append(
        Place(
            "Folder on disk",
            RENAMED,
            f"'{old}' is renamed to '{new}'{where}, by a journaled rename on its own disk.",
        )
    )
    with engine.connect() as conn:
        indexed = sum(
            conn.execute(
                select(func.count()).select_from(files).where(at_or_below(nfc(r)))
            ).scalar_one()
            for r in rels
        )
        db = {k: len(v) for k, v in _db_changes(conn, old, new, labels).items()}
        managed, other = _links_into(conn, paths, rels)
    places.append(
        Place("Index", RENAMED, f"{indexed} file and folder paths in the index follow the folder.")
    )
    places.extend(_config_places(app_paths, key, edits))
    places.extend(_publisher_places(key, db, managed))
    places.append(
        Place(
            "Collections, trays, tags, notes, locks",
            UNCHANGED,
            "They belong to a file, not to a path, so nothing changes for them.",
        )
    )
    places.append(
        Place(
            "Earlier entries in Activity",
            UNCHANGED,
            "They keep the old name as history. An older change that touched a path under "
            "the folder can be undone again after this rename is undone.",
        )
    )
    places.append(
        Place(
            "Scanner, watcher, publishers",
            REBUILT,
            "The archive is closed and opened again, so they start with the new name. "
            "This takes a few seconds.",
        )
    )
    if other:
        out.warnings.append(
            f"{other} shortcut{'s' if other != 1 else ''} elsewhere in the archive "
            f"point{'s' if other == 1 else ''} into '{old}'. They are not part of Ongoing or "
            "Important, so dam leaves them alone: they will not find their file until you "
            "remake them."
        )
    if out.google_drive:
        out.warnings.append(SYNC_NOTE)
    return out


def _config_places(app_paths: AppPaths, key: str, edits: list[FileChange]) -> list[Place]:
    config = app_paths.config_dir
    settings_edit = next((e for e in edits if e.path.name == "settings.yaml"), None)
    rule_edits = [e for e in edits if e.path.parent == config / "rules"]
    code_edit = next((e for e in edits if e.path == app_paths.filing_codes_path), None)
    more = ""
    if settings_edit is not None:
        followed = [e for e in settings_edit.edits if e[0][0] in ("protected_paths", "ai")]
        if followed:
            more = ", and the protected or excluded folders that start with the old name follow"
            if "protected_paths" not in (yaml.safe_load(settings_edit.before) or {}):
                more = (
                    ", and protected_paths is written out, because the built-in default "
                    "list has to follow the name too"
                )
    out = [
        Place(
            "config/settings.yaml",
            RENAMED,
            f"special_folders: {key} gets the new name{more}. The old file is kept next to "
            "it as settings.yaml.bak-<time>.",
        )
    ]
    if rule_edits:
        n = sum(len(e.lines) for e in rule_edits)
        names = ", ".join(e.path.name for e in rule_edits)
        out.append(
            Place(
                "Rules",
                RENAMED,
                f"{n} folder value{'s' if n != 1 else ''} in {names} start with the old name "
                "and follow it. Comments and layout stay as they are.",
            )
        )
    else:
        out.append(Place("Rules", UNCHANGED, "No rule has a folder that starts with the old name."))
    if code_edit:
        n = len(code_edit.lines)
        out.append(
            Place(
                "Filing codes",
                RENAMED,
                f"{n} folder value{'s' if n != 1 else ''} in filing_codes.yaml follow the folder.",
            )
        )
    else:
        out.append(
            Place(
                "Filing codes",
                UNCHANGED,
                "Their inbox folders (such as To pay) are stored inside the Inbox by name only, "
                "so they follow it as they are."
                if key == "inbox"
                else "No filing code has a folder that starts with the old name.",
            )
        )
    return out


def _publisher_places(key: str, db: dict[str, int], managed: int) -> list[Place]:
    out: list[Place] = []
    records = db["ongoing_entries"] + db["collections"]
    if key in ("ongoing", "important"):
        out.append(
            Place(
                "Ongoing and Important: records",
                RENAMED,
                f"The {records} entries dam keeps a record of in the folder get the new path. "
                "The shortcuts inside keep pointing at the same files, so they stay valid.",
            )
        )
    else:
        out.append(
            Place(
                "Ongoing and Important: records",
                UNCHANGED,
                "Neither folder is renamed, so their entries keep their paths.",
            )
        )
    if managed:
        out.append(
            Place(
                "Ongoing and Important: shortcuts",
                REBUILT,
                f"{managed} shortcut{'s' if managed != 1 else ''} to files in the folder: the "
                "sync that runs when the archive opens again makes them point at the new path.",
            )
        )
    else:
        out.append(
            Place(
                "Ongoing and Important: shortcuts",
                UNCHANGED,
                "No shortcut dam manages points into the folder, so they all stay valid.",
            )
        )
    if db["maintenance_ignored"]:
        n = db["maintenance_ignored"]
        out.append(
            Place(
                "Maintenance: ignored results",
                RENAMED,
                f"{n} ignored result{'s' if n != 1 else ''} keep their place under the new name.",
            )
        )
    return out


# --- apply -------------------------------------------------------------------------------


def _executor(app_paths: AppPaths, engine: Engine) -> tuple[Executor, ArchivePaths]:
    """An operation layer for the closed archive: what the App builds, without the rest."""
    settings = load_settings(app_paths)
    if settings.archive_root is None:
        raise Conflict("No archive folder is set.")
    paths = ArchivePaths(settings.archive_root, settings)
    repo = FileRepo(engine, inbox=settings.special_folders.inbox)
    paths.has_rows = repo.has_live_under
    executor = Executor(
        paths, engine, repo, throttle_ms=0, areas_dir=app_paths.config_dir / "rules" / AREAS_DIR
    )
    return executor, paths


def _journal_states(engine: Engine, batch_id: str) -> list[str]:
    with engine.connect() as conn:
        return [
            s
            for (s,) in conn.execute(
                select(operations.c.state).where(operations.c.batch_id == batch_id)
            ).all()
        ]


def _set_state(engine: Engine, batch_id: str, state: str, note: str | None = None) -> None:
    with write_tx(engine) as conn:
        conn.execute(
            update(special_folder_renames)
            .where(special_folder_renames.c.batch_id == batch_id)
            .values(state=state, note=note, finished=time.time())
        )


def rename_folder(app_paths: AppPaths, key: str, raw_name: str) -> Renamed:
    """Rename the special folder ``key``. Call with the archive closed
    (``Host.close_and_reopen``). The checks of ``preview`` run again; a snapshot is taken;
    the rename is recorded, the folder is renamed through the executor, and the settings,
    rules and stored paths follow. The folder is only left renamed when every disk's folder
    was; otherwise what was done is undone, and when that cannot be done the rename stays
    recorded (``planned`` or ``attention``) with the reason, for the next start or for Undo
    in Activity. It is never marked failed while a folder has moved."""
    engine = make_engine(app_paths.db_path)
    try:
        executor, paths = _executor(app_paths, engine)
        new = check_name(key, raw_name, paths)
        old = getattr(paths.settings.special_folders, key)
        _refusals(key, paths, engine)
        rels = targets(key, paths)
        if _nothing_to_rename(key, rels, old):
            raise InvalidRequest(f"The {TITLES[key]} folder '{old}' is not in the archive yet.")
        labels = _labels(key, paths.settings)
        # the config edits are computed (and checked) before anything moves
        try:
            changes = config_edits(app_paths, key, old, new, labels)
        except (YamlEditError, OSError, yaml.YAMLError) as e:
            raise InvalidRequest(
                f"A setting or rule that holds the name cannot be edited safely: {e}"
            ) from None
        _check_writable(changes)
        try:
            create_snapshot(app_paths, kind=BEFORE_RENAME)
        except OSError as e:
            raise Conflict(f"Could not take a snapshot first ({e}). Nothing was changed.") from None
        plan = _plan(key, rels, new, TITLES[key], old)
        batch_id = uuid4().hex
        with write_tx(engine) as conn:
            conn.execute(
                insert(special_folder_renames).values(
                    batch_id=batch_id,
                    key=key,
                    old=old,
                    new=new,
                    state=_PLANNED,
                    folders=len(rels),
                    created=time.time(),
                )
            )
        failure: Exception | None = None
        result = None
        try:
            result = executor.apply(plan, batch_id=batch_id)
        except Exception as e:
            failure = e
        complete = (
            failure is None
            and result is not None
            and result.failed is None
            and result.error is None
            and result.index_error is None
            and not result.stopped
            and len(result.done) == len(plan.ops)
        )
        if not complete:
            why = str(failure) if failure else _why(result)
            stuck = _back_out(engine, executor, batch_id, why)
            if stuck is None:
                if isinstance(failure, InvalidRequest | GuardError):
                    raise failure
                raise Conflict(f"The folder could not be renamed ({why}). Nothing was changed.")
            raise Conflict(stuck)
        roll_forward(app_paths, engine, batch_id, key, old, new, labels)
        return Renamed(batch_id, key, old, new)
    finally:
        engine.dispose()


def _why(result) -> str:
    if result is None:
        return "it did not run"
    if result.error:
        return result.error
    if result.failed is not None:
        return f"{result.failed.src} could not be renamed"
    if result.index_error:
        return result.index_error
    if result.stopped:
        return "it was stopped"
    return f"only {len(result.done)} of its folders were renamed"


def _back_out(engine: Engine, executor: Executor, batch_id: str, why: str) -> str | None:
    """Take back whatever the batch did, from the journal and not from what the call saw.
    None: nothing is left renamed, and the rename is marked failed (the only time it is).
    Otherwise the message for the owner: an operation still ``planned`` in the journal waits
    for Run recovery (the rename stays ``planned``, finished at the next start), anything
    else that could not be put back is marked ``attention`` with the reason, and Undo in
    Activity tries again."""
    states = _journal_states(engine, batch_id)
    if "planned" in states:
        note = "a move was not recorded as finished"
        with write_tx(engine) as conn:
            conn.execute(
                update(special_folder_renames)
                .where(special_folder_renames.c.batch_id == batch_id)
                .values(note=note)
            )
        return (
            f"The folder rename stopped ({why}) and a folder may have moved. Run recovery "
            "(Run recovery in the app), then restart dam: it finishes or takes back the "
            "rename then."
        )
    if any(s in ACTED for s in states):
        problem = None
        try:
            undone = executor.undo(batch_id)
            if undone.failed is not None or undone.error is not None:
                problem = undone.error or f"{undone.failed.src} could not be renamed back"
        except Exception as e:
            problem = str(e)
        if problem is None and any(s in ACTED for s in _journal_states(engine, batch_id)):
            problem = "some folders are still renamed"
        if problem is not None:
            _set_state(engine, batch_id, _ATTENTION, problem)
            return (
                f"The folder rename stopped ({why}) and could not be taken back ({problem}). "
                "Some folders have the new name. Undo this change in Activity once the "
                "problem is fixed; dam also tries again at the next start."
            )
    _set_state(engine, batch_id, _FAILED)
    return None


# --- the record of what changed ---------------------------------------------------------------


def _record(engine: Engine, batch_id: str) -> dict:
    row = _row(engine, batch_id)
    raw = row["changes"] if row is not None else None
    data = json.loads(raw) if raw else {}
    data.setdefault("files", {})
    data.setdefault("db", {})
    return data


def _merged(record: dict, files: list[FileChange], config: Path, db: dict) -> dict:
    """``record`` with these changes added (a change already in it is not added twice)."""
    for change in files:
        name = change.path.relative_to(config).as_posix()
        have = record["files"].setdefault(name, [])
        have += [e for e in change.edits if e not in have]
    for table, rows in db.items():
        have = record["db"].setdefault(table, [])
        known = {r[0] for r in have}
        have += [r for r in rows if r[0] not in known]
    return record


def _undo_edits(app_paths: AppPaths, record: dict) -> list[FileChange]:
    """The files with exactly the recorded values put back (a value is only changed while
    it is still what the rename made it)."""
    out: list[FileChange] = []
    for name, edits in record["files"].items():
        path = app_paths.config_dir / name
        if not path.is_file():
            continue
        wanted = {tuple(at): (was, now) for at, was, now in edits}

        def change(at: tuple, value: str, wanted=wanted) -> str | None:
            was, now = wanted.get(tuple(at), (None, None))
            return was if now is not None and value == now else None

        edit = _edit(path, change)
        if edit is not None:
            out.append(edit)
    return out


def roll_forward(
    app_paths: AppPaths,
    engine: Engine,
    batch_id: str,
    key: str,
    old: str,
    new: str,
    labels: tuple[str, ...],
) -> None:
    """Every folder is renamed: make the settings, rules and stored paths say so, then mark
    the rename done. What is going to change is recorded first, so Undo (and a rerun after
    an interruption) puts back exactly that and nothing else. Safe to run again. If a file
    cannot be written the rename stays recorded as ``attention`` with the reason, and the
    error is raised."""
    changes = config_edits(app_paths, key, old, new, labels)
    known = _record(engine, batch_id)
    with write_tx(engine) as conn:
        db = _db_changes(conn, old, new, labels)
        record = _merged(known, changes, app_paths.config_dir, db)
        conn.execute(
            update(special_folder_renames)
            .where(special_folder_renames.c.batch_id == batch_id)
            .values(changes=json.dumps(record))
        )
    try:
        _write_config(app_paths, changes)
    except Exception as e:
        _set_state(engine, batch_id, _ATTENTION, f"a setting could not be written: {e}")
        raise Conflict(
            f"The folder was renamed, but {e}. Make the file writable and restart dam, or undo "
            "this change in Activity."
        ) from None
    with write_tx(engine) as conn:
        _db_set(conn, db, forward=True)
        conn.execute(
            update(special_folder_renames)
            .where(special_folder_renames.c.batch_id == batch_id)
            .values(state=_DONE, note=None, finished=time.time())
        )


def roll_back(app_paths: AppPaths, engine: Engine, batch_id: str) -> None:
    """The folders have their old names again: put back the recorded values in the settings,
    rules and stored paths, and mark the rename undone. Safe to run again."""
    record = _record(engine, batch_id)
    _write_config(app_paths, _undo_edits(app_paths, record))
    with write_tx(engine) as conn:
        _db_set(conn, record["db"], forward=False)
        conn.execute(
            update(special_folder_renames)
            .where(special_folder_renames.c.batch_id == batch_id)
            .values(state=_UNDONE, note=None, finished=time.time())
        )


# --- undo --------------------------------------------------------------------------------


def _row(engine: Engine, batch_id: str):
    with engine.connect() as conn:
        return (
            conn.execute(
                select(special_folder_renames).where(special_folder_renames.c.batch_id == batch_id)
            )
            .mappings()
            .first()
        )


def is_rename(engine: Engine, batch_id: str) -> bool:
    """``batch_id`` is a special folder rename (its undo also restores settings and rules)."""
    return _row(engine, batch_id) is not None


def undo(app_paths: AppPaths, batch_id: str):
    """Undo the rename ``batch_id``: the executor renames the folder(s) back, then exactly
    the recorded values in the settings, rules and stored paths are put back. Call with the
    archive closed. Returns the executor's ``BatchResult`` of the undo. When only some
    folders could be renamed back, ``Conflict`` says so and the rename stays undoable: undo
    again once the problem is fixed."""
    engine = make_engine(app_paths.db_path)
    try:
        row = _row(engine, batch_id)
        if row is None:
            raise NotFound(f"batch {batch_id}")
        if row["state"] == _UNDONE:
            raise Conflict("This rename was undone already.")
        if row["state"] == _FAILED:
            raise Conflict("This rename never happened, so there is nothing to undo.")
        if row["state"] == _PLANNED:
            raise Conflict(UNFINISHED.format(why=""))
        executor, paths = _executor(app_paths, engine)
        try:
            _check_writable(_undo_edits(app_paths, _record(engine, batch_id)))
        except (YamlEditError, yaml.YAMLError, OSError) as e:
            raise InvalidRequest(f"A setting or rule cannot be put back safely: {e}") from None
        if "planned" in _journal_states(engine, batch_id):
            raise Conflict(INTERRUPTED)
        result = executor.undo(batch_id)
        left = [s for s in _journal_states(engine, batch_id) if s in ACTED]
        if result.failed is not None or result.error is not None or left:
            message = result.error or (
                f"{result.failed.src} could not be renamed back" if result.failed else "see the log"
            )
            raise Conflict(
                f"Only {len(result.done)} of {row['folders']} folders were renamed back "
                f"({message}). The settings and rules are still on the new name. Fix the "
                "problem and undo this change again."
            )
        roll_back(app_paths, engine, batch_id)
        return result
    finally:
        engine.dispose()


# --- an interruption ----------------------------------------------------------------------


def _unfinished(engine: Engine) -> list:
    """The renames that are not settled: ``planned`` and ``attention``, and ``done`` ones
    whose folders were all undone (an undo cut short before it put the settings back)."""
    with engine.connect() as conn:
        rows = (
            conn.execute(
                select(special_folder_renames).where(
                    special_folder_renames.c.state.in_((_PLANNED, _DONE, _ATTENTION))
                )
            )
            .mappings()
            .all()
        )
    out = []
    for row in rows:
        if row["state"] != _DONE:
            out.append(row)
            continue
        states = _journal_states(engine, row["batch_id"])
        if states and not any(s in ACTED for s in states) and all(s == "undone" for s in states):
            out.append(row)
    return out


def has_unfinished(engine: Engine) -> bool:
    return bool(_unfinished(engine))


def reconcile(app_paths: AppPaths) -> int:
    """Finish a rename an interruption left half done (``dam serve`` calls it with the
    archive closed and the lock held, never another process). A planned rename whose folders
    all moved gets its settings and stored paths; one with only some folders moved is taken
    back; one whose journal shows nothing acted is marked failed; a done rename whose
    folders were undone gets the old settings back. A journal row still ``planned`` waits for
    Run recovery. Whatever cannot be settled is marked ``attention`` with the reason, so
    Undo in Activity can take it. Returns how many renames it settled."""
    if not app_paths.db_path.exists():
        return 0
    engine = make_engine(app_paths.db_path)
    settled = 0
    try:
        if "special_folder_renames" not in inspect(engine).get_table_names():
            return 0
        for row in _unfinished(engine):
            try:
                settled += _settle(app_paths, engine, row)
            except Exception as e:
                log.exception("could not finish the rename of %s", row["old"])
                if row["state"] == _PLANNED:
                    _set_state(engine, row["batch_id"], _ATTENTION, str(e))
    finally:
        engine.dispose()
    return settled


def _settle(app_paths: AppPaths, engine: Engine, row) -> int:
    states = _journal_states(engine, row["batch_id"])
    if "planned" in states:
        return 0  # an interrupted move: Run recovery settles it, then this
    acted = [s for s in states if s in ACTED]
    if row["state"] == _DONE:  # the folders were undone, the settings were not put back
        roll_back(app_paths, engine, row["batch_id"])
        return 1
    if not acted:
        _set_state(engine, row["batch_id"], _FAILED)
        return 1
    if len(acted) < row["folders"]:
        # some disks were renamed and some not: put the renamed ones back
        executor, _ = _executor(app_paths, engine)
        stuck = _back_out(engine, executor, row["batch_id"], "it was interrupted")
        return 0 if stuck else 1
    labels: tuple[str, ...] = ()
    if row["key"] == "quarantine":
        labels = tuple(e.label for e in load_settings(app_paths).extra_folders)
    roll_forward(app_paths, engine, row["batch_id"], row["key"], row["old"], row["new"], labels)
    return 1
