import sys
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from dam.db.engine import migrate

TABLES = {"files", "file_text", "tags", "file_tags", "operations", "file_fts"}


def _names(engine) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        return {r[0] for r in rows}


def test_migrate_creates_tables(tmp_path: Path, new_engine):
    engine = new_engine(tmp_path / "dam.sqlite")
    migrate(engine)
    assert TABLES <= _names(engine)
    engine.dispose()


def test_migrate_idempotent(tmp_path: Path, new_engine):
    engine = new_engine(tmp_path / "dam.sqlite")
    migrate(engine)
    migrate(engine)
    assert TABLES <= _names(engine)
    engine.dispose()


def test_wal_enabled(engine):
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_fts_accepts_rows(engine):
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO file_fts(drive_id, name, path, text) VALUES ('a','Café','p','t')")
        )
        hit = conn.execute(text("SELECT drive_id FROM file_fts WHERE file_fts MATCH 'cafe'"))
        assert hit.scalar() == "a"


def test_operations_has_is_file_column(engine):
    with engine.connect() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(operations)"))}
    assert "is_file" in cols


def test_engine_sets_busy_timeout_and_wal(tmp_path: Path, new_engine):
    engine = new_engine(tmp_path / "dam.sqlite")
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 30000
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
    engine.dispose()


def test_engine_handles_odd_characters_in_path(tmp_path: Path, new_engine):
    odd = "we ird #dir%20x" if sys.platform == "win32" else "we?ird #dir%20x"  # no ? on Windows
    db = tmp_path / odd / "dam.sqlite"
    db.parent.mkdir()
    engine = new_engine(db)
    migrate(engine)
    assert TABLES <= _names(engine)
    engine.dispose()
    assert db.exists()


EXPECTED_INDEXES = {
    "ix_files_path_nfc": ("files", ["path_nfc"]),
    "ix_files_index_state_retry_at": ("files", ["index_state", "retry_at"]),
    "ix_files_parked_at": ("files", ["parked_at"]),
    "ix_operations_batch_id": ("operations", ["batch_id"]),
}


def test_migration_0004_creates_indexes(engine):
    with engine.connect() as conn:
        for name, (table, columns) in EXPECTED_INDEXES.items():
            row = conn.execute(
                text("SELECT tbl_name FROM sqlite_master WHERE type='index' AND name=:n"),
                {"n": name},
            ).scalar()
            assert row == table, name
            cols = [r[2] for r in conn.execute(text(f"PRAGMA index_info('{name}')"))]
            assert cols == columns, name


def test_tables_mirror_the_indexes():
    from dam.db.tables import metadata

    declared = {
        ix.name: (ix.table.name, [c.name for c in ix.columns])
        for table in metadata.tables.values()
        for ix in table.indexes
    }
    assert declared == {**EXPECTED_INDEXES, **PHASE2_INDEXES}


PHASE2_COLUMNS = {
    "items": [
        "id", "tray_id", "title", "fields", "date", "state", "created", "done_at",
        "done_fields", "created_by_batch",
    ],
    "item_files": ["item_id", "drive_id"],
    "item_events": ["id", "item_id", "at", "kind", "data"],
    "reminders_sent": ["item_id", "rule", "occasion", "fired_at", "channels"],
    "collections": [
        "id", "name", "name_fold", "state", "created", "closed_at", "publish", "ongoing_rel",
        "ongoing_status", "summary", "parent_id", "kind",
    ],
    "collection_members": [
        "collection_id", "drive_id", "added", "created_by_batch", "group_id", "link_name",
    ],
    "collection_groups": [
        "id", "collection_id", "parent_id", "name", "name_fold", "position", "summary",
        "created_by_batch",
    ],
    "notes": ["id", "target_kind", "target_id", "text", "updated", "created_by_batch"],
    "checklist_items": ["id", "target_kind", "target_id", "text", "done", "position"],
    "ongoing_entries": [
        "id", "collection_id", "rel", "kind", "link_value", "st_dev", "st_ino", "created",
        "st_birth",
    ],
    "ongoing_switched": ["id", "batch_id", "collection_id", "rel", "link_value", "created"],
    "member_link_names": ["collection_id", "drive_id", "link_name"],  # stars (0020)
}  # fmt: skip

PHASE2_INDEXES = {
    "ix_items_state_date": ("items", ["state", "date"]),
    "ix_items_tray_id_state": ("items", ["tray_id", "state"]),
    "ix_items_created_by_batch": ("items", ["created_by_batch"]),
    "ux_checklist_items_position": (
        "checklist_items",
        ["target_kind", "target_id", "position"],
    ),
    "ix_item_files_drive_id": ("item_files", ["drive_id"]),
    "ix_collection_members_drive_id": ("collection_members", ["drive_id"]),
    "ix_collection_members_created_by_batch": ("collection_members", ["created_by_batch"]),
    "ix_notes_created_by_batch": ("notes", ["created_by_batch"]),
    "ix_ongoing_entries_collection_id": ("ongoing_entries", ["collection_id"]),
    "ix_ongoing_switched_batch_id": ("ongoing_switched", ["batch_id"]),  # round 2 (0016)
    "ix_ai_calls_at": ("ai_calls", ["at"]),  # Phase 3 (0013)
    "ix_collections_parent_id": ("collections", ["parent_id"]),  # round 2 (0015)
    "ux_collections_kind": ("collections", ["kind"]),  # stars (0017)
    "ix_collection_groups_collection_id_parent_id": (
        "collection_groups",
        ["collection_id", "parent_id"],
    ),
    "ix_collection_groups_created_by_batch": ("collection_groups", ["created_by_batch"]),  # 0018
}


def test_phase2_tables_exist(engine):
    with engine.connect() as conn:
        for table, expected in PHASE2_COLUMNS.items():
            cols = [r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))]
            assert cols == expected, table


def test_phase2_indexes_exist(engine):
    with engine.connect() as conn:
        for name, (table, columns) in PHASE2_INDEXES.items():
            row = conn.execute(
                text("SELECT tbl_name FROM sqlite_master WHERE type='index' AND name=:n"),
                {"n": name},
            ).scalar()
            assert row == table, name
            cols = [r[2] for r in conn.execute(text(f"PRAGMA index_info('{name}')"))]
            assert cols == columns, name


def test_collection_name_fold_unique(engine):
    insert = text("INSERT INTO collections(name, name_fold, created) VALUES (:n, :f, 1.0)")
    with engine.begin() as conn:
        conn.execute(insert, {"n": "Sauna", "f": "sauna"})
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert, {"n": "sauna", "f": "sauna"})


def test_collection_defaults(engine):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO collections(name, name_fold, created) VALUES ('a','a',1.0)"))
        row = conn.execute(text("SELECT state, publish FROM collections WHERE name = 'a'")).one()
    assert row[0] == "open"
    assert row[1] == '{"ongoing": true}'


def test_item_delete_cascades(engine):
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO items(tray_id, title, fields, created) VALUES ('t','x','{}',1.0)")
        )
        conn.execute(text("INSERT INTO item_files(item_id, drive_id) VALUES (1, 'd')"))
        conn.execute(
            text(
                "INSERT INTO item_events(item_id, at, kind, data) VALUES (1, 1.0, 'created', '{}')"
            )
        )
        assert conn.execute(text("SELECT state FROM items")).scalar() == "open"
        conn.execute(text("DELETE FROM items"))
        assert conn.execute(text("SELECT count(*) FROM item_files")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM item_events")).scalar() == 0


def test_notes_unique_per_target(engine):
    insert = text(
        "INSERT INTO notes(target_kind, target_id, text, updated) VALUES ('file','d','t',1.0)"
    )
    with engine.begin() as conn:
        conn.execute(insert)
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert)


def _diff_table(diff: tuple) -> str:
    """Name of the table an autogenerate diff entry concerns."""
    kind, subject = diff[0], diff[1]
    if kind in ("add_table", "remove_table"):
        return subject.name
    if kind.endswith(("_index", "_constraint", "_fk")):
        return subject.table.name
    return diff[2]  # add/remove/modify_* column: (op, schema, table, ...)


def test_phase2_tables_have_no_metadata_drift(engine):
    from dam.db.tables import metadata

    with engine.connect() as conn:
        diffs = compare_metadata(MigrationContext.configure(conn), metadata)
    flat = [d for diff in diffs for d in (diff if isinstance(diff, list) else [diff])]
    assert [d for d in flat if _diff_table(d) in PHASE2_COLUMNS] == []


def test_ongoing_entries_cascade_with_their_collection(engine):
    from dam.db.tables import collections, ongoing_entries

    with engine.begin() as conn:
        cid = conn.execute(
            collections.insert().values(name="A", name_fold="a", created=1.0)
        ).inserted_primary_key[0]
        conn.execute(
            ongoing_entries.insert().values(
                collection_id=cid,
                rel="##. Ongoing/A",
                kind="folder",
                st_dev="1",
                st_ino="2",
                created=1.0,
            )
        )
        conn.execute(collections.delete())
        assert conn.execute(ongoing_entries.select()).all() == []
