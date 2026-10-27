"""``TagRepo``: the tags given to files (``dam.index.repo``)."""

import time

from sqlalchemy import (
    Engine,
    func,
    select,
    update,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from dam.core.text import fold
from dam.db.engine import write_tx
from dam.db.tables import (
    file_tags,
    tags,
)


class TagRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def add(self, drive_id: str, tag_names: list[str]) -> None:
        now = time.time()
        with write_tx(self.engine) as conn:
            for name in tag_names:
                conn.execute(sqlite_insert(tags).values(name=name).on_conflict_do_nothing())
                tag_id = conn.execute(select(tags.c.id).where(tags.c.name == name)).scalar_one()
                added = conn.execute(
                    sqlite_insert(file_tags)
                    .values(drive_id=drive_id, tag_id=tag_id)
                    .on_conflict_do_nothing()
                )
                if added.rowcount:
                    conn.execute(update(tags).where(tags.c.id == tag_id).values(last_used_at=now))

    def set_for_file(self, drive_id: str, tag_names: list[str]) -> None:
        """Make ``tag_names`` the file's tags, exactly (one transaction). A tag the file
        did not have is marked as just used (the sidebar's recent tags)."""
        now = time.time()
        with write_tx(self.engine) as conn:
            had = set(
                conn.execute(
                    select(tags.c.name)
                    .join(file_tags, file_tags.c.tag_id == tags.c.id)
                    .where(file_tags.c.drive_id == drive_id)
                ).scalars()
            )
            conn.execute(file_tags.delete().where(file_tags.c.drive_id == drive_id))
            for name in tag_names:
                conn.execute(sqlite_insert(tags).values(name=name).on_conflict_do_nothing())
                tag_id = conn.execute(select(tags.c.id).where(tags.c.name == name)).scalar_one()
                conn.execute(sqlite_insert(file_tags).values(drive_id=drive_id, tag_id=tag_id))
                if name not in had:
                    conn.execute(update(tags).where(tags.c.id == tag_id).values(last_used_at=now))

    def popular(self, prefix: str = "", limit: int = 8) -> list[tuple[str, int]]:
        """Tags starting with ``prefix`` (case and accents ignored) with the number of files
        that have each, most used first, then by name."""
        used = func.count(file_tags.c.drive_id)
        query = (
            select(tags.c.name, used)
            .join(file_tags, file_tags.c.tag_id == tags.c.id)
            .group_by(tags.c.id)
        )
        folded = fold(prefix.strip())
        if folded:
            escaped = folded.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.where(func.dam_fold(tags.c.name).like(f"{escaped}%", escape="\\"))
        with self.engine.connect() as conn:
            rows = conn.execute(query.order_by(used.desc(), tags.c.name).limit(limit)).all()
        return [(name, int(n)) for name, n in rows]

    def for_file(self, drive_id: str) -> list[str]:
        with self.engine.connect() as conn:
            return list(
                conn.execute(
                    select(tags.c.name)
                    .join(file_tags, file_tags.c.tag_id == tags.c.id)
                    .where(file_tags.c.drive_id == drive_id)
                    .order_by(tags.c.name)
                ).scalars()
            )
