"""identifier_names: the owner's name for a business ID; file_identifiers.name: the name
printed next to the ID in each file

Revision ID: 0044
Revises: 0043
"""

import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("file_identifiers")}
    if "name" not in columns:
        op.add_column("file_identifiers", sa.Column("name", sa.Text, nullable=True))
    if "identifier_names" not in inspector.get_table_names():
        op.create_table(
            "identifier_names",
            sa.Column("kind", sa.Text, primary_key=True),
            sa.Column("value", sa.Text, primary_key=True),
            sa.Column("name", sa.Text, nullable=False),
            sa.Column("set_by", sa.Text, nullable=False),
            sa.Column("set_at", sa.Float, nullable=False),
        )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
