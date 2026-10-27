"""readopted: the journal of Maintenance's "Left alone after a Drive restart", for Undo

Revision ID: 0040
Revises: 0039
"""

import sqlalchemy as sa
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "readopted" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "readopted",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("batch_id", sa.Text, nullable=False),
            sa.Column("entry_id", sa.Integer, nullable=False),
            sa.Column("rel", sa.Text, nullable=False),
            sa.Column("kind", sa.Text, nullable=False),
            sa.Column("st_ino", sa.Text, nullable=False),
            sa.Column("old_dev", sa.Text, nullable=False),
            sa.Column("new_dev", sa.Text, nullable=False),
            sa.Column("created", sa.Float, nullable=False),
            sa.Column("undone", sa.Float, nullable=True),
        )
        op.create_index("ix_readopted_batch_id", "readopted", ["batch_id"])


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
