"""Finnish bank barcode (pankkiviivakoodi): build, parse and the Code 128 set C modules.

The examples are the test invoices of Finance Finland's "Pankkiviivakoodi-opas" v5.3
(sections 13.1 and 13.2), checked against the guide itself.
"""

import random
from datetime import date
from decimal import Decimal

import pytest

from dam.bills.barcode import (
    PATTERNS,
    BarcodeData,
    BarcodeError,
    build,
    code128c_values,
    modules,
    parse,
)

# (IBAN, amount, reference, due, code, the guide's printed check character)
GUIDE = [
    # 13.1 version 4
    ("FI7944052020036082", "4883.15", "868516259619897", date(2010, 6, 12),
     "479440520200360820048831500000000868516259619897100612", 40),
    ("FI5810171000000122", "482.99", "559582243294671", date(2012, 1, 31),
     "458101710000001220004829900000000559582243294671120131", 55),
    ("FI0250004640001302", "693.80", "69875672083435364", date(2011, 7, 24),
     "402500046400013020006938000000069875672083435364110724", 14),
    ("FI1566010001530641", "7444.54", "7758474790647489", date(2019, 12, 19),
     "415660100015306410074445400000007758474790647489191219", 63),
    ("FI1680001400050267", "935.85", "78777679656628687", None,
     "416800014000502670009358500000078777679656628687000000", 30),
    ("FI7331313001000058", "0.00", "868624", date(2013, 8, 9),
     "473313130010000580000000000000000000000000868624130809", 68),
    ("FI8333010001100775", "150000.20", "92125374252539897737", date(2016, 5, 25),
     "483330100011007751500002000092125374252539897737160525", 45),
    ("FI3936363002092492", "1.03", "590738390", date(2023, 3, 11),
     "439363630020924920000010300000000000000590738390230311", 9),
    ("FI9239390001003391", "0.02", "1357914", date(2099, 12, 24),
     "492393900010033910000000200000000000000001357914991224", 30),
    # 13.2 version 5
    ("FI7944052020036082", "4883.15", "RF09868516259619897", date(2010, 6, 12),
     "579440520200360820048831509000000868516259619897100612", 74),
    ("FI5810171000000122", "482.99", "RF06559582243294671", date(2010, 1, 31),
     "558101710000001220004829906000000559582243294671100131", 31),
    # The guide prints [59] here, but its own mod-103 rule (section 12) gives 34; the
    # data digits follow the layout, so the code is kept and the check is ours.
    ("FI0250004640001302", "693.80", "RF61698756720839", date(2011, 7, 24),
     "502500046400013020006938061000000000698756720839110724", 34),
    ("FI1566010001530641", "7444.54", "RF847758474790647489", date(2019, 12, 19),
     "515660100015306410074445484000007758474790647489191219", 16),
    ("FI1680001400050267", "935.85", "RF6078777679656628687", None,
     "516800014000502670009358560000078777679656628687000000", 15),
    ("FI7331313001000058", "0.00", "RF10868624", date(2013, 8, 9),
     "573313130010000580000000010000000000000000868624130809", 91),
    ("FI8333010001100775", "150000.20", "RF7192125374252539897737", date(2016, 5, 25),
     "583330100011007751500002071092125374252539897737160525", 80),
    ("FI3936363002092492", "1.03", "RF66590738390", date(2023, 3, 11),
     "539363630020924920000010366000000000000590738390230311", 10),
    ("FI9239390001003391", "0.02", "RF951357914", date(2099, 12, 24),
     "592393900010033910000000295000000000000001357914991224", 33),
]  # fmt: skip


def test_brief_examples():
    """The two examples of the task brief (the guide's LASKU 1, versions 4 and 5)."""
    iban, amount, due = "FI79 4405 2020 0360 82", Decimal("4883.15"), date(2010, 6, 12)
    assert (
        build(iban, amount, "86851 62596 19897", due)
        == "479440520200360820048831500000000868516259619897100612"
    )
    assert (
        build(iban, amount, "RF09 8685 1625 9619 897", due)
        == "579440520200360820048831509000000868516259619897100612"
    )


@pytest.mark.parametrize("iban,amount,ref,due,code,check", GUIDE)
def test_guide_examples_build_and_parse(iban, amount, ref, due, code, check):
    assert build(iban, Decimal(amount), ref, due) == code
    assert parse(code) == BarcodeData(iban, Decimal(amount), ref, due)
    assert code128c_values(code)[-2] == check


def test_check_character_of_the_guide_section_12():
    # [X] 5 5810171000000122 00048299 06000000559582243294671 100131 [Z][Y]
    code = "558101710000001220004829906000000559582243294671100131"
    values = code128c_values(code)
    assert values[0] == 105 and values[-1] == 106 and len(values) == 30
    assert values[-2] == 31


def _random_input(rng: random.Random) -> tuple[str, Decimal, str, date | None]:
    bban = "".join(rng.choice("0123456789") for _ in range(14))
    check = 98 - int(bban + "151800") % 97
    iban = f"FI{check:02d}{bban}"
    amount = Decimal(rng.randint(0, 99_999_999)) / 100
    if rng.random() < 0.5:
        body = str(rng.randint(1, 9)) + "".join(
            rng.choice("0123456789") for _ in range(rng.randint(2, 18))
        )
        weights = [(7, 3, 1)[i % 3] for i in range(len(body))]
        total = sum(int(d) * w for d, w in zip(reversed(body), weights, strict=True))
        reference = body + str((10 - total % 10) % 10)
    else:
        body = str(rng.randint(1, 9)) + "".join(
            rng.choice("0123456789") for _ in range(rng.randint(0, 20))
        )
        rf_check = 98 - int(body + "271500") % 97
        reference = f"RF{rf_check:02d}{body}"
    first, last = date(2000, 1, 1).toordinal(), date(2099, 12, 31).toordinal()
    due = None if rng.random() < 0.2 else date.fromordinal(rng.randint(first, last))
    return iban, amount.quantize(Decimal("0.01")), reference, due


def test_build_roundtrips_every_field():
    rng = random.Random(20261020)
    for _ in range(50):
        iban, amount, reference, due = _random_input(rng)
        code = build(iban, amount, reference, due)
        assert len(code) == 54 and code.isdigit()
        assert code[0] == ("5" if reference.startswith("RF") else "4")
        assert parse(code) == BarcodeData(iban, amount, reference, due)


VALID = ("FI7944052020036082", Decimal("4883.15"), "868516259619897", date(2010, 6, 12))


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("iban", "DE89370400440532013000", "Finnish"),
        ("iban", "FI7944052020036083", "IBAN"),
        ("iban", "FI79440520200360", "IBAN"),
        ("amount", Decimal("-1.00"), "negative"),
        ("amount", Decimal("1000000.00"), "999 999,99"),
        ("amount", Decimal("1.005"), "cents"),
        ("amount", Decimal("NaN"), "amount"),
        ("reference", "868516259619898", "check digit"),
        ("reference", "123456789012345678901", "too long"),
        ("reference", "", "no reference"),
        ("reference", "0000", "reference"),
        ("reference", "123", "too short"),
        ("reference", "00000123", "too short"),
        ("reference", "12-34", "a national reference has only digits"),
        ("reference", "RF09868516259619898", "RF"),
        ("reference", "RF09868516259619897A", "RF"),
        ("reference", "RF18BBBB", "only digits"),
        ("reference", "RF401234567890123456789012", "too long"),
        ("due", date(1999, 12, 31), "due date"),
        ("due", date(2100, 1, 1), "due date"),
    ],
)
def test_build_refuses(field, value, reason):
    args = dict(zip(("iban", "amount", "reference", "due"), VALID, strict=True))
    args[field] = value
    with pytest.raises(BarcodeError) as exc:
        build(**args)
    assert reason in exc.value.reason


@pytest.mark.parametrize(
    "code,reason",
    [
        ("47944052020036082004883150000000086851625961989710061", "54 digits"),
        ("47944052020036082004883150000000086851625961989710061x", "54 digits"),
        ("679440520200360820048831500000000868516259619897100612", "version"),
        ("479440520200360830048831500000000868516259619897100612", "IBAN"),
        ("479440520200360820048831510000000868516259619897100612", "reserved"),
        ("479440520200360820048831500000000868516259619898100612", "check digit"),
        ("479440520200360820048831500000000000000000000000100612", "no reference"),
        ("4794405202003608200488315000" + "0" * 17 + "123100612", "too short"),
        ("579440520200360820048831509000000868516259619898100612", "RF"),
        ("479440520200360820048831500000000868516259619897101332", "due date"),
    ],
)
def test_parse_refuses(code, reason):
    with pytest.raises(BarcodeError) as exc:
        parse(code)
    assert reason in exc.value.reason


def test_parse_accepts_full_width_digits_only_as_ascii():
    with pytest.raises(BarcodeError):
        parse("４" + GUIDE[0][4][1:])


def test_patterns_are_the_code128_table():
    assert len(PATTERNS) == 107
    assert len(set(PATTERNS)) == 107
    assert all(len(p) == 6 and sum(p) == 11 for p in PATTERNS[:106])
    assert PATTERNS[105] == (2, 1, 1, 2, 3, 2)  # Start C
    assert PATTERNS[106] == (2, 3, 3, 1, 1, 1, 2)  # Stop with its final bar
    assert PATTERNS[0] == (2, 1, 2, 2, 2, 2)


def test_modules_width_and_shape():
    code = GUIDE[0][4]
    widths = modules(code)
    assert sum(widths) == 11 * (27 + 3) + 2
    assert len(widths) == 6 * 29 + 7  # bar first, bar last: an odd count
    assert widths[:6] == list(PATTERNS[105])
    assert widths[-13:-7] == list(PATTERNS[40])  # the guide's check character
    assert widths[-7:] == list(PATTERNS[106])
    assert widths[6:12] == list(PATTERNS[47])  # first pair "47"


def test_modules_refuses_a_code_that_does_not_parse():
    with pytest.raises(BarcodeError):
        modules("4" + "0" * 53)


def test_for_fields_and_mismatch():
    from dam.bills.barcode import for_fields, mismatch

    fields = {"iban": VALID[0], "amount": VALID[1], "reference": VALID[2], "due_date": VALID[3]}
    code, reason = for_fields(fields)
    assert code == GUIDE[0][4] and reason is None
    assert for_fields({**fields, "due_date": None})[0].endswith("000000")
    assert for_fields(fields, invalid={"amount"}) == (None, "the amount is not valid")
    assert for_fields({**fields, "reference": ""}) == (None, "no reference")
    printed = parse(code)
    # the same values written differently agree
    assert mismatch({**fields, "reference": "0086851 62596 19897"}, printed) == []
    assert mismatch({**fields, "reference": "RF09868516259619897"}, printed) == ["reference"]
    assert mismatch({**fields, "iban": None, "reference": 7}, printed) == ["iban", "reference"]
    payer_chooses = parse(build(VALID[0], Decimal("0"), VALID[2], None))
    assert mismatch({**fields, "amount": Decimal("5.00")}, payer_chooses) == []
