"""file_barcodes: the bank barcode read from a file's scan

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_barcodes",
        sa.Column("drive_id", sa.Text, sa.ForeignKey("files.drive_id"), primary_key=True),
        sa.Column("code", sa.Text, nullable=False),
        sa.Column("sha256", sa.Text, nullable=True),
        sa.Column("read_at", sa.Float, nullable=False),
    )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
