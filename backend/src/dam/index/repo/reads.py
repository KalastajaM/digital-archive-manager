"""What was read from a file's content: text, barcodes, QR stickers, filing codes and page-1
layouts. Part of ``FileRepo`` (``dam.index.repo``)."""

import json
import time
from collections.abc import Collection, Sequence
from dataclasses import asdict

from sqlalchemy import (
    Connection,
    and_,
    case,
    func,
    literal_column,
    not_,
    or_,
    select,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from dam.codes.qr_model import QrRead
from dam.db.tables import (
    file_assigned_codes,
    file_barcodes,
    file_identifier_reads,
    file_identifiers,
    file_layouts,
    file_qr_codes,
    file_text,
    files,
    item_files,
    items,
)
from dam.extract.layout import Page1Layout
from dam.index.repo.model import (
    BARCODE_EXTS,
    FileRecord,
    chunks,
    record,
)


class ReadsMixin:
    """What was read from a file's content: text, barcodes, QR stickers, filing codes and page-1
    layouts."""

    def text_for(self, drive_id: str) -> str:
        """Extracted text of ``drive_id``; ``""`` when there is none."""
        return self.texts_for([drive_id]).get(drive_id, "")

    def texts_for(self, drive_ids: Collection[str]) -> dict[str, str]:
        """``text_for`` for many files in one query (files without text are left out)."""
        out: dict[str, str] = {}
        with self._conn() as conn:
            for chunk in chunks(drive_ids):
                rows = conn.execute(
                    select(file_text.c.drive_id, file_text.c.text).where(
                        file_text.c.drive_id.in_(chunk)
                    )
                ).all()
                out.update((r.drive_id, r.text) for r in rows if r.text)
        return out

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
        return self.barcodes_for([drive_id]).get(drive_id)

    def barcodes_for(self, drive_ids: Collection[str]) -> dict[str, str]:
        """``barcode_for`` for many files in one query (files without one are left out)."""
        out: dict[str, str] = {}
        with self._conn() as conn:
            for chunk in chunks(drive_ids):
                rows = conn.execute(
                    select(file_barcodes.c.drive_id, file_barcodes.c.code)
                    .join(files, files.c.drive_id == file_barcodes.c.drive_id)
                    .where(
                        file_barcodes.c.drive_id.in_(chunk),
                        files.c.sha256 == file_barcodes.c.sha256,
                    )
                ).all()
                out.update((r.drive_id, r.code) for r in rows if r.code is not None)
        return out

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

    # -- identifiers (business IDs, IBANs, domains in the stored text) ----------------

    @staticmethod
    def _readable():
        """Files whose stored text the identifiers pass reads."""
        return and_(
            files.c.is_dir.is_not(True),
            files.c.is_link.is_not(True),
            files.c.missing.is_not(True),
            files.c.parked_at.is_(None),
            files.c.index_state == "indexed",
            files.c.sha256.is_not(None),
        )

    @staticmethod
    def _read_with(signature: str):
        return (
            select(file_identifier_reads.c.drive_id)
            .where(
                file_identifier_reads.c.drive_id == files.c.drive_id,
                file_identifier_reads.c.sha256 == files.c.sha256,
                file_identifier_reads.c.signature == signature,
            )
            .exists()
        )

    def next_for_identifiers(self, limit: int, signature: str) -> list[tuple[str, str, str]]:
        """(drive_id, sha256, text) of indexed files whose current content was not read
        with the packs of ``signature``."""
        stmt = (
            select(files.c.drive_id, files.c.sha256, file_text.c.text)
            .join(file_text, file_text.c.drive_id == files.c.drive_id)
            .where(self._readable(), not_(self._read_with(signature)))
            .order_by(files.c.drive_id)
            .limit(limit)
        )
        with self._conn() as conn:
            return [(r.drive_id, r.sha256, r.text or "") for r in conn.execute(stmt).all()]

    def save_identifiers(
        self, drive_id: str, sha256: str, signature: str, found: Sequence[tuple[str, str]]
    ) -> bool:
        """Replace the file's identifiers with ``found`` (kind, value), read from content
        ``sha256`` with ``signature``. Not saved (False) when the content changed since."""
        with self._conn(write=True) as conn:
            current = conn.execute(
                select(files.c.sha256).where(files.c.drive_id == drive_id)
            ).scalar()
            if current is None or current != sha256:
                return False
            conn.execute(file_identifiers.delete().where(file_identifiers.c.drive_id == drive_id))
            rows = [
                {"drive_id": drive_id, "kind": k, "value": v, "sha256": sha256} for k, v in found
            ]
            if rows:
                conn.execute(sqlite_insert(file_identifiers).on_conflict_do_nothing(), rows)
            stmt = sqlite_insert(file_identifier_reads).values(
                drive_id=drive_id, sha256=sha256, signature=signature, read_at=time.time()
            )
            conn.execute(
                stmt.on_conflict_do_update(
                    index_elements=["drive_id"],
                    set_={c: stmt.excluded[c] for c in ("sha256", "signature", "read_at")},
                )
            )
        return True

    def identifiers_for(self, drive_id: str) -> list[tuple[str, str]]:
        """(kind, value) found in the file's current content, in the order found."""
        stmt = (
            select(file_identifiers.c.kind, file_identifiers.c.value)
            .join(files, files.c.drive_id == file_identifiers.c.drive_id)
            .where(
                file_identifiers.c.drive_id == drive_id,
                files.c.sha256 == file_identifiers.c.sha256,
            )
            .order_by(literal_column("file_identifiers.rowid"))
        )
        with self._conn() as conn:
            return [(r.kind, r.value) for r in conn.execute(stmt).all()]

    def files_with_identifier(self, kind: str, value: str) -> list[str]:
        """The files there (not missing, not parked) whose current content carries it."""
        stmt = (
            select(file_identifiers.c.drive_id)
            .join(files, files.c.drive_id == file_identifiers.c.drive_id)
            .where(
                file_identifiers.c.kind == kind,
                file_identifiers.c.value == value,
                files.c.sha256 == file_identifiers.c.sha256,
                files.c.missing.is_not(True),
                files.c.parked_at.is_(None),
            )
            .order_by(file_identifiers.c.drive_id)
        )
        with self._conn() as conn:
            return [r.drive_id for r in conn.execute(stmt).all()]

    def identifier_progress(self, signature: str) -> tuple[int, int]:
        """(read, total): indexed files with text whose content was read with ``signature``."""
        base = select(func.count()).select_from(
            files.join(file_text, file_text.c.drive_id == files.c.drive_id)
        )
        with self._conn() as conn:
            total = conn.execute(base.where(self._readable())).scalar() or 0
            read = (
                conn.execute(base.where(self._readable(), self._read_with(signature))).scalar() or 0
            )
        return read, total

    def qr_for(self, drive_id: str) -> list[QrRead]:
        """The QR stickers read from the file's current content; ``[]`` if none were
        found or none were read (or they were read from content the file no longer has)."""
        return self.qrs_for([drive_id]).get(drive_id, [])

    def qrs_for(self, drive_ids: Collection[str]) -> dict[str, list[QrRead]]:
        """``qr_for`` for many files in one query (files without stickers are left out)."""
        out: dict[str, list[QrRead]] = {}
        with self._conn() as conn:
            for chunk in chunks(drive_ids):
                rows = conn.execute(
                    select(file_qr_codes.c.drive_id, file_qr_codes.c.reads)
                    .join(files, files.c.drive_id == file_qr_codes.c.drive_id)
                    .where(
                        file_qr_codes.c.drive_id.in_(chunk),
                        files.c.sha256 == file_qr_codes.c.sha256,
                    )
                ).all()
                for r in rows:
                    if r.reads:
                        out[r.drive_id] = [QrRead(**x) for x in json.loads(r.reads)]
        return out

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

    def assigned_code(self, drive_id: str) -> str | None:
        """The filing code the owner gave the file in the app, else None (also for a
        file outside the inbox: the caller decides when it counts)."""
        return self.assigned_codes([drive_id]).get(drive_id)

    def assigned_codes(self, drive_ids: Collection[str]) -> dict[str, str]:
        """``assigned_code`` for many files in one query (files without one are left out)."""
        out: dict[str, str] = {}
        with self._conn() as conn:
            for chunk in chunks(drive_ids):
                rows = conn.execute(
                    select(file_assigned_codes.c.drive_id, file_assigned_codes.c.code).where(
                        file_assigned_codes.c.drive_id.in_(chunk)
                    )
                ).all()
                out.update((r.drive_id, r.code) for r in rows if r.code is not None)
        return out

    def set_assigned_code(self, drive_ids: Sequence[str], code: str | None) -> None:
        """Give each file ``code`` (upper case), replacing the one it had; None removes
        it. The caller checks the code and the files."""
        with self._conn(write=True) as conn:
            for drive_id in drive_ids:
                if code is None:
                    conn.execute(
                        file_assigned_codes.delete().where(
                            file_assigned_codes.c.drive_id == drive_id
                        )
                    )
                    continue
                stmt = sqlite_insert(file_assigned_codes).values(
                    drive_id=drive_id, code=code.upper(), assigned_at=time.time()
                )
                conn.execute(
                    stmt.on_conflict_do_update(
                        index_elements=["drive_id"],
                        set_={c: stmt.excluded[c] for c in ("code", "assigned_at")},
                    )
                )

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
            return [record(r) for r in conn.execute(stmt).all()]

    # -- page-1 layouts (where the text of page 1 sits) -------------------------------

    def layout_for(self, drive_id: str) -> Page1Layout | None:
        """The page-1 layout read from the file's current content; None if none was read
        (or it was read from content the file no longer has). An empty layout means page 1
        was read and has no text."""
        return self.layouts_for([drive_id]).get(drive_id)

    def layouts_for(self, drive_ids: Collection[str]) -> dict[str, Page1Layout]:
        """``layout_for`` for many files in one query (files without a current layout are
        left out)."""
        out: dict[str, Page1Layout] = {}
        with self._conn() as conn:
            for chunk in chunks(drive_ids):
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
            return [record(r) for r in conn.execute(stmt).all()]

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
        for their current content, and how many there are. Kept until the next write."""
        return self._kept_answer(("layout_progress",), self._layout_progress)

    def _layout_progress(self) -> tuple[int, int]:
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
        (scans, photos): the two are read at different speeds. Kept until the next write."""
        return self._kept_answer(("layout_unread",), self._layout_unread)

    def _layout_unread(self) -> tuple[int, int]:
        quick = and_(files.c.ext == "pdf", file_text.c.ocr_used.is_not(True))
        with self._conn() as conn:
            row = conn.execute(
                select(func.count(), func.coalesce(func.sum(case((quick, 1), else_=0)), 0))
                .select_from(files.outerjoin(file_text, file_text.c.drive_id == files.c.drive_id))
                .where(*self._layout_population(), not_(self._has_layout()))
            ).one()
        return int(row[1]), int(row[0]) - int(row[1])
