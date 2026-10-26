"""File index repository."""

import json
import time
from collections.abc import Collection, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
from datetime import date
from pathlib import PurePosixPath

from sqlalchemy import Connection, Engine, and_, case, false, func, not_, or_, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from dam.codes.qr_model import QrRead
from dam.core.paths import nfc
from dam.db.engine import write_tx
from dam.db.tables import (
    file_barcodes,
    file_layouts,
    file_qr_codes,
    file_tags,
    file_text,
    files,
    item_files,
    items,
    tags,
)
from dam.extract.base import ExtractedText
from dam.extract.layout import Page1Layout
from dam.rules.model import fold


def ext_of(name: str, is_dir: bool | None) -> str | None:
    """Lower-case extension without the dot (``"pdf"``); None for folders."""
    return None if is_dir else PurePosixPath(name).suffix.lower().lstrip(".")


# the extensions the barcode pass reads (``read_page1``)
BARCODE_EXTS = ("pdf", "jpg", "jpeg", "png")

PARKED = "/parked/"  # no archive-relative path starts with "/"

# the rows the status counts and the inbox list count: no folders, links or parked rows
_COUNTED = (files.c.is_dir.is_not(True), files.c.is_link.is_not(True), files.c.parked_at.is_(None))


def _folded(path: str) -> str:
    """``path`` compared the way the disk does: NFC and case-insensitive."""
    return nfc(path).casefold()


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


_COLUMNS = [f.name for f in fields(FileRecord)]

FLAT_SORTS = ("name", "date", "size", "folder")


def _below(folder_nfc: str):
    """``path_nfc`` lies strictly below ``folder_nfc``: a range on the path index.

    Every path starting ``"<folder>/"`` sorts in ``["<folder>/", "<folder>0")``
    (``"0"`` follows ``"/"``; SQLite compares text bytewise, in code point order), and
    nothing else does, so ``"Sauna 2"`` is never under ``"Sauna"``."""
    return and_(files.c.path_nfc >= folder_nfc + "/", files.c.path_nfc < folder_nfc + "0")


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


def _record(row) -> FileRecord:
    data = {c: row._mapping[c] for c in _COLUMNS}
    data["is_dir"] = bool(data["is_dir"])
    data["is_link"] = bool(data["is_link"])
    data["missing"] = bool(data["missing"])
    data["attempts"] = data["attempts"] or 0
    return FileRecord(**data)


class FileRepo:
    def __init__(self, engine: Engine, inbox: str) -> None:
        self.engine = engine
        self.inbox = nfc(inbox)
        self._inbox_fold = _folded(self.inbox.strip("/"))
        # a filing code's inbox folder (folded name) -> its code; set by ``App`` after
        # every load of the code table
        self.code_folders: dict[str, str] = {}
        self._bound: Connection | None = None

    def in_inbox(self, rec: FileRecord) -> bool:
        """The file sits directly in the inbox folder or in a filing code's inbox folder
        (as ``counts`` and the inbox list count it), not deeper."""
        return self.in_inbox_path(rec.path_nfc)

    def in_inbox_path(self, path: str) -> bool:
        """``path`` (archive-relative) is directly in the inbox folder or directly in a
        filing code's inbox folder (``<inbox>/To pay``), not deeper. Compared folded
        (NFC, case-insensitive), as the disk does."""
        folder = _folded(path).rpartition("/")[0]
        return folder == self._inbox_fold or self._code_of_folder(folder) is not None

    def inbox_code_of(self, path: str) -> str | None:
        """The code whose inbox folder directly holds ``path``, else None."""
        return self._code_of_folder(_folded(path).rpartition("/")[0])

    def _code_of_folder(self, folded: str) -> str | None:
        above, _, name = folded.rpartition("/")
        return self.code_folders.get(name) if above == self._inbox_fold else None

    def inbox_files(self) -> list[FileRecord]:
        """Files (no folders, links, missing or parked rows) directly in the inbox or in
        a filing code's inbox folder, by path."""
        with self._conn() as conn:
            stmt = select(files).where(*_COUNTED, files.c.missing.is_not(True), self._under_inbox())
            rows = conn.execute(stmt.order_by(files.c.path)).all()
        return [r for r in map(_record, rows) if self.in_inbox_path(r.path_nfc)]

    def codes_pending(self) -> int:
        """How many inbox files (``in_inbox_path``) the barcode pass will still read for
        QR stickers: a type it reads and no sticker reading for the current content (no
        hash yet counts). Files that failed to index or are unsupported are never read,
        so they are not waited for."""
        qr_read = (
            select(file_qr_codes.c.drive_id)
            .where(
                file_qr_codes.c.drive_id == files.c.drive_id,
                file_qr_codes.c.sha256 == files.c.sha256,
            )
            .exists()
        )
        with self._conn() as conn:
            stmt = select(files.c.path_nfc).where(
                *_COUNTED,
                files.c.missing.is_not(True),
                self._under_inbox(),
                files.c.ext.in_(BARCODE_EXTS),
                files.c.index_state.in_(["pending", "indexed"]),
                not_(qr_read),
            )
            paths = conn.execute(stmt).scalars().all()
        return sum(1 for path in paths if self.in_inbox_path(path))

    def _under_inbox(self):
        """Every row below the inbox, at any depth, matching it up to ASCII case (LIKE);
        callers keep those ``in_inbox_path`` accepts. The inbox is small."""
        esc = self.inbox.strip("/").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return files.c.path_nfc.like(esc + "/%", escape="\\")

    @staticmethod
    def record_from_row(row) -> FileRecord:
        """A ``FileRecord`` from a row selected from ``files`` (all columns)."""
        return _record(row)

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

    def get(self, drive_id: str) -> FileRecord | None:
        with self._conn() as conn:
            row = conn.execute(select(files).where(files.c.drive_id == drive_id)).first()
        return _record(row) if row else None

    def by_path(self, rel: str) -> FileRecord | None:
        with self._conn() as conn:
            row = conn.execute(select(files).where(files.c.path_nfc == nfc(rel))).first()
        return _record(row) if row else None

    def by_folded_path(self, rel: str) -> list[FileRecord]:
        """Every live record whose path equals ``rel`` up to case (NFC, full casefold):
        candidates for a path spelled in another case on a case-insensitive disk."""
        want = nfc(rel)
        folded = want.casefold()
        cond = [
            func.length(files.c.path_nfc) == len(want),
            files.c.missing.is_not(True),
            files.c.parked_at.is_(None),
        ]
        with self._conn() as conn:
            rows = conn.execute(select(files).where(*cond)).all()
        return [_record(r) for r in rows if r.path_nfc.casefold() == folded]

    def list_dir(self, rel: str) -> list[FileRecord]:
        """Direct children of ``rel`` (``""`` = archive root) that are not missing."""
        prefix = nfc(rel) + "/" if rel else ""
        cond = [files.c.missing.is_not(True)]
        if prefix:
            cond.append(func.substr(files.c.path_nfc, 1, len(prefix)) == prefix)
        cond.append(func.instr(func.substr(files.c.path_nfc, len(prefix) + 1), "/") == 0)
        with self._conn() as conn:
            rows = conn.execute(select(files).where(and_(*cond)).order_by(files.c.path)).all()
        return [_record(r) for r in rows]

    def dir_paths(self) -> list[str]:
        """Paths of all folders in the index that are neither missing nor parked."""
        cond = and_(
            files.c.is_dir.is_(True), files.c.missing.is_not(True), files.c.parked_at.is_(None)
        )
        with self._conn() as conn:
            return list(conn.execute(select(files.c.path).where(cond)).scalars())

    # -- maintenance: duplicate candidates and stored hashes ---------------------------

    def regular_files(self, exclude: Sequence[str] = ()) -> list[FileRecord]:
        """Every live regular file (no folder, link, missing or parked row) outside the
        folders in ``exclude`` (archive-relative, with everything below them), by path."""
        cond = [
            files.c.is_dir.is_not(True),
            files.c.is_link.is_not(True),
            files.c.missing.is_not(True),
            files.c.parked_at.is_(None),
        ]
        for folder in exclude:
            f = nfc(folder).rstrip("/")
            cond.append(not_(or_(files.c.path_nfc == f, _below(f))))
        with self._conn() as conn:
            rows = conn.execute(select(files).where(*cond).order_by(files.c.path)).all()
        return [_record(r) for r in rows]

    def save_hash(
        self, drive_id: str, sha256: str, expect: tuple[int | None, float | None]
    ) -> bool:
        """Store a hash computed outside the content pass (the duplicate check), as the
        content pass stores it: only for the file as it was when it was picked
        (``expect`` = size, mtime, so a file the scanner has changed since keeps no hash).
        The row's index state is left alone. Returns whether it was stored."""
        with self._conn(write=True) as conn:
            row = conn.execute(
                select(files.c.size, files.c.mtime).where(files.c.drive_id == drive_id)
            ).first()
            if row is None or (row.size, row.mtime) != expect:
                return False
            conn.execute(update(files).where(files.c.drive_id == drive_id).values(sha256=sha256))
        return True

    # -- flat listing (Browse "Files" view) -------------------------------------

    def _files_below_query(
        self,
        rel: str,
        *,
        within: tuple[Sequence[str], Sequence[str]] | None = None,
        exclude: Sequence[str] = (),
    ):
        """The WHERE clause of ``files_below``: files (not folders) strictly below
        ``rel`` that are neither missing nor parked, outside every ``exclude`` folder,
        and, with ``within = (folders, drive_ids)``, below one of the folders or one
        of the ids. Every folder test is a ``path_nfc`` range, so it uses
        ``ix_files_path_nfc``."""
        cond = [
            files.c.is_dir.is_not(True),
            files.c.missing.is_not(True),
            # "+ 0": keeps the planner off ix_files_parked_at (nearly every row is
            # unparked), so it takes the path range on ix_files_path_nfc
            (files.c.parked_at + 0).is_(None),
        ]
        if rel:
            cond.append(_below(nfc(rel)))
        cond.extend(not_(_below(nfc(x))) for x in exclude)
        if within is not None:
            folders, ids = within
            alts = [_below(nfc(f)) for f in folders]
            if ids:
                alts.append(files.c.drive_id.in_(list(ids)))
            cond.append(or_(*alts) if alts else false())
        return and_(*cond)

    def _files_below_stmts(
        self,
        rel: str,
        *,
        within: tuple[Sequence[str], Sequence[str]] | None = None,
        exclude: Sequence[str] = (),
        sort: str = "name",
        desc: bool = False,
        limit: int = 500,
    ):
        """The count and the rows statement of ``files_below``.

        ``lower()`` folds ASCII letters only (SQLite's built-in), so "Äiti" sorts after
        "Z"; good enough for a capped list, and it keeps the sort in SQL."""
        where = self._files_below_query(rel, within=within, exclude=exclude)
        name = func.lower(files.c.name)
        folder = func.lower(
            func.substr(files.c.path, 1, func.length(files.c.path) - func.length(files.c.name))
        )

        def d(col):
            return col.desc() if desc else col.asc()

        order = {
            "name": [d(name), d(files.c.path_nfc)],
            "folder": [d(folder), d(name), d(files.c.path_nfc)],
            "date": [d(files.c.mtime), name, files.c.path_nfc],
            "size": [d(files.c.size), name, files.c.path_nfc],
        }[sort]
        count = select(func.count()).select_from(files).where(where)
        rows = select(files).where(where).order_by(*order).limit(limit)
        return count, rows

    def files_below(self, rel: str, **kw) -> tuple[list[FileRecord], int]:
        """Up to ``limit`` files below ``rel`` (see ``_files_below_query``), sorted
        by ``sort`` (``FLAT_SORTS``; ties by name, then path), plus how many there
        are in all. Keywords as ``_files_below_stmts``."""
        count, stmt = self._files_below_stmts(rel, **kw)
        with self._conn() as conn:
            total = conn.execute(count).scalar()
            rows = conn.execute(stmt).all()
        return [_record(r) for r in rows], total or 0

    def files_below_sql(self, rel: str, **kw) -> list[str]:
        """The two statements ``files_below(rel, **kw)`` runs, as SQL text with the
        values inlined (for query-plan tests)."""
        return [
            str(stmt.compile(self.engine, compile_kwargs={"literal_binds": True}))
            for stmt in self._files_below_stmts(rel, **kw)
        ]

    def counts(self) -> dict[str, int]:
        """File counts for the status view (folders, links and parked rows not counted).

        One key per ``index_state`` of the present (not missing) files, plus ``total``
        (present files), ``inbox`` (present files directly in the inbox or in a filing
        code's inbox folder, as ``inbox_files``) and ``missing``.
        """
        present = files.c.missing.is_not(True)
        stmt = (
            select(
                files.c.index_state,
                func.sum(case((present, 1), else_=0)),
                func.sum(case((present, 0), else_=1)),
            )
            .where(*_COUNTED)
            .group_by(files.c.index_state)
        )
        under = select(files.c.path_nfc).where(*_COUNTED, present, self._under_inbox())
        out: dict[str, int] = {"total": 0, "inbox": 0, "missing": 0}
        with self._conn() as conn:
            for state, n, missing in conn.execute(stmt).all():
                if n:
                    out[state] = n
                out["total"] += n
                out["missing"] += missing
            out["inbox"] = sum(1 for p in conn.execute(under).scalars() if self.in_inbox_path(p))
        return out

    def text_for(self, drive_id: str) -> str:
        """Extracted text of ``drive_id``; ``""`` when there is none."""
        with self._conn() as conn:
            body = conn.execute(
                select(file_text.c.text).where(file_text.c.drive_id == drive_id)
            ).scalar()
        return body or ""

    def content_keys(self) -> list[tuple[str, str]]:
        """(drive id, sha256) of every indexed file whose content is known."""
        with self._conn() as conn:
            rows = conn.execute(
                select(files.c.drive_id, files.c.sha256).where(files.c.sha256.is_not(None))
            ).all()
        return [(r[0], r[1]) for r in rows]

    def barcode_for(self, drive_id: str) -> str | None:
        """The bank barcode read from the file's current content; None if none was read
        (or it was read from content the file no longer has)."""
        with self._conn() as conn:
            return conn.execute(
                select(file_barcodes.c.code)
                .join(files, files.c.drive_id == file_barcodes.c.drive_id)
                .where(
                    file_barcodes.c.drive_id == drive_id,
                    files.c.sha256 == file_barcodes.c.sha256,
                )
            ).scalar()

    def save_barcode(self, drive_id: str, sha256: str, code: str | None) -> bool:
        """Record what the barcode pass read from content ``sha256`` (``code`` None: none
        found). Not saved (False) when the file's content is no longer ``sha256``."""
        with self._conn(write=True) as conn:
            current = conn.execute(
                select(files.c.sha256).where(files.c.drive_id == drive_id)
            ).scalar()
            if current is None or current != sha256:
                return False
            stmt = sqlite_insert(file_barcodes).values(
                drive_id=drive_id, code=code, sha256=sha256, read_at=time.time()
            )
            conn.execute(
                stmt.on_conflict_do_update(
                    index_elements=["drive_id"],
                    set_={c: stmt.excluded[c] for c in ("code", "sha256", "read_at")},
                )
            )
        return True

    def qr_for(self, drive_id: str) -> list[QrRead]:
        """The QR stickers read from the file's current content; ``[]`` if none were
        found or none were read (or they were read from content the file no longer has)."""
        with self._conn() as conn:
            reads = conn.execute(
                select(file_qr_codes.c.reads)
                .join(files, files.c.drive_id == file_qr_codes.c.drive_id)
                .where(
                    file_qr_codes.c.drive_id == drive_id,
                    files.c.sha256 == file_qr_codes.c.sha256,
                )
            ).scalar()
        return [QrRead(**r) for r in json.loads(reads)] if reads else []

    def save_qr(self, drive_id: str, sha256: str, reads: Sequence[QrRead]) -> bool:
        """Record the QR stickers read from content ``sha256`` (``[]``: none found). Not
        saved (False) when the file's content is no longer ``sha256``."""
        with self._conn(write=True) as conn:
            current = conn.execute(
                select(files.c.sha256).where(files.c.drive_id == drive_id)
            ).scalar()
            if current is None or current != sha256:
                return False
            stmt = sqlite_insert(file_qr_codes).values(
                drive_id=drive_id,
                sha256=sha256,
                reads=json.dumps([asdict(r) for r in reads]),
                read_at=time.time(),
            )
            conn.execute(
                stmt.on_conflict_do_update(
                    index_elements=["drive_id"],
                    set_={c: stmt.excluded[c] for c in ("sha256", "reads", "read_at")},
                )
            )
        return True

    def next_for_barcodes(
        self, limit: int, tray_ids: Collection[str], skip: Collection[str] = ()
    ) -> list[FileRecord]:
        """Indexed PDFs and images with no barcode reading for their current content
        (or, in the inbox, no QR sticker reading for it: files read before 0026):
        inbox files first, then the files of open items in ``tray_ids``, by path.
        ``skip``: drive ids to leave out (reads that timed out, waiting to retry)."""
        in_inbox = self._in_inbox()
        in_items = files.c.drive_id.in_(
            select(item_files.c.drive_id)
            .join(items, items.c.id == item_files.c.item_id)
            .where(items.c.state == "open", items.c.tray_id.in_(list(tray_ids)))
        )
        read = (
            select(file_barcodes.c.drive_id)
            .where(
                file_barcodes.c.drive_id == files.c.drive_id,
                file_barcodes.c.sha256 == files.c.sha256,
            )
            .exists()
        )
        qr_read = (
            select(file_qr_codes.c.drive_id)
            .where(
                file_qr_codes.c.drive_id == files.c.drive_id,
                file_qr_codes.c.sha256 == files.c.sha256,
            )
            .exists()
        )
        stmt = (
            select(files)
            .where(
                files.c.is_dir.is_not(True),
                files.c.is_link.is_not(True),
                files.c.missing.is_not(True),
                files.c.parked_at.is_(None),
                files.c.index_state == "indexed",
                files.c.sha256.is_not(None),
                files.c.ext.in_(BARCODE_EXTS),
                or_(in_inbox, in_items),
                or_(not_(read), and_(in_inbox, not_(qr_read))),
                files.c.drive_id.not_in(list(skip)),
            )
            .order_by(in_inbox.desc(), files.c.path)
            .limit(limit)
        )
        with self._conn() as conn:
            return [_record(r) for r in conn.execute(stmt).all()]

    # -- page-1 layouts (where the text of page 1 sits) -------------------------------

    def layout_for(self, drive_id: str) -> Page1Layout | None:
        """The page-1 layout read from the file's current content; None if none was read
        (or it was read from content the file no longer has). An empty layout means page 1
        was read and has no text."""
        return self.layouts_for([drive_id]).get(drive_id)

    def layouts_for(self, drive_ids: Collection[str]) -> dict[str, Page1Layout]:
        """``layout_for`` for many files in one query (files without a current layout are
        left out)."""
        ids = list(drive_ids)
        out: dict[str, Page1Layout] = {}
        with self._conn() as conn:
            for start in range(0, len(ids), 500):
                chunk = ids[start : start + 500]
                rows = conn.execute(
                    select(file_layouts.c.drive_id, file_layouts.c.lines, file_layouts.c.source)
                    .join(files, files.c.drive_id == file_layouts.c.drive_id)
                    .where(
                        file_layouts.c.drive_id.in_(chunk),
                        files.c.sha256 == file_layouts.c.sha256,
                    )
                ).all()
                for row in rows:
                    try:
                        out[row.drive_id] = Page1Layout.from_json(row.lines, row.source)
                    except (ValueError, KeyError, TypeError):
                        continue  # unreadable row: as if it was not read
        return out

    @staticmethod
    def _write_layout(conn: Connection, drive_id: str, sha256: str, layout: Page1Layout) -> None:
        stmt = sqlite_insert(file_layouts).values(
            drive_id=drive_id,
            sha256=sha256,
            lines=layout.lines_json(),
            source=layout.source,
            read_at=time.time(),
        )
        conn.execute(
            stmt.on_conflict_do_update(
                index_elements=["drive_id"],
                set_={c: stmt.excluded[c] for c in ("sha256", "lines", "source", "read_at")},
            )
        )

    def save_layout(self, drive_id: str, sha256: str, layout: Page1Layout) -> bool:
        """Record the page-1 layout read from content ``sha256`` (no lines: read, no
        text). Not saved (False) when the file's content is no longer ``sha256``."""
        with self._conn(write=True) as conn:
            current = conn.execute(
                select(files.c.sha256).where(files.c.drive_id == drive_id)
            ).scalar()
            if current is None or current != sha256:
                return False
            self._write_layout(conn, drive_id, sha256, layout)
        return True

    def _layout_population(self):
        """Where clauses of the files the layout pass reads: indexed PDFs and images with
        a hash, not folders, links, missing or parked."""
        return (
            files.c.is_dir.is_not(True),
            files.c.is_link.is_not(True),
            files.c.missing.is_not(True),
            files.c.parked_at.is_(None),
            files.c.index_state == "indexed",
            files.c.sha256.is_not(None),
            files.c.ext.in_(BARCODE_EXTS),
        )

    @staticmethod
    def _has_layout():
        return (
            select(file_layouts.c.drive_id)
            .where(
                file_layouts.c.drive_id == files.c.drive_id,
                file_layouts.c.sha256 == files.c.sha256,
            )
            .exists()
        )

    def text_was_ocrd(self, drive_id: str) -> bool | None:
        """Whether the file's indexed text came from OCR (None: it has no indexed text)."""
        with self._conn() as conn:
            return conn.execute(
                select(file_text.c.ocr_used).where(file_text.c.drive_id == drive_id)
            ).scalar()

    def next_for_layouts(
        self,
        limit: int,
        wanted: Collection[str] = (),
        skip: Collection[str] = (),
        everything: bool = True,
    ) -> list[FileRecord]:
        """Indexed PDFs and images with no page-1 layout for their current content:
        inbox files first, then the ``wanted`` drive ids (a replay asked for them), then
        by path. ``skip``: drive ids to leave out (reads that timed out). Without
        ``everything`` only the inbox files and the wanted ones are returned."""
        in_inbox = self._in_inbox()
        is_wanted = files.c.drive_id.in_(list(wanted))
        stmt = (
            select(files)
            .where(
                *self._layout_population(),
                not_(self._has_layout()),
                files.c.drive_id.not_in(list(skip)),
                *(() if everything else (or_(in_inbox, is_wanted),)),
            )
            .order_by(in_inbox.desc(), is_wanted.desc(), files.c.path)
            .limit(limit)
        )
        with self._conn() as conn:
            return [_record(r) for r in conn.execute(stmt).all()]

    def next_for_pictures(
        self,
        wanted: Collection[str] = (),
        skip: Collection[str] = (),
        everything: bool = True,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[tuple[str, str]]:
        """``(drive id, sha256)`` of the indexed PDFs and images that have a page-1 layout
        for their current content, in the order the layout pass reads them: inbox files
        first, then the ``wanted`` ones, then by path (only those two without
        ``everything``). The caller keeps the ones whose page-1 picture is not in the cache:
        a file check, not a database column. ``limit`` and ``offset`` page through the
        list."""
        in_inbox = self._in_inbox()
        is_wanted = files.c.drive_id.in_(list(wanted))
        stmt = (
            select(files.c.drive_id, files.c.sha256)
            .where(
                *self._layout_population(),
                self._has_layout(),
                files.c.drive_id.not_in(list(skip)),
                *(() if everything else (or_(in_inbox, is_wanted),)),
            )
            .order_by(in_inbox.desc(), is_wanted.desc(), files.c.path)
        )
        if limit is not None:
            stmt = stmt.limit(limit).offset(offset)
        with self._conn() as conn:
            return [(r.drive_id, r.sha256) for r in conn.execute(stmt).all()]

    def layout_progress(self) -> tuple[int, int]:
        """``(read, total)`` over the files the layout pass reads: how many have a layout
        for their current content, and how many there are."""
        read = case((self._has_layout(), 1), else_=0)
        with self._conn() as conn:
            row = conn.execute(
                select(func.count(), func.coalesce(func.sum(read), 0)).where(
                    *self._layout_population()
                )
            ).one()
        return int(row[1]), int(row[0])

    def layout_unread(self) -> tuple[int, int]:
        """``(text, scans)``: of the files the layout pass has not read yet, how many are PDFs
        whose text came from their text layer (read quickly, no OCR) and how many need OCR
        (scans, photos): the two are read at different speeds."""
        quick = and_(files.c.ext == "pdf", file_text.c.ocr_used.is_not(True))
        with self._conn() as conn:
            row = conn.execute(
                select(func.count(), func.coalesce(func.sum(case((quick, 1), else_=0)), 0))
                .select_from(files.outerjoin(file_text, file_text.c.drive_id == files.c.drive_id))
                .where(*self._layout_population(), not_(self._has_layout()))
            ).one()
        return int(row[1]), int(row[0]) - int(row[1])

    def _in_inbox(self):
        return or_(
            files.c.path_nfc == self.inbox,
            func.substr(files.c.path_nfc, 1, len(self.inbox) + 1) == self.inbox + "/",
        )

    def upsert(self, rec: FileRecord) -> None:
        """Insert or update by ``drive_id``; a different row holding the path is dropped."""
        values = {c: getattr(rec, c) for c in _COLUMNS}
        values["path_nfc"] = nfc(rec.path)
        with self._conn(write=True) as conn:
            self._drop_stale(conn, rec.path, rec.drive_id)
            stmt = sqlite_insert(files).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["drive_id"],
                set_={c: stmt.excluded[c] for c in _COLUMNS if c != "drive_id"},
            )
            conn.execute(stmt)

    # -- stale rows / identity ---------------------------------------------

    @staticmethod
    def _delete_rows(conn: Connection, ids: list[str]) -> None:
        for drive_id in ids:
            conn.execute(file_tags.delete().where(file_tags.c.drive_id == drive_id))
            conn.execute(file_barcodes.delete().where(file_barcodes.c.drive_id == drive_id))
            conn.execute(file_qr_codes.delete().where(file_qr_codes.c.drive_id == drive_id))
            conn.execute(file_layouts.delete().where(file_layouts.c.drive_id == drive_id))
            conn.execute(file_text.delete().where(file_text.c.drive_id == drive_id))
            conn.execute(text("DELETE FROM file_fts WHERE drive_id = :id"), {"id": drive_id})
            conn.execute(files.delete().where(files.c.drive_id == drive_id))

    def _drop_stale(self, conn: Connection, rel: str, keep_id: str) -> int:
        ids = list(
            conn.execute(
                select(files.c.drive_id).where(
                    files.c.drive_id != keep_id,
                    or_(files.c.path == rel, files.c.path_nfc == nfc(rel)),
                )
            ).scalars()
        )
        self._delete_rows(conn, ids)
        return len(ids)

    def park(
        self,
        rel: str,
        keep_id: str = "",
        *,
        descendants: bool = False,
        except_under: str | None = None,
    ) -> None:
        """Set rows holding ``rel`` (and with ``descendants`` those below it) aside.

        Parked rows get a unique tombstone path, ``missing`` and ``parked_at``, and a blank
        FTS path, so lookups and the UNIQUE path index no longer see them. Rows with
        ``keep_id`` or at/under ``except_under`` (the entry being moved) are left alone.
        The scanner may still claim a parked row later in the same walk (a rename
        chain); ``purge_parked`` drops the rest at the end of a full scan.
        """
        target = nfc(rel)
        cond = files.c.path_nfc == target
        if descendants:
            cond = or_(cond, func.substr(files.c.path_nfc, 1, len(target) + 1) == target + "/")
        conds = [cond, files.c.drive_id != keep_id]
        if except_under is not None:
            old = nfc(except_under)
            conds.append(files.c.path_nfc != old)
            conds.append(func.substr(files.c.path_nfc, 1, len(old) + 1) != old + "/")
        with self._conn(write=True) as conn:
            ids = list(conn.execute(select(files.c.drive_id).where(and_(*conds))).scalars())
            for drive_id in ids:
                tomb = f"{PARKED}{drive_id}"
                conn.execute(
                    update(files)
                    .where(files.c.drive_id == drive_id)
                    .values(path=tomb, path_nfc=tomb, missing=True, parked_at=time.time())
                )
                conn.execute(
                    text("UPDATE file_fts SET path = '' WHERE drive_id = :id"), {"id": drive_id}
                )

    def purge_parked(self) -> None:
        """Delete rows still parked (with their text, fts and tags). DB rows only."""
        with self._conn(write=True) as conn:
            ids = list(
                conn.execute(
                    select(files.c.drive_id).where(files.c.parked_at.is_not(None))
                ).scalars()
            )
            self._delete_rows(conn, ids)

    def rekey(self, old_id: str, new_id: str) -> None:
        """Replace a synthetic id by the real one, carrying text, fts, tags and the
        barcode, QR sticker and page-1 layout reads along."""
        with self._conn(write=True) as conn:
            conn.exec_driver_sql("PRAGMA defer_foreign_keys = ON")
            for table in (file_text, file_tags, file_barcodes, file_qr_codes, file_layouts, files):
                conn.execute(
                    update(table).where(table.c.drive_id == old_id).values(drive_id=new_id)
                )
            conn.execute(
                text("UPDATE file_fts SET drive_id = :new WHERE drive_id = :old"),
                {"new": new_id, "old": old_id},
            )

    def mark_missing(
        self, seen_before: float, subtree: str = "", skipped: Sequence[str] = ()
    ) -> int:
        """Flag rows not seen since ``seen_before`` (never seen counts too), limited to
        ``subtree``; returns count.

        Rows at or under any ``skipped`` rel (unreadable on disk) are left alone.
        """
        cond = [
            or_(files.c.last_seen.is_(None), files.c.last_seen < seen_before),
            files.c.missing.is_not(True),
        ]
        if subtree:
            sub = nfc(subtree)
            prefix = sub + "/"
            cond.append(
                or_(
                    files.c.path_nfc == sub,
                    func.substr(files.c.path_nfc, 1, len(prefix)) == prefix,
                )
            )
        for rel in skipped:
            sk = nfc(rel)
            skip_prefix = sk + "/"
            cond.append(
                not_(
                    or_(
                        files.c.path_nfc == sk,
                        func.substr(files.c.path_nfc, 1, len(skip_prefix)) == skip_prefix,
                    )
                )
            )
        with self._conn(write=True) as conn:
            return conn.execute(update(files).where(and_(*cond)).values(missing=True)).rowcount

    @staticmethod
    def _subtree_cond(rel: str):
        sub = nfc(rel)
        prefix = sub + "/"
        return or_(
            files.c.path_nfc == sub,
            func.substr(files.c.path_nfc, 1, len(prefix)) == prefix,
        )

    def count_subtree(self, rel: str, *, live_only: bool = False) -> int:
        """Rows at or under ``rel`` (``live_only``: not flagged missing)."""
        cond = [self._subtree_cond(rel)]
        if live_only:
            cond.append(files.c.missing.is_not(True))
        with self._conn() as conn:
            return conn.execute(
                select(func.count()).select_from(files).where(and_(*cond))
            ).scalar_one()

    def count_live(self) -> int:
        """Rows not flagged missing, in every folder of the archive."""
        with self._conn() as conn:
            return conn.execute(
                select(func.count()).select_from(files).where(files.c.missing.is_not(True))
            ).scalar_one()

    def forget_subtree(self, rel: str) -> int:
        """Remove the index rows at or under ``rel`` (tags, text and the rest of each row
        with them); returns how many. Database only: nothing on disk is touched."""
        with self._conn(write=True) as conn:
            ids = list(
                conn.execute(select(files.c.drive_id).where(self._subtree_cond(rel))).scalars()
            )
            self._delete_rows(conn, ids)
        return len(ids)

    def mark_missing_path(self, rel: str) -> None:
        """Flag the row at ``rel`` as missing (a folder just removed from disk)."""
        with self._conn(write=True) as conn:
            conn.execute(update(files).where(files.c.path_nfc == nfc(rel)).values(missing=True))

    def touch_seen(self, drive_ids: list[str], now: float) -> None:
        """Mark rows as seen (and no longer missing) without rewriting them."""
        with self._conn(write=True) as conn:
            for i in range(0, len(drive_ids), 500):
                chunk = drive_ids[i : i + 500]
                conn.execute(
                    update(files)
                    .where(files.c.drive_id.in_(chunk))
                    .values(last_seen=now, missing=False, parked_at=None)
                )

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
            return [_record(r) for r in conn.execute(stmt).all()]

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

    def set_index_state(
        self,
        drive_id: str,
        state: str,
        retry_at: float | None = None,
        attempts: int | None = None,
        expect: tuple[int | None, float | None] | None = None,
    ) -> None:
        """Set the state; with ``expect`` (size, mtime), a changed row goes to pending."""
        values: dict = {"index_state": state, "retry_at": retry_at}
        if attempts is not None:
            values["attempts"] = attempts
        with self._conn(write=True) as conn:
            if expect is not None:
                row = conn.execute(
                    select(files.c.size, files.c.mtime).where(files.c.drive_id == drive_id)
                ).first()
                if row is not None and (row.size, row.mtime) != expect:
                    values = {"index_state": "pending", "retry_at": None}
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
                    .values(index_state="pending", retry_at=None)
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
            conn.execute(file_text.delete().where(file_text.c.drive_id == drive_id))
            conn.execute(text("DELETE FROM file_fts WHERE drive_id = :id"), {"id": drive_id})
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
            conn.execute(
                text(
                    "INSERT INTO file_fts(drive_id, name, path, text) "
                    "VALUES (:id, :name, :path, :text)"
                ),
                {"id": drive_id, "name": nfc(row.name), "path": nfc(row.path), "text": body},
            )
        return True

    @staticmethod
    def _write_fts_name(conn: Connection, drive_id: str, name: str, path: str) -> None:
        """Set the FTS name/path of ``drive_id``, adding a row (empty text) if it has none."""
        params = {"id": drive_id, "name": nfc(name), "path": nfc(path)}
        updated = conn.execute(
            text("UPDATE file_fts SET name = :name, path = :path WHERE drive_id = :id"), params
        ).rowcount
        if not updated:
            conn.execute(
                text(
                    "INSERT INTO file_fts(drive_id, name, path, text) "
                    "VALUES (:id, :name, :path, '')"
                ),
                params,
            )

    def index_name(self, drive_id: str) -> None:
        """Make ``drive_id`` findable by name/path before its content is indexed.

        Keeps any extracted text already in the FTS row; ``save_content`` fills it later.
        """
        with self._conn(write=True) as conn:
            row = conn.execute(
                select(files.c.name, files.c.path).where(files.c.drive_id == drive_id)
            ).first()
            if row is not None:
                self._write_fts_name(conn, drive_id, row.name, row.path)

    @staticmethod
    def _park_occupants(conn: Connection, rel: str, keep_id: str, now: float) -> None:
        """Set aside the rows flagged missing that still hold ``rel`` (as ``park`` does)
        before a row is moved there: such a row describes something that left that path
        (a link an undo just took away), so it is stale, and it would keep the path
        from the entry that is there now. A row that is not flagged missing is left
        alone: that conflict is reported, not hidden. The next full scan drops parked
        rows."""
        stale = conn.execute(
            select(files.c.drive_id).where(
                files.c.drive_id != keep_id,
                files.c.missing.is_(True),
                or_(files.c.path == rel, files.c.path_nfc == nfc(rel)),
            )
        ).scalars()
        for other in list(stale):
            tomb = f"{PARKED}{other}"
            conn.execute(
                update(files)
                .where(files.c.drive_id == other)
                .values(path=tomb, path_nfc=tomb, missing=True, parked_at=now)
            )
            conn.execute(text("UPDATE file_fts SET path = '' WHERE drive_id = :id"), {"id": other})

    def update_path(self, old_rel: str, new_rel: str) -> None:
        """Move the record at ``old_rel`` (and, for folders, its descendants) to ``new_rel``.

        Matching is NFC-normalised and respects component boundaries (``a/b`` never
        touches ``a/bc``). Paths not in the index are ignored. Each re-pathed row gets
        its FTS name/path updated (or added, with empty text, if it had none).
        """
        old_nfc = nfc(old_rel)
        prefix = old_nfc + "/"
        depth = len(PurePosixPath(old_rel).parts)
        now = time.time()  # a re-pathed row is on disk right now: a concurrent scan must keep it
        with self._conn(write=True) as conn:
            rows = conn.execute(
                select(files.c.drive_id, files.c.path, files.c.is_dir).where(
                    or_(
                        files.c.path_nfc == old_nfc,
                        func.substr(files.c.path_nfc, 1, len(prefix)) == prefix,
                    )
                )
            ).all()
            for drive_id, path, is_dir in rows:
                rest = PurePosixPath(path).parts[depth:]
                new_path = PurePosixPath(new_rel, *rest).as_posix()
                name = PurePosixPath(new_path).name
                self._park_occupants(conn, new_path, drive_id, now)
                conn.execute(
                    update(files)
                    .where(files.c.drive_id == drive_id)
                    .values(
                        path=new_path,
                        path_nfc=nfc(new_path),
                        name=name,
                        ext=ext_of(name, is_dir),
                        last_seen=now,
                        missing=False,
                    )
                )
                self._write_fts_name(conn, drive_id, name, new_path)


class TagRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def add(self, drive_id: str, tag_names: list[str]) -> None:
        now = time.time()
        with write_tx(self.engine) as conn:
            for name in tag_names:
                conn.execute(sqlite_insert(tags).values(name=name).on_conflict_do_nothing())
                tag_id = conn.execute(select(tags.c.id).where(tags.c.name == name)).scalar_one()
                added = conn.execute(
                    sqlite_insert(file_tags)
                    .values(drive_id=drive_id, tag_id=tag_id)
                    .on_conflict_do_nothing()
                )
                if added.rowcount:
                    conn.execute(update(tags).where(tags.c.id == tag_id).values(last_used_at=now))

    def set_for_file(self, drive_id: str, tag_names: list[str]) -> None:
        """Make ``tag_names`` the file's tags, exactly (one transaction). A tag the file
        did not have is marked as just used (the sidebar's recent tags)."""
        now = time.time()
        with write_tx(self.engine) as conn:
            had = set(
                conn.execute(
                    select(tags.c.name)
                    .join(file_tags, file_tags.c.tag_id == tags.c.id)
                    .where(file_tags.c.drive_id == drive_id)
                ).scalars()
            )
            conn.execute(file_tags.delete().where(file_tags.c.drive_id == drive_id))
            for name in tag_names:
                conn.execute(sqlite_insert(tags).values(name=name).on_conflict_do_nothing())
                tag_id = conn.execute(select(tags.c.id).where(tags.c.name == name)).scalar_one()
                conn.execute(sqlite_insert(file_tags).values(drive_id=drive_id, tag_id=tag_id))
                if name not in had:
                    conn.execute(update(tags).where(tags.c.id == tag_id).values(last_used_at=now))

    def popular(self, prefix: str = "", limit: int = 8) -> list[tuple[str, int]]:
        """Tags starting with ``prefix`` (case and accents ignored) with the number of files
        that have each, most used first, then by name."""
        used = func.count(file_tags.c.drive_id)
        query = (
            select(tags.c.name, used)
            .join(file_tags, file_tags.c.tag_id == tags.c.id)
            .group_by(tags.c.id)
        )
        folded = fold(prefix.strip())
        if folded:
            escaped = folded.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.where(func.dam_fold(tags.c.name).like(f"{escaped}%", escape="\\"))
        with self.engine.connect() as conn:
            rows = conn.execute(query.order_by(used.desc(), tags.c.name).limit(limit)).all()
        return [(name, int(n)) for name, n in rows]

    def for_file(self, drive_id: str) -> list[str]:
        with self.engine.connect() as conn:
            return list(
                conn.execute(
                    select(tags.c.name)
                    .join(file_tags, file_tags.c.tag_id == tags.c.id)
                    .where(file_tags.c.drive_id == drive_id)
                    .order_by(tags.c.name)
                ).scalars()
            )
