"""The content indexer's queue and outcomes: what to read next, problems, retries and the saved
text. Part of ``FileRepo`` (``dam.index.repo``)."""

from collections.abc import Collection, Sequence
from pathlib import PurePosixPath

from sqlalchemy import (
    and_,
    func,
    or_,
    select,
    update,
)

from dam.core.paths import nfc
from dam.db.tables import (
    file_text,
    files,
)
from dam.extract.base import ExtractedText
from dam.index.repo.model import (
    READING_MARK,
    FileRecord,
    IndexProblem,
    fts_insert,
    fts_remove,
    record,
    unmarked,
)


class IndexingMixin:
    """The content indexer's queue and outcomes: what to read next, problems, retries and the saved
    text."""

    def next_for_content(self, limit: int, now: float) -> list[FileRecord]:
        """Files awaiting content indexing; inbox files first, then by path."""
        in_inbox = self._in_inbox()
        stmt = (
            select(files)
            .where(
                files.c.is_dir.is_not(True),
                files.c.is_link.is_not(True),
                files.c.missing.is_not(True),
                files.c.index_state.in_(["pending", "cloud_pending"]),
                or_(files.c.retry_at.is_(None), files.c.retry_at <= now),
            )
            .order_by(in_inbox.desc(), files.c.path)
            .limit(limit)
        )
        with self._conn() as conn:
            return [record(r) for r in conn.execute(stmt).all()]

    @staticmethod
    def _problem_cond(states: Sequence[str]):
        # the same files as ``counts()``: no folders, links, missing or parked rows
        return and_(
            files.c.index_state.in_(list(states)),
            files.c.is_dir.is_not(True),
            files.c.is_link.is_not(True),
            files.c.missing.is_not(True),
            files.c.parked_at.is_(None),
        )

    def index_problems(
        self,
        include_unsupported: bool = False,
        limit: int | None = None,
        offset: int = 0,
        only_unsupported: bool = False,
    ) -> list[IndexProblem]:
        """Present files whose content indexing failed (``error``; with
        ``include_unsupported`` also ``unsupported``), newest file (mtime) first; at
        most ``limit`` of them, after skipping ``offset``; ``only_unsupported`` lists
        just the ``unsupported`` ones."""
        states = ["error", "unsupported"] if include_unsupported else ["error"]
        if only_unsupported:
            states = ["unsupported"]
        stmt = (
            select(files)
            .where(self._problem_cond(states))
            .order_by(files.c.mtime.desc(), files.c.path)
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        with self._conn() as conn:
            return [
                IndexProblem(
                    drive_id=r.drive_id,
                    path=r.path,
                    name=r.name or PurePosixPath(r.path).name,
                    state=r.index_state,
                    reason=r.last_error,
                    retry_at=r.retry_at,
                )
                for r in conn.execute(stmt).all()
            ]

    def count_index_problems(self, include_unsupported: bool = False) -> int:
        """How many files ``index_problems`` lists without a limit."""
        states = ["error", "unsupported"] if include_unsupported else ["error"]
        stmt = select(func.count()).select_from(files).where(self._problem_cond(states))
        with self._conn() as conn:
            return int(conn.execute(stmt).scalar() or 0)

    def unsupported_by_type(self) -> list[tuple[str | None, int]]:
        """``(ext, count)`` of the unsupported files (``ext`` lower-case without the
        dot, None for no extension), most common first."""
        ext = func.nullif(func.lower(files.c.ext), "")
        n = func.count().label("n")
        stmt = (
            select(ext.label("ext"), n)
            .where(self._problem_cond(["unsupported"]))
            .group_by(ext)
            .order_by(n.desc(), ext.is_(None), ext)
        )
        with self._conn() as conn:
            return [(r.ext, int(r.n)) for r in conn.execute(stmt).all()]

    def retry_index(self, drive_ids: Collection[str]) -> int:
        """Queue those of ``drive_ids`` in ``error`` or ``unsupported`` for content
        indexing again (``pending``, attempts and reason cleared); returns how many."""
        ids = list(dict.fromkeys(drive_ids))
        queued = 0
        with self._conn(write=True) as conn:
            for i in range(0, len(ids), 500):
                result = conn.execute(
                    update(files)
                    .where(
                        files.c.drive_id.in_(ids[i : i + 500]),
                        files.c.index_state.in_(["error", "unsupported"]),
                    )
                    .values(index_state="pending", attempts=0, retry_at=None, last_error=None)
                )
                queued += result.rowcount
        return queued

    def retry_now_under(self, rel: str) -> int:
        """Let the files at or under ``rel`` that wait to be read again (``retry_at``
        set: a cloud file not downloaded, a disk that went away) be read at once, with
        their attempts counted from zero; returns how many."""
        with self._conn(write=True) as conn:
            return conn.execute(
                update(files)
                .where(self._subtree_cond(rel), files.c.retry_at.is_not(None))
                .values(retry_at=None, attempts=0)
            ).rowcount

    def mark_reading(self, drive_id: str) -> None:
        """Note that ``drive_id``'s content is being read (``READING_MARK``)."""
        with self._conn(write=True) as conn:
            conn.execute(
                update(files).where(files.c.drive_id == drive_id).values(last_error=READING_MARK)
            )

    def clear_reading(self, drive_ids: Collection[str]) -> None:
        """Drop the reading mark of those of ``drive_ids`` that still have it."""
        ids = list(drive_ids)
        with self._conn(write=True) as conn:
            for i in range(0, len(ids), 500):
                conn.execute(
                    update(files)
                    .where(
                        files.c.drive_id.in_(ids[i : i + 500]),
                        files.c.last_error == READING_MARK,
                    )
                    .values(last_error=None)
                )

    def fail_interrupted(self, reason: str) -> int:
        """Put every file still marked as being read in ``error`` with ``reason`` (only
        the explicit retry queues it again); returns how many."""
        with self._conn(write=True) as conn:
            return conn.execute(
                update(files)
                .where(files.c.last_error == READING_MARK)
                .values(index_state="error", retry_at=None, attempts=0, last_error=reason)
            ).rowcount

    def set_index_state(
        self,
        drive_id: str,
        state: str,
        retry_at: float | None = None,
        attempts: int | None = None,
        expect: tuple[int | None, float | None] | None = None,
    ) -> None:
        """Set the state; with ``expect`` (size, mtime), a changed row goes to pending.
        A reading mark (``READING_MARK``) is dropped either way."""
        values: dict = {"index_state": state, "retry_at": retry_at, "last_error": unmarked()}
        if attempts is not None:
            values["attempts"] = attempts
        with self._conn(write=True) as conn:
            if expect is not None:
                row = conn.execute(
                    select(files.c.size, files.c.mtime).where(files.c.drive_id == drive_id)
                ).first()
                if row is not None and (row.size, row.mtime) != expect:
                    values = {"index_state": "pending", "retry_at": None, "last_error": unmarked()}
            conn.execute(update(files).where(files.c.drive_id == drive_id).values(**values))

    def save_content(
        self,
        drive_id: str,
        sha256: str | None,
        extracted: ExtractedText | None,
        state: str,
        expect: tuple[int | None, float | None] | None = None,
        reason: str | None = None,
    ) -> bool:
        """Store hash, extracted text and the FTS row (replacing any earlier ones).

        ``reason`` is stored as ``last_error``: why a file is in ``error`` or
        ``unsupported`` (None clears it).

        Every state gets an FTS name/path row, so filename search finds unindexed files.
        With ``expect`` = (size, mtime) as captured when the file was picked, a row the
        scanner has changed since is not overwritten: it goes back to ``pending``.
        Returns whether the content was saved.
        """
        body = nfc(extracted.text) if extracted else ""
        with self._conn(write=True) as conn:
            row = conn.execute(
                select(files.c.name, files.c.path, files.c.size, files.c.mtime).where(
                    files.c.drive_id == drive_id
                )
            ).first()
            if row is None:
                return False
            if expect is not None and (row.size, row.mtime) != expect:
                conn.execute(
                    update(files)
                    .where(files.c.drive_id == drive_id)
                    .values(index_state="pending", retry_at=None, last_error=unmarked())
                )
                return False
            values: dict = {
                "index_state": state,
                "retry_at": None,
                "attempts": 0,
                "last_error": reason,
            }
            if sha256 is not None:
                values["sha256"] = sha256
            conn.execute(update(files).where(files.c.drive_id == drive_id).values(**values))
            fts_remove(conn, drive_id)  # while the view still shows the old text
            conn.execute(file_text.delete().where(file_text.c.drive_id == drive_id))
            if extracted and extracted.page1 is not None:
                sha = (
                    sha256
                    or conn.execute(
                        select(files.c.sha256).where(files.c.drive_id == drive_id)
                    ).scalar()
                )
                if sha is not None:
                    self._write_layout(conn, drive_id, sha, extracted.page1)
            if extracted:
                conn.execute(
                    file_text.insert().values(
                        drive_id=drive_id,
                        text=body,
                        extractor=extracted.extractor,
                        ocr_used=extracted.ocr_used,
                    )
                )
            fts_insert(conn, drive_id, nfc(row.name), nfc(row.path))
        return True
