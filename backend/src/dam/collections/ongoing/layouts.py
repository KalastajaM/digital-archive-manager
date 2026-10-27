"""The layouts a converter's batch carries, and recording them. Part of ``OngoingPublisher``
(``dam.collections.ongoing``)."""

from __future__ import annotations

import dataclasses
import os
import stat
import threading
import time
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from dam.core.fs import readlink
from dam.core.text import fold_name
from dam.db.engine import write_tx
from dam.db.tables import ongoing_entries, ongoing_switched, operations
from dam.errors import InvalidRequest
from dam.ops import identity
from dam.ops.guards import fold_parts, is_under, join
from dam.ops.model import BatchResult, OpKind

if TYPE_CHECKING:
    from dam.collections.service import Collection
from dam.collections.ongoing.model import (
    Layout,
    LeftAlone,
    depth_of,
    first_free,
    flatten,
    forest,
)


class LayoutsMixin:
    """The layouts a converter's batch carries, and recording them."""

    def ongoing_dir(self) -> Path:
        """The Ongoing folder; ``ArchiveUnavailable`` unless it is a listable folder."""
        return self._ongoing_dir()

    def root_dir(self, root: str) -> Path:
        """The publish root ``root`` (``paths.ongoing`` or ``paths.important``);
        ``ArchiveUnavailable`` unless it is a listable folder (see ``_root_dir``)."""
        if fold_parts(root) not in {fold_parts(r) for r in self.paths.publish_roots}:
            raise InvalidRequest(f"{root!r} is not a publish root")
        return self._root_dir(root)

    def owned_link_for(self, root: str, target: str) -> str | None:
        """The rel of a link the publisher owns under ``root`` that points at
        ``target`` (the first by rel), or None: where a member is published."""
        for recs in self._records(root).values():
            for r in recs:
                if r.kind == "link" and self._same_target(r.rel, target):
                    try:
                        if self._state(r) != "gone":
                            return r.rel
                    except OSError:
                        continue
        return None

    @property
    def sync_lock(self) -> threading.Lock:
        """Held by every sync. The converter holds it from planning until the entries
        it created are recorded, so no sync sees them unrecorded (and calls them
        foreign) in between. Never call ``sync`` while holding it."""
        return self._lock

    def owned_top(self, root: str | None = None) -> dict[str, int]:
        """Folded name -> collection id of the top-level entries of ``root`` (Ongoing
        by default) the publisher owns right now: a record whose identity still
        matches, and also one the sync leaves alone (same content, new identity) or
        cannot read right now, so a converter never offers an entry that may be the
        app's."""
        root = self.paths.ongoing if root is None else root
        out: dict[str, int] = {}
        for recs in self._records(root).values():
            for r in recs:
                if not self._is_top(r.rel, root):
                    continue
                try:
                    owned = self._state(r) != "gone"
                except OSError:
                    owned = True
                if owned:
                    out[fold_name(PurePosixPath(r.rel).name)] = r.collection_id
        return out

    def layout_after(self, c: Collection, vacated: list[str]) -> Layout:
        """The publisher's ops for ``c`` as it will be after a conversion: ``c`` holds
        its post-conversion members (``id`` 0 for a collection not created yet) and
        the top-level Ongoing entries ``vacated`` (rels) are taken as already removed
        by the conversion's earlier ops in the same batch. Reads only.

        ``c`` is planned with its tree (its place is inside its parent's folder);
        the layout holds only ``c``'s own entries plus the folders of the ancestors
        above it that do not exist yet (the rest of the tree is the next sync's),
        and, when an ancestor is one direct link that ``c`` turns into a folder, that
        ancestor's switch: the link's removal (``switches``) and the folder with the
        ancestor's own links (in ``creations``), all recorded for the ancestor.
        ``preview_for`` cannot be used for this: it plans against the disk and the
        DB as they are now, where the moved members are not at their new paths yet
        and the user's original entry still occupies the name. ``InvalidRequest`` when
        the sync leaves ``c``'s tree alone (an entry whose identity changed)."""
        ongoing = self._ongoing_dir()
        cols = self.collections.list(None)
        if any(x.id == c.id for x in cols):
            cols = [c if x.id == c.id else x for x in cols]
        else:
            cols.append(c)
        roots, children = forest(cols)
        by_id = {x.id: x for x in cols}
        root = c
        seen: set[int] = set()
        while root.parent_id in by_id and root.id not in seen:
            seen.add(root.id)
            root = by_id[root.parent_id]
        tree = flatten(root, children)
        all_recs, at = self._located()
        try:
            g = self._share(root, children, *self._tree_records(tree, all_recs, at))
        except LeftAlone as e:  # the sync leaves this tree alone: so does this
            raise InvalidRequest(f"{c.name!r} cannot be converted yet. {e}") from None
        if g.fresh is not None:
            taken = {fold_name(n) for n in os.listdir(ongoing)}
            taken -= {fold_name(PurePosixPath(v).name) for v in vacated}
            taken -= g.vacates
            name = first_free(root.name, taken)
            g.creations += self._checked(
                g, self._creation(join(self.paths.ongoing, name), g.fresh, root.id)
            )
        mine = [op for op in g.creations if g.owner_of[fold_parts(op.dst)] == c.id]
        keep = set(map(id, mine))
        if mine:  # the folders above c's entry that this plan creates
            entry = min(mine, key=lambda op: depth_of(op.dst)).dst
            keep |= {
                id(op)
                for op in g.creations
                if op.kind is OpKind.MKDIR and is_under(entry, op.dst, strict=True)
            }
        owner_of_rel = {fold_parts(r.rel): r.collection_id for r in g.owned}
        removals = [op for op in g.removals if owner_of_rel.get(fold_parts(op.src)) == c.id]
        left_out = [op for op in g.removals if op not in removals]
        # An ancestor whose one direct link this plan takes down and replaces with a
        # folder at the same path (it has a published child now: ``c``) switches in
        # this batch: the link's unlink, then its folder and its own links, each
        # recorded for the ancestor. Both are the app's own entries (the link an
        # owned, identity-matched record; the folder created by the batch).
        above: set[int] = set()
        at = c
        while at.parent_id in by_id and at.parent_id not in above and at.parent_id != c.id:
            above.add(at.parent_id)
            at = by_id[at.parent_id]
        made = {fold_parts(op.dst) for op in g.creations if op.kind is OpKind.MKDIR}
        switches = [
            op
            for op in left_out
            if op.kind is OpKind.UNLINK_SYMLINK
            and owner_of_rel.get(fold_parts(op.src)) in above
            and fold_parts(op.src) in made
        ]
        switched = {owner_of_rel[fold_parts(op.src)] for op in switches}
        keep |= {id(op) for op in g.creations if g.owner_of[fold_parts(op.dst)] in switched}
        left_out = [op for op in left_out if op not in switches]
        creations = [op for op in g.creations if id(op) in keep]
        for op in creations:  # a name free only once another collection's entry went
            waiting = next(
                (x.src for x in left_out if is_under(op.dst, x.src) or is_under(x.src, op.dst)),
                None,
            )
            if waiting is not None:
                raise InvalidRequest(
                    f"{c.name!r} cannot be converted yet: {waiting} is still waiting to be"
                    " removed from Ongoing. Sync Ongoing first."
                )
        return Layout(creations, removals, g.reasons_for(c.id), g, c.id, switches)

    def star_layout_after(self, c: Collection, vacated: list[str]) -> Layout:
        """``layout_after`` for the ★ built-in ``c`` (with its post-conversion
        members): its links at the top of Ongoing, named as a sync would name them
        once the top-level entries ``vacated`` are gone (the conversion's earlier
        ops in the same batch). Reads only. ``removals`` holds what a sync would
        take down first (the converter then leaves the layout to the next sync)."""
        ongoing = self._ongoing_dir()
        all_recs, _ = self._located()
        taken = {fold_name(n) for n in os.listdir(ongoing)}
        taken -= {fold_name(PurePosixPath(v).name) for v in vacated}
        try:
            g = self._star_share(c, all_recs, taken)
        except LeftAlone as e:
            raise InvalidRequest(f"This cannot be starred yet. {e}") from None
        return Layout(list(g.creations), list(g.removals), g.reasons_for(c.id), g, c.id)

    def important_layout_after(self, c: Collection, vacated: list[str]) -> Layout:
        """``layout_after`` for the ! built-in ``c`` (with its post-conversion
        members and groups, new groups with placeholder ids): the publisher's
        creations at the root of ``##. Important`` once the top-level entries
        ``vacated`` are gone (the conversion's earlier ops in the same batch), by
        the very reconciliation a sync runs. Reads only; ``InvalidRequest`` when a
        sync would leave the root alone."""
        root = self.paths.important
        if not self._roots_distinct:
            raise InvalidRequest(
                f"Cannot convert: {root} and {self.paths.ongoing} must not be inside each"
                " other. Check the folder settings."
            )
        self._root_dir(root)
        names = frozenset(fold_name(PurePosixPath(v).name) for v in vacated)
        try:
            g = self._important_share(c, root, names)
        except LeftAlone as e:
            raise InvalidRequest(f"{c.name!r} cannot be converted yet. {e}") from None
        reasons = g.reasons_for(c.id) + [
            f"The group folder {wanted} will be named {actual}, because that name is taken."
            for wanted, actual in g.suffixed
        ]
        return Layout(list(g.creations), list(g.removals), reasons, g, c.id)

    def record_layout(self, layout: Layout, collection: Collection, batch: BatchResult) -> None:
        """Record ownership of the layout's entries that ``batch`` created (the same
        path a sync uses), then ``collection``'s ``ongoing_rel``/``ongoing_status``
        (its ancestors' are the next sync's). An ancestor's link the batch switched
        to a folder is remembered (``ongoing_switched``) so the undo of the batch,
        which puts the link back, hands it back to the publisher."""
        g = layout.share
        swap = {layout.for_id: collection.id}
        share = dataclasses.replace(
            g,
            collection=collection if g.collection.id == layout.for_id else g.collection,
            tree=[collection],
            owner_of={k: swap.get(v, v) for k, v in g.owner_of.items()},
            per={swap.get(k, k): v for k, v in g.per.items()},
        )
        self._record([share], batch)
        unlinked = {fold_parts(r.src) for r in batch.done if r.kind is OpKind.UNLINK_SYMLINK} & {
            fold_parts(op.src) for op in layout.switches
        }
        rows = [
            {
                "batch_id": batch.batch_id,
                "collection_id": rec.collection_id,
                "rel": rec.rel,
                "link_value": rec.link_value,
                "created": time.time(),
            }
            for rec in g.owned
            if rec.kind == "link" and rec.link_value is not None and fold_parts(rec.rel) in unlinked
        ]
        if rows:
            with write_tx(self.engine) as conn:
                conn.execute(ongoing_switched.insert(), rows)

    def forget_undone(self, batch_id: str) -> int:
        """After an undo of ``batch_id``: forget the records of entries it created
        that the undo removed (the record no longer matches), so the next sync does
        not report them as "changed outside the app"; and record again an ancestor's
        link the batch had switched to a folder (``ongoing_switched``) when the undo
        put it back: a link at the recorded rel with exactly the recorded readlink
        value, and no record at that rel any more. Returns how many were forgotten."""
        with self.engine.connect() as conn:
            rels = set(
                fold_parts(r)
                for r in conn.execute(
                    select(operations.c.dst).where(
                        operations.c.batch_id == batch_id,
                        operations.c.kind.in_([str(OpKind.MKDIR), str(OpKind.SYMLINK)]),
                        operations.c.state == "undone",
                    )
                ).scalars()
                if r is not None
            )
            switched = conn.execute(
                select(ongoing_switched).where(ongoing_switched.c.batch_id == batch_id)
            ).all()
        stale = [
            r.id
            for recs in self._records().values()
            for r in recs
            if fold_parts(r.rel) in rels and self._gone(r)
        ]
        if stale:
            with write_tx(self.engine) as conn:
                conn.execute(delete(ongoing_entries).where(ongoing_entries.c.id.in_(stale)))
        if switched:
            self._own_again(switched)
        return len(stale)

    def _own_again(self, switched: list) -> None:
        """Record the links in ``switched`` (rows of ``ongoing_switched``) that an undo
        put back exactly as recorded; the rows go either way (one undo per batch)."""
        recorded = {fold_parts(r.rel) for recs in self._records().values() for r in recs}
        now = time.time()
        rows = []
        for s in switched:
            if fold_parts(s.rel) in recorded:
                continue
            p = self.paths.abs(s.rel)
            try:
                st = os.lstat(p)
                if not stat.S_ISLNK(st.st_mode) or readlink(p) != s.link_value:
                    continue
            except OSError:
                continue
            rows.append(
                {
                    "collection_id": s.collection_id,
                    "rel": s.rel,
                    "kind": "link",
                    "link_value": s.link_value,
                    **identity.of_stat(st, path=p).columns(),
                    "created": now,
                }
            )
        with write_tx(self.engine) as conn:
            if rows:
                conn.execute(ongoing_entries.insert(), rows)
            conn.execute(
                delete(ongoing_switched).where(ongoing_switched.c.id.in_([s.id for s in switched]))
            )

    # --- sync ----------------------------------------------------------------------------
