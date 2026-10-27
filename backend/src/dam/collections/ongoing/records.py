"""The recorded entries (``ongoing_entries``) and what is on disk at them. Part of
``OngoingPublisher`` (``dam.collections.ongoing``)."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select, update

from dam.core.fs import readlink
from dam.core.paths import OutsideArchiveError, nfc
from dam.db.tables import ongoing_entries
from dam.errors import ArchiveUnavailable, NotFound
from dam.index.scanner import is_ignored
from dam.ops import identity
from dam.ops.guards import fold_parts, is_under, parent
from dam.ops.identity import Identity

if TYPE_CHECKING:
    from dam.collections.service import Collection
from dam.collections.ongoing.model import (
    IDENTITY_CHANGED,
    LeftAlone,
    Record,
    log,
)


class RecordsMixin:
    """The recorded entries (``ongoing_entries``) and what is on disk at them."""

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

    def _records(self, root: str | None = None) -> dict[int, list[Record]]:
        """The records by collection id: every one, or only those under ``root``
        (a record lies under exactly one root: its ``rel`` says which)."""
        with self.engine.connect() as conn:
            rows = conn.execute(select(ongoing_entries).order_by(ongoing_entries.c.rel)).all()
        out: dict[int, list[Record]] = {}
        for r in rows:
            if root is not None and not is_under(r.rel, root, strict=True):
                continue
            out.setdefault(r.collection_id, []).append(
                Record(
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

    def _state(self, rec: Record) -> str:
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

    def _refresh_birth(self, rec: Record, now: Identity) -> None:
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

    def _matches(self, rec: Record) -> bool:
        """The entry at ``rec.rel`` is still exactly the one the publisher created.
        Raises OSError when that cannot be told (see ``_state``)."""
        return self._state(rec) == "match"

    def _gone(self, rec: Record) -> bool:
        """The record no longer matches (an entry that cannot be read is kept)."""
        try:
            return not self._matches(rec)
        except OSError:
            return False

    def _owned(self, rec: Record) -> bool:
        """``_matches`` for planning: a moved identity skips the whole tree."""
        state = self._state(rec)
        if state == "moved":
            raise LeftAlone(IDENTITY_CHANGED.format(rel=rec.rel))
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
