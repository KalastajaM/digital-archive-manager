"""The ★ Ongoing and ! Important marks: member changes on the two built-in collections.

Starring or marking a file as important adds it to the built-in collection of that
kind (``CollectionService.builtin``); unmarking removes it. Like every member change it
never moves or renames a file, and the opposite action reverses it. Important takes a
group path ("Houses/Hillside"): the groups along it are created as needed, and a file is
in one group at a time (another path moves it there).

``marks_for`` answers which marks a set of files has, in one query, for the API's file
records (``marks``); ``important_paths`` is what the quarantine guard checks.

Publishing: the two built-ins are published by their ``kind``, not by the ``publish``
flag (migration 0017 gives them ``publish = {}`` and ``set_publish`` refuses them):
``OngoingPublisher`` puts the ★ members as links at the top of ``##. Ongoing`` and
mirrors Important at the root of ``##. Important`` (members at the top, groups as
subfolders). Every mark change here runs ``on_change`` like any member change, so
Finder follows at once.
"""

from __future__ import annotations

from sqlalchemy import select

from dam.collections.service import Collection, CollectionService
from dam.core.paths import nfc
from dam.db.tables import collection_members, collections, files
from dam.services.errors import InvalidRequest

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
