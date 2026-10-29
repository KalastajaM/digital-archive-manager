"""file_fts keeps no copy of what it indexes: it reads the name and path from
``file_fts_map`` and the text from ``file_text``, through the view ``file_fts_src``

Until now FTS5 stored every indexed column a second time (``file_fts_content``), the
whole extracted text included: about as large as ``file_text`` itself. The map gains the
name and path the index held (NFC, '' for a parked file) and a unique index on
``fts_rowid`` (the index reads its rows by it); the index is made again over the view
and rebuilt from it. What a file is found by does not change: its indexed text was its
``file_text`` row, or '' without one. Derived rows only; the space comes back with the
VACUUM after the update (``dam.db.engine.compact``).

Revision ID: 0044
Revises: 0043
"""

import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None

SOURCE_VIEW = (
    "CREATE VIEW file_fts_src AS SELECT m.fts_rowid AS fts_rowid, m.drive_id AS drive_id, "
    "m.name AS name, m.path AS path, coalesce(t.text, '') AS text "
    "FROM file_fts_map m LEFT JOIN file_text t ON t.drive_id = m.drive_id"
)
INDEX = (
    "CREATE VIRTUAL TABLE file_fts USING fts5("
    "drive_id UNINDEXED, name, path, text, "
    "content='file_fts_src', content_rowid='fts_rowid', "
    "tokenize='unicode61 remove_diacritics 2')"
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("file_fts_map")}
    if "name" not in columns:
        op.add_column("file_fts_map", sa.Column("name", sa.Text, nullable=False, server_default=""))
        op.add_column("file_fts_map", sa.Column("path", sa.Text, nullable=False, server_default=""))
        op.execute(
            "UPDATE file_fts_map SET "
            "name = coalesce((SELECT name FROM file_fts WHERE rowid = fts_rowid), ''), "
            "path = coalesce((SELECT path FROM file_fts WHERE rowid = fts_rowid), '')"
        )
    if "ix_file_fts_map_fts_rowid" not in {
        i["name"] for i in inspector.get_indexes("file_fts_map")
    }:
        op.create_index("ix_file_fts_map_fts_rowid", "file_fts_map", ["fts_rowid"], unique=True)
    if "file_fts_src" not in inspector.get_view_names():
        op.execute(SOURCE_VIEW)
    stored = bind.execute(
        sa.text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'file_fts'")
    ).scalar()
    if "content=" not in (stored or ""):
        op.execute("DROP TABLE IF EXISTS file_fts")
        op.execute(INDEX)
        op.execute("INSERT INTO file_fts(file_fts) VALUES ('rebuild')")


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
