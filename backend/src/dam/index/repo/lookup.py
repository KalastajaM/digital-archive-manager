"""Finding rows: by id or path, a folder's children, the inbox, files below a folder and the
counts. Part of ``FileRepo`` (``dam.index.repo``)."""

from collections.abc import Collection, Sequence

from sqlalchemy import (
    and_,
    case,
    false,
    func,
    not_,
    or_,
    select,
)

from dam.core.paths import nfc
from dam.core.text import fold_name
from dam.db.tables import (
    file_qr_codes,
    files,
    reconnects,
)
from dam.index.repo.model import (
    BARCODE_EXTS,
    COUNTED,
    FileRecord,
    at_or_below,
    below,
    children_walk,
    chunks,
    record,
)


class LookupMixin:
    """Finding rows: by id or path, a folder's children, the inbox, files below a folder and the
    counts."""

    def in_inbox(self, rec: FileRecord) -> bool:
        """The file sits directly in the inbox folder or in a filing code's inbox folder
        (as ``counts`` and the inbox list count it), not deeper."""
        return self.in_inbox_path(rec.path_nfc)

    def in_inbox_path(self, path: str) -> bool:
        """``path`` (archive-relative) is directly in the inbox folder or directly in a
        filing code's inbox folder (``<inbox>/To pay``), not deeper. Compared folded
        (NFC, case-insensitive), as the disk does."""
        folder = fold_name(path).rpartition("/")[0]
        return folder == self._inbox_fold or self._code_of_folder(folder) is not None

    def inbox_code_of(self, path: str) -> str | None:
        """The code whose inbox folder directly holds ``path``, else None."""
        return self._code_of_folder(fold_name(path).rpartition("/")[0])

    def _code_of_folder(self, folded: str) -> str | None:
        above, _, name = folded.rpartition("/")
        return self.code_folders.get(name) if above == self._inbox_fold else None

    def inbox_files(self) -> list[FileRecord]:
        """Files (no folders, links, missing or parked rows) directly in the inbox or in
        a filing code's inbox folder, by path."""
        with self._conn() as conn:
            stmt = select(files).where(*COUNTED, files.c.missing.is_not(True), self._under_inbox())
            rows = conn.execute(stmt.order_by(files.c.path)).all()
        return [r for r in map(record, rows) if self.in_inbox_path(r.path_nfc)]

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
                *COUNTED,
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

    def get(self, drive_id: str) -> FileRecord | None:
        with self._conn() as conn:
            row = conn.execute(select(files).where(files.c.drive_id == drive_id)).first()
        return record(row) if row else None

    def by_path(self, rel: str) -> FileRecord | None:
        with self._conn() as conn:
            row = conn.execute(select(files).where(files.c.path_nfc == nfc(rel))).first()
        return record(row) if row else None

    def get_many(self, drive_ids: Collection[str]) -> dict[str, FileRecord]:
        """``get`` for many ids in one query per chunk; unknown ids are left out."""
        out: dict[str, FileRecord] = {}
        with self._conn() as conn:
            for chunk in chunks(drive_ids):
                rows = conn.execute(select(files).where(files.c.drive_id.in_(chunk))).all()
                out.update((r.drive_id, record(r)) for r in rows)
        return out

    def live_by_paths(self, rels: Collection[str]) -> dict[str, FileRecord]:
        """The live (neither missing nor parked) record at each path, by NFC path."""
        out: dict[str, FileRecord] = {}
        with self._conn() as conn:
            for chunk in chunks({nfc(r) for r in rels}):
                cond = [
                    files.c.path_nfc.in_(chunk),
                    files.c.missing.is_not(True),
                    files.c.parked_at.is_(None),
                ]
                out.update(
                    (r.path_nfc, record(r)) for r in conn.execute(select(files).where(*cond))
                )
        return out

    def reconnected_to(self, old_ids: Collection[str]) -> dict[str, str]:
        """The id each of ``old_ids`` was reconnected to (the latest reconnect that is
        not undone); ids never reconnected are left out."""
        out: dict[str, str] = {}
        with self._conn() as conn:
            for chunk in chunks(old_ids):
                rows = conn.execute(
                    select(reconnects.c.old_id, reconnects.c.new_id)
                    .where(reconnects.c.old_id.in_(chunk), reconnects.c.undone.is_(None))
                    .order_by(reconnects.c.id)
                )
                out.update((r.old_id, r.new_id) for r in rows)
        return out

    def by_folded_path(self, rel: str) -> list[FileRecord]:
        """Every live record whose path equals ``rel`` up to case (NFC, full casefold):
        candidates for a path spelled in another case on a case-insensitive disk."""
        want = nfc(rel)
        folded = want.casefold()
        parts = folded.split("/")  # folding never makes or removes a "/"
        # the spellings of each folder level in turn, from each level's children
        prefixes = [""]
        with self._conn() as conn:
            for i, part in enumerate(parts):
                last = i == len(parts) - 1
                found: set[str] = set()
                for prefix in prefixes:
                    for p in conn.execute(children_walk(prefix)).scalars():
                        name = p[len(prefix) :].partition("/")[0]
                        if name.casefold() == part:
                            found.add(prefix + name if last else prefix + name + "/")
                prefixes = sorted(found)
            rows = []
            for chunk in chunks(prefixes):
                cond = [
                    files.c.path_nfc.in_(chunk),
                    files.c.missing.is_not(True),
                    files.c.parked_at.is_(None),
                ]
                rows += conn.execute(select(files).where(*cond)).all()
        return [record(r) for r in rows if len(r.path_nfc) == len(want)]

    def list_dir(self, rel: str) -> list[FileRecord]:
        """Direct children of ``rel`` (``""`` = archive root) that are not missing."""
        prefix = nfc(rel) + "/" if rel else ""
        cond = [
            files.c.path_nfc.in_(children_walk(prefix)),
            files.c.missing.is_not(True),
            func.instr(func.substr(files.c.path_nfc, len(prefix) + 1), "/") == 0,
        ]
        with self._conn() as conn:
            rows = conn.execute(select(files).where(and_(*cond)).order_by(files.c.path)).all()
        return [record(r) for r in rows]

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
            cond.append(not_(or_(files.c.path_nfc == f, below(f))))
        with self._conn() as conn:
            rows = conn.execute(select(files).where(*cond).order_by(files.c.path)).all()
        return [record(r) for r in rows]

    def live_links(self) -> list[FileRecord]:
        """Every live link row (not missing, not parked), by path."""
        cond = [
            files.c.is_link.is_(True),
            files.c.missing.is_not(True),
            files.c.parked_at.is_(None),
        ]
        with self._conn() as conn:
            rows = conn.execute(select(files).where(*cond).order_by(files.c.path)).all()
        return [record(r) for r in rows]

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
            cond.append(below(nfc(rel)))
        cond.extend(not_(below(nfc(x))) for x in exclude)
        if within is not None:
            folders, ids = within
            alts = [below(nfc(f)) for f in folders]
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
        return [record(r) for r in rows], total or 0

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
        code's inbox folder, as ``inbox_files``) and ``missing``. Kept until the next
        write (``_kept_answer``): counting reads every row.
        """
        key = ("counts", tuple(sorted(self.code_folders.items())))
        return dict(self._kept_answer(key, self._count))

    def _count(self) -> dict[str, int]:
        present = files.c.missing.is_not(True)
        stmt = (
            select(
                files.c.index_state,
                func.sum(case((present, 1), else_=0)),
                func.sum(case((present, 0), else_=1)),
            )
            # "+ 0": keeps the planner off ix_files_parked_at (nearly every row is
            # unparked): a walk of ix_files_index_state_retry_at is about twice as fast
            .where(
                files.c.is_dir.is_not(True),
                files.c.is_link.is_not(True),
                (files.c.parked_at + 0).is_(None),
            )
            .group_by(files.c.index_state)
        )
        under = select(files.c.path_nfc).where(*COUNTED, present, self._under_inbox())
        out: dict[str, int] = {"total": 0, "inbox": 0, "missing": 0}
        with self._conn() as conn:
            for state, n, missing in conn.execute(stmt).all():
                if n:
                    out[state] = n
                out["total"] += n
                out["missing"] += missing
            out["inbox"] = sum(1 for p in conn.execute(under).scalars() if self.in_inbox_path(p))
        return out

    def _in_inbox(self):
        return at_or_below(self.inbox)
