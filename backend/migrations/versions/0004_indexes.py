"""indexes for path lookups, the content queue, parked rows and journal batches

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_files_path_nfc", "files", ["path_nfc"])
    op.create_index("ix_files_index_state_retry_at", "files", ["index_state", "retry_at"])
    op.create_index("ix_files_parked_at", "files", ["parked_at"])
    op.create_index("ix_operations_batch_id", "operations", ["batch_id"])


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
