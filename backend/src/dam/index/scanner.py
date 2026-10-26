"""Read-only archive walker that keeps the SQLite index in sync with the disk."""

import math
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

# listable and is_ignored are re-exported
from dam.core.fs import is_ignored, listable, lists_nothing, readlink  # noqa: F401
from dam.core.naming import parse_doc_date
from dam.core.paths import ArchiveFolder, ArchivePaths, _fold, folder_connected, nfc
from dam.index.driveid import read_drive_id
from dam.index.locks import INDEX_LOCK
from dam.index.repo import FileRecord, FileRepo, ext_of

# One scan at a time: the watcher, reconcile timer and CLI share the DB with the executor.
SCAN_LOCK = threading.Lock()


@dataclass
class ScanReport:
    added: int = 0
    moved: int = 0
    updated: int = 0
    missing: int = 0
    rekeyed: int = 0
    # The main folder (or the subtree's folder) could not be listed: nothing was
    # marked missing or purged, so an unmounted Drive never blanks the index.
    aborted: bool = False
    # Archive rels (on-disk spelling) the walk could not list or stat: their rows are
    # neither updated nor marked missing, so unreadable files are never hidden.
    skipped: list[str] = field(default_factory=list)
    # Labels of extra folders left out because they are not connected (unplugged,
    # unmounted, or listing nothing while the index has rows): their rows are kept.
    offline: list[str] = field(default_factory=list)
    # Top-level main-folder entries (on-disk names) that fold to an archive folder's
    # label: never indexed, since their rows would land on that folder's.
    clashes: list[str] = field(default_factory=list)


@dataclass
class _Item:
    """One directory entry with everything read from disk, gathered before any DB write."""

    rel: str
    abs_path: Path
    st: os.stat_result
    is_dir: bool
    is_link: bool
    disk_id: str | None
    link_target: str | None


def _same(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(a - b) < 1e-6


def _link_target(paths: ArchivePaths, abs_path: Path) -> str | None:
    """Rel path when the target lies inside the archive, else the absolute path."""
    try:
        target = readlink(abs_path)
    except OSError:
        return None
    full = os.path.normpath(os.path.join(abs_path.parent, target))
    try:
        return paths.rel(Path(full))
    except ValueError:  # OutsideArchiveError
        return full


def _disk_spelling(paths: ArchivePaths, rel: str) -> str:
    """Spell each component of ``rel`` the way the folder listing does (NFC/NFD safe).
    The label of an extra folder is kept as the settings spell it."""
    if not rel:
        return ""
    folder = paths.folder_of(rel)
    current = folder.root
    comps = PurePosixPath(rel).parts
    parts: list[str] = []
    if folder.label:
        parts.append(folder.label)
        comps = comps[1:]
    for comp in comps:
        match = comp
        try:
            with os.scandir(current) as it:
                for e in it:
                    if nfc(e.name) == nfc(comp):
                        match = e.name
                        break
        except OSError:
            pass
        parts.append(match)
        current = current / match
    return "/".join(parts)


class _Scan:
    def __init__(self, paths: ArchivePaths, repo: FileRepo, now: float) -> None:
        self.paths = paths
        self.repo = repo
        self.now = now
        self.report = ScanReport()
        self.claimed: set[str] = set()

    def gather(
        self, rel: str, abs_path: Path, st: os.stat_result, is_dir: bool, is_link: bool
    ) -> _Item:
        link_target = _link_target(self.paths, abs_path) if is_link else None
        return _Item(rel, abs_path, st, is_dir, is_link, read_drive_id(abs_path), link_target)

    def entry(self, repo: FileRepo, item: _Item, seen: list[str]) -> None:
        rel, st, is_dir, is_link = item.rel, item.st, item.is_dir, item.is_link
        link_target = item.link_target
        name = PurePosixPath(rel).name
        disk_id = item.disk_id
        if disk_id in self.claimed:  # duplicate id (e.g. a copied xattr): treat as id-less
            disk_id = None
        if disk_id:
            self.claimed.add(disk_id)
        at_path = repo.by_path(rel)
        by_id = repo.get(disk_id) if disk_id else None
        size = None if is_dir else st.st_size
        mtime = st.st_mtime
        report = self.report

        if by_id is not None:
            current = by_id
            if current.path != rel:
                repo.park(rel, current.drive_id, descendants=True, except_under=current.path)
                repo.update_path(current.path, rel)
                report.moved += 1
        elif (
            at_path is not None
            and disk_id
            and at_path.drive_id.startswith("local:")
            and at_path.size == size
            and _same(at_path.mtime, mtime)
        ):
            repo.rekey(at_path.drive_id, disk_id)
            report.rekeyed += 1
            current = repo.get(disk_id)
            assert current is not None
        elif (
            at_path is not None
            and not disk_id
            and (
                at_path.drive_id.startswith("local:")
                or (at_path.size == size and _same(at_path.mtime, mtime))
            )
        ):
            current = at_path
            self.claimed.add(current.drive_id)  # a later twin with this xattr is a duplicate
            if current.path != rel:  # same entry, different spelling (e.g. NFD vs NFC)
                repo.update_path(current.path, rel)
                report.moved += 1
        else:
            current = None

        if current is None:
            if at_path is not None:
                repo.park(rel, disk_id or "")
            new_id = disk_id or f"local:{uuid.uuid4()}"
            repo.upsert(
                FileRecord(
                    drive_id=new_id,
                    path=rel,
                    is_dir=is_dir,
                    is_link=is_link,
                    link_target=link_target,
                    size=size,
                    mtime=mtime,
                    doc_date=None if is_dir else parse_doc_date(nfc(name)),
                    index_state="unsupported" if (is_dir or is_link) else "pending",
                    last_seen=self.now,
                )
            )
            repo.index_name(new_id)  # name search works before content indexing
            report.added += 1
            return

        changed = not is_dir and not (current.size == size and _same(current.mtime, mtime))
        if changed or current.is_link != is_link or current.link_target != link_target:
            fresh = FileRecord(
                drive_id=current.drive_id,
                path=rel,
                name=name,
                ext=ext_of(name, is_dir),
                is_dir=is_dir,
                is_link=is_link,
                link_target=link_target,
                size=size,
                mtime=mtime,
                sha256=current.sha256,
                doc_date=None if is_dir else parse_doc_date(nfc(name)),
                index_state=current.index_state,
                attempts=current.attempts,
                last_seen=self.now,
            )
            if is_dir or is_link:
                fresh.index_state = "unsupported"
            elif changed:
                fresh.index_state = "pending"
                fresh.sha256 = None
                fresh.attempts = 0
            repo.upsert(fresh)
            if changed:
                report.updated += 1
        else:
            seen.append(current.drive_id)


def scan(paths: ArchivePaths, repo: FileRepo, subtree: str = "") -> ScanReport:
    """Walk the archive (or ``subtree``) once, syncing the index; never follows symlinks.

    If the archive root (or the subtree's folder) cannot be listed, the report has
    ``aborted`` set and nothing is marked missing or purged.

    Serialised by ``SCAN_LOCK``. Disk reads (stat, xattr, readlink) happen before each
    directory's write transaction opens, so slow cloud-backed I/O holds ``INDEX_LOCK`` for
    that directory (executor ops wait) but never SQLite's write lock.
    """
    with SCAN_LOCK:
        return _scan(paths, repo, subtree)


def _connected(repo: FileRepo, folder: ArchiveFolder) -> bool:
    """``core.paths.folder_connected``, with the rows this scan's index has."""
    return folder_connected(folder, repo.has_live_under)


def _index_start(s: _Scan, start: Path) -> bool | None:
    """Index the entry at ``start`` itself. True: a folder to walk; False: a file, or
    really gone; None: it cannot be read, so nothing may be concluded."""
    try:
        st = os.lstat(start)
    except (FileNotFoundError, NotADirectoryError):
        return False  # really gone
    except OSError:  # e.g. PermissionError: unknown, so never conclude "gone"
        return None
    seen: list[str] = []
    is_link = os.path.islink(start)
    is_dir = not is_link and os.path.isdir(start)
    with INDEX_LOCK:
        item = s.gather(s.paths.rel(start), start, st, is_dir, is_link)
        with s.repo.transaction() as tx:
            s.entry(tx, item, seen)
            tx.touch_seen(seen, s.now)
    return is_dir


def _walk(s: _Scan, start: Path, clash_folds: frozenset[str] = frozenset()) -> bool:
    """Walk the folder ``start`` and everything below it. False when ``start`` itself
    cannot be listed. Entries of ``start`` whose name folds into ``clash_folds`` are
    left out and recorded as clashes."""
    paths, repo, now = s.paths, s.repo, s.now
    stack = [start]
    while stack:
        directory = stack.pop()
        dir_rel = paths.rel(directory)
        subdirs: list[Path] = []
        # Per-directory critical section: gather and apply see one consistent disk state,
        # and no executor op can run in between (see dam.index.locks).
        with INDEX_LOCK:
            try:
                entries = sorted(os.scandir(directory), key=lambda e: e.name)
            except OSError:
                if directory == start:  # the folder being scanned cannot be read
                    return False
                s.report.skipped.append(dir_rel)
                continue
            items: list[_Item] = []
            for e in entries:
                if is_ignored(e.name):
                    continue
                if directory == start and _fold(e.name) in clash_folds:
                    s.report.clashes.append(e.name)
                    continue
                rel = f"{dir_rel}/{e.name}" if dir_rel else e.name
                try:
                    st = e.stat(follow_symlinks=False)
                    is_link = e.is_symlink()
                    is_dir = not is_link and e.is_dir(follow_symlinks=False)
                except OSError:
                    s.report.skipped.append(rel)
                    continue
                items.append(s.gather(rel, Path(e.path), st, is_dir, is_link))
                if is_dir:
                    subdirs.append(Path(e.path))
            seen: list[str] = []
            with repo.transaction() as tx:
                for item in items:
                    s.entry(tx, item, seen)
                tx.touch_seen(seen, now)
        stack.extend(reversed(subdirs))
    return True


def _scan(paths: ArchivePaths, repo: FileRepo, subtree: str) -> ScanReport:
    s = _Scan(paths, repo, time.time())
    if not listable(paths.root):
        s.report.aborted = True
        return s.report
    wanted = nfc(subtree).strip("/")
    if wanted:
        return _scan_subtree(s, wanted)
    return _scan_all(s)


def _scan_all(s: _Scan) -> ScanReport:
    """Each folder on its own: one that is not connected is left out completely, so an
    unplugged disk never looks like deleted files."""
    paths, repo, report = s.paths, s.repo, s.report
    # A detached folder's rows stay under its label, so a main entry there is a clash too.
    labels = frozenset(_fold(extra.label) for extra in paths.settings.extra_folders)
    own_rows = [r for r in repo.list_dir("") if _fold(r.path) not in labels]
    if own_rows and lists_nothing(paths.root):
        # A mount that lists nothing while the index has top-level rows is not "all deleted".
        report.aborted = True
        return report
    if not _walk(s, paths.root, labels):
        report.aborted = True
        return report
    walked: list[ArchiveFolder] = []
    for folder in paths.folders[1:]:
        if _connected(repo, folder) and _index_start(s, folder.root) and _walk(s, folder.root):
            walked.append(folder)
        else:
            report.offline.append(folder.label)
            report.skipped.append(folder.label)
    if not listable(paths.root):  # the main folder went away during the walk
        report.aborted = True
        return report
    for folder in walked:
        if not listable(folder.root):  # this folder went away during the walk
            report.offline.append(folder.label)
            report.skipped.append(folder.label)
    attached = {_fold(label) for label in paths.extra_labels}
    detached = [e.label for e in paths.settings.extra_folders if _fold(e.label) not in attached]
    for label in detached:
        # Kept out of the walk, and its rows marked missing again: a scan that still ran
        # with the folder attached (the App before a reopen) may have marked them seen.
        repo.mark_missing(math.inf, subtree=label)
    report.skipped.extend(detached)
    if not report.offline:
        # A parked row may belong to a file moved onto a folder that was not walked:
        # tombstones wait for the next scan that sees every folder.
        repo.purge_parked()
    report.missing = repo.mark_missing(s.now, "", report.skipped)
    return report


def _scan_subtree(s: _Scan, wanted: str) -> ScanReport:
    """Only ``wanted`` (a file or folder); leaves tombstones for the next full scan."""
    paths, repo, report = s.paths, s.repo, s.report
    parts = PurePosixPath(wanted).parts
    attached = {_fold(label) for label in paths.extra_labels}
    if any(
        _fold(extra.label) == _fold(parts[0]) and _fold(extra.label) not in attached
        for extra in paths.settings.extra_folders
    ):  # a detached folder: on disk this would be a clashing main-folder entry
        report.aborted = True
        return report
    folder = paths.folder_of(wanted)
    if folder.label:
        if not _connected(repo, folder):
            report.offline.append(folder.label)
            report.aborted = True
            return report
        wanted = "/".join((folder.label, *parts[1:]))  # stored under the settings spelling
    start = paths.abs(_disk_spelling(paths, wanted))  # on-disk spelling for walking
    is_dir = _index_start(s, start)
    if is_dir is None or (is_dir and not _walk(s, start)):
        report.aborted = True
        return report
    if not listable(paths.root):  # the main folder went away during the walk
        report.aborted = True
        return report
    if folder.label and not listable(folder.root):
        report.offline.append(folder.label)
        report.aborted = True
        return report
    report.missing = repo.mark_missing(s.now, wanted, report.skipped)
    return report
