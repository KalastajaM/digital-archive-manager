"""collection_groups.created_by_batch: groups the Important conversion made

Revision ID: 0018
Revises: 0017

The conversion of a ``##. Important`` folder creates one Important group per real
subfolder, in one journaled batch. Like the memberships (``collection_members.
created_by_batch``), those groups go again when the batch is undone, provided they
are still empty (no member, no subgroup): a group the user has used since stays.
"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def _heal_0017() -> None:
    """Run 0017 here when the database skipped it.

    Main briefly shipped ``file_fields`` as revision 0017 (now 0021). A database that
    ran it is stamped 0017 without ``collections.kind``; Alembic would skip the real
    0017, so it is applied here instead.
    """
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("collections")}
    if "kind" in cols:
        return
    path = Path(__file__).with_name("0017_collection_kind.py")
    spec = importlib.util.spec_from_file_location("_dam_migration_0017", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.upgrade()


def upgrade() -> None:
    _heal_0017()
    op.execute("ALTER TABLE collection_groups ADD COLUMN created_by_batch TEXT")
    op.create_index(
        "ix_collection_groups_created_by_batch", "collection_groups", ["created_by_batch"]
    )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
