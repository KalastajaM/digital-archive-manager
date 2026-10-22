"""Operation data model."""

from dataclasses import dataclass, field
from enum import StrEnum, auto

from dam.ops.identity import Identity


class OpKind(StrEnum):
    RENAME = auto()
    MOVE = auto()
    MKDIR = auto()
    SYMLINK = auto()
    UNLINK_SYMLINK = auto()
    QUARANTINE = auto()
    REMOVE_EMPTY_DIR = auto()
    COPY = auto()


class GuardError(ValueError):
    """An operation is not allowed (safety guard)."""


class OpFailed(RuntimeError):
    """An operation could not be carried out or verified."""


@dataclass(frozen=True)
class Op:
    """One requested operation.

    RENAME: ``dst`` is the new name (same folder). MOVE: ``dst`` is the destination
    folder (name kept). MKDIR: ``dst`` is the folder. SYMLINK: ``src`` is the target,
    ``dst`` the link. UNLINK_SYMLINK: ``src`` is the link. QUARANTINE: ``dst`` ignored.
    REMOVE_EMPTY_DIR: ``src`` is a folder inside Ongoing (at any depth, never Ongoing
    itself) that holds nothing but a ``.DS_Store`` file (deleted first); ``dst``,
    ``name``, ``exact`` and ``allow_top_level`` must stay unset. ``identity`` (this
    kind only): the identity (``dam.ops.identity``) the folder must still have when it is
    removed, so a folder swapped in since it was planned is refused.
    COPY: ``src`` is ``"abs:<file>"`` (a regular file anywhere on this computer, only
    read), ``dst`` the archive folder it is copied into (the inbox, nowhere else) and
    ``name`` the file name there; a taken name gets ``_N``, nothing is overwritten.
    ``made`` (REMOVE_EMPTY_DIR only, set only by undo): the folder was made by a
    user-confirmed "New folder" / layout batch (``Plan.new_folders``); it is removed
    again only while it is still the folder with the journaled ``identity`` and empty,
    anywhere in the archive (top level included).
    ``name`` (MOVE and COPY): move *and* rename in one op, landing at ``dst/name``.
    ``exact`` (used by undo, which restores entries to where they were): the final
    path must be free, so a collision is a ``GuardError`` instead of a ``_N`` suffix.
    With ``exact``, a SYMLINK target may also be the journal's ``"abs:<path>"`` form
    (a link that pointed outside the archive is recreated as it was).
    """

    kind: OpKind
    src: str | None
    dst: str | None
    allow_top_level: bool = False
    name: str | None = None
    exact: bool = False
    identity: Identity | None = None
    made: bool = False


ABS_TARGET = "abs:"  # journal prefix for a link target outside the archive
UNDO_ORIGIN = "undo"  # Plan.origin of undo batches; reserved (apply/preview refuse it)


@dataclass
class Plan:
    ops: list[Op]
    origin: str  # "cli" | "ui" | "workflow" | "undo"
    # What the user did, as a sentence ("Filed X into 80. Misc"); journaled on every row
    # of the batch for Activity. None: Activity derives a title from the ops.
    label: str | None = None
    # The "New folder" / "Create the archive layout" workflows only (user-confirmed, never
    # automatic): the plan may hold nothing but MKDIR ops, which may then create
    # top-level folders; each created folder is recorded (with its identity) so that
    # undo can remove it again while it is still empty. Filing suggestions, rules and
    # syncs never set it, and without it a top-level folder is never created.
    new_folders: bool = False


@dataclass
class ResolvedOp:
    """An operation with its final archive-relative destination (collisions resolved).

    For UNLINK_SYMLINK, ``dst`` is the link path itself (the journal row stores the
    link's target in ``dst`` instead, so the link can be recreated). For
    REMOVE_EMPTY_DIR, ``dst`` is the removed folder itself (as is the journal's), and
    ``identity`` the identity it must still have at act time (if given).
    """

    kind: OpKind
    src: str | None
    dst: str
    drive_id: str | None = None
    note: str | None = None
    identity: Identity | None = None
    # MKDIR: made by a ``Plan.new_folders`` batch (its identity is recorded after the
    # act). REMOVE_EMPTY_DIR: removing such a folder (undo only).
    made: bool = False


@dataclass
class BatchResult:
    batch_id: str
    dry_run: bool
    done: list[ResolvedOp] = field(default_factory=list)
    failed: ResolvedOp | None = None
    error: str | None = None
    # The last op in ``done`` completed (journaled done) but updating the file index
    # failed; the batch stopped there. The next scan repairs the index.
    index_error: str | None = None
    # undo of a batch that made folders: the ones left alone because something was put
    # in them since (or they were swapped); everything else was removed
    kept: list[str] = field(default_factory=list)
