"""trays, collections, notes and reminders

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tray_id", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("fields", sa.JSON, nullable=False),
        sa.Column("date", sa.Date, nullable=True),
        sa.Column("state", sa.Text, nullable=False, server_default="open"),
        sa.Column("created", sa.Float, nullable=False),
        sa.Column("done_at", sa.Float, nullable=True),
        sa.Column("done_fields", sa.JSON, nullable=True),
        sa.Column("created_by_batch", sa.Text, nullable=True),
    )
    op.create_index("ix_items_state_date", "items", ["state", "date"])
    op.create_index("ix_items_tray_id_state", "items", ["tray_id", "state"])
    op.create_index("ix_items_created_by_batch", "items", ["created_by_batch"])

    op.create_table(
        "item_files",
        sa.Column(
            "item_id", sa.Integer, sa.ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("drive_id", sa.Text, primary_key=True),
    )
    op.create_index("ix_item_files_drive_id", "item_files", ["drive_id"])

    op.create_table(
        "item_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "item_id", sa.Integer, sa.ForeignKey("items.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("at", sa.Float, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("data", sa.JSON, nullable=False),
    )

    op.create_table(
        "reminders_sent",
        sa.Column(
            "item_id", sa.Integer, sa.ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("rule", sa.Text, primary_key=True),
        sa.Column("occasion", sa.Date, primary_key=True),
        sa.Column("fired_at", sa.Float, nullable=False),
        sa.Column("channels", sa.JSON, nullable=False),
    )

    op.create_table(
        "collections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("name_fold", sa.Text, nullable=False, unique=True),
        sa.Column("state", sa.Text, nullable=False, server_default="open"),
        sa.Column("created", sa.Float, nullable=False),
        sa.Column("closed_at", sa.Float, nullable=True),
        sa.Column(
            "publish", sa.JSON, nullable=False, server_default=sa.text("'{\"ongoing\": true}'")
        ),
        sa.Column("ongoing_rel", sa.Text, nullable=True),
    )

    op.create_table(
        "collection_members",
        sa.Column(
            "collection_id",
            sa.Integer,
            sa.ForeignKey("collections.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("drive_id", sa.Text, primary_key=True),
        sa.Column("added", sa.Float, nullable=False),
        sa.Column("created_by_batch", sa.Text, nullable=True),
    )
    op.create_index("ix_collection_members_drive_id", "collection_members", ["drive_id"])
    op.create_index(
        "ix_collection_members_created_by_batch", "collection_members", ["created_by_batch"]
    )

    op.create_table(
        "notes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("target_kind", sa.Text, nullable=False),
        sa.Column("target_id", sa.Text, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("updated", sa.Float, nullable=False),
        sa.Column("created_by_batch", sa.Text, nullable=True),
        sa.UniqueConstraint("target_kind", "target_id"),
    )
    op.create_index("ix_notes_created_by_batch", "notes", ["created_by_batch"])

    op.create_table(
        "checklist_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("target_kind", sa.Text, nullable=False),
        sa.Column("target_id", sa.Text, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("done", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("position", sa.Integer, nullable=False),
    )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
