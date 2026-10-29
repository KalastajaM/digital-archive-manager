"""The address area of one document, as the owner drew it: used for that document instead
of the archive's area and a rule's. ``NONE``: the document has no address area, so nobody
is looked for on it. No row: the general area applies."""

import time
from typing import Literal

from sqlalchemy import Engine, delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from dam.db.engine import write_tx
from dam.db.tables import file_address_zones as t

Box = tuple[float, float, float, float]
NONE: Literal["none"] = "none"
DocumentZone = Box | Literal["none"]


def _zone(row) -> DocumentZone:
    sides = (row.x0, row.y0, row.x1, row.y1)
    return NONE if any(v is None for v in sides) else sides


class AddressAreas:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def of(self, drive_id: str) -> DocumentZone | None:
        """The document's own area, ``NONE``, or None when the general area applies."""
        with self.engine.connect() as conn:
            row = conn.execute(select(t).where(t.c.drive_id == drive_id)).first()
        return None if row is None else _zone(row)

    def all(self) -> dict[str, DocumentZone]:
        with self.engine.connect() as conn:
            return {row.drive_id: _zone(row) for row in conn.execute(select(t))}

    def set(self, drive_id: str, zone: DocumentZone) -> None:
        sides = (None,) * 4 if zone == NONE else zone
        values = dict(zip(("x0", "y0", "x1", "y1"), sides, strict=True), set_at=time.time())
        stmt = sqlite_insert(t).values(drive_id=drive_id, **values)
        with write_tx(self.engine) as conn:
            conn.execute(stmt.on_conflict_do_update(index_elements=["drive_id"], set_=values))

    def clear(self, drive_id: str) -> None:
        """The general area applies to the document again."""
        with write_tx(self.engine) as conn:
            conn.execute(delete(t).where(t.c.drive_id == drive_id))
