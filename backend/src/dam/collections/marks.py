"""The ★ Ongoing and ! Important marks: member changes on the two built-in collections.

Starring or marking a file as important adds it to the built-in collection of that
kind (``CollectionService.builtin``); unmarking removes it. Like every member change it
never moves or renames a file, and the opposite action reverses it. Important takes a
group path ("Houses/Hillside"): the groups along it are created as needed, and a file is
in one group at a time (another path moves it there).

``marks_for`` answers which marks a set of files has, in one query, for the API's file
records (``marks``); ``important_paths`` is what the quarantine guard checks.

A renewal passes the marks from an item's old file to its new one (``apply_transfer``,
``MarkState`` saying what the old file had) and its Undo gives them back
(``restore_transfer``).

Publishing: the two built-ins are published by their ``kind``, not by the ``publish``
flag (migration 0017 gives them ``publish = {}`` and ``set_publish`` refuses them):
``OngoingPublisher`` puts the ★ members as links at the top of ``##. Ongoing`` and
mirrors Important at the root of ``##. Important`` (members at the top, groups as
subfolders). Every mark change here runs ``on_change`` like any member change, so
Finder follows at once.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Connection, select, update

from dam.collections.service import Collection, CollectionService
from dam.core.paths import nfc
from dam.db.engine import write_tx
from dam.db.tables import collection_groups, collection_members, collections, files
from dam.errors import InvalidRequest

# the order marks are listed in
KINDS = ("starred", "important")
# above this many ids, ``marks_for`` reads every mark (they are few) instead of an IN
# list, so it stays one query whatever the SQLite variable limit
_IN_MAX = 900


def group_path(text: str | None) -> list[str] | None:
    """``"Houses/Hillside"`` -> ``["Houses", "Hillside"]`` (each part trimmed; the
    names are checked when the groups are made). None or blank: no group."""
    if text is None:
        return None
    if not isinstance(text, str):
        raise InvalidRequest("A group path is text")
    if not text.strip():
        return None
    parts = [p.strip() for p in text.strip().strip("/").split("/")]
    if any(not p for p in parts):
        raise InvalidRequest(f"{text!r} is not a group path (an empty part)")
    return parts


@dataclass(frozen=True)
class MarkState:
    """The marks a file has: Starred, Important, its Important group (names from the
    top; None: ungrouped or not Important) and its published link's own name (the
    Important one, else the Starred one; None: the file's own name)."""

    starred: bool
    important: bool
    group: list[str] | None
    link_name: str | None


class MarkService:
    def __init__(self, collections: CollectionService) -> None:
        self.collections = collections
        self.engine = collections.engine

    def _id(self, kind: str) -> int:
        return self.collections.builtin(kind).id

    def star(self, drive_ids: list[str], *, notify: bool = True) -> Collection:
        return self.collections.add_members(self._id("starred"), drive_ids, notify=notify)

    def unstar(self, drive_ids: list[str], *, notify: bool = True) -> Collection:
        return self.collections.remove_members(self._id("starred"), drive_ids, notify=notify)

    def mark_important(
        self, drive_ids: list[str], group: str | None = None, *, notify: bool = True
    ) -> Collection:
        """Mark the files as important, in the group at ``group`` ("A/B"; None: new
        ones ungrouped, already marked ones keep their group)."""
        return self.collections.set_group_path(
            self._id("important"), drive_ids, group_path(group), notify=notify
        )

    def unmark_important(self, drive_ids: list[str], *, notify: bool = True) -> Collection:
        return self.collections.remove_members(self._id("important"), drive_ids, notify=notify)

    def marks_for(self, drive_ids: list[str]) -> dict[str, list[str]]:
        """Each id's marks (``starred`` first, then ``important``; [] for none), in
        one query (none for no ids)."""
        ids = list(dict.fromkeys(drive_ids))
        if not ids:
            return {}
        query = (
            select(collection_members.c.drive_id, collections.c.kind)
            .select_from(
                collection_members.join(
                    collections, collections.c.id == collection_members.c.collection_id
                )
            )
            .where(collections.c.kind.is_not(None))
        )
        if len(ids) <= _IN_MAX:
            query = query.where(collection_members.c.drive_id.in_(ids))
        with self.engine.connect() as conn:
            rows = conn.execute(query).all()
        found: dict[str, set[str]] = {}
        for r in rows:
            found.setdefault(r.drive_id, set()).add(r.kind)
        return {d: [k for k in KINDS if k in found.get(d, ())] for d in ids}

    def important_paths(self) -> list[tuple[str, str, bool]]:
        """``(drive_id, path_nfc, is_dir)`` of every Important member that has a live
        row (one query): what the quarantine guard refuses, with everything under a
        marked folder."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(files.c.drive_id, files.c.path_nfc, files.c.is_dir)
                .select_from(
                    collection_members.join(
                        collections, collections.c.id == collection_members.c.collection_id
                    ).join(files, files.c.drive_id == collection_members.c.drive_id)
                )
                .where(
                    collections.c.kind == "important",
                    files.c.missing.is_not(True),
                    files.c.parked_at.is_(None),
                )
            ).all()
        return [(r.drive_id, nfc(r.path_nfc), bool(r.is_dir)) for r in rows]

    # --- renewal: the marks follow the new file ------------------------------------

    def marks_state(self, drive_id: str) -> MarkState:
        with self.engine.connect() as conn:
            return self.state_in(conn, drive_id)

    def state_in(self, conn: Connection, drive_id: str) -> MarkState:
        """``marks_state`` inside the caller's transaction."""
        rows = {
            r.kind: r
            for r in conn.execute(
                select(
                    collections.c.kind,
                    collection_members.c.group_id,
                    collection_members.c.link_name,
                )
                .select_from(
                    collection_members.join(
                        collections, collections.c.id == collection_members.c.collection_id
                    )
                )
                .where(collections.c.kind.in_(KINDS), collection_members.c.drive_id == drive_id)
            ).all()
        }
        important = rows.get("important")
        group: list[str] | None = None
        if important is not None and important.group_id is not None:
            group, gid = [], important.group_id
            while gid is not None:
                g = conn.execute(
                    select(collection_groups.c.name, collection_groups.c.parent_id).where(
                        collection_groups.c.id == gid
                    )
                ).one()
                group.insert(0, g.name)
                gid = g.parent_id
        named = important if important is not None else rows.get("starred")
        return MarkState(
            starred="starred" in rows,
            important=important is not None,
            group=group,
            link_name=named.link_name if named is not None else None,
        )

    def apply_transfer(self, old: str, new: str, state: MarkState, *, notify: bool = False) -> None:
        """Move the marks ``state`` says ``old`` has to ``new``, Important into the same
        group; ``old`` loses them. Tags and other collections are not touched."""
        with self.collections.important_lock, write_tx(self.engine) as conn:
            self.transfer_in(conn, old, new, state)
        if notify:
            self.collections.changed()

    def restore_transfer(
        self,
        old: str,
        new: str,
        state: MarkState,
        new_state: MarkState | None = None,
        *,
        notify: bool = False,
    ) -> None:
        """Undo ``apply_transfer``: ``old`` gets back the marks in ``state`` (its group,
        its link name) and ``new`` loses them, except the ones ``new_state`` (what
        ``new`` had before the transfer) says it had: those stay, Important back in
        its own group."""
        with self.collections.important_lock, write_tx(self.engine) as conn:
            self.restore_in(conn, old, new, state, new_state)
        if notify:
            self.collections.changed()

    def transfer_in(self, conn: Connection, old: str, new: str, state: MarkState) -> None:
        """``apply_transfer`` inside the caller's transaction; the caller holds
        ``important_lock`` and runs ``collections.changed`` after the commit."""
        self._move_marks(conn, old, new, state, None)

    def restore_in(
        self,
        conn: Connection,
        old: str,
        new: str,
        state: MarkState,
        new_state: MarkState | None = None,
    ) -> None:
        """``restore_transfer`` inside the caller's transaction (as ``transfer_in``)."""
        prior = new_state or MarkState(False, False, None, None)
        self._move_marks(conn, new, old, state, state.link_name, prior)

    def _move_marks(
        self,
        conn: Connection,
        source: str,
        target: str,
        state: MarkState,
        link_name: str | None,
        keep: MarkState | None = None,
    ) -> None:
        """Take the marks in ``state`` off ``source`` and put them on ``target``, which
        keeps ``link_name`` for its link (None: its own name, or the one it had).
        ``keep``: the marks ``source`` had of its own, which stay on it (Important put
        back in ``keep.group``)."""
        names = {target: link_name} if link_name is not None else None
        if state.starred:
            starred = self._id("starred")
            if not (keep and keep.starred):
                self.collections.take_out(conn, starred, [source])
            self.collections.put_in_group_path(
                conn, starred, [target], None, link_names=None if state.important else names
            )
        if state.important:
            important = self._id("important")
            if keep and keep.important:
                self._regroup(conn, important, source, keep.group)
            else:
                self.collections.take_out(conn, important, [source])
            self.collections.put_in_group_path(
                conn, important, [target], state.group, link_names=names
            )

    def _regroup(
        self, conn: Connection, important: int, drive_id: str, group: list[str] | None
    ) -> None:
        """Put an Important member back in the group at ``group`` (None: ungrouped)."""
        if group is not None:
            self.collections.put_in_group_path(conn, important, [drive_id], group)
            return
        conn.execute(
            update(collection_members)
            .where(
                collection_members.c.collection_id == important,
                collection_members.c.drive_id == drive_id,
            )
            .values(group_id=None)
        )
