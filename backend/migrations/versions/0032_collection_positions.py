"""collections.position: the owner's order of sibling collections

Revision ID: 0032
Revises: 0031
"""

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "collections", sa.Column("position", sa.Integer, nullable=False, server_default="0")
    )
    # Backfill from the order shown until now: per parent, by folded name, then id. The
    # two built-in collections (kind set) are not movable and keep 0.
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, parent_id FROM collections WHERE kind IS NULL ORDER BY name_fold, id")
    ).all()
    next_at: dict[int | None, int] = {}
    for cid, parent in rows:
        n = next_at.get(parent, 0)
        next_at[parent] = n + 1
        conn.execute(
            sa.text("UPDATE collections SET position = :p WHERE id = :i"), {"p": n, "i": cid}
        )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
