"""What should be in ``##. Ongoing``: each published collection's desired entries. Part of
``OngoingPublisher`` (``dam.collections.ongoing``)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dam.core.text import fold_name
from dam.ops.guards import is_ds_store_name, is_under, join

if TYPE_CHECKING:
    from dam.collections.service import Collection
from dam.collections.ongoing.model import (
    PUBLISHER_ID,
    Children,
    Desired,
    Want,
    WantedLink,
    first_free,
    forest,
    names_for_links,
    wanted_name_of,
)


class DesiredMixin:
    """What should be in ``##. Ongoing``: each published collection's desired entries."""

    def _live(self, c: Collection, root: str | None = None) -> list:
        """The members that get a link in ``root`` (Ongoing by default)."""
        root = self.paths.ongoing if root is None else root
        live = []
        for m in c.members:
            if m.missing or m.quarantined or not m.path:
                continue
            if is_under(m.path, root):
                continue  # never link a root to itself (e.g. a real file not converted)
            live.append(m)
        return live

    def _shown(self, c: Collection, children: Children, seen: frozenset = frozenset()) -> bool:
        """``c`` is published: open, the publisher on, and something to show (a live
        member of its own, or a published child). A child is only ever asked about
        through its parent, so an unpublished parent hides its whole subtree."""
        if c.state != "open" or not c.publish.get(PUBLISHER_ID, False) or c.id in seen:
            return False
        if self._live(c):
            return True
        seen = seen | {c.id}
        return any(self._shown(k, children, seen) for k in children.get(c.id, []))

    def _kids(self, c: Collection, children: Children) -> list[Collection]:
        return [k for k in children.get(c.id, []) if self._shown(k, children, frozenset({c.id}))]

    def desired_one(self, c: Collection) -> Desired | None:
        """``desired_tree`` for ``c`` on its own (as if it had no children)."""
        return self.desired_tree(c, {})

    def desired_tree(self, c: Collection, children: Children) -> Desired | None:
        """The wanted entry for ``c`` with every published descendant nested in it,
        None when ``c`` is not published (then nothing of its tree is)."""
        if not self._shown(c, children):
            return None
        rel = join(self.paths.ongoing, c.name)
        live = self._live(c)
        if len(live) == 1 and live[0].is_dir and not c.groups and not self._kids(c, children):
            return Desired(kind="link", rel=rel, target=live[0].path)
        links: dict[str, str] = {}
        folders: list[str] = []
        owners: dict[str, int] = {}
        refused: list[str] = []
        group_paths: dict[int, str] = {}
        want = self._want(
            c,
            children,
            "",
            links,
            folders,
            owners,
            refused,
            {c.id},
            self.paths.ongoing,
            group_paths,
        )
        return Desired(
            "folder",
            rel,
            links=links,
            folders=tuple(folders),
            refused=tuple(refused),
            owners=owners,
            groups=group_paths,
            want=want,
        )

    def _want(
        self,
        c: Collection,
        children: Children,
        prefix: str,
        links: dict[str, str],
        folders: list[str],
        owners: dict[str, int],
        refused: list[str],
        seen: set[int],
        root: str,
        group_paths: dict[int, str] | None = None,
    ) -> Want:
        """The folder of ``c`` at ``prefix``: its member links, its group folders, then
        its published children (A-Z), each named ``first_free`` among its siblings.
        ``root``: the publish root (members inside it are not linked)."""
        groups = {g.id: g for g in c.groups}
        by_parent: dict[int | None, list] = {}
        for g in c.groups:
            by_parent.setdefault(g.parent_id, []).append(g)
        targets: dict[int | None, list[tuple[str, str]]] = {}
        for m in self._live(c, root):
            if is_ds_store_name(wanted_name_of(m)):
                refused.append(m.path)
            else:  # a group this collection does not have: shown ungrouped
                targets.setdefault(m.group_id if m.group_id in groups else None, []).append(
                    (m.path, wanted_name_of(m))
                )
        seen_groups: set[int] = set()

        def walk(group_id: int | None, at: str, taken: set[str], base: str) -> Want:
            node = Want(c.id, base)
            for name, (target, base) in names_for_links(targets.get(group_id, []), taken).items():
                links[join(at, name)] = target
                node.links[name] = WantedLink(target, base, c.id)
                taken.add(fold_name(name))
            for g in by_parent.get(group_id, []):
                if g.id in seen_groups:  # never (the service refuses cycles); never loop
                    continue
                seen_groups.add(g.id)
                name = first_free(g.name, taken)
                taken.add(fold_name(name))
                folders.append(join(at, name))
                if group_paths is not None:  # each group's folder, by id
                    group_paths[g.id] = join(at, name)
                node.folders[name] = walk(g.id, join(at, name), set(), g.name)
            return node

        taken: set[str] = set()
        node = walk(None, prefix, taken, c.name)
        for kid in self._kids(c, children):
            if kid.id in seen:  # never (the service refuses cycles); never loop
                continue
            seen.add(kid.id)
            name = first_free(kid.name, taken)
            taken.add(fold_name(name))
            path = join(prefix, name)
            owners[path] = kid.id
            live = self._live(kid)
            if (
                len(live) == 1
                and live[0].is_dir
                and not kid.groups
                and not self._kids(kid, children)
            ):
                links[path] = live[0].path
                node.links[name] = WantedLink(live[0].path, kid.name, kid.id)
                continue
            folders.append(path)
            node.folders[name] = self._want(
                kid, children, path, links, folders, owners, refused, seen, root, group_paths
            )
        return node

    def desired(self, collections: list[Collection]) -> dict[str, Desired]:
        """Root collection name -> desired entry (its tree nested in it), for the
        open, published collections."""
        roots, children = forest(collections)
        out = {}
        for c in roots:
            want = self.desired_tree(c, children)
            if want is not None:
                out[c.name] = want
        return out

    # --- reading the disk and the records --------------------------------------------
