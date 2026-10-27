import logging
import sqlite3
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from sqlalchemy import URL, Connection, Engine, create_engine, event, inspect, text

from dam.core.text import fold
from dam.db.tables import metadata
from dam.errors import ForeignDatabase

MIGRATIONS_DIR = Path(__file__).parents[3] / "migrations"
APP_ID = "dam-public"  # dam_meta's ``app`` row (0038): whose migrations a database follows

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


def _config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def build_reference(path: Path, revision: str) -> None:
    """A fresh database at ``path`` migrated by this app to ``revision``: this app's own
    tables as they are at that revision."""
    config = _config()
    engine = make_engine(path)
    try:
        with write_tx(engine) as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, revision)
    finally:
        engine.dispose()


def _layout(connection: Connection) -> dict[str, set[str]]:
    """Each table's column names (alembic's own table and the full-text index's aside)."""
    inspector = inspect(connection)
    return {
        name: {c["name"] for c in inspector.get_columns(name)}
        for name in inspector.get_table_names()
        if name != "alembic_version" and _include_name(name, "table", {})
    }


# Differences this app's own history left in its databases, which its later migrations
# heal: main briefly shipped ``file_fields`` as 0017 (now 0021), so such a database is
# stamped 0017 without ``collections.kind`` (0018 adds it) and has ``file_fields`` from
# 0017 on (0021 keeps it). Not counted against a database at those revisions.
_HEALED = {
    "0017": {"collections lacks kind", "a table file_fields this dam never makes"},
    **dict.fromkeys(("0018", "0019", "0020"), {"a table file_fields this dam never makes"}),
}


def _layout_differences(ours: dict[str, set[str]], theirs: dict[str, set[str]]) -> list[str]:
    """How ``theirs`` differs from ``ours`` in tables and columns, in a few words each.
    Indexes, types and defaults are left out: an old database may differ in those
    without having skipped a migration, while a skipped one leaves a table or column
    missing (or one this app never made)."""
    out = []
    for name in sorted(ours.keys() | theirs.keys()):
        if name not in theirs:
            out.append(f"no table {name}")
        elif name not in ours:
            out.append(f"a table {name} this dam never makes")
        else:
            if missing := sorted(ours[name] - theirs[name]):
                out.append(f"{name} lacks {', '.join(missing)}")
            if extra := sorted(theirs[name] - ours[name]):
                out.append(f"{name} has {', '.join(extra)} this dam never makes")
    return out


def _marker(connection: Connection) -> str | None:
    """The database's ``app`` marker (None when it has none)."""
    if not inspect(connection).has_table("dam_meta"):
        return None
    return connection.execute(text("SELECT value FROM dam_meta WHERE key = 'app'")).scalar()


def _foreign(db: str | None, reason: str) -> ForeignDatabase:
    where = Path(db or "")
    return ForeignDatabase(
        f"dam will not open the database {where}: {reason}. It was most likely made by "
        f"another build of dam that uses the same data folder ({where.parent}). It was "
        "left as it is. Give this dam a data folder of its own (dam --data-dir <folder>), "
        "or open this one with the build that made it.",
        reason,
    )


def _check_identity(
    connection: Connection, db: str | None, current: str | None, script: ScriptDirectory
) -> bool:
    """Refuse (``ForeignDatabase``) a database another app made or migrated, before
    anything is written to it. Returns True when the database has no marker yet but is
    this app's at ``current`` (its tables and columns are those this app's migrations
    make at that revision): the caller adopts it.

    Revision ids alone cannot tell: another build of dam numbers its migrations the same
    way, and its ``0023`` taken for this app's would have this app skip its own."""
    marker = _marker(connection)
    if marker == APP_ID:
        return False
    if marker is not None:
        raise _foreign(db, f"it is marked as belonging to {marker!r}, not {APP_ID!r}")
    if current is None:
        return False  # a new database: migration 0038 marks it
    try:
        known = script.get_revision(current) is not None
    except CommandError:
        known = False
    if not known:
        raise _foreign(db, f"its revision {current} is not one this dam knows")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        reference = Path(tmp) / "reference.sqlite"
        build_reference(reference, current)
        engine = make_engine(reference)
        try:
            with engine.connect() as ref:
                ours = _layout(ref)
        finally:
            engine.dispose()
    healed = _HEALED.get(current, set())
    differences = [d for d in _layout_differences(ours, _layout(connection)) if d not in healed]
    if differences:
        shown = "; ".join(differences[:5])
        more = f"; and {len(differences) - 5} more" if len(differences) > 5 else ""
        raise _foreign(db, f"its tables are not this dam's at revision {current} ({shown}{more})")
    return True


def migrate(engine: Engine, backup: bool = True) -> list:
    """Bring the database to the newest revision, then compare its tables with what this
    version of dam expects; returns the differences (empty when none).

    First the database's identity is checked (``_check_identity``): one another app made
    or migrated is refused with ``ForeignDatabase`` and left untouched; one without the
    ``app`` marker that is this app's is marked (adopted) in the same transaction as
    the update.

    ``backup``: before a pending migration is applied to an existing database (one that
    has a revision), a consistent copy is written next to it (``backup_name``). A
    database whose tables differ after the update is still opened (it may carry history
    from an older app); the difference is logged as a warning, once per process."""
    config = _config()
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    db = engine.url.database
    with write_tx(engine) as connection:
        current = MigrationContext.configure(connection).get_current_revision()
        adopt = _check_identity(connection, db, current, script)
        if backup and db and db != ":memory:" and current is not None and current != head:
            target = backup_name(Path(db), current, head)
            _backup(Path(db), target)
            log.info("database backed up to %s before updating it to %s", target, head)
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        if adopt:
            connection.execute(
                text("INSERT OR IGNORE INTO dam_meta(key, value) VALUES ('app', :app)"),
                {"app": APP_ID},
            )
            log.info("database %s marked as %s's (tables matched %s)", db, APP_ID, current)
    differences = schema_differences(engine)
    if differences:
        shown = ", ".join(_describe(d) for d in differences[:5])
        more = f" and {len(differences) - 5} more" if len(differences) > 5 else ""
        message = (
            f"The database {Path(db or '').name} differs from the layout this version of dam "
            f"expects ({len(differences)} difference(s): {shown}{more}). dam keeps working; "
            "if something fails, restore a backup or a snapshot."
        )
        with _warned_lock:
            first = message not in _warned
            _warned.add(message)
        log.log(logging.WARNING if first else logging.INFO, "%s", message)
    return differences
