"""related_dismissed: pairs of files the owner marked "Not related" (Relatives)

Revision ID: 0041
Revises: 0040
"""

import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "related_dismissed" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "related_dismissed",
            sa.Column("drive_a", sa.Text, primary_key=True),
            sa.Column("drive_b", sa.Text, primary_key=True),
            sa.Column("created", sa.Float, nullable=False),
        )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
