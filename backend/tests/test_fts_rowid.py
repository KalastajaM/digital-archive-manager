"""FTS rows are written by rowid (via ``file_fts_map``), never by a ``drive_id`` scan;
migration 0037 maps existing rows and adds the partial index for planned operations."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event, select, text

from dam.db.engine import MIGRATIONS_DIR, migrate, write_tx
from dam.db.tables import operations
from dam.extract.base import ExtractedText
from dam.index.repo import FileRecord, FileRepo


def rec(drive_id: str, path: str) -> FileRecord:
    return FileRecord(drive_id=drive_id, path=path)


def hits(engine, query: str) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT drive_id FROM file_fts WHERE file_fts MATCH :q ORDER BY drive_id"),
            {"q": query},
        )
        return [r[0] for r in rows]


def fts_consistent(engine) -> bool:
    """Every FTS row has exactly one map row pointing at it, and vice versa."""
    with engine.connect() as conn:
        fts = conn.execute(text("SELECT rowid, drive_id FROM file_fts")).all()
        mapped = conn.execute(text("SELECT fts_rowid, drive_id FROM file_fts_map")).all()
    return sorted(fts) == sorted(mapped) and len({d for _, d in fts}) == len(fts)


def body(words: str) -> ExtractedText:
    return ExtractedText(text=words, extractor="test")


def test_insert_update_rekey_park_delete_keep_search_right(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    repo.upsert(rec("local:1", "a/Invoice.pdf"))
    repo.upsert(rec("d2", "a/Other.pdf"))
    repo.index_name("local:1")  # name-only rows
    repo.index_name("d2")
    assert hits(engine, "invoice") == ["local:1"] and fts_consistent(engine)

    assert repo.save_content("local:1", "h", body("electricity bill"), "indexed")
    assert hits(engine, "electricity") == ["local:1"] and hits(engine, "invoice") == ["local:1"]
    assert fts_consistent(engine)

    repo.update_path("a", "b/Moved")  # a folder move re-paths both rows
    assert hits(engine, "path:moved") == ["d2", "local:1"] and hits(engine, "electricity")
    assert fts_consistent(engine)

    repo.rekey("local:1", "real")
    assert hits(engine, "electricity") == ["real"] and fts_consistent(engine)

    repo.index_name("real")  # updates the row in place and keeps the text
    assert hits(engine, "electricity") == ["real"] and fts_consistent(engine)

    repo.upsert(rec("new", "b/Moved/Invoice.pdf"))  # displaces "real": its rows go
    assert hits(engine, "electricity") == [] and hits(engine, "invoice") == []
    assert fts_consistent(engine)

    repo.park("b/Moved/Other.pdf", keep_id="x")
    assert hits(engine, "path:moved") == [] and hits(engine, "other") == ["d2"]
    repo.purge_parked()
    assert hits(engine, "other") == [] and fts_consistent(engine)


def _fts_writes(engine, run) -> list[tuple[str, object]]:
    seen: list[tuple[str, object]] = []

    def grab(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("UPDATE FILE_FTS ", "DELETE FROM FILE_FTS ")):
            seen.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", grab)
    try:
        run()
    finally:
        event.remove(engine, "before_cursor_execute", grab)
    return seen


def test_fts_writes_look_rows_up_by_rowid(engine):
    repo = FileRepo(engine, inbox="##. Organize")

    def run():
        repo.upsert(rec("local:1", "a/x.pdf"))
        repo.upsert(rec("d2", "c/y.pdf"))
        repo.index_name("local:1")
        repo.index_name("d2")
        repo.save_content("local:1", "h", body("words"), "indexed")
        repo.update_path("a", "b")
        repo.rekey("local:1", "real")
        repo.park("b/x.pdf", keep_id="other")
        repo.purge_parked()
        with write_tx(engine) as conn:  # a stale missing row in the way of a move
            conn.execute(text("UPDATE files SET missing = 1 WHERE drive_id = 'd2'"))
        repo.upsert(rec("d3", "e/z.pdf"))
        repo.index_name("d3")
        repo.update_path("e/z.pdf", "c/y.pdf")  # parks d2 (_park_occupants)

    writes = _fts_writes(engine, run)
    assert {w[0].split()[0].upper() for w in writes} == {"UPDATE", "DELETE"}
    with engine.connect() as conn:
        for statement, params in writes:
            plan = conn.exec_driver_sql("EXPLAIN QUERY PLAN " + statement, params).all()
            fts = [r[3] for r in plan if "VIRTUAL TABLE" in r[3]]
            # FTS5 reports a rowid lookup as "INDEX 0:=" and a full scan as "INDEX 0:"
            assert fts and all(":=" in d for d in fts), (statement, plan)
    assert fts_consistent(engine)


def test_planned_operations_query_uses_the_partial_index(engine):
    # the query of dam.ops.undo.pending (the status poll), through ``entries``
    stmt = select(operations).where(operations.c.state == "planned").order_by(operations.c.id)
    with engine.connect() as conn:
        compiled = stmt.compile(conn)
        plan = conn.exec_driver_sql(
            "EXPLAIN QUERY PLAN " + str(compiled),
            tuple(compiled.params[k] for k in compiled.positiontup),
        ).all()
    assert any("ix_operations_planned" in r[3] for r in plan), plan


def test_migration_0037_maps_existing_fts_rows(tmp_path: Path, new_engine):
    engine = new_engine(tmp_path / "old.sqlite")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with write_tx(engine) as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "0036")
    with write_tx(engine) as conn:
        for drive_id, path in [("d1", "a/Invoice.pdf"), ("d2", "a/Other.pdf")]:
            conn.execute(
                text("INSERT INTO files(drive_id, path, path_nfc, name) VALUES (:d, :p, :p, :n)"),
                {"d": drive_id, "p": path, "n": path.split("/")[-1]},
            )
        fts = text("INSERT INTO file_fts(drive_id, name, path, text) VALUES (:d, :n, :p, :t)")
        # an older duplicate for d1 (the newest row wins) and a plain row for d2
        conn.execute(fts, {"d": "d1", "n": "Invoice.pdf", "p": "a/Invoice.pdf", "t": "stale"})
        conn.execute(fts, {"d": "d2", "n": "Other.pdf", "p": "a/Other.pdf", "t": "water"})
        conn.execute(fts, {"d": "d1", "n": "Invoice.pdf", "p": "a/Invoice.pdf", "t": "power"})
    migrate(engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0044"
        index = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'ix_operations_planned'")
        ).scalar()
    assert index and "WHERE state = 'planned'" in index
    assert fts_consistent(engine)
    assert hits(engine, "power") == ["d1"] and hits(engine, "stale") == []
    repo = FileRepo(engine, inbox="##. Organize")
    repo.update_path("a", "z")
    assert hits(engine, "path:z") == ["d1", "d2"] and hits(engine, "water") == ["d2"]
    repo.upsert(rec("d3", "z/Other.pdf"))  # drops d2 and its FTS row
    assert hits(engine, "water") == [] and fts_consistent(engine)
