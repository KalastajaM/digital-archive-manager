"""The smaller database: the search index reads what it indexes (0043), page-1 layouts
are stored compressed (0044), and an update that freed much of the file is compacted."""

import sqlite3
import zlib
from collections import namedtuple
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from conftest import fts_intact
from dam.db import engine as engine_mod
from dam.db.engine import MIGRATIONS_DIR, compact, migrate, write_tx
from dam.extract.base import ExtractedText
from dam.extract.layout import Line, Page1Layout, Word
from dam.index.repo import FileRecord, FileRepo


def _at(engine, revision: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with write_tx(engine) as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, revision)


def _search(engine, query: str) -> list[tuple[str, str]]:
    with engine.connect() as conn:
        return [
            tuple(r)
            for r in conn.execute(
                text(
                    "SELECT drive_id, snippet(file_fts, 3, '[', ']', '…', 8) FROM file_fts "
                    "WHERE file_fts MATCH :q ORDER BY bm25(file_fts), drive_id"
                ),
                {"q": query},
            )
        ]


OLD_ROWS = [
    # drive id, path, indexed path (a parked file's is ''), text (None: no file_text)
    ("d1", "a/Lasku.pdf", "a/Lasku.pdf", "Sähkölasku lokakuu, eräpäivä 15.11."),
    ("d2", "a/Kuva.jpg", "a/Kuva.jpg", None),
    ("d3", "~parked~d3", "", "vanha vakuutus"),
]


def test_migration_0043_keeps_what_every_search_finds(tmp_path: Path, new_engine):
    engine = new_engine(tmp_path / "old.sqlite")
    _at(engine, "0042")
    with write_tx(engine) as conn:
        for drive_id, path, indexed, words in OLD_ROWS:
            name = path.split("/")[-1]
            conn.execute(
                text("INSERT INTO files(drive_id, path, path_nfc, name) VALUES (:d, :p, :p, :n)"),
                {"d": drive_id, "p": path, "n": name},
            )
            if words is not None:
                conn.execute(
                    text("INSERT INTO file_text(drive_id, text) VALUES (:d, :t)"),
                    {"d": drive_id, "t": words},
                )
            conn.execute(
                text("INSERT INTO file_fts(drive_id, name, path, text) VALUES (:d, :n, :p, :t)"),
                {"d": drive_id, "n": name, "p": indexed, "t": words or ""},
            )
            conn.execute(
                text("INSERT INTO file_fts_map VALUES (:d, last_insert_rowid())"), {"d": drive_id}
            )
    queries = ['"lasku"*', '"sahkolasku"', '"kuva"', "path:a", '"vakuutus"', '"parked"*']
    before = {q: _search(engine, q) for q in queries}
    assert before['"vakuutus"'] == [("d3", "vanha [vakuutus]")]

    migrate(engine)

    assert {q: _search(engine, q) for q in queries} == before
    with engine.connect() as conn:
        assert fts_intact(conn)
        assert "content='file_fts_src'" in conn.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'file_fts'")
        ).scalar()
        stored = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master"))}
        assert "file_fts_content" not in stored  # the copy of the text is gone
        mapped = conn.execute(text("SELECT drive_id, name, path FROM file_fts_map")).all()
    assert sorted(mapped) == [
        ("d1", "Lasku.pdf", "a/Lasku.pdf"),
        ("d2", "Kuva.jpg", "a/Kuva.jpg"),
        ("d3", "~parked~d3", ""),
    ]


def test_new_text_leaves_no_tokens_of_the_old(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    repo.upsert(FileRecord(drive_id="d1", path="a/x.pdf"))
    repo.index_name("d1")
    for sha, words in [("h1", "alpha words"), ("h2", "beta words")]:
        assert repo.save_content("d1", sha, ExtractedText(text=words, extractor="t"), "indexed")
    assert [d for d, _ in _search(engine, '"alpha"')] == []
    assert [d for d, _ in _search(engine, '"beta"')] == ["d1"]
    assert repo.save_content("d1", "h3", None, "error", reason="unreadable")
    assert _search(engine, '"words"') == [] and [d for d, _ in _search(engine, "x")] == ["d1"]
    with engine.connect() as conn:
        assert fts_intact(conn)


def test_a_write_out_of_order_is_caught_by_the_integrity_check(engine):
    # why the order matters: text changed under the index leaves its old tokens behind
    repo = FileRepo(engine, inbox="##. Organize")
    repo.upsert(FileRecord(drive_id="d1", path="a/x.pdf"))
    repo.save_content("d1", "h", ExtractedText(text="alpha", extractor="t"), "indexed")
    with write_tx(engine) as conn:
        conn.execute(text("UPDATE file_text SET text = 'beta' WHERE drive_id = 'd1'"))
    with engine.connect() as conn:
        assert not fts_intact(conn)


def _layout() -> Page1Layout:
    return Page1Layout(
        [Line("Lasku 123", (0.1, 0.1, 0.5, 0.15), [Word("Lasku", (0.1, 0.1, 0.3, 0.15))])],
        "text-layer",
    )


def test_a_layout_is_stored_compressed_and_read_back(engine):
    repo = FileRepo(engine, inbox="##. Organize")
    repo.upsert(FileRecord(drive_id="d1", path="a/x.pdf", sha256="s"))
    assert repo.save_layout("d1", "s", _layout())
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT lines FROM file_layouts")).scalar()
    assert isinstance(stored, bytes) and zlib.decompress(stored).decode() == _layout().lines_json()
    assert repo.layout_for("d1") == _layout()


def test_migration_0044_compresses_the_layouts_already_stored(tmp_path: Path, new_engine):
    engine = new_engine(tmp_path / "old.sqlite")
    _at(engine, "0043")
    with write_tx(engine) as conn:
        for drive_id, lines in [("d1", _layout().lines_json()), ("d2", "not json")]:
            conn.execute(
                text(
                    "INSERT INTO files(drive_id, path, path_nfc, sha256) VALUES (:d, :d, :d, 's')"
                ),
                {"d": drive_id},
            )
            conn.execute(
                text(
                    "INSERT INTO file_layouts(drive_id, sha256, lines, source, read_at) "
                    "VALUES (:d, 's', :l, 'text-layer', 1.0)"
                ),
                {"d": drive_id, "l": lines},
            )
    migrate(engine)
    repo = FileRepo(engine, inbox="##. Organize")
    assert repo.layout_for("d1") == _layout()
    assert repo.layout_for("d2") is None  # unreadable before, skipped as before
    with engine.connect() as conn:
        assert "BLOB" in conn.execute(
            text("SELECT sql FROM sqlite_master WHERE name = 'file_layouts'")
        ).scalar()


def test_a_layout_stored_as_text_still_reads():
    assert Page1Layout.from_stored(_layout().lines_json(), "text-layer") == _layout()


def _bloated(db: Path) -> None:
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE filler(x BLOB)")
    con.executemany("INSERT INTO filler VALUES (?)", [(b"x" * 4000,) for _ in range(500)])
    con.commit()
    con.execute("DELETE FROM filler")
    con.commit()
    con.close()


def test_compact_gives_freed_space_back(tmp_path: Path):
    db = tmp_path / "dam.sqlite"
    _bloated(db)
    size = db.stat().st_size
    assert compact(db)
    assert db.stat().st_size < size / 4
    assert not compact(db)  # nothing left to give back


def test_compact_waits_for_room_on_the_disk(tmp_path: Path, monkeypatch):
    db = tmp_path / "dam.sqlite"
    _bloated(db)
    size = db.stat().st_size
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(engine_mod.shutil, "disk_usage", lambda _p: usage(0, 0, size))
    assert not compact(db)
    assert db.stat().st_size == size
