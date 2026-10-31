"""Rename an ordinary folder of the archive in place: same parent, a new name (Browse).

The folder is renamed on disk by one journaled ``RENAME`` (Activity shows it, Undo takes it
back), and everything that stores its path follows, as for a special folder
(``dam.special_folders``, whose record, undo and recovery this shares; ``key`` is
``folder`` and ``old``/``new`` are the folder's archive paths):

* the index: the executor re-paths the folder's rows and the search rows;
* the rules' ``folder`` and ``folder_is`` values and the filing codes' ``folder`` values
  that are the folder or lie under it, and the ``inbox_folder`` names of a folder that lies
  directly in the inbox;
* ``config/settings.yaml``: the ``protected_paths`` and ``ai.exclude_folders`` entries;
* Maintenance's ignored results under the folder.

Collections, tray items, tags, notes and locks belong to a file or folder id, so they stay
with it; the Ongoing and Important shortcuts into the folder are rebuilt by the publisher's
sync when the archive opens again. The rename runs with the archive closed
(``Host.close_and_reopen``), so the scanner never writes the old paths back and the
reopened app reads the new rules and settings.

Refused (``InvalidRequest``): what is not a folder, the app's own folders and what is in
them (``##. …``, the inbox itself, the top of an archive folder), a name the archive's name
rules reject or one that is taken (never a silent ``_2``), and a folder holding a file that
is locked or marked Important.
"""

import os
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import yaml
from sqlalchemy import Engine, func, select

from dam.collections.marks import MarkService
from dam.collections.publishers import PublisherRegistry
from dam.collections.service import CollectionService
from dam.config import AppPaths
from dam.core.foldernames import FolderNameError, check_folder_name
from dam.core.paths import ArchivePaths, fold_name, nfc
from dam.core.yamledit import YamlEditError
from dam.db.engine import make_engine
from dam.db.tables import collection_members, collections, files, item_files, items
from dam.errors import Conflict, InvalidRequest, NotFound
from dam.index.repo import FileRecord, FileRepo
from dam.index.repo.model import at_or_below
from dam.locks import LockService
from dam.ops.executor import Executor
from dam.ops.model import Op, OpKind, Plan
from dam.services import check_disk_identity
from dam.special_folders import (
    FOLDER,
    REBUILT,
    RENAMED,
    SYNC_NOTE,
    UNCHANGED,
    UNDO_HOW,
    FileChange,
    Place,
    Renamed,
    check_writable,
    closed_executor,
    config_edits,
    db_changes,
    links_into,
    on_google_drive,
    refusals,
    run_rename,
)

ALREADY = "That is already the folder's name."


@dataclass
class FolderPreview:
    old: str  # the folder's name now
    new: str  # its new name
    path: str  # its archive path now
    new_path: str
    places: list[Place] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    google_drive: bool = False
    undo: str = UNDO_HOW
    batch_id: str | None = None


def _folder(repo: FileRepo, drive_id: str) -> FileRecord:
    rec = repo.get(drive_id)
    if rec is None or rec.missing or rec.parked_at is not None:
        raise NotFound(drive_id)
    if not rec.is_dir or rec.is_link:
        raise InvalidRequest(f"{rec.path} is not a folder: rename a file with Edit details")
    return rec


def _check_folder(rec: FileRecord, paths: ArchivePaths) -> None:
    """Refuse the app's own folders, what is inside Ongoing, Important and To Delete, and
    the top of an archive folder (the main folder or an extra folder's label)."""
    special = paths.settings.special_folders
    path = rec.path
    if paths.is_root(path) or any(fold_name(path) == fold_name(x) for x in paths.extra_labels):
        raise InvalidRequest(f"{path}: the top of an archive folder is renamed in Settings")
    if fold_name(path) == fold_name(special.inbox):
        raise InvalidRequest(
            f"{path}: the app keeps that folder; rename it in Settings, Special folders"
        )
    for area in (special.ongoing, special.important, *paths.quarantines):
        if fold_name(path) == fold_name(area) or fold_name(path).startswith(fold_name(area) + "/"):
            raise InvalidRequest(f"{path}: the app keeps {area}; rename it in Settings")


def check_name(rec: FileRecord, raw: str, paths: ArchivePaths) -> str:
    """The new name as it will be used, or ``InvalidRequest`` with the reason: the archive's
    name rules (no ``##.``), not the name it has, not a name taken in its folder (a change
    of letter case alone is fine), and at the top of the main folder not the name of a
    special folder or an extra folder's label."""
    try:
        clean = check_folder_name(raw)
    except FolderNameError as e:
        raise InvalidRequest(str(e)) from None
    if clean == nfc(rec.name):
        raise InvalidRequest(ALREADY)
    parent = rec.path.rpartition("/")[0]
    if not parent:
        special = paths.settings.special_folders
        taken = [*special.model_dump().values(), *paths.extra_labels]
        if any(fold_name(clean) == fold_name(x) for x in taken):
            raise InvalidRequest(
                f"'{clean}' is the name of a folder dam keeps. Choose another name."
            )
    if fold_name(clean) != fold_name(rec.name):
        try:
            with os.scandir(paths.abs(parent) if parent else paths.root) as entries:
                hit = next((e.name for e in entries if fold_name(e.name) == fold_name(clean)), None)
        except OSError:
            hit = None
        if hit is not None:
            where = parent or "the top of the archive"
            raise InvalidRequest(
                f"There is already a folder or file named '{hit}' in {where}. Choose another name."
            )
    return clean


def _new_path(rec: FileRecord, name: str) -> str:
    parent = rec.path.rpartition("/")[0]
    return f"{parent}/{name}" if parent else name


def _plan(rec: FileRecord, name: str) -> Plan:
    op = Op(OpKind.RENAME, rec.path, name, allow_top_level="/" not in rec.path)
    return Plan([op], origin="ui", label=f"Renamed folder {rec.name} to {name}")


def _check_taken(rec: FileRecord, name: str):
    """The executor's check: the resolved RENAME is the folder asked for (``check_disk_
    identity``) and lands on the name asked for (a ``_2`` means it was taken meanwhile)."""
    wanted = _new_path(rec, name)

    def check(ops) -> None:
        if len(ops) != 1 or ops[0].dst != wanted:
            raise InvalidRequest(
                f"There is already a folder or file named '{name}' there. Choose another name."
            )

    return check


def _edits(app_paths: AppPaths, old: str, new: str) -> list[FileChange]:
    try:
        edits = config_edits(app_paths, FOLDER, old, new, ())
    except (YamlEditError, OSError, yaml.YAMLError) as e:
        raise InvalidRequest(
            f"A setting or rule that holds the path cannot be edited safely: {e}"
        ) from None
    check_writable(edits)
    return edits


def preview(
    app_paths: AppPaths,
    paths: ArchivePaths,
    engine: Engine,
    executor: Executor,
    repo: FileRepo,
    drive_id: str,
    raw_name: str,
    refuse_important=None,
) -> FolderPreview:
    """Everything renaming the folder ``drive_id`` to ``raw_name`` would change, read only.
    The refusals are the real ones (see the module); ``refuse_important`` (the Browse
    service's) refuses a folder with a file marked Important in it, and the executor's
    guards a locked one. ``Conflict`` (409) for a disk that is away or an interrupted
    operation."""
    rec = _folder(repo, drive_id)
    _check_folder(rec, paths)
    name = check_name(rec, raw_name, paths)
    if refuse_important is not None:
        refuse_important([rec])
    label = paths.label_of(rec.path)
    refusals(FOLDER, paths, engine)
    if label and not paths.is_connected(label):
        raise Conflict(f"'{label}' is not connected. Connect it and try again.")
    plan = _plan(rec, name)
    resolved = executor.preview(plan)
    check_disk_identity(paths, repo, [rec.drive_id], resolved)
    _check_taken(rec, name)(resolved)
    old, new = rec.path, _new_path(rec, name)
    edits = _edits(app_paths, old, new)
    out = FolderPreview(rec.name, name, old, new, google_drive=on_google_drive(paths.root))
    folder = nfc(rec.path_nfc)
    with engine.connect() as conn:
        indexed = conn.execute(
            select(func.count()).select_from(files).where(at_or_below(folder))
        ).scalar_one()
        ids = select(files.c.drive_id).where(at_or_below(folder))
        in_collections = conn.execute(
            select(func.count(func.distinct(collection_members.c.collection_id)))
            .select_from(collection_members.join(collections))
            .where(collection_members.c.drive_id.in_(ids), collections.c.kind.is_(None))
        ).scalar_one()
        open_items = conn.execute(
            select(func.count(func.distinct(item_files.c.item_id)))
            .select_from(item_files.join(items))
            .where(item_files.c.drive_id.in_(ids), items.c.state == "open")
        ).scalar_one()
        ignored = len(db_changes(conn, old, new, ())["maintenance_ignored"])
        managed, other = links_into(conn, paths, [rec.path])
    stays = "they belong to the folder and its files, not to a path, so they stay with it"
    where = PurePosixPath(rec.path).parent.as_posix()
    where = "the top of the archive" if where == "." else where
    on_disk = f"'{rec.name}' becomes '{name}' in {where}, by a journaled rename."
    out.places += [
        Place("Folder on disk", RENAMED, on_disk),
        Place("Index", RENAMED, f"{indexed - 1} file and folder paths in it follow the folder."),
        *_config_places(app_paths, edits),
    ]
    if ignored:
        what = f"{_n(ignored, 'ignored result')} keep their place under the new name."
        out.places.append(Place("Maintenance: ignored results", RENAMED, what))
    held = (
        f"{_n(in_collections, 'collection')} hold the folder or files in it; {stays}."
        if in_collections
        else "No collection holds the folder or a file in it."
    )
    trays = (
        f"{_n(open_items, 'open tray item')} hold files in it; {stays}."
        if open_items
        else "No open tray item holds a file in it."
    )
    out.places += [Place("Collections", UNCHANGED, held), Place("Tray items", UNCHANGED, trays)]
    if managed:
        what = (
            f"{_n(managed, 'shortcut')} to the folder or files in it: the sync that runs when "
            "the archive opens again makes them point at the new path."
        )
        out.places.append(Place("Ongoing and Important: shortcuts", REBUILT, what))
    else:
        what = "No shortcut dam manages points into the folder."
        out.places.append(Place("Ongoing and Important: shortcuts", UNCHANGED, what))
    out.places += [
        Place(
            "Tags, notes, locks",
            UNCHANGED,
            "They belong to a file, not to a path, so nothing changes for them.",
        ),
        Place("Earlier entries in Activity", UNCHANGED, "They keep the old path as history."),
        Place(
            "Scanner, watcher, publishers",
            REBUILT,
            "The archive is closed and opened again, so they start with the new path. "
            "This takes a few seconds.",
        ),
    ]
    if other:
        s = other != 1
        out.warnings.append(
            f"{other} shortcut{'s' if s else ''} elsewhere in the archive point{'' if s else 's'} "
            f"into '{rec.path}'. They are not part of Ongoing or Important, so dam leaves them "
            "alone: they will not find their file until you remake them."
        )
    if out.google_drive:
        out.warnings.append(SYNC_NOTE)
    return out


def _n(n: int, what: str) -> str:
    return f"{n} {what}{'s' if n != 1 else ''}"


def _config_places(app_paths: AppPaths, edits: list[FileChange]) -> list[Place]:
    config = app_paths.config_dir
    rule_edits = [e for e in edits if e.path.parent == config / "rules"]
    code_edit = next((e for e in edits if e.path == app_paths.filing_codes_path), None)
    settings_edit = next((e for e in edits if e.path.name == "settings.yaml"), None)
    out: list[Place] = []
    if rule_edits:
        n = len({(e.path, str(at[0])) for e in rule_edits for at, _, _ in e.edits})
        names = ", ".join(e.path.name for e in rule_edits)
        what = (
            f"{_n(n, 'rule')} point{'s' if n == 1 else ''} here and will follow ({names}). "
            "Comments and layout stay as they are."
        )
        out.append(Place("Rules", RENAMED, what))
    else:
        out.append(Place("Rules", UNCHANGED, "No rule has a folder in it or below it."))
    if code_edit:
        n = len({str(at[0]) for at, _, _ in code_edit.edits})
        what = (
            f"{_n(n, 'filing code')} point{'s' if n == 1 else ''} here and will follow "
            "(filing_codes.yaml)."
        )
        out.append(Place("Filing codes", RENAMED, what))
    else:
        what = "No filing code has a folder in it or below it."
        out.append(Place("Filing codes", UNCHANGED, what))
    if settings_edit:
        what = (
            f"{_n(len(settings_edit.edits), 'protected or AI-excluded folder')} follow the "
            "folder. The old file is kept next to it as settings.yaml.bak-<time>."
        )
        out.append(Place("config/settings.yaml", RENAMED, what))
    else:
        what = "No protected or AI-excluded folder lies in it."
        out.append(Place("config/settings.yaml", UNCHANGED, what))
    return out


def rename_folder(app_paths: AppPaths, drive_id: str, raw_name: str) -> Renamed:
    """Rename the folder ``drive_id`` to ``raw_name``. Call with the archive closed
    (``Host.close_and_reopen``), after ``preview`` with it open. The checks run again, a
    locked file inside is refused by the executor's guards, and the rename runs as
    ``special_folders.run_rename`` (snapshot, record, one RENAME, the stored paths follow)."""
    engine = make_engine(app_paths.db_path)
    try:
        executor, paths = closed_executor(app_paths, engine)
        _lock_guard(executor, paths, engine)
        repo = executor.repo
        rec = _folder(repo, drive_id)
        _check_folder(rec, paths)
        name = check_name(rec, raw_name, paths)
        label = paths.label_of(rec.path)
        refusals(FOLDER, paths, engine)
        if label and not paths.is_connected(label):
            raise Conflict(f"'{label}' is not connected. Connect it and try again.")
        old, new = rec.path, _new_path(rec, name)
        _edits(app_paths, old, new)
        taken = _check_taken(rec, name)

        def check(ops) -> None:
            check_disk_identity(paths, repo, [rec.drive_id], ops)
            taken(ops)

        plan = _plan(rec, name)
        return run_rename(app_paths, engine, executor, plan, FOLDER, old, new, (), check)
    finally:
        engine.dispose()


def _lock_guard(executor: Executor, paths: ArchivePaths, engine: Engine) -> None:
    """The App's lock guard for the closed archive's executor: a locked or Important file
    is not changed on disk (``dam.locks``)."""
    special = paths.settings.special_folders
    found = CollectionService(
        engine, executor.repo, PublisherRegistry(), special, quarantines=paths.quarantines
    )
    executor.locks = LockService(engine, MarkService(found).important_paths)
