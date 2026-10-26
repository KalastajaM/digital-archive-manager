"""The small maintenance lists: empty folders, broken links, collection and tray entries
that point at missing files, names that do not follow the archive's convention, what
has waited in ``##. To Delete``, main-folder entries named like an archive folder, and
unfinished copies a move across disks left.
Each is a read of the index (empty folders, broken links and name clashes also look at
the disk with ``lstat``/listing, nothing is opened or downloaded) and changes nothing;
the owner acts on a list through the usual previewed batches."""

from __future__ import annotations

import json
import os
import re
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from sqlalchemy import Engine, func, or_, select

from dam.core.fs import readlink, resolve
from dam.core.naming import matches_convention, parse_doc_date
from dam.core.paths import ArchivePaths, OutsideArchiveError, _fold, nfc
from dam.db.tables import (
    collection_members,
    collections,
    file_fields,
    files,
    item_files,
    items,
    operations,
)
from dam.index.repo import FileRecord, FileRepo
from dam.maintenance.duplicates import NUMBERED, own_folders
from dam.maintenance.jobs import JobContext
from dam.ops.guards import is_under, touches_protected
from dam.ops.primitives import TEMP_COPY_PREFIX

LIST_LIMIT = 500  # rows listed per check; the total is always counted
FINDER_CACHE = {".ds_store"}  # what an "empty" folder may still hold
DEFAULT_DAYS = 30
MAX_DAYS = 36500


@dataclass
class EmptyFolder:
    drive_id: str
    path: str


@dataclass
class EmptyFolders:
    items: list[EmptyFolder] = field(default_factory=list)
    total: int = 0


@dataclass
class BrokenLink:
    drive_id: str
    path: str
    target: str | None
    inside: str | None  # the app's folder it is in (##. Ongoing / ##. Important), else None
    # broken, or its target is in an extra folder that is not connected now / detached
    reason: Literal["broken", "folder_not_connected", "folder_detached"] = "broken"


@dataclass
class BrokenLinks:
    items: list[BrokenLink] = field(default_factory=list)
    total: int = 0


@dataclass
class BadReference:
    kind: str  # collection | tray
    owner_id: str  # collection id, or tray id
    owner_name: str
    item_id: int | None  # the tray item, for kind tray
    drive_id: str
    path: str | None  # where the file is, or for a missing one was last seen (None: unknown)
    reason: str  # "missing" | "in To Delete"


@dataclass
class BadReferences:
    items: list[BadReference] = field(default_factory=list)
    total: int = 0


@dataclass
class BadName:
    drive_id: str
    path: str
    name: str
    folder: str
    suggestion: str | None


@dataclass
class BadNames:
    items: list[BadName] = field(default_factory=list)
    total: int = 0


@dataclass
class WaitingFile:
    drive_id: str
    path: str
    size: int
    since: float  # epoch seconds it was put there (or the nearest the app can tell)
    days: int
    approximate: bool  # no record of the move: the file's own change time
    folder: str | None = None  # the extra folder's label whose To Delete it is in


@dataclass
class LabelClashes:
    items: list[str] = field(default_factory=list)  # the archive folders' labels
    total: int = 0


@dataclass
class UnfinishedCopy:
    drive_id: str
    path: str
    size: int


@dataclass
class UnfinishedCopies:
    items: list[UnfinishedCopy] = field(default_factory=list)
    total: int = 0
    total_size: int = 0


@dataclass
class Waiting:
    days: int  # the limit asked for
    items: list[WaitingFile] = field(default_factory=list)
    total: int = 0  # files waiting longer than ``days``
    total_size: int = 0
    in_to_delete: int = 0  # all files in To Delete
    in_to_delete_size: int = 0


def _live(*extra):
    return (files.c.missing.is_not(True), files.c.parked_at.is_(None), *extra)


# --- empty folders -----------------------------------------------------------------------


def _default_folder(rel: str, paths: ArchivePaths, repo: FileRepo) -> bool:
    """One of the folders the archive is set up with, which may well be empty: a special
    folder (``##. Organize``, ``##. To Delete``, ...) or a filing code's inbox folder
    (``##. Organize/To pay``)."""
    folded = nfc(rel).casefold()
    special = paths.settings.special_folders
    if folded in {nfc(f).casefold() for f in special.model_dump().values()}:
        return True
    above, _, name = folded.rpartition("/")
    return above == nfc(paths.inbox).casefold() and name in repo.code_folders


def empty_folders(
    ctx: JobContext, repo: FileRepo, paths: ArchivePaths, engine: Engine
) -> EmptyFolders:
    """Folders (below the top level, outside the app's own folders and protected paths,
    and not one of the archive's default folders) with nothing in them but a Finder
    cache file. The index names the candidates; each is listed on disk before it is
    shown."""
    with engine.connect() as conn:
        rows = conn.execute(select(files.c.path, files.c.is_dir).where(*_live())).all()
    parents = {PurePosixPath(r.path).parent.as_posix() for r in rows}
    folders = sorted(
        (r.path for r in rows if r.is_dir and r.path not in parents), key=lambda p: p.casefold()
    )
    out = EmptyFolders()
    for i, rel in enumerate(folders):
        if ctx.stopped():
            break
        ctx.progress(i, len(folders), current=rel)
        if (
            len(PurePosixPath(rel).parts) < 2
            or any(is_under(rel, area) for area in own_folders(paths))
            or touches_protected(rel, paths)
            or _default_folder(rel, paths, repo)
        ):
            continue
        try:
            names = os.listdir(paths.abs(rel))
        except OSError:
            continue
        if any(n.casefold() not in FINDER_CACHE for n in names):
            continue
        rec = repo.by_path(rel)
        if rec is None:
            continue
        out.total += 1
        if len(out.items) < LIST_LIMIT:
            out.items.append(EmptyFolder(rec.drive_id, rec.path))
    ctx.progress(len(folders), len(folders))
    return out


# --- broken links -------------------------------------------------------------------------


def broken_links(
    ctx: JobContext, repo: FileRepo, paths: ArchivePaths, engine: Engine
) -> BrokenLinks:
    """Links (symbolic links in the index) whose target is gone, with why: an extra
    folder that is not connected now or is detached is not a missing file."""
    detached = [resolve(e.path) for e in paths.settings.extra_folders if not e.attached]
    connected: dict[str, bool] = {}  # label -> connected, each root listed once
    with engine.connect() as conn:
        rows = conn.execute(
            select(files).where(*_live(files.c.is_link.is_(True))).order_by(files.c.path)
        ).all()
    out = BrokenLinks()
    for i, row in enumerate(rows):
        if ctx.stopped():
            break
        ctx.progress(i, len(rows), current=row.path)
        rec = repo.record_from_row(row)
        if paths.is_quarantined(rec.path):
            continue
        try:
            os.stat(paths.abs(rec.path))  # follows the link; a placeholder is not opened
            continue
        except OSError:
            pass  # gone, a loop or unreadable: the link leads nowhere
        if not os.path.lexists(paths.abs(rec.path)):
            continue  # the link itself is gone: the next scan notices
        out.total += 1
        if len(out.items) < LIST_LIMIT:
            out.items.append(
                BrokenLink(
                    rec.drive_id,
                    rec.path,
                    rec.link_target,
                    paths.in_publish_root(rec.path),
                    _why_broken(paths, rec.path, detached, connected),
                )
            )
    ctx.progress(len(rows), len(rows))
    return out


def link_into_offline(paths: ArchivePaths, rel: str, connected: dict[str, bool]) -> str | None:
    """The label of the extra folder the link ``rel`` points into when that folder is not
    connected now, else None. ``connected`` caches each label's answer."""
    target = _link_full(paths, rel)
    if target is None:
        return None
    try:
        label = paths.label_of(paths.rel(target))
    except (OutsideArchiveError, OSError):
        return None
    if not label:
        return None
    if label not in connected:
        connected[label] = paths.is_connected(label)
    return None if connected[label] else label


def _link_full(paths: ArchivePaths, rel: str) -> Path | None:
    link = paths.abs(rel)
    try:
        raw = readlink(link)
    except OSError:
        return None
    return Path(os.path.normpath(os.path.join(link.parent, raw)))


def _why_broken(
    paths: ArchivePaths, rel: str, detached: list[Path], connected: dict[str, bool]
) -> Literal["broken", "folder_not_connected", "folder_detached"]:
    if link_into_offline(paths, rel, connected) is not None:
        return "folder_not_connected"
    target = _link_full(paths, rel)
    if target is not None:
        full = resolve(target)
        for root in detached:
            if full == root or root in full.parents:
                return "folder_detached"
    return "broken"


# --- main-folder entries named like an archive folder -----------------------------------------


def label_clashes(
    ctx: JobContext, repo: FileRepo, paths: ArchivePaths, engine: Engine
) -> LabelClashes:
    """The archive folders (attached or detached) whose label a top-level entry of the
    main folder also has. That entry is not indexed (the archive folder wins); the owner
    renames one of the two. Lists the main folder's top level only."""
    try:
        names = {_fold(n) for n in os.listdir(paths.root)}
    except OSError:
        names = set()
    out = LabelClashes()
    extras = paths.settings.extra_folders
    for i, extra in enumerate(extras):
        ctx.progress(i, len(extras), current=extra.label)
        if _fold(extra.label) in names:
            out.total += 1
            out.items.append(extra.label)
    ctx.progress(len(extras), len(extras))
    return out


# --- unfinished copies of a move across disks ------------------------------------------------


def unfinished_copies(
    ctx: JobContext, repo: FileRepo, paths: ArchivePaths, engine: Engine
) -> UnfinishedCopies:
    """Files named like the temporary copy a move across disks writes before it is
    verified and renamed (``TEMP_COPY_PREFIX``): what a failed, stopped or interrupted
    move left. The original was never moved for them, so the owner can remove them; dam
    never deletes. The index names them (a scan picks a leftover up), and each is looked
    at on disk (``lstat``) before it is listed."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(files.c.drive_id, files.c.path)
            .where(*_live(files.c.is_dir.is_not(True), files.c.is_link.is_not(True)))
            .where(files.c.name.startswith(TEMP_COPY_PREFIX, autoescape=True))
            .order_by(files.c.path)
        ).all()
    out = UnfinishedCopies()
    for i, row in enumerate(rows):
        if ctx.stopped():
            break
        ctx.progress(i, len(rows), current=row.path)
        try:
            st = os.lstat(paths.abs(row.path))
        except (OSError, OutsideArchiveError):
            continue
        if not stat.S_ISREG(st.st_mode):
            continue
        out.total += 1
        out.total_size += st.st_size
        if len(out.items) < LIST_LIMIT:
            out.items.append(UnfinishedCopy(row.drive_id, row.path, st.st_size))
    ctx.progress(len(rows), len(rows))
    return out


# --- collection members and tray items without a file ---------------------------------------


def bad_references(
    ctx: JobContext,
    paths: ArchivePaths,
    engine: Engine,
    tray_name: Callable[[str], str],
) -> BadReferences:
    """Collection members and files of open tray items whose file is gone from the index
    or lies in ``##. To Delete``. A missing file is shown at the path it was last seen:
    its index row's, else the last one the journal has for it."""

    def problem(row) -> tuple[str | None, str | None]:
        if row.f_id is None or row.missing or row.parked_at is not None:
            return row.f_path, "missing"
        if paths.is_quarantined(row.f_path_nfc):
            return row.f_path, "in To Delete"
        return None, None

    def last_seen(drive_id: str) -> str | None:
        with engine.connect() as conn:
            op = conn.execute(
                select(operations.c.src, operations.c.dst)
                .where(operations.c.drive_id == drive_id, operations.c.state == "done")
                .order_by(operations.c.id.desc())
                .limit(1)
            ).first()
        return None if op is None else (op.dst or op.src)

    out = BadReferences()
    with engine.connect() as conn:
        members = conn.execute(
            select(
                collection_members.c.drive_id,
                collections.c.id.label("owner_id"),
                collections.c.name,
                collections.c.kind,
                files.c.drive_id.label("f_id"),
                files.c.path.label("f_path"),
                files.c.path_nfc.label("f_path_nfc"),
                files.c.missing,
                files.c.parked_at,
            )
            .select_from(
                collection_members.join(
                    collections, collections.c.id == collection_members.c.collection_id
                ).outerjoin(files, files.c.drive_id == collection_members.c.drive_id)
            )
            .where(collections.c.state == "open")
            .order_by(collections.c.name, collection_members.c.drive_id)
        ).all()
        tray_files = conn.execute(
            select(
                item_files.c.drive_id,
                items.c.id.label("item_id"),
                items.c.tray_id,
                items.c.title,
                files.c.drive_id.label("f_id"),
                files.c.path.label("f_path"),
                files.c.path_nfc.label("f_path_nfc"),
                files.c.missing,
                files.c.parked_at,
            )
            .select_from(
                item_files.join(items, items.c.id == item_files.c.item_id).outerjoin(
                    files, files.c.drive_id == item_files.c.drive_id
                )
            )
            .where(items.c.state == "open")
            .order_by(items.c.tray_id, items.c.id)
        ).all()
    total = len(members) + len(tray_files)
    for i, row in enumerate(members):
        if i % 500 == 0 and ctx.stopped():
            return out
        path, why = problem(row)
        if why is None:
            continue
        out.total += 1
        if len(out.items) < LIST_LIMIT:
            name = {"starred": "Starred", "important": "Important"}.get(row.kind, row.name)
            path = path if path is not None else last_seen(row.drive_id)
            out.items.append(
                BadReference("collection", str(row.owner_id), name, None, row.drive_id, path, why)
            )
    for i, row in enumerate(tray_files):
        if i % 500 == 0 and ctx.stopped():
            return out
        path, why = problem(row)
        if why is None:
            continue
        out.total += 1
        if len(out.items) < LIST_LIMIT:
            path = path if path is not None else last_seen(row.drive_id)
            out.items.append(
                BadReference(
                    "tray",
                    row.tray_id,
                    f"{tray_name(row.tray_id)}: {row.title}",
                    row.item_id,
                    row.drive_id,
                    path,
                    why,
                )
            )
    ctx.progress(total, total)
    return out


# --- names that do not follow YYYYMMDD_ ------------------------------------------------------

_LEADING_DATE = re.compile(r"^(\d{8})[_\- .]+")
SYSTEM_NAMES = {"thumbs.db", "desktop.ini"}


def suggest_name(name: str, doc_date: date | None, mtime: float | None) -> str | None:
    """``YYYYMMDD_<name>``: the date the name starts with (``20230105-bill.pdf`` becomes
    ``20230105_bill.pdf``), else the document date, else the file's modified date."""
    rest = name
    when = parse_doc_date(name)
    if when is not None:
        m = _LEADING_DATE.match(name)
        if m:
            rest = name[m.end() :]
    else:
        when = doc_date
    if when is None and mtime is not None:
        try:
            when = datetime.fromtimestamp(mtime).date()
        except (OSError, OverflowError, ValueError):
            when = None
    if when is None or not rest:
        return None
    suggestion = f"{when:%Y%m%d}_{rest}"
    return suggestion if matches_convention(suggestion) and suggestion != name else None


def _saved_dates(engine: Engine) -> dict[str, date]:
    """The document date in a file's saved (owner-edited) scan fields, by drive id."""
    out: dict[str, date] = {}
    with engine.connect() as conn:
        rows = conn.execute(select(file_fields.c.drive_id, file_fields.c.fields)).all()
    for row in rows:
        try:
            for f in json.loads(row.fields):
                if f.get("kind") == "doc_date":
                    out[row.drive_id] = date.fromisoformat(f["value"])
                    break
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
    return out


def bad_names(ctx: JobContext, repo: FileRepo, paths: ArchivePaths, engine: Engine) -> BadNames:
    """Files in the numbered folders whose name does not start with ``YYYYMMDD_``."""
    records = [
        r
        for r in repo.regular_files(own_folders(paths))
        if NUMBERED.match(r.path.split("/", 1)[0])
        and "/" in r.path
        and not r.name.startswith(".")
        and r.name.casefold() not in SYSTEM_NAMES
        and not matches_convention(nfc(r.name))
    ]
    dates = _saved_dates(engine)
    out = BadNames()
    for i, rec in enumerate(records):
        if i % 500 == 0 and ctx.stopped():
            break
        ctx.progress(i, len(records))
        out.total += 1
        if len(out.items) < LIST_LIMIT:
            folder = PurePosixPath(rec.path).parent.as_posix()
            when = dates.get(rec.drive_id) or rec.doc_date
            out.items.append(
                BadName(
                    rec.drive_id,
                    rec.path,
                    rec.name,
                    folder,
                    suggest_name(rec.name, when, rec.mtime),
                )
            )
    ctx.progress(len(records), len(records))
    return out


# --- what has waited in To Delete ---------------------------------------------------------------


def _inside(column, folders: tuple[str, ...]):
    """``column`` lies inside one of ``folders`` (a LIKE per folder)."""
    return or_(
        *(
            column.like(f.replace("%", r"\%").replace("_", r"\_") + "/%", escape="\\")
            for f in folders
        )
    )


def _moved_in(engine: Engine, quarantines: tuple[str, ...]) -> dict[str, float]:
    """When the app put each path into a quarantine folder: the newest finished MOVE or
    QUARANTINE journal row that ended there (a folder's row covers what is inside it)."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(operations.c.dst, func.max(operations.c.finished))
            .where(
                operations.c.kind.in_(["quarantine", "move"]),
                operations.c.state.in_(["done", "unverified"]),
                operations.c.undo_of.is_(None),
                operations.c.finished.is_not(None),
                _inside(operations.c.dst, quarantines),
            )
            .group_by(operations.c.dst)
        ).all()
    return {nfc(dst): float(t) for dst, t in rows if dst}


def waiting_in_to_delete(
    ctx: JobContext,
    repo: FileRepo,
    paths: ArchivePaths,
    engine: Engine,
    days: int,
    now: float | None = None,
) -> Waiting:
    """Files that have been in ``##. To Delete`` for more than ``days`` days, oldest
    first, with their total size. How long is from the app's journal; for a file put there
    some other way, from the time the file last changed place on disk (approximate)."""
    now = time.time() if now is None else now
    quarantines = tuple(nfc(q) for q in paths.quarantines)  # every folder's To Delete
    moved = _moved_in(engine, quarantines)
    with engine.connect() as conn:
        rows = conn.execute(
            select(files)
            .where(*_live(files.c.is_dir.is_not(True)))
            .where(_inside(files.c.path_nfc, quarantines))
            .order_by(files.c.path)
        ).all()
    out = Waiting(days=days)
    found: list[WaitingFile] = []
    for i, row in enumerate(rows):
        if i % 200 == 0 and ctx.stopped():
            break
        ctx.progress(i, len(rows))
        rec: FileRecord = repo.record_from_row(row)
        size = rec.size or 0
        out.in_to_delete += 1
        out.in_to_delete_size += size
        since, approx = _since(rec, moved, paths)
        if since is None:
            continue
        age = int((now - since) // 86400)
        if now - since > days * 86400:
            out.total += 1
            out.total_size += size
            folder = paths.label_of(rec.path) or None
            found.append(WaitingFile(rec.drive_id, rec.path, size, since, age, approx, folder))
    found.sort(key=lambda f: f.since)
    out.items = found[:LIST_LIMIT]
    ctx.progress(len(rows), len(rows))
    return out


def _since(
    rec: FileRecord, moved: dict[str, float], paths: ArchivePaths
) -> tuple[float | None, bool]:
    path = PurePosixPath(rec.path_nfc)
    times = [moved[p] for p in [path.as_posix(), *map(str, path.parents)] if p in moved]
    if times:
        return max(times), False
    try:
        st = os.lstat(paths.abs(rec.path))
    except OSError:
        return None, True
    return st.st_ctime, True
