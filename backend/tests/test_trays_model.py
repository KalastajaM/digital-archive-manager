from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from dam.trays.model import FIELD_TYPES, TrayDef, lead_days_of, load_trays

DEFAULTS = Path(__file__).resolve().parents[2] / "defaults" / "trays"


def tray(**overrides) -> TrayDef:
    data = {"id": "t", "name": "T", "order": 1} | overrides
    return TrayDef.model_validate(data)


def test_defaults_load_without_errors():
    trays, errors = load_trays(DEFAULTS)
    assert errors == []
    assert [t.id for t in trays] == ["to-pay", "to-action", "to-read", "follow-up", "renew"]
    pay, action, read, follow, _renew = trays
    assert pay.fields["amount"].prefill == "total"
    assert pay.fields["due_date"].required
    assert pay.fields["iban"].copyable and pay.fields["reference"].copyable
    assert pay.fields["amount"].copyable  # "Copy amount" on Today
    assert pay.fields["iban"].model_dump()["copy"] is True
    assert pay.date_field == "due_date"
    assert pay.done.label == "Mark paid"
    assert pay.done.fields["paid_on"].default == "today"
    assert [(r.days_before, r.overdue) for r in pay.reminders] == [
        (3, None),
        (0, None),
        (None, True),
    ]
    assert pay.summary.sum == "amount"
    assert action.date_field == "action_date"
    assert action.fields["action_date"].required
    assert [r.days_before for r in action.reminders] == [1, 0]
    assert action.done.label == "Done"
    assert read.fields == {} and read.date_field is None
    assert read.nudge_after_days == 30
    assert read.done.label == "Read"
    assert follow.date_field == "check_by" and not follow.fields["check_by"].required
    assert follow.fields["waiting_for"].type == "text"
    assert follow.done.label == "Done" and follow.done.fields == {}
    assert [(r.days_before, r.overdue) for r in follow.reminders] == [(0, None), (None, True)]


def test_bad_yaml_reported_with_line_and_others_load(tmp_path):
    (tmp_path / "10-good.yaml").write_text("id: good\nname: Good\norder: 1\n", encoding="utf-8")
    (tmp_path / "20-bad.yaml").write_text("id: bad\nname: Bad\norder: [1\n", encoding="utf-8")
    trays, errors = load_trays(tmp_path)
    assert [t.id for t in trays] == ["good"]
    assert len(errors) == 1
    assert errors[0].file == "20-bad.yaml"
    assert "line" in errors[0].message


def test_validation_error_reports_line_of_the_bad_key(tmp_path):
    (tmp_path / "t.yaml").write_text(
        "id: t\nname: T\norder: 1\nfields:\n  a: { type: text }\n  b: { type: nope }\n",
        encoding="utf-8",
    )
    trays, errors = load_trays(tmp_path)
    assert trays == []
    assert "line 6" in errors[0].message


def test_trays_sorted_by_order_and_duplicate_id_rejects_later_file(tmp_path):
    (tmp_path / "a.yaml").write_text("id: x\nname: X\norder: 5\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("id: y\nname: Y\norder: 2\n", encoding="utf-8")
    (tmp_path / "c.yaml").write_text("id: x\nname: X again\norder: 1\n", encoding="utf-8")
    trays, errors = load_trays(tmp_path)
    assert [t.id for t in trays] == ["y", "x"]
    assert trays[1].name == "X"
    assert [e.file for e in errors] == ["c.yaml"]
    assert "duplicate id 'x'" in errors[0].message


def test_top_level_must_be_mapping(tmp_path):
    (tmp_path / "t.yaml").write_text("- id: t\n", encoding="utf-8")
    _, errors = load_trays(tmp_path)
    assert "mapping" in errors[0].message


def test_missing_dir_gives_nothing(tmp_path):
    assert load_trays(tmp_path / "nope") == ([], [])


def test_date_field_must_name_a_date_field():
    with pytest.raises(ValidationError, match="date_field"):
        tray(fields={"due": {"type": "text"}}, date_field="due")
    with pytest.raises(ValidationError, match="date_field"):
        tray(date_field="nothing")


def test_title_placeholder_with_attribute_access_rejected():
    with pytest.raises(ValidationError, match="item_title"):
        tray(item_title="{x.y}")
    for bad in ("{name.upper}", "{name[0]}", "{name!r}", "{other}"):
        with pytest.raises(ValidationError):
            tray(item_title=bad)


def test_title_date_placeholder_needs_date_field():
    with pytest.raises(ValidationError, match="date_field"):
        tray(item_title="{name} {date:%d.%m}")
    t = tray(
        item_title="{name} {date:%d.%m}",
        fields={"due": {"type": "date"}},
        date_field="due",
    )
    assert t.item_title == "{name} {date:%d.%m}"


def test_summary_must_name_a_money_field():
    with pytest.raises(ValidationError, match="summary"):
        tray(fields={"a": {"type": "text"}}, summary={"sum": "a"})
    assert tray(fields={"a": {"type": "money"}}, summary={"sum": "a"}).summary.sum == "a"


def test_reminder_needs_exactly_one_kind_and_a_date_field():
    dated = {"fields": {"d": {"type": "date"}}, "date_field": "d"}
    with pytest.raises(ValidationError):
        tray(**dated, reminders=[{"days_before": 1, "overdue": True}])
    with pytest.raises(ValidationError):
        tray(**dated, reminders=[{}])
    with pytest.raises(ValidationError):
        tray(**dated, reminders=[{"days_before": -1}])
    with pytest.raises(ValidationError):
        tray(**dated, reminders=[{"overdue": False}])
    with pytest.raises(ValidationError, match="date_field"):
        tray(reminders=[{"days_before": 1}])
    assert len(tray(**dated, reminders=[{"overdue": True}]).reminders) == 1


def test_unknown_keys_and_types_rejected():
    with pytest.raises(ValidationError):
        tray(colour="red")
    with pytest.raises(ValidationError):
        tray(fields={"a": {"type": "colour"}})
    with pytest.raises(ValidationError):
        tray(fields={"a": {"type": "text", "prefill": "vendor"}})
    with pytest.raises(ValidationError):
        tray(fields={"a": {"type": "text", "default": "today"}})


@pytest.mark.parametrize(
    "raw",
    ["84,20", "84.20", "84.2", 84, Decimal("84.2"), " 84,20 € "],
)
def test_money_parses_common_forms(raw):
    expected = Decimal("84.20") if raw != 84 else Decimal("84.00")
    assert FIELD_TYPES["money"].parse(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [("1 234,50", "1234.50"), ("1.234,50", "1234.50"), ("1,234.50", "1234.50"), ("-5", "-5.00")],
)
def test_money_thousands_separators(raw, expected):
    money = FIELD_TYPES["money"]
    assert money.parse(raw) == Decimal(expected)
    assert money.dump(money.parse(raw)) == expected


@pytest.mark.parametrize("raw", ["abc", "", "1,2,3", "84.205", 84.2, True, "1.23.4,5", "NaN"])
def test_money_rejects_garbage(raw):
    with pytest.raises(ValueError):
        FIELD_TYPES["money"].parse(raw)


def test_other_field_types():
    d = FIELD_TYPES["date"]
    assert d.parse("2026-11-03") == date(2026, 11, 3) == d.parse(date(2026, 11, 3))
    assert d.dump(date(2026, 11, 3)) == "2026-11-03"
    with pytest.raises(ValueError):
        d.parse("3.11.2026x")
    iban = FIELD_TYPES["iban"]
    assert iban.parse("fi21 1234 5600 0007 85") == "FI2112345600000785"
    with pytest.raises(ValueError):
        iban.parse("FI2112345600000786")
    ref = FIELD_TYPES["reference"]
    assert ref.parse(" rf18 5390 0754 7034 ") == "RF18539007547034"
    with pytest.raises(ValueError):
        ref.parse("12-34")
    assert FIELD_TYPES["checkbox"].parse(True) is True
    with pytest.raises(ValueError):
        FIELD_TYPES["checkbox"].parse("yes")
    assert FIELD_TYPES["text"].parse("  hi ") == "hi"
    with pytest.raises(ValueError):
        FIELD_TYPES["text"].parse(5)


@pytest.mark.parametrize("raw", ["1,000", "2.500", "12,300", "-1,000", "84,200"])
def test_money_single_mark_before_three_digits_is_ambiguous(raw):
    with pytest.raises(ValueError, match="ambiguous"):
        FIELD_TYPES["money"].parse(raw)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("84,20", "84.20"),
        ("84.20", "84.20"),
        ("1 234,50", "1234.50"),
        ("1.234,50", "1234.50"),
        ("1.000,00", "1000.00"),
        ("1 000", "1000.00"),
        ("1.000.000", "1000000.00"),
    ],
)
def test_money_unambiguous_forms_accepted(raw, expected):
    assert FIELD_TYPES["money"].parse(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", ["-0", "-0,00", Decimal("-0.00"), "0"])
def test_money_negative_zero_normalised(raw):
    money = FIELD_TYPES["money"]
    assert money.dump(money.parse(raw)) == "0.00"


def test_negative_amounts_allowed():
    assert FIELD_TYPES["money"].dump(FIELD_TYPES["money"].parse("-12,50")) == "-12.50"


def test_escaped_braces_are_not_a_date_placeholder():
    assert tray(item_title="{name} {{date}}").item_title == "{name} {{date}}"


def test_deeply_nested_yaml_reported_and_siblings_load(tmp_path):
    (tmp_path / "10-deep.yaml").write_text(
        "id: d\nname: D\norder: 1\nx: " + "[" * 20000, encoding="utf-8"
    )
    (tmp_path / "20-good.yaml").write_text("id: good\nname: Good\norder: 1\n", encoding="utf-8")
    trays, errors = load_trays(tmp_path)
    assert [t.id for t in trays] == ["good"]
    assert [e.file for e in errors] == ["10-deep.yaml"]


def test_oversized_tray_file_skipped_before_parsing(tmp_path):
    (tmp_path / "big.yaml").write_text(
        "id: b\nname: B\norder: 1\n# " + "x" * 300_000 + "\n", encoding="utf-8"
    )
    trays, errors = load_trays(tmp_path)
    assert trays == []
    assert "too large" in errors[0].message


def shipped(tray_id: str) -> TrayDef:
    trays, _ = load_trays(DEFAULTS)
    return next(t for t in trays if t.id == tray_id)


def write_tray(tmp_path, body: str) -> tuple[list[TrayDef], list]:
    (tmp_path / "t.yaml").write_text("id: t\nname: T\norder: 1\n" + body, encoding="utf-8")
    return load_trays(tmp_path)


def test_shipped_trays_include_renew():
    trays, errors = load_trays(DEFAULTS)
    assert errors == []
    assert [t.id for t in trays] == ["to-pay", "to-action", "to-read", "follow-up", "renew"]
    renew = next(t for t in trays if t.id == "renew")
    assert renew.renew.label == "Renewed"
    assert renew.fields["kind"].options[0] == "Passport"
    assert renew.lead.days["Passport"] == 180


def test_choice_refuses_unknown_option():
    field = tray(fields={"k": {"type": "choice", "options": ["A", "B"]}}).fields["k"]
    assert field.parse("A") == "A"
    with pytest.raises(ValueError):
        field.parse("C")


def test_choice_needs_options():
    with pytest.raises(ValidationError):
        tray(fields={"k": {"type": "choice"}})


def test_days_accepts_int_or_digits_and_dumps_int():
    days = FIELD_TYPES["days"]
    assert days.parse(90) == 90 and days.parse(" 90 ") == 90
    assert days.dump(days.parse("90")) == 90
    for bad in (-1, "-1", "1.5", "abc", True, None):
        with pytest.raises(ValueError):
            days.parse(bad)


def test_options_only_on_choice(tmp_path):
    _, errors = write_tray(tmp_path, "fields:\n  a: { type: text, options: [x] }\n")
    assert len(errors) == 1 and "options" in errors[0].message and "fields.a" in errors[0].message


def test_lead_reminder_needs_lead_block(tmp_path):
    body = "fields:\n  d: { type: date }\ndate_field: d\nreminders:\n  - { lead: true }\n"
    _, errors = write_tray(tmp_path, body)
    assert len(errors) == 1 and "lead" in errors[0].message


def test_lead_days_keys_must_be_options(tmp_path):
    body = (
        "fields:\n  d: { type: date }\n  k: { type: choice, options: [A] }\n"
        "  n: { type: days }\ndate_field: d\n"
        "lead: { field: n, by: k, days: { Boat: 10 } }\n"
    )
    _, errors = write_tray(tmp_path, body)
    assert len(errors) == 1 and "Boat" in errors[0].message


def test_renew_needs_date_field(tmp_path):
    _, errors = write_tray(tmp_path, "renew: {}\n")
    assert len(errors) == 1 and "date_field" in errors[0].message


def test_lead_days_of():
    renew = shipped("renew")
    assert lead_days_of(renew, {"kind": "Passport"}) == 180
    assert lead_days_of(renew, {"kind": "Passport", "lead_days": 400}) == 400
    assert lead_days_of(renew, {}) == 30
    assert lead_days_of(shipped("to-pay"), {}) is None


def test_lead_days_of_ignores_an_own_value_that_is_not_an_int():
    renew = shipped("renew")
    assert lead_days_of(renew, {"kind": "Passport", "lead_days": "soon"}) == 180
    assert lead_days_of(renew, {"kind": "Passport", "lead_days": True}) == 180
