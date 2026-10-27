"""A counter that moves on whenever this process writes to some tables: a cache of
answers read from those tables keeps an answer only while the counter has not moved.

It counts at two moments: when a writing statement runs, and when its connection goes
back to the pool (after the commit or rollback). A reader that took the value before
the write, or between the write and its commit, reads it again afterwards, so an answer
read from the old rows is never kept under the new value. Writes from another process
are not seen; the profile lock (``dam.profiles``) keeps other dam processes from
changing an archive while it is open."""

import re
import threading
from collections.abc import Iterable

from sqlalchemy import Engine, event

_WRITE = re.compile(r"\b(INSERT|UPDATE|DELETE|REPLACE|DROP|ALTER|CREATE)\b", re.IGNORECASE)


class WriteGeneration:
    def __init__(self, engine: Engine, tables: Iterable[str]) -> None:
        names = "|".join(re.escape(t) for t in tables)
        self._tables = re.compile(rf"\b({names})\b", re.IGNORECASE)
        self._key = f"dam_write_generation_{id(self)}"
        self._value = 0
        self._lock = threading.Lock()
        event.listen(engine, "before_cursor_execute", self._on_execute)
        event.listen(engine, "checkin", self._on_checkin)

    @property
    def value(self) -> int:
        return self._value

    def _bump(self) -> None:
        with self._lock:
            self._value += 1

    def _on_execute(self, conn, cursor, statement, params, context, executemany) -> None:
        if self._tables.search(statement) and _WRITE.search(statement):
            conn.info[self._key] = True
            self._bump()

    def _on_checkin(self, dbapi_conn, record) -> None:
        if record is not None and record.info.pop(self._key, False):
            self._bump()
