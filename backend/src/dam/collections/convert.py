"""One-time conversion of the current ``##. Ongoing`` into collections (design §6.2),
and the shared machinery of the ``##. Important`` converter (``convert_important``).

Each top-level entry of Ongoing that the app does not own becomes a collection:

- a **link** to a file or folder in the archive: the target becomes the member; the
  user's link is removed (UNLINK_SYMLINK) and the publisher creates its own entry
  (for a folder target: a direct link at the same name, pointing at the same folder);
- a **real folder**: each top-level child (file or subfolder, moved whole) is MOVEd
  into the chosen archive folder and becomes a member by Drive ID; links directly in
  it are not moved: their targets become members and the links are removed; then the
  emptied folder is removed (REMOVE_EMPTY_DIR) and the publisher creates the layout;
- a **real file**: MOVEd into the chosen archive folder, member of the collection.

**Star it** (stars, Task 3): instead of a collection, a link or a real file can become
a ★ member (the ``starred`` built-in): the user's link is removed and the publisher's
own link to the member takes its place at the top of Ongoing, under the shortcut's
own name (``Member.link_name``, kept on the membership row; the file's name when the
shortcut's cannot be a link name, with a note), or the file is moved to the chosen
archive folder and linked from there. A real folder is refused (convert it into a
collection); so is a file that is starred already (its link is there).

One ``apply`` is one journaled batch (origin ``"ui"``): the conversion's file ops, then
the publisher's creation ops for the collection's new layout (planned as if the
conversion had already run: ``OngoingPublisher.layout_after``, or
``star_layout_after`` for a ★). So each entry is undone on its own, and the undo puts
back exactly what was there (the batch's memberships go with it: ``created_by_batch``).
The user's link is never adopted: it is removed and the publisher's own link,
recorded by identity like every entry the publisher creates, takes its name. A
collection that already owns entries in Ongoing and would need some of them removed
first (a layout switch) gets only the conversion in the batch; the sync that follows
(origin ``"workflow"``) does the rest.

Members must be in the index (a scan has seen them); links pointing outside the
archive, broken links or links into Ongoing make the whole entry unconvertible (never
a partial conversion). When the emptied folder cannot be removed (a ``.DS_Store``
carrying a Drive id, another leftover such as ``Icon\\r``) the moves still happen, the
folder stays where it is (foreign to the publisher, which then uses ``<name>_2``) and
the result says why.

``apply`` re-plans from the disk as it is then; the executor re-checks every op. The
binding preview: ``apply`` runs only the exact plan ``preview`` showed (its
``fingerprint`` over the resolved ops, the members, the notes and the target).

``_Converter`` holds what both converters share: reading a root's entries, checking
links and index rows, the destination rules, the fingerprint and the apply skeleton
(the publisher's ``sync_lock`` held from planning until the created entries are
recorded). The subclasses decide what an entry's ops are and what is saved.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

from dam.collections.ongoing import OngoingPublisher
from dam.collections.service import Collection, Member, check_collection_name, check_link_name
from dam.core.fs import readlink
from dam.core.paths import ArchivePaths, OutsideArchiveError, nfc
from dam.index.scanner import is_ignored
from dam.ops import primitives
from dam.ops.guards import canonical, fold_parts, is_under, join
from dam.ops.model import BatchResult, GuardError, Op, OpKind, Plan, ResolvedOp
from dam.ops.planner import COLLISION_NOTE
from dam.services.errors import InvalidRequest, NotFound, StalePreview

if TYPE_CHECKING:
    from dam.collections.ongoing import Layout, SyncResult
    from dam.collections.service import CollectionService
    from dam.index.repo import FileRecord, FileRepo
    from dam.ops.executor import Executor

log = logging.getLogger(__name__)

ORIGIN = "ui"
NOT_REMOVED = "original folder could not be removed: "
CHANGED = "Something changed since the preview. Preview again."
EMPTY = "The folder is empty, so there is nothing to convert."
NOT_RECORDED = (
    "The new Ongoing entry could not be saved, so this conversion can no longer be undone."
)
RELATIVE = " is a relative link: after undo the link will be absolute"
ALREADY_MEMBER = " was a member already; left as it was (not the conversion's to undo)"
FOLDER_NOT_REMOVED = " could not be removed: "
STAR_FOLDER = " is a folder, so it cannot be starred. Convert it into a collection instead."


@dataclass
class EntryItem:
    """One top-level item inside a real folder entry. ``drive_id``: what Quick Look,
    Open and Show in Finder act on (a link's is its target's; None when it is not
    indexed, or a link to outside the archive). ``unreadable``: it could not even be
    looked at (an ``OSError``), so it has no drive id either."""

    name: str
    drive_id: str | None
    is_dir: bool
    is_link: bool = False
    unreadable: bool = False


@dataclass
class Entry:
    """A top-level entry of ``##. Ongoing`` (or of ``##. Important``).

    ``target_rel``: for a link, the archive path it points at (None when it points
    outside the archive). ``managed``: the publisher owns it (it belongs to a
    collection). ``contents``: the top-level names inside a real folder.
    ``problem``: why it cannot be converted (None when it can). ``drive_id``: the
    indexed record to look at, open or show the entry by (a link's target's),
    ``is_dir``: it is (or points at) a folder, and ``items``: ``contents`` with theirs."""

    rel: str
    kind: Literal["link", "folder", "file"]
    target_rel: str | None
    managed: bool
    suggested_name: str
    contents: list[str] = field(default_factory=list)
    problem: str | None = None
    collection_id: int | None = None  # the collection that owns it, when managed
    collection_name: str | None = None
    drive_id: str | None = None
    is_dir: bool = False  # a folder, or a link to one
    items: list[EntryItem] = field(default_factory=list)
    # real files (not links) at any depth: what must move to an archive folder (a
    # real file is 1, a link 0); a folder holding none needs no destination
    real_files: int = 0


@dataclass
class ConvertPlan:
    """What ``apply`` would do: the resolved ops (collision suffixes applied), the
    collection's new members (their paths after the conversion), and notes to show
    (renames to avoid collisions, what will not be linked, a folder left in place).
    ``groups``: per member, the Important group it goes into ("A/B"; "" for none,
    always for Ongoing)."""

    ops: list[ResolvedOp]
    members: list[str]
    notes: list[str] = field(default_factory=list)
    # the collection the conversion goes into: the resolved name (the name matches
    # case-insensitively), whether it exists already, and how many members it has
    collection: str = ""
    existing: bool = False
    existing_members: int = 0
    # stable hash of ops, members and notes: ``apply`` runs only this exact plan
    fingerprint: str = ""
    groups: list[str] = field(default_factory=list)
    # per member, the name its link keeps (a converted shortcut's own name; "" for
    # the file's own name)
    link_names: list[str] = field(default_factory=list)


@dataclass
class ConvertResult:
    """``collection_id`` is None only when a new collection was not created because
    nothing could be done. ``problems``: what did not go as planned. ``sync``: the
    publisher sync run afterwards (normally empty)."""

    batch: BatchResult
    collection_id: int | None
    problems: list[str] = field(default_factory=list)
    sync: SyncResult | None = None


@dataclass
class _Member:
    drive_id: str
    src: str  # where it is now
    is_dir: bool
    op: Op  # the op after which it is a member (its MOVE, or the UNLINK of its link)
    dst: str | None = None  # its path after the conversion (set once resolved)
    group: tuple[str, ...] = ()  # the Important group path it goes into (names)
    link_name: str | None = None  # the shortcut's own name, when not the file's


@dataclass
class _Built:
    entry: Entry
    name: str
    existing: Collection | None
    ops: list[Op]  # the conversion's own ops
    members: list[_Member]
    layout: Layout | None = None  # the publisher's part, when it is in the batch
    resolved: list[ResolvedOp] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    star: bool = False  # into the ★ built-in (Ongoing)
    groups: list[tuple[str, ...]] = field(default_factory=list)  # Important: every group
    # drive id -> the user's entry (link path) that made it a member (Important)
    origins: dict[str, str] = field(default_factory=dict)

    @property
    def all_ops(self) -> list[Op]:
        if self.layout is None:
            return list(self.ops)
        return [*self.ops, *self.layout.switches, *self.layout.creations]


def _same_op(op: Op, rop: ResolvedOp) -> bool:
    return op.kind is rop.kind and fold_parts(op.src) == fold_parts(rop.src)


class _Converter:
    """What the Ongoing and the Important converter share. ``root`` is the publish
    root whose top-level entries are converted; a link's target may not lie in any
    of ``_refused_roots`` (the targets there are the app's or the user's unconverted
    entries); a destination may not lie in any of ``_forbidden_destinations``."""

    def __init__(
        self,
        paths: ArchivePaths,
        repo: FileRepo,
        executor: Executor,
        collections: CollectionService,
        ongoing: OngoingPublisher,
    ) -> None:
        self.paths = paths
        self.repo = repo
        self.executor = executor
        self.collections = collections
        self.ongoing = ongoing
        # syncs the publishers after a conversion; ``App`` sets it to the fan-out over
        # every registered publisher (returns the Ongoing ``SyncResult``)
        self.sync_publishers: Callable[[], SyncResult | None] = ongoing.sync

    @property
    def root(self) -> str:
        raise NotImplementedError

    @property
    def _refused_roots(self) -> tuple[str, ...]:
        return (self.root,)

    @property
    def _forbidden_destinations(self) -> tuple[str, ...]:
        return (self.paths.ongoing, self.paths.quarantine, self.paths.inbox)

    def _root_dir(self) -> Path:
        return self.ongoing.root_dir(self.root)

    # --- reading ----------------------------------------------------------------------

    def entries(self) -> list[Entry]:
        """Every top-level entry of the root (Finder/Drive housekeeping files left
        out), by name. Raises ``ArchiveUnavailable`` when it cannot be listed."""
        folder = self._root_dir()
        owned = self.ongoing.owned_top(self.root)
        return [
            self._safe_entry(name, owned)
            for name in sorted(os.listdir(folder))
            if not is_ignored(name)
        ]

    def _safe_entry(self, name: str, owned: dict[str, int]) -> Entry:
        """``_entry``, or an entry carrying the problem when it cannot be read (one
        unreadable entry never fails the whole listing)."""
        try:
            return self._entry(name, owned)
        except OSError as e:
            rel = join(self.root, name)
            owner = owned.get(nfc(name).casefold())
            return Entry(
                rel,
                "file",
                None,
                owner is not None,
                _stem(name),
                [],
                f"could not read it: {e.strerror or e}",
                *self._owner(owner),
            )

    def unmanaged_count(self) -> int:
        """How many top-level entries look convertible, cheaply (for Today, on every
        request): not owned, and a link whose target is a usable member, a non-empty
        real folder, or an indexed real file. Top-level entries only: no deep link walk
        and no checks of a folder's children (``preview`` does those). An entry that
        cannot be read is not counted. Raises ``ArchiveUnavailable`` (or ``OSError``)
        when the root itself cannot be listed."""
        folder = self._root_dir()
        owned = self.ongoing.owned_top(self.root)
        count = 0
        for name in os.listdir(folder):
            if is_ignored(name) or nfc(name).casefold() in owned:
                continue
            p = folder / name
            try:
                st = os.lstat(p)
                if stat.S_ISLNK(st.st_mode):
                    ok = self._link(p)[2] is None
                elif stat.S_ISDIR(st.st_mode):
                    ok = any(not is_ignored(n) for n in os.listdir(p))
                else:
                    ok = self._indexed_problem(join(self.root, name)) is None
            except OSError:  # this entry cannot be read now: not counted, the rest are
                continue
            count += ok
        return count

    def _entry(self, name: str, owned: dict[str, int]) -> Entry:
        rel = join(self.root, name)
        p = self.paths.abs(rel)
        st = os.lstat(p)
        owner = owned.get(nfc(name).casefold())
        managed = owner is not None
        if stat.S_ISLNK(st.st_mode):
            target, is_dir, problem = self._link(p)
            stem = name if is_dir else _stem(name)
            entry = Entry(rel, "link", target, managed, stem, [], problem, *self._owner(owner))
            entry.drive_id = self._record_id(target)
            entry.is_dir = is_dir
            return entry
        if stat.S_ISDIR(st.st_mode):
            contents = sorted(n for n in os.listdir(p) if not is_ignored(n))
            problem = None
            try:
                children = self._folder_children(rel, contents)
            except OSError as e:  # e.g. a subfolder that cannot be listed: only this entry
                children = []
                where = rel
                try:
                    where = self.paths.rel(Path(e.filename)) if e.filename else rel
                except (OutsideArchiveError, TypeError):
                    pass
                problem = f"could not read {where}: {e.strerror or e}"
            for child in children:
                if problem is not None:
                    break
                problem = self._child_problem(child, rel)
            entry = Entry(
                rel, "folder", None, managed, name, contents, problem, *self._owner(owner)
            )
            entry.drive_id = self._record_id(rel)
            entry.is_dir = True
            entry.items = [self._item(rel, n) for n in contents]
            if problem is None:
                entry.real_files = len(self._walk(rel)[0])
            return entry
        problem = self._indexed_problem(rel)
        entry = Entry(rel, "file", None, managed, _stem(name), [], problem, *self._owner(owner))
        entry.drive_id = self._record_id(rel)
        entry.real_files = 1
        return entry

    def _folder_children(self, rel: str, contents: list[str]) -> list[str]:
        """The rels inside the real folder entry ``rel`` that must be convertible:
        its top-level children and the links deeper inside (they would move with
        their subfolder)."""
        return [*(join(rel, n) for n in contents), *self._deep_links(rel)]

    def _record_id(self, rel: str | None) -> str | None:
        """The drive id of ``rel``'s usable index row, if any."""
        rec = self._indexed(rel) if rel else None
        return rec.drive_id if rec else None

    def _item(self, folder: str, name: str) -> EntryItem:
        """An item of a real folder entry, with the record it opens as (never followed
        outside the archive: a link is read, and its target looked up in the index)."""
        child = join(folder, name)
        p = self.paths.abs(child)
        try:
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode):
                target, is_dir, _ = self._link(p)
                return EntryItem(name, self._record_id(target), is_dir, True)
            return EntryItem(name, self._record_id(child), stat.S_ISDIR(st.st_mode))
        except OSError:
            return EntryItem(name, None, False, unreadable=True)

    def _owner(self, collection_id: int | None) -> tuple[int | None, str | None]:
        if collection_id is None:
            return None, None
        try:
            return collection_id, self.collections.get(collection_id).name
        except NotFound:
            return None, None

    def _link(self, link: Path) -> tuple[str | None, bool, str | None]:
        """(target rel, target is a folder, problem) for a link; read, never followed."""
        raw = readlink(link)
        full = os.path.normpath(os.path.join(link.parent, raw))
        try:
            target = self.paths.rel(Path(full))
        except OutsideArchiveError:
            return None, False, f"it points outside the archive ({raw})"
        try:
            st = os.lstat(self.paths.abs(target)) if target else None
        except FileNotFoundError:
            return target, False, f"it is broken: {target} does not exist"
        except (OSError, OutsideArchiveError) as e:
            return target, False, f"its target cannot be read: {e}"
        if st is None:
            return target, True, "it points at the archive root"
        is_dir = stat.S_ISDIR(st.st_mode)
        if stat.S_ISLNK(st.st_mode):
            return target, False, f"it points at another link ({target})"
        for root in self._refused_roots:
            if is_under(target, root):
                return target, is_dir, f"it points into {root} ({target})"
        if is_under(target, self.paths.quarantine):
            # what CollectionService calls quarantined: never published, so never a member
            return target, is_dir, f"its target {target} is marked for deletion"
        return target, is_dir, self._indexed_problem(target)

    def _indexed(self, rel: str) -> FileRecord | None:
        """The index row of ``rel`` if it is usable as a member (as CollectionService
        counts it: not missing, not parked, not a link)."""
        rec = self.repo.by_path(rel)
        if rec is None or rec.missing or rec.parked_at is not None or rec.is_link:
            return None
        return rec

    def _indexed_problem(self, rel: str) -> str | None:
        rec = self.repo.by_path(rel)
        if rec is None:
            return f"{rel} is not in the index yet (scan first)"
        if rec.missing or rec.parked_at is not None:
            return f"{rel} is missing in the index (scan again)"
        if rec.is_link:
            return f"{rel} is a link in the index (scan again)"
        return None

    def _child_problem(self, rel: str, folder: str) -> str | None:
        p = self.paths.abs(rel)
        if p.is_symlink():
            _, _, problem = self._link(p)
            inner = PurePosixPath(rel).relative_to(PurePosixPath(folder)).as_posix()
            return None if problem is None else f"the link {inner}: {problem}"
        return self._indexed_problem(rel)

    def _deep_links(self, rel: str) -> list[str]:
        """Links anywhere below the top-level subfolders of the folder ``rel`` (they
        would move with their subfolder): never followed, sorted."""
        out: list[str] = []
        stack = [
            self.paths.abs(join(rel, n))
            for n in os.listdir(self.paths.abs(rel))
            if self.paths.abs(join(rel, n)).is_dir()
            and not self.paths.abs(join(rel, n)).is_symlink()
        ]
        while stack:
            with os.scandir(stack.pop()) as it:
                for e in it:
                    if e.is_symlink():
                        out.append(self.paths.rel(Path(e.path)))
                    elif e.is_dir(follow_symlinks=False):
                        stack.append(Path(e.path))
        return sorted(out)

    # --- planning helpers ---------------------------------------------------------------

    def _destination(self, destination: str | None) -> str:
        """Validate the archive folder the entry's real content moves to."""
        if not isinstance(destination, str) or not destination.strip().strip("/"):
            raise InvalidRequest("Choose the archive folder its contents should move to.")
        try:
            dest = canonical(destination.strip().strip("/"), self.paths)
        except GuardError as e:
            raise InvalidRequest(f"That is not a usable destination: {e}") from None
        for special in self._forbidden_destinations:
            if is_under(dest, special):
                raise InvalidRequest(f"The destination cannot be inside {special}.")
        parts = PurePosixPath(dest).parts
        for i in range(1, len(parts) + 1):
            sub = PurePosixPath(*parts[:i]).as_posix()
            p = self.paths.abs(sub)
            if not os.path.lexists(p):
                if i == 1:
                    raise InvalidRequest(
                        f"That would create a new top-level folder, {sub}. "
                        "Choose a folder that already exists."
                    )
                break
            if p.is_symlink() or not p.is_dir():
                raise InvalidRequest(f"{sub} is not a folder.")
        return dest

    def _top_name(self, rel: object) -> str:
        """The on-disk name of the entry ``rel`` names directly in the root."""
        bad = InvalidRequest(f"{rel} is not an item directly inside {self.root}.")
        if not isinstance(rel, str) or "\0" in rel:
            raise bad
        parts = rel.split("/")
        if parts and parts[-1] == "":
            parts = parts[:-1]  # a trailing slash
        root_parts = self.root.split("/")
        if len(parts) != len(root_parts) + 1 or fold_parts("/".join(parts[:-1])) != fold_parts(
            self.root
        ):
            raise bad
        name = parts[-1]
        if name in ("", ".", ".."):
            raise bad
        want = nfc(name).casefold()
        for n in os.listdir(self._root_dir()):
            if nfc(n).casefold() == want:
                return n
        raise NotFound(f"{rel} was not found.")

    def _top_entry(self, rel: str) -> Entry:
        """The convertible entry ``rel`` names (refused with its reason otherwise)."""
        name = self._top_name(rel)
        if is_ignored(name):
            raise InvalidRequest(f"{name} is a system file, so it is not converted.")
        try:
            entry = self._entry(name, self.ongoing.owned_top(self.root))
        except FileNotFoundError:
            raise NotFound(f"{rel} was not found.") from None
        if entry.managed:
            raise InvalidRequest(f"{entry.rel} is already a collection.")
        if entry.problem is not None:
            raise InvalidRequest(f"{entry.rel} cannot be converted: {entry.problem}")
        if entry.kind == "folder" and not entry.contents:
            raise InvalidRequest(f"{entry.rel}: {EMPTY}")
        return entry

    def _guarded_build(self, rel: str, build: Callable[[], _Built]) -> _Built:
        """``build()``; a read error (other than "not there") is a refusal."""
        try:
            return build()
        except FileNotFoundError:
            raise NotFound(f"{rel} was not found.") from None
        except OSError as e:
            raise InvalidRequest(
                f"{rel} cannot be converted, because it could not be read: {e}"
            ) from None

    def _link_member(self, built: _Built, link: str, group: tuple[str, ...] = ()) -> _Member:
        """UNLINK the user's link ``link``; its target becomes a member."""
        p = self.paths.abs(link)
        target, _, problem = self._link(p)
        rec = self._indexed(target) if problem is None else None
        if rec is None:  # the entry was checked; the index may have changed since
            raise InvalidRequest(
                f"{link} cannot be converted: {problem or 'the file it points to is gone'}"
            )
        if not os.path.isabs(readlink(p)):
            built.notes.append(link + RELATIVE)
        op = Op(OpKind.UNLINK_SYMLINK, link, None)
        m = _Member(rec.drive_id, rec.path, rec.is_dir, op, rec.path, group)
        own = PurePosixPath(link).name
        if nfc(own) != nfc(PurePosixPath(rec.path).name):
            try:  # the shortcut keeps its own name (else the file's, and a note says so)
                m.link_name = check_link_name(own)
            except InvalidRequest:
                pass
        built.members.append(m)
        built.ops.append(op)
        built.origins.setdefault(m.drive_id, link)
        return m

    def _move_member(
        self, built: _Built, src: str, dest: str, group: tuple[str, ...] = ()
    ) -> _Member:
        """MOVE the real file (or folder) ``src`` into ``dest``; it becomes a member."""
        rec = self._indexed(src)
        if rec is None:  # the entry was checked; the index may have changed since
            raise InvalidRequest(f"{src} cannot be converted: {self._indexed_problem(src)}")
        op = Op(OpKind.MOVE, src, dest)
        m = _Member(rec.drive_id, src, rec.is_dir, op, group=group)
        built.members.append(m)
        built.ops.append(op)
        return m

    def _walk(self, rel: str) -> tuple[list[str], list[str], list[str]]:
        """(files, links, dirs) at any depth below the real folder ``rel``, as rels
        (housekeeping names left out; links never followed), each sorted by folded
        path, component by component."""
        files: list[str] = []
        links: list[str] = []
        dirs: list[str] = []
        stack = [rel]
        while stack:
            at = stack.pop()
            with os.scandir(self.paths.abs(at)) as it:
                for e in it:
                    if is_ignored(e.name):
                        continue
                    child = join(at, e.name)
                    if e.is_symlink():
                        links.append(child)
                    elif e.is_dir(follow_symlinks=False):
                        dirs.append(child)
                        stack.append(child)
                    else:
                        files.append(child)
        return (
            sorted(files, key=fold_parts),
            sorted(links, key=fold_parts),
            sorted(dirs, key=fold_parts),
        )

    def _leftover_problem(self, folder: str, left: list[str]) -> str | None:
        """Why ``folder`` could not be removed once the conversion has run: ``left``
        (what stays in it) must be nothing, or a genuine Finder ``.DS_Store`` (the
        check ``remove_empty_dir`` itself makes)."""
        others = [n for n in left if n != primitives.DS_STORE]
        if others:
            return f"it still holds {', '.join(repr(n) for n in others)}"
        if primitives.DS_STORE in left:
            return primitives.finder_cache_problem(self.paths.abs(folder))
        return None

    def _remove_emptied(
        self, built: _Built, entry_rel: str, dirs: list[str]
    ) -> set[tuple[str, ...]]:
        """REMOVE_EMPTY_DIR (deepest first) every folder of the entry that the planned
        ops leave empty (nothing but a genuine Finder ``.DS_Store``); a folder that
        keeps something stays, with a note why. The folded paths removed."""
        away = {fold_parts(op.src) for op in built.ops}
        removed: set[tuple[str, ...]] = set()
        for folder in sorted((entry_rel, *dirs), key=lambda d: -len(PurePosixPath(d).parts)):
            left = [
                n
                for n in sorted(os.listdir(self.paths.abs(folder)))
                if fold_parts(join(folder, n)) not in away | removed
            ]
            problem = self._leftover_problem(folder, left)
            if problem is not None:
                built.problems.append(f"{folder}{FOLDER_NOT_REMOVED}{problem}")
                continue
            built.ops.append(Op(OpKind.REMOVE_EMPTY_DIR, folder, None))
            removed.add(fold_parts(folder))
        return removed

    def _removal_problem(self, rel: str) -> str | None:
        """Why the folder, once its contents are out, could not be removed: what is
        left in it (housekeeping files are not moved) other than a genuine Finder
        ``.DS_Store`` (the check ``remove_empty_dir`` itself makes)."""
        folder = self.paths.abs(rel)
        left = sorted(n for n in os.listdir(folder) if is_ignored(n))
        others = [n for n in left if n != primitives.DS_STORE]
        if others:
            return f"it still holds {', '.join(repr(n) for n in others)}"
        if primitives.DS_STORE in left:
            return primitives.finder_cache_problem(folder)
        return None

    def _preview(self, ops: list[Op]) -> list[ResolvedOp]:
        try:
            return self.executor.preview(Plan(ops, ORIGIN))
        except GuardError as e:
            raise InvalidRequest(f"This cannot be converted: {e}") from None

    def _layout(self, built: _Built, vacated: list[str]) -> Layout:
        """The publisher's ops for the collection as it will be (reads only)."""
        raise NotImplementedError

    def _resolve(self, built: _Built, vacated: list[str]) -> None:
        """Resolve the conversion (collision suffixes), then plan the publisher's
        layout for the collection as it will be, and resolve the whole batch."""
        own = self._preview(built.ops) if built.ops else []
        for m in built.members:
            if m.op.kind is OpKind.MOVE:
                rop = next(r for r in own if _same_op(m.op, r))
                m.dst = rop.dst
        for rop in own:
            if rop.note and COLLISION_NOTE in rop.note:
                built.notes.append(
                    f"{rop.src} will be {rop.dst}: {PurePosixPath(rop.src).name} is"
                    " already taken there"
                )
        layout = self._layout(built, vacated)
        built.notes += layout.reasons
        for op in layout.switches:  # a parent's one link becomes a folder in the batch
            built.notes.append(
                f"{PurePosixPath(op.src).name} becomes a folder in {self.paths.ongoing}"
                " (its link moves inside it)"
            )
        if layout.removals:  # a layout switch of an existing collection: the next sync
            built.notes.append(f"the collection's {self.root} entry is updated right after")
        else:
            built.layout = layout
        built.resolved = self._preview(built.all_ops) if built.all_ops else []
        if [(r.kind, r.src, r.dst) for r in built.resolved[: len(own)]] != [
            (r.kind, r.src, r.dst) for r in own
        ]:
            raise InvalidRequest(
                "Something changed while the conversion was being prepared. Try again."
            )
        built.notes += self._renamed(built, built.resolved[len(own) :])
        built.notes += built.problems

    @staticmethod
    def _renamed(built: _Built, layout: list[ResolvedOp]) -> list[str]:
        """A note per shortcut whose link, as the batch resolves it, is not at the
        shortcut's own name (a name the publisher cannot use, or a real collision,
        ``_2``), and per moved file linked under another name than its own."""
        out = []
        for m in _unique(built.members):
            link = next(
                (
                    r
                    for r in layout
                    if r.kind is OpKind.SYMLINK and fold_parts(r.src) == fold_parts(m.dst)
                ),
                None,
            )
            if link is None:
                continue
            origin = built.origins.get(m.drive_id)
            if origin is not None:
                if nfc(PurePosixPath(link.dst).name) != nfc(PurePosixPath(origin).name):
                    out.append(f"{origin} becomes {link.dst}")
            elif nfc(PurePosixPath(link.dst).name) != nfc(PurePosixPath(m.dst).name):
                out.append(f"{m.dst} is linked as {link.dst}")
        return out

    @staticmethod
    def _plan(built: _Built) -> ConvertPlan:
        unique = _unique(built.members)
        members = [m.dst for m in unique]
        groups = ["/".join(m.group) for m in unique]
        link_names = [m.link_name or "" for m in unique]
        ops = [[str(r.kind), r.src, r.dst, r.drive_id, r.note] for r in built.resolved]
        raw = json.dumps(
            [built.name, ops, members, built.notes, groups, built.star, link_names],
            ensure_ascii=False,
        )
        digest = hashlib.sha256(raw.encode()).hexdigest()
        old = built.existing
        return ConvertPlan(
            built.resolved,
            members,
            built.notes,
            built.name,
            old is not None,
            len(old.members) if old is not None else 0,
            digest,
            groups,
            link_names,
        )

    # --- applying -------------------------------------------------------------------------

    def _save(self, built: _Built, batch: BatchResult) -> tuple[Collection | None, list[str]]:
        """Save what the batch did (memberships tagged with it, so undo removes
        them): the collection, or None when nothing was saved, and notes (a file
        that was a member already is left as it was: its membership is not the
        batch's to undo). Runs under ``sync_lock``, reading the members then."""
        raise NotImplementedError

    def _done_ids(self, built: _Built, batch: BatchResult) -> list[str]:
        """The members whose op completed, one per drive id."""
        return list(
            dict.fromkeys(
                m.drive_id for m in built.members if any(_same_op(m.op, r) for r in batch.done)
            )
        )

    @staticmethod
    def _split_new(built: _Built, ids: list[str], members: list[Member]) -> tuple[list, list]:
        """``ids`` that are not members yet, and notes for the ones that are."""
        have = {m.drive_id for m in members}
        by_id = {m.drive_id: m for m in _unique(built.members)}
        new = [d for d in ids if d not in have]
        notes = [f"{by_id[d].dst}{ALREADY_MEMBER}" for d in ids if d in have]
        return new, notes

    @staticmethod
    def _link_names(built: _Built, ids: list[str]) -> dict[str, str]:
        by_id = {m.drive_id: m for m in _unique(built.members)}
        return {d: by_id[d].link_name for d in ids if by_id[d].link_name}

    def _apply(
        self,
        rel: str,
        build: Callable[[], _Built],
        fingerprint: str,
        label: str | None = None,
    ) -> ConvertResult:
        """Convert ``rel`` in one journaled batch. It is re-planned from the disk now
        and refused (nothing runs) unless that plan is exactly the one previewed
        (``fingerprint`` from ``preview``).

        The publisher's ``sync_lock`` is held for the whole batch (planning, the file
        ops, recording ownership), so syncs wait for it; the ops inside the roots
        are not throttled, only the moves are."""
        with self.ongoing.sync_lock:  # no sync may see the new entries unrecorded
            built = build()
            if self._plan(built).fingerprint != fingerprint:
                raise StalePreview(CHANGED)
            try:
                batch = self.executor.apply(Plan(built.all_ops, ORIGIN, label=label))
            except GuardError as e:  # the disk changed since planning; nothing ran
                raise InvalidRequest(f"This cannot be converted: {e}") from None
            result = ConvertResult(batch, None, list(built.problems))
            if batch.failed is not None:
                result.problems.append(
                    f"The conversion stopped at {batch.failed.src}: {batch.error}"
                )
            if batch.index_error is not None:
                result.problems.append(batch.index_error)
            c = None
            try:
                c, notes = self._save(built, batch)
                result.problems += notes
            except Exception:  # the files moved: never lose the batch result
                log.exception("saving the conversion of %s failed", rel)
                result.problems.append(
                    "The conversion was done, but it could not be saved in the app "
                    "(details are in the log)."
                )
            if c is not None:
                result.collection_id = c.id
                if built.layout is not None:
                    result.problems += built.layout.reasons
                    try:
                        self.ongoing.record_layout(built.layout, c, batch)
                    except Exception:
                        # Without the record the app's folder is not known as the
                        # app's: undo refuses to remove it (identity check).
                        log.exception("recording the entry of %s failed", rel)
                        result.problems.append(NOT_RECORDED)
        # Whatever the batch could not do (a layout switch, a stop partway) the
        # publisher reconciles now, as after any collection change.
        # (outside sync_lock: every registered publisher, as ``App`` wires it)
        try:
            result.sync = self.sync_publishers()
        except Exception:
            log.exception("Ongoing sync after converting %s failed", rel)
            result.problems.append(
                "Ongoing could not be updated afterwards (details are in the log)."
            )
        else:
            if result.sync is None:
                result.problems.append(
                    "Ongoing could not be updated afterwards (details are in the log)."
                )
        result.problems += _undone_by_sync(batch, result.sync)
        return result


class OngoingConverter(_Converter):
    @property
    def root(self) -> str:
        return self.paths.ongoing

    # --- planning -----------------------------------------------------------------------

    def _build(
        self, rel: str, collection: str, destination: str | None, star: bool, to_inbox: bool
    ) -> _Built:
        return self._guarded_build(
            rel, lambda: self._plan_build(rel, collection, destination, star, to_inbox)
        )

    def _plan_build(
        self, rel: str, collection: str, destination: str | None, star: bool, to_inbox: bool
    ) -> _Built:
        entry = self._top_entry(rel)
        if star:
            if entry.kind == "folder":
                raise InvalidRequest(f"{entry.rel} {STAR_FOLDER}")
            existing = self.collections.builtin("starred")
            built = _Built(entry, existing.name, existing, [], [], star=True)
        else:
            cname = check_collection_name(collection)
            existing = self.collections.by_name(cname)
            if existing is not None and existing.state != "open":
                raise InvalidRequest(
                    f"The collection {existing.name!r} is closed. Reopen it first."
                )
            built = _Built(entry, existing.name if existing else cname, existing, [], [])
        vacated: list[str] = []
        if entry.kind == "link":
            self._link_member(built, entry.rel)
            vacated.append(entry.rel)
        else:
            # the inbox is no regular destination: only this explicit mode sends files there
            dest = self.paths.inbox if to_inbox else self._destination(destination)
            if entry.kind == "file":
                self._move_member(built, entry.rel, dest)
                vacated.append(entry.rel)
            elif to_inbox:
                if self._plan_folder_to_inbox(built, entry, dest):
                    vacated.append(entry.rel)
            elif self._plan_folder(built, entry, dest):
                vacated.append(entry.rel)
        if star:  # its membership would not be the batch's: the undo could not remove it
            have = {x.drive_id for x in existing.members}
            for m in built.members:
                if m.drive_id in have:
                    raise InvalidRequest(
                        f"{entry.rel} cannot be starred: {m.src} is already starred"
                    )
        self._resolve(built, vacated)
        return built

    def _plan_folder(self, built: _Built, entry: Entry, dest: str) -> bool:
        """UNLINK the links deeper inside (while still in Ongoing: no link ever moves
        into the archive), MOVE every child, then UNLINK the links directly in it,
        then REMOVE_EMPTY_DIR the folder when that can succeed. True when the folder
        is removed."""
        for link in self._deep_links(entry.rel):
            self._link_member(built, link)
        links = []
        for n in entry.contents:
            child = join(entry.rel, n)
            if self.paths.abs(child).is_symlink():
                links.append(child)
            else:
                self._move_member(built, child, dest)
        for child in links:
            self._link_member(built, child)
        problem = self._removal_problem(entry.rel)
        if problem is not None:
            built.problems.append(NOT_REMOVED + problem)
            return False
        built.ops.append(Op(OpKind.REMOVE_EMPTY_DIR, entry.rel, None))
        return True

    def _plan_folder_to_inbox(self, built: _Built, entry: Entry, inbox: str) -> bool:
        """Every link inside becomes a member (UNLINKed, as above), every real file at
        any depth is MOVEd flat into the inbox (``_2`` on a clash) to be filed one by
        one, then every folder left empty (deepest first) is REMOVE_EMPTY_DIRed. True
        when the entry's folder itself is removed."""
        files, links, dirs = self._walk(entry.rel)
        for link in links:
            self._link_member(built, link)
        for f in files:
            self._move_member(built, f, inbox)
        return fold_parts(entry.rel) in self._remove_emptied(built, entry.rel, dirs)

    def _layout(self, built: _Built, vacated: list[str]) -> Layout:
        if built.star:
            return self.ongoing.star_layout_after(self._after(built), vacated)
        return self.ongoing.layout_after(self._after(built), vacated)

    def _after(self, built: _Built) -> Collection:
        """The collection as it will be once the conversion has run."""
        base = built.existing or Collection(
            id=0,
            name=built.name,
            state="open",
            created=0.0,
            closed_at=None,
            publish={"ongoing": True},
            ongoing_rel=None,
        )
        have = {m.drive_id for m in base.members}
        new = [
            Member(m.drive_id, m.dst, m.is_dir, missing=False, link_name=m.link_name)
            for m in _unique(built.members)
            if m.drive_id not in have
        ]
        return dataclasses.replace(base, members=[*base.members, *new])

    def preview(
        self,
        rel: str,
        collection: str,
        destination: str | None,
        star: bool = False,
        to_inbox: bool = False,
    ) -> ConvertPlan:
        """What converting ``rel`` into ``collection`` (existing or new) would do.
        ``destination``: the archive folder a real folder's contents or a real file
        move to (required for those, ignored for links). ``star``: into the ★
        built-in instead (``collection`` is ignored; a folder is refused). ``to_inbox``:
        the real files go flat into the inbox, to be filed one by one, instead of
        to ``destination`` (ignored then). Reads only."""
        return self._plan(self._build(rel, collection, destination, star, to_inbox))

    # --- applying -------------------------------------------------------------------------

    def apply(
        self,
        rel: str,
        collection: str,
        destination: str | None,
        fingerprint: str,
        star: bool = False,
        to_inbox: bool = False,
    ) -> ConvertResult:
        """Convert ``rel`` in one journaled batch: exactly the previewed plan
        (``fingerprint``), re-planned from the disk now (see ``_Converter._apply``)."""
        name = rel.rsplit("/", 1)[-1]
        label = f"Starred {name}" if star else f"Converted {rel} into {collection}"
        return self._apply(
            rel,
            lambda: self._build(rel, collection, destination, star, to_inbox),
            fingerprint,
            label,
        )

    def _save(self, built: _Built, batch: BatchResult) -> tuple[Collection | None, list[str]]:
        """Members whose op completed and are not members yet, tagged with the batch
        (undo removes them). A new collection is created only when there is
        something to put in it."""
        ids = self._done_ids(built, batch)
        if not ids and built.existing is None:
            return None, []
        c = built.existing or self.collections.get_or_create(built.name, notify=False)
        with self.collections.add_lock(c.id):  # the members as they are now, then the add
            c = self.collections.get(c.id)
            new, notes = self._split_new(built, ids, c.members)
            if new:
                c = self.collections.add_members(
                    c.id, new, batch.batch_id, link_names=self._link_names(built, new), notify=False
                )
        return c, notes


def _unique(members: list[_Member]) -> list[_Member]:
    """One per drive id (two links to one target are one member): the first, or a
    later one whose name is the file's own (so the one link is named after the
    file whenever a duplicate was)."""
    kept: dict[str, _Member] = {}
    for m in members:
        if m.drive_id not in kept:
            kept[m.drive_id] = m
        elif m.link_name is None and kept[m.drive_id].link_name is not None:
            kept[m.drive_id] = m
    return list(kept.values())


def _undone_by_sync(batch: BatchResult, sync: SyncResult | None) -> list[str]:
    """Defence in depth: the follow-up sync removed an entry this batch created
    (it should never have to)."""
    if sync is None:
        return []
    batches = list(sync.batches)
    if sync.batch is not None and sync.batch not in batches:
        batches.append(sync.batch)
    created = {fold_parts(r.dst) for r in batch.done if r.kind in (OpKind.SYMLINK, OpKind.MKDIR)}
    return [
        f"{r.dst} was removed again right after the conversion."
        for b in batches
        for r in b.done
        if r.kind in (OpKind.UNLINK_SYMLINK, OpKind.REMOVE_EMPTY_DIR)
        and fold_parts(r.dst) in created
    ]


def _stem(name: str) -> str:
    """A collection name for a file: its name without the extension."""
    stem = PurePosixPath(name).stem
    return stem if stem and not stem.startswith(".") else name
