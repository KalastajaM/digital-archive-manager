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
    inspector = sa.inspect(op.get_bind())
    if "special_folder_renames" in inspector.get_table_names():
        # a database that ran this revision before ``changes`` and ``note`` were added to it
        have = {c["name"] for c in inspector.get_columns("special_folder_renames")}
        for name in ("changes", "note"):
            if name not in have:
                op.add_column("special_folder_renames", sa.Column(name, sa.Text, nullable=True))
    else:
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
