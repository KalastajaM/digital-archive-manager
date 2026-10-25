"""Locks: a safety catch against changes to a file on disk.

A locked file can be viewed and described (tags, notes, marks, trays) but the operation
layer refuses to rename, move or quarantine it (``dam.ops.planner``). Two kinds:

* ``important``: a file marked ! Important (or inside a marked folder). Always locked,
  needs no stored row, and can only be unlocked for now.
* ``file``: a lock the owner put on a file, a row in ``file_locks`` keyed by drive id (it
  survives moves and renames). It can be unlocked for now or for good.

"For now" is a *grant*: a random token held in this process's memory only and sent back by
the page in the ``X-Dam-Unlock`` header. The planner accepts a locked file only when a
live grant for it is among the request's tokens. Grants are never stored, so a restart or
a crash leaves every file locked, and one unused for ``IDLE_SECONDS`` expires. This is a
catch against mistakes, not a password.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy import Engine, delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from dam.core.paths import nfc
from dam.db.engine import write_tx
from dam.db.tables import file_locks, files

IMPORTANT = "important"
LOCKED = "file"
IDLE_SECONDS = 15 * 60  # a grant not used for this long expires
UNLOCK_HEADER = "x-dam-unlock"  # the page's tokens, comma separated
LOCKED_MESSAGE = "This file is locked. Unlock it to change it."
IMPORTANT_FOR_NOW = "An Important file can only be unlocked for now."

# the unlock tokens of the request being served (set by the API middleware; tests use
# ``with_tokens``)
_TOKENS: ContextVar[tuple[str, ...]] = ContextVar("dam_unlock_tokens", default=())


def request_tokens() -> tuple[str, ...]:
    return _TOKENS.get()


def parse_tokens(header: str | None) -> tuple[str, ...]:
    """The tokens of an ``X-Dam-Unlock`` header value (at most 50, each at most 100 chars)."""
    if not header:
        return ()
    parts = [p.strip() for p in header.split(",")]
    return tuple(p for p in parts if p and len(p) <= 100)[:50]


@contextmanager
def with_tokens(tokens: Iterable[str]) -> Iterator[None]:
    """Run the block as a request that carries these unlock tokens."""
    reset = _TOKENS.set(tuple(tokens))
    try:
        yield
    finally:
        _TOKENS.reset(reset)


@dataclass(frozen=True)
class Locked:
    drive_id: str
    path: str  # NFC, archive relative
    is_dir: bool
    reason: str  # IMPORTANT | LOCKED


def _under(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder + "/")


class LockService:
    def __init__(
        self,
        engine: Engine,
        important: Callable[[], list[tuple[str, str, bool]]],
        clock: Callable[[], float] = time.monotonic,
        idle_seconds: float = IDLE_SECONDS,
    ) -> None:
        self.engine = engine
        self._important = important  # MarkService.important_paths
        self._clock = clock
        self.idle_seconds = idle_seconds
        self._grants: dict[str, tuple[str, float]] = {}  # token -> (drive_id, last used)
        self._mutex = threading.Lock()

    # -- what is locked --------------------------------------------------------

    def stored(self) -> set[str]:
        """The drive ids with a stored (ordinary) lock, live or not."""
        with self.engine.connect() as conn:
            return set(conn.execute(select(file_locks.c.drive_id)).scalars())

    def entries(self) -> list[Locked]:
        """Every locked entry with a live row: Important ones (``important_paths``, a
        folder locks everything under it) and ordinary locked files."""
        out = [Locked(d, nfc(p), bool(is_dir), IMPORTANT) for d, p, is_dir in self._important()]
        seen = {e.drive_id for e in out}
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(files.c.drive_id, files.c.path_nfc, files.c.is_dir)
                .select_from(file_locks.join(files, files.c.drive_id == file_locks.c.drive_id))
                .where(files.c.missing.is_not(True), files.c.parked_at.is_(None))
            ).all()
        for r in rows:
            if r.drive_id not in seen:
                out.append(Locked(r.drive_id, nfc(r.path_nfc), bool(r.is_dir), LOCKED))
        return out

    def reason(self, drive_id: str, path_nfc: str) -> str | None:
        """Why the entry is locked: ``important`` (marked, or inside a marked folder),
        ``file`` (a stored lock) or None."""
        path = nfc(path_nfc).casefold()
        for e in self._important():
            if e[0] == drive_id or (e[2] and _under(path, nfc(e[1]).casefold())):
                return IMPORTANT
        return LOCKED if drive_id in self.stored() else None

    # -- the owner's lock ------------------------------------------------------

    def lock(self, drive_id: str) -> None:
        """Put a stored lock on the file and drop any grants for it."""
        with write_tx(self.engine) as conn:
            conn.execute(
                sqlite_insert(file_locks)
                .values(drive_id=drive_id, locked_at=time.time())
                .on_conflict_do_nothing()
            )
        self.release(drive_id)

    def unlock_for_good(self, drive_id: str) -> None:
        """Remove the stored lock (the caller has refused an Important file)."""
        with write_tx(self.engine) as conn:
            conn.execute(delete(file_locks).where(file_locks.c.drive_id == drive_id))
        self.release(drive_id)

    # -- grants (unlock for now) -----------------------------------------------

    def _expire(self, now: float) -> None:
        stale = [t for t, (_, used) in self._grants.items() if now - used > self.idle_seconds]
        for t in stale:
            del self._grants[t]

    def grant(self, drive_id: str) -> str:
        """A new token that unlocks ``drive_id`` for requests carrying it."""
        token = secrets.token_urlsafe(24)
        with self._mutex:
            now = self._clock()
            self._expire(now)
            self._grants[token] = (drive_id, now)
        return token

    def release(self, drive_id: str) -> int:
        """Drop every grant for the file (the owner left it); how many there were."""
        with self._mutex:
            gone = [t for t, (d, _) in self._grants.items() if d == drive_id]
            for t in gone:
                del self._grants[t]
        return len(gone)

    def granted(self, tokens: Iterable[str]) -> set[str]:
        """The drive ids unlocked by the live ones among ``tokens``; each use renews its
        grant. Unknown and expired tokens are ignored."""
        found: set[str] = set()
        with self._mutex:
            now = self._clock()
            self._expire(now)
            for t in tokens:
                grant = self._grants.get(t)
                if grant is not None:
                    self._grants[t] = (grant[0], now)
                    found.add(grant[0])
        return found

    def active(self, drive_id: str) -> bool:
        """Some live grant exists for the file (does not renew it)."""
        with self._mutex:
            self._expire(self._clock())
            return any(d == drive_id for d, _ in self._grants.values())

    # -- the check the planner makes -------------------------------------------

    def refused(
        self,
        rel: str,
        drive_id: str | None,
        entries: list[Locked],
        granted: set[str],
    ) -> bool:
        """True when changing the entry at ``rel`` (NFC path as on disk) would change a
        locked file that no grant covers: the entry itself, a folder holding it, or
        (for a folder) a locked entry inside it. A grant for the entry's own drive id
        covers it and the locked folders above it; a locked entry inside a moved folder
        needs a grant of its own."""
        rel = nfc(rel).casefold()  # the archive's file system ignores case
        for e in entries:
            path = e.path.casefold()
            own = drive_id is not None and e.drive_id == drive_id
            above = e.is_dir and _under(rel, path)
            below = _under(path, rel)
            if not (own or above or below):
                continue
            if e.drive_id in granted:
                continue
            if drive_id is not None and drive_id in granted and (own or above):
                continue
            return True
        return False
