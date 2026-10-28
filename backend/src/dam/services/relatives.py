"""Relatives: the files a document belongs with, and why.

A file is a relative of another when it shares at least one link with it: the same
reference number, sender, collection, tag, folder, IBAN or person. Each link adds its
weight (``WEIGHTS``) and the list is ranked by the sum. The booster (same month of the
document date) only adds to a file that already has a link, and never makes one.

A tag, IBAN, sender or person that very many files share says little: above
``COMMON_LIMIT`` files it counts half, above five times that not at all (a payment
service's IBAN, a catch-all tag). Only live files count: not missing, not parked, not
folders, not links (a link in the archive stands for its target, which is listed once),
and not what is marked for deletion. A pair the owner marked "Not related" is left out.

Everything here is read from the index; nothing is written to the archive. The marks
("Not related") are index data in ``related_dismissed``: no operation layer, no journal.
"""

import time
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import Connection, Engine, and_, delete, func, literal, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from dam.core.paths import ArchivePaths
from dam.core.text import fold
from dam.db.engine import write_tx
from dam.db.tables import (
    collection_members,
    collections,
    file_assignments,
    file_tags,
    files,
    item_files,
    items,
    related_dismissed,
    tags,
)
from dam.errors import InvalidRequest, NotFound
from dam.index.repo import FileRecord, FileRepo
from dam.services.links import link_target

# What each kind of link adds. One table, so the weights can be tuned in one place.
WEIGHTS: dict[str, float] = {
    "reference": 5,
    "sender": 3,
    "collection": 3,
    "tag": 2,  # each shared tag
    "folder": 2,
    "iban": 2,
    "person": 1,
}
SAME_MONTH = 1  # the booster: both files have a document date in the same year and month
KINDS = tuple(WEIGHTS)

# A value shared by more files than this counts half; by more than ``COMMON_FACTOR`` times
# this, not at all. Applies to tags, IBANs, senders and persons.
COMMON_LIMIT = 200
COMMON_FACTOR = 5
DAMPED = frozenset({"tag", "iban", "sender", "person"})

MAX_RELATIVES = 200
_CHUNK = 500


@dataclass(frozen=True)
class RelLink:
    kind: str
    value: str
    weight: float


@dataclass
class Relative:
    drive_id: str
    path: str
    name: str
    ext: str | None
    folder: str
    score: float
    links: list[RelLink]
    same_month: bool
    in_inbox: bool


@dataclass(frozen=True)
class Common:
    """A value some relatives share with the file, and how many of them do."""

    kind: str
    value: str
    count: int


@dataclass
class Relatives:
    drive_id: str  # the file asked about (for a link in the archive: its target)
    relatives: list[Relative] = field(default_factory=list)
    common: list[Common] = field(default_factory=list)
    total: int = 0  # relatives before ``limit`` cut the list
    hidden: int = 0  # pairs marked "Not related" for this file


@dataclass
class Dismissed:
    drive_id: str
    path: str
    name: str


_live = and_(
    files.c.missing.is_not(True),
    files.c.parked_at.is_(None),
    files.c.is_dir.is_not(True),
    files.c.is_link.is_not(True),
)


def _chunks(values: list[str]) -> Iterable[list[str]]:
    for i in range(0, len(values), _CHUNK):
        yield values[i : i + _CHUNK]


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def damping(count: int, limit: int = COMMON_LIMIT) -> float:
    """1 for a value shared by up to ``limit`` files, 0.5 up to ``COMMON_FACTOR`` times
    that, else 0."""
    if count > limit * COMMON_FACTOR:
        return 0.0
    return 0.5 if count > limit else 1.0


def _like_escape(path: str) -> str:
    """``path`` for a LIKE pattern with ``escape="\\"``."""
    return path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _folder_of(path_nfc: str) -> str:
    return path_nfc.rpartition("/")[0]


def _iban(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return "".join(value.split()).upper() or None


def _reference(value: object) -> str | None:
    if not isinstance(value, str | int):
        return None
    return "".join(str(value).split()).casefold() or None


class RelativesService:
    def __init__(
        self,
        engine: Engine,
        repo: FileRepo,
        paths: ArchivePaths,
        common_limit: int = COMMON_LIMIT,
    ) -> None:
        self.engine = engine
        self.repo = repo
        self.paths = paths
        self.common_limit = common_limit

    # -- reading ---------------------------------------------------------------

    def of(self, drive_id: str, limit: int = MAX_RELATIVES) -> Relatives:
        """The relatives of a file, best first (at most ``limit``). A link in the archive
        is asked about as its target; one that leads nowhere has no relatives."""
        rec = self.repo.get(drive_id)
        if rec is None or rec.missing or rec.parked_at is not None:
            raise NotFound(drive_id)
        if rec.is_link:
            target = link_target(self.paths, self.repo, rec)
            if target is None:
                return Relatives(drive_id)
            rec = target
        if rec.is_dir:
            return Relatives(rec.drive_id)
        subject = rec.drive_id
        with self.engine.connect() as conn:
            marked = self._marked(conn, subject)
            hits: dict[str, dict[tuple[str, str], float]] = {}
            self._tags(conn, subject, hits)
            self._assignments(conn, subject, hits)
            self._collections(conn, rec, hits)
            self._folder(conn, rec, hits)
            self._items(conn, subject, hits)
            for other in [*marked, subject]:
                hits.pop(other, None)
            rows = self._rows(conn, list(hits))
            hidden = len(self._dismissed_rows(conn, subject))
        found: list[Relative] = []
        for other_id, links in hits.items():
            row = rows.get(other_id)
            if row is None or self.paths.is_quarantined(row.path):
                continue
            score = sum(links.values())
            if score <= 0:
                continue
            month = (
                rec.doc_date is not None
                and row.doc_date is not None
                and (rec.doc_date.year, rec.doc_date.month)
                == (row.doc_date.year, row.doc_date.month)
            )
            found.append(
                Relative(
                    drive_id=other_id,
                    path=row.path,
                    name=row.name or row.path.rpartition("/")[2],
                    ext=row.ext,
                    folder=row.path.rpartition("/")[0],
                    score=score + (SAME_MONTH if month else 0),
                    links=[RelLink(k, v, w) for (k, v), w in links.items() if w > 0],
                    same_month=bool(month),
                    in_inbox=self.repo.in_inbox_path(row.path),
                )
            )
        found.sort(key=lambda r: (-r.score, fold(r.name), r.path, r.drive_id))
        shown = found[:limit]
        return Relatives(
            drive_id=subject,
            relatives=shown,
            common=self._common(shown),
            total=len(found),
            hidden=hidden,
        )

    @staticmethod
    def _common(relatives: list[Relative]) -> list[Common]:
        counts: dict[tuple[str, str], int] = {}
        for r in relatives:
            for link in r.links:
                key = (link.kind, link.value)
                counts[key] = counts.get(key, 0) + 1
        order = {kind: i for i, kind in enumerate(KINDS)}
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], order[kv[0][0]], fold(kv[0][1])))
        return [Common(kind, value, n) for (kind, value), n in ranked]

    # -- the links, one query per kind -----------------------------------------

    def _add(
        self,
        hits: dict[str, dict[tuple[str, str], float]],
        other: str,
        kind: str,
        value: str,
        count: int | None = None,
    ) -> None:
        weight = WEIGHTS[kind]
        if kind in DAMPED and count is not None:
            weight *= damping(count, self.common_limit)
        if weight > 0:
            hits.setdefault(other, {})[(kind, value)] = weight

    def _tags(self, conn: Connection, subject: str, hits: dict) -> None:
        mine = conn.execute(
            select(tags.c.id, tags.c.name)
            .join(file_tags, file_tags.c.tag_id == tags.c.id)
            .where(file_tags.c.drive_id == subject)
        ).all()
        if not mine:
            return
        names = {tag_id: name for tag_id, name in mine}
        rows = conn.execute(
            select(file_tags.c.tag_id, file_tags.c.drive_id)
            .join(files, files.c.drive_id == file_tags.c.drive_id)
            .where(file_tags.c.tag_id.in_(list(names)), file_tags.c.drive_id != subject, _live)
        ).all()
        sharing: dict[int, list[str]] = {}
        for tag_id, other in rows:
            sharing.setdefault(tag_id, []).append(other)
        for tag_id, others in sharing.items():
            count = len(others) + 1  # and this file
            for other in others:
                self._add(hits, other, "tag", names[tag_id], count)

    def _assignments(self, conn: Connection, subject: str, hits: dict) -> None:
        mine = conn.execute(
            select(file_assignments.c.sender, file_assignments.c.person).where(
                file_assignments.c.drive_id == subject
            )
        ).one_or_none()
        if mine is None:
            return
        for kind, value in (("sender", mine.sender), ("person", mine.person)):
            if not value:
                continue
            column = getattr(file_assignments.c, kind)
            others = (
                conn.execute(
                    select(file_assignments.c.drive_id)
                    .join(files, files.c.drive_id == file_assignments.c.drive_id)
                    .where(
                        func.dam_fold(column) == fold(value),
                        file_assignments.c.drive_id != subject,
                        _live,
                    )
                )
                .scalars()
                .all()
            )
            for other in others:
                self._add(hits, other, kind, value, len(others) + 1)

    def _collections(self, conn: Connection, rec: FileRecord, hits: dict) -> None:
        # A collection holds files directly or through a member folder (every file inside
        # it, at any depth), as the file panel's collection chips count them. The two
        # built-in collections (starred, important) are marks, not groups of files.
        subject = rec.drive_id
        folders = files.alias("folder")
        live_folder = and_(
            folders.c.is_dir.is_(True),
            folders.c.missing.is_not(True),
            folders.c.parked_at.is_(None),
        )
        regular = collections.c.kind.is_(None)
        direct = select(collection_members.c.collection_id).where(
            collection_members.c.drive_id == subject
        )
        prefix_len = func.length(folders.c.path_nfc) + 1
        through_folder = (
            select(collection_members.c.collection_id)
            .join(folders, folders.c.drive_id == collection_members.c.drive_id)
            .where(
                live_folder,
                func.substr(literal(rec.path_nfc), 1, prefix_len) == folders.c.path_nfc + "/",
            )
        )
        mine = dict(
            conn.execute(
                select(collections.c.id, collections.c.name).where(
                    regular, collections.c.id.in_(direct.union(through_folder))
                )
            ).all()
        )
        if not mine:
            return
        # the files added one by one
        rows = conn.execute(
            select(collection_members.c.drive_id, collection_members.c.collection_id)
            .join(files, files.c.drive_id == collection_members.c.drive_id)
            .where(
                collection_members.c.collection_id.in_(list(mine)),
                collection_members.c.drive_id != subject,
                _live,
            )
        ).all()
        for other, cid in rows:
            self._add(hits, other, "collection", mine[cid])
        # the files inside its member folders
        held = conn.execute(
            select(folders.c.path_nfc, collection_members.c.collection_id)
            .join(folders, folders.c.drive_id == collection_members.c.drive_id)
            .where(collection_members.c.collection_id.in_(list(mine)), live_folder)
        ).all()
        for path, cid in held:
            others = conn.execute(
                select(files.c.drive_id).where(
                    files.c.path_nfc.like(_like_escape(path) + "/%", escape="\\"),
                    files.c.drive_id != subject,
                    _live,
                )
            ).scalars()
            for other in others:
                self._add(hits, other, "collection", mine[cid])

    def _folder(self, conn: Connection, rec: FileRecord, hits: dict) -> None:
        # Sharing the inbox (or a code's inbox folder) or the archive root says nothing:
        # those hold what is not filed yet, so they are no folder link.
        folder = _folder_of(rec.path_nfc)
        if not folder or self.repo.in_inbox_path(rec.path):
            return
        escaped = _like_escape(folder)
        direct = and_(
            files.c.path_nfc.like(escaped + "/%", escape="\\"),
            files.c.path_nfc.not_like(escaped + "/%/%", escape="\\"),
        )
        others = conn.execute(
            select(files.c.drive_id).where(direct, files.c.drive_id != rec.drive_id, _live)
        ).scalars()
        label = rec.path.rpartition("/")[0]
        for other in others:
            self._add(hits, other, "folder", label)

    def _items(self, conn: Connection, subject: str, hits: dict) -> None:
        """Reference numbers and IBANs of the tray items the files belong to."""
        mine = conn.execute(
            select(items.c.fields)
            .join(item_files, item_files.c.item_id == items.c.id)
            .where(item_files.c.drive_id == subject)
        ).scalars()
        refs: dict[str, str] = {}
        ibans: dict[str, str] = {}
        for fields in mine:
            if not isinstance(fields, dict):
                continue
            if (ref := _reference(fields.get("reference"))) is not None:
                refs.setdefault(ref, str(fields["reference"]).strip())
            if (iban := _iban(fields.get("iban"))) is not None:
                ibans.setdefault(iban, iban)
        if not refs and not ibans:
            return
        rows = conn.execute(
            select(item_files.c.drive_id, items.c.fields)
            .join(items, items.c.id == item_files.c.item_id)
            .join(files, files.c.drive_id == item_files.c.drive_id)
            .where(_live)
        ).all()
        by_iban: dict[str, set[str]] = {}
        shared_ref: dict[str, set[str]] = {}
        for other, fields in rows:
            if not isinstance(fields, dict):
                continue
            ref = _reference(fields.get("reference"))
            if ref in refs and other != subject:
                shared_ref.setdefault(ref, set()).add(other)
            iban = _iban(fields.get("iban"))
            if iban in ibans:
                by_iban.setdefault(iban, set()).add(other)
        for ref, others in shared_ref.items():
            for other in others:
                self._add(hits, other, "reference", refs[ref])
        for iban, everyone in by_iban.items():
            count = len(everyone | {subject})
            for other in everyone - {subject}:
                self._add(hits, other, "iban", ibans[iban], count)

    def _rows(self, conn: Connection, ids: list[str]) -> dict:
        out: dict = {}
        for part in _chunks(ids):
            for row in conn.execute(
                select(
                    files.c.drive_id, files.c.path, files.c.name, files.c.ext, files.c.doc_date
                ).where(files.c.drive_id.in_(part), _live)
            ):
                out[row.drive_id] = row
        return out

    # -- "Not related" ---------------------------------------------------------

    def _marked(self, conn: Connection, drive_id: str) -> set[str]:
        rows = conn.execute(
            select(related_dismissed.c.drive_a, related_dismissed.c.drive_b).where(
                or_(
                    related_dismissed.c.drive_a == drive_id, related_dismissed.c.drive_b == drive_id
                )
            )
        ).all()
        return {b if a == drive_id else a for a, b in rows}

    def _dismissed_rows(self, conn: Connection, drive_id: str) -> list:
        ids = sorted(self._marked(conn, drive_id))
        out = []
        for part in _chunks(ids):
            out.extend(
                conn.execute(
                    select(files.c.drive_id, files.c.path, files.c.name).where(
                        files.c.drive_id.in_(part),
                        files.c.missing.is_not(True),
                        files.c.parked_at.is_(None),
                    )
                ).all()
            )
        return out

    def dismissed(self, drive_id: str) -> list[Dismissed]:
        """The files marked "Not related" to this one that still exist, by name."""
        with self.engine.connect() as conn:
            rows = self._dismissed_rows(conn, drive_id)
        rows.sort(key=lambda r: (fold(r.name or ""), r.path))
        return [Dismissed(r.drive_id, r.path, r.name or r.path.rpartition("/")[2]) for r in rows]

    def _check_pair(self, a: str, b: str) -> None:
        if a == b:
            raise InvalidRequest("A file is not related to itself")
        for drive_id in (a, b):
            rec = self.repo.get(drive_id)
            if rec is None or rec.missing or rec.parked_at is not None:
                raise NotFound(drive_id)

    def dismiss(self, a: str, b: str) -> None:
        """Mark the two files "Not related": each is left out of the other's list."""
        self._check_pair(a, b)
        low, high = _pair(a, b)
        with write_tx(self.engine) as conn:
            conn.execute(
                sqlite_insert(related_dismissed)
                .values(drive_a=low, drive_b=high, created=time.time())
                .on_conflict_do_nothing()
            )

    def restore(self, a: str, b: str) -> None:
        """Take the mark off again (an index row only, never a file)."""
        low, high = _pair(a, b)
        with write_tx(self.engine) as conn:
            conn.execute(
                delete(related_dismissed).where(
                    related_dismissed.c.drive_a == low, related_dismissed.c.drive_b == high
                )
            )
