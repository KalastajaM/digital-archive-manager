"""Scan fields: normalisation, the detected list, the effective prefill, the API, migration 0021."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from dam.api import create_api
from dam.db.engine import MIGRATIONS_DIR, make_engine, migrate, write_tx
from dam.errors import InvalidRequest
from dam.extract.base import ExtractedText
from dam.index.scanner import scan
from dam.services.inbox import FileRequest
from dam.services.scan_fields import check_fields

INBOX = "##. Organize"
BANKS = "10. Financial/Banks"
BILL = (
    "Northpower Oy lasku\nLaskun päivämäärä 01.11.2026\nEräpäivä 15.11.2026\nYhteensä 84,20 €\n"
    "Toimitusmaksu 12,00 €\nIBAN FI21 1234 5600 0007 85\nViitenumero RF18 5390 0754 7034"
)


def field(kind, value, label=None):
    return {"kind": kind, "label": label, "value": value}


def add_scan(app, fake_archive, drive_id="id-a", text_=BILL):
    fake_archive.add(f"{INBOX}/{drive_id}.pdf", content=drive_id.encode(), drive_id=drive_id)
    scan(app.paths, app.repo)
    app.repo.save_content(drive_id, None, ExtractedText(text_, "test"), "indexed")


def kinds(fields):
    return [(f["kind"], f["value"]) for f in fields]


# --- normalisation -------------------------------------------------------------------


def test_values_are_normalised_per_kind():
    out = check_fields(
        [
            field("total", "84,20"),
            field("amount", "-1 234.5"),
            field("date", "2026-11-15"),
            field("iban", "fi21 1234 5600 0007 85"),
            field("reference", " rf18 5390 0754 7034 "),
            field("payee", "  Northpower Oy "),
            field("custom", " 1 ", " Customer no "),
        ]
    )
    assert out == [
        field("total", "84.20"),
        field("amount", "-1234.50"),
        field("date", "2026-11-15"),
        field("iban", "FI2112345600000785"),
        field("reference", "RF18539007547034"),
        field("payee", "Northpower Oy"),
        field("custom", "1", "Customer no"),
    ]


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        (field("nope", "x"), "unknown field kind"),
        (field("custom", "x"), "needs a label"),
        (field("custom", "x", "l" * 61), "needs a label"),
        (field("total", "84", "Label"), "has no label"),
        (field("payee", ""), "1 to 200"),
        (field("payee", "x" * 201), "1 to 200"),
        (field("due_date", "15.11.2026"), "due date"),
        (field("due_date", "2026-02-31"), "due date"),
        (field("total", "abc"), "total"),
        (field("iban", "FI21 1234 5600 0007 86"), "IBAN"),
    ],
)
def test_invalid_fields_are_refused(bad, message):
    with pytest.raises(InvalidRequest, match=message):
        check_fields([bad])


def test_single_valued_kinds_once_others_repeat():
    check_fields([field("date", "2026-01-01"), field("date", "2026-01-02")])
    check_fields([field("amount", "1"), field("amount", "2"), field("custom", "a", "A")] * 2)
    with pytest.raises(InvalidRequest, match="(?i)at most one total"):
        check_fields([field("total", "1"), field("total", "2")])
    with pytest.raises(InvalidRequest, match="(?i)at most 50"):
        check_fields([field("amount", "1")] * 51)
    with pytest.raises(InvalidRequest):
        check_fields("nope")


# --- detected and effective lists ----------------------------------------------------


def test_detected_list_order_and_dedupe(app, fake_archive):
    add_scan(app, fake_archive)
    [entry] = app.inbox.list()
    assert entry.fields_edited is False
    assert kinds(entry.fields) == [
        ("doc_date", "2026-11-01"),
        ("due_date", "2026-11-15"),
        ("total", "84.20"),
        ("iban", "FI2112345600000785"),
        ("reference", "RF18539007547034"),
        ("amount", "12.00"),
    ]
    assert ("amount", "84.20") not in kinds(entry.fields)
    assert ("amount", "12.00") in kinds(entry.fields)
    assert app.scan_fields.get("id-a") == {"fields": entry.fields, "edited": False}


def test_detected_list_has_payee_and_other_dates(app, fake_archive):
    (app.rules_dir / "50-northpower.yaml").write_text(
        "- id: northpower\n  when: {text_contains: [northpower]}\n"
        "  then: {folder: '10. Financial/Banks', payee: Northpower Oy}\n",
        encoding="utf-8",
    )
    assert app.reload_rules() == []
    add_scan(app, fake_archive, text_=BILL + "\nSopimus 02.01.2025")
    [entry] = app.inbox.list()
    ks = [f["kind"] for f in entry.fields]
    assert "payee" in ks and ks.index("payee") < ks.index("date") < ks.index("amount")
    assert ("date", "2025-01-02") in kinds(entry.fields)


def test_saved_list_replaces_detected_and_drives_the_prefill(app, fake_archive):
    add_scan(app, fake_archive)
    assert app.inbox.prefill_for("id-a")["total"] == "84.20"
    app.scan_fields.put("id-a", [field("total", "99,00"), field("payee", "Me")])
    [entry] = app.inbox.list()
    assert entry.fields_edited is True
    assert kinds(entry.fields) == [("total", "99.00"), ("payee", "Me")]
    # the saved list wins over the text, nothing else is prefilled
    assert entry.prefill == {"total": "99.00", "payee": "Me"}
    assert app.inbox.prefill_for("id-a") == entry.prefill


def test_removing_the_total_removes_its_prefill(app, fake_archive):
    add_scan(app, fake_archive)
    [entry] = app.inbox.list()
    app.scan_fields.put("id-a", [f for f in entry.fields if f["kind"] != "total"])
    [entry] = app.inbox.list()
    assert "total" not in entry.prefill and entry.prefill["iban"] == "FI2112345600000785"
    app.inbox.file_it([FileRequest("id-a", "a.pdf", BANKS, tray="to-pay")])
    [item] = app.trays.list("to-pay")
    assert "total" not in item.fields


def test_saved_list_overrides_the_barcode(app, fake_archive, monkeypatch):
    add_scan(app, fake_archive)
    monkeypatch.setattr(
        app.repo,
        "barcode_for",
        lambda _id: "416800014000502670009358500000078777679656628687000000",
    )
    assert app.inbox.prefill_for("id-a")["iban"] == "FI1680001400050267"
    app.scan_fields.put("id-a", [field("iban", "FI21 1234 5600 0007 85")])
    assert app.inbox.prefill_for("id-a") == {"iban": "FI2112345600000785"}


def test_delete_resets_to_detected(app, fake_archive):
    add_scan(app, fake_archive)
    detected = app.scan_fields.get("id-a")["fields"]
    app.scan_fields.put("id-a", [])
    assert app.scan_fields.get("id-a") == {"fields": [], "edited": True}
    assert app.inbox.prefill_for("id-a") == {}
    assert app.scan_fields.delete("id-a") == {"fields": detected, "edited": False}
    assert app.inbox.prefill_for("id-a")["total"] == "84.20"


# --- API -----------------------------------------------------------------------------

BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}


@pytest.fixture
def client(app):
    with TestClient(create_api(app), base_url=BASE) as c:
        yield c


def test_fields_routes(client, app, fake_archive):
    add_scan(app, fake_archive)
    r = client.get("/api/files/id-a/fields")
    assert r.status_code == 200 and r.json()["edited"] is False
    detected = r.json()["fields"]
    [entry] = client.get("/api/inbox").json()
    assert entry["fields"] == detected and entry["fields_edited"] is False

    body = {"fields": [field("total", "5,5"), field("custom", "7", "Customer")]}
    r = client.put("/api/files/id-a/fields", json=body, headers=LOCAL_ORIGIN)
    assert r.status_code == 200
    assert r.json() == {
        "fields": [field("total", "5.50"), field("custom", "7", "Customer")],
        "edited": True,
    }
    [entry] = client.get("/api/inbox").json()
    assert entry["fields_edited"] is True and entry["prefill"] == {"total": "5.50"}

    r = client.delete("/api/files/id-a/fields", headers=LOCAL_ORIGIN)
    assert r.json() == {"fields": detected, "edited": False}


def test_fields_routes_refuse_bad_input_unknown_files_and_foreign_origins(
    client, app, fake_archive
):
    add_scan(app, fake_archive)
    r = client.put(
        "/api/files/id-a/fields",
        json={"fields": [field("total", "abc")]},
        headers=LOCAL_ORIGIN,
    )
    assert r.status_code == 400 and "total" in r.json()["error"]
    bad_kind = {"fields": [field("nope", "1")]}
    r = client.put("/api/files/id-a/fields", json=bad_kind, headers=LOCAL_ORIGIN)
    assert r.status_code == 422
    assert client.get("/api/files/nope/fields").status_code == 404
    r = client.put("/api/files/nope/fields", json={"fields": []}, headers=LOCAL_ORIGIN)
    assert r.status_code == 404
    assert client.delete("/api/files/nope/fields", headers=LOCAL_ORIGIN).status_code == 404
    foreign = {"Origin": "http://evil.example"}
    r = client.put("/api/files/id-a/fields", json={"fields": []}, headers=foreign)
    assert r.status_code == 403
    assert client.delete("/api/files/id-a/fields", headers=foreign).status_code == 403
    assert app.scan_fields.get("id-a")["edited"] is False


# --- migration -----------------------------------------------------------------------


def test_migration_0017_upgrades_a_db_at_0016(tmp_path: Path):
    engine = make_engine(tmp_path / "old.sqlite")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with write_tx(engine) as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "0016")
    migrate(engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0042"
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(file_fields)"))]
    assert cols == ["drive_id", "fields", "updated"]
    engine.dispose()
