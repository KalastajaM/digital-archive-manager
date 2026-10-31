"""Tray schema, field types and loading from ``config/trays/*.yaml``.

A tray file is one YAML *mapping*::

    id: to-pay
    name: To pay
    order: 1
    fields:
      due_date: { type: date, required: true, prefill: due_date }
    date_field: due_date
    done: { label: Mark paid, fields: { paid_on: { type: date, default: today } } }
"""

import re
import string
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal, Protocol

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    ValidationError,
    field_validator,
    model_validator,
)

from dam.checks import valid_iban
from dam.rules.engine import TemplateError, check_template
from dam.rules.model import TOO_DEEP_MESSAGE, RuleError, read_yaml

# --- field types -------------------------------------------------------------------


class FieldType(Protocol):
    def parse(self, raw: object) -> object:
        """Turn user/JSON input into the field's value; raise ``ValueError`` if invalid."""
        ...

    def dump(self, value) -> object:
        """The JSON-able form stored in the DB (``parse(dump(v)) == v``)."""
        ...


class _Text:
    def parse(self, raw: object) -> str:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("expected text")
        return raw.strip()

    def dump(self, value: str) -> str:
        return value


_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)


class _Date:
    def parse(self, raw: object) -> date:
        if isinstance(raw, date) and not hasattr(raw, "hour"):
            return raw
        if isinstance(raw, str) and _ISO_DATE.fullmatch(raw.strip()):
            return date.fromisoformat(raw.strip())
        raise ValueError("expected a date (YYYY-MM-DD)")

    def dump(self, value: date) -> str:
        return value.isoformat()


_CENT = Decimal("0.01")
_MAX_MONEY = Decimal("1e12")
_MONEY_TEXT = re.compile(r"-?[0-9][0-9., ]*", re.ASCII)
_GROUPED = re.compile(r"[0-9]{1,3}(?:[^0-9][0-9]{3})*", re.ASCII)


def _money_from_text(raw: str) -> Decimal:
    """``"84,20"``, ``"84.20"``, ``"1 234,50"``, ``"1.234,50"``, ``"1,234.50"``, ``"84,20 €"``.

    With both ``,`` and ``.`` the last one is the decimal mark; a single mark used once is
    the decimal mark; used several times it groups thousands (groups must be 3 digits).
    A mark used once before exactly three digits (``"1,000"``, ``"2.500"``) could be
    either, so it is refused rather than guessed; more than two decimals are refused too.
    """
    s = re.sub(r"\s+", " ", raw).strip().removesuffix("€").removeprefix("€").strip()
    if not _MONEY_TEXT.fullmatch(s):
        raise ValueError("expected an amount")
    sign, s = ("-", s[1:]) if s.startswith("-") else ("", s)
    marks = {c for c in s if c in ",."}
    if len(marks) == 2:
        decimal_mark = "," if s.rfind(",") > s.rfind(".") else "."
    elif len(marks) == 1:
        mark = next(iter(marks))
        decimal_mark = mark if s.count(mark) == 1 else ""
    else:
        decimal_mark = ""
    whole, _, cents = s.rpartition(decimal_mark) if decimal_mark else (s, "", "")
    if decimal_mark and not cents.isdigit():
        raise ValueError("expected an amount")
    if len(marks) == 1 and decimal_mark and len(cents) == 3:
        raise ValueError(f"ambiguous amount {raw.strip()!r}: write 1000,00 or 1,00")
    if len(cents) > 2:
        raise ValueError("an amount has at most two decimals")
    separators = {c for c in whole if not c.isdigit()}
    if len(separators) > 1 or (separators and not _GROUPED.fullmatch(whole)):
        raise ValueError("expected an amount")
    digits = "".join(c for c in whole if c.isdigit())
    return Decimal(f"{sign}{digits}.{cents or '0'}")


class _Money:
    """EUR amount as ``Decimal`` with two decimals; stored as a ``"1234.50"`` string.

    Negative amounts are allowed (credit notes, refunds); ``-0`` becomes ``0.00``.
    """

    def parse(self, raw: object) -> Decimal:
        if isinstance(raw, bool) or not isinstance(raw, int | Decimal | str):
            raise ValueError("expected an amount")
        try:
            value = _money_from_text(raw) if isinstance(raw, str) else Decimal(raw)
            if not value.is_finite() or abs(value) >= _MAX_MONEY:
                raise ValueError("amount out of range")
            cents = value.quantize(_CENT)
        except InvalidOperation as e:
            raise ValueError("expected an amount") from e
        if cents != value:
            raise ValueError("an amount has at most two decimals")
        return cents.copy_abs() if cents.is_zero() else cents

    def dump(self, value: Decimal) -> str:
        return str(value.quantize(_CENT))


_IBAN_SHAPE = re.compile(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}", re.ASCII)


class _Iban:
    def parse(self, raw: object) -> str:
        if not isinstance(raw, str):
            raise ValueError("expected an IBAN")
        compact = "".join(raw.split()).upper()
        if not _IBAN_SHAPE.fullmatch(compact) or not valid_iban(compact):
            raise ValueError("not a valid IBAN")
        return compact

    def dump(self, value: str) -> str:
        return value


_REFERENCE = re.compile(r"[A-Z0-9]{1,35}", re.ASCII)


class _Reference:
    """Payment reference (RF or domestic), stored without spaces."""

    def parse(self, raw: object) -> str:
        if not isinstance(raw, str):
            raise ValueError("expected a reference")
        compact = "".join(raw.split()).upper()
        if not _REFERENCE.fullmatch(compact):
            raise ValueError("a reference has only letters and digits")
        return compact

    def dump(self, value: str) -> str:
        return value


class _Checkbox:
    def parse(self, raw: object) -> bool:
        if not isinstance(raw, bool):
            raise ValueError("expected true or false")
        return raw

    def dump(self, value: bool) -> bool:
        return value


class _Choice:
    """One of the field's ``options``. The type alone has no options: ``FieldDef.parse``
    does the membership check."""

    def parse(self, raw: object) -> str:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("expected one of the options")
        return raw.strip()

    def dump(self, value: str) -> str:
        return value


class _Days:
    """A non-negative whole number of days, from an int or a string of digits."""

    def parse(self, raw: object) -> int:
        if isinstance(raw, bool):
            raise ValueError("expected a number of days")
        if isinstance(raw, int):
            value = raw
        elif isinstance(raw, str) and raw.strip().isascii() and raw.strip().isdigit():
            value = int(raw.strip())
        else:
            raise ValueError("expected a number of days")
        if value < 0 or value > _MAX_DAYS:
            raise ValueError("expected a number of days")
        return value

    def dump(self, value: int) -> int:
        return value


_MAX_DAYS = 36500

FIELD_TYPES: dict[str, FieldType] = {
    "text": _Text(),
    "date": _Date(),
    "money": _Money(),
    "iban": _Iban(),
    "reference": _Reference(),
    "checkbox": _Checkbox(),
    "choice": _Choice(),
    "days": _Days(),
}

# The field type each Phase 1 ``detect_fields`` value fits.
# ``payee`` comes from a rule's ``then.payee``, not from the text.
_PREFILL_TYPES = {
    "due_date": "date",
    "total": "money",
    "iban": "iban",
    "reference": "reference",
    "payee": "text",
}

# --- schema ------------------------------------------------------------------------

_FIELD_NAME = re.compile(r"[a-z][a-z0-9_]*", re.ASCII)
_TITLE_KEYS = frozenset({"name", "date"})


class FieldDef(BaseModel):
    # ``copy`` (show a copy button) would shadow ``BaseModel.copy``: the attribute is
    # ``copyable``, the YAML/JSON key stays ``copy``.
    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    type: str
    required: bool = False
    prefill: Literal["due_date", "total", "iban", "reference", "payee"] | None = None
    copyable: bool = Field(default=False, alias="copy")
    default: Literal["today"] | None = None
    options: list[str] | None = None

    @field_validator("type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        if value not in FIELD_TYPES:
            raise ValueError(f"unknown field type {value!r} (known: {', '.join(FIELD_TYPES)})")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> "FieldDef":
        if self.type == "choice":
            if not self.options or any(not o.strip() for o in self.options):
                raise ValueError("a choice field needs options")
            if len(set(self.options)) != len(self.options):
                raise ValueError("options must be distinct")
        elif self.options is not None:
            raise ValueError("options only belong on a choice field")
        if self.default == "today" and self.type != "date":
            raise ValueError("default 'today' needs a date field")
        if self.prefill is not None and _PREFILL_TYPES[self.prefill] != self.type:
            raise ValueError(
                f"prefill {self.prefill!r} needs a {_PREFILL_TYPES[self.prefill]} field"
            )
        return self

    def parse(self, raw: object) -> object:
        """The field type's ``parse``, plus the options check for a ``choice``."""
        value = FIELD_TYPES[self.type].parse(raw)
        if self.type == "choice" and value not in (self.options or []):
            raise ValueError(f"expected one of: {', '.join(self.options or [])}")
        return value


def _check_field_names(fields: dict[str, FieldDef]) -> dict[str, FieldDef]:
    for name in fields:
        if not _FIELD_NAME.fullmatch(name):
            raise ValueError(f"field name {name!r}: use lowercase letters, digits and _")
    return fields


class DoneDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(default="Done", min_length=1)
    fields: dict[str, FieldDef] = Field(default_factory=dict)

    @field_validator("fields", mode="before")
    @classmethod
    def _null_means_empty(cls, value):
        return {} if value is None else value

    @field_validator("fields")
    @classmethod
    def _field_names(cls, fields: dict[str, FieldDef]) -> dict[str, FieldDef]:
        return _check_field_names(fields)


class ReminderRule(BaseModel):
    """Exactly one of ``days_before: N`` (N days before the date), ``overdue: true`` or
    ``lead: true`` (the item's own lead time, see ``LeadDef``)."""

    model_config = ConfigDict(extra="forbid")

    days_before: NonNegativeInt | None = None
    overdue: Literal[True] | None = None
    lead: Literal[True] | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "ReminderRule":
        chosen = [v for v in (self.days_before, self.overdue, self.lead) if v is not None]
        if len(chosen) != 1:
            raise ValueError("a reminder is days_before: N, overdue: true or lead: true")
        return self


class LeadDef(BaseModel):
    """How long before the date an item is due for attention: its own ``days`` field if
    set, else ``days[<its kind>]``, else ``default``."""

    model_config = ConfigDict(extra="forbid")

    field: str
    by: str
    days: dict[str, NonNegativeInt] = Field(default_factory=dict)
    default: NonNegativeInt = 30

    @field_validator("days", mode="before")
    @classmethod
    def _null_means_empty(cls, value):
        return {} if value is None else value


class RenewDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(default="Renewed", min_length=1)


class SummaryDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sum: str


class TrayDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1)
    order: int
    item_title: str = "{name}"
    fields: dict[str, FieldDef] = Field(default_factory=dict)
    date_field: str | None = None
    done: DoneDef = Field(default_factory=DoneDef)
    reminders: list[ReminderRule] = Field(default_factory=list)
    nudge_after_days: PositiveInt | None = None
    summary: SummaryDef | None = None
    lead: LeadDef | None = None
    renew: RenewDef | None = None

    @field_validator("fields", "done", "reminders", mode="before")
    @classmethod
    def _null_means_empty(cls, value, info):
        if value is None:
            return [] if info.field_name == "reminders" else {}
        return value

    @field_validator("fields")
    @classmethod
    def _field_names(cls, fields: dict[str, FieldDef]) -> dict[str, FieldDef]:
        return _check_field_names(fields)

    @field_validator("item_title")
    @classmethod
    def _safe_title(cls, value: str) -> str:
        try:
            check_template(value, _TITLE_KEYS)
        except TemplateError as e:
            raise ValueError(f"item_title: {e}") from e
        return value

    @model_validator(mode="after")
    def _cross_checks(self) -> "TrayDef":
        if self.date_field is not None:
            f = self.fields.get(self.date_field)
            if f is None or f.type != "date":
                raise ValueError(f"date_field {self.date_field!r} must name a date field")
        if self.reminders and self.date_field is None:
            raise ValueError("reminders need a date_field")
        if self.renew is not None and self.date_field is None:
            raise ValueError("renew needs a date_field")
        if any(r.lead for r in self.reminders) and self.lead is None:
            raise ValueError("a lead reminder needs a lead block")
        if self.lead is not None:
            days_field = self.fields.get(self.lead.field)
            if days_field is None or days_field.type != "days":
                raise ValueError(f"lead field {self.lead.field!r} must name a days field")
            by = self.fields.get(self.lead.by)
            if by is None or by.type != "choice":
                raise ValueError(f"lead by {self.lead.by!r} must name a choice field")
            unknown = [k for k in self.lead.days if k not in (by.options or [])]
            if unknown:
                raise ValueError(f"lead days {unknown[0]!r} is not an option of {self.lead.by!r}")
        placeholders = {f for _, f, _, _ in string.Formatter().parse(self.item_title) if f}
        if self.date_field is None and "date" in placeholders:
            raise ValueError("item_title uses {date} but the tray has no date_field")
        if self.summary is not None:
            f = self.fields.get(self.summary.sum)
            if f is None or f.type != "money":
                raise ValueError(f"summary sum {self.summary.sum!r} must name a money field")
        return self


def lead_days_of(tray: TrayDef, values: dict[str, object]) -> int | None:
    """The item's lead time in days, or ``None`` when the tray has no ``lead`` block."""
    lead = tray.lead
    if lead is None:
        return None
    own = values.get(lead.field)
    if own is not None:
        return int(own)  # type: ignore[call-overload]
    kind = values.get(lead.by)
    if isinstance(kind, str) and kind in lead.days:
        return lead.days[kind]
    return lead.default


# --- loading -----------------------------------------------------------------------


def _line_of(node: yaml.Node, loc: tuple) -> int:
    """The YAML line (1-based) of the deepest node that ``loc`` reaches."""
    for part in loc:
        child = None
        if isinstance(node, yaml.MappingNode) and isinstance(part, str):
            child = next((v for k, v in node.value if k.value == part), None)
        elif isinstance(node, yaml.SequenceNode) and isinstance(part, int):
            child = node.value[part] if 0 <= part < len(node.value) else None
        if child is None:
            break
        node = child
    return node.start_mark.line + 1


def _load_file(path: Path) -> TrayDef:
    """Parse one tray file; raise ``ValueError`` with a readable message on any problem."""
    node, data = read_yaml(path)
    return _validate(node, data)


def load_tray_text(text: str) -> TrayDef:
    """Parse a tray file's text exactly as ``load_trays`` would parse the file; raise
    ``ValueError`` with a readable message on any problem."""
    loader = yaml.SafeLoader(text)
    try:
        node = loader.get_single_node()
        data = loader.construct_document(node) if node is not None else None
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f"line {mark.line + 1}: " if mark else ""
        raise ValueError(f"{where}invalid YAML: {getattr(e, 'problem', None) or e}") from e
    except (RecursionError, MemoryError) as e:
        raise ValueError(TOO_DEEP_MESSAGE) from e
    finally:
        loader.dispose()
    return _validate(node, data)


def _validate(node: yaml.Node | None, data: object) -> TrayDef:
    if not isinstance(data, dict):
        raise ValueError("top level must be a mapping (one tray per file)")
    try:
        return TrayDef.model_validate(data)
    except ValidationError as e:
        problems = []
        for err in e.errors():
            # Errors raised in model validators carry no loc: point at the tray itself.
            loc = tuple(p for p in err["loc"] if not str(p).startswith("function-"))
            label = ".".join(str(p) for p in loc) or "tray"
            problems.append(f"line {_line_of(node, loc)}: {label}: {err['msg']}")
        raise ValueError("file skipped: " + "; ".join(problems)) from e


def load_trays(trays_dir: Path) -> tuple[list[TrayDef], list[RuleError]]:
    """Load ``*.yaml``/``*.yml`` (name order), sorted by ``order``; bad files reported."""
    trays: list[TrayDef] = []
    errors: list[RuleError] = []
    trays_dir = Path(trays_dir)
    if not trays_dir.is_dir():
        return trays, errors
    paths = sorted(
        (p for p in trays_dir.iterdir() if p.suffix.lower() in (".yaml", ".yml") and p.is_file()),
        key=lambda p: p.name,
    )
    owner: dict[str, str] = {}
    for path in paths:
        try:
            tray = _load_file(path)
            if tray.id in owner:
                raise ValueError(
                    f"file skipped: duplicate id {tray.id!r} (first defined in {owner[tray.id]})"
                )
        except ValueError as e:
            errors.append(RuleError(file=path.name, message=str(e)))
            continue
        except (RecursionError, MemoryError):  # e.g. validating absurdly nested data
            errors.append(RuleError(file=path.name, message=TOO_DEEP_MESSAGE))
            continue
        owner[tray.id] = path.name
        trays.append(tray)
    trays.sort(key=lambda t: (t.order, t.id))
    return trays, errors
