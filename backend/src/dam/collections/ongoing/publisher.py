"""``OngoingPublisher``: syncing ``##. Ongoing`` and ``##. Important`` (``dam.collections.ongoing``
has the whole design)."""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import Connection, delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from dam.core.fs import readlink, resolve
from dam.core.paths import ArchivePaths, OutsideArchiveError
from dam.db.engine import write_tx
from dam.db.tables import collections as collections_table
from dam.db.tables import ongoing_entries
from dam.errors import ArchiveUnavailable
from dam.ops import identity
from dam.ops.guards import fold_parts, is_under, parent
from dam.ops.model import BatchResult, GuardError, OpKind, Plan, ResolvedOp

if TYPE_CHECKING:
    from dam.collections.service import Collection, CollectionService, GroupConverted
    from dam.index.repo import FileRepo
    from dam.ops.executor import Executor
from dam.collections.ongoing.desired import DesiredMixin
from dam.collections.ongoing.layouts import LayoutsMixin
from dam.collections.ongoing.model import (
    NOT_MANAGED,
    NOT_SHOWN,
    ORIGIN,
    PUBLISHER_ID,
    REPLACED,
    RETRY_FAILED_S,
    Desired,
    Share,
    SyncResult,
    depth_of,
    forest,
    log,
)
from dam.collections.ongoing.planning import PlanningMixin
from dam.collections.ongoing.records import RecordsMixin
from dam.collections.ongoing.remount import RemountMixin


class OngoingPublisher(DesiredMixin, RecordsMixin, PlanningMixin, LayoutsMixin, RemountMixin):
    id = PUBLISHER_ID

    def __init__(
        self,
        paths: ArchivePaths,
        repo: FileRepo,
        executor: Executor,
        collections: CollectionService,
    ) -> None:
        self.paths = paths
        self.repo = repo
        self.executor = executor
        self.collections = collections
        self.engine = collections.engine
        self._lock = threading.Lock()
        # per root, the last applied plan that failed at act time: the same plan again
        # is not re-applied (it would journal the same failed batch on every trigger)
        # until the plan changes or an hour has passed
        # root -> (plan key, failure text, when); retried once RETRY_FAILED_S passed
        self._failed: dict[str, tuple[tuple, str, float]] = {}
        self._clock = time.monotonic  # injectable for tests
        # the two roots must not contain each other (a misconfiguration otherwise:
        # records of one root would lie under the other and ownership would churn;
        # the Important root is then not published at all, and every sync says so)
        self._roots_distinct = not (
            is_under(paths.ongoing, paths.important) or is_under(paths.important, paths.ongoing)
        )

    @property
    def last_failure(self) -> str | None:
        """Why the last applied sync of a root failed, while its plan is still the
        same (both roots' reasons when both failed); None after a successful sync
        (for Today)."""
        return "; ".join(f[1] for f in self._failed.values()) or None

    # --- desired state -----------------------------------------------------------

    def sync(self, dry_run: bool = False, label: str | None = None) -> SyncResult:
        """Plan every collection and apply the plan (one journaled batch, origin
        ``"workflow"``); an empty plan journals nothing. ``dry_run``: plan only.
        ``label``: what the user did that caused this sync (the batch's title in
        Activity; without it the batch is an automatic update). It does not make the
        batch undoable: that follows the origin."""
        with self._lock:
            result = self._sync(dry_run, label)
        for problem in result.problems:
            log.warning("ongoing sync: %s", problem)
        return result

    def _preview(self, shares: list[Share], problems: list[str]) -> list[ResolvedOp]:
        """Resolve the shares' ops together; a share refused on its own is skipped
        (reported) so one odd tree cannot block the others."""
        ops = self._ordered(shares)
        if not ops:
            return []
        try:
            return self.executor.preview(Plan(ops, ORIGIN))
        except GuardError:
            pass
        for g in shares:
            if not g.ops or g.skipped:
                continue
            try:
                self.executor.preview(Plan(g.ops, ORIGIN))
            except GuardError as e:
                g.skipped = True
                log.warning("ongoing: plan refused for %s: %s", g.collection.name, e)
                problems.append(f"{g.collection.name}: its changes could not be applied.")
        ops = self._ordered(shares)
        if not ops:
            return []
        try:
            return self.executor.preview(Plan(ops, ORIGIN))
        except GuardError as e:
            log.warning("ongoing: plan refused: %s", e)
            problems.append("The changes to the folders could not be applied.")
            for g in shares:
                g.skipped = True
            return []

    def _root_shares(self, problems: list[str]) -> list[tuple[str, list[Share]]]:
        """The shares of each root, Ongoing first (the trees and ★) then Important;
        a root that is not a listable folder is reported and left out (Ongoing) or
        left alone with its status saying so (Important)."""
        out: list[tuple[str, list[Share]]] = []
        try:
            out.append((self.paths.ongoing, self._shares(self.collections.list(None), problems)))
        except ArchiveUnavailable as e:
            problems.append(str(e))
        out.append((self.paths.important, self._important_shares(problems)))
        for _, shares in out:
            self._hold(shares)
        return out

    def _hold(self, shares: list[Share]) -> None:
        """Leave out of the shares (one root's) every change to a link into an extra
        folder that is not connected now or is detached: its unlink, the removal of
        each folder above it, a new link to a member there, and any creation at or
        below a path that therefore stays as it is (a creation inside a folder left
        out goes too)."""
        offline = set(self.paths.disconnected_labels())
        detached = [resolve(e.path) for e in self.paths.settings.extra_folders if not e.attached]
        if not offline and not detached:
            return
        held: list[tuple[str, ...]] = []
        for g in shares:
            keep = []
            for op in g.removals:
                if op.kind is OpKind.UNLINK_SYMLINK and self._into_absent(
                    op.src, offline, detached
                ):
                    log.info("ongoing: %s left as it is (its folder is not there)", op.src)
                    held.append(fold_parts(op.src))
                else:
                    keep.append(op)
            g.removals = keep
        if not held and not any(
            op.kind is OpKind.SYMLINK and self.paths.label_of(op.src) in offline
            for g in shares
            for op in g.creations
        ):
            return

        def above_held(rel: str) -> bool:
            parts = fold_parts(rel)
            return any(h[: len(parts)] == parts for h in held)

        for g in shares:
            g.removals = [
                op
                for op in g.removals
                if not (op.kind is OpKind.REMOVE_EMPTY_DIR and above_held(op.src))
            ]
        blocked = list(held)
        for g in shares:
            keep = []
            for op in g.creations:  # parents first: a folder left out takes its content
                parts = fold_parts(op.dst)
                if (
                    (op.kind is OpKind.SYMLINK and self.paths.label_of(op.src) in offline)
                    or above_held(op.dst)
                    or any(parts[: len(b)] == b for b in blocked)
                ):
                    if op.kind is OpKind.MKDIR:
                        blocked.append(parts)
                    continue
                keep.append(op)
            g.creations = keep

    def _into_absent(self, link_rel: str, offline: set[str], detached: list[Path]) -> bool:
        """The link ``link_rel`` points into an extra folder that is not connected
        (``offline``: labels) or detached (``detached``: their folders)."""
        link = self.paths.abs(link_rel)
        try:
            raw = readlink(link)
        except OSError:
            return False
        full = Path(os.path.normpath(os.path.join(link.parent, raw)))
        try:
            return self.paths.label_of(self.paths.rel(full)) in offline
        except (OutsideArchiveError, OSError):
            pass
        for root in detached:
            try:
                full.relative_to(root)
            except ValueError:
                continue
            return True
        return False

    def _sync(self, dry_run: bool, label: str | None = None) -> SyncResult:
        """Each root on its own: planned, previewed, applied as one batch and
        recorded, so a refusal or a failure in one root never holds the other back
        (the failing-sync throttle is per root too)."""
        problems: list[str] = []
        result = SyncResult([], None, problems)
        for root, shares in self._root_shares(problems):
            resolved = self._preview(shares, problems)
            result.plan += resolved
            if dry_run:
                continue
            ops = self._ordered(shares)
            batch = None
            key = tuple(sorted((str(r.kind), r.src or "", r.dst) for r in resolved))
            failed = self._failed.get(root)
            if (
                ops
                and failed is not None
                and failed[0] == key
                and self._clock() - failed[2] < RETRY_FAILED_S
            ):
                log.info("ongoing: not retried (same plan as the last failed sync): %s", failed[1])
                problems.append(
                    f"Not tried again yet, because nothing has changed since it failed. {failed[1]}"
                )
                continue
            self._failed.pop(root, None)
            if ops:
                try:
                    batch = self.executor.apply(Plan(ops, ORIGIN, label=label))
                except GuardError as e:  # the disk changed since planning; nothing ran
                    log.warning("ongoing: plan refused: %s", e)
                    problems.append("The changes to the folders could not be applied.")
                    continue
                if batch.failed is not None:
                    failure = f"Ongoing stopped while updating {batch.failed.dst}: {batch.error}"
                    log.warning("ongoing: %s (%s)", failure, batch.failed.kind)
                    problems.append(failure)
                    self._failed[root] = (key, failure, self._clock())
                if batch.index_error is not None:
                    problems.append(batch.index_error)
                result.batches.append(batch)
                result.batch = batch
            self._record([g for g in shares if not g.skipped], batch)
            self._note_left_alone(shares)
        return result

    # --- recording -----------------------------------------------------------------------

    def _sticky(self, c: Collection, reasons: list[str], owned_now: set) -> list[str]:
        """Earlier "changed outside the app" notes whose entry is still there."""
        old = c.ongoing_status
        if not old or not old.startswith(NOT_MANAGED):
            return []
        out = []
        # the reasons are sentences joined by a space; a "changed outside the app" one
        # starts with the entry's path (below one of the roots) and ends with REPLACED
        roots = "|".join(re.escape(r) for r in (self.paths.ongoing, self.paths.important))
        found = re.finditer(
            rf"(?:^|(?<=\. ))((?:{roots})/(?:##\. |(?!\. )[^\n])+?){re.escape(REPLACED)}",
            old[len(NOT_MANAGED) :],
        )
        for m in found:
            part = m.group(0)
            rel = m.group(1)
            try:
                there = os.path.lexists(self.paths.abs(rel))
            except (OutsideArchiveError, ValueError):
                continue
            if there and fold_parts(rel) not in owned_now and part not in reasons:
                out.append(part)
        return out

    def _note_left_alone(self, shares: list[Share]) -> None:
        """Show why a tree was left alone as its collections' ``ongoing_status``
        (their records and ``ongoing_rel`` stay as they are)."""
        for g in shares:
            status = None if g.left_alone is None else NOT_MANAGED + g.left_alone
            if status is None:
                continue
            for c in g.tree:
                if status == c.ongoing_status:
                    continue
                with write_tx(self.engine) as conn:
                    conn.execute(
                        update(collections_table)
                        .where(collections_table.c.id == c.id)
                        .values(ongoing_status=status)
                    )

    def _record(self, shares: list[Share], batch: BatchResult | None) -> None:
        """Update ``ongoing_entries`` from what the batch actually did (only creations
        in ``batch.done`` are recorded, with their identity read right after, each for
        the collection it was planned for), then each collection's ``ongoing_rel``
        (its own top entry: the shallowest it owns) and ``ongoing_status``. A
        collection that would be shown but is hidden because its parent is not
        shown gets the status ``"not shown: its parent collection '<name>' is not
        shown in ##. Ongoing"`` (unless it has a "not managed" note); a status only,
        nothing about what is removed or created."""
        done = batch.done if batch is not None else []
        hidden: dict[int, str] = {}  # collection id -> the name of the parent hiding it
        for g in shares:
            _, kids = forest(g.tree)
            by_id = {c.id: c for c in g.tree}
            shown: dict[int, bool] = {}
            for c in g.tree:  # parents first
                above = shown[c.parent_id] if c.parent_id in by_id else True
                mine = self._shown(c, kids)
                shown[c.id] = above and mine
                if mine and not above:
                    hidden[c.id] = by_id[c.parent_id].name
        failed = batch.failed if batch is not None else None
        removed = {
            fold_parts(r.dst)
            for r in done
            if r.kind in (OpKind.UNLINK_SYMLINK, OpKind.REMOVE_EMPTY_DIR)
        }
        owner = {parts: cid for g in shares for parts, cid in g.owner_of.items()}
        now = time.time()
        new_rows = []
        for r in done:
            if r.kind not in (OpKind.MKDIR, OpKind.SYMLINK):
                continue
            cid = owner.get(fold_parts(r.dst))
            if cid is None:
                continue
            p = self.paths.abs(r.dst)
            try:
                st = os.lstat(p)
                value = readlink(p) if r.kind is OpKind.SYMLINK else None
            except OSError:
                continue  # gone already: not recorded, so never treated as ours
            new_rows.append(
                {
                    "collection_id": cid,
                    "rel": r.dst,
                    "kind": "link" if r.kind is OpKind.SYMLINK else "folder",
                    "link_value": value,
                    **identity.of_stat(st, path=p).columns(),
                    "created": now,
                }
            )
        with write_tx(self.engine) as conn:
            for g in shares:
                gone = [rec.id for rec in g.owned if fold_parts(rec.rel) in removed]
                ids = [*g.forget, *gone]
                if ids:
                    conn.execute(delete(ongoing_entries).where(ongoing_entries.c.id.in_(ids)))
            for row in new_rows:
                conn.execute(
                    sqlite_insert(ongoing_entries)
                    .values(**row)
                    .on_conflict_do_update(index_elements=["rel"], set_=row)
                )
            rows = conn.execute(
                select(ongoing_entries.c.collection_id, ongoing_entries.c.rel)
            ).all()
            by_collection: dict[int, list[str]] = {}
            for cid, rel in rows:
                by_collection.setdefault(cid, []).append(rel)
            # Reasons are merged across shares: a collection that moved to another
            # tree gets the note about what it left behind in the old one.
            reasons: dict[int, list[str]] = {}
            for g in shares:
                for cid, texts in g.per.items():
                    for text in texts:
                        if text not in reasons.setdefault(cid, []):
                            reasons[cid].append(text)
                if failed is not None and failed.kind is OpKind.REMOVE_EMPTY_DIR:
                    for rec in g.owned:
                        if is_under(failed.dst, rec.rel):
                            text = batch.error or f"{failed.dst} could not be removed"
                            if text not in reasons.setdefault(rec.collection_id, []):
                                reasons[rec.collection_id].append(text)
            tops: dict[int, str | None] = {}
            for g in shares:
                for c in g.tree:  # parents first: a child's place is under its parent's
                    rels = sorted(by_collection.get(c.id, []))
                    home = tops.get(c.parent_id) if c.parent_id is not None else None
                    at_home = [
                        r for r in rels if home and fold_parts(parent(r)) == fold_parts(home)
                    ]
                    top = min(at_home or rels, key=depth_of) if rels else None
                    if g.root_rel is not None:  # a built-in: its place is the root
                        top = g.root_rel
                    tops[c.id] = top
                    why = list(reasons.get(c.id, []))
                    why += self._sticky(c, why, {fold_parts(r) for r in rels})
                    status = NOT_MANAGED + " ".join(why) if why else None
                    if status is None and c.id in hidden:
                        status = (
                            f"{NOT_SHOWN}its parent collection '{hidden[c.id]}' is not shown"
                            f" in {self.paths.ongoing}."
                        )
                    if (top, status) != (c.ongoing_rel, c.ongoing_status):
                        conn.execute(
                            update(collections_table)
                            .where(collections_table.c.id == c.id)
                            .values(ongoing_rel=top, ongoing_status=status)
                        )

    # --- groups turned into collections ---------------------------------------------------

    def desired_roots(self) -> dict[int, Desired | None]:
        """``desired_tree`` of every top-level ordinary collection, by id (reads only)."""
        roots, children = forest(self.collections.list(None))
        return {r.id: self.desired_tree(r, children) for r in roots}

    def reown(
        self, conn: Connection, before: dict[int, Desired | None], done: list[GroupConverted]
    ) -> int:
        """Inside the transaction that turned groups into collections (``done``): hand
        each former group folder's records (the folder and what is in it, still its
        collection's) to the group's new collection, deepest first, so the next sync
        keeps every folder and link where it is. ``before``: ``desired_roots()`` taken
        before the change. Returns how many records changed owner."""
        folder_of: dict[int, tuple[int, str]] = {}  # group id -> (root id, folder path)
        for root_id, was in before.items():
            if was is not None and was.kind == "folder":
                for gid, path in was.groups.items():
                    folder_of[gid] = (root_id, path)
        homes: dict[int, str | None] = {}
        moves = []
        for d in done:
            if d.group_id not in folder_of:  # its collection is not published
                continue
            root_id, path = folder_of[d.group_id]
            if root_id not in homes:
                homes[root_id] = conn.execute(
                    select(collections_table.c.ongoing_rel).where(collections_table.c.id == root_id)
                ).scalar()
            if homes[root_id]:  # recorded only once it was published
                moves.append((f"{homes[root_id]}/{path}", d.collection_id, d.new_id))
        changed = 0
        for rel, old_owner, new_owner in sorted(moves, key=lambda m: -m[0].count("/")):
            rows = conn.execute(
                select(ongoing_entries.c.id, ongoing_entries.c.rel).where(
                    ongoing_entries.c.collection_id == old_owner
                )
            ).all()
            ids = [r.id for r in rows if r.rel == rel or r.rel.startswith(rel + "/")]
            if ids:
                conn.execute(
                    update(ongoing_entries)
                    .where(ongoing_entries.c.id.in_(ids))
                    .values(collection_id=new_owner)
                )
                changed += len(ids)
        return changed
