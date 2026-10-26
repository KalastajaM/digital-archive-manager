"""Extra archive folders: the rules for adding, detaching and attaching one.

The main folder and each extra folder form one archive (``core.paths.ArchivePaths``).
Everything here changes only the settings file and the index; no file in any folder is
touched. A dry run computes the same ``FolderChange`` and writes nothing."""

import math
import os
from dataclasses import dataclass
from pathlib import Path

from dam import settings_write
from dam.config import AppPaths, ExtraFolder, Settings, load_settings
from dam.core.foldernames import FolderNameError, check_folder_name
from dam.core.fs import listable
from dam.core.paths import ArchivePaths, _fold
from dam.index.repo import FileRepo
from dam.profiles import ProfileStore, related, root_conflict
from dam.services.errors import InvalidRequest, NotFound

MAIN_FOLDER = "the main folder"


@dataclass
class FolderChange:
    """What adding, detaching or attaching a folder does (or, in a dry run, would do).

    ``files`` is the number of index rows a detach marks missing or a forget removes;
    ``reopen`` is true when the attached set changed, so the app must reopen its
    scanner and watcher."""

    label: str
    path: str
    files: int
    reopen: bool


def _taken(label: str, settings: Settings) -> bool:
    """Detached entries count: attaching them again must stay possible."""
    return any(_fold(e.label) == _fold(label) for e in settings.extra_folders)


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
    if any(_fold(name) == _fold(label) for name in names):
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
        connected = listable(Path(e.path).expanduser())
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
        if _fold(extra.label) == _fold(label):
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
    if message is None and related(candidate, app_paths.data_dir):
        message = "That folder overlaps the app's own data folder. Choose another."
    if message:
        raise InvalidRequest(message)
    clean = check_folder_name(label)
    if not dry_run:
        _write(app_paths, [*settings.extra_folders, ExtraFolder(label=clean, path=candidate)])
    return FolderChange(clean, str(candidate), 0, not dry_run)


def detach_folder(
    app_paths: AppPaths, repo: FileRepo, label: str, forget: bool, dry_run: bool
) -> FolderChange:
    """Take the folder out of the archive; its entry stays in the settings, detached. Its
    index rows are marked missing (as when it is offline), or with ``forget`` removed.
    Database rows only: no file on disk is touched."""
    settings, _ = _context(app_paths)
    target = _entry(settings, label)
    was_attached = target.attached
    if dry_run:
        files = repo.count_subtree(target.label, live_only=not forget)
    else:
        if was_attached:
            _write(
                app_paths,
                [
                    e.model_copy(update={"attached": False}) if e is target else e
                    for e in settings.extra_folders
                ],
            )
        if forget:
            files = repo.forget_subtree(target.label)
        else:
            files = repo.mark_missing(math.inf, subtree=target.label)
    return FolderChange(target.label, str(target.path), files, not dry_run and was_attached)


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
