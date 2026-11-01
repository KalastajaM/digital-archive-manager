"""content_changes: files whose content differs from what dam last knew of them

Revision ID: 0049
Revises: 0048
"""

import sqlalchemy as sa
from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "content_changes" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "content_changes",
            sa.Column("drive_id", sa.Text, primary_key=True),
            sa.Column("was_sha256", sa.Text, nullable=False),
            sa.Column("was_size", sa.Integer),
            sa.Column("was_mtime", sa.Float),
            sa.Column("sha256", sa.Text, nullable=True),
            sa.Column("size", sa.Integer),
            sa.Column("mtime", sa.Float),
            sa.Column("detected_at", sa.Float, nullable=True),
            sa.Column("seen_at", sa.Float, nullable=True),
        )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
