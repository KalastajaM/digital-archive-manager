"""Collections: named groups of files and folders. DB-only, nothing touches the archive.

Members are held by Drive ID (so they survive moves and renames) and are never copied. A
folder member means "everything in it", resolved when asked (``expand``, ``for_file``).
A collection's members can be arranged in groups, nested to any depth (a member is in
at most one group per collection; ``group_id`` None is "Ungrouped"). Removing a group
moves its child groups and members to its parent: it never removes a membership. The
collection and each group have a ``summary``, typed by the user for now.

Collections form a tree too: a collection can have a parent collection (``parent_id``,
None at the top), nested to any depth. Names stay unique across the whole tree. The
service keeps the tree whole: no cycles, no open collection under a closed one (closing
a parent with open children and reopening under a closed parent are refused), and no
orphans (there is no delete). ``list`` returns the tree depth-first, A-Z per level; each
collection carries its ``path`` (the names from the root).

Two collections are built in (``kind``, migration 0017): "Ongoing" (``starred``, the
★ mark) and "Important" (``important``, the ! mark; ``dam.collections.marks``). They
always exist and keep their names: they cannot be renamed, closed, reopened, moved,
given children or a parent, or have their publishing changed (there is no delete for
any collection), and their names are reserved (folded) for them. ★ Ongoing has no
groups; Important may. ``list`` and ``for_file`` leave them out unless asked
(``include_builtin``), as do the pickers that use them.

Publishing (the Ongoing links) is a separate step: the mutations here only change the
DB, then call the optional ``on_change`` callback (``App`` wires it to a sync of every
registered publisher) once their write transaction has committed.
"""

# Annotations stay strings: the ``list`` method would otherwise shadow ``list[...]``
# in the annotations after it on Python 3.13.
from __future__ import annotations

import logging
import threading
import time
import unicodedata
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import NamedTuple

from sqlalchemy import Connection, Engine, and_, delete, func, insert, literal, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from dam.collections.publishers import PublisherRegistry
from dam.config import SpecialFolders
from dam.core.paths import nfc
from dam.db.engine import write_tx
from dam.db.tables import (
    collection_groups,
    collection_members,
    collections,
    files,
    member_link_names,
)
from dam.index.repo import FileRecord, FileRepo
from dam.ops.guards import is_ds_store_name
from dam.services.errors import Conflict, InvalidRequest, NotFound

log = logging.getLogger(__name__)

NAME_MAX = 120
STATES = ("open", "closed")
# the built-in collections: kind -> name
BUILTINS = {"starred": "Ongoing", "important": "Important"}
SUMMARY_MAX = 4000


class _Keep:
    """``update_group(parent_id=KEEP)``: leave the parent as it is (None is the top)."""

    def __repr__(self) -> str:
        return "KEEP"


KEEP = _Keep()


@dataclass
class Member:
    drive_id: str
    # None when there is no usable row (unknown, or parked: its path is a tombstone)
    path: str | None
    is_dir: bool
    # the row is missing, parked, or absent
    missing: bool
    # at or under the quarantine folder (##. To Delete): not live content
    quarantined: bool = False
    # its group in this collection; None: ungrouped
    group_id: int | None = None
    # the name its published link keeps (a converted shortcut's own name); None: the
    # file's own name
    link_name: str | None = None
    # a symbolic link (Trash moves the link, never its target)
    is_link: bool = False


@dataclass
class Group:
    id: int
    # None: at the top of the collection
    parent_id: int | None
    name: str
    # order among its siblings: 0, 1, ...
    position: int
    summary: str = ""
    collection_id: int = 0


@dataclass
class Collection:
    id: int
    name: str
    state: str
    created: float
    closed_at: float | None
    publish: dict[str, bool]
    ongoing_rel: str | None
    members: list[Member] = field(default_factory=list)
    # "not managed: <reason>" when the publisher could not finish (e.g. a user file in
    # the collection's Ongoing folder kept it from being removed); None otherwise
    ongoing_status: str | None = None
    summary: str = ""
    # every group of the collection, flat: top level first, then by parent id; siblings
    # by position
    groups: list[Group] = field(default_factory=list)
    # the parent collection; None: at the top
    parent_id: int | None = None
    # the names from the root down to this collection (its own name last)
    path: list[str] = field(default_factory=list)
    # "starred" | "important" for the two built-in collections; None otherwise
    kind: str | None = None
    # the owner's order among the collections with the same parent (0, 1, ...)
    position: int = 0


def _fold(name: str) -> str:
    return nfc(name).casefold()


# folded reserved name -> kind
_RESERVED = {nfc(n).casefold(): k for k, n in BUILTINS.items()}
# how the UI names each mark
MARK_LABELS = {"starred": "★ Starred", "important": "! Important"}


def check_name(name: object, what: str = "collection") -> str:
    """Trim and validate. The name is also a folder name in ``##. Ongoing`` (for a
    group: a subfolder there). ``what`` names the thing in the messages."""
    if not isinstance(name, str):
        raise InvalidRequest(f"A {what} needs a name")
    name = nfc(name.strip())
    if not name:
        raise InvalidRequest(f"A {what} needs a name")
    if len(name) > NAME_MAX:
        raise InvalidRequest(f"A {what} name is at most {NAME_MAX} characters")
    if "/" in name:
        raise InvalidRequest(f"A {what} name must not contain '/'")
    if "\\" in name:
        raise InvalidRequest(f"A {what} name must not contain '\\'")
    if any(unicodedata.category(c) in ("Cc", "Cf") for c in name):  # NUL, bidi, format
        raise InvalidRequest(f"A {what} name must not contain control characters")
    if name.endswith(".") or name[-1].isspace():
        raise InvalidRequest(f"A {what} name must not end with '.' or a space")
    if name.startswith("."):
        raise InvalidRequest(f"A {what} name must not start with '.'")
    return name


def check_link_name(name: object) -> str:
    """A member's ``link_name``: a file name a link in a publish root may have (no
    separator, no control characters, not a reserved name, at most ``NAME_MAX``)."""
    if not isinstance(name, str) or not name or name in (".", ".."):
        raise InvalidRequest("A link name must be a file name")
    name = nfc(name)
    if len(name) > NAME_MAX:
        raise InvalidRequest(f"A link name is at most {NAME_MAX} characters")
    if "/" in name or "\\" in name:
        raise InvalidRequest("A link name must not contain '/' or '\\'")
    if any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") for c in name):
        # NUL, bidi and format characters, line and paragraph separators
        raise InvalidRequest("A link name must not contain control characters")
    if is_ds_store_name(name):
        raise InvalidRequest(f"{name!r} is a reserved name")
    return name


class RemovedRows(NamedTuple):
    """What ``remove_created_by`` deleted."""

    members: int
    groups: int

    @property
    def total(self) -> int:
        return self.members + self.groups


def check_collection_name(name: object) -> str:
    """``check_name`` for an ordinary collection's name, plus the reserved names: the
    built-ins' names (folded) are refused, pointing at their mark. The one validator
    for every place a collection is named (create, rename and its preview, filing
    from the inbox and its preview, Convert Ongoing)."""
    name = check_name(name)
    kind = _RESERVED.get(_fold(name))
    if kind is not None:
        raise InvalidRequest(
            f"{BUILTINS[kind]!r} is built in: use the {MARK_LABELS[kind]} mark instead"
        )
    return name


def check_summary(text: object) -> str:
    """Strip and validate a summary (``""`` means none), as ``check_note`` does a note."""
    if not isinstance(text, str):
        raise InvalidRequest("A summary is text")
    text = text.strip()
    if len(text) > SUMMARY_MAX:
        raise InvalidRequest(f"A summary is at most {SUMMARY_MAX} characters")
    return text


def _group(row) -> Group:
    return Group(
        id=row.id,
        parent_id=row.parent_id,
        name=row.name,
        position=row.position,
        summary=row.summary,
        collection_id=row.collection_id,
    )


def _parent_is(parent_id: int | None):
    col = collection_groups.c.parent_id
    return col.is_(None) if parent_id is None else col == parent_id


def _drive_ids(drive_ids: list[str]) -> list[str]:
    for drive_id in drive_ids:
        if not isinstance(drive_id, str) or not drive_id:
            raise InvalidRequest("A member is given by its drive id")
    return list(dict.fromkeys(drive_ids))


def _under(path_nfc: str, folder_nfc: str) -> bool:
    """``path_nfc`` is ``folder_nfc`` or lies below it (component boundary)."""
    return path_nfc == folder_nfc or path_nfc.startswith(folder_nfc + "/")


def _usable(row) -> bool:
    return row is not None and not row.missing and row.parked_at is None


@dataclass
class _Node:
    name: str
    name_fold: str
    parent_id: int | None
    state: str
    position: int = 0
    kind: str | None = None

    def sort_key(self, cid: int) -> tuple[int, int, str, int]:
        """Among siblings: the built-ins first, then the owner's order, then A-Z."""
        return (0 if self.kind else 1, self.position, self.name_fold, cid)


CLOSE_CHILDREN_FIRST = "Close or move its collections first"


def _tree(conn: Connection) -> dict[int, _Node]:
    """Every collection's place in the tree, by id (one small query)."""
    return {
        r.id: _Node(r.name, r.name_fold, r.parent_id, r.state, r.position, r.kind)
        for r in conn.execute(
            select(
                collections.c.id,
                collections.c.name,
                collections.c.name_fold,
                collections.c.parent_id,
                collections.c.state,
                collections.c.position,
                collections.c.kind,
            )
        ).all()
    }


def _path(tree: dict[int, _Node], collection_id: int) -> list[str]:
    """The names from the root down to ``collection_id``. A broken link (an unknown
    parent, or a cycle written outside the service) ends the walk: never a hang."""
    names: list[str] = []
    seen: set[int] = set()
    cid: int | None = collection_id
    while cid is not None and cid in tree and cid not in seen:
        seen.add(cid)
        names.append(tree[cid].name)
        cid = tree[cid].parent_id
    return names[::-1]


def _subtree(tree: dict[int, _Node], root: int) -> list[int]:
    """``root`` and every collection below it, by the ``parent_id`` tree (a cycle in
    bad data ends the walk instead of looping)."""
    children: dict[int, list[int]] = {}
    for cid, node in tree.items():
        if node.parent_id is not None:
            children.setdefault(node.parent_id, []).append(cid)
    out: list[int] = []
    todo = [root]
    seen: set[int] = set()
    while todo:
        cid = todo.pop()
        if cid in seen:
            continue
        seen.add(cid)
        out.append(cid)
        todo.extend(children.get(cid, []))
    return out


def _tree_order(tree: dict[int, _Node]) -> list[int]:
    """Every id, depth-first, siblings in the owner's order (built-ins first; then
    ``position``, folded name, id). A collection whose
    parent is unknown, or that sits in a cycle, is placed at the top so none is lost."""
    children: dict[int | None, list[int]] = {}
    for cid, node in tree.items():
        parent = node.parent_id if node.parent_id in tree else None
        children.setdefault(parent, []).append(cid)
    for ids in children.values():
        ids.sort(key=lambda i: tree[i].sort_key(i))
    order: list[int] = []
    seen: set[int] = set()

    def walk(parent: int | None) -> None:
        for cid in children.get(parent, []):
            if cid not in seen:
                seen.add(cid)
                order.append(cid)
                walk(cid)

    walk(None)
    for cid in sorted(set(tree) - seen, key=lambda i: tree[i].sort_key(i)):
        if cid not in seen:  # in a cycle: start a walk from it
            seen.add(cid)
            order.append(cid)
            walk(cid)
    return order


class CollectionService:
    def __init__(
        self,
        engine: Engine,
        repo: FileRepo,
        publishers: PublisherRegistry,
        special_folders: SpecialFolders,
        on_change: Callable[..., object] | None = None,
    ) -> None:
        self.engine = engine
        self.repo = repo
        self.publishers = publishers
        self._quarantine = nfc(special_folders.quarantine)
        # Called after every change that can alter what is published (create,
        # get_or_create when it creates, set_name, add/remove members,
        # remove_created_by, close, reopen, set_parent, set_publish, every group and
        # summary change), in the caller's thread, after the write has committed
        # (never inside a write_tx).
        self.on_change = on_change
        # Held while members are added to the Important built-in (add_members,
        # set_member_group, set_group_path with that target; ``MarkService.
        # mark_important``) and by the quarantine for its whole batch
        # (``BrowseService``), so a file marked Important while a quarantine runs is
        # never moved by it. Adds to every other collection (★ included) never take
        # it. Lock order: sync_lock -> important_lock -> INDEX_LOCK; on_change runs
        # after it is released.
        self.important_lock = threading.RLock()
        self._important_id: int | None = None

    def _changed(self, label: str | None = None) -> object:
        """Run ``on_change`` and return its result; a failure is logged, never raised
        (the change is saved), and returns None. ``label`` (what the user did) is
        passed on only when given."""
        if self.on_change is None:
            return None
        try:
            return self.on_change(label=label) if label else self.on_change()
        except Exception:
            log.exception("collection change callback failed")
            return None

    def add_lock(self, collection_id: int):
        """The lock every add to ``collection_id`` takes (``important_lock`` for the
        Important built-in, re-entrant; a no-op context otherwise), for a caller that
        must read the members and add under one lock (the converters' ``_save``)."""
        return self._add_lock(collection_id)

    def _add_lock(self, collection_id: int):
        """``important_lock`` when ``collection_id`` is the Important built-in (its id
        never changes: read once), else a no-op context."""
        if self._important_id is None:
            with self.engine.connect() as conn:
                self._important_id = conn.execute(
                    select(collections.c.id).where(collections.c.kind == "important")
                ).scalar()
        return self.important_lock if collection_id == self._important_id else nullcontext()

    def _quarantined(self, row) -> bool:
        return row.path_nfc is not None and _under(row.path_nfc, self._quarantine)

    # --- reading -----------------------------------------------------------------

    def _load(
        self, conn: Connection, rows, tree: dict[int, _Node] | None = None
    ) -> list[Collection]:
        """``tree``: the collections' places (``_tree``), when the caller read it."""
        rows = list(rows)
        if not rows:
            return []
        if tree is None:
            tree = _tree(conn)
        ids = [r.id for r in rows]
        member_rows = conn.execute(
            select(
                collection_members.c.collection_id,
                collection_members.c.drive_id,
                files.c.path,
                files.c.path_nfc,
                files.c.is_dir,
                files.c.is_link,
                files.c.missing,
                files.c.parked_at,
                files.c.drive_id.label("file_id"),
                collection_members.c.group_id,
                collection_members.c.link_name,
            )
            .select_from(
                collection_members.outerjoin(
                    files, files.c.drive_id == collection_members.c.drive_id
                )
            )
            .where(collection_members.c.collection_id.in_(ids))
            .order_by(collection_members.c.added, collection_members.c.drive_id)
        ).all()
        by_collection: dict[int, list[Member]] = {i: [] for i in ids}
        for m in member_rows:
            has_row = m.file_id is not None
            usable = has_row and not m.missing and m.parked_at is None
            by_collection[m.collection_id].append(
                Member(
                    drive_id=m.drive_id,
                    path=m.path if has_row and m.parked_at is None else None,
                    is_dir=bool(m.is_dir),
                    missing=not usable,
                    quarantined=usable and self._quarantined(m),
                    group_id=m.group_id,
                    link_name=m.link_name,
                    is_link=bool(m.is_link),
                )
            )
        groups: dict[int, list[Group]] = {i: [] for i in ids}
        for g in conn.execute(
            select(collection_groups)
            .where(collection_groups.c.collection_id.in_(ids))
            # NULL (top level) sorts first in SQLite
            .order_by(
                collection_groups.c.parent_id,
                collection_groups.c.position,
                collection_groups.c.id,
            )
        ).all():
            groups[g.collection_id].append(_group(g))
        return [
            Collection(
                id=r.id,
                name=r.name,
                state=r.state,
                created=r.created,
                closed_at=r.closed_at,
                publish=dict(r.publish or {}),
                ongoing_rel=r.ongoing_rel,
                members=by_collection[r.id],
                ongoing_status=r.ongoing_status,
                summary=r.summary,
                groups=groups[r.id],
                parent_id=r.parent_id,
                path=_path(tree, r.id),
                kind=r.kind,
                position=r.position,
            )
            for r in rows
        ]

    def get(self, collection_id: int) -> Collection:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(collections).where(collections.c.id == collection_id)
            ).one_or_none()
            if row is None:
                raise NotFound(f"No collection {collection_id}")
            return self._load(conn, [row])[0]

    def by_name(self, name: str) -> Collection | None:
        fold = _fold(name.strip()) if isinstance(name, str) else ""
        with self.engine.connect() as conn:
            row = conn.execute(
                select(collections).where(collections.c.name_fold == fold)
            ).one_or_none()
            return self._load(conn, [row])[0] if row else None

    def builtin(self, kind: str) -> Collection:
        """The built-in collection of ``kind`` (``starred`` or ``important``)."""
        if kind not in BUILTINS:
            raise InvalidRequest(f"kind must be one of {', '.join(BUILTINS)}")
        with self.engine.connect() as conn:
            row = conn.execute(select(collections).where(collections.c.kind == kind)).one_or_none()
            if row is None:  # the migration creates both; never expected
                raise NotFound(f"No built-in collection {kind!r}")
            return self._load(conn, [row])[0]

    def list(self, state: str | None = "open", include_builtin: bool = False) -> list[Collection]:
        """Collections in ``state`` (``"open"`` by default; ``None`` for all) in tree
        order: depth-first, the owner's order per level (then A-Z). The order (and each
        ``path``) is that of the whole tree, so a closed child of an open parent keeps its
        place and full path in the closed list. The built-in collections only with
        ``include_builtin``."""
        if state is not None and state not in STATES:
            raise InvalidRequest(f"state must be one of {', '.join(STATES)}")
        with self.engine.connect() as conn:
            tree = _tree(conn)
            rank = {cid: i for i, cid in enumerate(_tree_order(tree))}
            query = select(collections)
            if state is not None:
                query = query.where(collections.c.state == state)
            if not include_builtin:
                query = query.where(collections.c.kind.is_(None))
            rows = sorted(conn.execute(query).all(), key=lambda r: rank.get(r.id, len(rank)))
            return self._load(conn, rows, tree)

    # --- writing -----------------------------------------------------------------

    @staticmethod
    def _name_taken(conn: Connection, name: str, exclude_id: int | None = None) -> bool:
        query = select(collections.c.id).where(collections.c.name_fold == _fold(name))
        if exclude_id is not None:
            query = query.where(collections.c.id != exclude_id)
        return conn.execute(query).first() is not None

    @staticmethod
    def _require(conn: Connection, collection_id: int) -> None:
        if (
            conn.execute(select(collections.c.id).where(collections.c.id == collection_id)).first()
            is None
        ):
            raise NotFound(f"No collection {collection_id}")

    @staticmethod
    def _kind(conn: Connection, collection_id: int) -> str | None:
        """The collection's ``kind`` (None: an ordinary one); NotFound if unknown."""
        row = conn.execute(
            select(collections.c.kind).where(collections.c.id == collection_id)
        ).one_or_none()
        if row is None:
            raise NotFound(f"No collection {collection_id}")
        return row.kind

    def _ordinary(self, conn: Connection, collection_id: int, what: str) -> None:
        """Refuse ``what`` (e.g. "renamed") for a built-in collection; NotFound if
        unknown."""
        kind = self._kind(conn, collection_id)
        if kind is not None:
            raise InvalidRequest(f"{BUILTINS[kind]!r} is built in: it cannot be {what}")

    def check_ordinary(self, collection_id: int, what: str) -> None:
        """``InvalidRequest`` when the collection is built in (``what``: "renamed",
        "reopened", ...), ``NotFound`` when unknown: for the previews, so they refuse
        what their apply refuses."""
        with self.engine.connect() as conn:
            self._ordinary(conn, collection_id, what)

    @staticmethod
    def _check_parent(conn: Connection, parent_id: int) -> None:
        """``parent_id`` exists (else NotFound), is an ordinary collection (the
        built-ins have no children) and is open (else Conflict)."""
        row = conn.execute(
            select(collections.c.name, collections.c.state, collections.c.kind).where(
                collections.c.id == parent_id
            )
        ).one_or_none()
        if row is None:
            raise NotFound(f"No collection {parent_id}")
        if row.kind is not None:
            raise InvalidRequest(f"{row.name!r} is built in: it cannot hold collections")
        if row.state == "closed":
            raise Conflict(f"{row.name!r} is closed; reopen it first")

    def _insert(self, conn: Connection, name: str, parent_id: int | None = None) -> int:
        """``name``: checked by ``check_collection_name``."""
        if self._name_taken(conn, name):
            raise InvalidRequest(f"A collection named {name!r} already exists")
        if parent_id is not None:
            self._check_parent(conn, parent_id)
        result = conn.execute(
            insert(collections).values(
                name=name,
                name_fold=_fold(name),
                created=time.time(),
                publish={"ongoing": True},
                parent_id=parent_id,
                position=self._next_position(conn, parent_id),
            )
        )
        return result.inserted_primary_key[0]

    @staticmethod
    def _next_position(conn: Connection, parent_id: int | None) -> int:
        """The place after the last ordinary collection inside ``parent_id``: a new
        collection (or one moved in) goes at the end of its siblings."""
        parent = (
            collections.c.parent_id.is_(None)
            if parent_id is None
            else collections.c.parent_id == parent_id
        )
        top = conn.execute(
            select(func.max(collections.c.position)).where(parent, collections.c.kind.is_(None))
        ).scalar()
        return 0 if top is None else top + 1

    def create(self, name: str, parent_id: int | None = None, *, notify: bool = True) -> Collection:
        """A new open collection, inside ``parent_id`` (None: at the top), which must
        be open. ``notify=False``: skip ``on_change`` (see ``get_or_create``)."""
        name = check_collection_name(name)
        with write_tx(self.engine) as conn:
            new_id = self._insert(conn, name, parent_id)
        if notify:
            self._changed()
        return self.get(new_id)

    @staticmethod
    def _check_no_cycle(tree: dict[int, _Node], collection_id: int, parent_id: int) -> None:
        """Refuse ``parent_id`` being the collection or anything below it."""
        ancestor: int | None = parent_id
        seen: set[int] = set()
        while ancestor is not None and ancestor not in seen:
            if ancestor == collection_id:
                raise InvalidRequest("A collection cannot go inside itself")
            seen.add(ancestor)
            ancestor = tree[ancestor].parent_id if ancestor in tree else None

    def set_parent(
        self, collection_id: int, parent_id: int | None, *, notify: bool = True
    ) -> Collection:
        """Move the collection (with everything under it) inside ``parent_id`` (None:
        to the top). Refuses a cycle (into itself or one of its descendants) and a
        closed parent. DB only; the Ongoing publisher follows on its next sync. The
        same parent again changes nothing (no sync: the publisher would take the
        subtree down and recreate it for nothing)."""
        with write_tx(self.engine) as conn:
            self._ordinary(conn, collection_id, "moved")
            if parent_id is not None:
                self._check_parent(conn, parent_id)
                self._check_no_cycle(_tree(conn), collection_id, parent_id)
            current = conn.execute(
                select(collections.c.parent_id).where(collections.c.id == collection_id)
            ).scalar_one()
            moved = current != parent_id
            if moved:
                conn.execute(
                    update(collections)
                    .where(collections.c.id == collection_id)
                    .values(parent_id=parent_id, position=self._next_position(conn, parent_id))
                )
        if moved and notify:
            self._changed()
        return self.get(collection_id)

    def move(
        self,
        collection_id: int,
        *,
        before_id: int | None = None,
        after_id: int | None = None,
        notify: bool = True,
    ) -> Collection:
        """Put the collection just before ``before_id`` or just after ``after_id`` (give
        exactly one). The anchor is never a built-in one (they stay first). When the
        anchor has another parent the collection goes into that parent too (as
        ``set_parent``: a cycle or a closed parent is refused, and the Ongoing sync
        follows unless ``notify`` is off); within one parent only the order changes and
        there is no sync. The same place again changes nothing."""
        if (before_id is None) == (after_id is None):
            raise InvalidRequest("Give exactly one of before_id and after_id")
        anchor_id = before_id if before_id is not None else after_id
        reparented = False
        with write_tx(self.engine) as conn:
            self._ordinary(conn, collection_id, "moved")
            if anchor_id == collection_id:
                raise InvalidRequest("A collection cannot be put beside itself")
            kind = self._kind(conn, anchor_id)
            if kind is not None:
                raise InvalidRequest(f"{BUILTINS[kind]!r} is built in: it stays first")
            tree = _tree(conn)
            parent = tree[anchor_id].parent_id
            reparented = parent != tree[collection_id].parent_id
            if reparented and parent is not None:
                self._check_parent(conn, parent)
                self._check_no_cycle(tree, collection_id, parent)
            order = sorted(
                (i for i, n in tree.items() if n.parent_id == parent and n.kind is None),
                key=lambda i: tree[i].sort_key(i),
            )
            before = list(order)
            order = [i for i in order if i != collection_id]
            at = order.index(anchor_id) + (0 if before_id is not None else 1)
            order.insert(at, collection_id)
            if order != before or reparented:
                for pos, cid in enumerate(order):
                    values: dict[str, object] = {}
                    if tree[cid].position != pos or (cid == collection_id and reparented):
                        values["position"] = pos
                    if cid == collection_id and reparented:
                        values["parent_id"] = parent
                    if values:
                        conn.execute(
                            update(collections).where(collections.c.id == cid).values(**values)
                        )
        if reparented and notify:
            self._changed()
        return self.get(collection_id)

    def get_or_create(self, name: str, *, notify: bool = True) -> Collection:
        """``notify=False``: skip ``on_change`` (a caller that publishes the result
        itself, e.g. the Ongoing converter, which records the entries it created).
        Never a built-in collection: their names are refused (use the marks)."""
        name = check_collection_name(name)
        with write_tx(self.engine) as conn:
            row = conn.execute(
                select(collections.c.id).where(collections.c.name_fold == _fold(name))
            ).first()
            cid = row.id if row else self._insert(conn, name)
        if row is None and notify:
            self._changed()
        return self.get(cid)

    def set_name(self, collection_id: int, name: str, *, notify: bool = True) -> Collection:
        """Rename the collection (DB only: never a file rename, hence the name)."""
        # ``ongoing_rel`` is deliberately left as it is: it names the folder/link that
        # currently exists in ##. Ongoing. The Ongoing publisher moves it to the new name
        # on its next sync.
        name = check_collection_name(name)
        with write_tx(self.engine) as conn:
            self._ordinary(conn, collection_id, "renamed")
            if self._name_taken(conn, name, exclude_id=collection_id):
                raise InvalidRequest(f"A collection named {name!r} already exists")
            conn.execute(
                update(collections)
                .where(collections.c.id == collection_id)
                .values(name=name, name_fold=_fold(name))
            )
        if notify:
            self._changed()
        return self.get(collection_id)

    def add_members(
        self,
        collection_id: int,
        drive_ids: list[str],
        batch_id: str | None = None,
        *,
        link_names: dict[str, str] | None = None,
        notify: bool = True,
    ) -> Collection:
        """Add files/folders by drive id; one already a member is left alone (no-op,
        also for its ``link_names`` entry). ``link_names``: drive id -> the name the
        member's published link keeps (``check_link_name``), for new rows only.
        ``notify=False``: skip ``on_change`` (see ``get_or_create``)."""
        ids = _drive_ids(drive_ids)
        with self._add_lock(collection_id), write_tx(self.engine) as conn:
            self._require(conn, collection_id)
            self._add(conn, collection_id, ids, batch_id, link_names)
        if notify:
            self._changed()
        return self.get(collection_id)

    @staticmethod
    def _add(
        conn: Connection,
        collection_id: int,
        ids: list[str],
        batch_id: str | None,
        link_names: dict[str, str] | None = None,
    ) -> None:
        """Insert member rows (existing ones are left alone, their ``link_name`` too);
        every id must be a known, unparked file or folder. A new row without an
        explicit ``link_name`` gets back the last one the file had in this collection
        (``member_link_names``: a converted shortcut's name survives an unmark)."""
        names = {d: check_link_name(n) for d, n in (link_names or {}).items()}
        if ids:
            for d, n in conn.execute(
                select(member_link_names.c.drive_id, member_link_names.c.link_name).where(
                    member_link_names.c.collection_id == collection_id,
                    member_link_names.c.drive_id.in_(ids),
                )
            ).all():
                names.setdefault(d, n)
        known = (
            set(
                conn.execute(
                    select(files.c.drive_id).where(
                        files.c.drive_id.in_(ids), files.c.parked_at.is_(None)
                    )
                ).scalars()
            )
            if ids
            else set()
        )
        unknown = [d for d in ids if d not in known]
        if unknown:
            raise NotFound(f"No such file or folder: {unknown[0]}")
        now = time.time()
        for drive_id in ids:
            conn.execute(
                sqlite_insert(collection_members)
                .values(
                    collection_id=collection_id,
                    drive_id=drive_id,
                    added=now,
                    created_by_batch=batch_id,
                    link_name=names.get(drive_id),
                )
                .on_conflict_do_nothing()
            )

    @staticmethod
    def _remember_link_names(conn: Connection, where) -> None:
        """Before member rows matching ``where`` go: keep their ``link_name`` (the last
        one per collection and file) for a later add."""
        rows = conn.execute(
            select(
                collection_members.c.collection_id,
                collection_members.c.drive_id,
                collection_members.c.link_name,
            ).where(where, collection_members.c.link_name.is_not(None))
        ).all()
        for r in rows:
            conn.execute(
                sqlite_insert(member_link_names)
                .values(collection_id=r.collection_id, drive_id=r.drive_id, link_name=r.link_name)
                .on_conflict_do_update(
                    index_elements=["collection_id", "drive_id"], set_={"link_name": r.link_name}
                )
            )

    def remove_member(
        self, collection_id: int, drive_id: str, *, notify: bool = True
    ) -> Collection:
        return self.remove_members(collection_id, [drive_id], notify=notify)

    def remove_members(
        self, collection_id: int, drive_ids: list[str], *, notify: bool = True
    ) -> Collection:
        """Remove these members in one transaction; one that is not a member is left
        alone (no-op)."""
        ids = _drive_ids(drive_ids)
        with write_tx(self.engine) as conn:
            self._require(conn, collection_id)
            if ids:
                where = and_(
                    collection_members.c.collection_id == collection_id,
                    collection_members.c.drive_id.in_(ids),
                )
                self._remember_link_names(conn, where)
                conn.execute(delete(collection_members).where(where))
        if notify:
            self._changed()
        return self.get(collection_id)

    @staticmethod
    def _check_closable(conn: Connection, collection_id: int) -> None:
        if (
            conn.execute(
                select(collections.c.id).where(
                    collections.c.parent_id == collection_id, collections.c.state == "open"
                )
            ).first()
            is not None
        ):
            raise Conflict(CLOSE_CHILDREN_FIRST)

    def check_closable(self, collection_id: int) -> None:
        """``Conflict`` (as ``close`` raises) while the collection has open child
        collections; ``NotFound`` for an unknown one. For the close preview, so the
        user is told before a plan is shown."""
        with self.engine.connect() as conn:
            self._ordinary(conn, collection_id, "closed")
            self._check_closable(conn, collection_id)

    def close(self, collection_id: int, *, notify: bool = True) -> Collection:
        """DB only; the Ongoing links are removed by the publisher's next sync.
        ``notify=False``: skip ``on_change`` (the caller runs ``changed()`` itself to
        get the publisher's result, as the API does). Refused while the collection
        has open child collections."""
        with write_tx(self.engine) as conn:
            self._ordinary(conn, collection_id, "closed")
            self._check_closable(conn, collection_id)
            conn.execute(
                update(collections)
                .where(collections.c.id == collection_id, collections.c.state != "closed")
                .values(state="closed", closed_at=time.time())
            )
        if notify:
            self._changed()
        return self.get(collection_id)

    def reopen(self, collection_id: int, *, notify: bool = True) -> Collection:
        """Refused while the parent collection is closed (reopen or move it first)."""
        with write_tx(self.engine) as conn:
            self._ordinary(conn, collection_id, "reopened")
            row = conn.execute(
                select(collections.c.parent_id).where(collections.c.id == collection_id)
            ).one_or_none()
            if row is None:
                raise NotFound(f"No collection {collection_id}")
            if row.parent_id is not None:
                parent = conn.execute(
                    select(collections.c.name, collections.c.state).where(
                        collections.c.id == row.parent_id
                    )
                ).one()
                if parent.state == "closed":
                    raise Conflict(
                        f"Its parent collection {parent.name!r} is closed; "
                        "reopen it or move this collection first"
                    )
            conn.execute(
                update(collections)
                .where(collections.c.id == collection_id)
                .values(state="open", closed_at=None)
            )
        if notify:
            self._changed()
        return self.get(collection_id)

    def set_publish(
        self, collection_id: int, publisher: str, on: bool, *, notify: bool = True
    ) -> Collection:
        self.publishers.get(publisher)  # unknown id -> NotFound
        with write_tx(self.engine) as conn:
            self._ordinary(conn, collection_id, "published or unpublished")
            row = conn.execute(
                select(collections.c.publish).where(collections.c.id == collection_id)
            ).one_or_none()
            if row is None:
                raise NotFound(f"No collection {collection_id}")
            current = dict(row.publish or {})
            current[publisher] = bool(on)
            conn.execute(
                update(collections).where(collections.c.id == collection_id).values(publish=current)
            )
        if notify:
            self._changed()
        return self.get(collection_id)

    def changed(self, label: str | None = None) -> object:
        """Run ``on_change`` now (after changes made with ``notify=False``) and return
        its result (the Ongoing publisher's ``SyncResult`` in the App); None if it
        failed (logged) or there is no callback. ``label``: what the user did, the
        title of the batch the sync journals (without it, an automatic update)."""
        return self._changed(label)

    def remove_created_by(self, batch_id: str, *, notify: bool = True) -> RemovedRows:
        """Delete the member rows a batch created, then the groups it created that are
        still empty (no member, no subgroup; deepest first), so an undone Important
        conversion leaves no empty group folders behind; returns how many of each
        went. ``notify=False``: skip ``on_change`` (see ``get_or_create``).

        Collections are never deleted here, not even ones the batch created: deleting
        a whole collection (its notes, its other members) on an undo would surprise
        the user; an emptied collection is theirs to remove or reuse. A group the
        user made, or one of the batch's the user has put something in since, stays.
        """
        with write_tx(self.engine) as conn:
            self._remember_link_names(conn, collection_members.c.created_by_batch == batch_id)
            result = conn.execute(
                delete(collection_members).where(collection_members.c.created_by_batch == batch_id)
            )
            removed = RemovedRows(result.rowcount, self._remove_empty_groups_of(conn, batch_id))
        if removed.total and notify:
            self._changed()
        return removed

    def _remove_empty_groups_of(self, conn: Connection, batch_id: str) -> int:
        """Delete the groups ``batch_id`` created while they hold nothing (a round per
        depth, three queries each: a parent goes once its subgroups have); siblings
        are renumbered."""
        removed = 0
        while True:
            rows = conn.execute(
                select(collection_groups).where(collection_groups.c.created_by_batch == batch_id)
            ).all()
            if not rows:
                return removed
            ids = [r.id for r in rows]
            used = set(
                conn.execute(
                    select(collection_members.c.group_id)
                    .where(collection_members.c.group_id.in_(ids))
                    .distinct()
                ).scalars()
            )
            parents = set(
                conn.execute(
                    select(collection_groups.c.parent_id)
                    .where(collection_groups.c.parent_id.in_(ids))
                    .distinct()
                ).scalars()
            )
            empty = [r for r in rows if r.id not in used and r.id not in parents]
            if not empty:
                return removed
            ids = [r.id for r in empty]
            conn.execute(delete(collection_groups).where(collection_groups.c.id.in_(ids)))
            for r in empty:
                self._renumber(
                    conn, [s.id for s in self._siblings(conn, r.collection_id, r.parent_id)]
                )
            removed += len(ids)

    # --- summaries and groups ------------------------------------------------------

    def set_summary(self, collection_id: int, text: str, *, notify: bool = True) -> Collection:
        text = check_summary(text)
        with write_tx(self.engine) as conn:
            self._require(conn, collection_id)
            conn.execute(
                update(collections).where(collections.c.id == collection_id).values(summary=text)
            )
        if notify:
            self._changed()
        return self.get(collection_id)

    def group(self, group_id: int) -> Group:
        with self.engine.connect() as conn:
            return _group(self._group_row(conn, group_id))

    @staticmethod
    def _group_row(conn: Connection, group_id: int):
        row = conn.execute(
            select(collection_groups).where(collection_groups.c.id == group_id)
        ).one_or_none()
        if row is None:
            raise NotFound(f"No group {group_id}")
        return row

    def _check_group_of(self, conn: Connection, collection_id: int, group_id: int) -> None:
        """``group_id`` exists (else NotFound) and belongs to ``collection_id``."""
        if self._group_row(conn, group_id).collection_id != collection_id:
            raise InvalidRequest(f"Group {group_id} is in another collection")

    @staticmethod
    def _siblings(
        conn: Connection, collection_id: int, parent_id: int | None, exclude: int | None = None
    ) -> list:
        query = (
            select(collection_groups)
            .where(collection_groups.c.collection_id == collection_id, _parent_is(parent_id))
            .order_by(collection_groups.c.position, collection_groups.c.id)
        )
        if exclude is not None:
            query = query.where(collection_groups.c.id != exclude)
        return conn.execute(query).all()

    def _check_free(
        self,
        conn: Connection,
        collection_id: int,
        parent_id: int | None,
        name: str,
        exclude: int | None = None,
    ) -> None:
        """No sibling under ``parent_id`` has ``name`` (folded). Enforced here, not by
        an index: SQLite treats NULL parents as distinct."""
        fold = _fold(name)
        if any(
            r.name_fold == fold for r in self._siblings(conn, collection_id, parent_id, exclude)
        ):
            raise InvalidRequest(f"A group named {name!r} already exists there")

    @staticmethod
    def _renumber(conn: Connection, ids: list[int]) -> None:
        for position, gid in enumerate(ids):
            conn.execute(
                update(collection_groups)
                .where(collection_groups.c.id == gid, collection_groups.c.position != position)
                .values(position=position)
            )

    def create_group(
        self,
        collection_id: int,
        name: str,
        parent_id: int | None = None,
        *,
        notify: bool = True,
    ) -> Group:
        """A new group, last among its siblings (``parent_id`` None: at the top)."""
        name = check_name(name, "group")
        with write_tx(self.engine) as conn:
            self._groups_allowed(conn, collection_id)
            if parent_id is not None:
                self._check_group_of(conn, collection_id, parent_id)
            self._check_free(conn, collection_id, parent_id, name)
            new_id = self._insert_group(conn, collection_id, parent_id, name)
        if notify:
            self._changed()
        return self.group(new_id)

    def _groups_allowed(self, conn: Connection, collection_id: int) -> None:
        """NotFound for an unknown collection; ★ Ongoing has no groups."""
        if self._kind(conn, collection_id) == "starred":
            raise InvalidRequest(f"{BUILTINS['starred']!r} is built in: it has no groups")

    def _insert_group(
        self,
        conn: Connection,
        collection_id: int,
        parent_id: int | None,
        name: str,
        batch_id: str | None = None,
    ) -> int:
        position = len(self._siblings(conn, collection_id, parent_id))
        return conn.execute(
            insert(collection_groups).values(
                collection_id=collection_id,
                parent_id=parent_id,
                name=name,
                name_fold=_fold(name),
                position=position,
                created_by_batch=batch_id,
            )
        ).inserted_primary_key[0]

    def set_group_path(
        self,
        collection_id: int,
        drive_ids: list[str],
        path: list[str] | None,
        *,
        batch_id: str | None = None,
        link_names: dict[str, str] | None = None,
        notify: bool = True,
    ) -> Collection:
        """Put the files/folders in the group at ``path`` (group names from the top),
        creating the groups along it that do not exist yet (matched folded), adding
        the ones that are not members yet; all in one transaction. ``path`` None: new
        members are ungrouped and existing ones keep their group. ``batch_id`` (the
        Important converter): the memberships and groups made here are the batch's,
        and go again when it is undone (``remove_created_by``). ``link_names``: as
        for ``add_members`` (new rows only)."""
        ids = _drive_ids(drive_ids)
        names = [check_name(n, "group") for n in path] if path is not None else None
        with self._add_lock(collection_id), write_tx(self.engine) as conn:
            self._require(conn, collection_id)
            have = self._members_of(conn, collection_id, ids)
            self._add(conn, collection_id, [d for d in ids if d not in have], batch_id, link_names)
            if names:
                self._groups_allowed(conn, collection_id)
                group_id: int | None = None
                for name in names:
                    fold = _fold(name)
                    match = next(
                        (
                            r.id
                            for r in self._siblings(conn, collection_id, group_id)
                            if r.name_fold == fold
                        ),
                        None,
                    )
                    if match is None:
                        match = self._insert_group(conn, collection_id, group_id, name, batch_id)
                    group_id = match
                if ids:
                    conn.execute(
                        update(collection_members)
                        .where(
                            collection_members.c.collection_id == collection_id,
                            collection_members.c.drive_id.in_(ids),
                        )
                        .values(group_id=group_id)
                    )
        if notify:
            self._changed()
        return self.get(collection_id)

    @staticmethod
    def _members_of(conn: Connection, collection_id: int, ids: list[str]) -> set[str]:
        """Which of ``ids`` are members of the collection already."""
        if not ids:
            return set()
        return set(
            conn.execute(
                select(collection_members.c.drive_id).where(
                    collection_members.c.collection_id == collection_id,
                    collection_members.c.drive_id.in_(ids),
                )
            ).scalars()
        )

    def update_group(
        self,
        group_id: int,
        *,
        name: str | None = None,
        parent_id: int | None | _Keep = KEEP,
        position: int | None = None,
        summary: str | None = None,
        notify: bool = True,
    ) -> Group:
        """Change any of name, place and summary in one transaction (None/KEEP: leave
        as it is). A new ``parent_id`` without ``position`` puts the group last there;
        ``position`` is clamped to the end. A move into the group itself or one of its
        descendants is refused, as is a name a new sibling already has."""
        if name is not None:
            name = check_name(name, "group")
        if summary is not None:
            summary = check_summary(summary)
        if position is not None and (
            not isinstance(position, int) or isinstance(position, bool) or position < 0
        ):
            raise InvalidRequest("A group position is a whole number from 0")
        with write_tx(self.engine) as conn:
            row = self._group_row(conn, group_id)
            cid = row.collection_id
            target = row.parent_id if isinstance(parent_id, _Keep) else parent_id
            reparent = target != row.parent_id
            if reparent and target is not None:
                self._check_group_of(conn, cid, target)
                ancestor = target
                while ancestor is not None:
                    if ancestor == group_id:
                        raise InvalidRequest("A group cannot go inside itself")
                    ancestor = self._group_row(conn, ancestor).parent_id
            values: dict[str, object] = {}
            if name is not None or reparent:
                self._check_free(conn, cid, target, name or row.name, exclude=group_id)
            if name is not None:
                values.update(name=name, name_fold=_fold(name))
            if summary is not None:
                values["summary"] = summary
            if reparent:
                values["parent_id"] = target
            if values:
                conn.execute(
                    update(collection_groups)
                    .where(collection_groups.c.id == group_id)
                    .values(**values)
                )
            if reparent or position is not None:
                others = [r.id for r in self._siblings(conn, cid, target, exclude=group_id)]
                if position is None:
                    position = len(others)
                others.insert(min(position, len(others)), group_id)
                self._renumber(conn, others)
                if reparent:
                    self._renumber(conn, [r.id for r in self._siblings(conn, cid, row.parent_id)])
        if notify:
            self._changed()
        return self.group(group_id)

    def rename_group(self, group_id: int, name: str, *, notify: bool = True) -> Group:
        return self.update_group(group_id, name=name, notify=notify)

    def move_group(
        self, group_id: int, parent_id: int | None, position: int, *, notify: bool = True
    ) -> Group:
        """Put the group at ``position`` among the children of ``parent_id`` (None: the
        top); refuses a cycle."""
        return self.update_group(group_id, parent_id=parent_id, position=position, notify=notify)

    def set_group_summary(self, group_id: int, text: str, *, notify: bool = True) -> Group:
        return self.update_group(group_id, summary=text, notify=notify)

    def remove_group(self, group_id: int, *, notify: bool = True) -> None:
        """Remove the group; its child groups take its place among its siblings and its
        members move to its parent (None: ungrouped). Never removes a membership.
        Refused when a child's name clashes with a sibling it would get."""
        with write_tx(self.engine) as conn:
            row = self._group_row(conn, group_id)
            cid, parent = row.collection_id, row.parent_id
            children = self._siblings(conn, cid, group_id)
            taken = {r.name_fold for r in self._siblings(conn, cid, parent, exclude=group_id)}
            for child in children:
                if child.name_fold in taken:
                    raise InvalidRequest(
                        f"A group named {child.name!r} already exists where "
                        f"{row.name!r}'s groups would go; rename one first"
                    )
            conn.execute(
                update(collection_members)
                .where(
                    collection_members.c.collection_id == cid,
                    collection_members.c.group_id == group_id,
                )
                .values(group_id=parent)
            )
            conn.execute(
                update(collection_groups)
                .where(collection_groups.c.parent_id == group_id)
                .values(parent_id=parent)
            )
            # the children (now siblings) take the removed group's place, in their order
            child_ids = [c.id for c in children]
            order: list[int] = []
            for r in self._siblings(conn, cid, parent):
                if r.id == group_id:
                    order.extend(child_ids)
                elif r.id not in child_ids:
                    order.append(r.id)
            conn.execute(delete(collection_groups).where(collection_groups.c.id == group_id))
            self._renumber(conn, order)
        if notify:
            self._changed()

    def set_member_group(
        self,
        collection_id: int,
        drive_ids: list[str],
        group_id: int | None,
        *,
        notify: bool = True,
    ) -> Collection:
        """Put the files/folders in ``group_id`` (None: ungrouped), adding the ones that
        are not members yet. A member has one group per collection."""
        ids = _drive_ids(drive_ids)
        with self._add_lock(collection_id), write_tx(self.engine) as conn:
            self._require(conn, collection_id)
            if group_id is not None:
                self._check_group_of(conn, collection_id, group_id)
            have = self._members_of(conn, collection_id, ids)
            self._add(conn, collection_id, [d for d in ids if d not in have], None)
            if ids:
                conn.execute(
                    update(collection_members)
                    .where(
                        collection_members.c.collection_id == collection_id,
                        collection_members.c.drive_id.in_(ids),
                    )
                    .values(group_id=group_id)
                )
        if notify:
            self._changed()
        return self.get(collection_id)

    # --- resolving folder members --------------------------------------------------

    def member_paths(self, collection_id: int) -> list[tuple[str, bool, str]]:
        """``(path_nfc, is_dir, drive_id)`` of each direct member of the collection and
        of every collection below it (children, grandchildren, ...; open or closed)
        that is live and not quarantined, once each, unsorted: what the Browse
        collection filter shows. Raises ``NotFound`` for an unknown collection."""
        with self.engine.connect() as conn:
            self._require(conn, collection_id)
            subtree = _subtree(_tree(conn), collection_id)
            rows = conn.execute(
                select(
                    files.c.path_nfc,
                    files.c.is_dir,
                    files.c.drive_id,
                    files.c.missing,
                    files.c.parked_at,
                )
                .select_from(
                    collection_members.join(
                        files, files.c.drive_id == collection_members.c.drive_id
                    )
                )
                .where(collection_members.c.collection_id.in_(subtree))
            ).all()
        found = {
            r.drive_id: (r.path_nfc, bool(r.is_dir), r.drive_id)
            for r in rows
            if _usable(r) and not self._quarantined(r)
        }
        return list(found.values())

    def expand(self, collection_id: int) -> list[FileRecord]:
        """Every live file of the collection: file members, and the files at any depth
        under folder members (current paths). Missing, parked and quarantined (##. To
        Delete) files are left out, as is everything under a quarantined folder member.
        Deduplicated, sorted by path."""
        with self.engine.connect() as conn:
            self._require(conn, collection_id)
            members = conn.execute(
                select(files)
                .select_from(
                    collection_members.join(
                        files, files.c.drive_id == collection_members.c.drive_id
                    )
                )
                .where(collection_members.c.collection_id == collection_id)
            ).all()
            found: dict[str, object] = {}
            for m in members:
                if not _usable(m) or self._quarantined(m):
                    continue
                if not m.is_dir:
                    found[m.drive_id] = m
                    continue
                # component boundary: "<folder>/" prefix, so "Sauna 2" is not under "Sauna"
                prefix = m.path_nfc + "/"
                rows = conn.execute(
                    select(files).where(
                        func.substr(files.c.path_nfc, 1, len(prefix)) == prefix,
                        files.c.missing.is_not(True),
                        files.c.parked_at.is_(None),
                        files.c.is_dir.is_not(True),
                        files.c.is_link.is_not(True),
                    )
                ).all()
                for r in rows:
                    if not self._quarantined(r):
                        found[r.drive_id] = r
        return sorted(
            (self.repo.record_from_row(r) for r in found.values()), key=lambda rec: rec.path
        )

    def for_file(self, drive_id: str, include_builtin: bool = False) -> list[Collection]:
        """Collections holding the file directly, or through a folder member containing
        its current path. Open and closed both count; sorted by name. The built-in
        collections only with ``include_builtin`` (their marks show them)."""
        with self.engine.connect() as conn:
            ids = set(
                conn.execute(
                    select(collection_members.c.collection_id).where(
                        collection_members.c.drive_id == drive_id
                    )
                ).scalars()
            )
            me = conn.execute(select(files).where(files.c.drive_id == drive_id)).one_or_none()
            if _usable(me):
                folders = files.alias("folder")
                prefix_len = func.length(folders.c.path_nfc) + 1
                ids.update(
                    conn.execute(
                        select(collection_members.c.collection_id)
                        .select_from(
                            collection_members.join(
                                folders, folders.c.drive_id == collection_members.c.drive_id
                            )
                        )
                        .where(
                            and_(
                                folders.c.is_dir.is_(True),
                                folders.c.missing.is_not(True),
                                folders.c.parked_at.is_(None),
                                func.substr(literal(me.path_nfc), 1, prefix_len)
                                == folders.c.path_nfc + "/",
                            )
                        )
                    ).scalars()
                )
            if not ids:
                return []
            query = select(collections).where(collections.c.id.in_(ids))
            if not include_builtin:
                query = query.where(collections.c.kind.is_(None))
            tree = _tree(conn)
            rank = {cid: i for i, cid in enumerate(_tree_order(tree))}
            rows = sorted(conn.execute(query).all(), key=lambda r: rank.get(r.id, len(rank)))
            return self._load(conn, rows, tree)
