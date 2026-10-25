"""tags: pins, groups and last use; groups for the Tags screen; an index on file_tags.tag_id


Revision ID: 0033
Revises: 0032
"""

import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("tags")}
    if "pinned_at" not in columns:
        op.add_column("tags", sa.Column("pinned_at", sa.Float, nullable=True))
    if "group_id" not in columns:
        op.add_column("tags", sa.Column("group_id", sa.Integer, nullable=True))
    if "last_used_at" not in columns:
        op.add_column("tags", sa.Column("last_used_at", sa.Float, nullable=True))
    if "tag_groups" not in inspector.get_table_names():
        op.create_table(
            "tag_groups",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.Text, nullable=False, unique=True),
        )
    indexes = {i["name"] for i in inspector.get_indexes("file_tags")}
    if "ix_file_tags_tag_id" not in indexes:
        op.create_index("ix_file_tags_tag_id", "file_tags", ["tag_id"])


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
