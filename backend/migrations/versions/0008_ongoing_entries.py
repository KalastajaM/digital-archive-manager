"""ongoing_entries: what the Ongoing publisher created, by identity

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ongoing_entries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "collection_id",
            sa.Integer,
            sa.ForeignKey("collections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rel", sa.Text, nullable=False, unique=True),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("link_value", sa.Text, nullable=True),
        sa.Column("st_dev", sa.Integer, nullable=False),
        sa.Column("st_ino", sa.Integer, nullable=False),
        sa.Column("created", sa.Float, nullable=False),
    )
    op.create_index("ix_ongoing_entries_collection_id", "ongoing_entries", ["collection_id"])


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
