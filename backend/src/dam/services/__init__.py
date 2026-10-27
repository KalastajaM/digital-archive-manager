"""Services between the interfaces (CLI, HTTP API) and the engine.

Interfaces hold no business logic: they only call these services. Services only
build ``Plan``s; the executor is the only code that changes the archive.
"""

import os
import stat
from typing import TYPE_CHECKING

from dam.core.paths import ArchivePaths
from dam.errors import InvalidRequest
from dam.index.driveid import LOCAL_ID_PREFIX
from dam.ops.guards import is_under
from dam.ops.model import OpKind, ResolvedOp

if TYPE_CHECKING:
    from dam.index.repo import FileRepo

ORIGINS = frozenset({"ui", "cli", "workflow"})


def check_origin(origin: str) -> str:
    """Return ``origin`` if callers may use it (``"undo"`` is reserved for the executor)."""
    if origin not in ORIGINS:
        raise InvalidRequest(f"invalid origin {origin!r}; expected one of {sorted(ORIGINS)}")
    return origin


_RELOCATIONS = (OpKind.RENAME, OpKind.MOVE, OpKind.COPY_ACROSS)  # a copy across: the file


def check_destination_area(dest: str, paths: ArchivePaths) -> None:
    """Refuse (``InvalidRequest``) a move or filing destination at or under a
    quarantine (any folder's ``##. To Delete``) or ``##. Ongoing``: nothing is ever
    moved into either, whichever way it is asked for (Browse's Move to…, Edit details,
    inbox filing, ``dam file``). The quarantine is only reached through
    ``BrowseService.quarantine``, which is where the ! Important protection is checked,
    so this is also what keeps a marked file from being filed into ``##. To Delete``."""
    for area in (*paths.quarantines, paths.ongoing):
        if is_under(dest, area):
            raise InvalidRequest(f"Files cannot be moved into {area}.")


def _twin_of_another(repo: "FileRepo", rop: ResolvedOp) -> bool:
    """The Drive id on disk belongs to another indexed file, elsewhere: the copied xattr
    of a twin, which the scanner indexed under a local id."""
    owner = repo.get(rop.drive_id) if rop.drive_id else None
    return owner is not None and not owner.missing and owner.path != rop.src


def check_disk_identity(
    paths: ArchivePaths,
    repo: "FileRepo",
    ids: list[str],
    resolved: list[ResolvedOp],
    kinds: tuple[OpKind, ...] = _RELOCATIONS,
) -> None:
    """Refuse (``InvalidRequest``) unless each RENAME/MOVE in ``resolved`` (``kinds``:
    or a SYMLINK / COPY of a drop, whose source is the file asked for) is the file
    asked for. ``ids`` holds the requested drive id of each such op, in plan order.

    - A Drive id: the id the planner read from the disk must equal it.
    - A ``local:`` id (the scanner's, for a file without a Drive id xattr, e.g. one
      Drive has not uploaded yet): the disk must still carry no Drive id (one that now
      does is a different or replaced file), or only the Drive id of another indexed
      file (a copy carries its original's xattr; the scanner treats such a twin as
      id-less too), and, when the index has its size, the disk size must equal it (a
      weak signal, but the only one there is).
    - Always: the source is a regular file on disk (lstat: not a folder, not a link), or
      a folder on disk when the indexed row is a folder.

    A folder moved across disks is many ops (made folders, a copy per file); the op
    checked for it is its final QUARANTINE (the one carrying the planned ``tree``), whose
    source is the folder itself.

    Catches a stale index (the file was replaced since the last scan). Pass it as
    ``Executor.apply(check=...)`` so the ops checked are the ops run."""
    folder_copies = [r for r in resolved if r.kind is OpKind.QUARANTINE and r.tree is not None]
    relocations = folder_copies or [r for r in resolved if r.kind in kinds]
    if len(relocations) != len(ids):
        raise InvalidRequest("The files have changed since this was planned. Scan and try again.")
    for drive_id, rop in zip(ids, relocations, strict=True):
        local = drive_id.startswith(LOCAL_ID_PREFIX)
        if local and rop.drive_id is not None and not _twin_of_another(repo, rop):
            raise InvalidRequest(
                f"{rop.src} now has Drive id {rop.drive_id!r}, so it is not the file indexed"
                " there (no Drive id); scan and try again"
            )
        if not local and rop.drive_id != drive_id:
            raise InvalidRequest(
                f"{rop.src} is no longer the file {drive_id!r} on disk; scan and try again"
            )
        try:
            st = os.lstat(paths.abs(rop.src))
        except OSError:
            raise InvalidRequest(f"{rop.src} cannot be read; scan and try again") from None
        rec = repo.get(drive_id)
        is_folder = rec is not None and rec.is_dir
        if is_folder:
            if not stat.S_ISDIR(st.st_mode):
                raise InvalidRequest(f"{rop.src} is not a folder on disk; scan and try again")
            continue  # a folder has no size to compare; its identity was checked above
        if not stat.S_ISREG(st.st_mode):
            raise InvalidRequest(f"{rop.src} is not a file on disk; scan and try again")
        if local:
            rec = repo.get(drive_id)
            if rec is not None and rec.size is not None and rec.size != st.st_size:
                raise InvalidRequest(
                    f"{rop.src} has changed since the last scan (its size differs);"
                    " scan and try again"
                )
