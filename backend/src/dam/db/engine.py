import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import URL, Connection, Engine, create_engine, event

from dam.core.text import fold
from dam.db.tables import metadata

MIGRATIONS_DIR = Path(__file__).parents[3] / "migrations"

log = logging.getLogger(__name__)
_warned: set[str] = set()  # layout warnings already given by this process
_warned_lock = threading.Lock()


def _fold(value: str | None) -> str | None:
    """NFKD, combining marks dropped, casefolded (``dam.core.text.fold``; None stays None)."""
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


def backup_name(db: Path, current: str, head: str) -> Path:
    """Where the copy of ``db`` taken before migrating it from ``current`` to ``head``
    goes: next to it, ``dam.sqlite.before-<from>-to-<to>.bak``. A name already taken
    (the same step tried before) gets ``-2``, ``-3``, ...: nothing is overwritten."""
    base = f"{db.name}.before-{current}-to-{head}"
    target, n = db.with_name(f"{base}.bak"), 1
    while target.exists():
        n += 1
        target = db.with_name(f"{base}-{n}.bak")
    return target


def _backup(db: Path, target: Path) -> None:
    """A consistent copy of the database (WAL included) with SQLite's online backup API.
    The caller holds the write lock (``write_tx``), so the last commit this separate
    reader sees is exactly what the migration starts from. (The writing connection
    itself cannot be the source: SQLite refuses a backup from a connection that is
    writing.)"""
    src = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.execute("PRAGMA busy_timeout=30000")
        src.backup(dst)
    except sqlite3.Error as e:
        raise RuntimeError(
            f"Could not back up the database before updating it ({e}); it was not "
            f"updated. {target.name} may be incomplete."
        ) from e
    finally:
        dst.close()
        src.close()


def _include_name(name: str | None, type_: str, _parents: dict) -> bool:
    """Leave out the full-text index's own tables (``file_fts*``; not in metadata)."""
    return not (
        type_ == "table" and name and name.startswith("file_fts") and name not in metadata.tables
    )


def schema_differences(engine: Engine) -> list:
    """How the database's tables differ from ``dam.db.tables.metadata`` (alembic's
    ``compare_metadata``; empty when they match)."""
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"include_name": _include_name})
        return compare_metadata(context, metadata)


def _describe(difference) -> str:
    """One difference from ``compare_metadata`` in a few words: what and where."""
    if isinstance(difference, list):  # column changes come as a list of modify_* tuples
        return "; ".join(_describe(d) for d in difference)
    kind, *rest = difference
    named = [getattr(x, "name", None) or (x if isinstance(x, str) else None) for x in rest]
    return " ".join([kind, *(str(n) for n in named if n)])


def migrate(engine: Engine, backup: bool = True) -> list:
    """Bring the database to the newest revision, then compare its tables with what this
    version of dam expects; returns the differences (empty when none).

    ``backup``: before a pending migration is applied to an existing database (one that
    has a revision), a consistent copy is written next to it (``backup_name``). A
    database whose tables differ after the update is still opened (it may carry history
    from an older app); the difference is logged as a warning, once per process."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    head = ScriptDirectory.from_config(config).get_current_head()
    db = engine.url.database
    with write_tx(engine) as connection:
        current = MigrationContext.configure(connection).get_current_revision()
        if backup and db and db != ":memory:" and current is not None and current != head:
            target = backup_name(Path(db), current, head)
            _backup(Path(db), target)
            log.info("database backed up to %s before updating it to %s", target, head)
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    differences = schema_differences(engine)
    if differences:
        shown = ", ".join(_describe(d) for d in differences[:5])
        more = f" and {len(differences) - 5} more" if len(differences) > 5 else ""
        text = (
            f"The database {Path(db or '').name} differs from the layout this version of dam "
            f"expects ({len(differences)} difference(s): {shown}{more}). dam keeps working; "
            "if something fails, restore a backup or a snapshot."
        )
        with _warned_lock:
            first = text not in _warned
            _warned.add(text)
        log.log(logging.WARNING if first else logging.INFO, "%s", text)
    return differences
