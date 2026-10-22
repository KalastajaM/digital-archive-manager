"""ai_calls (the AI call log) and ai_cache (results by file sha, task, model, prompt)

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_calls",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("at", sa.Float, nullable=False),
        sa.Column("task", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("files", sa.JSON, nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_eur", sa.Float, nullable=False, server_default="0"),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_ai_calls_at", "ai_calls", ["at"])
    op.create_table(
        "ai_cache",
        sa.Column("sha_key", sa.Text, primary_key=True),
        sa.Column("task", sa.Text, primary_key=True),
        sa.Column("model", sa.Text, primary_key=True),
        sa.Column("prompt_version", sa.Text, primary_key=True),
        sa.Column("data", sa.JSON, nullable=False),
        sa.Column("at", sa.Float, nullable=False),
    )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
