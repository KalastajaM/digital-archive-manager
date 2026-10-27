"""A database another build of dam made or migrated is refused and left as it is, never
migrated as this app's (dam_meta's ``app`` marker, migration 0038). Every database here
is a temporary one; another build's is imitated by stamping a revision over this app's
tables (the private build's 0023 changed no tables, this app's 0023 adds one)."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dam.cli.main import app as cli
from dam.db.engine import APP_ID, build_reference, migrate
from dam.errors import ForeignDatabase


def _query(db: Path, sql: str, *args) -> list[tuple]:
    with closing(sqlite3.connect(db)) as con:
        return con.execute(sql, args).fetchall()


def _change(db: Path, sql: str, *args) -> None:
    with closing(sqlite3.connect(db)) as con, con:
        con.execute(sql, args)


def _marker(db: Path) -> str | None:
    rows = _query(db, "SELECT value FROM dam_meta WHERE key = 'app'")
    return rows[0][0] if rows else None


def _dump(db: Path) -> list[str]:
    with closing(sqlite3.connect(db)) as con:
        return list(con.iterdump())


def _backups(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.glob("*.bak"))


def _refused(db: Path, new_engine) -> ForeignDatabase:
    before = _dump(db)
    with pytest.raises(ForeignDatabase) as refused:
        migrate(new_engine(db))
    assert _dump(db) == before  # left as it is
    assert _backups(db.parent) == []
    message = str(refused.value)
    assert str(db) in message and str(db.parent) in message
    assert "another build of dam" in message
    return refused.value


def test_a_new_database_is_marked(tmp_path: Path, new_engine):
    db = tmp_path / "dam.sqlite"
    assert migrate(new_engine(db)) == []
    assert _marker(db) == APP_ID


def test_an_unmarked_database_with_this_apps_tables_is_adopted_and_updated(
    tmp_path: Path, new_engine
):
    db = tmp_path / "dam.sqlite"
    build_reference(db, "0022")  # where this app and the private build still agree
    assert migrate(new_engine(db)) == []
    assert _marker(db) == APP_ID
    assert _query(db, "SELECT name FROM sqlite_master WHERE name = 'made_folders'")
    assert _backups(tmp_path) != []  # #97's backup is still taken for the update
    migrate(new_engine(db))  # marked now: opened as before
    assert _marker(db) == APP_ID


def test_an_unmarked_database_at_the_newest_revision_is_adopted(tmp_path: Path, new_engine):
    db = tmp_path / "dam.sqlite"
    build_reference(db, "head")
    _change(db, "DELETE FROM dam_meta")
    assert migrate(new_engine(db)) == []
    assert _marker(db) == APP_ID
    assert _backups(tmp_path) == []  # nothing to update


def test_a_revision_stamped_over_other_tables_is_refused(tmp_path: Path, new_engine):
    db = tmp_path / "dam.sqlite"
    build_reference(db, "0022")
    _change(db, "UPDATE alembic_version SET version_num = '0023'")
    refused = _refused(db, new_engine)
    assert "revision 0023" in refused.reason and "no table made_folders" in refused.reason


def test_a_changed_column_is_enough_to_refuse(tmp_path: Path, new_engine):
    db = tmp_path / "dam.sqlite"
    build_reference(db, "0030")  # unmarked, as every database from before 0038
    _change(db, "ALTER TABLE files ADD COLUMN private_only TEXT")
    refused = _refused(db, new_engine)
    assert "files has private_only" in refused.reason


def test_a_revision_this_app_does_not_know_is_refused(tmp_path: Path, new_engine):
    db = tmp_path / "dam.sqlite"
    build_reference(db, "0022")
    _change(db, "UPDATE alembic_version SET version_num = '0023_requeue_new_readers'")
    refused = _refused(db, new_engine)
    assert "0023_requeue_new_readers is not one this dam knows" in refused.reason


def test_a_database_marked_as_another_apps_is_refused(tmp_path: Path, new_engine):
    db = tmp_path / "dam.sqlite"
    build_reference(db, "head")
    _change(db, "UPDATE dam_meta SET value = 'dam-private' WHERE key = 'app'")
    refused = _refused(db, new_engine)
    assert "'dam-private'" in refused.reason
    assert _marker(db) == "dam-private"


def test_the_command_line_refuses_another_builds_database_plainly(app_paths):
    build_reference(app_paths.db_path, "0022")
    _change(app_paths.db_path, "UPDATE alembic_version SET version_num = '0023'")
    before = _dump(app_paths.db_path)
    r = CliRunner().invoke(cli, ["--data-dir", str(app_paths.data_dir), "inbox"])
    assert r.exit_code == 1, r.output
    assert "error: dam will not open the database" in r.output
    assert "another build of dam" in r.output and str(app_paths.data_dir) in r.output
    assert _dump(app_paths.db_path) == before
