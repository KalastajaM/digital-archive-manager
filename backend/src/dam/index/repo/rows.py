"""Changing rows: upsert, park, rekey, reconnect, missing files, forgetting and moving paths. Part
of ``FileRepo`` (``dam.index.repo``)."""

import json
import time
from collections.abc import Collection, Sequence
from datetime import date
from pathlib import PurePosixPath

from sqlalchemy import (
    Connection,
    and_,
    func,
    insert,
    not_,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from dam.core.paths import nfc
from dam.db.tables import (
    checklist_items,
    collection_members,
    file_address_zones,
    file_assigned_codes,
    file_assignments,
    file_barcodes,
    file_fields,
    file_identifier_reads,
    file_identifiers,
    file_layouts,
    file_locks,
    file_qr_codes,
    file_summaries,
    file_tags,
    file_text,
    files,
    item_files,
    member_link_names,
    notes,
    reconnects,
    rule_outcomes,
)
from dam.index.repo.model import (
    COLUMNS,
    GIVEN,
    GIVEN_NOTES,
    PARKED,
    RECONNECTED,
    FileRecord,
    at_or_below,
    below,
    ext_of,
    fts_clear_path,
    fts_delete,
    fts_index,
    fts_insert,
    fts_remove,
    fts_rename,
    keys_besides,
    of_file,
)


class RowsMixin:
    """Changing rows: upsert, park, rekey, reconnect, missing files, forgetting and moving paths."""

    def upsert(self, rec: FileRecord) -> None:
        """Insert or update by ``drive_id``; a different row holding the path is dropped."""
        values = {c: getattr(rec, c) for c in COLUMNS}
        values["path_nfc"] = nfc(rec.path)
        with self._conn(write=True) as conn:
            self._drop_stale(conn, rec.path, rec.drive_id)
            stmt = sqlite_insert(files).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["drive_id"],
                set_={c: stmt.excluded[c] for c in COLUMNS if c != "drive_id"},
            )
            conn.execute(stmt)

    # -- stale rows / identity ---------------------------------------------

    @staticmethod
    def _delete_rows(conn: Connection, ids: list[str]) -> None:
        for drive_id in ids:
            conn.execute(file_tags.delete().where(file_tags.c.drive_id == drive_id))
            conn.execute(file_barcodes.delete().where(file_barcodes.c.drive_id == drive_id))
            conn.execute(file_qr_codes.delete().where(file_qr_codes.c.drive_id == drive_id))
            conn.execute(
                file_assigned_codes.delete().where(file_assigned_codes.c.drive_id == drive_id)
            )
            conn.execute(file_layouts.delete().where(file_layouts.c.drive_id == drive_id))
            conn.execute(file_identifiers.delete().where(file_identifiers.c.drive_id == drive_id))
            conn.execute(
                file_identifier_reads.delete().where(file_identifier_reads.c.drive_id == drive_id)
            )
            fts_delete(conn, drive_id)  # before its text goes
            conn.execute(file_text.delete().where(file_text.c.drive_id == drive_id))
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
            cond = or_(cond, below(target))
        conds = [cond, files.c.drive_id != keep_id]
        if except_under is not None:
            old = nfc(except_under)
            conds.append(not_(at_or_below(old)))
        with self._conn(write=True) as conn:
            ids = list(conn.execute(select(files.c.drive_id).where(and_(*conds))).scalars())
            for drive_id in ids:
                tomb = f"{PARKED}{drive_id}"
                conn.execute(
                    update(files)
                    .where(files.c.drive_id == drive_id)
                    .values(path=tomb, path_nfc=tomb, missing=True, parked_at=time.time())
                )
                fts_clear_path(conn, drive_id)

    def has_attachments(self, drive_id: str) -> bool:
        """The owner gave the file something: a tag, a note or checklist entry, a place in
        a collection or a tray item, or a lock."""
        with self._conn() as conn:
            for column in (
                file_tags.c.drive_id,
                collection_members.c.drive_id,
                item_files.c.drive_id,
                file_locks.c.drive_id,
            ):
                if conn.execute(select(column).where(column == drive_id).limit(1)).first():
                    return True
            for table in (notes, checklist_items):
                found = conn.execute(
                    select(table.c.id)
                    .where(table.c.target_kind == "file", table.c.target_id == drive_id)
                    .limit(1)
                ).first()
                if found:
                    return True
        return False

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
        """Give the row ``old_id`` the id ``new_id`` (a synthetic id replaced by the real
        one, or a file copied across disks), carrying along everything that names the file
        by its id: text, fts, tags, the barcode, QR sticker, page-1 layout and identifier
        reads, notes
        and checklists, collection and tray item places, summaries, fields, sender and
        person, locks, rule outcomes and the filing code given in the app."""
        with self._conn(write=True) as conn:
            conn.exec_driver_sql("PRAGMA defer_foreign_keys = ON")
            # out of the index under the old id, back in under the new one once its text
            # and map row carry it
            indexed = fts_remove(conn, old_id)
            for table in (
                file_text,
                file_tags,
                file_barcodes,
                file_qr_codes,
                file_layouts,
                file_identifiers,
                file_identifier_reads,
                collection_members,
                member_link_names,
                item_files,
                file_locks,
                file_assignments,
                file_address_zones,
                file_summaries,
                file_fields,
                rule_outcomes,
                file_assigned_codes,
                files,
            ):
                conn.execute(
                    update(table).where(table.c.drive_id == old_id).values(drive_id=new_id)
                )
            for table in (notes, checklist_items):
                conn.execute(
                    update(table)
                    .where(table.c.target_kind == "file", table.c.target_id == old_id)
                    .values(target_id=new_id)
                )
            conn.execute(
                text("UPDATE file_fts_map SET drive_id = :new WHERE drive_id = :old"),
                {"new": new_id, "old": old_id},
            )
            if indexed:
                fts_index(conn, new_id)

    @staticmethod
    def _given_in(conn: Connection, drive_ids: Sequence[str]) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for i in range(0, len(drive_ids), 500):
            chunk = drive_ids[i : i + 500]
            for what, column in GIVEN:
                for drive_id, n in conn.execute(
                    select(column, func.count()).where(column.in_(chunk)).group_by(column)
                ):
                    out.setdefault(drive_id, {})[what] = n
            for what, table in GIVEN_NOTES:
                for drive_id, n in conn.execute(
                    select(table.c.target_id, func.count())
                    .where(table.c.target_kind == "file", table.c.target_id.in_(chunk))
                    .group_by(table.c.target_id)
                ):
                    out.setdefault(drive_id, {})[what] = n
        return out

    def given(self, drive_ids: Collection[str]) -> dict[str, dict[str, int]]:
        """What the owner (or a filing) gave each of ``drive_ids``, counted by kind (the
        keys of ``GIVEN`` and ``GIVEN_NOTES``); a file with nothing is left out."""
        with self._conn() as conn:
            return self._given_in(conn, list(dict.fromkeys(drive_ids)))

    def reconnect(self, old_id: str, new_id: str, batch_id: str) -> dict[str, int]:
        """The file indexed as ``old_id`` (flagged missing) is the one now indexed as
        ``new_id`` (moved or renamed outside the app, so the scanner gave it a new row):
        everything given to it (what ``rekey`` carries: tags, notes and checklists,
        collection and tray item places, the name its published link keeps, summaries,
        fields, sender and person, locks, rule outcomes, the filing code) moves to
        ``new_id``, and the old row goes with what was read from its content (text, fts,
        barcode, QR and layout reads; the new row has its own). One transaction; returns
        what moved, counted as ``given``. ``ValueError`` (nothing changes) when the old
        row is not missing, the new one is not a present file, or the new one has
        something given already. Database only: nothing on disk is touched. Journaled
        in ``reconnects`` under ``batch_id`` (the old row and the keys of what moved) in
        the same transaction, for ``undo_reconnect``."""
        with self._conn(write=True) as conn:
            old = conn.execute(
                select(files.c.missing, files.c.parked_at).where(files.c.drive_id == old_id)
            ).first()
            new = conn.execute(
                select(files.c.missing, files.c.parked_at, files.c.is_dir, files.c.is_link).where(
                    files.c.drive_id == new_id
                )
            ).first()
            if old is None or not old.missing or old.parked_at is not None:
                raise ValueError("the old row is not missing")
            if new is None or new.missing or new.parked_at is not None:
                raise ValueError("the new row is not a present file")
            if new.is_dir or new.is_link:
                raise ValueError("the new row is not a regular file")
            names_kept = conn.execute(
                select(member_link_names.c.drive_id)
                .where(member_link_names.c.drive_id == new_id)
                .limit(1)
            ).first()
            own_area = conn.execute(
                select(file_address_zones.c.drive_id).where(file_address_zones.c.drive_id == new_id)
            ).first()
            if self._given_in(conn, [new_id]) or names_kept or own_area:
                raise ValueError("the new row has something of its own")
            moved = self._given_in(conn, [old_id]).get(old_id, {})
            row = conn.execute(select(files).where(files.c.drive_id == old_id)).mappings().one()
            keys: dict[str, list[list]] = {}
            for _, table, column in RECONNECTED:
                key_cols = keys_besides(table, column)
                found = conn.execute(
                    select(column, *key_cols).where(of_file(table, column, old_id))
                )
                if rows := [list(r)[1:] for r in found]:
                    keys[table.name] = rows
                conn.execute(
                    update(table).where(of_file(table, column, old_id)).values({column.key: new_id})
                )
            self._delete_rows(conn, [old_id])
            conn.execute(
                insert(reconnects).values(
                    batch_id=batch_id,
                    old_id=old_id,
                    new_id=new_id,
                    old_row=json.dumps(
                        {k: v.isoformat() if isinstance(v, date) else v for k, v in row.items()}
                    ),
                    moved=json.dumps(keys),
                    created=time.time(),
                )
            )
        return moved

    def reconnects_of(self, batch_id: str) -> list[tuple[int, str, str, str, bool]]:
        """The pairs one ``reconnect`` call journaled as ``batch_id``: (journal id, old id,
        the old row's path, new id, undone)."""
        with self._conn() as conn:
            return [
                (r.id, r.old_id, json.loads(r.old_row)["path"], r.new_id, r.undone is not None)
                for r in conn.execute(
                    select(reconnects)
                    .where(reconnects.c.batch_id == batch_id)
                    .order_by(reconnects.c.id)
                )
            ]

    def undo_reconnect(self, entry_id: int) -> dict[str, int]:
        """Undo the reconnect journaled as ``entry_id``: the old row comes back as it was
        (still missing; what was read from its content is not kept, so it reads as pending)
        and the rows that moved to the new one and are still there move back to it. What
        the file was given since stays with it. One transaction; returns what moved back,
        counted as ``given``. ``ValueError`` (nothing changes) when it was undone already,
        the old id is in use again, the old path is taken or the new row is gone. Database
        only: nothing on disk is touched."""
        with self._conn(write=True) as conn:
            entry = conn.execute(select(reconnects).where(reconnects.c.id == entry_id)).first()
            if entry is None:
                raise ValueError("no such reconnect")
            if entry.undone is not None:
                raise ValueError("already undone")
            row = json.loads(entry.old_row)
            old_id, new_id = entry.old_id, entry.new_id
            if (
                conn.execute(select(files.c.drive_id).where(files.c.drive_id == new_id)).first()
                is None
            ):
                raise ValueError("the file is no longer in the index")
            taken = conn.execute(
                select(files.c.drive_id).where(
                    or_(
                        files.c.drive_id == old_id,
                        files.c.path == row["path"],
                        files.c.path_nfc == nfc(row["path"]),
                    )
                )
            ).first()
            if taken is not None:
                raise ValueError("another file is indexed at its old place now")
            if row.get("doc_date"):
                row["doc_date"] = date.fromisoformat(row["doc_date"])
            row.update(
                missing=True,
                parked_at=None,
                index_state="pending",
                retry_at=None,
                attempts=0,
                last_error=None,
            )
            conn.execute(insert(files).values(row))
            fts_insert(conn, old_id, nfc(row["name"] or ""), nfc(row["path"]))
            journaled = json.loads(entry.moved)
            back: dict[str, int] = {}
            for what, table, column in RECONNECTED:
                key_cols = keys_besides(table, column)
                for key in journaled.get(table.name, []):
                    n = conn.execute(
                        update(table)
                        .where(
                            of_file(table, column, new_id),
                            *(c == v for c, v in zip(key_cols, key, strict=True)),
                        )
                        .values({column.key: old_id})
                    ).rowcount
                    if n and what:
                        back[what] = back.get(what, 0) + n
            conn.execute(
                update(reconnects).where(reconnects.c.id == entry_id).values(undone=time.time())
            )
        return back

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
            cond.append(at_or_below(nfc(subtree)))
        cond.extend(not_(at_or_below(nfc(rel))) for rel in skipped)
        with self._conn(write=True) as conn:
            return conn.execute(update(files).where(and_(*cond)).values(missing=True)).rowcount

    @staticmethod
    def _subtree_cond(rel: str):
        return at_or_below(nfc(rel))

    def count_subtree(self, rel: str, *, live_only: bool = False) -> int:
        """Rows at or under ``rel`` (``live_only``: not flagged missing)."""
        cond = [self._subtree_cond(rel)]
        if live_only:
            cond.append(files.c.missing.is_not(True))
        with self._conn() as conn:
            return conn.execute(
                select(func.count()).select_from(files).where(and_(*cond))
            ).scalar_one()

    def has_live_under(self, rel: str) -> bool:
        """Some row strictly under ``rel`` is not flagged missing."""
        cond = and_(below(nfc(rel)), files.c.missing.is_not(True))
        with self._conn() as conn:
            return conn.execute(select(files.c.drive_id).where(cond).limit(1)).first() is not None

    def count_live(self) -> int:
        """Rows not flagged missing, in every folder of the archive."""
        with self._conn() as conn:
            return conn.execute(
                select(func.count()).select_from(files).where(files.c.missing.is_not(True))
            ).scalar_one()

    def subtree_ids(self, rel: str) -> list[str]:
        """The drive ids of the rows at or under ``rel``."""
        with self._conn() as conn:
            return list(
                conn.execute(select(files.c.drive_id).where(self._subtree_cond(rel))).scalars()
            )

    def forget_rows(self, drive_ids: Collection[str]) -> int:
        """Remove the index rows ``drive_ids`` with everything the owner gave those
        files: tags, notes, checklists, collection and item places, summaries, fields,
        sender and person, locks (the collections and items themselves stay). Returns how
        many rows there were. Database only: nothing on disk is touched."""
        with self._conn(write=True) as conn:
            wanted = list(dict.fromkeys(drive_ids))
            ids = []
            for i in range(0, len(wanted), 500):
                chunk = wanted[i : i + 500]
                ids += conn.execute(
                    select(files.c.drive_id).where(files.c.drive_id.in_(chunk))
                ).scalars()
            for i in range(0, len(ids), 500):
                chunk = ids[i : i + 500]
                for table in (notes, checklist_items):
                    conn.execute(
                        table.delete().where(
                            table.c.target_kind == "file", table.c.target_id.in_(chunk)
                        )
                    )
                for table in (
                    collection_members,
                    member_link_names,
                    item_files,
                    file_summaries,
                    file_fields,
                    file_assignments,
                    file_address_zones,
                    file_locks,
                ):
                    conn.execute(table.delete().where(table.c.drive_id.in_(chunk)))
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

    @staticmethod
    def _write_fts_name(conn: Connection, drive_id: str, name: str, path: str) -> None:
        """Set the FTS name/path of ``drive_id``, adding a row (empty text) if it has none."""
        if not fts_rename(conn, drive_id, name=nfc(name), path=nfc(path)):
            fts_insert(conn, drive_id, nfc(name), nfc(path))

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
            fts_clear_path(conn, other)

    def update_path(self, old_rel: str, new_rel: str, *, recursive: bool = True) -> None:
        """Move the record at ``old_rel`` (and, for folders, its descendants) to ``new_rel``.
        ``recursive`` False: that one row only (a folder row following its copy across
        disks, while the rows below it stay where they are).

        Matching is NFC-normalised and respects component boundaries (``a/b`` never
        touches ``a/bc``). Paths not in the index are ignored. Each re-pathed row gets
        its FTS name/path updated (or added, with empty text, if it had none).
        """
        old_nfc = nfc(old_rel)
        depth = len(PurePosixPath(old_rel).parts)
        now = time.time()  # a re-pathed row is on disk right now: a concurrent scan must keep it
        where = files.c.path_nfc == old_nfc
        if recursive:
            where = or_(where, below(old_nfc))
        with self._conn(write=True) as conn:
            rows = conn.execute(
                select(files.c.drive_id, files.c.path, files.c.is_dir).where(where)
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
