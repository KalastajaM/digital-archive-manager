"""member_link_names: the last link_name a member had in a collection

Revision ID: 0020
Revises: 0019

When a member row with a ``link_name`` (a converted shortcut's own name) is removed
(unmarked, or an undo), the name is remembered per (collection, file), and a later
add without an explicit name gets it back: a converted file that is unmarked and
marked again keeps its shortcut's name, so the undo of its conversion still finds
the app's link where the conversion put it.
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "member_link_names",
        sa.Column(
            "collection_id",
            sa.Integer,
            sa.ForeignKey("collections.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("drive_id", sa.Text, primary_key=True),
        sa.Column("link_name", sa.Text, nullable=False),
    )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
