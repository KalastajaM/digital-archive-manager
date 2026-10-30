"""The wider core of field detection: IBANs of any SEPA country, amounts with a dot or
space for thousands after the euro sign, and day-first dates written with dashes, slashes
or a month name."""

from datetime import date
from decimal import Decimal

import pytest

from dam import packs
from dam.checks import valid_iban
from dam.rules.fields import detect_fields


@pytest.mark.parametrize(
    "text, iban",
    [
        ("IBAN DE89 3704 0044 0532 0130 00", "DE89370400440532013000"),
        ("Rekening NL91ABNA0417164300 t.n.v.", "NL91ABNA0417164300"),
        ("GB82 WEST 1234 5698 7654 32", "GB82WEST12345698765432"),
        ("Tilinumero FI21 1234 5600 0007 85 Viite 123", "FI2112345600000785"),
        ("FI21 1234 5600 0007 85 1234", "FI2112345600000785"),
    ],
)
def test_iban_of_any_sepa_country(text, iban):
    assert detect_fields(text).iban == iban


def test_invalid_or_wrong_length_iban():
    assert detect_fields("IBAN DE89 3704 0044 0532 0130 01").iban is None
    assert not valid_iban("FI211234560000078")  # one digit short, though mod 97 is not the point
    assert detect_fields("Order AB12 3456 7890 1234").iban is None  # no such country


@pytest.mark.parametrize(
    "text, amount",
    [
        ("Total € 1.234,56", Decimal("1234.56")),
        ("Te betalen: € 84,20", Decimal("84.20")),
        ("EUR 1 234,56", Decimal("1234.56")),
        ("€1,234.56", Decimal("1234.56")),
    ],
)
def test_amount_after_the_euro_sign(text, amount):
    assert detect_fields(text).amounts == [amount]


def test_dates_are_not_amounts_and_references_not_dates():
    assert detect_fields("EUR 12.10.2026").amounts == []
    assert detect_fields("puh. 040-123-4567").dates == []
    assert detect_fields("Viite 2026/10").dates == []


@pytest.mark.parametrize(
    "text",
    [
        "Vervaldatum 15-10-2026",
        "Due 15/10/2026",
        "Förfallodag 15 oktober 2026",
        "Eräpäivä 15. lokakuuta 2026",
        "Due date: October 15, 2026",
        "due 15 Oct 2026",
    ],
)
def test_day_first_and_written_dates(text):
    assert detect_fields(text).dates == [date(2026, 10, 15)]


def test_written_dates_need_the_language():
    packs.activate(packs.build([], ["en"]))
    assert detect_fields("15. lokakuuta 2026").dates == []
    assert detect_fields("15 October 2026").dates == [date(2026, 10, 15)]


def test_a_written_due_date_is_the_due_date():
    found = detect_fields("Eräpäivä 15. lokakuuta 2026 Yhteensä 47,90 €")
    assert found.due_date == date(2026, 10, 15) and found.total == Decimal("47.90")


def test_an_iban_ends_where_its_country_says():
    # more letters or digits right after the IBAN: not an IBAN (as before for FI)
    assert detect_fields("FI2112345600000785123").iban is None
    assert detect_fields("NL91 ABNA 0417 1643 00X").iban is None
    assert detect_fields("NL91 ABNA 0417 1643 00, ref 12").iban == "NL91ABNA0417164300"


@pytest.mark.parametrize(
    "text",
    [
        "you may 15 2026 come",
        "Section 5 march 2026",
        "version 1-2-2026",
        "Puh 09-12-2026",
        "tel. 05/11/2026",
    ],
)
def test_words_and_numbers_that_only_look_like_dates(text):
    assert detect_fields(text).dates == []


@pytest.mark.parametrize("text", ["Due May 15, 2026", "5 March 2026", "Laskun päiväys 15-05-2026"])
def test_real_dates_like_them_still_count(text):
    assert len(detect_fields(text).dates) == 1


@pytest.mark.parametrize(
    "text",
    [
        "förfallodag 30 dec. 2026",
        "15 jan 2026",
        "15 sept 2026",
        "15 october 2026",
        "voimassa v. 1-1-2026",
    ],
)
def test_lower_case_months_and_plain_dates_still_count(text):
    assert len(detect_fields(text).dates) == 1
