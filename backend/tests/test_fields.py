from datetime import date
from decimal import Decimal

from dam.rules.fields import detect_fields

VALID_IBAN = "FI21 1234 5600 0007 85"


def test_finnish_amount():
    assert detect_fields("Yhteensä 1.234,56 €").amounts == [Decimal("1234.56")]


def test_amount_formats():
    text = "A 1 234,56 € B 123,45 EUR C €12.50 D 7,00 €"
    assert detect_fields(text).amounts == [
        Decimal("1234.56"),
        Decimal("123.45"),
        Decimal("12.50"),
        Decimal("7.00"),
    ]


def test_amounts_deduped_in_order_and_two_places():
    amounts = detect_fields("5,10 € ja 5,10 € sekä 2,00 €").amounts
    assert amounts == [Decimal("5.10"), Decimal("2.00")]
    assert all(a.as_tuple().exponent == -2 for a in amounts)


def test_date_formats():
    text = "Eräpäivä 3.4.2026, laskupäivä 13.10.2026 ja 2026-11-05; virhe 31.2.2026; 13.10.2026"
    assert detect_fields(text).dates == [date(2026, 4, 3), date(2026, 10, 13), date(2026, 11, 5)]


def test_iban_valid_and_invalid():
    assert detect_fields(f"Tilinumero {VALID_IBAN} Northbank").iban == "FI2112345600000785"
    assert detect_fields("Tilinumero FI21 1234 5600 0007 86").iban is None
    assert detect_fields("FI2112345600000785").iban == "FI2112345600000785"


def test_rf_reference():
    assert detect_fields("Viite RF23 5000 1").reference == "RF2350001"
    assert detect_fields("RF18 1234 5678 9").reference == "RF18123456789"
    # trailing capitalised words are not swallowed
    assert detect_fields("RF23 5000 1 SUMMA 12,00").reference == "RF2350001"
    assert detect_fields("RF24 5000 1").reference is None


def test_domestic_reference_requires_label():
    assert detect_fields("Viitenumero: 1234561").reference == "1234561"
    assert detect_fields("1234561").reference is None
    assert detect_fields("Viite 1234562").reference is None  # bad check digit
    assert detect_fields("Reference nro 1234561").reference == "1234561"


def test_grouped_domestic_reference():
    from dam.rules.fields import _check_731

    base = "123456789"
    ref = base + str(_check_731(base))
    grouped = f"{ref[:5]} {ref[5:]}" if len(ref) > 5 else ref
    assert detect_fields(f"Viitenumero {grouped}").reference == ref


def test_nothing_found():
    f = detect_fields("")
    assert (f.dates, f.amounts, f.iban, f.reference) == ([], [], None, None)


def test_prefix_amount_not_taken_from_dates():
    assert detect_fields("EUR 12.10.2026").amounts == []
    assert detect_fields("€ 5.10.2026").amounts == []
    assert detect_fields("€12.50").amounts == [Decimal("12.50")]
    assert detect_fields("EUR 12,50 ja €3.10,5").amounts == [Decimal("12.50")]


def test_domestic_reference_rejects_dates_zeros_and_short():
    assert detect_fields("Viite 2026-10-12").reference is None
    assert detect_fields("Viite 12.10.2026").reference is None
    assert detect_fields("Viite 2026/10").reference is None
    assert detect_fields("Viite 0000").reference is None
    assert detect_fields("Viite 000000").reference is None
    assert detect_fields("Viite 123").reference is None


def test_rf_prefers_longest_valid_on_group_boundary():
    assert detect_fields("RF18 1234 5678 9 12 345").reference == "RF18123456789"


def test_check_digit_731_hand_checked_vectors():
    from dam.rules.fields import _check_731

    assert _check_731("123456") == 1  # 1234561
    assert _check_731("123") == 2  # 1232
    assert detect_fields("Viite 1234561").reference == "1234561"
    assert detect_fields("Viite 1232").reference == "1232"


def test_implausible_text_dates_ignored():
    f = detect_fields("1.1.1900 ja 1.1.2099 ja 5.5.2025")
    assert f.dates == [date(2025, 5, 5)]


def test_due_date_after_label():
    assert detect_fields("Eräpäivä 15.10.2026").due_date == date(2026, 10, 15)
    assert detect_fields("Due date 2026-11-02").due_date == date(2026, 11, 2)
    assert detect_fields("FÖRFALLODAG 3.4.2026").due_date == date(2026, 4, 3)
    assert detect_fields("ERAPAIVA: 15.10.2026").due_date == date(2026, 10, 15)


def test_due_date_not_document_date():
    text = "Päiväys 01.10.2026 Laskun numero 123 Eräpäivä: 15.10.2026"
    assert detect_fields(text).due_date == date(2026, 10, 15)


def test_due_date_none_without_label_or_too_far():
    assert detect_fields("Päiväys 01.10.2026").due_date is None
    assert detect_fields("Eräpäivä" + " " * 41 + "15.10.2026").due_date is None
    assert detect_fields("Eräpäivä" + " " * 40 + "15.10.2026").due_date == date(2026, 10, 15)
    assert detect_fields("Eräpäivä 15.10.1900").due_date is None


def test_due_is_whole_word_only():
    assert detect_fields("overdue 15.10.2026").due_date is None
    assert detect_fields("residue 15.10.2026").due_date is None
    assert detect_fields("Payment due 15.10.2026").due_date == date(2026, 10, 15)
    assert detect_fields("Maksettava 15.10.2026").due_date == date(2026, 10, 15)


def test_total_after_label_beats_larger_amount():
    text = "Vuokra 1 200,00 € ... Yhteensä 84,20 €"
    assert detect_fields(text).total == Decimal("84.20")
    assert detect_fields("Att betala: 12,00 EUR").total == Decimal("12.00")
    assert detect_fields("Maksettava 9,90 € ja 50,00 €").total == Decimal("9.90")


def test_total_falls_back_to_largest_and_none():
    assert detect_fields("A 5,00 € B 70,00 € C 8,00 €").total == Decimal("70.00")
    assert detect_fields("ei summia").total is None
    assert detect_fields("").due_date is None


def test_total_ignores_subtotal_and_valisumma():
    assert detect_fields("Subtotal 10,00 € Total 50,00 €").total == Decimal("50.00")
    assert detect_fields("Subtotal 10,00 € Alv 12,00 € Total 50,00 €").total == Decimal("50.00")
    assert detect_fields("Välisumma 10,00 € Total 50,00 €").total == Decimal("50.00")


def test_total_strong_label_beats_weak_summa():
    assert detect_fields("Summa 5,00 € Yhteensä 100,00 €").total == Decimal("100.00")
    assert detect_fields("Summa 5,00 € ja 7,00 €").total == Decimal("5.00")
    assert detect_fields("Loppusumma 120,00 €").total == Decimal("120.00")
    assert detect_fields("Kokonaissumma 80,00 €").total == Decimal("80.00")
    assert detect_fields("Totalt 30,00 EUR").total == Decimal("30.00")


def test_label_window_with_decomposed_diacritics():
    import unicodedata

    label = unicodedata.normalize("NFD", "Eräpäivä")
    assert detect_fields(label + " " * 40 + "15.10.2026").due_date == date(2026, 10, 15)
    assert detect_fields(label + " " * 41 + "15.10.2026").due_date is None
