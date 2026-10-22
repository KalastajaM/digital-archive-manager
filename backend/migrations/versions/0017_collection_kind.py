"""collections.kind: the built-in collections ★ Ongoing (starred) and ! Important

Revision ID: 0017
Revises: 0016

Adds ``kind`` (NULL for an ordinary collection; unique where set) and creates the two
built-ins, "Ongoing" (``starred``) and "Important" (``important``). An ordinary
collection that already has one of those names (folded) is renamed "<name>
(collection)" first ("(collection 2)", ... when that is taken too), and the rename is
written at the top of the collection's note, so the user sees why.

The built-ins start with ``publish = {}``: the Ongoing publisher of this round skips
them (it also never lists them); publishing them is the next step's job.
"""

import json
import time
import unicodedata

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

BUILTINS = (("starred", "Ongoing"), ("important", "Important"))


def _fold(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


def _free(conn, base: str) -> str:
    taken = {r[0] for r in conn.execute(sa.text("SELECT name_fold FROM collections"))}
    candidate = f"{base} (collection)"
    n = 2
    while _fold(candidate) in taken:
        candidate = f"{base} (collection {n})"
        n += 1
    return candidate


def upgrade() -> None:
    op.execute("ALTER TABLE collections ADD COLUMN kind TEXT")
    op.create_index(
        "ux_collections_kind",
        "collections",
        ["kind"],
        unique=True,
        sqlite_where=sa.text("kind IS NOT NULL"),
    )
    conn = op.get_bind()
    now = time.time()
    for kind, name in BUILTINS:
        clash = conn.execute(
            sa.text("SELECT id, name FROM collections WHERE name_fold = :f"),
            {"f": _fold(name)},
        ).one_or_none()
        if clash is not None:
            new = _free(conn, clash.name)
            conn.execute(
                sa.text("UPDATE collections SET name = :n, name_fold = :f WHERE id = :id"),
                {"n": new, "f": _fold(new), "id": clash.id},
            )
            line = (
                f"The app renamed this collection from {clash.name!r} to {new!r}: "
                f"{name!r} is now the built-in collection for "
                f"{'★ starred' if kind == 'starred' else '! Important'} files."
            )
            note = conn.execute(
                sa.text(
                    "SELECT id, text FROM notes WHERE target_kind = 'collection' AND target_id = :t"
                ),
                {"t": str(clash.id)},
            ).one_or_none()
            if note is None:
                conn.execute(
                    sa.text(
                        "INSERT INTO notes(target_kind, target_id, text, updated)"
                        " VALUES ('collection', :t, :x, :u)"
                    ),
                    {"t": str(clash.id), "x": line, "u": now},
                )
            else:
                text = f"{line}\n\n{note.text}" if note.text.strip() else line
                conn.execute(
                    sa.text("UPDATE notes SET text = :x, updated = :u WHERE id = :id"),
                    {"x": text, "u": now, "id": note.id},
                )
        conn.execute(
            sa.text(
                "INSERT INTO collections(name, name_fold, state, created, publish, kind)"
                " VALUES (:n, :f, 'open', :c, :p, :k)"
            ),
            {"n": name, "f": _fold(name), "c": now, "p": json.dumps({}), "k": kind},
        )


def downgrade() -> None:
    # Downgrades are intentionally unsupported (as in 0001).
    raise NotImplementedError("downgrade is not supported")
