"""Planning a sync: one share per tree or root, the ops that reconcile it. Part of
``OngoingPublisher`` (``dam.collections.ongoing``)."""

from __future__ import annotations

import dataclasses
import os
import unicodedata
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from dam.core.paths import nfc
from dam.core.text import fold_name
from dam.errors import ArchiveUnavailable
from dam.ops import primitives
from dam.ops.guards import fold_parts, is_ds_store_name, join, parent, validate
from dam.ops.identity import Identity
from dam.ops.model import GuardError, Op, OpKind, Plan, ResolvedOp

if TYPE_CHECKING:
    from dam.collections.service import Collection
from dam.collections.ongoing.model import (
    ORIGIN,
    PUBLISHER_ID,
    REPLACED,
    Children,
    Desired,
    LeftAlone,
    Node,
    Record,
    Share,
    Want,
    WantedLink,
    depth_of,
    entry_kind,
    first_free,
    flatten,
    forest,
    is_variant,
    items_text,
    log,
    names_for_links,
    wanted_name_of,
)


class PlanningMixin:
    """Planning a sync: one share per tree or root, the ops that reconcile it."""

    @staticmethod
    def _creation(rel: str, want: Desired, owner: int) -> list[tuple[Op, int]]:
        # exact: the path must be free at act time; never adopt something that
        # appeared there since planning, never let the planner pick another suffix.
        if want.kind == "link":
            return [(Op(OpKind.SYMLINK, want.target, rel, exact=True), owner)]
        return PlanningMixin._subtree(rel, Want.of(want, owner))

    @staticmethod
    def _subtree(rel: str, want: Want) -> list[tuple[Op, int]]:
        """Create the folder ``rel`` and everything wanted in it: every folder first
        (parents before children), then every link, each with the collection it is
        recorded for. All exact."""
        dirs = [(Op(OpKind.MKDIR, None, rel, exact=True), want.owner)]
        links: list[tuple[Op, int]] = []

        def walk(base: str, node: Want) -> None:
            links.extend(
                (Op(OpKind.SYMLINK, link.target, join(base, n), exact=True), link.owner)
                for n, link in node.links.items()
            )
            for name, sub in node.folders.items():
                dirs.append((Op(OpKind.MKDIR, None, join(base, name), exact=True), sub.owner))
                walk(join(base, name), sub)

        walk(rel, want)
        return [*dirs, *links]

    def _checked(self, g: Share, pairs: list[tuple[Op, int]]) -> list[Op]:
        """Drop (and report) a creation the guards would refuse, or a link whose name
        has control or format characters; keep the rest, noting whose each is."""
        out = []
        for op, owner in pairs:
            try:
                validate(op, self.paths)
                name = PurePosixPath(op.dst).name
                if op.kind is OpKind.SYMLINK and any(
                    unicodedata.category(ch) in ("Cc", "Cf") for ch in name
                ):  # as check_name refuses for collection names (NUL, bidi, format)
                    g.note(
                        owner,
                        f"{op.src} was not added because its name has characters that are not"
                        " allowed.",
                    )
                    continue
            except GuardError as e:
                log.info("ongoing: %s not linked: %s", op.src, e)
                g.note(owner, f"{op.src} could not be added, so it was skipped.")
                continue
            g.owner_of[fold_parts(op.dst)] = owner
            out.append(op)
        return out

    def _analyse(
        self, g: Share, tops: list[Record], inner: list[Record]
    ) -> tuple[Record | None, Node | None, list[tuple[Record, Node | None]]]:
        """Split the records into owned/forgotten. Returns the root's owned top record
        (if any) and, for a folder, the tree of what the publisher owns inside it
        (every owned folder listed: its foreign names and why it could not be
        removed), plus the *strays*: other owned top-level entries of the tree's
        collections (a child's entry from before it was moved inside, a second
        entry), each with its tree, to be taken down."""
        top = None
        strays: list[tuple[Record, Node | None]] = []
        nodes: dict[tuple[str, ...], Node] = {}
        for r in sorted(tops, key=lambda r: r.rel):
            if not self._owned(r):
                g.forget.append(r.id)
                if os.path.lexists(self.paths.abs(r.rel)):
                    g.note(r.collection_id, f"{r.rel}{REPLACED}")
                continue
            g.owned.append(r)
            node = Node(r, (r.collection_id,)) if r.kind == "folder" else None
            if node is not None:
                nodes[fold_parts(r.rel)] = node
            if top is None and r.collection_id == g.collection.id:
                top = r
            else:
                strays.append((r, node))
        tree = nodes.get(fold_parts(top.rel)) if top is not None else None
        # Parents first: an entry is owned only inside a folder that is owned itself,
        # so nothing is ever planned through a folder someone else put there.
        for r in sorted(inner, key=lambda r: depth_of(r.rel)):
            node = nodes.get(fold_parts(parent(r.rel)))
            if node is None:  # its folder is not the app's (any more): forgotten quietly
                g.forget.append(r.id)
                continue
            if self._owned(r):
                name = PurePosixPath(r.rel).name
                g.owned.append(r)
                if r.kind == "link":
                    node.links[name] = r
                else:
                    owners = node.owners
                    if r.collection_id != owners[-1]:  # a child collection's folder
                        owners = (*owners, r.collection_id)
                    node.folders[name] = nodes[fold_parts(r.rel)] = Node(r, owners)
                continue
            g.forget.append(r.id)
            # a replaced folder is worth a word (its whole subtree is affected);
            # a replaced link is just a foreign name from here on, as before
            if r.kind == "folder" and os.path.lexists(self.paths.abs(r.rel)):
                for cid in (*node.owners, r.collection_id):
                    g.note(cid, f"{r.rel}{REPLACED}")
        for node in nodes.values():
            self._list(node)
        return top, tree, strays

    def _list(self, node: Node) -> None:
        """What is in the owned folder ``node`` beside its owned entries, and whether
        that keeps it from being removed."""
        folder = self.paths.abs(node.rec.rel)
        ds_store = False
        for n in sorted(os.listdir(folder)):
            if n in node.links or n in node.folders:
                continue
            if n == primitives.DS_STORE and entry_kind(folder / n) == "file":
                ds_store = True
                continue
            node.foreign.append(n)
        if node.foreign:
            node.blocker = (
                f"{node.rec.rel} contains {items_text(len(node.foreign))} not created by the"
                " app, so it was left as it is."
            )
        elif ds_store:
            problem = primitives.finder_cache_problem(folder)
            if problem is not None:
                log.info("ongoing: %s: %s", node.rec.rel, problem)
                node.blocker = (
                    f"{node.rec.rel} has a hidden Finder file that could not be removed,"
                    " so it was left as it is."
                )
        if ds_store:
            node.foreign.append(primitives.DS_STORE)

    def _take_down_node(self, g: Share, node: Node, start: Node | None = None) -> bool:
        """Remove what ``node`` owns: its links, its owned subfolders (deepest first)
        and, when nothing else is in it, the folder itself. A folder holding anything
        else stays, and so does every folder above it; that is reported to the
        collection whose folder it is and to each collection above it whose own
        folder was to go too, or that asked for the removal (from ``start``: the
        folder this take-down began at, or the parent folder it was wanted gone
        from). True when the folder goes."""
        start = start or node
        g.removals += [Op(OpKind.UNLINK_SYMLINK, r.rel, None) for r in node.links.values()]
        children_gone = all([self._take_down_node(g, n, start) for n in node.folders.values()])
        if node.blocker is not None:
            for cid in node.owners[len(start.owners) - 1 :]:
                g.note(cid, node.blocker)
            return False
        if not children_gone:
            return False
        rec = node.rec  # removed only while still the very folder recorded (identity)
        g.removals.append(Op(OpKind.REMOVE_EMPTY_DIR, rec.rel, None, identity=rec.ident))
        return True

    def _take_down(self, g: Share, top: Record, tree: Node | None) -> bool:
        """Remove the top entry ``top`` and everything it owns below it; True when
        its top-level name is vacated."""
        if top.kind == "link":
            g.removals.append(Op(OpKind.UNLINK_SYMLINK, top.rel, None))
            gone = True
        else:
            gone = self._take_down_node(g, tree)
        if gone:
            g.vacates.add(fold_name(PurePosixPath(top.rel).name))
        return gone

    def _reconcile(self, g: Share, node: Node, want: Want) -> None:
        """Make the owned folder ``node`` hold what ``want`` says: keep correct owned
        links and wanted owned subfolders (their names reserved first), take down the
        rest it owns, then create what is missing beside whatever else is there. An
        entry is kept only for the collection it is recorded for: a child's folder is
        never taken for a group's (or another child's), nor the other way round."""
        vacated: set[str] = set()
        wanted = list(want.links.items())  # (wanted name, link)
        claimed: set[int] = set()  # indexes into ``wanted`` already held by a kept link
        for name, rec in node.links.items():
            found = self._target(self.paths.abs(rec.rel))
            match = next(
                (
                    i
                    for i, (_, link) in enumerate(wanted)
                    if i not in claimed
                    and found is not None
                    and nfc(link.target) == nfc(found)
                    and link.owner == rec.collection_id
                    and is_variant(name, link.base)
                ),
                None,
            )
            if match is not None:
                claimed.add(match)
            else:
                g.removals.append(Op(OpKind.UNLINK_SYMLINK, rec.rel, None))
                vacated.add(fold_name(name))
        # A wanted folder keeps an owned subfolder of the same name, else one named
        # a ``first_free`` variant of it (what an earlier collision gave), else one
        # named a variant of its base name (a child's folder that a group's wanted
        # name has since overtaken, or the other way round); never the other way
        # round, so a folder is not kept under a name a member wants.
        link_names = {fold_name(n) for n in want.links}
        kept: dict[str, str] = {}  # wanted folder name -> owned folder name
        for how in ("same", "variant", "base"):
            for wanted_name, sub in want.folders.items():
                if wanted_name in kept:
                    continue
                for name, child in node.folders.items():
                    if name in kept.values() or child.rec.collection_id != sub.owner:
                        continue
                    if how == "same":
                        ok = nfc(name) == nfc(wanted_name)
                    elif how == "variant":
                        ok = is_variant(name, wanted_name)
                    else:
                        ok = is_variant(name, sub.base) and fold_name(name) not in link_names
                    if ok:
                        kept[wanted_name] = name
                        break
        for name, child in node.folders.items():
            # taken down on this folder's behalf: a leftover is its owner's problem too
            if name not in kept.values() and self._take_down_node(g, child, node):
                vacated.add(fold_name(name))
        taken = {fold_name(n) for n in [*node.links, *node.folders, *node.foreign]} - vacated
        pairs: list[tuple[Op, int]] = []
        for i, (_, link) in enumerate(wanted):
            if i in claimed:
                continue
            name = first_free(link.base, taken)
            taken.add(fold_name(name))
            pairs.append(
                (Op(OpKind.SYMLINK, link.target, join(node.rec.rel, name), exact=True), link.owner)
            )
        g.creations += self._checked(g, pairs)
        for wanted_name, sub in want.folders.items():
            if wanted_name in kept:
                if nfc(kept[wanted_name]) != nfc(wanted_name):
                    g.suffixed.append(
                        (join(node.rec.rel, wanted_name), join(node.rec.rel, kept[wanted_name]))
                    )
                self._reconcile(g, node.folders[kept[wanted_name]], sub)
                continue
            name = first_free(sub.base or wanted_name, taken)
            taken.add(fold_name(name))
            if nfc(name) != nfc(sub.base or wanted_name):
                g.suffixed.append((join(node.rec.rel, wanted_name), join(node.rec.rel, name)))
            g.creations += self._checked(g, self._subtree(join(node.rec.rel, name), sub))

    def _share(
        self,
        root: Collection,
        children: Children,
        tops: list[Record],
        inner: list[Record],
        orphans: list[Record],
    ) -> Share:
        """Removals and in-place creations for the tree under ``root``; ``fresh`` when
        a new top entry is needed. ``tops``: the tree's top-level records; ``inner``:
        every record located under one of them (whichever collection's); ``orphans``:
        the tree's records under no owned chain at all (forgotten quietly)."""
        g = Share(root, flatten(root, children))
        g.forget += [r.id for r in orphans]
        want = self.desired_tree(root, children)
        top, tree, strays = self._analyse(g, tops, inner)
        if want is not None:
            for r in want.refused:
                owner = next((c.id for c in g.tree if any(m.path == r for m in c.members)), root.id)
                g.note(owner, f"{r} was not added because its name is reserved.")
        self._plan_share(g, want, top, tree, strays)
        return g

    def _plan_share(
        self,
        g: Share,
        want: Desired | None,
        top: Record | None,
        tree: Node | None,
        strays: list[tuple[Record, Node | None]],
    ) -> None:
        c = g.collection
        for rec, node in strays:  # an entry at the top that is not the root's place
            self._take_down(g, rec, node)
        if want is None:  # closed or unpublished: take down what it owns
            if top is not None:
                self._take_down(g, top, tree)
            return
        if top is None:
            g.fresh = want
            return
        in_place = is_variant(PurePosixPath(top.rel).name, c.name)
        if tree is not None and not tree.removable():
            # A folder with user content (anywhere in the tree) is never removed: it
            # stays the collection's place (renames and the switch to a direct link
            # wait until it is empty).
            if not in_place or want.kind == "link":
                for text, owners in tree.blockers():
                    for cid in owners:
                        g.note(cid, text)
            in_place = True
            if want.kind == "link":
                member = next((m for m in self._live(c) if m.path == want.target), None)
                base = wanted_name_of(member) if member else PurePosixPath(want.target).name
                links = {n: t for n, (t, _) in names_for_links([(want.target, base)]).items()}
                want = Desired("folder", want.rel, links=links)
        if not in_place:  # renamed: remove the old entry, recreate under the new name
            self._take_down(g, top, tree)
            g.fresh = want
            return
        if want.kind == "link":
            if top.kind == "link" and self._same_target(top.rel, want.target):
                return
            self._take_down(g, top, tree)
            g.vacates.discard(fold_name(PurePosixPath(top.rel).name))  # recreated right here
            g.creations += self._checked(g, self._creation(top.rel, want, c.id))
        elif top.kind == "link":
            self._take_down(g, top, tree)
            g.vacates.discard(fold_name(PurePosixPath(top.rel).name))
            g.creations += self._checked(g, self._creation(top.rel, want, c.id))
        else:
            self._reconcile(g, tree, Want.of(want, c.id))

    def _located(self) -> tuple[list[Record], dict[int, Record | None]]:
        """Every record, and for each (by id) the top-level record its owned chain of
        folders hangs from (None: the chain breaks at a folder with no record)."""
        all_recs = [r for recs in self._records(self.paths.ongoing).values() for r in recs]
        by_rel = {fold_parts(r.rel): r for r in all_recs}
        at: dict[int, Record | None] = {}

        def locate(r: Record) -> Record | None:
            if r.id in at:
                return at[r.id]
            if self._is_top(r.rel):
                at[r.id] = r
                return r
            above = by_rel.get(fold_parts(parent(r.rel)))
            at[r.id] = None if above is None else locate(above)
            return at[r.id]

        for r in all_recs:
            locate(r)
        return all_recs, at

    def _tree_records(
        self, tree: list[Collection], all_recs: list[Record], at: dict[int, Record | None]
    ) -> tuple[list[Record], list[Record], list[Record]]:
        """(tops, inner, orphans) of ``_share`` for the collections ``tree``."""
        ids = {c.id for c in tree}
        tops = [r for r in all_recs if self._is_top(r.rel) and r.collection_id in ids]
        top_ids = {r.id for r in tops}
        inner, orphans = [], []
        for r in all_recs:
            if self._is_top(r.rel):
                continue
            where = at.get(r.id)
            if where is not None and where.id in top_ids:
                inner.append(r)
            elif where is None and r.collection_id in ids:
                orphans.append(r)
        return tops, inner, orphans

    def _shares(self, collections: list[Collection], problems: list[str]) -> list[Share]:
        """One share per tree (root collection), in tree order, then the ★ built-in's
        (its links at the top level, named after every tree's fresh entry). A tree
        whose entries cannot be read is skipped (reported in ``problems``). Raises
        ``ArchiveUnavailable`` when Ongoing is not a listable folder."""
        ongoing = self._ongoing_dir()
        all_recs, at = self._located()
        roots, children = forest(collections)
        shares = []
        for root in roots:
            tree = flatten(root, children)
            try:
                tops, inner, orphans = self._tree_records(tree, all_recs, at)
                shares.append(self._share(root, children, tops, inner, orphans))
            except OSError as e:  # unknown, not gone: keep its records, plan nothing
                log.warning("ongoing: cannot read the entry of %s: %s", root.name, e)
                problems.append(
                    f"{root.name}: its entry in {self.paths.ongoing} could not be read."
                )
                shares.append(Share(root, tree, skipped=True))
            except LeftAlone as e:
                problems.append(f"{root.name}: {e}")
                shares.append(Share(root, tree, skipped=True, left_alone=str(e)))
        # Fresh top-level names: everything on disk is taken except names this plan
        # vacates (their removals run first), plus the names handed out here.
        taken = {fold_name(n) for n in os.listdir(ongoing)}
        for g in shares:
            taken -= g.vacates
        for g in shares:
            if g.fresh is None:
                continue
            name = first_free(g.collection.name, taken)
            taken.add(fold_name(name))
            g.creations += self._checked(
                g, self._creation(join(self.paths.ongoing, name), g.fresh, g.collection.id)
            )
        star = self._builtin("starred")
        if star is not None:
            shares.append(
                self._guarded(star, problems, lambda: self._star_share(star, all_recs, taken))
            )
        return shares

    def _guarded(self, c: Collection, problems: list[str], build) -> Share:
        """``build()`` a built-in's share; a record that cannot be read, or whose
        identity moved, leaves the whole share alone this sync (as for a tree)."""
        try:
            return build()
        except OSError as e:  # unknown, not gone: keep its records, plan nothing
            log.warning("ongoing: cannot read the entry of %s: %s", c.name, e)
            problems.append(f"{c.name}: its entry could not be read.")
            return Share(c, [c], skipped=True)
        except LeftAlone as e:
            problems.append(f"{c.name}: {e}")
            return Share(c, [c], skipped=True, left_alone=str(e))

    def _star_share(self, c: Collection, all_recs: list[Record], taken: set[str]) -> Share:
        """The ★ built-in's share: one link per live member at the top of Ongoing,
        named after the member (``first_free`` among everything at the top: what is
        on disk, less what this plan vacates, plus the fresh names handed out to the
        trees in ``taken``). An owned link is kept while it points at a member and
        its name is a variant of that member's; a replaced one is foreign from then
        on (reported). Nothing but its own links is ever planned."""
        g = Share(c, [c], root_rel=self.paths.ongoing)
        owned: list[Record] = []
        for r in sorted((r for r in all_recs if r.collection_id == c.id), key=lambda r: r.rel):
            if r.kind != "link" or not self._is_top(r.rel):
                g.forget.append(r.id)  # never made by this share: forgotten quietly
                continue
            if not self._owned(r):
                g.forget.append(r.id)
                if os.path.lexists(self.paths.abs(r.rel)):
                    g.note(c.id, f"{r.rel}{REPLACED}")
                continue
            g.owned.append(r)
            owned.append(r)
        wanted: list[WantedLink] = []
        for m in self._live(c, self.paths.ongoing):
            name = wanted_name_of(m)
            if is_ds_store_name(name):
                g.note(c.id, f"{m.path} was not added because its name is reserved.")
                continue
            wanted.append(WantedLink(m.path, name, c.id))
        claimed: set[int] = set()
        for r in owned:
            name = PurePosixPath(r.rel).name
            found = self._target(self.paths.abs(r.rel))
            match = next(
                (
                    i
                    for i, link in enumerate(wanted)
                    if i not in claimed
                    and found is not None
                    and nfc(link.target) == nfc(found)
                    and is_variant(name, link.base)
                ),
                None,
            )
            if match is not None:
                claimed.add(match)
            else:
                g.removals.append(Op(OpKind.UNLINK_SYMLINK, r.rel, None))
                g.vacates.add(fold_name(name))
        names = set(taken) - g.vacates
        pairs: list[tuple[Op, int]] = []
        for i, link in enumerate(wanted):
            if i in claimed:
                continue
            name = first_free(link.base, names)
            names.add(fold_name(name))
            pairs.append(
                (Op(OpKind.SYMLINK, link.target, join(self.paths.ongoing, name), exact=True), c.id)
            )
        g.creations += self._checked(g, pairs)
        return g

    # --- the Important root ----------------------------------------------------------

    def _important_shares(self, problems: list[str]) -> list[Share]:
        """The ! built-in's share for ``##. Important`` (empty when there is no such
        collection): skipped, with the reason as its status, when the folder is not
        a listable folder, or the two roots are configured as the same folder."""
        c = self._builtin("important")
        if c is None:
            return []
        root = self.paths.important
        if not self._roots_distinct:
            why = (
                f"{root} and {self.paths.ongoing} must not be inside each other. "
                "Check the folder settings; nothing was published."
            )
            problems.append(why)
            return [Share(c, [c], skipped=True, left_alone=why)]
        try:
            self._root_dir(root)
        except ArchiveUnavailable as e:
            problems.append(str(e))
            return [Share(c, [c], skipped=True, left_alone=str(e))]
        return [self._guarded(c, problems, lambda: self._important_share(c, root))]

    def _important_share(
        self, c: Collection, root: str, vacated: frozenset[str] = frozenset()
    ) -> Share:
        """Reconcile the root folder itself: what the publisher owns in it (from the
        records under ``root``, parents first, each owned only inside an owned folder
        or the root) against the collection's members and groups, exactly as a
        collection's own folder in Ongoing. The root is a synthetic node that is never
        removed (no record, no identity, never a removal op); its foreign entries (the
        user's own shortcuts and files) only take names. ``vacated`` (the Important
        converter, folded top-level names): foreign entries of the root taken as
        already removed by the conversion's earlier ops in the same batch."""
        g = Share(c, [c], root_rel=root)
        node = Node(Record(0, c.id, root, "folder", None, Identity(0, 0)), (c.id,))
        nodes: dict[tuple[str, ...], Node] = {fold_parts(root): node}
        recs = [r for rs in self._records(root).values() for r in rs]
        for r in sorted(recs, key=lambda r: (depth_of(r.rel), r.rel)):
            if r.collection_id != c.id:
                continue  # another collection's (or root's) record: not this share's
            above = nodes.get(fold_parts(parent(r.rel)))
            if above is None:
                g.forget.append(r.id)  # not inside an owned folder: forgotten quietly
                continue
            if self._owned(r):
                name = PurePosixPath(r.rel).name
                g.owned.append(r)
                if r.kind == "link":
                    above.links[name] = r
                else:
                    above.folders[name] = nodes[fold_parts(r.rel)] = Node(r, above.owners)
                continue
            g.forget.append(r.id)
            if (r.kind == "folder" or above is node) and os.path.lexists(self.paths.abs(r.rel)):
                g.note(c.id, f"{r.rel}{REPLACED}")
        for n in nodes.values():
            self._list(n)
        node.blocker = None  # the root is never removed, so nothing can block that
        node.foreign = [n for n in node.foreign if fold_name(n) not in vacated]
        links: dict[str, str] = {}
        folders: list[str] = []
        owners: dict[str, int] = {}
        refused: list[str] = []
        want = self._want(c, {}, "", links, folders, owners, refused, {c.id}, root)
        for r in refused:
            g.note(c.id, f"{r} was not added because its name is reserved.")
        desired = Desired(
            "folder",
            root,
            links=links,
            folders=tuple(folders),
            refused=tuple(refused),
            owners=owners,
            want=want,
        )
        self._reconcile(g, node, Want.of(desired, c.id))
        return g

    @staticmethod
    def _ordered(shares: list[Share]) -> list[Op]:
        """All removals first, then all creations (each in tree order)."""
        live = [g for g in shares if not g.skipped]
        return [op for g in live for op in g.removals] + [op for g in live for op in g.creations]

    def _trees_of(
        self, collection_ids: list[int], changed: dict[int, Collection]
    ) -> list[Collection]:
        """Every collection of every tree one of ``collection_ids`` is in, in tree
        order, with ``changed`` (by id) in place of the stored ones."""
        cols = [changed.get(c.id, c) for c in self.collections.list(None)]
        roots, children = forest(cols)
        wanted = set(collection_ids)
        out: list[Collection] = []
        for root in roots:
            tree = flatten(root, children)
            if any(c.id in wanted for c in tree):
                out += tree
        return out

    def preview_for(
        self,
        collection_ids: list[int],
        *,
        state: str | None = None,
        publish: bool | None = None,
        name: str | None = None,
    ) -> list[ResolvedOp]:
        """What a sync of these collections' trees would do, optionally as if they
        were in ``state``, had the Ongoing publisher ``publish``ed on/off, or were
        called ``name`` (for previewing a user's close / toggle / rename). Reads only
        (``Publisher`` protocol). A collection is planned with its whole tree (its
        place is inside its parent's folder), so the plan can include what the tree
        is waiting for anyway.

        The sync that follows the change re-plans from the disk and the DB at that
        moment; the executor re-validates it, so a change in between is caught there.
        """
        changed = {}
        for i in collection_ids:
            c = self.collections.get(i)
            if state is not None:
                c = dataclasses.replace(c, state=state)
            if name is not None:
                c = dataclasses.replace(c, name=name)
            if publish is not None:
                c = dataclasses.replace(c, publish={**c.publish, PUBLISHER_ID: publish})
            changed[c.id] = c
        shares = self._shares(self._trees_of(collection_ids, changed), [])
        self._hold(shares)
        ops = self._ordered(shares)
        return self.executor.preview(Plan(ops, ORIGIN)) if ops else []

    # --- for the Ongoing converter ----------------------------------------------------
