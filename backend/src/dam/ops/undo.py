"""Undo of a journaled batch and recovery of interrupted operations.

Undo builds an ordinary ``Plan`` (``origin="undo"``) that goes through preview, guards
and the journaled executor loop. Recovery only reads the disk and settles journal rows.
"""

from __future__ import annotations

import dataclasses
import json
import os
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import Connection, select, update
from sqlalchemy.exc import SQLAlchemyError

from dam.core.fs import readlink
from dam.core.paths import OutsideArchiveError
from dam.db.engine import write_tx
from dam.db.tables import made_folders, ongoing_entries, operations
from dam.index.driveid import read_drive_id
from dam.index.locks import INDEX_LOCK
from dam.ops import identity, primitives
from dam.ops.guards import check_connected, fold_parts, is_under, join, parent, rebase
from dam.ops.model import (
    UNDO_ORIGIN,
    BatchResult,
    GuardError,
    Op,
    OpFailed,
    OpKind,
    Plan,
    ResolvedOp,
)
from dam.ops.planner import Planner
from dam.ops.primitives import DS_STORE, TEMP_COPY_PREFIX, finder_cache_problem

if TYPE_CHECKING:
    from dam.ops.executor import Executor

RELOCATE = {OpKind.RENAME, OpKind.MOVE, OpKind.QUARANTINE}
ACTED = ("done", "unverified")  # the act happened (unverified: verification failed)
INTERRUPTED = "interrupted before execution"
# Automatic Ongoing syncs follow the collections in the DB: undoing one would only be
# re-applied (or orphan its entries), so the collection change is undone instead.
SYNC_ORIGIN = "workflow"
SYNC_UNDO_REFUSED = "This was an automatic Ongoing update. Undo the collection change instead."
MANUAL_CHECK = "needs manual check"
FOLDER_NOT_EMPTY = (
    " — undo the later changes to this collection first (or move out what was added to the folder)"
)


@dataclass(frozen=True)
class JournalEntry:
    """One row of the ``operations`` journal."""

    id: int
    batch_id: str
    seq: int
    kind: str
    src: str | None
    dst: str | None
    drive_id: str | None
    size: int | None
    mtime: float | None
    is_file: bool | None
    state: str
    error: str | None
    origin: str
    undo_of: str | None
    created: float
    finished: float | None
    label: str | None = None
    method: str | None = None  # rule pictures: "rename" or "copy"
    content_hash: str | None = None  # rule pictures: sha256 of the file
    # a folder moved across disks, on its final QUARANTINE: where the copy is, and the
    # folder rows that followed it (JSON: [[old_id, new_id, old_path, new_path], ...])
    copied_to: str | None = None
    followed: str | None = None


@dataclass
class RecoveryResult:
    """Settled rows, plus index updates that failed (the next scan repairs the index;
    the rows stay ``done``), in the spirit of ``BatchResult.index_error``."""

    entries: list[JournalEntry] = field(default_factory=list)
    index_errors: list[str] = field(default_factory=list)


def entries(ex: Executor, *where) -> list[JournalEntry]:
    with ex.engine.connect() as conn:
        rows = conn.execute(select(operations).where(*where).order_by(operations.c.id))
        return [JournalEntry(**r) for r in rows.mappings()]


# --- undo ----------------------------------------------------------------------


def undo(ex: Executor, batch_id: str) -> BatchResult:
    """Revert the acted (``done``/``unverified``) rows of ``batch_id``, newest first.

    Restores are exact: an occupied origin is a ``GuardError``, never a suffix.
    Created folders stay (never removed), except a folder inside Ongoing that took
    the place of an entry the batch removed, and the folders the same batch created
    inside it (``_replaces``): they are removed (REMOVE_EMPTY_DIR, deepest
    first, each still the identity-recorded, empty folder the app made) so the
    original can be restored. A removed empty folder (REMOVE_EMPTY_DIR)
    is re-created by an exact MKDIR, refused if anything occupies the path; the
    ``.DS_Store`` file deleted with it is never restored (Finder caches only).
    Everything is checked before anything is touched: if a moved file or a created
    link differs from the journal, ``OpFailed("changed since …")``. Each original
    row is marked ``undone`` as its inverse completes (or ends ``unverified``: the
    revert was carried out).
    An undo batch itself cannot be undone (no redo), nor can an automatic Ongoing
    sync (origin ``"workflow"``): undo the collection change instead.
    """
    resolved, kept = _plan_undo(ex, batch_id)
    result = ex._run_resolved(  # private: undo is part of the executor
        UNDO_ORIGIN, resolved, BatchResult(uuid4().hex, dry_run=False), undo_of=batch_id
    )
    result.kept = kept
    if len(result.done) == len(resolved):
        # complete: created folders count as undone, and so do the files a folder move
        # found at the destination already (no inverse: ``_select_reverts``)
        with write_tx(ex.engine) as conn:
            conn.execute(
                update(operations)
                .where(
                    operations.c.batch_id == batch_id,
                    operations.c.kind == str(OpKind.MKDIR),
                    operations.c.state.in_(ACTED),
                )
                .values(state="undone")
            )
            conn.execute(
                update(operations)
                .where(
                    operations.c.batch_id == batch_id,
                    operations.c.kind == str(OpKind.COPY_ACROSS),
                    operations.c.method == primitives.PRESENT,
                    operations.c.state.in_(ACTED),
                )
                .values(state="undone")
            )
    return result


def plan_undo(ex: Executor, batch_id: str) -> list[ResolvedOp]:
    """The resolved inverse plan ``undo(batch_id)`` would run, with all its refusals
    (an undo, an automatic sync, interrupted, nothing to undo, changed since, an
    occupied origin, the app's folder not empty). Read only: nothing on disk changes
    and nothing is journaled. ``undo`` itself runs exactly this plan."""
    return _plan_undo(ex, batch_id)[0]


def made_folders_kept(ex: Executor, batch_id: str) -> list[str]:
    """The folders ``undo(batch_id)`` would leave alone (made by a New folder / layout
    batch, but something was put in them since)."""
    return _plan_undo(ex, batch_id)[1]


def _plan_undo(ex: Executor, batch_id: str) -> tuple[list[ResolvedOp], list[str]]:
    rows = entries(ex, operations.c.batch_id == batch_id)
    if not rows:
        raise OpFailed("That change could not be found.")
    if any(r.undo_of is not None for r in rows):
        raise OpFailed("This was an undo, so it cannot be undone again.")
    if any(r.origin == SYNC_ORIGIN for r in rows):
        raise OpFailed(SYNC_UNDO_REFUSED)
    if any(r.state == "planned" for r in rows):
        raise OpFailed("This change was interrupted before it finished. Run dam recover first.")
    acted = [r for r in rows if r.state in ACTED]
    if not acted:
        raise OpFailed("There is nothing to undo here.")
    _check_no_later_move_relies(ex, batch_id, acted)
    known: dict[str, bool] = {}  # each folder's root is listed once
    for row in acted:  # an unplugged folder would look changed: wait until it is back
        check_connected(ex.paths, row.src, row.dst, known=known)
    made = _made_identities(ex, batch_id)
    revert, kept = _select_reverts(ex, acted, made)
    for row in revert:
        if not (row.kind == OpKind.MKDIR and _fold_key(row.dst) in made):  # checked already
            _check_unchanged(ex, row, _now_at(row, acted))
    inverses = [_inverse(ex, r, made) for r in revert]
    for op, row in zip(inverses, revert, strict=True):
        _check_restores_origin(ex, op, row)
    plan = Plan(inverses, origin=UNDO_ORIGIN)
    # restore=True enables the restore-only guard exceptions for these exact ops;
    # Executor.preview/apply refuse origin "undo", so no other caller gets them.
    try:
        planner = Planner(ex.paths, ex.areas_dir)
        resolved = planner.resolve(plan, restore=True, connected=known)
        _mark_restored_rows(resolved, revert)
        return resolved, kept
    except GuardError as e:
        if str(e).startswith("not empty:") and any(
            op.kind is OpKind.REMOVE_EMPTY_DIR for op in inverses
        ):
            # the app's folder holds what came later (a sync's links, the user's files)
            raise GuardError(f"{e}{FOLDER_NOT_EMPTY}") from None
        raise


def _check_no_later_move_relies(ex: Executor, batch_id: str, acted: list[JournalEntry]) -> None:
    """A later move of the same folder across disks found this batch's copies present
    and sent the folder (with the originals) to To Delete: undoing this batch would move
    those copies, the only live ones, to To Delete as well. Refused until that later move
    is undone (its final QUARANTINE is acted and not undone). OpFailed: a 409, like the
    other refusals here."""
    made = {
        fold_parts(r.dst)
        for r in acted
        if r.kind == OpKind.COPY_ACROSS and r.method != primitives.PRESENT
    }
    if not made:
        return
    present = entries(
        ex,
        operations.c.batch_id != batch_id,
        operations.c.kind == str(OpKind.COPY_ACROSS),
        operations.c.method == primitives.PRESENT,
        operations.c.state.in_(ACTED),
    )
    for later in dict.fromkeys(r.batch_id for r in present if fold_parts(r.dst) in made):
        for final in entries(
            ex,
            operations.c.batch_id == later,
            operations.c.kind == str(OpKind.QUARANTINE),
            operations.c.copied_to.is_not(None),
            operations.c.state.in_(ACTED),
        ):
            raise OpFailed(f"Undo the later move of {PurePosixPath(final.src).name} first.")


def _mark_restored_rows(resolved: list[ResolvedOp], revert: list[JournalEntry]) -> None:
    """The QUARANTINE that undoes a copy across disks carries the original's path and
    id, so the executor points the index row back at the original. The MOVE that brings
    a folder moved across disks back from To Delete carries the folder rows that
    followed its copy (``followed``), so they follow back."""
    copies = {fold_parts(r.dst): r for r in revert if r.kind == OpKind.COPY_ACROSS}
    folders = {
        fold_parts(r.dst): r
        for r in revert
        if r.kind == OpKind.QUARANTINE and r.copied_to is not None
    }
    for rop in resolved:
        if rop.kind is OpKind.QUARANTINE:
            row = copies.get(fold_parts(rop.src))
            if row is not None:
                rop.restore_row = (row.src, row.drive_id)
        elif rop.kind is OpKind.MOVE:
            row = folders.get(fold_parts(rop.src))
            if row is not None and row.followed:
                rop.follow_back = [tuple(f) for f in json.loads(row.followed)]


def _fold_key(rel: str) -> tuple[str, ...]:
    return fold_parts(rel)


def _made_identities(ex: Executor, batch_id: str) -> dict[tuple[str, ...], identity.Identity]:
    """Folders ``batch_id`` made as a New folder / layout batch (``made_folders``):
    folded path -> the identity recorded right after it was made."""
    with ex.engine.connect() as conn:
        rows = conn.execute(
            select(
                made_folders.c.rel,
                made_folders.c.st_dev,
                made_folders.c.st_ino,
                made_folders.c.st_birth,
            ).where(made_folders.c.batch_id == batch_id)
        ).all()
    return {_fold_key(r.rel): identity.from_columns(r.st_dev, r.st_ino, r.st_birth) for r in rows}


def _select_reverts(
    ex: Executor, acted: list[JournalEntry], made: dict
) -> tuple[list[JournalEntry], list[str]]:
    """The acted rows to revert, newest first, and the made folders to leave alone.

    A folder a New folder / layout batch made is removed only if it is still the folder
    that was made (its identity), and empty: holding nothing, or only folders removed
    before it in this same undo (deepest first) and a genuine Finder ``.DS_Store``.
    Otherwise it stays, and so does every folder that holds it. Other created folders
    stay, as ever, except those ``_replaces`` names.

    A copy across disks goes to To Delete before the folders it is in, so it does not
    keep them. A file a folder move found at the destination already (``present``) has
    no inverse: that copy belongs to the earlier batch, whose own undo moves it."""
    revert: list[JournalEntry] = []
    kept: list[str] = []
    removed: set[tuple[str, ...]] = set()
    for r in reversed(acted):
        if r.kind == OpKind.COPY_ACROSS and r.method == primitives.PRESENT:
            continue
        if r.kind == OpKind.COPY_ACROSS:
            revert.append(r)
            removed.add(_fold_key(r.dst))
        elif r.kind != OpKind.MKDIR:
            revert.append(r)
        elif _fold_key(r.dst) in made:
            if _removable(ex, r.dst, made[_fold_key(r.dst)], removed):
                revert.append(r)
                removed.add(_fold_key(r.dst))
            else:
                kept.append(r.dst)
        elif _replaces(ex, r, acted):
            revert.append(r)
    return revert, kept


def _removable(ex: Executor, rel: str, ident: identity.Identity, removed: set) -> bool:
    """``rel`` is still the recorded real folder and holds nothing that stays."""
    p = ex.paths.abs(rel)
    try:
        st = os.lstat(p)
        if (
            stat.S_ISLNK(st.st_mode)
            or not stat.S_ISDIR(st.st_mode)
            or not identity.same_object(ident, identity.of_stat(st, path=p))
        ):
            return False
        names = os.listdir(p)
    except OSError:
        return False
    for name in names:
        if name == DS_STORE:
            if finder_cache_problem(p) is not None:
                return False
        elif _fold_key(join(rel, name)) not in removed:
            return False
    return True


def _replaces(ex: Executor, row: JournalEntry, acted: list[JournalEntry]) -> bool:
    """An MKDIR inside a publish root (Ongoing or Important) at a path an earlier op
    of the same batch vacated
    (UNLINK_SYMLINK or REMOVE_EMPTY_DIR), e.g. the Ongoing converter replacing a
    user's folder or link with the app's folder, or a parent collection's one link
    with its folder (at the top, or inside its own parent's folder), or an MKDIR
    strictly inside such a folder, by an earlier op of the same batch (the
    collection's group subfolders). Unlike other created folders they are removed
    again (REMOVE_EMPTY_DIR: refused unless empty, and unless still the app's
    recorded folder), deepest first, or the original could never be put back at its
    path."""
    if ex.paths.in_publish_root(row.dst) is None:
        return False
    if any(
        r.seq < row.seq
        and OpKind(r.kind) in (OpKind.UNLINK_SYMLINK, OpKind.REMOVE_EMPTY_DIR)
        and fold_parts(r.src) == fold_parts(row.dst)
        for r in acted
    ):
        return True
    return any(
        r.seq < row.seq
        and OpKind(r.kind) is OpKind.MKDIR
        and is_under(row.dst, r.dst, strict=True)
        and _replaces(ex, r, acted)
        for r in acted
    )


def _now_at(row: JournalEntry, acted: list[JournalEntry]) -> str:
    """Where the entry ``row`` produced is now: later ops of the batch may have moved
    it again, or a folder holding it (a rename chain, a file then its folder)."""
    loc = row.dst
    for later in acted:
        if later.seq > row.seq and OpKind(later.kind) in RELOCATE:
            if is_under(loc, later.src):
                loc = rebase(loc, later.src, later.dst)
    return loc


def _check_unchanged(ex: Executor, row: JournalEntry, now_at: str) -> None:
    """Refuse if what the op left behind (now at ``now_at``) is no longer what the
    journal recorded: missing, a different type, or a different identity.

    Identity: with a journaled drive_id, the same drive_id and (files) the same size;
    mtime is ignored, because Google Drive rewrites it on sync. TRADE-OFF: a same-size
    in-place edit of a Drive file does not block its undo. Without a drive_id, a file
    must keep its size and mtime.

    LIMITATION: a folder is compared by drive_id only (when one was recorded). Without
    one, any folder at that path passes; its contents are not compared.
    """
    kind = OpKind(row.kind)
    if kind in RELOCATE:
        p = ex.paths.abs(now_at)
        try:
            st = os.lstat(p)
        except FileNotFoundError:
            raise OpFailed(f"{now_at} is missing, so this cannot be undone.") from None
        same = not _type_changed(st, row)
        if same and stat.S_ISREG(st.st_mode) and row.size is not None:
            same = st.st_size == row.size
            if row.drive_id is None:  # no id to go by: the mtime must match too
                same = same and st.st_mtime == row.mtime
        if same and row.drive_id is not None:
            same = read_drive_id(p) == row.drive_id
        if not same:
            raise OpFailed(f"{now_at} has changed since, so this cannot be undone.")
    elif kind in (OpKind.COPY, OpKind.COPY_ACROSS, OpKind.PICTURE_TO_QUARANTINE):
        # still the file that came in
        p = ex.paths.abs(now_at)
        try:
            st = os.lstat(p)
        except FileNotFoundError:
            raise OpFailed(f"{now_at} is missing, so this cannot be undone.") from None
        if not stat.S_ISREG(st.st_mode) or (row.size is not None and st.st_size != row.size):
            raise OpFailed(f"{now_at} has changed since, so this cannot be undone.")
        if row.content_hash is not None and primitives.file_sha256(p) != row.content_hash:
            raise OpFailed(f"{now_at} has changed since, so this cannot be undone.")
    elif kind is OpKind.MKDIR:  # only folders that replaced a vacated entry (_replaces)
        p = ex.paths.abs(now_at)
        if (
            p.is_symlink()
            or not p.is_dir()
            or not identity.same_object(_recorded_identity(ex, now_at), identity.of_path(p))
        ):
            raise OpFailed(
                f"{now_at} is no longer the folder the app made, so this cannot be undone."
            )
    elif kind is OpKind.SYMLINK:
        link = ex.paths.abs(now_at)
        if not link.is_symlink() or readlink(link) != str(ex.link_target(row.src)):
            why = ""
            if ex.paths.in_publish_root(now_at) is not None:
                why = (
                    " The collection changed after the conversion, or Ongoing was edited."
                    " Undo that change first."
                )
            raise OpFailed(f"The link {now_at} has changed since, so this cannot be undone.{why}")


def _recorded_identity(ex: Executor, rel: str) -> identity.Identity | None:
    """The ``(st_dev, st_ino)`` the Ongoing publisher recorded for the folder it
    created at ``rel`` (``ongoing_entries``), None if it recorded none: a folder the
    user put there since is never the app's."""
    with ex.engine.connect() as conn:
        rows = conn.execute(
            select(
                ongoing_entries.c.rel,
                ongoing_entries.c.st_dev,
                ongoing_entries.c.st_ino,
                ongoing_entries.c.st_birth,
            ).where(ongoing_entries.c.kind == "folder")
        ).all()
    return next(
        (
            identity.from_columns(r.st_dev, r.st_ino, r.st_birth)
            for r in rows
            if fold_parts(r.rel) == fold_parts(rel)
        ),
        None,
    )


def _inverse(ex: Executor, row: JournalEntry, made: dict | None = None) -> Op:
    kind = OpKind(row.kind)
    if kind is OpKind.MKDIR and made and _fold_key(row.dst) in made:
        # a folder a New folder / layout batch made: removed only while it is still
        # that folder (identity, checked again on the opened fd) and empty
        return Op(
            OpKind.REMOVE_EMPTY_DIR, row.dst, None, identity=made[_fold_key(row.dst)], made=True
        )
    if kind in (OpKind.COPY, OpKind.COPY_ACROSS):
        # a copy (into the inbox, or across disks): moved to the To Delete of its own
        # folder, never deleted; a copy across disks also gives the index row back to
        # the original (``_mark_restored_rows``)
        return Op(OpKind.QUARANTINE, row.dst, None)
    if kind is OpKind.PICTURE_TO_QUARANTINE:
        # back to its plain name in the rules' areas folder, refused if that is taken
        return Op(OpKind.PICTURE_BACK, row.dst, row.src, exact=True)
    if kind is OpKind.MKDIR:  # a folder that replaced a vacated entry (_replaces)
        # removed only while it is still that recorded folder (checked again on the
        # opened fd at act time)
        return Op(OpKind.REMOVE_EMPTY_DIR, row.dst, None, identity=_recorded_identity(ex, row.dst))
    if kind is OpKind.REMOVE_EMPTY_DIR:
        # Exactly the same path, never an existing folder reused (the planner refuses
        # an occupied path); its parent, Ongoing, is top-level and never created.
        return Op(OpKind.MKDIR, None, row.src, exact=True)
    top = ex.paths.is_top_level(row.src) or ex.paths.is_top_level(row.dst)
    if kind is OpKind.SYMLINK:
        # dst names the target the app made the link with: wherever the link is, it is
        # removed only while it is still a symbolic link pointing there (guards)
        return Op(OpKind.UNLINK_SYMLINK, row.dst, row.src, exact=True)
    if kind is OpKind.UNLINK_SYMLINK:
        # dst holds the link's target (archive-relative or abs:). LIMITATION: the link
        # is recreated with an absolute target even if the original was relative.
        return Op(OpKind.SYMLINK, row.dst, row.src, allow_top_level=top, exact=True)
    name = PurePosixPath(row.src).name
    if kind is OpKind.RENAME:
        return Op(OpKind.RENAME, row.dst, name, allow_top_level=top, exact=True)
    # MOVE (possibly with a new name) and QUARANTINE: back to the exact origin. A
    # top-level origin means a MOVE into the root, which guards allow only for undo.
    return Op(OpKind.MOVE, row.dst, parent(row.src), name=name, allow_top_level=top, exact=True)


def _check_restores_origin(ex: Executor, op: Op, row: JournalEntry) -> None:
    """Belt and braces: a MOVE inverse lands exactly on the journaled source, and a
    MOVE into the root only puts back a top-level item."""
    if op.kind is not OpKind.MOVE:
        return
    if fold_parts(join(op.dst, op.name)) != fold_parts(row.src):
        raise OpFailed(f"internal: inverse of row {row.id} does not restore {row.src!r}")
    if ex.paths.is_root(op.dst) and not ex.paths.is_top_level(row.src):
        raise OpFailed(f"internal: inverse of row {row.id} moves into the root")


def _type_changed(st: os.stat_result, row: JournalEntry) -> bool:
    """A file where a non-file was journaled, or the reverse (e.g. a folder replacing
    a moved file). Rows from before migration 0002 have no type: not compared."""
    return row.is_file is not None and stat.S_ISREG(st.st_mode) != row.is_file


def mark_reverted(
    conn: Connection, batch_id: str, kind: OpKind, src: str | None, dst: str | None
) -> None:
    """Mark the row of ``batch_id`` that the undo op (kind, src, dst) reverted."""
    rows = conn.execute(
        select(operations)
        .where(operations.c.batch_id == batch_id, operations.c.state.in_(ACTED))
        .order_by(operations.c.seq.desc())
    ).mappings()

    def same(a: str | None, b: str | None) -> bool:
        return a is not None and b is not None and fold_parts(a) == fold_parts(b)

    for r in rows:
        match OpKind(kind):
            case OpKind.UNLINK_SYMLINK:
                hit = r["kind"] == OpKind.SYMLINK and same(r["dst"], src)
            case OpKind.SYMLINK:
                hit = r["kind"] == OpKind.UNLINK_SYMLINK and same(r["src"], dst)
            case OpKind.MKDIR:
                hit = r["kind"] == OpKind.REMOVE_EMPTY_DIR and same(r["src"], dst)
            case OpKind.REMOVE_EMPTY_DIR:
                hit = r["kind"] == OpKind.MKDIR and same(r["dst"], src)
            case OpKind.PICTURE_BACK:
                hit = r["kind"] == OpKind.PICTURE_TO_QUARANTINE and same(r["dst"], src)
            case k if k in RELOCATE:
                hit = (r["kind"] in RELOCATE and same(r["dst"], src) and same(r["src"], dst)) or (
                    k is OpKind.QUARANTINE
                    and r["kind"] in (OpKind.COPY, OpKind.COPY_ACROSS)
                    and same(r["dst"], src)
                )
            case _:
                hit = False
        if hit:
            conn.execute(
                update(operations).where(operations.c.id == r["id"]).values(state="undone")
            )
            return


# --- crash recovery -----------------------------------------------------------------


def pending(ex: Executor) -> list[JournalEntry]:
    """Rows still ``planned``: the process stopped between journaling and finishing."""
    return entries(ex, operations.c.state == "planned")


def recover(ex: Executor) -> RecoveryResult:
    """Settle every ``planned`` row from what is on disk (read only; never acts).

    ``done`` (+ index update, and the reverted original for an undo row) when the op
    evidently happened, ``failed`` with ``"interrupted before execution"`` when it
    evidently did not, otherwise ``failed`` with ``"needs manual check"``. An index
    update that fails is collected in ``index_errors``; the remaining rows still run.
    A done final QUARANTINE of a folder moved across disks (``copied_to``) also has its
    folder rows follow its copy: planned and journaled first when ``followed`` is
    missing, else the journaled plan again (idempotent; index only).
    """
    result = RecoveryResult()
    settled: set[int] = set()
    for e in pending(ex):
        state, error = _classify(ex, e)
        now = time.time()
        with write_tx(ex.engine) as conn:
            conn.execute(
                update(operations)
                .where(operations.c.id == e.id)
                .values(state=state, error=error, finished=now)
            )
            if state == "done" and e.undo_of is not None:
                mark_reverted(conn, e.undo_of, OpKind(e.kind), e.src, e.dst)
        if state == "done" and OpKind(e.kind) in (*RELOCATE, OpKind.COPY_ACROSS):
            settled.add(e.id)
            try:
                with INDEX_LOCK:
                    if OpKind(e.kind) is OpKind.COPY_ACROSS:
                        rop = ResolvedOp(OpKind.COPY_ACROSS, e.src, e.dst, method=e.method)
                        ex._repoint_copy(rop)
                    elif e.copied_to is not None:  # a folder moved across disks
                        ex._recover_followed(e)
                    else:
                        ex.repo.update_path(e.src, e.dst)
            except SQLAlchemyError as err:
                result.index_errors.append(f"index update failed for {e.dst}: {err}")
        result.entries.append(dataclasses.replace(e, state=state, error=error, finished=now))
    # a folder moved across disks whose index step stopped part way (its row was done
    # already): its folder rows follow now
    for e in entries(
        ex,
        operations.c.kind == str(OpKind.QUARANTINE),
        operations.c.state == "done",
        operations.c.copied_to.is_not(None),
    ):
        if e.id in settled:
            continue
        try:
            with INDEX_LOCK:
                ex._recover_followed(e)
        except SQLAlchemyError as err:
            result.index_errors.append(f"index update failed for {e.dst}: {err}")
    return result


def _classify(ex: Executor, e: JournalEntry) -> tuple[str, str | None]:
    try:
        happened = _happened(ex, e)
    except (OSError, OutsideArchiveError, ValueError):
        happened = None
    if happened is None:
        return "failed", MANUAL_CHECK
    return ("done", None) if happened else ("failed", INTERRUPTED)


def _happened(ex: Executor, e: JournalEntry) -> bool | None:
    """True: the op's effect is on disk; False: the state before it; None: unclear."""
    match OpKind(e.kind):
        case OpKind.MKDIR:
            dst = ex.paths.abs(e.dst)
            if not os.path.lexists(dst):
                return False
            return True if dst.is_dir() and not dst.is_symlink() else None
        case OpKind.COPY:
            dst = ex.paths.abs(e.dst)
            if not os.path.lexists(dst):
                return False
            st = os.lstat(dst)
            # complete only when it has the size of the source (a cut-short copy is not)
            return True if stat.S_ISREG(st.st_mode) and st.st_size == e.size else None
        case OpKind.COPY_ACROSS if e.method == primitives.PRESENT:
            return _present_happened(ex, e)
        case OpKind.COPY_ACROSS:
            return _copy_across_happened(ex, e)
        case OpKind.PICTURE_TO_QUARANTINE | OpKind.PICTURE_BACK:
            if ex.areas_dir is None:
                return None
            if OpKind(e.kind) is OpKind.PICTURE_TO_QUARANTINE:
                here, there = ex.paths.abs(e.dst), Path(ex.areas_dir) / e.src
            else:  # back: the file was in the archive (src) and goes to the areas folder
                here, there = Path(ex.areas_dir) / e.dst, ex.paths.abs(e.src)
            if e.method == primitives.PICTURE_COPY:
                return _picture_copy_happened(ex, e, here, there)
            if os.path.lexists(there) and not os.path.lexists(here):
                return False  # still where it was
            if os.path.lexists(here) and not os.path.lexists(there):
                st = os.lstat(here)
                return True if stat.S_ISREG(st.st_mode) and st.st_size == e.size else None
            return None
        case OpKind.SYMLINK:
            link = ex.paths.abs(e.dst)
            if not os.path.lexists(link):
                return False
            ok = link.is_symlink() and readlink(link) == str(ex.link_target(e.src))
            return True if ok else None
        case OpKind.UNLINK_SYMLINK:
            link = ex.paths.abs(e.src)
            if not os.path.lexists(link):
                return True
            return False if link.is_symlink() else None
        case OpKind.REMOVE_EMPTY_DIR:
            folder = ex.paths.abs(e.src)
            if not os.path.lexists(folder):
                return True
            # Still there (its .DS_Store may be gone: never restored anyway).
            return False if folder.is_dir() and not folder.is_symlink() else None
    src, dst = ex.paths.abs(e.src), ex.paths.abs(e.dst)
    if fold_parts(e.src) == fold_parts(e.dst):  # case-only: both "exist"; match names
        src_here, dst_here = _exact_name_exists(src), _exact_name_exists(dst)
    else:
        src_here, dst_here = os.path.lexists(src), os.path.lexists(dst)
    if dst_here and not src_here:
        return True if _same_entry(dst, e) else None
    if src_here and not dst_here:
        return False
    return None


def _copy_across_happened(ex: Executor, e: JournalEntry) -> bool | None:
    """A copy across disks is complete when the copy has the journaled size and hash and
    the original is still in its place (its move to To Delete is a row of its own). An
    unfinished temporary copy, or a copy that does not match: unclear, every file is left
    alone. Nothing at all: the copy never started."""
    dst, src = ex.paths.abs(e.dst), ex.paths.abs(e.src)
    if not os.path.lexists(dst):
        try:
            names = os.listdir(dst.parent)
        except FileNotFoundError:
            return False
        temp = any(n.startswith(TEMP_COPY_PREFIX) and n.endswith(f"-{dst.name}") for n in names)
        return None if temp else False
    st = os.lstat(dst)
    if not stat.S_ISREG(st.st_mode) or st.st_size != e.size or not os.path.lexists(src):
        return None
    return True if primitives.file_sha256(dst) == e.content_hash else None


def _present_happened(ex: Executor, e: JournalEntry) -> bool | None:
    """A file a folder move found at the destination already: nothing was written, only
    compared. Done when both files are there and the same (their hashes); otherwise
    unclear, and both are left alone."""
    src, dst = ex.paths.abs(e.src), ex.paths.abs(e.dst)
    for p in (src, dst):
        if not os.path.lexists(p) or not stat.S_ISREG(os.lstat(p).st_mode):
            return None
    return True if primitives.file_sha256(src) == primitives.file_sha256(dst) else None


def _picture_copy_happened(ex: Executor, e: JournalEntry, here: Path, there: Path) -> bool | None:
    """A rule picture that crosses disks is copied (``here``, the new file) and the original
    (``there``) is removed afterwards. Both files present with the journaled hash: the
    copy is complete, so a move out of the areas folder is finished by removing the
    original (only if its hash matches too). A copy that is partial or does not match,
    or anything else unclear: both files are left alone and the row is reported. A copy
    back never removes anything: it is done when the new file has the journaled hash."""
    if e.content_hash is None:
        return None
    here_ok = (
        os.path.lexists(here)
        and stat.S_ISREG(os.lstat(here).st_mode)
        and primitives.file_sha256(here) == e.content_hash
    )
    if not os.path.lexists(there):
        return True if here_ok else None
    if not os.path.lexists(here):
        return False  # nothing was copied
    if not here_ok:
        return None  # a partial or different copy: leave both
    if OpKind(e.kind) is OpKind.PICTURE_BACK:
        return True  # the archive file stays, always
    try:
        primitives.remove_moved_picture(there, Path(ex.areas_dir), here, e.content_hash)
    except (OSError, OpFailed, GuardError):
        return None
    return True


def _same_entry(dst: Path, e: JournalEntry) -> bool:
    """The entry at ``dst`` is the one the journal recorded: same type (file or not),
    same drive_id (when one was journaled) and, for a file, the same size. mtime is
    not compared (Drive rewrites it). Without a drive_id a folder cannot be told apart
    from another folder (LIMITATION) and is accepted."""
    st = os.lstat(dst)
    if _type_changed(st, e):
        return False
    if e.drive_id is not None and read_drive_id(dst) != e.drive_id:
        return False
    if stat.S_ISREG(st.st_mode) and e.size is not None:
        return st.st_size == e.size
    return True


def _exact_name_exists(p: Path) -> bool:
    """``p`` exists under exactly this spelling (not only a case/NFC variant)."""
    return os.path.lexists(p) and p.name in os.listdir(p.parent)
