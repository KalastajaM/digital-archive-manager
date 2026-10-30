"""From (``file_assignments.sender``) filled from the owner's names for identifiers
(``identifier_names``): a file whose current content carries named identifiers that all
name the same sender gets that sender, with ``set_by`` "filing". A row the owner set is
never touched; a sender is only taken back when it is one a name gave."""

import time
from collections.abc import Iterable

from sqlalchemy import Connection, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from dam import packs
from dam.db.tables import file_assignments, file_identifiers, files, identifier_names
from dam.index.repo.model import chunks

OWNER = "owner"  # as ``services.assignments``
FILING = "filing"


def _active_kinds() -> list[str]:
    return [s.kind for p in packs.active().countries for s in p.identifiers]


def carriers(conn: Connection, kind: str, value: str) -> list[str]:
    """The live files (not missing, not parked) whose current content carries the value."""
    return list(
        conn.execute(
            select(file_identifiers.c.drive_id)
            .join(files, files.c.drive_id == file_identifiers.c.drive_id)
            .where(
                file_identifiers.c.kind == kind,
                file_identifiers.c.value == value,
                files.c.sha256 == file_identifiers.c.sha256,
                files.c.missing.is_not(True),
                files.c.parked_at.is_(None),
            )
        ).scalars()
    )


def given(conn: Connection, name: str) -> list[str]:
    """The files whose From is ``name`` (case ignored) and not the owner's word: those a
    name gave, wherever they are now."""
    want = name.casefold()
    rows = conn.execute(
        select(file_assignments.c.drive_id, file_assignments.c.sender).where(
            file_assignments.c.sender.is_not(None), file_assignments.c.set_by != OWNER
        )
    ).all()
    return [r.drive_id for r in rows if r.sender.casefold() == want]


def _named_senders(conn: Connection, drive_ids: list[str]) -> dict[str, list[str]]:
    """drive_id -> the names of the named identifiers its current content carries, of the
    enabled countries; not the owner's own business IDs."""
    rows = conn.execute(
        select(file_identifiers.c.drive_id, identifier_names.c.name)
        .join(files, files.c.drive_id == file_identifiers.c.drive_id)
        .join(
            identifier_names,
            (identifier_names.c.kind == file_identifiers.c.kind)
            & (identifier_names.c.value == file_identifiers.c.value),
        )
        .where(
            file_identifiers.c.drive_id.in_(drive_ids),
            files.c.sha256 == file_identifiers.c.sha256,
            identifier_names.c.kind.in_(_active_kinds()),
            identifier_names.c.value.not_in(packs.active().own_ids),
        )
        .order_by(identifier_names.c.kind, identifier_names.c.value)
    ).all()
    out: dict[str, list[str]] = {}
    for r in rows:
        out.setdefault(r.drive_id, []).append(r.name)
    return out


def fill_senders(conn: Connection, drive_ids: Iterable[str], forget: str | None = None) -> int:
    """Give each file the sender its named identifiers agree on; take back a sender a name
    gave when they no longer do (``forget``: a name just cleared or changed). Returns how
    many files changed."""
    named = {n.casefold() for n in conn.execute(select(identifier_names.c.name)).scalars()}
    if forget:
        named.add(forget.casefold())
    now = time.time()
    changed = 0
    for part in chunks(list(dict.fromkeys(drive_ids)), 500):
        want_by = _named_senders(conn, part)
        rows = {
            r.drive_id: r
            for r in conn.execute(
                select(file_assignments).where(file_assignments.c.drive_id.in_(part))
            ).all()
        }
        for drive_id in part:
            row = rows.get(drive_id)
            if row is not None and row.set_by == OWNER:
                continue
            spelled = {n.casefold(): n for n in reversed(want_by.get(drive_id, []))}
            want = next(iter(spelled.values())) if len(spelled) == 1 else None
            have = row.sender if row is not None else None
            if want is not None:
                if have == want:
                    continue
                stmt = sqlite_insert(file_assignments).values(
                    drive_id=drive_id,
                    sender=want,
                    person=row.person if row is not None else None,
                    set_by=FILING,
                    set_at=now,
                )
                conn.execute(
                    stmt.on_conflict_do_update(
                        index_elements=["drive_id"],
                        set_={"sender": want, "set_by": FILING, "set_at": now},
                    )
                )
            elif row is not None and have is not None and have.casefold() in named:
                if row.person is None:
                    conn.execute(
                        file_assignments.delete().where(file_assignments.c.drive_id == drive_id)
                    )
                else:
                    conn.execute(
                        file_assignments.update()
                        .where(file_assignments.c.drive_id == drive_id)
                        .values(sender=None, set_at=now)
                    )
            else:
                continue
            changed += 1
    return changed
