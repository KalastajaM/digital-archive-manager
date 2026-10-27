"""One-time conversion of the user's own ``##. Important`` into the ! Important
built-in (stars design §3.4 and §6, calls 1 and 2).

Each top-level entry of ``##. Important`` that the app does not own is converted on
its own, in one journaled batch (origin ``"ui"``) with one undo, after a binding
preview (``fingerprint``), exactly as Convert Ongoing:

- a **link** to a file or folder in the archive: the target becomes a member
  (ungrouped); the user's link is removed (UNLINK_SYMLINK) and the publisher's own
  link to the member takes its place at the root (named after the member);
- a **real file**: MOVEd into the chosen archive folder, an ungrouped member, linked
  from there;
- a **real folder**: it and each real subfolder below it become Important **groups**
  (nested as the folders are, named as they are); every link inside becomes a member
  of the group for its folder, and its link is replaced by the publisher's in the
  group's folder; every real file inside is MOVEd into the chosen archive folder,
  **mirroring its path** below the root (``<dest>/Houses/Hillside/deed.pdf`` for
  ``##. Important/Houses/Hillside/deed.pdf``, ``_2`` on a clash) and becomes a member
  of its folder's group. The emptied folders are removed (REMOVE_EMPTY_DIR, deepest
  first) only when nothing is left in them but a genuine Finder ``.DS_Store``; a
  folder holding anything else stays, and so does every folder above it (the
  publisher then creates the group's folder beside it, ``<name>_2``), and the
  preview says why. That ``_2`` is for good: a user shortcut left untouched (call 1,
  below) keeps ``Houses`` on disk, the group publishes as ``Houses_2``, and the
  publisher's stable-suffix rule never renames a group folder back once ``Houses``
  is emptied or removed later (a sync note for that is a possible follow-up).

**Every user shortcut is kept** (anti-goal): it is either recreated as the app's
link to the same file in the same folder, under the shortcut's own name
(``Member.link_name`` on the membership row; the file's own name only when the
shortcut's cannot be a link name, and ``_2`` on a real clash, each with a note from
the resolved plan), or left untouched with a reason. A file is in
at most one Important group (call 1): when two shortcuts in the entry point at the
same file, the first in path order (A-Z, folded) becomes the member and the other
is left untouched, "same file as <that path> (already in Important)"; so is a
shortcut to a file that is Important already (the app's link is named instead).
A link that points outside the archive, is broken, or points into ``##. Important``
or ``##. Ongoing`` makes the whole entry unconvertible (never a partial conversion);
so does a file that the index has not seen, or a folder whose name cannot be a
group's.

The batch: the user's links' UNLINKs, the MOVEs, the REMOVE_EMPTY_DIRs, then the
publisher's creations for the built-in as it will be (``OngoingPublisher.
important_layout_after``: the very reconciliation a sync runs, with the vacated
entry taken as gone). The memberships and the groups the conversion makes are
tagged with the batch (``created_by_batch``): the undo of the batch puts back
every link, file and folder exactly where it was (the app's entries are removed
first, identity-checked) and drops the memberships and the still-empty groups.
Nothing outside ``##. Important`` is ever removed; inside it, only the user's links
listed in the preview and the user's folders once empty (never recursively), plus
the app's own entries. The destination may not be inside ``##. Important``,
``##. Ongoing``, the inbox or the quarantine.
"""

from __future__ import annotations

import dataclasses
from pathlib import PurePosixPath

from dam.collections.convert import (
    FOLDER_NOT_REMOVED,
    ConvertBuilt,
    Converter,
    ConvertPlan,
    ConvertResult,
    Entry,
    unique_members,
)
from dam.collections.service import Collection, Group, Member, check_name
from dam.core.paths import nfc
from dam.ops.guards import fold_parts, join, parent
from dam.ops.model import BatchResult
from dam.services.errors import InvalidRequest

NOT_REMOVED = FOLDER_NOT_REMOVED
UNTOUCHED = " is left untouched: same file as "
ALREADY = " (already in Important)"


def _fold(name: str) -> str:
    return nfc(name).casefold()


class ImportantConverter(Converter):
    @property
    def root(self) -> str:
        return self.paths.important

    @property
    def _refused_roots(self) -> tuple[str, ...]:
        return (self.paths.important, self.paths.ongoing)

    @property
    def _forbidden_destinations(self) -> tuple[str, ...]:
        return (*super()._forbidden_destinations, self.paths.important)

    # --- reading ----------------------------------------------------------------------

    def _folder_children(self, rel: str, contents: list[str]) -> list[str]:
        """Everything that must be convertible in the folder entry ``rel``: itself
        and every real subfolder (as group names), every real file and every link
        at any depth."""
        files, links, dirs = self._walk(rel)
        return [rel, *dirs, *files, *links]

    def _child_problem(self, rel: str, folder: str) -> str | None:
        p = self.paths.abs(rel)
        if p.is_symlink():
            return super()._child_problem(rel, folder)
        if p.is_dir():  # a real subfolder (or the entry itself) becomes a group
            try:
                check_name(PurePosixPath(rel).name, "group")
            except InvalidRequest as e:
                return f"The folder {PurePosixPath(rel).name!r} cannot become a group: {e}"
            return None
        return self._indexed_problem(rel)

    # --- planning -----------------------------------------------------------------------

    def _group_of(self, folder: str) -> tuple[str, ...]:
        """The group path (names) for the folder ``folder`` under the root."""
        parts = PurePosixPath(folder).parts
        return tuple(parts[len(PurePosixPath(self.root).parts) :])

    def _build(self, rel: str, destination: str | None) -> ConvertBuilt:
        return self._guarded_build(rel, lambda: self._plan_build(rel, destination))

    def _plan_build(self, rel: str, destination: str | None) -> ConvertBuilt:
        entry = self._top_entry(rel)
        c = self.collections.builtin("important")
        built = ConvertBuilt(entry, c.name, c, [], [])
        vacated: list[str] = []
        if entry.kind == "link":
            if not self._plan_link(built, entry.rel, ()):
                raise InvalidRequest(f"{entry.rel} cannot be converted: {built.notes[-1]}")
            vacated.append(entry.rel)
        else:
            if entry.kind == "file":
                self._move_member(built, entry.rel, self._destination(destination))
                vacated.append(entry.rel)
            else:  # a folder of shortcuts and subfolders only has nothing to move
                dest = self._destination(destination) if entry.real_files else ""
                if self._plan_folder(built, entry, dest):
                    vacated.append(entry.rel)
        self._resolve(built, vacated)
        return built

    def _plan_link(self, built: ConvertBuilt, link: str, group: tuple[str, ...]) -> bool:
        """UNLINK the user's link and make its target a member of ``group``, unless
        the file is Important already (a member, or an earlier link of this entry
        points at it): then the link is left untouched, with the reason noted.
        True when it is converted."""
        target, _, problem = self._link(self.paths.abs(link))
        rec = self._indexed(target) if problem is None else None
        if rec is None:  # the entry was checked; the index may have changed since
            raise InvalidRequest(
                f"{link} cannot be converted: {problem or 'the file it points to is gone'}"
            )
        if rec.drive_id in {m.drive_id for m in built.existing.members}:
            where = self.ongoing.owned_link_for(self.root, rec.path) or rec.path
            built.notes.append(f"{link}{UNTOUCHED}{where}{ALREADY}")
            return False
        first = built.origins.get(rec.drive_id)
        if first is not None:
            built.notes.append(f"{link}{UNTOUCHED}{first}{ALREADY}")
            return False
        self._link_member(built, link, group)
        return True

    def _plan_folder(self, built: ConvertBuilt, entry: Entry, dest: str) -> bool:
        """Every link inside becomes a member of its folder's group and is UNLINKed
        (no link ever moves), every real file is MOVEd to its mirrored place under
        ``dest``, then every folder that is left empty (deepest first) is
        REMOVE_EMPTY_DIRed. The entry and each real subfolder become groups. True
        when the entry's folder itself is removed."""
        files, links, dirs = self._walk(entry.rel)
        built.groups = [self._group_of(d) for d in (entry.rel, *dirs)]
        for link in links:
            self._plan_link(built, link, self._group_of(parent(link)))
        for f in files:
            mirrored = self._group_of(parent(f))
            self._move_member(
                built, f, join(dest, "/".join(mirrored)) if mirrored else dest, mirrored
            )
        removed = self._remove_emptied(built, entry.rel, dirs)
        return fold_parts(entry.rel) in removed

    def _layout(self, built: ConvertBuilt, vacated: list[str]):
        return self.ongoing.important_layout_after(self._after(built), vacated)

    def _after(self, built: ConvertBuilt) -> Collection:
        """The built-in as it will be once the conversion has run: the new members
        in their groups, and the groups that do not exist yet with placeholder ids
        (negative; the publisher only tells groups apart by id)."""
        base = built.existing
        groups = list(base.groups)
        fresh = [0]

        def group_id(path: tuple[str, ...]) -> int | None:
            at: int | None = None
            for name in path:
                found = next(
                    (g for g in groups if g.parent_id == at and _fold(g.name) == _fold(name)),
                    None,
                )
                if found is None:
                    fresh[0] -= 1
                    siblings = [g for g in groups if g.parent_id == at]
                    found = Group(fresh[0], at, name, len(siblings), collection_id=base.id)
                    groups.append(found)
                at = found.id
            return at

        have = {m.drive_id for m in base.members}
        new = [
            Member(
                m.drive_id,
                m.dst,
                m.is_dir,
                missing=False,
                group_id=group_id(m.group),
                link_name=m.link_name,
            )
            for m in unique_members(built.members)
            if m.drive_id not in have
        ]
        for path in built.groups:  # a subfolder without members becomes a group too
            group_id(path)
        return dataclasses.replace(base, members=[*base.members, *new], groups=groups)

    def preview(self, rel: str, destination: str | None) -> ConvertPlan:
        """What converting the entry ``rel`` would do. ``destination``: the archive
        folder its real files move to (required for a real file, or a folder
        that holds real files; ignored for a link). Reads only."""
        return self._plan(self._build(rel, destination))

    # --- applying -------------------------------------------------------------------------

    def apply(self, rel: str, destination: str | None, fingerprint: str) -> ConvertResult:
        """Convert ``rel`` in one journaled batch: exactly the previewed plan
        (``fingerprint``), re-planned from the disk now (see ``Converter._apply``)."""
        return self._apply(
            rel, lambda: self._build(rel, destination), fingerprint, f"Converted {rel}"
        )

    def _save(self, built: ConvertBuilt, batch: BatchResult) -> tuple[Collection | None, list[str]]:
        """The members whose op completed and are not members yet (read now, under
        the lock; one that is already is left as it was and noted), each in its
        group, and every planned group (one ``set_group_path`` per group), all
        tagged with the batch so the undo removes the memberships and the groups
        that are still empty then."""
        cid = built.existing.id
        with self.collections.add_lock(cid):  # the members as they are now, then the adds
            c = self.collections.get(cid)
            new, notes = self._split_new(built, self._done_ids(built, batch), c.members)
            by_id = {m.drive_id: m for m in unique_members(built.members)}
            by_group: dict[tuple[str, ...], list[str]] = {}
            for d in new:
                by_group.setdefault(by_id[d].group, []).append(d)
            for path in built.groups:
                by_group.setdefault(path, [])
            for path, ids in by_group.items():
                if not ids and not path:
                    continue
                self.collections.set_group_path(
                    cid,
                    ids,
                    list(path) or None,
                    batch_id=batch.batch_id,
                    link_names=self._link_names(built, ids),
                    notify=False,
                )
        return self.collections.get(cid), notes
