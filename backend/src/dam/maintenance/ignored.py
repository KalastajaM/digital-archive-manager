"""Maintenance results the owner chose to ignore: kept in the archive's database, left out
of every later result of their check, and listed so they can be taken back.

What an entry is keyed by, per kind (the API sends the key; ``versions`` is folded here):

- ``duplicates``: a group's sha256, with the drive ids it had (``members``)
- ``versions``: a name shared by files with different content, with their drive ids
- ``empty_folders``, ``broken_links``, ``names``: the drive id
- ``references``: ``"<collection|tray>-<owner id>-<item id or empty>-<drive id>"``
- ``moved``: ``"<old drive id>><new drive id>"``, a pair of "Moved outside dam"

A group stays ignored while every file in it was among ``members``; a new copy (or a
new file with the name) makes it show again. Nothing in the archive changes here."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from sqlalchemy import Engine, delete, select
from sqlalchemy.dialects.sqlite import insert

from dam.core.text import fold_name
from dam.db.engine import write_tx
from dam.db.tables import maintenance_ignored
from dam.services.errors import InvalidRequest

KINDS = (
    "duplicates",
    "versions",
    "empty_folders",
    "broken_links",
    "references",
    "names",
    "moved",
)
GROUPS = ("duplicates", "versions")


@dataclass
class Ignored:
    id: int
    kind: str
    key: str
    label: str
    created: float


class IgnoreList:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list(self) -> list[Ignored]:
        """Every ignored entry, newest first."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(maintenance_ignored).order_by(
                    maintenance_ignored.c.created.desc(), maintenance_ignored.c.id.desc()
                )
            ).all()
        return [Ignored(r.id, r.kind, r.key, r.label, r.created) for r in rows]

    def add(self, kind: str, key: str, label: str, members: Iterable[str] = ()) -> Ignored:
        """Ignore an entry (again: its label and members are replaced)."""
        if kind not in KINDS:
            raise InvalidRequest(f"unknown kind {kind!r}")
        key = fold_name(key) if kind == "versions" else key
        ids = sorted(set(members))
        if not key.strip() or not label.strip():
            raise InvalidRequest("key and label are required")
        if kind in GROUPS and not ids:
            raise InvalidRequest("a group needs the drive ids it has")
        values = {
            "kind": kind,
            "key": key,
            "label": label,
            "members": json.dumps(ids) if kind in GROUPS else None,
            "created": time.time(),
        }
        with write_tx(self.engine) as conn:
            conn.execute(
                insert(maintenance_ignored)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=["kind", "key"],
                    set_={k: values[k] for k in ("label", "members", "created")},
                )
            )
            row = conn.execute(
                select(maintenance_ignored).where(
                    maintenance_ignored.c.kind == kind, maintenance_ignored.c.key == key
                )
            ).one()
        return Ignored(row.id, row.kind, row.key, row.label, row.created)

    def unignore(self, ignored_id: int) -> bool:
        """Stop ignoring; False when there was no such entry."""
        with write_tx(self.engine) as conn:
            gone = conn.execute(
                delete(maintenance_ignored).where(maintenance_ignored.c.id == ignored_id)
            )
        return gone.rowcount > 0

    def _of(self, kind: str) -> dict[str, set[str] | None]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(maintenance_ignored.c.key, maintenance_ignored.c.members).where(
                    maintenance_ignored.c.kind == kind
                )
            ).all()
        return {r.key: set(json.loads(r.members)) if r.members else None for r in rows}

    def drop(self, kind: str, items: list, key: Callable, members: Callable | None = None):
        """``items`` without the ignored ones, and how many were left out. For a group,
        ``members(item)`` gives its drive ids: it is left out only while they are all
        among those it had when it was ignored."""
        ignored = self._of(kind)
        if not ignored:
            return items, 0
        kept = []
        for item in items:
            k = key(item)
            if k in ignored and (members is None or set(members(item)) <= (ignored[k] or set())):
                continue
            kept.append(item)
        return kept, len(items) - len(kept)
