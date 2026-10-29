"""file_layouts.lines is stored zlib-compressed (a BLOB)

The JSON of a page-1 layout repeats each line's text and every word's box with five
decimals: on a real archive 126 MB, 28 MB compressed. The table is made again with a BLOB
``lines`` (the rest unchanged) and every row compressed in place. A row whose JSON is
already unreadable stays as it was; the reader skips it, as before.

Revision ID: 0045
Revises: 0044
"""

import zlib

import sqlalchemy as sa
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None

BATCH = 500


def upgrade() -> None:
    bind = op.get_bind()
    lines = next(c for c in sa.inspect(bind).get_columns("file_layouts") if c["name"] == "lines")
    if not isinstance(lines["type"], sa.LargeBinary):
        with op.batch_alter_table("file_layouts") as batch:
            batch.alter_column("lines", type_=sa.LargeBinary, existing_nullable=False)
    last = ""
    while True:
        rows = bind.execute(
            sa.text(
                "SELECT drive_id, lines FROM file_layouts WHERE drive_id > :last "
                "ORDER BY drive_id LIMIT :n"
            ),
            {"last": last, "n": BATCH},
        ).all()
        if not rows:
            break
        last = rows[-1].drive_id
        for drive_id, value in rows:
            packed = _packed(value)
            if packed is not None:
                bind.execute(
                    sa.text("UPDATE file_layouts SET lines = :v WHERE drive_id = :id"),
                    {"v": packed, "id": drive_id},
                )


def _packed(value: bytes | str) -> bytes | None:
    """``value`` compressed, or None when it already is (or is not JSON text at all)."""
    raw = value.encode() if isinstance(value, str) else bytes(value)
    if raw[:1] not in (b"[", b"{"):
        return None
    return zlib.compress(raw, 6)


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
