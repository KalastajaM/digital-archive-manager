"""Journal-then-act executor: the only code that changes the archive."""

import logging
import os
import stat
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import Engine, insert, update
from sqlalchemy.exc import SQLAlchemyError

from dam.core.fs import readlink
from dam.core.paths import ArchivePaths, OutsideArchiveError
from dam.db.engine import write_tx
from dam.db.tables import made_folders, operations
from dam.index.driveid import read_drive_id
from dam.index.locks import INDEX_LOCK
from dam.index.repo import FileRepo
from dam.ops import identity, primitives
from dam.ops import undo as _undo
from dam.ops.guards import check_areas_source, fold_parts
from dam.ops.model import (
    ABS_TARGET,
    UNDO_ORIGIN,
    BatchResult,
    GuardError,
    OpFailed,
    OpKind,
    Plan,
    ResolvedOp,
)
from dam.ops.planner import Planner
from dam.ops.undo import JournalEntry, RecoveryResult
from dam.services import LOCAL_ID_PREFIX

if TYPE_CHECKING:
    from dam.locks import LockService

log = logging.getLogger(__name__)

__all__ = ["Executor", "JournalEntry", "RecoveryResult"]

_RELOCATE = _undo.RELOCATE
_FAILURES = (OSError, OpFailed, GuardError, OutsideArchiveError)
# Ops that only touch links and folders inside a publish root (##. Ongoing or
# ##. Important; no Drive uploads of documents)
_PICTURE_KINDS = {OpKind.PICTURE_TO_QUARANTINE, OpKind.PICTURE_BACK}
_ONGOING_KINDS = {OpKind.MKDIR, OpKind.SYMLINK, OpKind.UNLINK_SYMLINK, OpKind.REMOVE_EMPTY_DIR}


def _outside_copy(rop: ResolvedOp) -> bool:
    """A COPY of a file elsewhere on this computer (``abs:``), not one already in the
    archive."""
    return rop.kind is OpKind.COPY and rop.src is not None and rop.src.startswith(ABS_TARGET)


class Executor:
    def __init__(
        self,
        paths: ArchivePaths,
        engine: Engine,
        repo: FileRepo,
        throttle_ms: int = 0,
        areas_dir: Path | None = None,
    ) -> None:
        self.paths = paths
        # the rules' picture folder (config/rules/areas): the one place outside the archive
        # that PICTURE_TO_QUARANTINE takes a file from and PICTURE_BACK returns it to
        self.areas_dir = areas_dir
        self.engine = engine
        self.repo = repo
        self.throttle_ms = throttle_ms
        # refuses a change to a locked file (``dam.locks``); set by the App
        self.locks: LockService | None = None
        # set when the app closes: a copy across disks in progress ends at its next
        # chunk (its unfinished temporary file stays, and the op fails saying so)
        self.cancel_copies = threading.Event()

    def preview(self, plan: Plan) -> list[ResolvedOp]:
        """Validate and resolve ``plan`` without touching the disk or the journal.

        Plans claiming ``origin="undo"`` are refused: undo batches are built only by
        ``undo()``, which resolves them itself with the restore exceptions.
        """
        if plan.origin == UNDO_ORIGIN:
            raise GuardError('origin "undo" is reserved for Executor.undo()')
        return Planner(self.paths, self.areas_dir, self.locks).resolve(plan)

    def apply(
        self,
        plan: Plan,
        dry_run: bool = False,
        check: Callable[[list[ResolvedOp]], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        progress: Callable[[ResolvedOp, int, int], None] | None = None,
    ) -> BatchResult:
        """Run ``plan``; stops at the first failure. Dry run: ``done`` lists what would run.

        ``check`` (optional) is called with the resolved ops before anything is
        journaled or changed; it raises to refuse the whole plan. The ops it approved
        are exactly the ops run (each relocation's ``drive_id`` is re-checked against
        the disk at act time by the pre-check).

        ``should_stop`` (a background move) is asked before each op; true ends the batch
        there (``BatchResult.stopped``), except between a copy across disks and the move
        of its original to To Delete, which always run together. ``progress`` is called
        with each op that completed, its index and the number of ops.
        """
        resolved = self.preview(plan)
        if check is not None:
            check(resolved)
        result = BatchResult(batch_id=uuid4().hex, dry_run=dry_run)
        if dry_run:
            result.done = resolved
            return result
        return self._run_resolved(
            plan.origin, resolved, result, label=plan.label, should_stop=should_stop,
            progress=progress,
        )

    # --- undo and recovery (see dam.ops.undo) --------------------------------

    def undo(self, batch_id: str) -> BatchResult:
        """Revert batch ``batch_id`` exactly (see ``dam.ops.undo.undo``)."""
        return _undo.undo(self, batch_id)

    def preview_undo(self, batch_id: str) -> list[ResolvedOp]:
        """The plan ``undo(batch_id)`` would run, read only (see ``dam.ops.undo``).

        Not ``preview()``: that refuses origin "undo" and resolves without the
        restore-only guard exceptions, so it would refuse exact restores that undo
        accepts. This is the very planning ``undo()`` runs before it acts."""
        return _undo.plan_undo(self, batch_id)

    def pending(self) -> list[JournalEntry]:
        """Journal rows still ``planned`` (interrupted operations)."""
        return _undo.pending(self)

    def recover(self) -> RecoveryResult:
        """Settle ``planned`` rows from the disk, read only (see ``dam.ops.undo``)."""
        return _undo.recover(self)

    # --- run -----------------------------------------------------------------

    def _run_resolved(
        self,
        origin: str,
        resolved: list[ResolvedOp],
        result: BatchResult,
        undo_of: str | None = None,
        label: str | None = None,
        should_stop: Callable[[], bool] | None = None,
        progress: Callable[[ResolvedOp, int, int], None] | None = None,
    ) -> BatchResult:
        """Journal and carry out ``resolved`` in order; ``undo_of``: the batch reverted.
        ``should_stop`` and ``progress``: see ``apply``.

        The throttle (spacing out changes Drive must sync) applies only to ops outside
        the publish roots: creating or removing links and folders inside ``##. Ongoing``
        or ``##. Important`` never waits, also in a batch that mixes both (an Ongoing
        conversion)."""
        for seq, rop in enumerate(resolved):
            pair = seq and resolved[seq - 1].kind is OpKind.COPY_ACROSS
            if should_stop is not None and not pair and should_stop():
                result.stopped = True
                return result
            if seq and self.throttle_ms and not self._in_publish_root(rop):
                time.sleep(self.throttle_ms / 1000)  # outside the lock
            with INDEX_LOCK:
                if self._run_op(seq, rop, origin, result, undo_of, label):
                    return result
            if progress is not None:
                progress(rop, seq, len(resolved))
        return result

    def _in_publish_root(self, rop: ResolvedOp) -> bool:
        return rop.kind in _ONGOING_KINDS and self.paths.in_publish_root(rop.dst) is not None

    def _removal_root(self, rel: str, made: bool = False, undo_link: bool = False) -> Path:
        """The publish root a removal at ``rel`` happens in, for the primitive's own
        containment check. The guards have refused anything outside both roots
        already; Ongoing is handed over otherwise, and the primitive refuses it.
        A folder the app made (``made``, undo of New folder / layout), and a link the
        app made outside the publish roots (``undo_link``, undo of a Link drop), are
        checked from the archive folder itself."""
        if made or (undo_link and self.paths.in_publish_root(rel) is None):
            return self.paths.folder_of(rel).root
        root = self.paths.in_publish_root(rel) or self.paths.ongoing
        return self.paths.abs(root)

    def _run_op(
        self,
        seq: int,
        rop: ResolvedOp,
        origin: str,
        result: BatchResult,
        undo_of: str | None,
        label: str | None = None,
    ) -> bool:
        """Journal, act, verify and index one op; True when the batch must stop."""
        try:
            snap, snap_error = self._snapshot(rop), None
        except _FAILURES as e:
            snap, snap_error = self._empty_snapshot(), f"cannot read source: {e}"
        rop.content_hash = snap["content_hash"]  # a rule picture's hash, for the act
        op_id = self._journal_planned(result.batch_id, seq, rop, snap, origin, undo_of, label)
        if snap_error is not None:
            self._stop(result, op_id, rop, "failed", snap_error)
            return True
        try:
            self._precheck(rop)
            self._act(rop)
        except _FAILURES as e:
            self._stop(result, op_id, rop, "failed", str(e))
            return True
        try:
            self._verify(rop, snap)
        except _FAILURES as e:
            # The act happened but the result is not what we expected: needs a human.
            # For an undo op the revert was carried out: the original is undone too.
            self._stop(result, op_id, rop, "unverified", str(e), undo_of)
            return True
        self._journal_finish(op_id, "done", reverts=undo_of, rop=rop)
        result.done.append(rop)
        if rop.kind is OpKind.MKDIR and rop.made:
            self._record_made(result.batch_id, rop)
        if rop.kind is OpKind.REMOVE_EMPTY_DIR and rop.made:
            try:
                self.repo.mark_missing_path(rop.dst)  # gone from disk: out of the index now
            except SQLAlchemyError as e:
                result.index_error = f"index update failed for {rop.dst}: {e}"
                return True
        if rop.kind is OpKind.UNLINK_SYMLINK and rop.expect_target is not None:
            try:
                self.repo.mark_missing_path(rop.src)  # the link is gone: out of the index now
            except SQLAlchemyError as e:
                result.index_error = f"index update failed for {rop.src}: {e}"
                return True
        if rop.kind is OpKind.PICTURE_BACK and rop.method != primitives.PICTURE_COPY:
            try:
                self.repo.mark_missing_path(rop.src)  # left the archive: out of the index now
            except SQLAlchemyError as e:
                result.index_error = f"index update failed for {rop.src}: {e}"
                return True
        if rop.kind is OpKind.COPY_ACROSS:
            try:
                self._repoint_copy(rop)
            except SQLAlchemyError as e:
                result.index_error = f"index update failed for {rop.dst}: {e}"
                return True
        if rop.kind in _RELOCATE:
            try:
                self.repo.update_path(rop.src, rop.dst)
                if rop.restore_row is not None:
                    self._restore_row(rop)
            except SQLAlchemyError as e:
                result.index_error = f"index update failed for {rop.dst}: {e}"
                return True
        return False

    def _repoint_copy(self, rop: ResolvedOp) -> None:
        """The file was copied across disks: its index row now describes the copy, so
        everything given to it (tags, notes, collections, items, locks) follows. The row
        takes the copy's own Drive id if it has one; a row with a Drive id gets a fresh
        local id otherwise, since the original (moved to To Delete next) keeps that id
        on disk and must not take the row back on the next scan."""
        rec = self.repo.by_path(rop.src)
        if rec is None:  # never indexed: the next scan finds the copy
            return
        new_id = read_drive_id(self.paths.abs(rop.dst))
        if new_id is None:
            local = rec.drive_id.startswith(LOCAL_ID_PREFIX)
            new_id = rec.drive_id if local else f"{LOCAL_ID_PREFIX}{uuid4()}"
        if new_id != rec.drive_id:
            self.repo.rekey(rec.drive_id, new_id)
        self.repo.update_path(rop.src, rop.dst)

    def _restore_row(self, rop: ResolvedOp) -> None:
        """Undo of a copy across disks: the copy went to To Delete (``rop.dst``), and the
        index row that followed it describes the original again, at its path and with its
        id. A row the scanner gave the original meanwhile (nothing can be attached to it:
        a file in To Delete is read-only) is dropped first, so the owner's row survives."""
        original, original_id = rop.restore_row
        rec = self.repo.by_path(rop.dst)
        if rec is None:
            return
        others = [r.drive_id for r in (self.repo.by_path(original),) if r is not None]
        if original_id is not None and self.repo.get(original_id) is not None:
            others.append(original_id)
        self.repo.drop_rows([d for d in dict.fromkeys(others) if d != rec.drive_id])
        self.repo.update_path(rop.dst, original)
        if original_id is not None and original_id != rec.drive_id:
            self.repo.rekey(rec.drive_id, original_id)

    def _record_made(self, batch_id: str, rop: ResolvedOp) -> None:
        """Remember which folder a New folder / layout batch made, so that undo removes
        only that folder and only while it is empty. If this fails the folder simply
        stays on undo (it cannot be proven to be the one made)."""
        try:
            ident = identity.of_path(self.paths.abs(rop.dst))
            with write_tx(self.engine) as conn:
                conn.execute(
                    insert(made_folders).values(
                        batch_id=batch_id,
                        rel=rop.dst,
                        **ident.columns(),
                        created=time.time(),
                    )
                )
        except (OSError, SQLAlchemyError):
            log.warning("could not record the folder made at %s", rop.dst, exc_info=True)

    def _stop(
        self,
        result: BatchResult,
        op_id: int,
        rop: ResolvedOp,
        state: str,
        error: str,
        undo_of: str | None = None,
    ) -> BatchResult:
        self._journal_finish(op_id, state, error, reverts=undo_of, rop=rop)
        result.failed, result.error = rop, error
        return result

    # --- journal -------------------------------------------------------------

    @staticmethod
    def _empty_snapshot() -> dict:
        return {
            "drive_id": None,
            "size": None,
            "mtime": None,
            "is_file": False,
            "link": None,
            "content_hash": None,
        }

    def _snapshot(self, rop: ResolvedOp) -> dict:
        """Size/mtime/drive_id of the source (the target, for SYMLINK) before acting.

        A missing source gives an empty snapshot (the pre-check then reports it); any
        other OSError propagates and fails the op.
        """
        snap = self._empty_snapshot()
        if rop.src is None:
            return snap
        if _outside_copy(rop):  # the file being copied in: only read
            st = os.stat(Path(rop.src[len(ABS_TARGET) :]))
            snap.update(size=st.st_size, mtime=st.st_mtime, is_file=stat.S_ISREG(st.st_mode))
            return snap
        if rop.kind is OpKind.PICTURE_TO_QUARANTINE:  # a link is not followed
            source = Path(rop.src[len(ABS_TARGET) :])
            st = os.lstat(source)
            snap.update(size=st.st_size, mtime=st.st_mtime, is_file=stat.S_ISREG(st.st_mode))
            snap["content_hash"] = primitives.file_sha256(source)  # journaled for undo/recovery
            return snap
        if rop.src.startswith(ABS_TARGET) and rop.kind is OpKind.SYMLINK:
            return snap  # a link target outside the archive: never looked at
        p = self.paths.abs(rop.src)
        try:
            st = os.lstat(p)
        except FileNotFoundError:
            return snap
        snap.update(
            drive_id=read_drive_id(p),
            size=st.st_size,
            mtime=st.st_mtime,
            is_file=stat.S_ISREG(st.st_mode),
            link=self._link_record(p) if stat.S_ISLNK(st.st_mode) else None,
        )
        if rop.kind in (OpKind.PICTURE_BACK, OpKind.COPY_ACROSS):
            snap["content_hash"] = primitives.file_sha256(p)
        if rop.kind is OpKind.COPY:  # the row describes the new file, not the original's id
            snap["drive_id"] = None
        return snap

    def _link_record(self, link: Path) -> str:
        """Where ``link`` points: archive-relative if inside the archive, else ``abs:<path>``."""
        target = os.path.normpath(os.path.join(link.parent, readlink(link)))
        try:
            return self.paths.rel(Path(target))
        except OutsideArchiveError:
            return ABS_TARGET + target

    def link_target(self, src: str) -> Path:
        """Absolute target for a SYMLINK ``src``: archive-relative or ``abs:<path>``."""
        if src.startswith(ABS_TARGET):
            return Path(src[len(ABS_TARGET) :])
        return self.paths.abs(src)

    def _journal_planned(
        self,
        batch_id: str,
        seq: int,
        rop: ResolvedOp,
        snap: dict,
        origin: str,
        undo_of: str | None,
        label: str | None = None,
    ) -> int:
        with write_tx(self.engine) as conn:
            res = conn.execute(
                insert(operations).values(
                    batch_id=batch_id,
                    seq=seq,
                    kind=str(rop.kind),
                    # a COPY keeps only the file's name: the path it was read from (an
                    # upload's temporary file) says nothing, and undo never needs it
                    src=Path(rop.src[len(ABS_TARGET) :]).name
                    if _outside_copy(rop) or rop.kind is OpKind.PICTURE_TO_QUARANTINE
                    else rop.src,
                    # UNLINK_SYMLINK: dst records the link's target so undo can recreate
                    # it: an archive-relative path if the target is inside the archive,
                    # otherwise "abs:" + the absolute path (see _link_record).
                    dst=self._journal_dst(rop, snap),
                    drive_id=snap["drive_id"],
                    size=snap["size"],
                    mtime=snap["mtime"],
                    is_file=snap["is_file"] if rop.src is not None else None,
                    state="planned",
                    origin=origin,
                    undo_of=undo_of,
                    label=label,
                    method=rop.method,
                    content_hash=snap["content_hash"],
                    created=time.time(),
                )
            )
            return res.inserted_primary_key[0]

    @staticmethod
    def _journal_dst(rop: ResolvedOp, snap: dict) -> str:
        if rop.kind is OpKind.UNLINK_SYMLINK:
            return snap["link"]
        if rop.kind is OpKind.PICTURE_BACK:  # the name in the areas folder, not its path
            return Path(rop.dst[len(ABS_TARGET) :]).name
        return rop.dst

    def _journal_finish(
        self,
        op_id: int,
        state: str,
        error: str | None = None,
        reverts: str | None = None,
        rop: ResolvedOp | None = None,
    ) -> None:
        """Record the outcome; for an undo op that acted (``done``/``unverified``;
        ``reverts`` = the undone batch), mark the original row it reverted ``undone``
        in the same transaction."""
        with write_tx(self.engine) as conn:
            conn.execute(
                update(operations)
                .where(operations.c.id == op_id)
                .values(state=state, error=error, finished=time.time())
            )
            if reverts is not None and state in _undo.ACTED:
                _undo.mark_reverted(conn, reverts, rop.kind, rop.src, rop.dst)

    # --- act -----------------------------------------------------------------

    def _is_case_variant(self, src, dst) -> bool:
        """``dst`` is the same entry as ``src``, spelled differently (case / NFC)."""
        if fold_parts(str(src)) != fold_parts(str(dst)):
            return False
        try:
            return os.path.samestat(os.lstat(src), os.lstat(dst))
        except OSError:
            return False

    def _areas(self) -> Path:
        if self.areas_dir is None:
            raise OpFailed("The rules' picture folder is not known here.")
        return Path(self.areas_dir)

    def _precheck_picture(self, rop: ResolvedOp) -> None:
        """PICTURE_TO_QUARANTINE / PICTURE_BACK, checked again right before acting."""
        areas = self._areas()
        if rop.kind is OpKind.PICTURE_TO_QUARANTINE:
            check_areas_source(Path(rop.src[len(ABS_TARGET) :]), areas)
            dst = self.paths.abs(rop.dst)
            if os.path.lexists(dst):
                raise OpFailed(f"{rop.dst} already exists.")
            if not dst.parent.is_dir() or dst.parent.is_symlink():
                raise OpFailed(f"The folder for {rop.dst} is missing.")
            return
        src = self.paths.abs(rop.src)
        target = Path(rop.dst[len(ABS_TARGET) :])
        if not os.path.lexists(src):
            raise OpFailed(f"{rop.src} is no longer there.")
        if not stat.S_ISREG(os.lstat(src).st_mode):
            raise OpFailed(f"{rop.src} is no longer a plain file.")
        if fold_parts(str(target.parent)) != fold_parts(str(areas)):
            raise OpFailed(f"{target.name} is not going into the rules' picture folder.")
        if os.path.lexists(target):
            raise OpFailed(f"{target.name} already exists in the rules' picture folder.")
        folder = os.lstat(areas)
        if stat.S_ISLNK(folder.st_mode) or not stat.S_ISDIR(folder.st_mode):
            raise OpFailed("The rules' picture folder is not a real folder.")

    def _precheck(self, rop: ResolvedOp) -> None:
        if rop.kind in _PICTURE_KINDS:
            self._precheck_picture(rop)
            return
        dst = self.paths.abs(rop.dst)
        if rop.kind is OpKind.MKDIR:
            if os.path.lexists(dst):
                raise OpFailed(f"{rop.dst} already exists.")
            return
        if rop.kind is OpKind.COPY:
            if os.path.lexists(dst):
                raise OpFailed(f"{rop.dst} already exists.")
            if not dst.parent.is_dir() or dst.parent.is_symlink():
                raise OpFailed(f"The folder for {rop.dst} is missing.")
            if _outside_copy(rop):
                if not Path(rop.src[len(ABS_TARGET) :]).is_file():
                    raise OpFailed(f"{Path(rop.src[len(ABS_TARGET) :]).name} is no longer there.")
                return
            origin = self.paths.abs(rop.src)  # a file already in the archive: a plain file
            try:
                st = os.lstat(origin)
            except OSError:
                raise OpFailed(f"{rop.src} is no longer there.") from None
            if not stat.S_ISREG(st.st_mode):
                raise OpFailed(f"{rop.src} is no longer a plain file.")
            if rop.drive_id is not None and read_drive_id(origin) != rop.drive_id:
                raise OpFailed(f"{rop.src} changed since the preview.")
            return
        if rop.kind is OpKind.COPY_ACROSS:
            self._precheck_copy_across(rop, dst)
            return
        if rop.kind is OpKind.SYMLINK and rop.src.startswith(ABS_TARGET):
            src = None  # target outside the archive: never looked at
        else:
            src = self.paths.abs(rop.src)
            if not os.path.lexists(src):
                raise OpFailed(f"{rop.src} is no longer there.")
        if rop.kind is OpKind.UNLINK_SYMLINK:
            if not src.is_symlink():
                raise OpFailed(f"{rop.src} is no longer a shortcut.")
            if rop.expect_target is not None and readlink(src) != str(
                self.link_target(rop.expect_target)
            ):
                raise OpFailed(f"{rop.src} points somewhere else now, so it is left alone.")
            return
        if rop.kind is OpKind.REMOVE_EMPTY_DIR:
            if src.is_symlink() or not src.is_dir():
                raise OpFailed(f"{rop.src} is no longer a folder.")
            if rop.drive_id is not None and read_drive_id(src) != rop.drive_id:
                raise OpFailed(f"{rop.src} changed since the preview.")
            return  # emptiness is re-checked by the primitive itself
        if rop.kind in _RELOCATE and rop.drive_id is not None:
            if read_drive_id(src) != rop.drive_id:
                raise OpFailed(f"{rop.src} changed since the preview.")
        if os.path.lexists(dst) and not (rop.kind in _RELOCATE and self._is_case_variant(src, dst)):
            raise OpFailed(f"{rop.dst} already exists.")
        # CHECK-THEN-ACT WINDOW: ancestors are re-checked here (abs() refuses escapes,
        # the parent must be a real folder) but could still be swapped for a symlink
        # before the rename; RENAME_EXCL still guarantees nothing is overwritten.
        if not dst.parent.is_dir() or dst.parent.is_symlink():
            raise OpFailed(f"The folder for {rop.dst} is missing.")

    def _precheck_copy_across(self, rop: ResolvedOp, dst: Path) -> None:
        src = self.paths.abs(rop.src)
        try:
            st = os.lstat(src)
        except OSError:
            raise OpFailed(f"{rop.src} is no longer there.") from None
        if not stat.S_ISREG(st.st_mode):
            raise OpFailed(f"{rop.src} is no longer a plain file.")
        if rop.drive_id is not None and read_drive_id(src) != rop.drive_id:
            raise OpFailed(f"{rop.src} changed since the preview.")
        if os.path.lexists(dst):
            raise OpFailed(f"{rop.dst} already exists.")
        if not dst.parent.is_dir() or dst.parent.is_symlink():
            raise OpFailed(f"The folder for {rop.dst} is missing.")

    def _act(self, rop: ResolvedOp) -> None:
        if rop.kind is OpKind.PICTURE_TO_QUARANTINE:
            source, dst = Path(rop.src[len(ABS_TARGET) :]), self.paths.abs(rop.dst)
            if rop.method == primitives.PICTURE_COPY:
                self._copy_picture_out(source, dst, rop.content_hash)
            else:
                primitives.move_between_folders(source, dst)
            return
        if rop.kind is OpKind.PICTURE_BACK:
            source, target = self.paths.abs(rop.src), Path(rop.dst[len(ABS_TARGET) :])
            if rop.method == primitives.PICTURE_COPY:
                # undo never removes an archive file: the copy in the quarantine folder stays
                primitives.copy_picture(source, target, rop.content_hash)
            else:
                primitives.move_between_folders(source, target)
            return
        dst = self.paths.abs(rop.dst)
        match rop.kind:
            case OpKind.MKDIR:
                primitives.make_dir(dst)
            case OpKind.SYMLINK:
                primitives.make_symlink(self.link_target(rop.src), dst)
            case OpKind.UNLINK_SYMLINK:
                primitives.unlink_symlink(
                    dst,
                    self._removal_root(rop.dst, undo_link=rop.expect_target is not None),
                    expected_target=None
                    if rop.expect_target is None
                    else str(self.link_target(rop.expect_target)),
                )
            case OpKind.REMOVE_EMPTY_DIR:
                primitives.remove_empty_dir(
                    dst, self._removal_root(rop.dst, rop.made), identity=rop.identity
                )
            case OpKind.COPY_ACROSS:
                primitives.copy_across(
                    self.paths.abs(rop.src), dst, rop.content_hash, stop=self.cancel_copies.is_set
                )
            case OpKind.COPY:
                if _outside_copy(rop):
                    primitives.copy_file(Path(rop.src[len(ABS_TARGET) :]), dst)
                else:
                    primitives.copy_file(self.paths.abs(rop.src), dst)
            case _:
                src = self.paths.abs(rop.src)
                if self._is_case_variant(src, dst):
                    # Same entry on a case-insensitive volume: RENAME_EXCL would say EEXIST.
                    primitives.rename_case_only(src, dst)
                else:
                    primitives.rename_excl(src, dst)

    def _copy_picture_out(self, source: Path, dst: Path, sha256: str) -> None:
        """A rule picture to the archive across disks: copy and verify it (size and hash);
        only then remove dam's own file. Whatever fails, the copy stays and so does the
        original (unless it was removed), and the error says which."""
        try:
            primitives.copy_picture(source, dst, sha256)
        except (OSError, OpFailed) as e:
            raise OpFailed(f"{e} The original stays in the rules' picture folder.") from None
        try:
            primitives.remove_moved_picture(source, self._areas(), dst, sha256)
        except (OSError, OpFailed, GuardError) as e:
            raise OpFailed(
                f"{source.name} was copied to {dst.name} in To Delete and the copy checks out,"
                f" but the original in the rules' picture folder was not removed ({e})."
                " Both files exist."
            ) from None

    def _verify(self, rop: ResolvedOp, snap: dict) -> None:
        if rop.kind in _PICTURE_KINDS:
            moved_to = (
                Path(rop.dst[len(ABS_TARGET) :])
                if rop.kind is OpKind.PICTURE_BACK
                else self.paths.abs(rop.dst)
            )
            st = os.lstat(moved_to)
            source_left = (
                rop.kind is OpKind.PICTURE_TO_QUARANTINE
                and rop.method == primitives.PICTURE_COPY
                and os.path.lexists(Path(rop.src[len(ABS_TARGET) :]))
            )
            if source_left or not (stat.S_ISREG(st.st_mode) and st.st_size == snap["size"]):
                raise OpFailed(f"Could not confirm that {rop.src} was moved to {rop.dst}.")
            return
        dst = self.paths.abs(rop.dst)
        match rop.kind:
            case OpKind.MKDIR:
                ok = dst.is_dir() and not dst.is_symlink()
            case OpKind.SYMLINK:
                ok = dst.is_symlink() and readlink(dst) == str(self.link_target(rop.src))
            case OpKind.UNLINK_SYMLINK | OpKind.REMOVE_EMPTY_DIR:
                ok = not os.path.lexists(dst)
            case OpKind.COPY:
                st = os.lstat(dst)
                ok = stat.S_ISREG(st.st_mode) and st.st_size == snap["size"]
            case OpKind.COPY_ACROSS:
                st = os.lstat(dst)
                ok = (
                    stat.S_ISREG(st.st_mode)
                    and st.st_size == snap["size"]
                    and primitives.file_sha256(dst) == snap["content_hash"]
                    and os.path.lexists(self.paths.abs(rop.src))
                )
            case _:
                ok = os.path.lexists(dst)
                if ok and snap["drive_id"] is not None:
                    ok = read_drive_id(dst) == snap["drive_id"]
                if ok and snap["is_file"]:
                    ok = os.lstat(dst).st_size == snap["size"]
        if not ok:
            raise OpFailed(f"Could not confirm that {rop.src} was changed to {rop.dst}.")
