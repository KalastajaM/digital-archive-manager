"""Versions of a document: editable files in one folder (and its archive subfolder) whose
names differ only by a date, a number or a word like ``final``. Nothing is guessed from the
content, and nothing is stored but the owner's Not a version marks: a file's group is worked
out from the index when it is asked for, so a rename, a move or an edit shows at once.
"""

from __future__ import annotations

import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import Connection, Engine, delete, func, or_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from dam.core.paths import ArchivePaths, nfc
from dam.core.text import fold_name
from dam.db.engine import write_tx
from dam.db.tables import files, version_dismissed
from dam.errors import InvalidRequest, NotFound
from dam.index.repo import FileRecord, FileRepo
from dam.index.repo.model import below, chunks, record
from dam.locks import LockService, request_tokens
from dam.ops.guards import is_under

MIN_KEY = 3

_FAMILIES = {
    "doc": "word",
    "docx": "word",
    "xls": "excel",
    "xlsx": "excel",
    "ppt": "powerpoint",
    "pptx": "powerpoint",
    **{e: e for e in ("odt", "ods", "odp", "pages", "numbers", "key", "rtf", "txt", "md")},
}
_WORDS = (
    "v|ver|version|versio|rev|revised|draft|luonnos|concept|final|lopullinen|new|uusi|old|vanha"
    "|copy|kopio|korjattu|edit|edited|updated|latest|redline"
)
_DASHED = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_DOTTED = re.compile(r"(?<!\d)(\d{1,2})[.-](\d{1,2})[.-](\d{4})(?!\d)")
_SEPARATORS = re.compile(r"[\s_\-.]+")
_COUNTED = re.compile(r"\(\d+\)$")
_NUMBER = re.compile(r"\d{1,2}$")
_VERSION_WORD = re.compile(rf"(?:{_WORDS})\d*$")


def type_family(ext: str | None) -> str | None:
    """The kind of editable document, or None for a file that is not one (PDFs, scans,
    mail and images never have versions here: their similar names are mostly other
    documents)."""
    return _FAMILIES.get((ext or "").lower().lstrip("."))


def _is_date(token: str) -> bool:
    if not token.isdigit() or len(token) not in (6, 8):
        return False
    return 1 <= int(token[-4:-2]) <= 12 and 1 <= int(token[-2:]) <= 31


def _droppable_at_end(token: str) -> bool:
    return bool(
        _is_date(token)
        or _COUNTED.fullmatch(token)
        or _NUMBER.fullmatch(token)
        or _VERSION_WORD.fullmatch(token)
    )


def version_key(name: str) -> str | None:
    """What is left of a file name without its date, number and version words: two names
    with the same key may be versions of one document. A date in the middle stays (it tells
    two letters apart). None when too little is left to say anything."""
    stem = name.rpartition(".")[0] or name
    stem = unicodedata.normalize("NFC", stem).casefold()
    stem = _DASHED.sub(r"\1\2\3", stem)
    stem = _DOTTED.sub(lambda m: f"{m[3]}{int(m[2]):02}{int(m[1]):02}", stem)
    # ``Offer(1)``: the counter stands on its own whatever is in front of it
    stem = re.sub(r"(\(\d+\))", r" \1", stem)
    tokens = [t for t in _SEPARATORS.split(stem) if t]
    if tokens and _is_date(tokens[0]):
        tokens = tokens[1:]
    if tokens[:2] == ["copy", "of"]:
        tokens = tokens[2:]
    while tokens and _droppable_at_end(tokens[-1]):
        tokens.pop()
    key = " ".join(tokens)
    return key if len(key) >= MIN_KEY else None


@dataclass
class VersionFile:
    drive_id: str
    path: str
    name: str
    mtime: float | None
    latest: bool
    in_archive: bool


@dataclass
class Versions:
    """A file's versions as it sees them, newest first, itself among them; no ``files`` when
    it has none. ``folder``: where the older ones would move (None at the top of the
    archive); ``movable``: which would; ``staying``: older files that would not, each
    ``{name, reason}``; ``blocked``: why nothing can move. ``hidden``: how many files are
    marked Not a version of this one."""

    files: list[VersionFile] = field(default_factory=list)
    latest: str | None = None
    hidden: int = 0
    folder: str | None = None
    movable: list[str] = field(default_factory=list)
    staying: list[dict] = field(default_factory=list)
    blocked: str | None = None


@dataclass
class Dismissed:
    drive_id: str
    path: str
    name: str


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def _parent(path: str) -> str:
    return path.rpartition("/")[0]


class VersionsService:
    def __init__(
        self,
        engine: Engine,
        repo: FileRepo,
        paths: ArchivePaths,
        locks: LockService,
        folder_name: Callable[[], str],
    ) -> None:
        self.engine = engine
        self.repo = repo
        self.paths = paths
        self.locks = locks
        self.folder_name = folder_name  # the settings' ``versions_folder_name``

    # --- where a file belongs ---------------------------------------------------------

    def _is_root(self, folder: str) -> bool:
        """The top of the archive or of an extra archive folder: never given a subfolder."""
        return not folder or self.paths.label_of(folder) == folder

    def _is_archive_name(self, name: str) -> bool:
        wanted = fold_name(self.folder_name())
        return fold_name(name) in {wanted, f"_{wanted}"}

    def _home(self, parent: str) -> str:
        """The folder F a file with this parent belongs to: the parent, or its parent when
        the parent is an archive subfolder of a real folder."""
        above, _, name = parent.rpartition("/")
        return above if not self._is_root(above) and self._is_archive_name(name) else parent

    def _considered(self, rec: FileRecord) -> bool:
        if rec.is_dir or rec.is_link or type_family(rec.ext) is None:
            return False
        path = rec.path_nfc
        own = [*self.paths.quarantines, *self.paths.publish_roots, self.paths.inbox]
        return not any(is_under(path, nfc(folder)) for folder in own)

    def _nearby(self, conn: Connection, home: str) -> list:
        """The live rows in ``home`` and one folder below it."""
        path = files.c.path_nfc
        slashes = func.length(path) - func.length(func.replace(path, "/", ""))
        cond = [files.c.missing.is_not(True), files.c.parked_at.is_(None)]
        if home:
            cond += [below(home), slashes <= home.count("/") + 2]
        else:
            cond.append(slashes <= 1)
        return conn.execute(select(files).where(*cond)).all()

    # --- the group ----------------------------------------------------------------------

    def of(self, drive_id: str) -> Versions:
        """The versions of the document as this file sees them. ``NotFound`` for an unknown,
        missing or parked file."""
        rec = self.repo.get(drive_id)
        if rec is None or rec.missing or rec.parked_at is not None:
            raise NotFound(drive_id)
        with self.engine.connect() as conn:
            marked = self._marked(conn, drive_id)
            hidden = len(self._dismissed_rows(conn, marked))
            key = version_key(rec.name or "")
            if key is None or not self._considered(rec):
                return Versions(hidden=hidden)
            home = self._home(_parent(rec.path_nfc))
            nearby = [record(r) for r in self._nearby(conn, home)]
        family = type_family(rec.ext)
        group = []
        for other in nearby:
            parent = _parent(other.path_nfc)
            if (
                self._home(parent) == home
                and other.drive_id not in marked
                and self._considered(other)
                and type_family(other.ext) == family
                and version_key(other.name or "") == key
            ):
                group.append(other)
        if len(group) < 2:
            return Versions(hidden=hidden)
        group.sort(
            key=lambda r: (r.mtime if r.mtime is not None else -1.0, len(r.name or ""), r.path),
            reverse=True,
        )
        latest = group[0].drive_id
        out = Versions(
            files=[
                VersionFile(
                    r.drive_id,
                    r.path,
                    r.name or r.path.rpartition("/")[2],
                    r.mtime,
                    r.drive_id == latest,
                    _parent(r.path_nfc) != home,
                )
                for r in group
            ],
            latest=latest,
            hidden=hidden,
        )
        self._fill_move(out, group, home, nearby)
        return out

    def _fill_move(
        self, out: Versions, group: list[FileRecord], home: str, nearby: list[FileRecord]
    ) -> None:
        folder_name = self.folder_name()
        older = [r for r in group[1:] if _parent(r.path_nfc) == home]
        if self._is_root(home):
            out.blocked = "These files are at the top of the archive, in no folder"
            return
        out.folder = self._destination(group[0].path, home, folder_name, nearby)
        entries = self.locks.entries()
        granted = self.locks.granted(request_tokens())
        for r in older:
            label = self.paths.label_of(r.path)
            name = r.name or r.path.rpartition("/")[2]
            if self.locks.refused(r.path, r.drive_id, entries, granted):
                out.staying.append({"name": name, "reason": "locked"})
            elif label and not self.paths.is_connected(label, cached=True):
                out.staying.append({"name": name, "reason": "not connected"})
            else:
                out.movable.append(r.drive_id)
        if not out.movable:
            reasons = {s["reason"] for s in out.staying}
            if "not connected" in reasons:
                out.blocked = "This archive folder is not connected"
            elif reasons:
                out.blocked = "The older versions are locked"
            else:
                out.blocked = f"The older versions are already in {folder_name}"

    def _destination(
        self, spelled: str, home: str, folder_name: str, nearby: list[FileRecord]
    ) -> str:
        """``F/<name>``, or the ``F/_<name>`` that is already there when ``F/<name>`` is not.
        Spelled as on disk where the folder exists; ``F`` as in the path of a group's file."""
        wanted = fold_name(folder_name)
        dirs = {
            fold_name(r.name or ""): r.path
            for r in nearby
            if r.is_dir and _parent(r.path_nfc) == home
        }
        if wanted in dirs:
            return dirs[wanted]
        if f"_{wanted}" in dirs:
            return dirs[f"_{wanted}"]
        return f"{home}/{folder_name}"

    # --- Not a version --------------------------------------------------------------------

    def _marked(self, conn: Connection, drive_id: str) -> set[str]:
        rows = conn.execute(
            select(version_dismissed.c.drive_a, version_dismissed.c.drive_b).where(
                or_(
                    version_dismissed.c.drive_a == drive_id,
                    version_dismissed.c.drive_b == drive_id,
                )
            )
        ).all()
        return {b if a == drive_id else a for a, b in rows}

    def _dismissed_rows(self, conn: Connection, ids: set[str]) -> list:
        out = []
        for part in chunks(sorted(ids)):
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
        """The files marked Not a version of this one that still exist, by name."""
        with self.engine.connect() as conn:
            rows = self._dismissed_rows(conn, self._marked(conn, drive_id))
        rows.sort(key=lambda r: (fold_name(r.name or ""), r.path))
        return [Dismissed(r.drive_id, r.path, r.name or r.path.rpartition("/")[2]) for r in rows]

    def dismiss(self, a: str, b: str) -> None:
        """Mark the two files Not a version: each is left out of the other's list."""
        if a == b:
            raise InvalidRequest("A file is not a version of itself")
        for drive_id in (a, b):
            rec = self.repo.get(drive_id)
            if rec is None or rec.missing or rec.parked_at is not None:
                raise NotFound(drive_id)
        low, high = _pair(a, b)
        with write_tx(self.engine) as conn:
            conn.execute(
                sqlite_insert(version_dismissed)
                .values(drive_a=low, drive_b=high, created=time.time())
                .on_conflict_do_nothing()
            )

    def restore(self, a: str, b: str) -> None:
        """Take the mark off again (an index row only, never a file)."""
        low, high = _pair(a, b)
        with write_tx(self.engine) as conn:
            conn.execute(
                delete(version_dismissed).where(
                    version_dismissed.c.drive_a == low, version_dismissed.c.drive_b == high
                )
            )
