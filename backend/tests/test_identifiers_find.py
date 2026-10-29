import pytest

from dam import countries
from dam.checks import ytunnus_check


def found(text: str, kind: str) -> list[str]:
    (spec,) = [s for p in countries.ALL for s in p.identifiers if s.kind == kind]
    return spec.find(text)


def test_ytunnus_check_digit():
    assert ytunnus_check("0112038") == 9
    assert ytunnus_check("0000006") is None  # remainder 1: no valid check digit


@pytest.mark.parametrize(
    "text",
    ["Y-tunnus 0112038-9", "Business ID: 0112038-9.", "ALV-nro FI01120389", "FI 0112038-9"],
)
def test_ytunnus_in_its_forms(text):
    assert found(text, "fi.ytunnus") == ["0112038-9"]


@pytest.mark.parametrize(
    "text",
    ["0112038-8", "Eräpäivä 05.11.2026", "puh. 040-1234567", "Viite 1234567-8", "10112038-9"],
)
def test_no_ytunnus(text):
    assert found(text, "fi.ytunnus") == []


def test_one_ytunnus_once_in_order():
    text = "Y-tunnus 0112038-9, VAT FI01120389, also 0112038-9"
    assert found(text, "fi.ytunnus") == ["0112038-9"]


def test_ibans_in_order():
    text = "FI21 1234 5600 0007 85 or NL91ABNA0417164300"
    assert found(text, "core.iban") == ["FI2112345600000785", "NL91ABNA0417164300"]


def test_domains_from_web_and_mail():
    text = "www.Example.fi, info@example.fi and laskut@Billing.Example.COM"
    assert found(text, "core.domain") == ["example.fi", "billing.example.com"]


def test_free_mail_domains_name_nobody():
    assert found("matti.meikalainen@gmail.com or me@outlook.com", "core.domain") == []


def test_signature_names_every_pack_and_version():
    assert countries.signature() == "core:1 fi:2"
    assert [p.code for p in countries.ALL] == ["core", "fi"]


def test_a_long_run_without_spaces_is_quick():
    import time

    t = time.perf_counter()
    found("a-" * 40_000 + " info@firma.fi", "core.domain")
    assert time.perf_counter() - t < 1.0
    assert found("a-" * 40_000 + " info@firma.fi", "core.domain") == ["firma.fi"]


def test_file_names_are_no_domains():
    assert found("logo@2x.png and WWW.report.docx", "core.domain") == []


@pytest.mark.parametrize("text", ["SE0112038-9", "ABC0112038-9", "x0112038-9"])
def test_a_ytunnus_does_not_follow_letters(text):
    assert found(text, "fi.ytunnus") == []
