"""maintenance_ignored: results of the Maintenance checks the owner chose to ignore

Revision ID: 0034
Revises: 0033
"""

import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "maintenance_ignored" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "maintenance_ignored",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("kind", sa.Text, nullable=False),
            sa.Column("key", sa.Text, nullable=False),
            sa.Column("label", sa.Text, nullable=False),
            sa.Column("members", sa.Text, nullable=True),
            sa.Column("created", sa.Float, nullable=False),
            sa.UniqueConstraint("kind", "key", name="uq_maintenance_ignored_kind_key"),
        )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
