"""file_locks: files the owner locked (a safety catch against file changes)

Revision ID: 0031
Revises: 0030
"""

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_locks",
        sa.Column("drive_id", sa.Text, primary_key=True),
        sa.Column("locked_at", sa.Float, nullable=False),
    )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
