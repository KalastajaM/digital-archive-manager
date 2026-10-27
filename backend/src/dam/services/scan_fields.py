"""A file's scan fields (``file_fields``): what the inbox review card lists as "Detected
fields", editable per file.

Each field is ``{kind, label, value}``. Until the user changes the list it is the
*detected* one (the suggestion's dates and amounts plus the barcode-aware prefill, built
by ``detected_of``). Saving a list replaces the detected one for that file (a snapshot:
later rule or text changes do not touch it); deleting the row is "Reset to detected".
The *effective* list (saved, else detected) drives the tray-field prefill
(``prefill_from``).
"""

import json
import time
from collections.abc import Callable, Collection
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine, delete, select
from sqlalchemy.dialects.sqlite import insert

from dam.db.engine import write_tx
from dam.db.tables import file_fields
from dam.errors import InvalidRequest
from dam.rules.engine import Suggestion
from dam.trays.model import FIELD_TYPES

# field kind -> the tray field type that parses and normalises its value
KINDS = {
    "doc_date": "date",
    "due_date": "date",
    "date": "date",
    "total": "money",
    "amount": "money",
    "iban": "iban",
    "reference": "reference",
    "payee": "text",
    "custom": "text",
}
SINGLE = ("doc_date", "due_date", "total", "iban", "reference", "payee")  # at most once
PREFILLS = ("due_date", "total", "iban", "reference", "payee")  # kinds that fill tray fields
MAX_FIELDS = 50
LABEL_CHARS = 60
VALUE_CHARS = 200


def check_fields(raw: Any) -> list[dict[str, str | None]]:
    """The list as stored: every field's value normalised for its kind. ``InvalidRequest``
    for an unknown kind, a missing or misplaced label, a bad value, a second value of a
    single-valued kind or more than ``MAX_FIELDS`` fields."""
    if not isinstance(raw, list) or len(raw) > MAX_FIELDS:
        raise InvalidRequest(f"At most {MAX_FIELDS} fields")
    out: list[dict[str, str | None]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise InvalidRequest("A field is {kind, label, value}")
        kind, label, value = item.get("kind"), item.get("label"), item.get("value")
        if not isinstance(kind, str) or kind not in KINDS:
            raise InvalidRequest(f"unknown field kind {kind!r}")
        if kind == "custom":
            label = label.strip() if isinstance(label, str) else ""
            if not label or len(label) > LABEL_CHARS:
                raise InvalidRequest(
                    f"A custom field needs a label of 1 to {LABEL_CHARS} characters"
                )
        elif label is not None:
            raise InvalidRequest(f"A {kind} field has no label")
        if not isinstance(value, str) or not value.strip() or len(value) > VALUE_CHARS:
            raise InvalidRequest(f"A field value must be 1 to {VALUE_CHARS} characters")
        ftype = FIELD_TYPES[KINDS[kind]]
        try:
            normal = ftype.dump(ftype.parse(value))
        except ValueError as e:
            raise InvalidRequest(f"{kind.replace('_', ' ')}: {e}") from e
        out.append({"kind": kind, "label": label, "value": str(normal)})
    for kind in SINGLE:
        if sum(f["kind"] == kind for f in out) > 1:
            raise InvalidRequest(f"At most one {kind.replace('_', ' ')} field")
    return out


def detected_of(found: Suggestion, prefill: dict[str, str]) -> list[dict[str, str | None]]:
    """The detected list: the suggestion's document date, the prefill's due date, total,
    IBAN, reference and payee, then the other dates and amounts found in the text."""
    out: list[dict[str, str | None]] = []

    def add(kind: str, value: str | None) -> None:
        if value:
            out.append({"kind": kind, "label": None, "value": value})

    doc_date = found.doc_date.isoformat() if found.doc_date else None
    add("doc_date", doc_date)
    for kind in PREFILLS:
        add(kind, prefill.get(kind))
    taken = {doc_date, prefill.get("due_date")}
    for d in found.fields.dates:
        if d.isoformat() not in taken:
            add("date", d.isoformat())
    for amount in found.fields.amounts:
        if str(amount.quantize(Decimal("0.01"))) != prefill.get("total"):
            add("amount", str(amount.quantize(Decimal("0.01"))))
    return out


def prefill_from(fields: list[dict[str, str | None]]) -> dict[str, str]:
    """Tray-field prefills (``FieldDef.prefill`` keys) from a list; only the ones present."""
    return {str(f["kind"]): str(f["value"]) for f in fields if f["kind"] in PREFILLS}


class ScanFieldService:
    def __init__(
        self, engine: Engine, detected: Callable[[str], list[dict[str, str | None]]]
    ) -> None:
        self.engine = engine
        # the detected list of a file (``InboxService.detected_fields``)
        self._detected = detected

    def saved(self, drive_id: str) -> list[dict[str, str | None]] | None:
        """The file's saved list, None if the user never changed it."""
        return self.saved_for([drive_id]).get(drive_id)

    def saved_for(self, drive_ids: Collection[str]) -> dict[str, list[dict[str, str | None]]]:
        """``saved`` for many files in one query (files the user never changed are left
        out)."""
        ids = list(drive_ids)
        out: dict[str, list[dict[str, str | None]]] = {}
        with self.engine.connect() as conn:
            for start in range(0, len(ids), 500):
                rows = conn.execute(
                    select(file_fields.c.drive_id, file_fields.c.fields).where(
                        file_fields.c.drive_id.in_(ids[start : start + 500])
                    )
                ).all()
                out.update((r.drive_id, json.loads(r.fields)) for r in rows if r.fields is not None)
        return out

    def get(self, drive_id: str) -> dict[str, Any]:
        """``{fields, edited}``: the effective list and whether it is a saved one."""
        saved = self.saved(drive_id)
        if saved is None:
            return {"fields": self._detected(drive_id), "edited": False}
        return {"fields": saved, "edited": True}

    def put(self, drive_id: str, fields: Any) -> dict[str, Any]:
        """Save the list (replacing the detected one) after checking it."""
        checked = check_fields(fields)
        stmt = insert(file_fields).values(
            drive_id=drive_id, fields=json.dumps(checked), updated=time.time()
        )
        with write_tx(self.engine) as conn:
            conn.execute(
                stmt.on_conflict_do_update(
                    index_elements=["drive_id"],
                    set_={"fields": stmt.excluded.fields, "updated": stmt.excluded.updated},
                )
            )
        return {"fields": checked, "edited": True}

    def delete(self, drive_id: str) -> dict[str, Any]:
        """Forget the saved list: the detected one is the file's again."""
        with write_tx(self.engine) as conn:
            conn.execute(delete(file_fields).where(file_fields.c.drive_id == drive_id))
        return self.get(drive_id)
