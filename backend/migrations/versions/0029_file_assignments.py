"""file_assignments: who a document is from and for, as the owner said

Revision ID: 0029
Revises: 0028
"""

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_assignments",
        sa.Column("drive_id", sa.Text, primary_key=True),
        sa.Column("sender", sa.Text, nullable=True),
        sa.Column("person", sa.Text, nullable=True),
        sa.Column("set_by", sa.Text, nullable=False),
        sa.Column("set_at", sa.Float, nullable=False),
    )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
