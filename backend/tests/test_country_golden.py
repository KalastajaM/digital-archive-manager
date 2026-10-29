"""Field detection and the stopword lists, recorded before Finland-specific code moved into
country and language packs: the move must not change any of it.

``DAM_UPDATE_GOLDEN=1`` rewrites ``golden/fields.json`` from the current code. Do that only
when a change in detection is intended, never to make this test pass after a move.
"""

import json
import os
from pathlib import Path

from dam.ai.tasks.ask_archive import STOPWORDS
from dam.demo import PDFS
from dam.rules.fields import detect_fields
from dam.rules.similar import _STOP

GOLDEN = Path(__file__).parent / "golden" / "fields.json"

CORPUS = [
    # the texts of tests/test_fields.py
    "",
    "1.1.1900 ja 1.1.2099 ja 5.5.2025",
    "5,10 € ja 5,10 € sekä 2,00 €",
    "Yhteensä 1.234,56 €",
    "A 1 234,56 € B 123,45 EUR C €12.50 D 7,00 €",
    "Eräpäivä 3.4.2026, laskupäivä 13.10.2026 ja 2026-11-05; virhe 31.2.2026; 13.10.2026",
    "Tilinumero FI21 1234 5600 0007 85 Northbank",
    "Tilinumero FI21 1234 5600 0007 86",
    "FI2112345600000785",
    "Viite RF23 5000 1",
    "RF18 1234 5678 9",
    "RF23 5000 1 SUMMA 12,00",
    "RF24 5000 1",
    "Viitenumero: 1234561",
    "1234561",
    "Viite 1234562",
    "Reference nro 1234561",
    "EUR 12.10.2026",
    "€ 5.10.2026",
    "€12.50",
    "EUR 12,50 ja €3.10,5",
    "Viite 2026-10-12",
    "Viite 12.10.2026",
    "Viite 2026/10",
    "Viite 0000",
    "Viite 000000",
    "Viite 123",
    "RF18 1234 5678 9 12 345",
    "Viite 1234561",
    "Viite 1232",
    "Eräpäivä 15.10.2026",
    "Due date 2026-11-02",
    "FÖRFALLODAG 3.4.2026",
    "ERAPAIVA: 15.10.2026",
    "Päiväys 01.10.2026",
    "Eräpäivä 15.10.1900",
    "overdue 15.10.2026",
    "residue 15.10.2026",
    "Payment due 15.10.2026",
    "Maksettava 15.10.2026",
    "Att betala: 12,00 EUR",
    "Maksettava 9,90 € ja 50,00 €",
    "A 5,00 € B 70,00 € C 8,00 €",
    "ei summia",
    "Subtotal 10,00 € Total 50,00 €",
    "Subtotal 10,00 € Alv 12,00 € Total 50,00 €",
    "Välisumma 10,00 € Total 50,00 €",
    "Summa 5,00 € Yhteensä 100,00 €",
    "Summa 5,00 € ja 7,00 €",
    "Loppusumma 120,00 €",
    "Kokonaissumma 80,00 €",
    "Totalt 30,00 EUR",
    # label order across languages, and both kinds of reference in one text
    "Due date 31.10.2026 due 1.11.2026 12,00 €",
    "due 1.11.2026 Due date 31.10.2026",
    "Maksettava 12,00 € eräpäivä 1.11.2026",
    "Att betala 45,10 kr 45,10 € Förfallodag 2.11.2026",
    "Totalt 9,90 € summa 3,00 € Total 12,00 €",
    "Viite 1234561 RF18 1234 5678 9",
    "RF18 1234 5678 9 Viitenumero: 1234561",
    "Reference nro 1234561 Yhteensä 1.234,56 €",
    # the demo archive's scans
    *(text for _, text in PDFS if text is not None),
]


def _fields(text: str) -> dict:
    found = detect_fields(text)
    return {
        "text": text,
        "dates": [d.isoformat() for d in found.dates],
        "amounts": [str(a) for a in found.amounts],
        "iban": found.iban,
        "reference": found.reference,
        "due_date": found.due_date.isoformat() if found.due_date else None,
        "total": str(found.total) if found.total is not None else None,
    }


def _snapshot() -> dict:
    return {
        "fields": [_fields(text) for text in CORPUS],
        "stopwords": sorted(STOPWORDS),
        "kind_words": sorted(_STOP),
    }


def test_golden():
    if os.environ.get("DAM_UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        text = json.dumps(_snapshot(), ensure_ascii=False, indent=1, sort_keys=True)
        GOLDEN.write_text(text + "\n", encoding="utf-8")
    assert _snapshot() == json.loads(GOLDEN.read_text(encoding="utf-8"))
