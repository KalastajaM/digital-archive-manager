"""The Netherlands pack: betalingskenmerk, btw-id, KvK-nummer and RSIN (spec section 7)."""

from datetime import date
from decimal import Decimal

from dam import countries, packs
from dam.checks import elfproef, kenmerk_check, mod97_10, valid_kenmerk
from dam.countries.nl import find_btw, find_kenmerk, find_kvk, find_rsin
from dam.rules.fields import detect_fields


def test_kenmerk_check_digit():
    # weights 2, 4, 8, 5, 10, 9, 7, 3, 6, 1 from the right; 11 - (sum mod 11)
    assert kenmerk_check("2234534622567") == 1  # Wikipedia: sum 263
    assert kenmerk_check("036000016301110") == 2  # Belastingdienst: sum 152


def test_valid_kenmerk_examples_and_lengths():
    assert valid_kenmerk("12234534622567")  # 14 digits, length code 2 (12 follow)
    assert valid_kenmerk("2036000016301110")  # 16 digits, no length code
    assert not valid_kenmerk("22234534622567")  # wrong check digit
    assert not valid_kenmerk("13234534622567")  # length code 3 is not a length
    assert not valid_kenmerk("1223453462256")  # 13 digits but the code says 12 follow
    assert not valid_kenmerk("0000000000000000")  # passes the sum, but no reference
    assert not valid_kenmerk("1234567")  # 7 digits: no check digit, not detected
    assert not valid_kenmerk("203600001630111")  # 15 digits: no such length


def test_elfproef():
    assert elfproef("123456782") and elfproef("111222333")
    assert not elfproef("123456789")
    assert not elfproef("12345678")


def test_mod97_10_without_rearranging():
    assert mod97_10("NL002455799B11") == 1
    assert mod97_10("NL123456789B90") != 1


def test_kenmerk_after_a_label():
    assert find_kenmerk("Betalingskenmerk: 1223 4534 6225 67") == [(0, "12234534622567")]
    text = "Bedrag € 84,20\nbetalingskenmerk 2036 0000 1630 1110 IBAN NL91 ABNA 0417 1643 00"
    assert [v for _, v in find_kenmerk(text)] == ["2036000016301110"]
    assert [v for _, v in find_kenmerk("Betaalkenmerk 2036000016301110")] == ["2036000016301110"]
    assert [v for _, v in find_kenmerk("Kenmerk: 2036 0000 1630 1110")] == ["2036000016301110"]


def test_a_long_run_of_groups_is_read_in_linear_time():
    import time

    started = time.perf_counter()
    assert find_kenmerk("kenmerk " + "1 " * 20000) == []
    assert time.perf_counter() - started < 0.5


def test_kenmerk_is_never_read_without_a_label_or_with_a_bad_check():
    assert find_kenmerk("2036 0000 1630 1110") == []
    assert find_kenmerk("Betalingskenmerk: 3036 0000 1630 1110") == []
    # a letter's own reference ("Ons kenmerk", "Uw kenmerk") is not a payment reference
    assert find_kenmerk("Ons kenmerk: 2036 0000 1630 1110") == []
    assert find_kenmerk("Uw kenmerk 2036000016301110") == []


def test_btw_either_check():
    assert find_btw("Btw-nummer: NL002455799B11") == ["NL002455799B11"]  # mod 97-10
    assert find_btw("NL 8003.12.351 B01") == ["NL800312351B01"]  # elfproef, an RSIN
    assert find_btw("btw NL123456789B90") == []  # neither


def test_btw_never_stores_a_number_that_is_not_an_rsin():
    # 123456782 passes the elfproef but starts neither 00 nor 80 to 89: before 2020 a sole
    # proprietor's btw-id carried their BSN, a personal number, so it is not read
    assert elfproef("123456782")
    assert find_btw("NL123456782B01") == []


def test_kvk_only_near_a_label():
    assert find_kvk("KvK 12345678") == ["12345678"]
    assert find_kvk("K.v.K.-nummer: 01234567") == ["01234567"]
    assert find_kvk("ingeschreven bij de Kamer van Koophandel onder nummer 87654321") == [
        "87654321"
    ]
    assert find_kvk("Handelsregister 33221100") == ["33221100"]
    assert find_kvk("Klantnummer 12345678") == []
    assert find_kvk("KvK " + "x" * 41 + " 12345678") == []  # beyond the 40-character window
    assert find_kvk("KvK 123456789") == []  # nine digits are not a KvK-nummer
    assert find_kvk("KvK 06-12345678") == []  # a phone number
    # nine digits at the edge of the window are not cut to eight (they may be a BSN)
    assert find_kvk("KvK" + " " * 40 + "111222333") == []


def test_rsin_only_right_after_its_label():
    assert find_rsin("RSIN: 800312351") == ["800312351"]
    assert find_rsin("RSIN 003212345") == []  # fails the elfproef
    # a bare nine-digit number is never stored: the BSN shares the check
    assert find_rsin("123456782") == []
    assert find_rsin("BSN 123456782") == []
    assert find_rsin("Klantnummer 800312351") == []
    assert find_rsin("RSIN 123456782") == []  # not 00 or 80 to 89: may be a BSN
    assert find_rsin("BSN/RSIN: 800312351") == []  # which of the two, unknown


def test_pack_registered_with_its_parts():
    nl = countries.get("nl")
    assert nl in countries.ALL
    assert "nl:" in countries.signature()
    assert nl.languages == ("nl",)
    assert nl.address_zone == (0.071, 0.135, 0.548, 0.320)
    assert [s.kind for s in nl.references] == ["nl.kenmerk"]
    kinds = {s.kind: s.names_sender for s in nl.identifiers}
    assert kinds == {"nl.btw": True, "nl.kvk": True, "nl.rsin": True}


BILL = """Energie Leverancier B.V.
KvK 12345678  Btw NL002455799B11
Factuur

Factuurdatum 15 oktober 2026
Vervaldatum: 29-10-2026

Subtotaal € 1.000,00
Btw 21% € 210,00
Totaal te betalen € 1.210,00

Graag betalen op IBAN NL91 ABNA 0417 1643 00
onder vermelding van betalingskenmerk 2036 0000 1630 1110
"""


def test_a_dutch_bill_with_the_dutch_packs():
    before = packs.active()
    try:
        packs.activate(packs.build(["nl"], ["nl", "en"]))
        found = detect_fields(BILL)
    finally:
        packs.activate(before)
    assert found.reference == "2036000016301110"
    assert found.iban == "NL91ABNA0417164300"
    assert found.due_date == date(2026, 10, 29)
    assert found.total == Decimal("1210.00")
    assert date(2026, 10, 15) in found.dates
