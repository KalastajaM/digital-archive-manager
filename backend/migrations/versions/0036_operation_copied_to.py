"""operations.copied_to and operations.followed (a folder moved across disks: where its
copy is, and the folder rows that followed it, for undo and recovery)

Revision ID: 0036
Revises: 0035
"""

import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("operations")}
    if "copied_to" not in columns:
        op.add_column("operations", sa.Column("copied_to", sa.Text, nullable=True))
    if "followed" not in columns:
        op.add_column("operations", sa.Column("followed", sa.Text, nullable=True))


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
