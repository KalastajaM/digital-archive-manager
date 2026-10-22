"""collection_groups (nested, per collection), collection_members.group_id, summaries

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "collection_groups",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "collection_id",
            sa.Integer,
            sa.ForeignKey("collections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parent_id", sa.Integer, sa.ForeignKey("collection_groups.id"), nullable=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("name_fold", sa.Text, nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("summary", sa.Text, nullable=False, server_default=""),
    )
    op.create_index(
        "ix_collection_groups_collection_id_parent_id",
        "collection_groups",
        ["collection_id", "parent_id"],
    )
    with op.batch_alter_table("collection_members") as batch:
        # no FK: the service keeps it pointing at a group of the same collection
        batch.add_column(sa.Column("group_id", sa.Integer, nullable=True))
    with op.batch_alter_table("collections") as batch:
        batch.add_column(sa.Column("summary", sa.Text, nullable=False, server_default=""))


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
