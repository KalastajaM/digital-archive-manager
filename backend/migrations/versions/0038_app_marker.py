"""dam_meta: which app's migrations this database follows (``app = dam-public``)

Revision ids are bare numbers, and an earlier private build of dam numbers its own
migrations the same way, so a revision alone does not say whose ``0023`` a database is
at. The marker does; ``dam.db.engine.migrate`` checks it before migrating.

Revision ID: 0038
Revises: 0037
"""

import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dam_meta",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
    )
    op.execute("INSERT INTO dam_meta(key, value) VALUES ('app', 'dam-public')")


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
