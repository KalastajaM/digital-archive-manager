"""file_identifiers: business IDs, IBANs and domains found in each file's text

Revision ID: 0043
Revises: 0042
"""

import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "file_identifiers" not in tables:
        op.create_table(
            "file_identifiers",
            sa.Column("drive_id", sa.Text, primary_key=True),
            sa.Column("kind", sa.Text, primary_key=True),
            sa.Column("value", sa.Text, primary_key=True),
            sa.Column("sha256", sa.Text, nullable=False),
        )
        op.create_index("ix_file_identifiers_kind_value", "file_identifiers", ["kind", "value"])
    if "file_identifier_reads" not in tables:
        op.create_table(
            "file_identifier_reads",
            sa.Column("drive_id", sa.Text, primary_key=True),
            sa.Column("sha256", sa.Text, nullable=False),
            sa.Column("signature", sa.Text, nullable=False),
            sa.Column("read_at", sa.Float, nullable=False),
        )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
