"""Realistic "the user deleted it and put another in its place" for the tests.

Linux file systems hand a freed inode number to the next file created, and stamp
timestamps from a clock that ticks only every few milliseconds, so a delete followed
at once by a create can produce an object with exactly the same identity. A person
needs far longer than that between the two steps; ``recreate_*`` waits until the new
object's identity differs from the old one's (a few ms at most) before returning.
"""

import os
import time
from pathlib import Path

from dam.ops import identity

_TRIES = 500


def _until_different(path: Path, old: identity.Identity, make) -> None:
    for _ in range(_TRIES):
        make()
        if identity.of_path(path) != old:
            return
        os.unlink(path) if path.is_symlink() else os.rmdir(path)
        time.sleep(0.005)
    raise AssertionError(f"could not make {path} look different from what it replaced")


def recreate_dir(path: Path) -> None:
    """Remove the empty folder ``path`` and make a new, empty one at the same path."""
    old = identity.of_path(path)
    os.rmdir(path)
    _until_different(path, old, path.mkdir)


def recreate_link(path: Path, target) -> None:
    """Remove the link ``path`` and make a new link, to ``target``, at the same path."""
    old = identity.of_path(path)
    os.unlink(path)
    _until_different(path, old, lambda: os.symlink(target, path))
