"""The file index's model: ``FileRecord``, the problem rows, the shared conditions and the FTS
helpers (``dam.index.repo``)."""

from collections.abc import Collection, Iterator
from dataclasses import dataclass, fields
from datetime import date
from pathlib import PurePosixPath
from typing import TypeVar

from sqlalchemy import (
    Connection,
    Text,
    and_,
    case,
    or_,
    text,
)

from dam.core.paths import nfc
from dam.db.tables import (
    checklist_items,
    collection_members,
    file_assigned_codes,
    file_assignments,
    file_fields,
    file_locks,
    file_summaries,
    file_tags,
    files,
    item_files,
    member_link_names,
    notes,
    rule_outcomes,
)


def ext_of(name: str, is_dir: bool | None) -> str | None:
    """Lower-case extension without the dot (``"pdf"``); None for folders."""
    return None if is_dir else PurePosixPath(name).suffix.lower().lstrip(".")


# the extensions the barcode pass reads (``read_page1``)
BARCODE_EXTS = ("pdf", "jpg", "jpeg", "png")

PARKED = "/parked/"  # no archive-relative path starts with "/"

# the rows the status counts and the inbox list count: no folders, links or parked rows
COUNTED = (files.c.is_dir.is_not(True), files.c.is_link.is_not(True), files.c.parked_at.is_(None))


# What the owner (or a filing) gave a file, by its id, as ``FileRepo.given`` counts it:
# the rows ``FileRepo.reconnect`` moves to another row (``member_link_names``, a name
# remembered for a published link, moves too but is not counted).
GIVEN = (
    ("tags", file_tags.c.drive_id),
    ("collections", collection_members.c.drive_id),
    ("tray_items", item_files.c.drive_id),
    ("lock", file_locks.c.drive_id),
    ("from_for", file_assignments.c.drive_id),
    ("filing_code", file_assigned_codes.c.drive_id),
    ("summaries", file_summaries.c.drive_id),
    ("fields", file_fields.c.drive_id),
    ("rule_outcomes", rule_outcomes.c.drive_id),
)
GIVEN_NOTES = (("note", notes), ("checklist", checklist_items))
# Everything ``reconnect`` moves, as (what it counts as or "", the table, the column that
# names the file); ``undo_reconnect`` moves the journaled rows back by their keys.
RECONNECTED = (
    *((what, column.table, column) for what, column in GIVEN),
    ("", member_link_names, member_link_names.c.drive_id),
    *((what, table, table.c.target_id) for what, table in GIVEN_NOTES),
)

# the tables the kept status answers read (``FileRepo._kept_answer``)
STATUS_TABLES = ("files", "file_layouts", "file_text")

T = TypeVar("T")


@dataclass
class FileRecord:
    """One row of ``files``. ``path`` is the on-disk spelling; ``path_nfc`` its NFC form."""

    drive_id: str
    path: str
    path_nfc: str = ""
    name: str | None = None
    ext: str | None = None
    is_dir: bool = False
    is_link: bool = False
    link_target: str | None = None
    size: int | None = None
    mtime: float | None = None
    sha256: str | None = None
    doc_date: date | None = None
    index_state: str = "pending"
    retry_at: float | None = None
    attempts: int = 0
    missing: bool = False
    last_seen: float | None = None
    parked_at: float | None = None

    def __post_init__(self) -> None:
        self.path_nfc = nfc(self.path)
        if self.name is None:
            self.name = PurePosixPath(self.path).name
            self.ext = ext_of(self.name, self.is_dir)


COLUMNS = [f.name for f in fields(FileRecord)]

FLAT_SORTS = ("name", "date", "size", "folder")

# ``last_error`` of a pending file while the content indexer reads it: set before the
# read, replaced when its outcome is recorded. Still there on the next start means the
# read stopped dam (a crafted file that ran it out of memory), so the file is skipped.
READING_MARK = "dam: reading"


def unmarked():
    """``last_error`` with a reading mark dropped (any other reason is kept)."""
    return case((files.c.last_error == READING_MARK, None), else_=files.c.last_error)


def below(folder_nfc: str):
    """``path_nfc`` lies strictly below ``folder_nfc``: a range on the path index.

    Every path starting ``"<folder>/"`` sorts in ``["<folder>/", "<folder>0")``
    (``"0"`` follows ``"/"``; SQLite compares text bytewise, in code point order), and
    nothing else does, so ``"Sauna 2"`` is never under ``"Sauna"``."""
    return and_(files.c.path_nfc >= folder_nfc + "/", files.c.path_nfc < folder_nfc + "0")


def at_or_below(folder_nfc: str):
    """``path_nfc`` is ``folder_nfc`` or lies below it (see ``below``)."""
    return or_(files.c.path_nfc == folder_nfc, below(folder_nfc))


# One ``path_nfc`` per direct child of the folder with the ``path_nfc`` prefix ``:pre``
# (``""`` = the archive root): the child's own path, or for a child folder without a
# row of its own the first path below it. Each step is one seek on ix_files_path_nfc:
# past a child with no "/" after the prefix to the next path (``|| char(1)``: no path
# holds NUL), past a child folder to the first path after its subtree (``"<child>0"``,
# as ``below``). So a listing reads its children, not everything below them.
CHILDREN_WALK = """
WITH RECURSIVE walk(p) AS (
    SELECT (SELECT min(path_nfc) FROM files WHERE path_nfc >= :pre {upper})
    UNION ALL
    SELECT (
        SELECT min(path_nfc) FROM files
        WHERE path_nfc >= CASE
            WHEN instr(substr(p, :n + 1), '/') = 0 THEN p || char(1)
            ELSE substr(p, 1, :n + instr(substr(p, :n + 1), '/') - 1) || '0'
        END {upper}
    )
    FROM walk WHERE p IS NOT NULL
)
SELECT p FROM walk WHERE p IS NOT NULL
"""


def children_walk(prefix: str):
    """``CHILDREN_WALK`` for the folder prefix ``prefix`` (``"<folder>/"``, or ``""``)."""
    upper = "AND path_nfc < :hi" if prefix else ""
    params = {"pre": prefix, "n": len(prefix)}
    if prefix:
        params["hi"] = prefix[:-1] + "0"
    return text(CHILDREN_WALK.format(upper=upper)).bindparams(**params).columns(p=Text)


@dataclass
class IndexProblem:
    """A file whose content could not be indexed, and why (``reason``: may be None for
    rows marked before the reason was stored). No attempt count: an error is not
    retried automatically (only ``cloud_pending`` is), so it would always be 0."""

    drive_id: str
    path: str
    name: str
    state: str  # error | unsupported
    reason: str | None
    retry_at: float | None


# FTS rows are found by rowid through ``file_fts_map``: ``file_fts.drive_id`` is
# UNINDEXED, so a ``WHERE drive_id = ...`` on it reads the whole table.
FTS_ROWID = "(SELECT fts_rowid FROM file_fts_map WHERE drive_id = :id)"

# ``file_fts`` keeps no copy of what it indexes (migration 0043): it reads the view
# ``file_fts_src``, the map's name and path with the file's ``file_text``. FTS5 cannot see
# those rows change, so a file's tokens are taken out with the values they were indexed
# from: ``fts_remove`` runs while the view still shows them (before ``file_text`` or the
# map row changes) and ``fts_index`` after. Nothing UPDATEs or DELETEs ``file_fts``
# itself; a wrong order is not an error, it leaves stale tokens behind.
_FTS_SRC = (
    "SELECT fts_rowid, drive_id, name, path, text FROM file_fts_src WHERE fts_rowid = :rowid"
)


def _fts_rowid(conn: Connection, drive_id: str) -> int | None:
    return conn.execute(text(f"SELECT {FTS_ROWID}"), {"id": drive_id}).scalar()


def fts_remove(conn: Connection, drive_id: str) -> bool:
    """Take the tokens of ``drive_id`` out of the index, keeping its map row (before its
    text or map row changes); False when it has none."""
    rowid = _fts_rowid(conn, drive_id)
    if rowid is None:
        return False
    row = conn.execute(text(_FTS_SRC), {"rowid": rowid}).one()
    conn.execute(
        text(
            "INSERT INTO file_fts(file_fts, rowid, drive_id, name, path, text) "
            "VALUES ('delete', :rowid, :d, :n, :p, :t)"
        ),
        {"rowid": rowid, "d": row.drive_id, "n": row.name, "p": row.path, "t": row.text},
    )
    return True


def fts_index(conn: Connection, drive_id: str) -> None:
    """Index ``drive_id`` as its map row and ``file_text`` stand now (its earlier tokens
    were taken out with ``fts_remove``)."""
    conn.execute(
        text(f"INSERT INTO file_fts(rowid, drive_id, name, path, text) {_FTS_SRC}"),
        {"rowid": _fts_rowid(conn, drive_id)},
    )


def fts_insert(conn: Connection, drive_id: str, name: str, path: str) -> None:
    """Map ``drive_id`` with ``name``/``path`` and index it with its ``file_text`` (any
    earlier tokens were taken out with ``fts_remove``; its rowid is kept)."""
    conn.execute(
        text(
            "INSERT OR REPLACE INTO file_fts_map(drive_id, fts_rowid, name, path) VALUES "
            "(:id, coalesce((SELECT fts_rowid FROM file_fts_map WHERE drive_id = :id), "
            "(SELECT coalesce(max(fts_rowid), 0) + 1 FROM file_fts_map)), :name, :path)"
        ),
        {"id": drive_id, "name": name, "path": path},
    )
    fts_index(conn, drive_id)


def fts_delete(conn: Connection, drive_id: str) -> None:
    """Drop ``drive_id`` from the index and the map (before its ``file_text`` goes)."""
    fts_remove(conn, drive_id)
    conn.execute(text("DELETE FROM file_fts_map WHERE drive_id = :id"), {"id": drive_id})


def fts_rename(conn: Connection, drive_id: str, **values: str) -> bool:
    """Set the indexed ``name`` and/or ``path`` of ``drive_id``; False when it has no
    entry (nothing changes)."""
    assert values and set(values) <= {"name", "path"}, values
    if not fts_remove(conn, drive_id):
        return False
    sets = ", ".join(f"{column} = :{column}" for column in values)
    conn.execute(
        text(f"UPDATE file_fts_map SET {sets} WHERE drive_id = :id"), {"id": drive_id, **values}
    )
    fts_index(conn, drive_id)
    return True


def fts_clear_path(conn: Connection, drive_id: str) -> None:
    fts_rename(conn, drive_id, path="")


def keys_besides(table, column) -> list:
    """The primary key columns of ``table`` other than ``column`` (the file's id), which
    name one of the file's rows there (none: the table has one row per file)."""
    return [c for c in table.primary_key.columns if c is not column]


def of_file(table, column, drive_id: str):
    """The rows of ``table`` that belong to the file ``drive_id`` (a note or checklist
    names it as a target of kind "file")."""
    if column is table.c.get("target_id"):
        return and_(table.c.target_kind == "file", column == drive_id)
    return column == drive_id


def chunks(drive_ids: Collection[str], size: int = 500) -> Iterator[list[str]]:
    """``drive_ids`` in lists of at most ``size``, for ``IN (...)`` queries."""
    ids = list(drive_ids)
    for start in range(0, len(ids), size):
        yield ids[start : start + size]


def record(row) -> FileRecord:
    data = {c: row._mapping[c] for c in COLUMNS}
    data["is_dir"] = bool(data["is_dir"])
    data["is_link"] = bool(data["is_link"])
    data["missing"] = bool(data["missing"])
    data["attempts"] = data["attempts"] or 0
    return FileRecord(**data)
