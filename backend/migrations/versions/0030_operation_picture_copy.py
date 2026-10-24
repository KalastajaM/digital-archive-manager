"""operations.method and operations.content_hash (how a rule picture was moved, and its hash)

Revision ID: 0030
Revises: 0029
"""

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("operations")}
    if "method" not in columns:
        op.add_column("operations", sa.Column("method", sa.Text, nullable=True))
    if "content_hash" not in columns:
        op.add_column("operations", sa.Column("content_hash", sa.Text, nullable=True))


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
