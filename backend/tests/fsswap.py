"""Realistic "the user deleted it and put another in its place" for the tests.

The app accepts an entry as its own when ``dev`` and ``ino`` match (the birth time is
not compared; see ``dam.ops.identity.same_object``), so a replacement must have a new
inode number. Linux file systems hand a freed inode number straight to the next file
created, so ``recreate_*`` makes the new object while the old one still exists (it
cannot share the old one's inode), then removes the old one and renames the new one
into its place.
"""

import os
from pathlib import Path


def _swap_name(path: Path) -> Path:
    return path.with_name(path.name + ".swap")


def recreate_dir(path: Path) -> None:
    """Replace the empty folder ``path`` with a new, empty one at the same path."""
    new = _swap_name(path)
    new.mkdir()
    os.rmdir(path)
    os.rename(new, path)


def recreate_link(path: Path, target) -> None:
    """Replace the link ``path`` with a new link, to ``target``, at the same path."""
    new = _swap_name(path)
    os.symlink(target, new)
    os.unlink(path)
    os.rename(new, path)
