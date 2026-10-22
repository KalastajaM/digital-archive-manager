"""file_barcodes.code nullable: a row with no code means "read, none found"

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("file_barcodes") as batch:
        batch.alter_column("code", existing_type=sa.Text, nullable=True)


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
