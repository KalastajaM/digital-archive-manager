"""file_assigned_codes: the filing code the owner gave an inbox file in the app

Revision ID: 0035
Revises: 0034
"""

import sqlalchemy as sa
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "file_assigned_codes" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "file_assigned_codes",
            sa.Column("drive_id", sa.Text, sa.ForeignKey("files.drive_id"), primary_key=True),
            sa.Column("code", sa.Text, nullable=False),
            sa.Column("assigned_at", sa.Float, nullable=False),
        )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
