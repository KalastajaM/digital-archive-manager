"""Content changes: a file whose bytes differ from what dam last knew of them.

The scanner sees that size or mtime moved and clears the hash; ``note_rewritten`` keeps the
old hash here first. Only the read that follows can tell: ``_settle_change`` compares the
new hash with the kept one, so a file that was merely touched, or changed back, never
shows. One row per file: until it is seen, its ``was_*`` stay those of the content last
known, however often the file changes in between.
"""

import time
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from sqlalchemy import Connection, delete, func, not_, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from dam.core.paths import nfc
from dam.db.tables import content_changes, files
from dam.index.repo.model import FileRecord, below

_JOINED = content_changes.join(files, files.c.drive_id == content_changes.c.drive_id)
_SHOWN = select(
    content_changes.c.drive_id,
    files.c.path,
    files.c.name,
    content_changes.c.was_size,
    content_changes.c.was_mtime,
    content_changes.c.size,
    content_changes.c.mtime,
    content_changes.c.detected_at,
).select_from(_JOINED)


@dataclass
class ContentChange:
    drive_id: str
    path: str
    name: str | None
    was_size: int | None
    was_mtime: float | None
    size: int | None
    mtime: float | None
    detected_at: float


def _row(r) -> ContentChange:
    return ContentChange(
        r.drive_id, r.path, r.name, r.was_size, r.was_mtime, r.size, r.mtime, r.detected_at
    )


class ChangesMixin:
    """What the scanner and the indexer record, and what Today and the file panel read."""

    def note_rewritten(self, rec: FileRecord) -> None:
        """The scanner is about to clear the hash of ``rec`` (its row as it still is): keep
        it to compare with. A file with no hash was never read, so there is nothing to
        compare with, and an open row keeps the content the owner last knew."""
        if rec.sha256 is None:
            return
        with self._conn(write=True) as conn:
            seen_at = conn.execute(
                select(content_changes.c.seen_at).where(content_changes.c.drive_id == rec.drive_id)
            ).first()
            if seen_at is not None and seen_at[0] is None:
                return
            values = {
                "was_sha256": rec.sha256,
                "was_size": rec.size,
                "was_mtime": rec.mtime,
                "sha256": None,
                "size": None,
                "mtime": None,
                "detected_at": None,
                "seen_at": None,
            }
            stmt = sqlite_insert(content_changes).values(drive_id=rec.drive_id, **values)
            conn.execute(
                stmt.on_conflict_do_update(
                    index_elements=["drive_id"], set_={k: stmt.excluded[k] for k in values}
                )
            )

    def _settle_change(self, conn: Connection, drive_id: str, row, sha256: str) -> None:
        """A read gave the file's hash (``row``: its path, size and mtime): the kept hash
        decides whether its content changed. A file in an inbox is still arriving, not
        changing, so it has no notice."""
        kept = conn.execute(
            select(content_changes.c.was_sha256, content_changes.c.seen_at).where(
                content_changes.c.drive_id == drive_id
            )
        ).first()
        if kept is None or kept.seen_at is not None:
            return
        this = content_changes.c.drive_id == drive_id
        if kept.was_sha256 == sha256 or self.in_inbox_path(row.path):
            conn.execute(delete(content_changes).where(this))
            return
        conn.execute(
            update(content_changes)
            .where(this)
            .values(sha256=sha256, size=row.size, mtime=row.mtime, detected_at=time.time())
        )

    @staticmethod
    def _open_changes(exclude: Sequence[str] = ()) -> list:
        cond = [
            content_changes.c.sha256.is_not(None),
            content_changes.c.seen_at.is_(None),
            files.c.missing.is_not(True),
            files.c.parked_at.is_(None),
        ]
        for folder in exclude:
            f = nfc(folder).rstrip("/")
            cond.append(not_(or_(files.c.path_nfc == f, below(f))))
        return cond

    def content_changes(
        self, exclude: Sequence[str] = (), limit: int | None = None
    ) -> tuple[list[ContentChange], int]:
        """The notices not yet seen, newest first, up to ``limit``, and how many there are.
        Left out: gone files and those in the folders ``exclude`` (To Delete)."""
        cond = self._open_changes(exclude)
        with self._conn() as conn:
            count = conn.execute(select(func.count()).select_from(_JOINED).where(*cond)).scalar()
            rows = conn.execute(
                _SHOWN.where(*cond)
                .order_by(content_changes.c.detected_at.desc(), files.c.path)
                .limit(limit)
            ).all()
        return [_row(r) for r in rows], count or 0

    def content_change(self, drive_id: str) -> ContentChange | None:
        """The file's notice, if it has one not yet seen."""
        with self._conn() as conn:
            row = conn.execute(
                _SHOWN.where(
                    content_changes.c.drive_id == drive_id,
                    content_changes.c.sha256.is_not(None),
                    content_changes.c.seen_at.is_(None),
                )
            ).first()
        return _row(row) if row is not None else None

    def see_changes(self, drive_ids: Collection[str]) -> list[str]:
        """Mark these notices as seen. Returns the ids that were open."""
        wanted = list(dict.fromkeys(drive_ids))
        done: list[str] = []
        with self._conn(write=True) as conn:
            for i in range(0, len(wanted), 500):
                this = (
                    content_changes.c.drive_id.in_(wanted[i : i + 500]),
                    content_changes.c.sha256.is_not(None),
                    content_changes.c.seen_at.is_(None),
                )
                done += conn.execute(select(content_changes.c.drive_id).where(*this)).scalars()
                conn.execute(update(content_changes).where(*this).values(seen_at=time.time()))
        return done

    def unsee_changes(self, drive_ids: Collection[str]) -> None:
        """Undo ``see_changes``. A file that changed again since has an open row already."""
        wanted = list(dict.fromkeys(drive_ids))
        with self._conn(write=True) as conn:
            for i in range(0, len(wanted), 500):
                conn.execute(
                    update(content_changes)
                    .where(
                        content_changes.c.drive_id.in_(wanted[i : i + 500]),
                        content_changes.c.seen_at.is_not(None),
                    )
                    .values(seen_at=None)
                )
