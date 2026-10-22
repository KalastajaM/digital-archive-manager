"""checklist positions are unique per target

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make positions dense (0..n-1 per target) before they must be unique.
    op.execute(
        """
        UPDATE checklist_items SET position = (
            SELECT n FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY target_kind, target_id ORDER BY position, id
                ) - 1 AS n
                FROM checklist_items
            ) AS ranked WHERE ranked.id = checklist_items.id
        )
        """
    )
    op.create_index(
        "ux_checklist_items_position",
        "checklist_items",
        ["target_kind", "target_id", "position"],
        unique=True,
    )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
