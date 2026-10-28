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
from dam.config import AppPaths, SpecialFolders, load_settings
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
_DONE, _UNDONE, _PLANNED, _FAILED = "done", "undone", "planned", "failed"


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
    path: Path
    lines: list[int]
    text: str  # the new content
    before: str  # the content now


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
        pending = conn.execute(
            select(special_folder_renames.c.id)
            .where(special_folder_renames.c.state == _PLANNED)
            .limit(1)
        ).first()
    if pending:
        raise Conflict(INTERRUPTED)


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


def _settings_edit(
    app_paths: AppPaths, key: str, old: str, new: str, labels: tuple[str, ...]
) -> FileChange | None:
    """The settings file with the name changed. When the file does not spell the name
    out (the built-in default is in use) the whole ``special_folders`` entry is written."""
    path = app_paths.config_dir / "settings.yaml"
    edit = _edit(path, _settings_change(key, old, new, labels))
    before = edit.before if edit else path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    text = edit.text if edit else before
    data = yaml.safe_load(text) or {}
    written = (data.get("special_folders") or {}).get(key)
    if isinstance(written, str) and fold_name(written) == fold_name(new):
        return edit
    names = SpecialFolders().model_dump()
    names.update(data.get("special_folders") or {})
    names[key] = new
    text = with_keys(text, {"special_folders": names})
    return FileChange(path, edit.lines if edit else [], text, before)


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
            return change.path.read_bytes().decode("utf-8") == change.text
        except (ValueError, yaml.YAMLError, OSError):
            return False

    return check


def _write_config(app_paths: AppPaths, changes: list[FileChange]) -> None:
    """Write the files, settings last (the file the next start reads first); a file that
    cannot be written gets its old content back and the error is raised. Each replaced file
    is kept as ``.bak-<time>`` (``write_config_file``)."""
    ordered = sorted(changes, key=lambda c: c.path.name == "settings.yaml")
    for change in ordered:
        write_config_file(change.path, change.text, _verify(change, app_paths))


# --- what stores the name: the database --------------------------------------------------


def _db(
    conn: Connection, old: str, new: str, labels: tuple[str, ...], write: bool
) -> dict[str, int]:
    """Rewrite (or, without ``write``, count) the stored paths under ``old`` that are
    state, not history: the publisher's records and Maintenance's ignored results."""
    counts = {"ongoing_entries": 0, "collections": 0, "maintenance_ignored": 0}
    for row_id, rel in conn.execute(select(ongoing_entries.c.id, ongoing_entries.c.rel)).all():
        moved = swap(rel, old, new, labels)
        if moved is None:
            continue
        counts["ongoing_entries"] += 1
        if write:
            conn.execute(
                update(ongoing_entries).where(ongoing_entries.c.id == row_id).values(rel=moved)
            )
    for row_id, rel in conn.execute(select(collections.c.id, collections.c.ongoing_rel)).all():
        moved = swap(rel, old, new, labels)
        if moved is None:
            continue
        counts["collections"] += 1
        if write:
            conn.execute(
                update(collections).where(collections.c.id == row_id).values(ongoing_rel=moved)
            )
    ignored = conn.execute(
        select(maintenance_ignored.c.id, maintenance_ignored.c.kind, maintenance_ignored.c.key)
    )
    for row_id, kind, found in ignored.all():
        moved = None if kind in GROUPS else swap(found, old, new, labels)
        if moved is None:
            continue
        counts["maintenance_ignored"] += 1
        if write:
            conn.execute(
                update(maintenance_ignored)
                .where(maintenance_ignored.c.id == row_id)
                .values(key=moved)
            )
    return counts


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
    if not rels or fold_name(rels[0]) != fold_name(old):
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
        db = _db(conn, old, new, labels, write=False)
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
    out = [
        Place(
            "config/settings.yaml",
            RENAMED,
            f"special_folders: {key} gets the new name"
            + (
                ", and the protected or excluded folders that start with the old name follow"
                if settings_edit and len(settings_edit.lines) > 1
                else ""
            )
            + ". The old file is kept next to it as settings.yaml.bak-<time>.",
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


def rename_folder(app_paths: AppPaths, key: str, raw_name: str) -> Renamed:
    """Rename the special folder ``key``. Call with the archive closed
    (``Host.close_and_reopen``). The checks of ``preview`` run again; then the rename is
    recorded, the folder is renamed through the executor, and the settings, rules and stored
    paths follow. If the folder cannot be renamed on every disk, what was done is undone and
    nothing else changes."""
    engine = make_engine(app_paths.db_path)
    try:
        executor, paths = _executor(app_paths, engine)
        new = check_name(key, raw_name, paths)
        old = getattr(paths.settings.special_folders, key)
        _refusals(key, paths, engine)
        rels = targets(key, paths)
        if not rels or fold_name(rels[0]) != fold_name(old):
            raise InvalidRequest(f"The {TITLES[key]} folder '{old}' is not in the archive yet.")
        labels = _labels(key, paths.settings)
        # the config edits are computed (and checked) before anything moves
        try:
            config_edits(app_paths, key, old, new, labels)
        except (YamlEditError, OSError, yaml.YAMLError) as e:
            raise InvalidRequest(
                f"A setting or rule that holds the name cannot be edited safely: {e}"
            ) from None
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
        try:
            result = executor.apply(plan, batch_id=batch_id)
        except BaseException:
            _fail(engine, batch_id)
            raise
        if result.failed is not None or result.error is not None:
            message = result.error or f"{result.failed.src} could not be renamed."
            _roll_back_partial(executor, engine, batch_id, result)
            raise Conflict(f"The folder could not be renamed ({message}). Nothing was changed.")
        roll_forward(app_paths, engine, batch_id, key, old, new, labels)
        return Renamed(batch_id, key, old, new)
    finally:
        engine.dispose()


def _fail(engine: Engine, batch_id: str) -> None:
    with write_tx(engine) as conn:
        conn.execute(
            update(special_folder_renames)
            .where(special_folder_renames.c.batch_id == batch_id)
            .values(state=_FAILED, finished=time.time())
        )


def _roll_back_partial(executor: Executor, engine: Engine, batch_id: str, result) -> None:
    """A rename that stopped part way (one disk done, a later one not): put the done ones
    back through the executor's undo, and note that the rename did not happen."""
    if result.done:
        try:
            executor.undo(batch_id)
        except Exception:
            log.exception("could not undo the part of the rename that was done")
    _fail(engine, batch_id)


def roll_forward(
    app_paths: AppPaths,
    engine: Engine,
    batch_id: str,
    key: str,
    old: str,
    new: str,
    labels: tuple[str, ...],
) -> None:
    """The folder is renamed: make the settings, rules and stored paths say so, then mark
    the rename done. Safe to run again (a value already changed is left as it is)."""
    _write_config(app_paths, config_edits(app_paths, key, old, new, labels))
    with write_tx(engine) as conn:
        _db(conn, old, new, labels, write=True)
        conn.execute(
            update(special_folder_renames)
            .where(special_folder_renames.c.batch_id == batch_id)
            .values(state=_DONE, finished=time.time())
        )


def roll_back(
    app_paths: AppPaths,
    engine: Engine,
    batch_id: str,
    key: str,
    old: str,
    new: str,
    labels: tuple[str, ...],
) -> None:
    """The folder has its old name again: put back the settings, rules and stored paths
    (``roll_forward`` the other way round), and mark the rename undone."""
    _write_config(app_paths, config_edits(app_paths, key, new, old, labels))
    with write_tx(engine) as conn:
        _db(conn, new, old, labels, write=True)
        conn.execute(
            update(special_folder_renames)
            .where(special_folder_renames.c.batch_id == batch_id)
            .values(state=_UNDONE, finished=time.time())
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
    """Undo the rename ``batch_id``: the executor renames the folder(s) back, then the
    settings, rules and stored paths are restored. Call with the archive closed. Returns
    the executor's ``BatchResult`` of the undo."""
    engine = make_engine(app_paths.db_path)
    try:
        row = _row(engine, batch_id)
        if row is None:
            raise NotFound(f"batch {batch_id}")
        if row["state"] == _UNDONE:
            raise Conflict("This rename was undone already.")
        if row["state"] != _DONE:
            raise Conflict(INTERRUPTED)
        executor, paths = _executor(app_paths, engine)
        with engine.connect() as conn:
            if conn.execute(
                select(operations.c.id).where(operations.c.state == "planned").limit(1)
            ).first():
                raise Conflict(INTERRUPTED)
        result = executor.undo(batch_id)
        if result.failed is not None or result.error is not None:
            message = result.error or f"{result.failed.src} could not be renamed back."
            raise Conflict(f"The rename could not be undone ({message}).")
        roll_back(
            app_paths, engine, batch_id, row["key"], row["old"], row["new"],
            _labels(row["key"], paths.settings),
        )
        return result
    finally:
        engine.dispose()


# --- an interruption ----------------------------------------------------------------------


def reconcile(app_paths: AppPaths) -> int:
    """Finish a rename an interruption left half done; called before the settings are read.
    A planned rename whose folder moved gets its settings and stored paths (forward); one
    whose journal shows nothing acted is marked failed; a done rename whose folder was
    undone gets them back. A journal row still ``planned`` is left for Run recovery.
    Returns how many renames it settled."""
    if not app_paths.db_path.exists():
        return 0
    engine = make_engine(app_paths.db_path)
    settled = 0
    try:
        if "special_folder_renames" not in inspect(engine).get_table_names():
            return 0
        with engine.connect() as conn:
            rows = (
                conn.execute(
                    select(special_folder_renames).where(
                        special_folder_renames.c.state.in_((_PLANNED, _DONE))
                    )
                )
                .mappings()
                .all()
            )
        for row in rows:
            try:
                settled += _settle(app_paths, engine, row)
            except Exception:
                log.exception("could not finish the rename of %s", row["old"])
    finally:
        engine.dispose()
    return settled


def _settle(app_paths: AppPaths, engine: Engine, row) -> int:
    with engine.connect() as conn:
        states = [
            s
            for (s,) in conn.execute(
                select(operations.c.state).where(operations.c.batch_id == row["batch_id"])
            ).all()
        ]
    if "planned" in states:
        return 0  # an interrupted move: Run recovery settles it, then this
    acted = [s for s in states if s in ACTED]
    labels: tuple[str, ...] = ()
    if row["key"] == "quarantine":
        labels = tuple(e.label for e in load_settings(app_paths).extra_folders)
    if row["state"] == _PLANNED:
        if not acted:
            _fail(engine, row["batch_id"])
            return 1
        if len(acted) < row["folders"]:
            # some disks were renamed and some not: put the renamed ones back
            executor, _ = _executor(app_paths, engine)
            executor.undo(row["batch_id"])
            _fail(engine, row["batch_id"])
            return 1
        # every folder moved, the rest did not finish: go on from there
        roll_forward(
            app_paths, engine, row["batch_id"], row["key"], row["old"], row["new"], labels
        )
        return 1
    if states and not acted and all(s == "undone" for s in states):
        roll_back(app_paths, engine, row["batch_id"], row["key"], row["old"], row["new"], labels)
        return 1
    return 0
