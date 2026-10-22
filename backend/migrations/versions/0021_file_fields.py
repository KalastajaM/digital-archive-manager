"""file_fields (a file's scan fields as the user edited them)

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A database that ran this as the short-lived revision 0017 already has the table.
    if sa.inspect(op.get_bind()).has_table("file_fields"):
        return
    op.create_table(
        "file_fields",
        sa.Column("drive_id", sa.Text, primary_key=True),
        sa.Column("fields", sa.Text, nullable=False),
        sa.Column("updated", sa.Float, nullable=False),
    )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
