"""What a link (symlink) in the archive stands for: its target's index record.

A link is followed to its end (a chain of links resolved fully). It stands for its
target only when the end is inside the archive root and indexed as a live record
that is not itself a link; anything else (outside, missing, a loop, not indexed) has
no target. Previews and Open then act on the target, through the same checks as for
the target itself.

The disk may be case-insensitive, so a link can spell its target (or the archive
root) in another case. Containment is decided by file identity (``st_dev`` and
``st_ino`` of the root among the end's parents), and a path that misses the index is
looked up up to case and accepted only when it is the same file on disk (samestat).
Only ``stat`` is used: nothing is opened (that could start a cloud download).
"""

import os
from pathlib import Path

from dam.core.fs import resolve
from dam.core.paths import ArchivePaths, OutsideArchiveError
from dam.index.repo import FileRecord, FileRepo

NO_LINK_PREVIEW = "No preview (the link points outside the archive or to nothing)"


def _rel_inside(root: Path, real: Path) -> str | None:
    """``real`` relative to the archive root found among its parents by identity, or
    None when the root is not one of them (or something cannot be stat'ed)."""
    try:
        root_st = os.stat(root)
    except OSError:
        return None
    for parent in real.parents:
        try:
            st = os.stat(parent)
        except OSError:
            return None
        if (st.st_dev, st.st_ino) == (root_st.st_dev, root_st.st_ino):
            return real.relative_to(parent).as_posix()
    return None


def _rel_in_folders(paths: ArchivePaths, real: Path) -> str | None:
    """``real`` as an archive path, found in whichever folder (main or extra) holds it."""
    for folder in paths.folders:
        inner = _rel_inside(folder.root, real)
        if inner:
            return f"{folder.label}/{inner}" if folder.label else inner
    return None


def _same_file(paths: ArchivePaths, real_st: os.stat_result, rec: FileRecord) -> bool:
    try:
        return os.path.samestat(real_st, os.stat(paths.abs(rec.path)))
    except (OSError, OutsideArchiveError):
        return False


def link_target(paths: ArchivePaths, repo: FileRepo, rec: FileRecord) -> FileRecord | None:
    """The live record ``rec`` (a link) resolves to inside the archive, else None."""
    if not rec.is_link:
        return None
    try:
        real = resolve(paths.abs(rec.path), strict=True)
        real_st = os.stat(real)
    except (OSError, RuntimeError, OutsideArchiveError):
        return None  # missing, a loop, or a stored path that is not the archive's
    rel = _rel_in_folders(paths, real)
    if not rel:
        return None
    target = repo.by_path(rel)
    if target is None:  # spelled in another case than the index has it?
        target = next((c for c in repo.by_folded_path(rel) if _same_file(paths, real_st, c)), None)
    if target is None or target.missing or target.parked_at is not None or target.is_link:
        return None
    return target
