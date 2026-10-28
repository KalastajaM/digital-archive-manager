"""special_folder_renames: renames of the app's special folders (Settings, Archive folders)

Revision ID: 0042
Revises: 0041
"""

import sqlalchemy as sa
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "special_folder_renames" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "special_folder_renames",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("batch_id", sa.Text, nullable=False, unique=True),
            sa.Column("key", sa.Text, nullable=False),
            sa.Column("old", sa.Text, nullable=False),
            sa.Column("new", sa.Text, nullable=False),
            sa.Column("state", sa.Text, nullable=False),
            sa.Column("folders", sa.Integer, nullable=False, server_default="1"),
            sa.Column("changes", sa.Text, nullable=True),
            sa.Column("note", sa.Text, nullable=True),
            sa.Column("created", sa.Float, nullable=False),
            sa.Column("finished", sa.Float, nullable=True),
        )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
