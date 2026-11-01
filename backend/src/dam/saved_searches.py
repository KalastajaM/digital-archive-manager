"""The owner's saved searches: a name and a query each, listed in the sidebar.

A saved search keeps the query as Browse's address does (``q`` and ``tag_mode``), so
opening one is opening that address. They are dam's own data in the index database (not
archive files), so nothing here goes through the operation layer or is journaled.
"""

import re
import time
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Engine, delete, insert, select, update

from dam.core.text import fold_name
from dam.db.engine import write_tx
from dam.db.tables import saved_searches

MAX_NAME = 200
MAX_QUERY = 2000

TagMode = Literal["all", "any"]


class SavedSearchError(Exception):
    """A change that cannot be made; ``kind``: "exists", "missing" or "invalid"."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass
class SavedSearch:
    id: int
    name: str
    query: str
    tag_mode: TagMode


def _name(name: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise SavedSearchError("invalid", "A saved search needs a name")
    if len(name) > MAX_NAME:
        raise SavedSearchError("invalid", f"A name can have at most {MAX_NAME} characters")
    return name


def _query(query: str) -> str:
    query = query.strip()
    if not query:
        raise SavedSearchError("invalid", "There is no search to save")
    if len(query) > MAX_QUERY:
        raise SavedSearchError("invalid", f"A search can have at most {MAX_QUERY} characters")
    return query


def _row(r) -> SavedSearch:
    return SavedSearch(r.id, r.name, r.query, "any" if r.tag_mode == "any" else "all")


class SavedSearches:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list(self) -> list[SavedSearch]:
        """Every saved search, by name (case ignored, numbers in order: "2" before "10")."""
        with self.engine.connect() as conn:
            rows = [_row(r) for r in conn.execute(select(saved_searches))]
        return sorted(rows, key=lambda s: _natural(s.name))

    def save(
        self, name: str, query: str, tag_mode: TagMode = "all", replace: bool = False
    ) -> SavedSearch:
        """Save ``query`` under ``name``. A name in use (case ignored) is "exists" unless
        ``replace``: then that search gets the new query and mode (and the name as typed)
        and keeps its id."""
        name, query = _name(name), _query(query)
        now = time.time()
        with write_tx(self.engine) as conn:
            have = conn.execute(
                select(saved_searches.c.id).where(saved_searches.c.name_fold == fold_name(name))
            ).scalar()
            if have is not None and not replace:
                raise SavedSearchError("exists", f'A search named "{name}" exists')
            values = {"name": name, "query": query, "tag_mode": tag_mode, "updated_at": now}
            if have is None:
                have = conn.execute(
                    insert(saved_searches).values(
                        **values, name_fold=fold_name(name), created_at=now
                    )
                ).inserted_primary_key[0]
            else:
                conn.execute(
                    update(saved_searches).where(saved_searches.c.id == have).values(**values)
                )
        return SavedSearch(have, name, query, tag_mode)

    def rename(self, search_id: int, name: str) -> SavedSearch:
        """Give a saved search another name; "exists" when another one has it."""
        name = _name(name)
        with write_tx(self.engine) as conn:
            row = conn.execute(
                select(saved_searches).where(saved_searches.c.id == search_id)
            ).first()
            if row is None:
                raise SavedSearchError("missing", "That saved search is gone")
            other = conn.execute(
                select(saved_searches.c.id).where(
                    saved_searches.c.name_fold == fold_name(name), saved_searches.c.id != search_id
                )
            ).scalar()
            if other is not None:
                raise SavedSearchError("exists", f'A search named "{name}" exists')
            conn.execute(
                update(saved_searches)
                .where(saved_searches.c.id == search_id)
                .values(name=name, name_fold=fold_name(name), updated_at=time.time())
            )
        return SavedSearch(row.id, name, row.query, "any" if row.tag_mode == "any" else "all")

    def delete(self, search_id: int) -> None:
        with write_tx(self.engine) as conn:
            gone = conn.execute(delete(saved_searches).where(saved_searches.c.id == search_id))
            if gone.rowcount == 0:
                raise SavedSearchError("missing", "That saved search is gone")


def _natural(name: str) -> list:
    """Sort key: case ignored, runs of digits compared as numbers."""
    return [
        (0, int(p), "") if p.isdigit() else (1, 0, p)
        for p in re.split(r"(\d+)", fold_name(name))
        if p
    ]
