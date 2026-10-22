"""file_summaries (a file's AI or user summary, with the sha256 it describes)

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_summaries",
        sa.Column("drive_id", sa.Text, primary_key=True),
        sa.Column("source", sa.Text, primary_key=True),
        sa.Column("sha256", sa.Text, nullable=True),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("key_facts", sa.JSON, nullable=False),
        sa.Column("at", sa.Float, nullable=False),
    )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
