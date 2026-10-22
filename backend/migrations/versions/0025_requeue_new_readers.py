"""Re-queue unsupported files whose type now has a text reader

Revision ID: 0025
Revises: 0024
"""

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

# types read since this migration: xlsx/xls/pptx, textutil (doc and friends), iWork
EXTS = (
    "xlsx", "xlsm", "xls", "pptx", "doc", "dot", "dotx", "docm", "odt", "html", "htm",
    "webarchive", "pages", "numbers", "key",
)  # fmt: skip


def upgrade() -> None:
    marks = ", ".join(f":e{i}" for i in range(len(EXTS)))
    op.get_bind().execute(
        sa.text(
            "UPDATE files SET index_state = 'pending', attempts = 0, retry_at = NULL, "
            f"last_error = NULL WHERE index_state = 'unsupported' AND lower(ext) IN ({marks})"
        ),
        {f"e{i}": e for i, e in enumerate(EXTS)},
    )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
