"""Who a document is from (a sender) and for (a person), as the owner said it.

Index data in ``file_assignments``: not in the archive, so no operation layer and no
journal. A row is keyed by ``drive_id`` only. ``set_by`` says whether the owner set it or a
confirmed filing recorded it; the owner's word is never overwritten by a filing.
"""

import time
from collections import Counter
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass

from sqlalchemy import Engine, delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from dam.config import Person
from dam.core.paths import nfc
from dam.db.engine import write_tx
from dam.db.tables import file_assignments
from dam.index.repo import FileRepo
from dam.services.errors import InvalidRequest, NotFound

OWNER = "owner"
FILING = "filing"
MAX_SENDER = 80
MAX_FILES = 2000


@dataclass
class Assignment:
    drive_id: str
    sender: str | None
    person: str | None
    set_by: str
    set_at: float


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()  # a field the caller leaves as it is (None clears it)


def check_sender(value: str) -> str:
    """A sender as stored: NFC, one line, trimmed. ``InvalidRequest`` for a blank one."""
    clean = " ".join(nfc(value).split())
    if not clean:
        raise InvalidRequest("A sender name cannot be blank. Use null to clear it.")
    if len(clean) > MAX_SENDER:
        raise InvalidRequest(f"A sender name is at most {MAX_SENDER} characters.")
    if any(not c.isprintable() for c in clean):
        raise InvalidRequest("A sender name cannot contain control characters.")
    return clean


class AssignmentService:
    def __init__(
        self, engine: Engine, repo: FileRepo, people: Callable[[], Sequence[Person]] = list
    ) -> None:
        self.engine = engine
        self.repo = repo
        self._people = people

    # -- reading ---------------------------------------------------------------

    def get(self, drive_ids: Collection[str]) -> dict[str, Assignment]:
        """The assignments of these files (files without one are left out)."""
        ids = list(drive_ids)
        out: dict[str, Assignment] = {}
        with self.engine.connect() as conn:
            for start in range(0, len(ids), 500):
                rows = conn.execute(
                    select(file_assignments).where(
                        file_assignments.c.drive_id.in_(ids[start : start + 500])
                    )
                ).all()
                for r in rows:
                    out[r.drive_id] = Assignment(r.drive_id, r.sender, r.person, r.set_by, r.set_at)
        return out

    def person_of(self, drive_id: str) -> str | None:
        """The person the file is assigned to, else None."""
        with self.engine.connect() as conn:
            return conn.execute(
                select(file_assignments.c.person).where(file_assignments.c.drive_id == drive_id)
            ).scalar()

    def persons(self) -> dict[str, str]:
        """``drive_id -> person`` for every file that has a person assigned."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(file_assignments.c.drive_id, file_assignments.c.person).where(
                    file_assignments.c.person.is_not(None)
                )
            ).all()
        return {r.drive_id: r.person for r in rows}

    def senders(self) -> list[tuple[str, int]]:
        """The senders in use with the number of documents each has, by name."""
        with self.engine.connect() as conn:
            names = conn.execute(
                select(file_assignments.c.sender).where(file_assignments.c.sender.is_not(None))
            ).scalars()
            counts = Counter(names)
        return sorted(counts.items(), key=lambda kv: (kv[0].casefold(), kv[0]))

    def with_sender(self, sender: str) -> list[str]:
        """The drive ids assigned to ``sender`` (compared without case)."""
        want = nfc(sender).casefold()
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(file_assignments.c.drive_id, file_assignments.c.sender).where(
                    file_assignments.c.sender.is_not(None)
                )
            ).all()
        return [r.drive_id for r in rows if nfc(r.sender).casefold() == want]

    # -- writing ---------------------------------------------------------------

    def _person(self, value: str) -> str:
        """The person as the people list spells it; ``InvalidRequest`` if not in it."""
        for p in self._people():
            if p.name.casefold() == nfc(value).strip().casefold():
                return p.name
        raise InvalidRequest(f"{value!r} is not in the people list.")

    def _sender(self, value: str) -> str:
        """The sender as typed, or as already spelled when one with the same letters is in
        use (so "pohjola" does not become a second "Pohjola")."""
        clean = check_sender(value)
        for name, _ in self.senders():
            if name.casefold() == clean.casefold():
                return name
        return clean

    def set(
        self,
        drive_ids: Sequence[str],
        sender: str | None | _Unset = UNSET,
        person: str | None | _Unset = UNSET,
    ) -> list[Assignment]:
        """The owner sets From (``sender``) and/or For (``person``) on these files; a
        field left out stays as it was and ``None`` clears it. A row with both fields empty
        is removed. ``InvalidRequest``: no files, too many, a bad sender, or a person not in
        the people list; ``NotFound``: an unknown, missing or parked file. Nothing is
        written then."""
        ids = list(dict.fromkeys(drive_ids))
        if not ids:
            raise InvalidRequest("No documents given.")
        if len(ids) > MAX_FILES:
            raise InvalidRequest(f"At most {MAX_FILES} documents at a time.")
        if sender is UNSET and person is UNSET:
            raise InvalidRequest("Give a sender, a person, or both (null clears one).")
        new_sender = (
            sender if sender is UNSET or sender is None else self._sender(sender)  # type: ignore[arg-type]
        )
        new_person = (
            person if person is UNSET or person is None else self._person(person)  # type: ignore[arg-type]
        )
        for drive_id in ids:
            rec = self.repo.get(drive_id)
            if rec is None or rec.missing or rec.parked_at is not None:
                raise NotFound(drive_id)
        before = self.get(ids)
        now = time.time()
        with write_tx(self.engine) as conn:
            for drive_id in ids:
                old = before.get(drive_id)
                s = old.sender if old else None
                p = old.person if old else None
                if new_sender is not UNSET:
                    s = new_sender
                if new_person is not UNSET:
                    p = new_person
                if s is None and p is None:
                    conn.execute(
                        delete(file_assignments).where(file_assignments.c.drive_id == drive_id)
                    )
                    continue
                self._upsert(conn, drive_id, s, p, OWNER, now)
        return list(self.get(ids).values())

    def record_filing(self, drive_id: str, person: str) -> bool:
        """A confirmed filing used ``person`` for the folder: remember it as this file's
        person, unless the owner has set something for it. Returns whether it was written."""
        old = self.get([drive_id]).get(drive_id)
        if old is not None and old.set_by == OWNER:
            return False
        with write_tx(self.engine) as conn:
            self._upsert(conn, drive_id, old.sender if old else None, person, FILING, time.time())
        return True

    @staticmethod
    def _upsert(conn, drive_id: str, sender, person, set_by: str, now: float) -> None:
        stmt = sqlite_insert(file_assignments).values(
            drive_id=drive_id, sender=sender, person=person, set_by=set_by, set_at=now
        )
        conn.execute(
            stmt.on_conflict_do_update(
                index_elements=["drive_id"],
                set_={c: stmt.excluded[c] for c in ("sender", "person", "set_by", "set_at")},
            )
        )
