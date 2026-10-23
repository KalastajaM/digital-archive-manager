"""file_qr_codes: the filing-code QR stickers read from a file's scan

Revision ID: 0026
Revises: 0025
"""

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No backfill here: the barcode pass reads inbox files that have no row once.
    op.create_table(
        "file_qr_codes",
        sa.Column("drive_id", sa.Text, sa.ForeignKey("files.drive_id"), primary_key=True),
        sa.Column("sha256", sa.Text, nullable=True),
        sa.Column("reads", sa.Text, nullable=False),
        sa.Column("read_at", sa.Float, nullable=False),
    )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
