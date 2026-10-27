"""The Ongoing publisher: each open, published collection mirrored in ``##. Ongoing``.

Layout: a collection whose only (live) member is a folder, and which has no groups and
no published child collections, is one direct link ``##. Ongoing/<name>`` -> that
folder; any other collection is a folder ``##. Ongoing/<name>/`` holding one link per
live ungrouped member, one subfolder per group (nested groups nest), each holding its
members' links, and one entry per published child collection (see below). A group's
folder is named after the group, ``<name>_2`` when a sibling has the name. A collection
without any live member and without a published child is not published at all (its
owned entries are taken down, as for a closed one). Missing, parked and quarantined
members get no link until they come back; a member whose name cannot be a link name
(e.g. ``.ds_store``) is skipped and named in the status.

Parent collections (round 2). ``##. Ongoing`` mirrors the collection tree: a child
collection is published *inside its parent's folder*, at ``##. Ongoing/<parent
path>/<name>``, in the same form it would take at the top (a direct link, or a folder
holding its links, groups and its own children). Its entry is a sibling of the parent's
member links and group folders, and name clashes among siblings of every kind (links,
group folders, child entries) get ``_2``, members first, then groups, then children
A-Z; the suffix is stable across syncs (an owned entry whose name is a variant of the
wanted one is kept). A parent with nothing of its own is still a folder while a child is
published in it. A child is published only while every ancestor is open and published
(the tree is one unit: an unpublished or closed parent takes its children down with it;
the service refuses to close a parent with open children, and stale state is handled
the same way). Moving a collection to another parent or to the top, and renaming a
child, take its whole subtree down and recreate it at the new place, in the same
batch, exactly as a group rename does; a root rename keeps the in-place rule below.
Planning works per *tree*: one share per top-level collection, whose desired state
nests its descendants; every entry is recorded for the collection it belongs to (the
child's folder or link, and what is inside it, for the child), so each collection has
its own ``ongoing_rel`` and ``ongoing_status``.

Ownership is by identity. Every entry the publisher creates (its folder, its links) is
recorded in ``ongoing_entries`` with the identity (``dam.ops.identity``) it has right after
creation and, for a link, the exact readlink value written. An entry is the publisher's
only while the record still matches: same rel, same kind, same dev/ino, same readlink
value (the birth time is not compared: Google Drive for desktop re-writes a new item a
few seconds after creating it, keeping the inode but giving it a new birth, so a birth
that differs while the rest matches is the app's own entry; the stored birth is then
refreshed). A mismatch means someone else replaced it: the record is forgotten, the entry is never
touched, and the collection's ``ongoing_status`` says so for as long as the entry is
there. Nothing else in ``##. Ongoing`` is ever touched either (real files, foreign
links, folders, foreign links inside the collection's own folder); something foreign at
a name the publisher wants makes it use ``<name>_2`` (``unique_name`` semantics). An
existing link is never adopted, even one pointing at the right folder (the Ongoing
converter records ownership explicitly). ``collections.ongoing_rel`` mirrors the owned
top entry (the collection's own folder or link) for display.

Only "nothing there" (ENOENT) forgets a record. An entry that cannot be read for any
other reason is unknown: that tree is skipped for the sync (records kept, nothing
planned) and reported. So is a tree with an entry of the same kind and, for a link, the
same readlink value at its recorded rel but a new dev/ino (Drive may re-enumerate): it
is neither forgotten (which would publish ``<name>_2``) nor touched, and the
``ongoing_status`` says so. An Ongoing folder that lists as empty while entries are
recorded skips the whole sync (as the scanner's empty-root guard).

A folder (a collection's, or a group's) holding anything it does not own (other than a
genuine Finder ``.DS_Store``) is never removed, nor is any folder above it: its own
links are, and ``ongoing_status`` says ``"Needs attention: <reason>"`` (on the collection
whose folder it is, on the collection whose folder it was to leave, and on each
collection above it whose own folder had to stay because of it; a collection that
moved away still gets the note about what it left behind). The root collection's
folder also stays its place on a rename or a switch to a direct link, until it is
empty. Only folders the publisher created (recorded, identity matching) are ever
removed, always after their own links and subfolders, deepest first. A child
collection's folder is removed only when that child is taken down itself (closed,
unpublished, moved, renamed, or its tree taken down): the parent's reconciliation
keeps every wanted child folder in place.

Every disk change is a ``Plan`` (origin ``"workflow"``) of MKDIR / SYMLINK /
UNLINK_SYMLINK / REMOVE_EMPTY_DIR through the executor (journaled). All removals come
first, then all creations, so a name vacated in the same plan (a rename, or two
collections swapping names) is reused instead of suffixed. There is never a MOVE or
RENAME inside Ongoing: a renamed collection's entry, or a renamed or moved group's or
child's subtree, is removed and recreated. Creations are ``exact``: the path must
still be free at act time. These batches cannot be undone
(the DB is the truth; undo the collection change instead) and skip the throttle.
The one exception is the Ongoing converter's batch (origin ``"ui"``, undoable): it
carries the publisher's creations for the converted collection (``layout_after``),
and, when converting into a child whose ancestor is one direct link, that ancestor's
switch to a folder (the link's unlink, then the folder with the ancestor's own links,
recorded for the ancestor). The undo of such a batch puts the link back exactly as
it was; ``ongoing_switched`` remembers that it was the publisher's, and
``forget_undone`` records it again (same rel, same readlink value) once the undo has
run, so the sync that follows is quiet.

Races. ``sync`` reads the DB and lists Ongoing without holding ``SCAN_LOCK`` (it never
blocks scans), plans, then applies. If the user changes Ongoing in between, the
executor catches it: ``apply`` re-resolves the plan against the disk (an exact MKDIR or
SYMLINK whose path became occupied refuses the whole plan; nothing runs), then each op
is pre-checked at act time (destination exists, source no longer a link) and
``remove_empty_dir`` re-checks emptiness itself and that the folder still has the
recorded identity (every REMOVE_EMPTY_DIR carries the record's dev/ino: a folder of the
user's swapped in under the same name is refused on the opened fd); the batch stops at
the first refusal. The next sync re-plans from what is then on disk. A link swapped
between planning and its UNLINK is the one residual window (the executor checks only
that it is a link).
Syncs are serialised by a lock of their own, so two triggers never plan twice.
A plan that failed at act time is not applied again while every sync resolves to the
same plan (one failed batch in the journal, not one per trigger), for at most an hour
(then it is retried once more); ``last_failure`` says why until the plan changes or a
sync succeeds. It is kept in memory only.

Two roots (stars). The publisher also mirrors the two built-in collections, by their
``kind`` (their ``publish`` flag is empty and never consulted):

- ★ Ongoing (``starred``): one link per live member *at the top level* of
  ``##. Ongoing``, next to the project collections' entries, sharing their name space
  (a clash gets ``_2`` by ``first_free``; an owned variant of the wanted name is
  kept, so the suffix is stable). Its records are top-level links recorded for the
  built-in; the project trees never see them (they are not of any tree's collection)
  and avoid their names like any other entry on disk.
- ! Important (``important``): published at the root of ``##. Important`` itself,
  which is a top-level archive folder the publisher never creates or removes: its
  members at the top, its groups as subfolders (nested), reconciled exactly like a
  collection's own folder in Ongoing (``_reconcile`` on a synthetic, unremovable node
  for the root). Identity records, no adoption (the user's existing shortcuts there
  are foreign until the Important converter adopts them: a clash gets ``_2``), the
  left-alone rules, the empty-listing guard and the failing-sync throttle all apply
  per root. When ``##. Important`` is missing or not a folder, that root does nothing
  and says so (the built-in's ``ongoing_status``); the Ongoing root still syncs.

Records are partitioned by their ``rel`` (every record lies under exactly one root,
``_records(root)``; the roots must not contain each other, else the Important root
is left alone and says so), so ``ongoing_entries`` needs no root column; each root is
planned, previewed, applied (one batch per root, so a refusal or failure in one
never holds the other back) and recorded on its own, under the same ``sync_lock``.
The empty-listing guard is per root too: an ``##. Important`` that lists empty while
records exist skips only that root, so a Drive that is partly there never makes the
app forget (and then republish as ``_2``) what it owns in ``##. Important``.
The deletion exception is the same under both roots: only app-owned links and
app-owned (identity-matched) empty folders strictly inside the root, plus a genuine
Finder ``.DS_Store``; the guards (``ops.guards``) and the primitives take the root as
a parameter and refuse everything else. The one addition is a *conversion* (origin
``"ui"``, previewed with a fingerprint, undoable): the Important converter's batch
(``collections.convert_important``) unlinks the user's own links in ``##. Important``
and carries this publisher's creations for the built-in as it will be
(``important_layout_after``); "Star it" in the Ongoing converter does the same for
one ★ link (``star_layout_after``). Both are recorded with ``record_layout``.

Archive folders that are not there. A member in an extra archive folder that is not
connected now (an unplugged disk) is not gone, and one in a detached folder is left
as it was: a sync leaves out every change to a link into such a folder (no link is
created, repaired, replaced or taken down, nor the folder it is in, nor whatever was
to take its place) and plans the rest as usual (``_hold``). Once the folder is back,
the next sync catches up.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import re
import stat
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from dam.core.fs import readlink, resolve
from dam.core.paths import ArchivePaths, OutsideArchiveError, nfc
from dam.core.text import fold_name
from dam.db.engine import write_tx
from dam.db.tables import collections as collections_table
from dam.db.tables import ongoing_entries, ongoing_switched, operations
from dam.index.scanner import is_ignored
from dam.ops import identity, primitives
from dam.ops.guards import fold_parts, is_ds_store_name, is_under, join, parent, validate
from dam.ops.identity import Identity
from dam.ops.model import BatchResult, GuardError, Op, OpKind, Plan, ResolvedOp
from dam.services.errors import ArchiveUnavailable, InvalidRequest, NotFound

if TYPE_CHECKING:
    from dam.collections.service import Collection, CollectionService
    from dam.index.repo import FileRepo
    from dam.ops.executor import Executor

log = logging.getLogger(__name__)

PUBLISHER_ID = "ongoing"
ORIGIN = "workflow"
NOT_MANAGED = "Needs attention: "
NOT_SHOWN = "Not shown: "  # a status only: the collection is hidden with its parent
_REPLACED = " was changed outside the app, so it was left as it is."
RETRY_FAILED_S = 3600.0  # an unchanged failed plan is retried after this long
_IDENTITY = (
    "{rel} looks different from before (Google Drive may have re-created it),"
    " so it was left as it is."
)

# a collection's children by parent id (``None``: the roots), in tree order
_Children = dict[int | None, list["Collection"]]


class _LeftAlone(Exception):
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
    # the same as a tree, with each link's base name and owner (built with the
    # Desired; ``_Want.of`` reconstructs it when absent)
    want: _Want | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class _Link:
    target: str
    base: str  # the name wanted before any ``_n`` suffix (its variants are kept)
    owner: int  # the collection the link is recorded for


@dataclass
class _Want:
    """``Desired`` (kind folder) as a tree: one node per folder, with the collection
    that owns the folder (the root's, a group's, or a child collection's)."""

    owner: int = 0
    base: str = ""  # the folder's name before any ``_n`` suffix (its variants are kept)
    links: dict[str, _Link] = field(default_factory=dict)  # link name -> link
    folders: dict[str, _Want] = field(default_factory=dict)  # folder name -> subtree

    @classmethod
    def of(cls, want: Desired, owner: int) -> _Want:
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
            node.links[name] = _Link(
                target, PurePosixPath(target).name, want.owners.get(path, node.owner)
            )
        return root

    def at(self, path: str) -> _Want:
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
    share: _Share
    for_id: int = 0
    switches: list[Op] = field(default_factory=list)


@dataclass(frozen=True)
class _Record:
    id: int
    collection_id: int
    rel: str
    kind: str  # link | folder
    link_value: str | None
    ident: Identity


@dataclass
class _Node:
    """An owned folder in Ongoing (a collection's, a group's, or a child
    collection's), with what the publisher owns directly inside it and what it does
    not. ``owners``: the collection ids from the tree's root down to the collection
    whose folder this is (a problem with the folder is reported to each)."""

    rec: _Record
    owners: tuple[int, ...] = ()
    links: dict[str, _Record] = field(default_factory=dict)  # owned links, by name
    folders: dict[str, _Node] = field(default_factory=dict)  # owned subfolders, by name
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
class _Share:
    """One tree's share of the plan (``collection`` is its root, ``tree`` every
    collection in it, root first), and what to record once it has run."""

    collection: Collection
    tree: list[Collection] = field(default_factory=list)
    owned: list[_Record] = field(default_factory=list)  # records that still match
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


def _items(n: int) -> str:
    return f"{n} item" if n == 1 else f"{n} items"


def _kind(p: Path) -> str | None:
    """link, dir, file or None (nothing there). Never follows a link."""
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(st.st_mode):
        return "link"
    return "dir" if stat.S_ISDIR(st.st_mode) else "file"


def _split(name: str) -> tuple[str, str]:
    p = Path(name)
    return p.stem, p.suffix


def first_free(name: str, taken: set[str]) -> str:
    """``name``, or ``<stem>_<n><suffix>`` (n = 2, 3, ...): the first whose NFC casefold
    is not in ``taken``. Same rule as ``dam.core.naming.unique_name``."""
    if fold_name(name) not in taken:
        return name
    stem, suffix = _split(name)
    n = 2
    while fold_name(f"{stem}_{n}{suffix}") in taken:
        n += 1
    return f"{stem}_{n}{suffix}"


def _is_variant(base: str, name: str) -> bool:
    """``base`` is ``name`` or a ``first_free`` suffix variant of it (exact spelling)."""
    base, name = nfc(base), nfc(name)
    if base == name:
        return True
    stem, suffix = _split(name)
    return re.fullmatch(rf"{re.escape(stem)}_[0-9]+{re.escape(suffix)}", base) is not None


def _link_names(
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


def _wanted_name(m) -> str:
    """The name a member's link is wanted under: its ``link_name`` (a converted
    shortcut's own name) or the file's own name."""
    return m.link_name or PurePosixPath(m.path).name


def _depth(rel: str) -> int:
    return len(PurePosixPath(rel).parts)


def _forest(collections: list[Collection]) -> tuple[list[Collection], _Children]:
    """The roots (a collection whose parent is not in the list counts as one) and the
    children by parent id, both in the given (tree) order."""
    ids = {c.id for c in collections}
    roots: list[Collection] = []
    children: _Children = {}
    for c in collections:
        if c.parent_id is None or c.parent_id not in ids:
            roots.append(c)
        else:
            children.setdefault(c.parent_id, []).append(c)
    reached = {c.id for root in roots for c in _flatten(root, children)}
    dropped = [c for c in collections if c.id not in reached]
    if dropped:  # a parent cycle (the service refuses them): planned by no tree at all
        log.warning(
            "ongoing: %s are in a parent cycle; left alone",
            ", ".join(repr(c.name) for c in dropped),
        )
    return roots, children


def _flatten(root: Collection, children: _Children) -> list[Collection]:
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


class OngoingPublisher:
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

    def _shown(self, c: Collection, children: _Children, seen: frozenset = frozenset()) -> bool:
        """``c`` is published: open, the publisher on, and something to show (a live
        member of its own, or a published child). A child is only ever asked about
        through its parent, so an unpublished parent hides its whole subtree."""
        if c.state != "open" or not c.publish.get(PUBLISHER_ID, False) or c.id in seen:
            return False
        if self._live(c):
            return True
        seen = seen | {c.id}
        return any(self._shown(k, children, seen) for k in children.get(c.id, []))

    def _kids(self, c: Collection, children: _Children) -> list[Collection]:
        return [k for k in children.get(c.id, []) if self._shown(k, children, frozenset({c.id}))]

    def desired_one(self, c: Collection) -> Desired | None:
        """``desired_tree`` for ``c`` on its own (as if it had no children)."""
        return self.desired_tree(c, {})

    def desired_tree(self, c: Collection, children: _Children) -> Desired | None:
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
        want = self._want(
            c, children, "", links, folders, owners, refused, {c.id}, self.paths.ongoing
        )
        return Desired(
            "folder",
            rel,
            links=links,
            folders=tuple(folders),
            refused=tuple(refused),
            owners=owners,
            want=want,
        )

    def _want(
        self,
        c: Collection,
        children: _Children,
        prefix: str,
        links: dict[str, str],
        folders: list[str],
        owners: dict[str, int],
        refused: list[str],
        seen: set[int],
        root: str,
    ) -> _Want:
        """The folder of ``c`` at ``prefix``: its member links, its group folders, then
        its published children (A-Z), each named ``first_free`` among its siblings.
        ``root``: the publish root (members inside it are not linked)."""
        groups = {g.id: g for g in c.groups}
        by_parent: dict[int | None, list] = {}
        for g in c.groups:
            by_parent.setdefault(g.parent_id, []).append(g)
        targets: dict[int | None, list[tuple[str, str]]] = {}
        for m in self._live(c, root):
            if is_ds_store_name(_wanted_name(m)):
                refused.append(m.path)
            else:  # a group this collection does not have: shown ungrouped
                targets.setdefault(m.group_id if m.group_id in groups else None, []).append(
                    (m.path, _wanted_name(m))
                )
        seen_groups: set[int] = set()

        def walk(group_id: int | None, at: str, taken: set[str], base: str) -> _Want:
            node = _Want(c.id, base)
            for name, (target, base) in _link_names(targets.get(group_id, []), taken).items():
                links[join(at, name)] = target
                node.links[name] = _Link(target, base, c.id)
                taken.add(fold_name(name))
            for g in by_parent.get(group_id, []):
                if g.id in seen_groups:  # never (the service refuses cycles); never loop
                    continue
                seen_groups.add(g.id)
                name = first_free(g.name, taken)
                taken.add(fold_name(name))
                folders.append(join(at, name))
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
                node.links[name] = _Link(live[0].path, kid.name, kid.id)
                continue
            folders.append(path)
            node.folders[name] = self._want(
                kid, children, path, links, folders, owners, refused, seen, root
            )
        return node

    def desired(self, collections: list[Collection]) -> dict[str, Desired]:
        """Root collection name -> desired entry (its tree nested in it), for the
        open, published collections."""
        roots, children = _forest(collections)
        out = {}
        for c in roots:
            want = self.desired_tree(c, children)
            if want is not None:
                out[c.name] = want
        return out

    # --- reading the disk and the records --------------------------------------------

    def _ongoing_dir(self) -> Path:
        """``_root_dir`` for Ongoing."""
        return self._root_dir(self.paths.ongoing)

    def _root_dir(self, root: str) -> Path:
        """The publish root ``root`` (Ongoing or Important), which must be a real,
        listable folder (else the archive is probably not mounted: planning against
        it would forget every link)."""
        p = self.paths.abs(root)
        try:
            if not stat.S_ISDIR(os.lstat(p).st_mode):
                raise ArchiveUnavailable(f"{root} is not a folder.")
            names = os.listdir(p)
        except OSError as e:
            log.warning("ongoing: cannot list %s: %s", root, e)
            raise ArchiveUnavailable(f"{root} is not available.") from None
        if not any(not is_ignored(n) for n in names) and self._has_records(root):
            # A folder that lists empty while the app owns entries in it is more likely
            # a Drive that is not (fully) there than everything removed (as the scanner)
            raise ArchiveUnavailable(
                f"{root} looks empty, although the app put items there. Google Drive may not "
                "be fully available, so nothing was changed."
            )
        return p

    def _has_records(self, root: str) -> bool:
        with self.engine.connect() as conn:
            rels = conn.execute(select(ongoing_entries.c.rel)).scalars().all()
        return any(is_under(rel, root, strict=True) for rel in rels)

    def _records(self, root: str | None = None) -> dict[int, list[_Record]]:
        """The records by collection id: every one, or only those under ``root``
        (a record lies under exactly one root: its ``rel`` says which)."""
        with self.engine.connect() as conn:
            rows = conn.execute(select(ongoing_entries).order_by(ongoing_entries.c.rel)).all()
        out: dict[int, list[_Record]] = {}
        for r in rows:
            if root is not None and not is_under(r.rel, root, strict=True):
                continue
            out.setdefault(r.collection_id, []).append(
                _Record(
                    r.id,
                    r.collection_id,
                    r.rel,
                    r.kind,
                    r.link_value,
                    identity.from_columns(r.st_dev, r.st_ino, r.st_birth),
                )
            )
        return out

    def _builtin(self, kind: str) -> Collection | None:
        """The built-in collection of ``kind`` (None before migration 0017: never
        expected, then simply not published)."""
        try:
            return self.collections.builtin(kind)
        except NotFound:
            return None

    def _state(self, rec: _Record) -> str:
        """What is at ``rec.rel`` now: ``"match"`` (exactly the entry the publisher
        created), ``"gone"`` (nothing there, or something else: forget the record) or
        ``"moved"`` (same kind and, for a link, the same readlink value, but a new
        dev/ino: Drive may have re-enumerated it; neither forgotten nor touched).
        Only dev/ino decide: a birth that differs (Drive re-writes new items) is still
        ``"match"`` and the stored birth is refreshed (``_refresh_birth``).
        Any OSError other than "not there" propagates: unknown, never "gone"."""
        try:
            p = self.paths.abs(rec.rel)
        except (OutsideArchiveError, ValueError):
            return "gone"
        try:
            st = os.lstat(p)
            is_link = stat.S_ISLNK(st.st_mode)
            value = readlink(p) if rec.kind == "link" and is_link else None
        except (FileNotFoundError, NotADirectoryError):
            return "gone"
        same = (
            (is_link and value == rec.link_value)
            if rec.kind == "link"
            else (not is_link and stat.S_ISDIR(st.st_mode))
        )
        if not same:
            return "gone"
        now = identity.of_stat(st, path=p)
        if not identity.same_object(rec.ident, now):
            return "moved"
        if not identity.same(rec.ident, now):
            self._refresh_birth(rec, now)
        return "match"

    def _refresh_birth(self, rec: _Record, now: Identity) -> None:
        """Store the birth the entry has now, so later checks (and the next sync's
        note) go by the refreshed value. Best effort: a failed write changes nothing
        (the entry still matches, and the next look tries again)."""
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    update(ongoing_entries)
                    .where(ongoing_entries.c.id == rec.id)
                    .values(st_birth=now.birth)
                )
        except Exception:  # noqa: BLE001
            log.warning("could not refresh the stored birth of %s", rec.rel, exc_info=True)

    def _matches(self, rec: _Record) -> bool:
        """The entry at ``rec.rel`` is still exactly the one the publisher created.
        Raises OSError when that cannot be told (see ``_state``)."""
        return self._state(rec) == "match"

    def _gone(self, rec: _Record) -> bool:
        """The record no longer matches (an entry that cannot be read is kept)."""
        try:
            return not self._matches(rec)
        except OSError:
            return False

    def _owned(self, rec: _Record) -> bool:
        """``_matches`` for planning: a moved identity skips the whole tree."""
        state = self._state(rec)
        if state == "moved":
            raise _LeftAlone(_IDENTITY.format(rel=rec.rel))
        return state == "match"

    def _target(self, link: Path) -> str | None:
        """The archive rel a link points at (read with readlink, never followed)."""
        try:
            raw = readlink(link)
        except OSError:
            return None
        full = os.path.normpath(os.path.join(link.parent, raw))
        try:
            return self.paths.rel(Path(full))
        except (OutsideArchiveError, OSError):
            return None

    def _same_target(self, link_rel: str, target: str) -> bool:
        found = self._target(self.paths.abs(link_rel))
        return found is not None and nfc(found) == nfc(target)

    def _is_top(self, rel: str, root: str | None = None) -> bool:
        """``rel`` is directly inside ``root`` (Ongoing by default)."""
        root = self.paths.ongoing if root is None else root
        return fold_parts(parent(rel)) == fold_parts(root)

    # --- planning ------------------------------------------------------------------------

    @staticmethod
    def _creation(rel: str, want: Desired, owner: int) -> list[tuple[Op, int]]:
        # exact: the path must be free at act time; never adopt something that
        # appeared there since planning, never let the planner pick another suffix.
        if want.kind == "link":
            return [(Op(OpKind.SYMLINK, want.target, rel, exact=True), owner)]
        return OngoingPublisher._subtree(rel, _Want.of(want, owner))

    @staticmethod
    def _subtree(rel: str, want: _Want) -> list[tuple[Op, int]]:
        """Create the folder ``rel`` and everything wanted in it: every folder first
        (parents before children), then every link, each with the collection it is
        recorded for. All exact."""
        dirs = [(Op(OpKind.MKDIR, None, rel, exact=True), want.owner)]
        links: list[tuple[Op, int]] = []

        def walk(base: str, node: _Want) -> None:
            links.extend(
                (Op(OpKind.SYMLINK, link.target, join(base, n), exact=True), link.owner)
                for n, link in node.links.items()
            )
            for name, sub in node.folders.items():
                dirs.append((Op(OpKind.MKDIR, None, join(base, name), exact=True), sub.owner))
                walk(join(base, name), sub)

        walk(rel, want)
        return [*dirs, *links]

    def _checked(self, g: _Share, pairs: list[tuple[Op, int]]) -> list[Op]:
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
        self, g: _Share, tops: list[_Record], inner: list[_Record]
    ) -> tuple[_Record | None, _Node | None, list[tuple[_Record, _Node | None]]]:
        """Split the records into owned/forgotten. Returns the root's owned top record
        (if any) and, for a folder, the tree of what the publisher owns inside it
        (every owned folder listed: its foreign names and why it could not be
        removed), plus the *strays*: other owned top-level entries of the tree's
        collections (a child's entry from before it was moved inside, a second
        entry), each with its tree, to be taken down."""
        top = None
        strays: list[tuple[_Record, _Node | None]] = []
        nodes: dict[tuple[str, ...], _Node] = {}
        for r in sorted(tops, key=lambda r: r.rel):
            if not self._owned(r):
                g.forget.append(r.id)
                if os.path.lexists(self.paths.abs(r.rel)):
                    g.note(r.collection_id, f"{r.rel}{_REPLACED}")
                continue
            g.owned.append(r)
            node = _Node(r, (r.collection_id,)) if r.kind == "folder" else None
            if node is not None:
                nodes[fold_parts(r.rel)] = node
            if top is None and r.collection_id == g.collection.id:
                top = r
            else:
                strays.append((r, node))
        tree = nodes.get(fold_parts(top.rel)) if top is not None else None
        # Parents first: an entry is owned only inside a folder that is owned itself,
        # so nothing is ever planned through a folder someone else put there.
        for r in sorted(inner, key=lambda r: _depth(r.rel)):
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
                    node.folders[name] = nodes[fold_parts(r.rel)] = _Node(r, owners)
                continue
            g.forget.append(r.id)
            # a replaced folder is worth a word (its whole subtree is affected);
            # a replaced link is just a foreign name from here on, as before
            if r.kind == "folder" and os.path.lexists(self.paths.abs(r.rel)):
                for cid in (*node.owners, r.collection_id):
                    g.note(cid, f"{r.rel}{_REPLACED}")
        for node in nodes.values():
            self._list(node)
        return top, tree, strays

    def _list(self, node: _Node) -> None:
        """What is in the owned folder ``node`` beside its owned entries, and whether
        that keeps it from being removed."""
        folder = self.paths.abs(node.rec.rel)
        ds_store = False
        for n in sorted(os.listdir(folder)):
            if n in node.links or n in node.folders:
                continue
            if n == primitives.DS_STORE and _kind(folder / n) == "file":
                ds_store = True
                continue
            node.foreign.append(n)
        if node.foreign:
            node.blocker = (
                f"{node.rec.rel} contains {_items(len(node.foreign))} not created by the"
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

    def _take_down_node(self, g: _Share, node: _Node, start: _Node | None = None) -> bool:
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

    def _take_down(self, g: _Share, top: _Record, tree: _Node | None) -> bool:
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

    def _reconcile(self, g: _Share, node: _Node, want: _Want) -> None:
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
                    and _is_variant(name, link.base)
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
                        ok = _is_variant(name, wanted_name)
                    else:
                        ok = _is_variant(name, sub.base) and fold_name(name) not in link_names
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
        children: _Children,
        tops: list[_Record],
        inner: list[_Record],
        orphans: list[_Record],
    ) -> _Share:
        """Removals and in-place creations for the tree under ``root``; ``fresh`` when
        a new top entry is needed. ``tops``: the tree's top-level records; ``inner``:
        every record located under one of them (whichever collection's); ``orphans``:
        the tree's records under no owned chain at all (forgotten quietly)."""
        g = _Share(root, _flatten(root, children))
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
        g: _Share,
        want: Desired | None,
        top: _Record | None,
        tree: _Node | None,
        strays: list[tuple[_Record, _Node | None]],
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
        in_place = _is_variant(PurePosixPath(top.rel).name, c.name)
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
                base = _wanted_name(member) if member else PurePosixPath(want.target).name
                links = {n: t for n, (t, _) in _link_names([(want.target, base)]).items()}
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
            self._reconcile(g, tree, _Want.of(want, c.id))

    def _located(self) -> tuple[list[_Record], dict[int, _Record | None]]:
        """Every record, and for each (by id) the top-level record its owned chain of
        folders hangs from (None: the chain breaks at a folder with no record)."""
        all_recs = [r for recs in self._records(self.paths.ongoing).values() for r in recs]
        by_rel = {fold_parts(r.rel): r for r in all_recs}
        at: dict[int, _Record | None] = {}

        def locate(r: _Record) -> _Record | None:
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
        self, tree: list[Collection], all_recs: list[_Record], at: dict[int, _Record | None]
    ) -> tuple[list[_Record], list[_Record], list[_Record]]:
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

    def _shares(self, collections: list[Collection], problems: list[str]) -> list[_Share]:
        """One share per tree (root collection), in tree order, then the ★ built-in's
        (its links at the top level, named after every tree's fresh entry). A tree
        whose entries cannot be read is skipped (reported in ``problems``). Raises
        ``ArchiveUnavailable`` when Ongoing is not a listable folder."""
        ongoing = self._ongoing_dir()
        all_recs, at = self._located()
        roots, children = _forest(collections)
        shares = []
        for root in roots:
            tree = _flatten(root, children)
            try:
                tops, inner, orphans = self._tree_records(tree, all_recs, at)
                shares.append(self._share(root, children, tops, inner, orphans))
            except OSError as e:  # unknown, not gone: keep its records, plan nothing
                log.warning("ongoing: cannot read the entry of %s: %s", root.name, e)
                problems.append(
                    f"{root.name}: its entry in {self.paths.ongoing} could not be read."
                )
                shares.append(_Share(root, tree, skipped=True))
            except _LeftAlone as e:
                problems.append(f"{root.name}: {e}")
                shares.append(_Share(root, tree, skipped=True, left_alone=str(e)))
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

    def _guarded(self, c: Collection, problems: list[str], build) -> _Share:
        """``build()`` a built-in's share; a record that cannot be read, or whose
        identity moved, leaves the whole share alone this sync (as for a tree)."""
        try:
            return build()
        except OSError as e:  # unknown, not gone: keep its records, plan nothing
            log.warning("ongoing: cannot read the entry of %s: %s", c.name, e)
            problems.append(f"{c.name}: its entry could not be read.")
            return _Share(c, [c], skipped=True)
        except _LeftAlone as e:
            problems.append(f"{c.name}: {e}")
            return _Share(c, [c], skipped=True, left_alone=str(e))

    def _star_share(self, c: Collection, all_recs: list[_Record], taken: set[str]) -> _Share:
        """The ★ built-in's share: one link per live member at the top of Ongoing,
        named after the member (``first_free`` among everything at the top: what is
        on disk, less what this plan vacates, plus the fresh names handed out to the
        trees in ``taken``). An owned link is kept while it points at a member and
        its name is a variant of that member's; a replaced one is foreign from then
        on (reported). Nothing but its own links is ever planned."""
        g = _Share(c, [c], root_rel=self.paths.ongoing)
        owned: list[_Record] = []
        for r in sorted((r for r in all_recs if r.collection_id == c.id), key=lambda r: r.rel):
            if r.kind != "link" or not self._is_top(r.rel):
                g.forget.append(r.id)  # never made by this share: forgotten quietly
                continue
            if not self._owned(r):
                g.forget.append(r.id)
                if os.path.lexists(self.paths.abs(r.rel)):
                    g.note(c.id, f"{r.rel}{_REPLACED}")
                continue
            g.owned.append(r)
            owned.append(r)
        wanted: list[_Link] = []
        for m in self._live(c, self.paths.ongoing):
            name = _wanted_name(m)
            if is_ds_store_name(name):
                g.note(c.id, f"{m.path} was not added because its name is reserved.")
                continue
            wanted.append(_Link(m.path, name, c.id))
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
                    and _is_variant(name, link.base)
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

    def _important_shares(self, problems: list[str]) -> list[_Share]:
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
            return [_Share(c, [c], skipped=True, left_alone=why)]
        try:
            self._root_dir(root)
        except ArchiveUnavailable as e:
            problems.append(str(e))
            return [_Share(c, [c], skipped=True, left_alone=str(e))]
        return [self._guarded(c, problems, lambda: self._important_share(c, root))]

    def _important_share(
        self, c: Collection, root: str, vacated: frozenset[str] = frozenset()
    ) -> _Share:
        """Reconcile the root folder itself: what the publisher owns in it (from the
        records under ``root``, parents first, each owned only inside an owned folder
        or the root) against the collection's members and groups, exactly as a
        collection's own folder in Ongoing. The root is a synthetic node that is never
        removed (no record, no identity, never a removal op); its foreign entries (the
        user's own shortcuts and files) only take names. ``vacated`` (the Important
        converter, folded top-level names): foreign entries of the root taken as
        already removed by the conversion's earlier ops in the same batch."""
        g = _Share(c, [c], root_rel=root)
        node = _Node(_Record(0, c.id, root, "folder", None, Identity(0, 0)), (c.id,))
        nodes: dict[tuple[str, ...], _Node] = {fold_parts(root): node}
        recs = [r for rs in self._records(root).values() for r in rs]
        for r in sorted(recs, key=lambda r: (_depth(r.rel), r.rel)):
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
                    above.folders[name] = nodes[fold_parts(r.rel)] = _Node(r, above.owners)
                continue
            g.forget.append(r.id)
            if (r.kind == "folder" or above is node) and os.path.lexists(self.paths.abs(r.rel)):
                g.note(c.id, f"{r.rel}{_REPLACED}")
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
        self._reconcile(g, node, _Want.of(desired, c.id))
        return g

    @staticmethod
    def _ordered(shares: list[_Share]) -> list[Op]:
        """All removals first, then all creations (each in tree order)."""
        live = [g for g in shares if not g.skipped]
        return [op for g in live for op in g.removals] + [op for g in live for op in g.creations]

    def _trees_of(
        self, collection_ids: list[int], changed: dict[int, Collection]
    ) -> list[Collection]:
        """Every collection of every tree one of ``collection_ids`` is in, in tree
        order, with ``changed`` (by id) in place of the stored ones."""
        cols = [changed.get(c.id, c) for c in self.collections.list(None)]
        roots, children = _forest(cols)
        wanted = set(collection_ids)
        out: list[Collection] = []
        for root in roots:
            tree = _flatten(root, children)
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
        roots, children = _forest(cols)
        by_id = {x.id: x for x in cols}
        root = c
        seen: set[int] = set()
        while root.parent_id in by_id and root.id not in seen:
            seen.add(root.id)
            root = by_id[root.parent_id]
        tree = _flatten(root, children)
        all_recs, at = self._located()
        try:
            g = self._share(root, children, *self._tree_records(tree, all_recs, at))
        except _LeftAlone as e:  # the sync leaves this tree alone: so does this
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
            entry = min(mine, key=lambda op: _depth(op.dst)).dst
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
        except _LeftAlone as e:
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
        except _LeftAlone as e:
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

    def _preview(self, shares: list[_Share], problems: list[str]) -> list[ResolvedOp]:
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

    def _root_shares(self, problems: list[str]) -> list[tuple[str, list[_Share]]]:
        """The shares of each root, Ongoing first (the trees and ★) then Important;
        a root that is not a listable folder is reported and left out (Ongoing) or
        left alone with its status saying so (Important)."""
        out: list[tuple[str, list[_Share]]] = []
        try:
            out.append((self.paths.ongoing, self._shares(self.collections.list(None), problems)))
        except ArchiveUnavailable as e:
            problems.append(str(e))
        out.append((self.paths.important, self._important_shares(problems)))
        for _, shares in out:
            self._hold(shares)
        return out

    def _hold(self, shares: list[_Share]) -> None:
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
        # starts with the entry's path (below one of the roots) and ends with _REPLACED
        roots = "|".join(re.escape(r) for r in (self.paths.ongoing, self.paths.important))
        found = re.finditer(
            rf"(?:^|(?<=\. ))((?:{roots})/(?:##\. |(?!\. )[^\n])+?){re.escape(_REPLACED)}",
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

    def _note_left_alone(self, shares: list[_Share]) -> None:
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

    def _record(self, shares: list[_Share], batch: BatchResult | None) -> None:
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
            _, kids = _forest(g.tree)
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
                    top = min(at_home or rels, key=_depth) if rels else None
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
