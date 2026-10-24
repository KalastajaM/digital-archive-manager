"""file_layouts: where the text of page 1 sits

Revision ID: 0028
Revises: 0027
"""

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No backfill here: the layout pass reads page 1 of files that have no row.
    op.create_table(
        "file_layouts",
        sa.Column("drive_id", sa.Text, sa.ForeignKey("files.drive_id"), primary_key=True),
        sa.Column("sha256", sa.Text, nullable=True),
        sa.Column("lines", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("read_at", sa.Float, nullable=False),
    )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
