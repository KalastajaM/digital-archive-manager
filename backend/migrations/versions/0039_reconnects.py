"""reconnects: the journal of Maintenance's "Moved outside dam" reconnects, for Undo

Revision ID: 0039
Revises: 0038
"""

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "reconnects" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "reconnects",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("batch_id", sa.Text, nullable=False),
            sa.Column("old_id", sa.Text, nullable=False),
            sa.Column("new_id", sa.Text, nullable=False),
            sa.Column("old_row", sa.Text, nullable=False),
            sa.Column("moved", sa.Text, nullable=False),
            sa.Column("created", sa.Float, nullable=False),
            sa.Column("undone", sa.Float, nullable=True),
        )
        op.create_index("ix_reconnects_batch_id", "reconnects", ["batch_id"])


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
