"""file_address_zones: the address area of one document, as the owner drew it

Revision ID: 0047
Revises: 0046
"""

import sqlalchemy as sa
from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "file_address_zones" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "file_address_zones",
            sa.Column("drive_id", sa.Text, primary_key=True),
            sa.Column("x0", sa.Float, nullable=True),
            sa.Column("y0", sa.Float, nullable=True),
            sa.Column("x1", sa.Float, nullable=True),
            sa.Column("y1", sa.Float, nullable=True),
            sa.Column("set_at", sa.Float, nullable=False),
        )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
