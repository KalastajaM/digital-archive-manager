"""Managing tags: the Tags screen's list, create, rename, merge, delete, pins, groups and
the sidebar's pinned and recent tags.

Tags are dam's own data in the index database (not archive files), so none of this goes
through the operation layer and nothing is journaled. Every change returns an ``undo``
record that ``undo`` applies: tags to remove, files to unlink and tags to restore.
"""

import time
from dataclasses import dataclass, field

from sqlalchemy import Connection, Engine, delete, func, insert, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from dam.core.text import fold
from dam.db.engine import write_tx
from dam.db.tables import file_tags, files, tag_groups, tags

SIDEBAR_TAGS = 8


class TagError(Exception):
    """A tag change that cannot be made; ``kind``: "exists", "missing" or "invalid"."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass
class TagSnapshot:
    """A tag as it was, with the files that had it."""

    name: str
    pinned_at: float | None
    group_id: int | None
    last_used_at: float | None
    drive_ids: list[str]


@dataclass
class Unlink:
    name: str
    drive_ids: list[str]


@dataclass
class TagUndo:
    drop: list[str] = field(default_factory=list)
    detach: list[Unlink] = field(default_factory=list)
    restore: list[TagSnapshot] = field(default_factory=list)


@dataclass
class MergePlan:
    """What a merge would do: files that gain the target tag, tags that go away."""

    into: str
    gains: int
    removes: list[str]
    undo: TagUndo | None = None


_live = (files.c.missing.is_not(True)) & (files.c.parked_at.is_(None))


def _clean(name: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise TagError("invalid", "A tag needs a name")
    if len(name) > 200:
        raise TagError("invalid", "A tag name can have at most 200 characters")
    return name


def _chunks(items: list[str], size: int = 500):
    for i in range(0, len(items), size):
        yield items[i : i + size]


class TagAdmin:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # -- reading ------------------------------------------------------------

    def _counts(self, conn: Connection) -> dict[int, int]:
        rows = conn.execute(
            select(file_tags.c.tag_id, func.count())
            .select_from(file_tags.join(files, files.c.drive_id == file_tags.c.drive_id))
            .where(_live)
            .group_by(file_tags.c.tag_id)
        )
        return {tag_id: n for tag_id, n in rows}

    def listing(self, query: str = "") -> dict:
        """Every tag (also those no file has yet) with its live file count, pin and group,
        and the groups. ``query`` keeps the tags whose name contains it (case and accents
        ignored)."""
        wanted = fold(query.strip())
        with self.engine.connect() as conn:
            counts = self._counts(conn)
            rows = conn.execute(select(tags).order_by(tags.c.name)).all()
            groups = [
                {"id": g.id, "name": g.name}
                for g in conn.execute(select(tag_groups).order_by(func.lower(tag_groups.c.name)))
            ]
        out = [
            {
                "name": r.name,
                "files": counts.get(r.id, 0),
                "pinned": r.pinned_at is not None,
                "group_id": r.group_id,
            }
            for r in rows
            if not wanted or wanted in fold(r.name)
        ]
        return {"tags": out, "groups": groups}

    def sidebar(self, limit: int = SIDEBAR_TAGS) -> list[dict]:
        """Up to ``limit`` tags: the pinned ones first (oldest pin first), then the most
        recently used (put on a file) that are not pinned, to fill up."""
        with self.engine.connect() as conn:
            counts = self._counts(conn)
            pinned = conn.execute(
                select(tags)
                .where(tags.c.pinned_at.is_not(None))
                .order_by(tags.c.pinned_at, tags.c.name)
            ).all()
            recent = conn.execute(
                select(tags)
                .where(tags.c.pinned_at.is_(None), tags.c.last_used_at.is_not(None))
                .order_by(tags.c.last_used_at.desc(), tags.c.name)
            ).all()
        out = [(r, True) for r in pinned] + [(r, False) for r in recent if counts.get(r.id, 0) > 0]
        return [
            {"name": r.name, "files": counts.get(r.id, 0), "pinned": pin} for r, pin in out[:limit]
        ]

    def drive_ids(self, name: str) -> list[str]:
        with self.engine.connect() as conn:
            tag_id = self._id(conn, name)
            return list(
                conn.execute(
                    select(file_tags.c.drive_id).where(file_tags.c.tag_id == tag_id)
                ).scalars()
            )

    # -- helpers --------------------------------------------------------------

    def _id(self, conn: Connection, name: str) -> int:
        found = conn.execute(select(tags.c.id).where(tags.c.name == name)).scalar()
        if found is None:
            raise TagError("missing", f"There is no tag called '{name}'")
        return found

    def _clash(self, conn: Connection, name: str, ignore: int | None = None) -> str | None:
        """The name of another tag that is the same but for case and accents."""
        wanted = fold(name)
        for tag_id, other in conn.execute(select(tags.c.id, tags.c.name)):
            if tag_id != ignore and fold(other) == wanted:
                return other
        return None

    def _snapshot(self, conn: Connection, name: str) -> TagSnapshot:
        row = conn.execute(select(tags).where(tags.c.name == name)).one_or_none()
        if row is None:
            raise TagError("missing", f"There is no tag called '{name}'")
        ids = list(
            conn.execute(select(file_tags.c.drive_id).where(file_tags.c.tag_id == row.id)).scalars()
        )
        return TagSnapshot(row.name, row.pinned_at, row.group_id, row.last_used_at, ids)

    # -- changes --------------------------------------------------------------

    def create(self, name: str) -> TagUndo:
        name = _clean(name)
        with write_tx(self.engine) as conn:
            other = self._clash(conn, name)
            if other is not None:
                raise TagError("exists", f"A tag called '{other}' already exists")
            conn.execute(insert(tags).values(name=name))
        return TagUndo(drop=[name])

    def apply(self, name: str, drive_ids: list[str]) -> TagUndo:
        """Put the tag on these files (a tag that is the same but for case and accents is
        used as it is spelled; a new one is made). One undo step: files that had it
        already are not touched, and Undo takes it off the others (and drops the tag
        again if this made it)."""
        name = _clean(name)
        ids = list(dict.fromkeys(drive_ids))
        if not ids:
            raise TagError("invalid", "No files given")
        now = time.time()
        with write_tx(self.engine) as conn:
            known = set()
            for part in _chunks(ids):
                known.update(
                    conn.execute(
                        select(files.c.drive_id).where(files.c.drive_id.in_(part), _live)
                    ).scalars()
                )
            for drive_id in ids:
                if drive_id not in known:
                    raise TagError("missing", f"There is no file {drive_id}")
            existing = self._clash(conn, name)
            created = existing is None
            if created:
                conn.execute(insert(tags).values(name=name))
            else:
                name = existing
            tag_id = self._id(conn, name)
            added = []
            for drive_id in ids:
                put = conn.execute(
                    sqlite_insert(file_tags)
                    .values(drive_id=drive_id, tag_id=tag_id)
                    .on_conflict_do_nothing()
                )
                if put.rowcount:
                    added.append(drive_id)
            if added:
                conn.execute(update(tags).where(tags.c.id == tag_id).values(last_used_at=now))
        if created:
            return TagUndo(drop=[name])
        return TagUndo(detach=[Unlink(name, added)] if added else [])

    def rename_tag(self, old: str, new: str) -> TagUndo:
        new = _clean(new)
        with write_tx(self.engine) as conn:
            snap = self._snapshot(conn, old)
            tag_id = self._id(conn, old)
            other = self._clash(conn, new, ignore=tag_id)
            if other is not None:
                raise TagError(
                    "exists", f"A tag called '{other}' already exists: merge the tags instead"
                )
            if new == old:
                return TagUndo()
            conn.execute(update(tags).where(tags.c.id == tag_id).values(name=new))
        return TagUndo(drop=[new], restore=[snap])

    def merge(self, sources: list[str], into: str, dry_run: bool = False) -> MergePlan:
        """Put ``into`` on every file that has one of ``sources``; the sources go away."""
        sources = [s for s in dict.fromkeys(sources) if s != into]
        if not sources:
            raise TagError("invalid", "Pick at least one other tag to merge")
        with write_tx(self.engine) as conn:
            target_id = self._id(conn, into)
            ids = [self._id(conn, s) for s in sources]
            have = set(
                conn.execute(
                    select(file_tags.c.drive_id).where(file_tags.c.tag_id == target_id)
                ).scalars()
            )
            gain = sorted(
                {
                    d
                    for d in conn.execute(
                        select(file_tags.c.drive_id).where(file_tags.c.tag_id.in_(ids))
                    ).scalars()
                }
                - have
            )
            plan = MergePlan(into, len(gain), sources)
            if dry_run:
                return plan
            undo = TagUndo(detach=[Unlink(into, gain)] if gain else [])
            undo.restore = [self._snapshot(conn, s) for s in sources]
            for d in gain:
                conn.execute(insert(file_tags).values(drive_id=d, tag_id=target_id))
            if gain:
                conn.execute(
                    update(tags).where(tags.c.id == target_id).values(last_used_at=time.time())
                )
            conn.execute(delete(file_tags).where(file_tags.c.tag_id.in_(ids)))
            conn.execute(delete(tags).where(tags.c.id.in_(ids)))
            plan.undo = undo
            return plan

    def delete(self, name: str) -> TagUndo:
        with write_tx(self.engine) as conn:
            snap = self._snapshot(conn, name)
            tag_id = self._id(conn, name)
            conn.execute(delete(file_tags).where(file_tags.c.tag_id == tag_id))
            conn.execute(delete(tags).where(tags.c.id == tag_id))
        return TagUndo(restore=[snap])

    def pin(self, names: list[str], pinned: bool) -> TagUndo:
        """Pin or unpin tags. Undo restores the pins as they were."""
        now = time.time()
        with write_tx(self.engine) as conn:
            snaps = [self._snapshot_no_files(conn, n) for n in names]
            for i, name in enumerate(names):
                conn.execute(
                    update(tags)
                    .where(tags.c.name == name)
                    .values(pinned_at=(now + i * 1e-6) if pinned else None)
                )
        return TagUndo(restore=snaps)

    def set_group(self, names: list[str], group_id: int | None) -> TagUndo:
        with write_tx(self.engine) as conn:
            if (
                group_id is not None
                and conn.execute(
                    select(tag_groups.c.id).where(tag_groups.c.id == group_id)
                ).scalar()
                is None
            ):
                raise TagError("missing", "There is no such group")
            snaps = [self._snapshot_no_files(conn, n) for n in names]
            conn.execute(update(tags).where(tags.c.name.in_(names)).values(group_id=group_id))
        return TagUndo(restore=snaps)

    def _snapshot_no_files(self, conn: Connection, name: str) -> TagSnapshot:
        row = conn.execute(select(tags).where(tags.c.name == name)).one_or_none()
        if row is None:
            raise TagError("missing", f"There is no tag called '{name}'")
        return TagSnapshot(row.name, row.pinned_at, row.group_id, row.last_used_at, [])

    # -- groups ---------------------------------------------------------------

    def create_group(self, name: str) -> tuple[int, TagUndo]:
        name = _clean(name)
        with write_tx(self.engine) as conn:
            if self._group_clash(conn, name):
                raise TagError("exists", f"A group called '{name}' already exists")
            group_id = conn.execute(insert(tag_groups).values(name=name)).inserted_primary_key[0]
        return group_id, TagUndo()

    def _group_clash(self, conn: Connection, name: str, ignore: int | None = None) -> bool:
        wanted = fold(name)
        return any(
            gid != ignore and fold(other) == wanted
            for gid, other in conn.execute(select(tag_groups.c.id, tag_groups.c.name))
        )

    def rename_group(self, group_id: int, name: str) -> str:
        """Returns the old name (for Undo)."""
        name = _clean(name)
        with write_tx(self.engine) as conn:
            old = conn.execute(
                select(tag_groups.c.name).where(tag_groups.c.id == group_id)
            ).scalar()
            if old is None:
                raise TagError("missing", "There is no such group")
            if self._group_clash(conn, name, ignore=group_id):
                raise TagError("exists", f"A group called '{name}' already exists")
            conn.execute(update(tag_groups).where(tag_groups.c.id == group_id).values(name=name))
        return old

    def delete_group(self, group_id: int) -> tuple[str, list[str]]:
        """Delete the group; its tags are ungrouped. Returns its name and those tags
        (for Undo: ``restore_group``)."""
        with write_tx(self.engine) as conn:
            name = conn.execute(
                select(tag_groups.c.name).where(tag_groups.c.id == group_id)
            ).scalar()
            if name is None:
                raise TagError("missing", "There is no such group")
            members = list(
                conn.execute(
                    select(tags.c.name).where(tags.c.group_id == group_id).order_by(tags.c.name)
                ).scalars()
            )
            conn.execute(update(tags).where(tags.c.group_id == group_id).values(group_id=None))
            conn.execute(delete(tag_groups).where(tag_groups.c.id == group_id))
        return name, members

    def restore_group(self, name: str, members: list[str]) -> int:
        """Bring a deleted group back (a new id) with its tags."""
        name = _clean(name)
        with write_tx(self.engine) as conn:
            if self._group_clash(conn, name):
                raise TagError("exists", f"A group called '{name}' already exists")
            group_id = conn.execute(insert(tag_groups).values(name=name)).inserted_primary_key[0]
            conn.execute(update(tags).where(tags.c.name.in_(members)).values(group_id=group_id))
        return group_id

    # -- undo -----------------------------------------------------------------

    def undo(self, undo: TagUndo) -> None:
        """Put things back as ``undo`` says: first the tags to remove, then the files to
        unlink, then the tags to restore (created again if gone)."""
        with write_tx(self.engine) as conn:
            for name in undo.drop:
                row = conn.execute(select(tags.c.id).where(tags.c.name == name)).scalar()
                if row is not None:
                    conn.execute(delete(file_tags).where(file_tags.c.tag_id == row))
                    conn.execute(delete(tags).where(tags.c.id == row))
            for u in undo.detach:
                row = conn.execute(select(tags.c.id).where(tags.c.name == u.name)).scalar()
                if row is None:
                    continue
                for part in _chunks(u.drive_ids):
                    conn.execute(
                        delete(file_tags).where(
                            file_tags.c.tag_id == row, file_tags.c.drive_id.in_(part)
                        )
                    )
            for snap in undo.restore:
                conn.execute(sqlite_insert(tags).values(name=snap.name).on_conflict_do_nothing())
                tag_id = conn.execute(
                    select(tags.c.id).where(tags.c.name == snap.name)
                ).scalar_one()
                group_id = snap.group_id
                if (
                    group_id is not None
                    and conn.execute(
                        select(tag_groups.c.id).where(tag_groups.c.id == group_id)
                    ).scalar()
                    is None
                ):
                    group_id = None
                conn.execute(
                    update(tags)
                    .where(tags.c.id == tag_id)
                    .values(
                        pinned_at=snap.pinned_at, group_id=group_id, last_used_at=snap.last_used_at
                    )
                )
                known = set(
                    conn.execute(
                        select(file_tags.c.drive_id).where(file_tags.c.tag_id == tag_id)
                    ).scalars()
                )
                # a file removed since is not brought back (its row would break the key)
                alive: set[str] = set()
                for part in _chunks(snap.drive_ids):
                    alive.update(
                        conn.execute(
                            select(files.c.drive_id).where(files.c.drive_id.in_(part))
                        ).scalars()
                    )
                for d in snap.drive_ids:
                    if d not in known and d in alive:
                        conn.execute(insert(file_tags).values(drive_id=d, tag_id=tag_id))
