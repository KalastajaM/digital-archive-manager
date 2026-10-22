"""collections.parent_id (parent collections, nested to any depth)

Revision ID: 0015
Revises: 0014
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No cascade: the service refuses to orphan a collection (there is no delete, and
    # close/reopen/set_parent keep the tree consistent). A plain ADD COLUMN, written
    # out because Alembic's SQLite dialect will not emit one with a REFERENCES clause
    # (SQLite allows it when the default is NULL). Batch mode would recreate the
    # table, which other tables reference with ON DELETE CASCADE.
    op.execute("ALTER TABLE collections ADD COLUMN parent_id INTEGER REFERENCES collections (id)")
    op.create_index("ix_collections_parent_id", "collections", ["parent_id"])


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
