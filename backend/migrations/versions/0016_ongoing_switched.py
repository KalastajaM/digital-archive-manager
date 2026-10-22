"""ongoing_switched: a publisher's link a conversion batch replaced with a folder

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ongoing_switched",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("batch_id", sa.Text, nullable=False),
        sa.Column(
            "collection_id",
            sa.Integer,
            sa.ForeignKey("collections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rel", sa.Text, nullable=False),
        sa.Column("link_value", sa.Text, nullable=False),
        sa.Column("created", sa.Float, nullable=False),
    )
    op.create_index("ix_ongoing_switched_batch_id", "ongoing_switched", ["batch_id"])


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
