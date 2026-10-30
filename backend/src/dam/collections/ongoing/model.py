"""The Ongoing publisher's model: its constants, the desired and recorded entries,
and the helpers for names and trees (``dam.collections.ongoing``)."""

from __future__ import annotations

import logging
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from dam.core.paths import nfc
from dam.core.text import fold_name
from dam.ops.guards import parent
from dam.ops.identity import Identity
from dam.ops.model import BatchResult, Op, ResolvedOp

if TYPE_CHECKING:
    from dam.collections.service import Collection

# every part of the package logs under its name, as when it was one module
log = logging.getLogger("dam.collections.ongoing")

PUBLISHER_ID = "ongoing"
ORIGIN = "workflow"
NOT_MANAGED = "Needs attention: "
NOT_SHOWN = "Not shown: "  # a status only: the collection is hidden with its parent
REPLACED = " was changed outside the app, so it was left as it is."
RETRY_FAILED_S = 3600.0  # an unchanged failed plan is retried after this long
IDENTITY_CHANGED = (
    "{rel} looks different from before (Google Drive may have re-created it),"
    " so it was left as it is."
)

# a collection's children by parent id (``None``: the roots), in tree order
Children = dict[int | None, list["Collection"]]


class LeftAlone(Exception):
    """A tree the sync must not touch this time (the message says why)."""


@dataclass(frozen=True)
class Desired:
    """What a collection (with its published descendants) should look like in Ongoing.

    ``rel`` is the wanted path ``##. Ongoing/<name>``; the plan may use ``<name>_2``
    when something it does not own is there. ``kind="link"`` (a collection without
    groups or published children whose one live member is a folder): ``target`` is
    that folder's rel. ``kind="folder"``: ``folders`` are the group subfolders and the
    child collections' folders as paths relative to ``rel`` (parents first), and
    ``links`` maps a link path relative to ``rel`` (with ``/`` for a link inside a
    folder) -> member rel, in member order (the basename; a collision between members
    in the same folder gets ``_2``; a group or child whose name a sibling has gets
    ``_2``); a child in the direct-link form is one link named after it. ``owners``:
    the paths (folders or links) that are a child collection's own entry -> that
    child's id; everything else belongs to the nearest owner above (the root).
    ``refused``: member rels that cannot be linked (their name is reserved).

    These are the wanted names; the plan keeps an owned entry whose name is a
    ``first_free`` variant of the wanted one and avoids names others hold."""

    kind: str
    rel: str
    target: str | None = None
    links: dict[str, str] = field(default_factory=dict)
    folders: tuple[str, ...] = ()
    refused: tuple[str, ...] = ()
    owners: dict[str, int] = field(default_factory=dict)
    # group id -> the group's folder, a path relative to ``rel`` (compare=False: what a
    # sync plans never depends on it; turning groups into collections does)
    groups: dict[int, str] = field(default_factory=dict, compare=False, repr=False)
    # the same as a tree, with each link's base name and owner (built with the
    # Desired; ``Want.of`` reconstructs it when absent)
    want: Want | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class WantedLink:
    target: str
    base: str  # the name wanted before any ``_n`` suffix (its variants are kept)
    owner: int  # the collection the link is recorded for


@dataclass
class Want:
    """``Desired`` (kind folder) as a tree: one node per folder, with the collection
    that owns the folder (the root's, a group's, or a child collection's)."""

    owner: int = 0
    base: str = ""  # the folder's name before any ``_n`` suffix (its variants are kept)
    links: dict[str, WantedLink] = field(default_factory=dict)  # link name -> link
    folders: dict[str, Want] = field(default_factory=dict)  # folder name -> subtree

    @classmethod
    def of(cls, want: Desired, owner: int) -> Want:
        if want.want is not None:
            return want.want
        root = cls(owner)
        for path in want.folders:
            node = root.at(parent(path))
            name = PurePosixPath(path).name
            node.folders[name] = cls(want.owners.get(path, node.owner), name)
        for path, target in want.links.items():
            node = root.at(parent(path))
            name = PurePosixPath(path).name
            node.links[name] = WantedLink(
                target, PurePosixPath(target).name, want.owners.get(path, node.owner)
            )
        return root

    def at(self, path: str) -> Want:
        node = self
        for part in PurePosixPath(path).parts:
            node = node.folders[part]
        return node


@dataclass
class SyncResult:
    """``plan``: the resolved ops of every root; ``batch``: the last batch applied
    (None when no root applied one); ``batches``: one per root that applied one."""

    plan: list[ResolvedOp]
    batch: BatchResult | None
    problems: list[str] = field(default_factory=list)
    batches: list[BatchResult] = field(default_factory=list)


@dataclass
class Layout:
    """The publisher's share of a conversion batch for one collection (see
    ``OngoingPublisher.layout_after``). ``removals``: the collection's own entries
    that would have to go first; ``switches``: an ancestor's direct link that the
    batch replaces with a folder (``creations`` then holds that folder and the
    ancestor's own links in it too); ``reasons``: what will not be linked, and why.
    ``for_id``: the collection's id at planning (0 for one not created yet)."""

    creations: list[Op]
    removals: list[Op]
    reasons: list[str]
    share: Share
    for_id: int = 0
    switches: list[Op] = field(default_factory=list)


@dataclass(frozen=True)
class Record:
    id: int
    collection_id: int
    rel: str
    kind: str  # link | folder
    link_value: str | None
    ident: Identity


@dataclass
class Node:
    """An owned folder in Ongoing (a collection's, a group's, or a child
    collection's), with what the publisher owns directly inside it and what it does
    not. ``owners``: the collection ids from the tree's root down to the collection
    whose folder this is (a problem with the folder is reported to each)."""

    rec: Record
    owners: tuple[int, ...] = ()
    links: dict[str, Record] = field(default_factory=dict)  # owned links, by name
    folders: dict[str, Node] = field(default_factory=dict)  # owned subfolders, by name
    foreign: list[str] = field(default_factory=list)  # names the app did not create
    blocker: str | None = None  # why this folder itself cannot be removed

    def removable(self) -> bool:
        """Nothing foreign in it or in any owned folder below it."""
        return self.blocker is None and all(n.removable() for n in self.folders.values())

    def blockers(self) -> list[tuple[str, tuple[int, ...]]]:
        out = [(self.blocker, self.owners)] if self.blocker is not None else []
        for n in self.folders.values():
            out += n.blockers()
        return out


@dataclass
class Share:
    """One tree's share of the plan (``collection`` is its root, ``tree`` every
    collection in it, root first), and what to record once it has run."""

    collection: Collection
    tree: list[Collection] = field(default_factory=list)
    owned: list[Record] = field(default_factory=list)  # records that still match
    forget: list[int] = field(default_factory=list)  # record ids that no longer match
    removals: list[Op] = field(default_factory=list)
    creations: list[Op] = field(default_factory=list)
    # folded creation path -> the collection id the entry is recorded for
    owner_of: dict[tuple[str, ...], int] = field(default_factory=dict)
    per: dict[int, list[str]] = field(default_factory=dict)  # reasons, by collection
    vacates: set[str] = field(default_factory=set)  # top-level names (folded) removed
    fresh: Desired | None = None  # still needs a new top-level entry (named later)
    skipped: bool = False  # refused at preview on its own: neither run nor recorded
    left_alone: str | None = None  # skipped for this reason (shown as its status)
    # a built-in's share (★ at the top of Ongoing, ! at the root of Important): the
    # root it publishes into, which is also its ``ongoing_rel``
    root_rel: str | None = None
    # group folders published under another name than wanted: (wanted rel, actual
    # rel), for a conversion preview (a sync says nothing about them)
    suffixed: list[tuple[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.tree:
            self.tree = [self.collection]

    @property
    def ops(self) -> list[Op]:
        return [*self.removals, *self.creations]

    def note(self, collection_id: int, text: str) -> None:
        """Report ``text`` in ``collection_id``'s status (once)."""
        reasons = self.per.setdefault(collection_id, [])
        if text not in reasons:
            reasons.append(text)

    def reasons_for(self, collection_id: int) -> list[str]:
        return list(self.per.get(collection_id, []))


def items_text(n: int) -> str:
    return f"{n} item" if n == 1 else f"{n} items"


def entry_kind(p: Path) -> str | None:
    """link, dir, file or None (nothing there). Never follows a link."""
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(st.st_mode):
        return "link"
    return "dir" if stat.S_ISDIR(st.st_mode) else "file"


def split_name(name: str) -> tuple[str, str]:
    p = Path(name)
    return p.stem, p.suffix


def first_free(name: str, taken: set[str]) -> str:
    """``name``, or ``<stem>_<n><suffix>`` (n = 2, 3, ...): the first whose NFC casefold
    is not in ``taken``. Same rule as ``dam.core.naming.unique_name``."""
    if fold_name(name) not in taken:
        return name
    stem, suffix = split_name(name)
    n = 2
    while fold_name(f"{stem}_{n}{suffix}") in taken:
        n += 1
    return f"{stem}_{n}{suffix}"


def is_variant(base: str, name: str) -> bool:
    """``base`` is ``name`` or a ``first_free`` suffix variant of it (exact spelling)."""
    base, name = nfc(base), nfc(name)
    if base == name:
        return True
    stem, suffix = split_name(name)
    return re.fullmatch(rf"{re.escape(stem)}_[0-9]+{re.escape(suffix)}", base) is not None


def names_for_links(
    wanted: list[tuple[str, str]], taken: set[str] = frozenset()
) -> dict[str, tuple[str, str]]:
    """Link name -> (target, wanted name) for the ``(target, wanted name)`` pairs in
    order: the wanted name, suffixed on collision."""
    used = set(taken)
    out: dict[str, tuple[str, str]] = {}
    for target, base in wanted:
        name = first_free(base, used)
        used.add(fold_name(name))
        out[name] = (target, base)
    return out


def wanted_name_of(m) -> str:
    """The name a member's link is wanted under: its ``link_name`` (a converted
    shortcut's own name) or the file's own name."""
    return m.link_name or PurePosixPath(m.path).name


def depth_of(rel: str) -> int:
    return len(PurePosixPath(rel).parts)


def forest(collections: list[Collection]) -> tuple[list[Collection], Children]:
    """The roots (a collection whose parent is not in the list counts as one) and the
    children by parent id, both in the given (tree) order."""
    ids = {c.id for c in collections}
    roots: list[Collection] = []
    children: Children = {}
    for c in collections:
        if c.parent_id is None or c.parent_id not in ids:
            roots.append(c)
        else:
            children.setdefault(c.parent_id, []).append(c)
    reached = {c.id for root in roots for c in flatten(root, children)}
    dropped = [c for c in collections if c.id not in reached]
    if dropped:  # a parent cycle (the service refuses them): planned by no tree at all
        log.warning(
            "ongoing: %s are in a parent cycle; left alone",
            ", ".join(repr(c.name) for c in dropped),
        )
    return roots, children


def flatten(root: Collection, children: Children) -> list[Collection]:
    """``root`` and every descendant, parents first (a cycle is never followed)."""
    out: list[Collection] = []
    seen: set[int] = set()

    def walk(c: Collection) -> None:
        if c.id in seen:
            return
        seen.add(c.id)
        out.append(c)
        for k in children.get(c.id, []):
            walk(k)

    walk(root)
    return out
