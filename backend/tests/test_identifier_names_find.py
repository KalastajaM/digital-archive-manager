"""The company name printed next to a Y-tunnus, recognised by its legal-form ending."""

import pytest

from dam import countries


def name(text: str, value: str = "0112038-9") -> str | None:
    (spec,) = [s for p in countries.ALL for s in p.identifiers if s.kind == "fi.ytunnus"]
    assert spec.name is not None
    return spec.name(text, value)


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("Vesilaitos Oy, Y-tunnus 0112038-9", "Vesilaitos Oy"),
        ("Lähettäjä: Pohjola Vakuutus Oy | Y-tunnus 0112038-9", "Pohjola Vakuutus Oy"),
        ("Nordea Bank Abp\nY-tunnus 0112038-9", "Nordea Bank Abp"),
        ("Y-tunnus: 0112038-9\nKonepaja Virtanen Ky", "Konepaja Virtanen Ky"),
        ("Elisa Oyj · ALV-nro FI01120389", "Elisa Oyj"),
        ("Oy Karl Fazer Ab, FI01120389", "Oy Karl Fazer Ab"),
        ("Kesko Oyj Abp 0112038-9", "Kesko Oyj Abp"),
        ("Tmi Matti Meikäläinen, Y-tunnus 0112038-9", "Tmi Matti Meikäläinen"),
        ("Asunto Oy Helsingin Kotikatu 5\nY-tunnus 0112038-9", "Asunto Oy Helsingin Kotikatu 5"),
        ("Helsingin Tennisseura ry 0112038-9", "Helsingin Tennisseura ry"),
        ("VESILAITOS OY Y-TUNNUS 0112038-9", "VESILAITOS OY"),
        ("Osuuskauppa Keskimaa osk, 0112038-9", "Osuuskauppa Keskimaa osk"),
        ("Telia Finland Oyj, Y-tunnus 0112038-9", "Telia Finland Oyj"),
        ("Teleste Oyj 0112038-9", "Teleste Oyj"),
        ("Vattenfall Oy 0112038-9", "Vattenfall Oy"),
        ("Alvar Aalto Oy 0112038-9", "Alvar Aalto Oy"),
        ("Fortum Power and Heat Oy, 0112038-9", "Fortum Power and Heat Oy"),
        ("Rakennus Virtanen Tmi 0112038-9", "Rakennus Virtanen Tmi"),
        ("Asunto  Oy Kotikatu 5\nY-tunnus 0112038-9", "Asunto Oy Kotikatu 5"),
        ("Laskuttaja Elisa Oyj, Y-tunnus 0112038-9", "Elisa Oyj"),
        ("Elisa Oyj\nPL 1\n00061 ELISA\nPuh. 010 190\nY-tunnus 0112038-9", "Elisa Oyj"),
        ("DNA Oyj\n\n\nY-tunnus 0112038-9", "DNA Oyj"),
    ],
)
def test_the_name_next_to_the_id(text, want):
    assert name(text) == want


def test_the_closest_line_wins():
    text = "Asiakas Oy\nrivi\nVesilaitos Oy\nY-tunnus 0112038-9"
    assert name(text) == "Vesilaitos Oy"


@pytest.mark.parametrize(
    "text",
    [
        "Y-tunnus 0112038-9",  # no legal form near
        "Asiakas Oy\nrivi\nrivi\nrivi\nrivi\nY-tunnus 0112038-9",  # too far away
        "Vähennettävät AY-jäsenmaksut 0112038-9",  # not a legal form
        "Vesilaitos Oy, Y-tunnus 2345678-1",  # another ID only
        "Oy 0112038-9",  # a legal form with no name
        "Lisätietoja saat osoitteesta oy.fi 0112038-9",  # a word that only looks like one
    ],
)
def test_no_name(text):
    assert name(text) is None


def test_a_name_far_from_the_id_in_a_long_text_is_not_read():
    text = "Vesilaitos Oy\n" + "rivi\n" * 200 + "Y-tunnus 0112038-9"
    assert name(text) is None
