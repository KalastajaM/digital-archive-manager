"""Tray guesses for inbox documents (no AI): a rule's ``then.tray``, else the To pay
heuristic (due date + amount + IBAN or reference)."""

from datetime import date
from decimal import Decimal

import pytest

from dam.index.repo import FileRecord
from dam.rules.engine import suggest
from dam.rules.fields import DetectedFields
from dam.rules.guess import guess_tray
from dam.rules.model import Rule

TRAYS = ("to-pay", "to-action", "to-read")
DUE = date(2026, 11, 15)
TOTAL = Decimal("84.20")
IBAN = "FI2112345600000785"
REF = "RF18539007547034"


def found(**kw) -> DetectedFields:
    return DetectedFields(**kw)


@pytest.mark.parametrize(
    "fields",
    [
        {"due_date": DUE, "total": TOTAL, "iban": IBAN},
        {"due_date": DUE, "total": TOTAL, "reference": REF},
        {"due_date": DUE, "total": TOTAL, "iban": IBAN, "reference": REF},
    ],
)
def test_heuristic_guesses_to_pay(fields):
    assert guess_tray(found(**fields), None, TRAYS) == "to-pay"


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"due_date": DUE, "total": TOTAL},  # no IBAN, no reference
        {"total": TOTAL, "iban": IBAN, "reference": REF},  # no due date
        {"due_date": DUE, "iban": IBAN, "reference": REF},  # no amount
        {"due_date": DUE, "total": TOTAL, "iban": "", "reference": ""},
    ],
)
def test_heuristic_false_cases(fields):
    assert guess_tray(found(**fields), None, TRAYS) is None


def test_heuristic_needs_a_to_pay_tray():
    bill = found(due_date=DUE, total=TOTAL, iban=IBAN)
    assert guess_tray(bill, None, ("to-action", "to-read")) is None


def test_rule_beats_heuristic():
    bill = found(due_date=DUE, total=TOTAL, iban=IBAN)
    assert guess_tray(bill, "to-action", TRAYS) == "to-action"
    assert guess_tray(found(), "to-read", TRAYS) == "to-read"


def test_unknown_rule_tray_falls_back():
    bill = found(due_date=DUE, total=TOTAL, iban=IBAN)
    assert guess_tray(bill, "no-such-tray", TRAYS) == "to-pay"
    assert guess_tray(found(), "no-such-tray", TRAYS) is None


# -- the rule keys then.tray and then.payee ------------------------------------------


def rule(id: str, when: dict | None = None, **then) -> Rule:
    return Rule.model_validate({"id": id, "when": when or {}, "then": then})


REC = FileRecord(drive_id="id", path="##. Organize/scan.pdf", name="scan.pdf", ext="pdf")


def test_suggestion_takes_tray_and_payee_from_the_folder_rule():
    rules = [
        rule("no-folder", {"text_contains": ["northpower"]}, tags=["x"]),
        rule(
            "northpower",
            {"text_contains": ["northpower"]},
            folder="10. Financial",
            tray="to-pay",
            payee="Northpower Oy",
        ),
        rule("later", {"text_contains": ["northpower"]}, folder="11. Other", payee="Someone else"),
    ]
    s = suggest(REC, "Northpower lasku", rules)
    assert s.folder == "10. Financial"
    assert s.tray == "to-pay" and s.payee == "Northpower Oy"


def test_suggestion_tray_and_payee_not_mixed_across_rules():
    rules = [
        rule("first", {"text_contains": ["northpower"]}, folder="10. Financial"),
        rule("second", {"text_contains": ["northpower"]}, tray="to-pay", payee="Northpower Oy"),
    ]
    s = suggest(REC, "Northpower lasku", rules)
    assert s.tray is None and s.payee is None


def test_suggestion_without_any_folder_rule_uses_the_first_tray_rule():
    rules = [
        rule("northpower", {"text_contains": ["northpower"]}, tray="to-pay", payee="Northpower Oy")
    ]
    s = suggest(REC, "Northpower lasku", rules)
    assert s.folder is None and s.tray == "to-pay" and s.payee == "Northpower Oy"


def test_suggestion_without_matching_rule_has_no_tray_or_payee():
    s = suggest(
        REC, "nothing", [rule("northpower", {"text_contains": ["northpower"]}, tray="to-pay")]
    )
    assert s.tray is None and s.payee is None


def test_blank_payee_is_none():
    r = rule("r", payee="  ")
    assert r.then.payee is None


def test_a_valid_bank_barcode_guesses_to_pay():
    from dam.bills.barcode import build

    code = build("FI7944052020036082", Decimal("1.00"), "868516259619897", None)
    assert guess_tray(DetectedFields(), None, ["to-pay"], code) == "to-pay"
    assert guess_tray(DetectedFields(), None, ["letters"], code) is None
    assert guess_tray(DetectedFields(), "letters", ["to-pay", "letters"], code) == "letters"
    assert guess_tray(DetectedFields(), None, ["to-pay"], "4" + "0" * 53) is None
    assert guess_tray(DetectedFields(), None, ["to-pay"], None) is None
