"""file identity: st_dev / st_ino as text, plus st_birth (the creation time)

ongoing_entries held st_dev / st_ino as INTEGER, which cannot store a Windows file
index (unsigned 64-bit or more). They become TEXT (SQLite copies the numbers as their
decimal text, nothing is lost) and both ongoing_entries and made_folders get a
nullable ``st_birth`` ("b:<ns>" / "c:<ns>", see dam.ops.identity). Existing rows keep
NULL there: such an identity is compared on (dev, ino) only, as before.

Revision ID: 0024
Revises: 0023
"""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "st_birth" not in _columns("ongoing_entries"):
        with op.batch_alter_table("ongoing_entries") as batch:
            batch.alter_column("st_dev", existing_type=sa.Integer, type_=sa.Text, nullable=False)
            batch.alter_column("st_ino", existing_type=sa.Integer, type_=sa.Text, nullable=False)
            batch.add_column(sa.Column("st_birth", sa.Text, nullable=True))
    if "st_birth" not in _columns("made_folders"):
        with op.batch_alter_table("made_folders") as batch:
            batch.add_column(sa.Column("st_birth", sa.Text, nullable=True))


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
