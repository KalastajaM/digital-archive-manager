"""Senders named from their business IDs (Settings, Senders).

The identifiers pass keeps, per file, the company name printed next to each ID
(``file_identifiers.name``). Here those are counted into one suggested name per ID, and
the owner's confirmed names (``identifier_names``) fill From on the files that carry the
ID (``dam.index.repo.names.fill_senders``). Clearing a name takes those senders back.
Index data, as ``file_assignments``: no operation layer and no journal.
"""

import time
from collections import Counter, defaultdict
from dataclasses import dataclass

from sqlalchemy import Engine, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from dam import packs
from dam.countries import IdentifierSpec
from dam.db.engine import write_tx
from dam.db.tables import file_assignments, file_identifiers, files, identifier_names
from dam.errors import InvalidRequest
from dam.index.repo import FileRepo
from dam.index.repo.names import OWNER, carriers, fill_senders, given
from dam.services.assignments import check_sender

MIN_FILES = 2  # an ID on one file only is not worth a question


@dataclass
class NameRow:
    kind: str
    label: str
    value: str
    files: int  # live files whose current content carries it
    suggested: str | None  # the name printed next to it most often
    name: str | None  # the owner's name, else None
    set_at: float | None
    filled: int  # of ``files``, those whose From is ``name``
    own: bool  # the owner's own business ID: it names no sender


def _spelling(names: Counter[str]) -> str:
    """The most common spelling, mixed case before all capitals."""
    return max(names, key=lambda n: (names[n], not n.isupper(), n))


def suggest(names: Counter[str]) -> str | None:
    """The name read next to an ID on the most files, letters compared without case."""
    groups: dict[str, Counter[str]] = defaultdict(Counter)
    for name, n in names.items():
        groups[" ".join(name.split()).casefold()][name] += n
    if not groups:
        return None
    best = max(groups.values(), key=lambda g: (g.total(), _spelling(g)))
    return " ".join(_spelling(best).split())


class SenderNames:
    def __init__(self, engine: Engine, repo: FileRepo) -> None:
        self.engine = engine
        self.repo = repo

    @staticmethod
    def specs() -> dict[str, IdentifierSpec]:
        """The enabled packs' identifiers that can be named from a document."""
        return {
            s.kind: s for p in packs.active().countries for s in p.identifiers if s.name is not None
        }

    def list(self) -> list[NameRow]:
        """Every nameable ID on two or more live files, and every named one: most files
        first."""
        specs = self.specs()
        if not specs:
            return []
        own = packs.active().own_ids
        live = (
            files.c.sha256 == file_identifiers.c.sha256,
            files.c.missing.is_not(True),
            files.c.parked_at.is_(None),
            file_identifiers.c.kind.in_(specs),
        )
        joined = file_identifiers.join(files, files.c.drive_id == file_identifiers.c.drive_id)
        with self.engine.connect() as conn:
            counts = {
                (r.kind, r.value): r.n
                for r in conn.execute(
                    select(
                        file_identifiers.c.kind, file_identifiers.c.value, func.count().label("n")
                    )
                    .select_from(joined)
                    .where(*live)
                    .group_by(file_identifiers.c.kind, file_identifiers.c.value)
                )
            }
            named = {
                (r.kind, r.value): r
                for r in conn.execute(
                    select(identifier_names).where(identifier_names.c.kind.in_(specs))
                )
            }
            keys = [k for k, n in counts.items() if n >= MIN_FILES or k in named or k[1] in own]
            keys += [k for k in named if k not in counts]
            read: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
            for r in conn.execute(
                select(file_identifiers.c.kind, file_identifiers.c.value, file_identifiers.c.name)
                .select_from(joined)
                .where(*live, file_identifiers.c.name.is_not(None))
            ):
                read[r.kind, r.value][r.name] += 1
            filled: Counter[tuple[str, str]] = Counter()
            if named:
                for r in conn.execute(
                    select(
                        file_identifiers.c.kind,
                        file_identifiers.c.value,
                        file_assignments.c.sender,
                    )
                    .select_from(
                        joined.join(
                            file_assignments,
                            file_assignments.c.drive_id == file_identifiers.c.drive_id,
                        )
                    )
                    .where(*live, file_assignments.c.sender.is_not(None))
                ):
                    have = named.get((r.kind, r.value))
                    if have is not None and r.sender.casefold() == have.name.casefold():
                        filled[r.kind, r.value] += 1
        rows = [
            NameRow(
                kind=kind,
                label=specs[kind].label,
                value=value,
                files=counts.get((kind, value), 0),
                suggested=suggest(read[kind, value]),
                name=named[kind, value].name if (kind, value) in named else None,
                set_at=named[kind, value].set_at if (kind, value) in named else None,
                filled=filled[kind, value],
                own=value in own,
            )
            for kind, value in keys
        ]
        rows.sort(key=lambda r: (-r.files, r.kind, r.value))
        return rows

    def _check(self, kind: str, value: str) -> None:
        spec = self.specs().get(kind)
        if spec is None:
            raise InvalidRequest(f"{kind!r} cannot be given a name.")
        if spec.find(value) != [value]:
            raise InvalidRequest(f"{value!r} is not a valid {spec.label}.")

    def refill(self, kind: str, value: str) -> int:
        """From again on the files that carry the ID, after it became the owner's own (a
        sender its name gave is taken back) or stopped being so. Returns how many files
        changed."""
        with write_tx(self.engine) as conn:
            name = self._name(conn, kind, value)
            # as ``clear``: also the files its name gave that do not carry it now (parked)
            touched = carriers(conn, kind, value) + (given(conn, name) if name else [])
            return fill_senders(conn, touched)

    def _name(self, conn, kind: str, value: str) -> str | None:
        return conn.execute(
            select(identifier_names.c.name).where(
                identifier_names.c.kind == kind, identifier_names.c.value == value
            )
        ).scalar()

    def _spelled(self, conn, kind: str, value: str, name: str) -> str:
        """``name`` as another named ID or a sender the owner set already spells it, so
        "elisa oyj" does not become a second "Elisa Oyj". Not this ID's own name, so a
        change of case is kept."""
        others = conn.execute(
            select(identifier_names.c.name).where(
                (identifier_names.c.kind != kind) | (identifier_names.c.value != value)
            )
        ).scalars()
        owners = conn.execute(
            select(file_assignments.c.sender).where(
                file_assignments.c.sender.is_not(None), file_assignments.c.set_by == OWNER
            )
        ).scalars()
        want = name.casefold()
        return next((n for n in [*others, *owners] if n.casefold() == want), name)

    def name_of(self, kind: str, value: str) -> str | None:
        """The owner's name for the ID, else None."""
        with self.engine.connect() as conn:
            return self._name(conn, kind, value)

    def confirm(self, kind: str, value: str, name: str) -> int:
        """The owner names the ID: From becomes ``name`` on every live file that carries
        it, where the owner has not set From or For, and follows a changed name on the
        files the old one gave. Returns how many files changed."""
        self._check(kind, value)
        if value in packs.active().own_ids:
            raise InvalidRequest(f"{value} is marked as yours, so it names no sender.")
        clean = check_sender(name)
        # all in one write: a file the identifiers pass saves meanwhile is either a carrier
        # here or reads the name when it saves
        with write_tx(self.engine) as conn:
            old = self._name(conn, kind, value)
            clean = self._spelled(conn, kind, value, clean)
            touched = carriers(conn, kind, value) + (given(conn, old) if old else [])
            stmt = sqlite_insert(identifier_names).values(
                kind=kind, value=value, name=clean, set_by=OWNER, set_at=time.time()
            )
            conn.execute(
                stmt.on_conflict_do_update(
                    index_elements=["kind", "value"],
                    set_={c: stmt.excluded[c] for c in ("name", "set_by", "set_at")},
                )
            )
            return fill_senders(conn, touched, forget=old)

    def clear(self, kind: str, value: str) -> int:
        """Forget the owner's name for the ID: the senders it gave are taken back (or
        follow another named ID on the same file), also on files that no longer carry it.
        Returns how many files changed."""
        self._check(kind, value)
        with write_tx(self.engine) as conn:
            old = self._name(conn, kind, value)
            if old is None:
                return 0
            touched = carriers(conn, kind, value) + given(conn, old)
            conn.execute(
                identifier_names.delete().where(
                    identifier_names.c.kind == kind, identifier_names.c.value == value
                )
            )
            return fill_senders(conn, touched, forget=old)
