"""initial schema

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("drive_id", sa.Text, primary_key=True),
        sa.Column("path", sa.Text, nullable=False, unique=True),
        sa.Column("path_nfc", sa.Text, nullable=False),
        sa.Column("name", sa.Text),
        sa.Column("ext", sa.Text),
        sa.Column("is_dir", sa.Boolean),
        sa.Column("is_link", sa.Boolean),
        sa.Column("link_target", sa.Text, nullable=True),
        sa.Column("size", sa.Integer),
        sa.Column("mtime", sa.Float),
        sa.Column("sha256", sa.Text, nullable=True),
        sa.Column("doc_date", sa.Date, nullable=True),
        sa.Column("index_state", sa.Text),
        sa.Column("retry_at", sa.Float, nullable=True),
        sa.Column("attempts", sa.Integer, server_default="0"),
        sa.Column("missing", sa.Boolean, server_default=sa.false()),
        sa.Column("last_seen", sa.Float),
    )
    op.create_table(
        "file_text",
        sa.Column("drive_id", sa.Text, sa.ForeignKey("files.drive_id"), primary_key=True),
        sa.Column("text", sa.Text),
        sa.Column("extractor", sa.Text),
        sa.Column("ocr_used", sa.Boolean),
    )
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, unique=True),
    )
    op.create_table(
        "file_tags",
        sa.Column("drive_id", sa.Text, sa.ForeignKey("files.drive_id"), primary_key=True),
        sa.Column("tag_id", sa.Integer, sa.ForeignKey("tags.id"), primary_key=True),
    )
    op.create_table(
        "operations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("batch_id", sa.Text),
        sa.Column("seq", sa.Integer),
        sa.Column("kind", sa.Text),
        sa.Column("src", sa.Text, nullable=True),
        sa.Column("dst", sa.Text, nullable=True),
        sa.Column("drive_id", sa.Text, nullable=True),
        sa.Column("size", sa.Integer, nullable=True),
        sa.Column("mtime", sa.Float, nullable=True),
        sa.Column("state", sa.Text),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("origin", sa.Text),
        sa.Column("undo_of", sa.Text, nullable=True),
        sa.Column("created", sa.Float),
        sa.Column("finished", sa.Float, nullable=True),
    )
    op.execute(
        "CREATE VIRTUAL TABLE file_fts USING fts5("
        "drive_id UNINDEXED, name, path, text, "
        "tokenize='unicode61 remove_diacritics 2')"
    )


def downgrade() -> None:
    # Downgrades are intentionally unsupported: the app never deletes data.
    raise NotImplementedError("downgrade is not supported")
