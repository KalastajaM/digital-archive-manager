"""Extra archive folders: the rules for adding, detaching and attaching one.

The main folder and each extra folder form one archive (``core.paths.ArchivePaths``).
Everything here changes only the settings file and the index; no file in any folder is
touched. A dry run computes the same ``FolderChange`` and writes nothing."""

import math
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from dam import settings_write
from dam.config import AppPaths, ExtraFolder, Settings, load_settings
from dam.core.foldernames import FolderNameError, check_folder_name
from dam.core.fs import listable
from dam.core.paths import ArchiveFolder, ArchivePaths, fold_name, folder_connected
from dam.db.engine import make_engine
from dam.index.repo import FileRepo
from dam.profiles import ProfileStore, related, root_conflict
from dam.services.errors import InvalidRequest, NotFound

MAIN_FOLDER = "the main folder"


@dataclass
class FolderChange:
    """What adding, detaching or attaching a folder does (or, in a dry run, would do).

    ``files`` is the number of index rows a detach marks missing or a forget removes;
    ``reopen`` is true when the folders changed and the caller must still reopen the
    app's scanner and watcher; ``restart_needed`` is true when a reopen made here (a
    detach given ``reopen``) was not possible."""

    label: str
    path: str
    files: int
    reopen: bool
    restart_needed: bool = False


def _taken(label: str, settings: Settings) -> bool:
    """Detached entries count: attaching them again must stay possible."""
    return any(fold_name(e.label) == fold_name(label) for e in settings.extra_folders)


def check_label(label: str, paths: ArchivePaths, settings: Settings) -> str | None:
    """Why ``label`` cannot name a new extra folder, or None."""
    if not isinstance(label, str) or not label.strip():
        return "Give the folder a label."
    try:
        clean = check_folder_name(label)
    except FolderNameError as e:
        return str(e)
    if _taken(clean, settings):
        return f"There is already an archive folder labelled '{clean}'. Choose another label."
    return _main_clash(clean, paths)


def _main_clash(label: str, paths: ArchivePaths) -> str | None:
    """Why ``label`` is the name of a top-level entry of the main folder, or None."""
    try:
        with os.scandir(paths.root) as entries:
            names = [entry.name for entry in entries]
    except OSError:
        names = []
    if any(fold_name(name) == fold_name(label) for name in names):
        return (
            f"'{label}' is already the name of a folder in the main folder. Choose another label."
        )
    return None


def _overlap(how: str | None, label: str) -> str | None:
    if how == "same":
        return f"That folder is already part of this archive ('{label}')."
    if how == "inside":
        return f"That folder is inside '{label}', which is already part of this archive."
    if how == "around":
        return f"That folder contains '{label}', which is already part of this archive."
    return None


def check_folder(
    candidate: Path, paths: ArchivePaths, store: ProfileStore | None, current_id: str | None
) -> str | None:
    """Why ``candidate`` cannot be an extra folder of this archive, or None: it may not
    overlap a folder of this archive, another archive's folders or any data folder, and
    it must be readable now."""
    for folder in paths.folders:
        message = _overlap(related(candidate, folder.root), folder.label or MAIN_FOLDER)
        if message:
            return message
    if store is not None:
        message = root_conflict(candidate, store.load(), store.base, current_id)
        if message:
            return message
    if not listable(candidate):
        return "That folder cannot be read right now. Check that it exists and is connected."
    return None


def _detached_as(candidate: Path, settings: Settings) -> str | None:
    """Why ``candidate`` is not a new folder: it is a detached one, under its own label."""
    for e in settings.extra_folders:
        if not e.attached and related(candidate, Path(e.path).expanduser()) == "same":
            return f"That folder was detached as '{e.label}'. Attach it again instead."
    return None


@dataclass
class FolderStatus:
    """One folder of the archive as Settings lists it; ``label`` None is the main folder."""

    label: str | None
    path: str
    attached: bool
    connected: bool
    files: int


def list_folders(app_paths: AppPaths, repo: FileRepo) -> list[FolderStatus]:
    """The main folder, then every extra folder (detached ones too), as the settings
    file has them now. ``files`` counts index rows not flagged missing; the main folder's
    are the rows under no attached label."""
    settings, _ = _context(app_paths)
    extras = []
    for e in settings.extra_folders:
        files = repo.count_subtree(e.label, live_only=True)
        root = Path(e.path).expanduser()
        connected = folder_connected(ArchiveFolder(e.label, root), repo.has_live_under)
        extras.append(FolderStatus(e.label, str(e.path), e.attached, connected, files))
    in_extras = sum(f.files for f in extras if f.attached)
    main = FolderStatus(None, str(settings.archive_root), True, True, repo.count_live() - in_extras)
    return [main, *extras]


def _context(app_paths: AppPaths) -> tuple[Settings, ArchivePaths]:
    settings = load_settings(app_paths)
    if settings.archive_root is None:
        raise InvalidRequest("Set up the main archive folder first.")
    return settings, ArchivePaths(settings.archive_root, settings)


def _entry(settings: Settings, label: str) -> ExtraFolder:
    for extra in settings.extra_folders:
        if fold_name(extra.label) == fold_name(label):
            return extra
    raise NotFound(f"There is no archive folder labelled '{label}'.")


def _write(app_paths: AppPaths, entries: list[ExtraFolder]) -> None:
    expected = [(e.label, e.path, e.attached) for e in entries]

    def verify(settings: Settings) -> bool:
        return [(e.label, e.path, e.attached) for e in settings.extra_folders] == expected

    value = [{"label": e.label, "path": str(e.path), "attached": e.attached} for e in entries]
    try:
        settings_write.write_keys(app_paths, {"extra_folders": value}, verify)
    except OSError as e:
        raise InvalidRequest(f"Could not save the settings: {e}") from None


def add_folder(
    app_paths: AppPaths,
    label: str,
    path: Path,
    dry_run: bool,
    *,
    store: ProfileStore | None,
    current_id: str | None,
) -> FolderChange:
    """Add ``path`` to the archive as an extra folder shown under ``label``."""
    settings, paths = _context(app_paths)
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        raise InvalidRequest("Give the full path of the folder.")
    message = check_label(label, paths, settings)
    if message is None:
        message = check_folder(candidate, paths, store, current_id)
    if message is None:
        message = _detached_as(candidate, settings)
    if message is None and related(candidate, app_paths.data_dir):
        message = "That folder overlaps the app's own data folder. Choose another."
    if message:
        raise InvalidRequest(message)
    clean = check_folder_name(label)
    if not dry_run:
        _write(app_paths, [*settings.extra_folders, ExtraFolder(label=clean, path=candidate)])
    return FolderChange(clean, str(candidate), 0, not dry_run)


def detach_folder(
    app_paths: AppPaths,
    repo: FileRepo,
    label: str,
    forget: bool,
    dry_run: bool,
    reopen: Callable[[], bool] | None = None,
) -> FolderChange:
    """Take the folder out of the archive. Its entry stays in the settings, detached, and
    its index rows are marked missing (as when it is offline). With ``forget`` the entry
    is removed (nothing is left to attach again, so its label is free) and so are its rows
    with everything the owner gave those files. Database and settings only: no file on
    disk is touched.

    The order is settings, then ``reopen`` (the running app opened afresh; True when that
    worked), then the index. After the reopen the old app's scans have stopped, so none
    puts forgotten rows back. When the reopen is not possible the index changes anyway;
    a row a late scan still marks seen is marked missing again by the next full scan (a
    detached label's rows always are, and a forgotten label is no folder any more).
    Without ``reopen`` the caller reopens afterwards (``FolderChange.reopen``)."""
    settings, _ = _context(app_paths)
    target = _entry(settings, label)
    if dry_run:
        files = repo.count_subtree(target.label, live_only=not forget)
        return FolderChange(target.label, str(target.path), files, False)
    if forget:
        _write(app_paths, [e for e in settings.extra_folders if e is not target])
    elif target.attached:
        _write(
            app_paths,
            [
                e.model_copy(update={"attached": False}) if e is target else e
                for e in settings.extra_folders
            ],
        )
    changed = forget or target.attached
    # chosen before the reopen: the new app's first scan may index a main-folder entry
    # of the same name (the label is free now) at these paths, and those rows stay
    forgotten = repo.subtree_ids(target.label) if forget else []
    restart_needed = False
    if changed and reopen is not None:
        restart_needed = not reopen()
    with _index_repo(app_paths, repo, fresh=changed and reopen is not None) as index:
        if forget:
            files = index.forget_rows(forgotten)
        else:
            files = index.mark_missing(math.inf, subtree=target.label)
    return FolderChange(
        target.label, str(target.path), files, changed and reopen is None, restart_needed
    )


@contextmanager
def _index_repo(app_paths: AppPaths, repo: FileRepo, fresh: bool) -> Iterator[FileRepo]:
    """``repo``, or after a reopen (which closed the app ``repo`` belongs to) one on its
    own connection to the same index, closed again at the end."""
    if not fresh:
        yield repo
        return
    engine = make_engine(app_paths.db_path)
    try:
        yield FileRepo(engine, inbox=repo.inbox)
    finally:
        engine.dispose()


def attach_folder(
    app_paths: AppPaths,
    label: str,
    dry_run: bool,
    *,
    store: ProfileStore | None,
    current_id: str | None,
) -> FolderChange:
    """Attach a detached folder again; the same overlap checks as for a new one."""
    settings, paths = _context(app_paths)
    target = _entry(settings, label)
    if target.attached:
        return FolderChange(target.label, str(target.path), 0, False)
    message = _main_clash(target.label, paths) or check_folder(
        target.path, paths, store, current_id
    )
    if message is None and related(target.path, app_paths.data_dir):
        message = "That folder overlaps the app's own data folder. Choose another."
    if message:
        raise InvalidRequest(message)
    if not dry_run:
        _write(
            app_paths,
            [
                e.model_copy(update={"attached": True}) if e is target else e
                for e in settings.extra_folders
            ],
        )
    return FolderChange(target.label, str(target.path), 0, not dry_run)


@dataclass(frozen=True)
class RelabelChange:
    """What changing a folder's label changes (or, in a dry run, would change)."""

    label: str
    new_label: str
    counts: dict[str, int]
    files: list[tuple[str, list[int]]]  # file name, the lines that change
    warnings: list[str]


def _relabel_problem(new: str, target: ExtraFolder, paths: ArchivePaths, settings: Settings):
    """Why ``new`` cannot be ``target``'s label, or None: the rules for a new label,
    where the folder's own label does not count as taken (a change of case is fine)."""
    if not isinstance(new, str) or not new.strip():
        return "Give the folder a label."
    try:
        clean = check_folder_name(new)
    except FolderNameError as e:
        return str(e)
    if clean == target.label:
        return "That is already the folder's label."
    others = [e for e in settings.extra_folders if e is not target]
    if any(fold_name(e.label) == fold_name(clean) for e in others):
        return f"There is already an archive folder labelled '{clean}'. Choose another label."
    if fold_name(clean) == fold_name(target.label):
        return None
    return _main_clash(clean, paths)


def relabel_folder(
    app_paths: AppPaths, label: str, new_label: str, dry_run: bool, engine=None
) -> RelabelChange:
    """Change the label of the extra folder ``label`` to ``new_label`` (``dam.relabel``):
    every stored path under it is rewritten, nothing on disk changes. Run with the
    archive closed (``Host.close_and_reopen``); ``engine`` None opens the index for
    the change. 400 for a label that cannot be used, a rule or setting that cannot be
    edited safely, or an interrupted operation."""
    from dam import relabel
    from dam.core.yamledit import YamlEditError
    from dam.ops.model import OpFailed

    settings, paths = _context(app_paths)
    target = _entry(settings, label)
    message = _relabel_problem(new_label, target, paths, settings)
    if message is not None:
        raise InvalidRequest(message)
    new = check_folder_name(new_label)
    own = engine is None
    engine = make_engine(app_paths.db_path) if own else engine
    try:
        try:
            plan = relabel.plan(app_paths, engine, target.label, new)
        except (YamlEditError, OpFailed) as e:
            raise InvalidRequest(str(e)) from None
        if not dry_run:
            try:
                relabel.apply(app_paths, engine, plan)
            except OSError as e:
                raise InvalidRequest(f"Could not change the label: {e}") from None
    finally:
        if own:
            engine.dispose()
    files = [(f.path.name, f.lines) for f in plan.files]
    return RelabelChange(target.label, new, plan.counts, files, plan.warnings)
