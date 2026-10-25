"""Duplicate files: exact copies (same content) and the same name with different content.

The check reads the index, groups regular files by size, and hashes only the files that
share a size with another file (a file with a stored, still valid sha256 is not read again).
A hash is stored back the way the content pass stores it. Reading a file can make Google
Drive for desktop download it, so ``estimate`` says first how much would be read. Nothing
here changes the archive."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from dam.core.paths import ArchivePaths, nfc
from dam.index.repo import FileRecord, FileRepo
from dam.index.scanner import _same
from dam.locks import IMPORTANT, LOCKED, LockService
from dam.maintenance.jobs import JobContext
from dam.ops.guards import is_under

CHUNK = 1 << 20
NUMBERED = re.compile(r"^\d+\.")  # "10. Financial": a numbered top-level folder
LIST_LIMIT = 300  # groups listed per kind; the rest is counted
WHY_LOCKED = {
    IMPORTANT: "marked Important",
    LOCKED: "locked",
}


@dataclass
class DupFile:
    drive_id: str
    path: str
    name: str
    size: int
    mtime: float | None
    place: str  # numbered | inbox | other
    locked: str | None = None  # important | file: never removed by this check
    why: str | None = None  # why it cannot be removed, in words


@dataclass
class DupGroup:
    sha256: str
    size: int
    files: list[DupFile]
    keep: str  # drive id of the copy suggested to keep


@dataclass
class NameGroup:
    name: str
    files: list[DupFile]


@dataclass
class Unreadable:
    path: str
    reason: str


@dataclass
class DuplicatesResult:
    groups: list[DupGroup] = field(default_factory=list)
    groups_total: int = 0
    name_groups: list[NameGroup] = field(default_factory=list)
    name_groups_total: int = 0
    unreadable: list[Unreadable] = field(default_factory=list)
    changed: int = 0  # files that changed since the last scan and were left out
    read_files: int = 0  # hashed in this run
    reused: int = 0  # candidates whose stored hash was used
    complete: bool = True  # false: stopped before every candidate was hashed


@dataclass
class DuplicateEstimate:
    files: int  # regular files looked at
    candidates: int  # share a size with another file
    known: int  # candidates with a stored hash (not read again)
    to_read_files: int
    to_read_bytes: int


class LockIndex:
    """Which files the lock service refuses to change, answered from one read."""

    def __init__(self, locks: LockService | None) -> None:
        self.by_id: dict[str, str] = {}
        self.folders: list[tuple[str, str]] = []
        if locks is None:
            return
        for e in locks.entries():
            if e.is_dir:
                self.folders.append((nfc(e.path).casefold(), e.reason))
            else:
                self.by_id[e.drive_id] = e.reason
        stored = locks.stored()
        for drive_id in stored:
            self.by_id.setdefault(drive_id, LOCKED)

    def reason(self, drive_id: str, path_nfc: str) -> str | None:
        if drive_id in self.by_id:
            return self.by_id[drive_id]
        folded = nfc(path_nfc).casefold()
        for folder, why in self.folders:
            if folded == folder or folded.startswith(folder + "/"):
                return why
        return None


def own_folders(paths: ArchivePaths) -> list[str]:
    """The folders the app keeps (links, files marked for deletion): never looked into."""
    return [paths.quarantine, *paths.publish_roots]


def place_of(path: str, paths: ArchivePaths) -> str:
    if is_under(path, paths.inbox):
        return "inbox"
    first = path.split("/", 1)[0]
    return "numbered" if NUMBERED.match(first) else "other"


def keep_order(f: DupFile) -> tuple:
    """Sort key: the copy to keep comes first. A copy that cannot be removed (Important
    or locked) is the one to keep, then one in a numbered folder before one in the inbox
    or elsewhere, then the oldest, then by path."""
    rank = {"numbered": 0, "other": 1, "inbox": 2}[f.place]
    return (f.locked is None, rank, f.mtime if f.mtime is not None else float("inf"), f.path)


def suggest_keep(files: Iterable[DupFile]) -> str:
    return min(files, key=keep_order).drive_id


def describe(rec: FileRecord, paths: ArchivePaths, locks: LockIndex) -> DupFile:
    locked = locks.reason(rec.drive_id, rec.path_nfc)
    return DupFile(
        drive_id=rec.drive_id,
        path=rec.path,
        name=rec.name or Path(rec.path).name,
        size=rec.size or 0,
        mtime=rec.mtime,
        place=place_of(rec.path, paths),
        locked=locked,
        why=f"It is {WHY_LOCKED[locked]}, so it stays" if locked else None,
    )


def _candidates(records: list[FileRecord]) -> list[FileRecord]:
    """The files that share a size with another file (empty files are left out: all of
    them are alike and say nothing)."""
    by_size: dict[int, list[FileRecord]] = defaultdict(list)
    for rec in records:
        if rec.size:
            by_size[rec.size].append(rec)
    return [r for group in by_size.values() if len(group) > 1 for r in group]


def considered(repo: FileRepo, paths: ArchivePaths) -> list[FileRecord]:
    return repo.regular_files(own_folders(paths))


def estimate(repo: FileRepo, paths: ArchivePaths) -> DuplicateEstimate:
    """What the check would read, from the index alone (nothing is opened)."""
    records = considered(repo, paths)
    cands = _candidates(records)
    todo = [r for r in cands if not r.sha256]
    return DuplicateEstimate(
        files=len(records),
        candidates=len(cands),
        known=len(cands) - len(todo),
        to_read_files=len(todo),
        to_read_bytes=sum(r.size or 0 for r in todo),
    )


def hash_file(path: Path, stopped: Callable[[], bool]) -> str | None:
    """The sha256 of the file, read in chunks; None when stopped meanwhile."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(CHUNK):
            digest.update(chunk)
            if stopped():
                return None
    return digest.hexdigest()


def disk_matches(paths: ArchivePaths, rec: FileRecord) -> bool:
    """The file on disk is still the one the index describes (a regular file of the
    recorded size and time; only ``lstat``, nothing is read)."""
    try:
        st = os.lstat(paths.abs(rec.path))
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode) and st.st_size == rec.size and _same(st.st_mtime, rec.mtime)


def find(
    ctx: JobContext,
    repo: FileRepo,
    paths: ArchivePaths,
    locks: LockService | None,
) -> DuplicatesResult:
    """The duplicate check: hash the candidates (cancellable, with progress), then list
    the exact copies and the same-name files with different content."""
    records = considered(repo, paths)
    cands = _candidates(records)
    result = DuplicatesResult()
    hashes: dict[str, str] = {r.drive_id: r.sha256 for r in cands if r.sha256}
    result.reused = len(hashes)
    todo = [r for r in cands if not r.sha256]
    total_bytes = sum(r.size or 0 for r in todo)
    done_bytes = 0
    for i, rec in enumerate(todo):
        if ctx.stopped():
            result.complete = False
            break
        ctx.progress(i, len(todo), done_bytes, total_bytes, rec.name)
        if not disk_matches(paths, rec):
            result.changed += 1
            done_bytes += rec.size or 0
            continue
        try:
            sha = hash_file(paths.abs(rec.path), ctx.stopped)
        except OSError as e:
            result.unreadable.append(Unreadable(rec.path, e.strerror or type(e).__name__))
            done_bytes += rec.size or 0
            continue
        if sha is None:  # stopped in the middle of this file
            result.complete = False
            break
        done_bytes += rec.size or 0
        if repo.save_hash(rec.drive_id, sha, (rec.size, rec.mtime)):
            hashes[rec.drive_id] = sha
            result.read_files += 1
        else:
            result.changed += 1  # the scanner changed the row meanwhile
    else:
        ctx.progress(len(todo), len(todo), total_bytes, total_bytes, None)
    index = LockIndex(locks)
    _fill(result, records, hashes, paths, index)
    return result


def _fill(
    result: DuplicatesResult,
    records: list[FileRecord],
    hashes: dict[str, str],
    paths: ArchivePaths,
    locks: LockIndex,
) -> None:
    by_hash: dict[tuple[int, str], list[FileRecord]] = defaultdict(list)
    for rec in records:
        sha = hashes.get(rec.drive_id) or rec.sha256
        if sha and rec.size:
            by_hash[(rec.size, sha)].append(rec)
    groups = []
    for (size, sha), recs in by_hash.items():
        if len(recs) < 2:
            continue
        files = sorted(
            (describe(r, paths, locks) for r in recs), key=lambda f: (keep_order(f), f.path)
        )
        groups.append(DupGroup(sha, size, files, suggest_keep(files)))
    groups.sort(key=lambda g: (-g.size * (len(g.files) - 1), g.files[0].path))
    result.groups_total = len(groups)
    result.groups = groups[:LIST_LIMIT]

    by_name: dict[str, list[FileRecord]] = defaultdict(list)
    for rec in records:
        if rec.name and not rec.name.startswith("."):
            by_name[nfc(rec.name).casefold()].append(rec)
    names = []
    for recs in by_name.values():
        if len(recs) > 1 and _differs(recs, hashes):
            files = sorted((describe(r, paths, locks) for r in recs), key=lambda f: f.path)
            names.append(NameGroup(files[0].name, files))
    names.sort(key=lambda g: (g.name.casefold(), g.files[0].path))
    result.name_groups_total = len(names)
    result.name_groups = names[:LIST_LIMIT]


def _differs(recs: list[FileRecord], hashes: dict[str, str]) -> bool:
    """Two of the files are known to differ: another size, or two known hashes apart."""
    sha = {r.drive_id: hashes.get(r.drive_id) or r.sha256 for r in recs}
    for i, a in enumerate(recs):
        for b in recs[i + 1 :]:
            if a.size != b.size:
                return True
            if sha[a.drive_id] and sha[b.drive_id] and sha[a.drive_id] != sha[b.drive_id]:
                return True
    return False


def refresh(
    result: DuplicatesResult,
    repo: FileRepo,
    paths: ArchivePaths,
    locks: LockService | None,
) -> DuplicatesResult:
    """The result without what changed since it was found: files that moved, were marked
    for deletion or are gone drop out, a group left with one file goes, and the suggested
    copy to keep is chosen again among the rest. Reads the index only."""
    index = LockIndex(locks)

    def alive(f: DupFile) -> DupFile | None:
        rec = repo.get(f.drive_id)
        if (
            rec is None
            or rec.missing
            or rec.parked_at is not None
            or rec.is_link
            or rec.path != f.path
            or any(is_under(rec.path, area) for area in own_folders(paths))
        ):
            return None
        return describe(rec, paths, index)

    out = DuplicatesResult(
        unreadable=result.unreadable,
        changed=result.changed,
        read_files=result.read_files,
        reused=result.reused,
        complete=result.complete,
    )
    for g in result.groups:
        files = [f for f in map(alive, g.files) if f is not None]
        if len(files) > 1:
            out.groups.append(DupGroup(g.sha256, g.size, files, suggest_keep(files)))
    for ng in result.name_groups:
        files = [f for f in map(alive, ng.files) if f is not None]
        if len(files) > 1:
            out.name_groups.append(NameGroup(ng.name, files))
    out.groups_total = result.groups_total - (len(result.groups) - len(out.groups))
    out.name_groups_total = result.name_groups_total - (
        len(result.name_groups) - len(out.name_groups)
    )
    return out
