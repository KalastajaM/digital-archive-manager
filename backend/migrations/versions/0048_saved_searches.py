"""saved_searches: the owner's saved searches, a name and a query each

Revision ID: 0048
Revises: 0047
"""

import sqlalchemy as sa
from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "saved_searches" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "saved_searches",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.Text, nullable=False),
            sa.Column("name_fold", sa.Text, nullable=False, unique=True),
            sa.Column("query", sa.Text, nullable=False),
            sa.Column("tag_mode", sa.Text, nullable=False, server_default="all"),
            sa.Column("created_at", sa.Float, nullable=False),
            sa.Column("updated_at", sa.Float, nullable=False),
        )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
