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
    PICTURE_TO_QUARANTINE = auto()
    PICTURE_BACK = auto()
    COPY_ACROSS = auto()


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
    PICTURE_TO_QUARANTINE: ``src`` is ``"abs:<file>"``, a regular file (no link) directly
    inside the rules' ``areas`` folder (the executor is told where that is; without it the
    op is refused), ``dst`` the quarantine folder itself and ``name`` the file name there
    (a taken name gets ``_N``, nothing is overwritten). On one disk the file is
    renamed. On different disks it is copied (exclusively, verified by size and hash) and
    only then removed from the areas folder (dam's own settings, not the archive).
    PICTURE_BACK (undo of the above, restore only): ``src`` the file in the quarantine
    folder, ``dst`` its plain name in the ``areas`` folder; ``exact``: refused when that
    name is taken. On different disks it is copied back and the copy in the quarantine
    folder stays.
    ``made`` (REMOVE_EMPTY_DIR only, set only by undo): the folder was made by a
    user-confirmed "New folder" / layout batch (``Plan.new_folders``); it is removed
    again only while it is still the folder with the journaled ``identity`` and empty,
    anywhere in the archive (top level included).
    COPY may also name a file already in the archive (``src`` an archive path, not
    ``abs:``): it is copied into an ordinary folder (``dst``) under ``name`` (default the
    file's own name); undo moves the copy to the quarantine folder.
    UNLINK_SYMLINK outside ``##. Ongoing`` / ``##. Important`` is only an undo's
    (``restore`` and ``exact``): ``dst`` is then the target the app made the link with,
    and the link is removed only while it is still a symbolic link pointing there.
    ``name`` (MOVE and COPY): move *and* rename in one op, landing at ``dst/name``.
    COPY_ACROSS is never requested: the planner makes it from a MOVE of a file between
    archive folders on different disks in a ``Plan.copy_across`` plan (``ResolvedOp``).
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
    # With ``new_folders`` only (the user-confirmed "Create the filing code folders"):
    # an MKDIR may also make a folder directly inside the inbox (its parent is exactly
    # the inbox), nothing deeper and nothing in the other special folders.
    inbox_folders: bool = False
    # A move the owner asked for by hand (Browse, Restore): a MOVE of a file between
    # archive folders on different disks becomes COPY_ACROSS (a verified copy) followed
    # by a QUARANTINE of the original in its own folder. Without it such a move is
    # refused, and undo plans never set it (an undo is renames only).
    copy_across: bool = False


@dataclass
class ResolvedOp:
    """An operation with its final archive-relative destination (collisions resolved).

    For UNLINK_SYMLINK, ``dst`` is the link path itself (the journal row stores the
    link's target in ``dst`` instead, so the link can be recreated). For
    PICTURE_TO_QUARANTINE, ``src`` is ``"abs:<file>"``; for PICTURE_BACK, ``dst`` is
    ``"abs:<file>"`` (the journal keeps only the plain names). For
    REMOVE_EMPTY_DIR, ``dst`` is the removed folder itself (as is the journal's), and
    ``identity`` the identity it must still have at act time (if given). For
    COPY_ACROSS, ``src`` is the file and ``dst`` the copy's path in the other folder.
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
    # PICTURE_TO_QUARANTINE / PICTURE_BACK: "rename" (one disk) or "copy" (two disks), as
    # decided when planned
    method: str | None = None
    # the sha256 of that picture, read and journaled just before acting (set by the executor)
    content_hash: str | None = None
    # UNLINK_SYMLINK of an undo: the target (journal form, archive-relative or ``abs:``) the
    # app made the link with; the link is removed only while it still points there
    expect_target: str | None = None
    # COPY_ACROSS: the file's size, and whether it is in the cloud only (downloaded first)
    size: int | None = None
    cloud_only: bool = False
    # QUARANTINE of a copy, by the undo of a COPY_ACROSS: (the original's path, its
    # drive id); the index row goes back to describing the original
    restore_row: tuple[str, str | None] | None = None


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
    # ended early on request (``should_stop``): what is in ``done`` happened, the rest not
    stopped: bool = False
    # a move across disks started in the background (``dam.ops.jobs``): this result is
    # empty, and the job's result is the batch
    job_id: str | None = None
