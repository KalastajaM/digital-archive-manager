"""made_folders: folders a New folder / layout batch made, by identity (for undo)

Revision ID: 0023
Revises: 0022
"""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "made_folders" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "made_folders",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("batch_id", sa.Text, nullable=False),
        sa.Column("rel", sa.Text, nullable=False),
        # st_dev / st_ino as text: a 64-bit file index does not always fit SQLite's integer
        sa.Column("st_dev", sa.Text, nullable=False),
        sa.Column("st_ino", sa.Text, nullable=False),
        sa.Column("created", sa.Float, nullable=False),
        sa.UniqueConstraint("batch_id", "rel", name="uq_made_folders_batch_rel"),
    )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
