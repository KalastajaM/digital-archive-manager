"""Paths the app itself just moved, so the watcher does not scan them again.

The executor indexes a relocation (rename, move, To Delete, the final rename of a copy
across disks) itself with ``FileRepo.update_path``. The filesystem events that follow are
only the echo of that change: the watcher drops them while they are fresh. Everything the
executor leaves to a scan (new folders, copies, links) is never registered here.
"""

import threading
import time
from collections.abc import Callable, Iterable
from pathlib import PurePosixPath

from dam.core.paths import nfc

OWN_CHANGE_TTL_S = 10.0  # how long after the op the echo of its events is expected


def _parent(key: str) -> str:
    parent = PurePosixPath(key).parent.as_posix()
    return "" if parent == "." else parent


class OwnChanges:
    """Thread safe: the executor adds, the watcher's threads ask."""

    def __init__(
        self, ttl_s: float = OWN_CHANGE_TTL_S, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.ttl_s = ttl_s
        self._clock = clock
        self._lock = threading.Lock()
        self._paths: dict[str, tuple[float, bool]] = {}  # path -> (expiry, a folder)
        self._parents: dict[str, float] = {}  # folder whose listing changed -> expiry

    def add(self, rels: Iterable[str], tree: bool = False) -> None:
        """Register ``rels`` (archive-relative) as just changed by the app; ``tree``: they
        are folders, so everything below them is covered too (a moved folder's rows were
        re-pathed with it)."""
        now = self._clock()
        expiry = now + self.ttl_s
        with self._lock:
            self._paths = {k: v for k, v in self._paths.items() if v[0] > now}
            self._parents = {k: v for k, v in self._parents.items() if v > now}
            for rel in rels:
                key = nfc(rel).strip("/")
                if not key:
                    continue
                self._paths[key] = (expiry, tree)
                self._parents[_parent(key)] = expiry

    def covers(self, rel: str, dir_modified: bool = False) -> bool:
        """An event at ``rel`` is the echo of an own change: ``rel`` is a registered path
        or lies below a registered folder, or (``dir_modified``: the event only says the
        folder's listing changed) ``rel`` is the folder a registered path is in."""
        key = nfc(rel).strip("/")
        now = self._clock()
        with self._lock:
            hit = self._paths.get(key)
            if hit is not None and hit[0] > now:
                return True
            for parent in PurePosixPath(key).parents:
                above = self._paths.get(parent.as_posix())
                if above is not None and above[1] and above[0] > now:
                    return True
            if dir_modified:
                expiry = self._parents.get(key)
                if expiry is not None and expiry > now:
                    return True
        return False
