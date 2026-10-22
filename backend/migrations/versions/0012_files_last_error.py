"""files.last_error: why a file's content could not be indexed

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("files") as batch:
        # the readable reason stored with index_state "error" or "unsupported"
        batch.add_column(sa.Column("last_error", sa.Text, nullable=True))


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
