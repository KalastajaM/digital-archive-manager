"""rule_outcomes: what each learned filing rule suggested and whether it was kept

Revision ID: 0027
Revises: 0026
"""

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rule_outcomes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("batch_id", sa.Text, nullable=False),
        sa.Column("drive_id", sa.Text, nullable=False),
        sa.Column("rule_id", sa.Text, nullable=False),
        sa.Column("field", sa.Text, nullable=False),
        sa.Column("kept", sa.Boolean, nullable=False),
        sa.Column("created", sa.Float, nullable=False),
    )
    op.create_index("ix_rule_outcomes_batch_id", "rule_outcomes", ["batch_id"])
    op.create_index("ix_rule_outcomes_rule_id", "rule_outcomes", ["rule_id"])


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
