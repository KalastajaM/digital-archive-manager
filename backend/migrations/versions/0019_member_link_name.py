"""collection_members.link_name: the name a member's published link keeps

Revision ID: 0019
Revises: 0018

A converted shortcut keeps the user's own name (stars, Task 3 ruling): the
conversion records it on the membership row when it differs from the file's name,
and the publisher names the member's link after it (``_2`` on a clash, as ever).
NULL: the file's own name.
"""

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE collection_members ADD COLUMN link_name TEXT")


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
