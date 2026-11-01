"""``FileRepo``: the file index (``files`` and the rows that name a file), built from the parts
beside it."""

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy import (
    Connection,
    Engine,
    select,
    update,
)

from dam.core.paths import nfc
from dam.core.text import fold_name
from dam.db.engine import write_tx
from dam.db.generation import WriteGeneration
from dam.db.tables import (
    files,
)
from dam.index.repo.changes import ChangesMixin
from dam.index.repo.indexing import IndexingMixin
from dam.index.repo.lookup import LookupMixin
from dam.index.repo.model import (
    STATUS_TABLES,
    FileRecord,
    T,
    record,
)
from dam.index.repo.reads import ReadsMixin
from dam.index.repo.rows import RowsMixin


class FileRepo(LookupMixin, ReadsMixin, RowsMixin, IndexingMixin, ChangesMixin):
    def __init__(self, engine: Engine, inbox: str) -> None:
        self.engine = engine
        self.inbox = nfc(inbox)
        self._inbox_fold = fold_name(self.inbox.strip("/"))
        # a filing code's inbox folder (folded name) -> its code; set by ``App`` after
        # every load of the code table
        self.code_folders: dict[str, str] = {}
        self._bound: Connection | None = None
        # the status answers (``counts``, ``layout_progress``, ``layout_unread``) kept
        # until a write to the tables they read: the status bar asks every few seconds
        self._kept_gen: WriteGeneration | None = None
        self._kept: dict[tuple, object] = {}
        self._kept_at = -1
        self._kept_lock = threading.Lock()

    def _kept_answer(self, key: tuple, compute: Callable[[], T]) -> T:
        """``compute()``, or its answer from an earlier call while nothing in this process
        has written to the tables it reads since (see ``WriteGeneration``). Not kept
        inside a ``transaction``: its own writes are not committed yet."""
        if self._bound is not None:
            return compute()
        with self._kept_lock:
            if self._kept_gen is None:
                self._kept_gen = WriteGeneration(self.engine, STATUS_TABLES)
            gen = self._kept_gen
            at = gen.value
            if self._kept_at == at and key in self._kept:
                return self._kept[key]  # type: ignore[return-value]
        answer = compute()
        with self._kept_lock:
            # a write while computing: the answer may be from the old rows
            if gen.value == at:
                if self._kept_at != at:
                    self._kept.clear()
                    self._kept_at = at
                self._kept[key] = answer
        return answer

    @staticmethod
    def record_from_row(row) -> FileRecord:
        """A ``FileRecord`` from a row selected from ``files`` (all columns)."""
        return record(row)

    @contextmanager
    def _conn(self, write: bool = False) -> Iterator[Connection]:
        if self._bound is not None:
            yield self._bound
        elif write:
            with write_tx(self.engine) as conn:
                yield conn
        else:
            with self.engine.connect() as conn:
                yield conn

    @contextmanager
    def transaction(self) -> Iterator["FileRepo"]:
        """Run several repo calls in one DB transaction (batched scanner writes)."""
        with write_tx(self.engine) as conn:
            bound = FileRepo(self.engine, self.inbox)
            bound.code_folders = self.code_folders
            bound._bound = conn
            yield bound

    # -- basic access -------------------------------------------------------

    def save_hash(
        self, drive_id: str, sha256: str, expect: tuple[int | None, float | None]
    ) -> bool:
        """Store a hash computed outside the content pass (the duplicate check), as the
        content pass stores it: only for the file as it was when it was picked
        (``expect`` = size, mtime, so a file the scanner has changed since keeps no hash).
        The row's index state is left alone. Returns whether it was stored."""
        with self._conn(write=True) as conn:
            row = conn.execute(
                select(files.c.path, files.c.size, files.c.mtime).where(
                    files.c.drive_id == drive_id
                )
            ).first()
            if row is None or (row.size, row.mtime) != expect:
                return False
            conn.execute(update(files).where(files.c.drive_id == drive_id).values(sha256=sha256))
            self._settle_change(conn, drive_id, row, sha256)
        return True

    # -- flat listing (Browse "Files" view) -------------------------------------
