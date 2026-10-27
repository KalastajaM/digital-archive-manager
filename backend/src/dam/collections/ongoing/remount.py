"""Taking over a new device number after Google Drive for desktop is remounted. Part of
``OngoingPublisher`` (``dam.collections.ongoing``).

A remount gives the volume a new device number, so every entry the publisher recorded
under a root reads as ``"moved"`` (``_state``: same kind and, for a link, the same
readlink value, but a new dev/ino) and its tree is left alone. ``remounted`` lists, per
publish root, the recorded entries in that state. A root is offered only when every one
of them kept its inode, sits on the device the root itself is on now, and was recorded on
one and the same device: then only the device number changed, the same way for all of
them. ``readopt`` records the new device number of an offered root's entries, journaled
in ``readopted``; ``undo_readopt`` puts the old one back. Database only: nothing on disk
changes. Both hold ``sync_lock``, so no sync plans in between.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from sqlalchemy import insert, select, update

from dam.db.tables import ongoing_entries, readopted
from dam.ops import identity
from dam.ops.guards import fold_parts


@dataclass
class RemountedEntry:
    id: int  # the ``ongoing_entries`` row
    rel: str
    kind: str  # link | folder
    st_ino: str
    old_dev: str  # the recorded device number
    new_dev: str  # the one it has now


@dataclass
class RemountedRoot:
    root: str  # ``##. Ongoing`` or ``##. Important``
    entries: list[RemountedEntry] = field(default_factory=list)
    # every entry kept its inode and moved from one old device to the root's own: the new
    # device number can be taken over; else ``reason`` says why the root stays left alone
    offered: bool = False
    reason: str | None = None


class RemountMixin:
    """Taking over a new device number after Google Drive for desktop is remounted."""

    def remounted(self) -> list[RemountedRoot]:
        """Each publish root with recorded entries that read as ``"moved"``, and whether
        their new device number can be taken over (see the module doc). Reads only."""
        out: list[RemountedRoot] = []
        for root in self.paths.publish_roots:
            try:
                root_dev = os.lstat(self.paths.abs(root)).st_dev
            except (OSError, ValueError):
                continue  # not there now: nothing to compare with (the sync says so)
            found = RemountedRoot(root)
            problems: list[str] = []
            for recs in self._records(root).values():
                for rec in recs:
                    try:
                        if self._state(rec) != "moved":
                            continue
                        now = identity.of_path(self.paths.abs(rec.rel))
                    except OSError as e:
                        problems.append(f"{rec.rel} cannot be read ({e.strerror or e})")
                        continue
                    if now.ino != rec.ident.ino:
                        problems.append(f"{rec.rel} has a new inode number too")
                    elif now.dev != root_dev:
                        problems.append(f"{rec.rel} is on another device than {root}")
                    found.entries.append(
                        RemountedEntry(
                            rec.id,
                            rec.rel,
                            rec.kind,
                            str(rec.ident.ino),
                            str(rec.ident.dev),
                            str(now.dev),
                        )
                    )
            if not found.entries:
                continue
            if len({e.old_dev for e in found.entries}) > 1:
                problems.append("the entries were recorded on more than one device")
            found.offered = not problems
            found.reason = "; ".join(problems) or None
            out.append(found)
        return out

    def readopt(
        self, roots: list[str], batch_id: str, dry_run: bool = False
    ) -> tuple[list[RemountedRoot], list[str]]:
        """Take over the new device number of the entries of each of ``roots`` that is
        offered now (one transaction per root, journaled under ``batch_id``): (the roots
        taken over, why others were not). A root that is not offered is left out; one
        whose entries changed in between is left as it was. ``dry_run``: list them only."""
        wanted = {fold_parts(r) for r in roots}
        with self.sync_lock:
            offered = [r for r in self.remounted() if r.offered and fold_parts(r.root) in wanted]
            if dry_run:
                return offered, []
            done: list[RemountedRoot] = []
            errors: list[str] = []
            for found in offered:
                try:
                    self._take_over(found, batch_id)
                except ValueError as e:
                    errors.append(f"{found.root}: not taken over ({e})")
                    continue
                done.append(found)
            return done, errors

    def _take_over(self, found: RemountedRoot, batch_id: str) -> None:
        """One root's entries in one transaction; ``ValueError`` (nothing changes) when
        one of them changed since it was listed."""
        with self.engine.begin() as conn:
            for e in found.entries:
                moved = conn.execute(
                    update(ongoing_entries)
                    .where(
                        ongoing_entries.c.id == e.id,
                        ongoing_entries.c.st_dev == e.old_dev,
                        ongoing_entries.c.st_ino == e.st_ino,
                    )
                    .values(st_dev=e.new_dev)
                ).rowcount
                if moved != 1:
                    raise ValueError(f"{e.rel} changed while it was taken over")
                conn.execute(
                    insert(readopted).values(
                        batch_id=batch_id,
                        entry_id=e.id,
                        rel=e.rel,
                        kind=e.kind,
                        st_ino=e.st_ino,
                        old_dev=e.old_dev,
                        new_dev=e.new_dev,
                        created=time.time(),
                    )
                )

    def readopted_of(self, batch_id: str) -> list[tuple[int, str, bool]]:
        """The entries ``readopt`` journaled as ``batch_id``: (journal id, rel, undone)."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(readopted).where(readopted.c.batch_id == batch_id).order_by(readopted.c.id)
            ).all()
        return [(r.id, r.rel, r.undone is not None) for r in rows]

    def undo_readopt(self, batch_id: str) -> tuple[list[RemountedEntry], list[str]]:
        """Put back the device number ``readopt`` replaced for each entry it journaled as
        ``batch_id`` and not undone yet: (the entries put back, their device numbers now
        old and new as before, and why others were not). An entry
        whose row changed since (another device number or inode, or gone) is left as it
        is. Every journal row of the batch is marked undone."""
        put_back: list[RemountedEntry] = []
        errors: list[str] = []
        with self.sync_lock, self.engine.begin() as conn:
            rows = conn.execute(
                select(readopted)
                .where(readopted.c.batch_id == batch_id, readopted.c.undone.is_(None))
                .order_by(readopted.c.id)
            ).all()
            for r in rows:
                n = conn.execute(
                    update(ongoing_entries)
                    .where(
                        ongoing_entries.c.id == r.entry_id,
                        ongoing_entries.c.st_dev == r.new_dev,
                        ongoing_entries.c.st_ino == r.st_ino,
                    )
                    .values(st_dev=r.old_dev)
                ).rowcount
                if n:
                    put_back.append(
                        RemountedEntry(r.entry_id, r.rel, r.kind, r.st_ino, r.old_dev, r.new_dev)
                    )
                else:
                    errors.append(f"{r.rel}: not undone (it changed since it was taken over)")
                conn.execute(
                    update(readopted).where(readopted.c.id == r.id).values(undone=time.time())
                )
        return put_back, errors
