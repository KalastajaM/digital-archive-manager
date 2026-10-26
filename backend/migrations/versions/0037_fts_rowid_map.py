"""file_fts_map: the FTS rowid of each file, so FTS writes skip a full-table scan;
a partial index on planned operations for the status poll

FTS5 cannot index ``file_fts.drive_id`` (UNINDEXED), so ``WHERE drive_id = :id`` reads
every row. The map gives each drive id its FTS rowid. Existing FTS rows are mapped in
one pass; if a drive id has more than one FTS row (none should), the newest is kept and
the older ones are dropped from the index (derived database rows only, rebuilt by
indexing).

Revision ID: 0037
Revises: 0036
"""

import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "file_fts_map" not in inspector.get_table_names():
        op.create_table(
            "file_fts_map",
            sa.Column("drive_id", sa.Text, primary_key=True),
            sa.Column("fts_rowid", sa.Integer, nullable=False),
        )
        op.execute(
            "DELETE FROM file_fts WHERE drive_id IS NULL OR rowid NOT IN "
            "(SELECT max(rowid) FROM file_fts GROUP BY drive_id)"
        )
        op.execute(
            "INSERT INTO file_fts_map(drive_id, fts_rowid) SELECT drive_id, rowid FROM file_fts"
        )
    indexes = {i["name"] for i in inspector.get_indexes("operations")}
    if "ix_operations_planned" not in indexes:
        op.create_index(
            "ix_operations_planned",
            "operations",
            ["state"],
            sqlite_where=sa.text("state = 'planned'"),
        )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
