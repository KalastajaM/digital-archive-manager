from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, Connection, Engine, create_engine, event

from dam.rules.model import fold

MIGRATIONS_DIR = Path(__file__).parents[3] / "migrations"


def _fold(value: str | None) -> str | None:
    """NFKD, combining marks dropped, casefolded (``dam.rules.model.fold``; None stays None)."""
    return None if value is None else fold(value)


def make_engine(db_path: Path) -> Engine:
    engine = create_engine(URL.create("sqlite", database=str(db_path)))

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
        # dam_fold(text): case- and accent-insensitive form, for searching in SQL
        dbapi_conn.create_function("dam_fold", 1, _fold, deterministic=True)
        # Let SQLAlchemy emit BEGIN itself (see the "begin" listener below).
        dbapi_conn.isolation_level = None

    @event.listens_for(engine, "begin")
    def _on_begin(conn) -> None:
        # Writers (``write_tx``) take the write lock up front, so a read-then-write
        # cannot interleave with another writer. Readers get a plain deferred BEGIN
        # and, under WAL, never wait for (or block) anyone.
        write = conn.get_execution_options().get("dam_write", False)
        conn.exec_driver_sql("BEGIN IMMEDIATE" if write else "BEGIN")

    return engine


@contextmanager
def write_tx(engine: Engine) -> Iterator[Connection]:
    """A transaction that holds SQLite's write lock from its first statement.

    Use for every block that writes (and for read-then-write blocks); plain reads use
    ``engine.connect()``.
    """
    with engine.connect().execution_options(dam_write=True) as conn, conn.begin():
        yield conn


def migrate(engine: Engine) -> None:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with write_tx(engine) as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
