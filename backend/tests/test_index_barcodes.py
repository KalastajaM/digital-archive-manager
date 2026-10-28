"""Bank barcodes read from scans: decoding, storing at index time, prefill, item API."""

import hashlib
import logging
import threading
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
import xattr
import zxingcpp
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from dam.api import create_api
from dam.bills.barcode import PATTERNS, build, modules
from dam.config import Settings
from dam.core.paths import ArchivePaths
from dam.db.engine import MIGRATIONS_DIR, migrate, write_tx
from dam.extract.base import ExtractedText, ExtractorRegistry
from dam.index import barcodes, content
from dam.index.barcodes import read_barcodes
from dam.index.content import ContentIndexer
from dam.index.driveid import DRIVE_ID_XATTR
from dam.index.repo import FileRecord, FileRepo
from dam.index.scanner import scan
from dam.rules.fields import DetectedFields
from dam.services.inbox import prefill_of
from pdfs import barcode_image, make_barcode_pdf, make_text_pdf
from test_barcode import GUIDE

NOW = 1_000_000.0
INBOX = "##. Organize"
CODE = build("FI79 4405 2020 0360 82", Decimal("4883.15"), "86851 62596 19897", date(2010, 6, 12))
RF_CODE = build("FI58 1017 1000 0001 22", Decimal("482.99"), "RF06559582243294671", None)
# a valid Code 128 set C symbol that is not a bank barcode
OTHER = [w for v in (105, 12, 34, (105 + 12 + 2 * 34) % 103, 106) for w in PATTERNS[v]]


# --- reading -------------------------------------------------------------------


def test_reads_the_code_drawn_from_modules_in_a_pdf(tmp_path: Path):
    pdf = make_barcode_pdf(tmp_path / "bill.pdf", modules(CODE))
    assert read_barcodes(pdf, "pdf") == [CODE]


def test_reads_page_two_but_not_page_three(tmp_path: Path):
    assert read_barcodes(make_barcode_pdf(tmp_path / "p2.pdf", modules(RF_CODE), 2), "pdf") == [
        RF_CODE
    ]
    assert read_barcodes(make_barcode_pdf(tmp_path / "p3.pdf", modules(RF_CODE), 3), "pdf") == []


@pytest.mark.parametrize("code", [g[4] for g in GUIDE], ids=lambda c: c[:1] + c[-6:])
def test_zxing_decodes_every_guide_code_drawn_from_modules(tmp_path: Path, code: str):
    path = tmp_path / "guide.png"
    barcode_image(modules(code)).save(path)
    assert read_barcodes(path, "png") == [code]
    hits = zxingcpp.read_barcodes(barcode_image(modules(code)))
    assert [(h.format, h.text) for h in hits] == [(zxingcpp.BarcodeFormat.Code128, code)]


@pytest.mark.parametrize("ext", ["png", "jpg"])
def test_reads_images(tmp_path: Path, ext: str):
    path = tmp_path / f"bill.{ext}"
    barcode_image(modules(CODE)).convert("RGB").save(path)
    assert read_barcodes(path, ext) == [CODE]


def test_keeps_only_bank_barcodes(tmp_path: Path):
    pdf = make_barcode_pdf(tmp_path / "other.pdf", OTHER)
    assert read_barcodes(pdf, "pdf") == []


def test_unreadable_files_give_nothing_and_never_raise(tmp_path: Path, caplog):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 not really")
    with caplog.at_level(logging.WARNING, logger="dam.index.barcodes"):
        assert read_barcodes(bad, "pdf") == []
        assert read_barcodes(tmp_path / "missing.png", "png") == []
    assert "barcode" in caplog.text
    assert read_barcodes(make_text_pdf(tmp_path / "t.pdf"), "pdf") == []
    assert read_barcodes(tmp_path / "x.docx", "docx") == []


# --- indexing: the barcode pass ------------------------------------------------


class _Fake:
    name = "fake"

    def supports(self, path):
        return path.suffix.lower() in {".pdf", ".png"}

    def extract(self, path, data=None):
        return ExtractedText("Lasku 12,00 EUR", self.name)


def _indexer(fake_archive, engine, trays=(), **kw):
    paths = ArchivePaths(fake_archive.root, Settings(archive_root=fake_archive.root))
    repo = FileRepo(engine, inbox=paths.inbox)
    registry = ExtractorRegistry()
    registry.register(_Fake())
    indexer = ContentIndexer(paths, repo, engine, registry, 60, barcode_trays=lambda: trays, **kw)
    return repo, indexer


def _add(fake_archive, repo, rel, drive_id, widths=None):
    path = fake_archive.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if widths is None:
        make_text_pdf(path)
    else:
        make_barcode_pdf(path, widths)
    st = path.stat()
    repo.upsert(FileRecord(drive_id=drive_id, path=rel, size=st.st_size, mtime=st.st_mtime))
    return path


def _indexed_before_0009(fake_archive, repo, rel, drive_id, widths=None):
    """A file indexed by a dam without barcodes: state ``indexed``, sha set, no row."""
    path = _add(fake_archive, repo, rel, drive_id, widths)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    repo.save_content(drive_id, sha, ExtractedText("Lasku", "test"), "indexed")
    return path


def _counting(monkeypatch):
    calls: list[str] = []
    real = content.read_page1

    def counted(path, ext, data=None):
        calls.append(path.name)
        return real(path, ext, data)

    monkeypatch.setattr(content, "read_page1", counted)
    return calls


def _rows(engine):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT drive_id, code, sha256, read_at FROM file_barcodes ORDER BY drive_id")
        ).all()


def test_new_scan_gets_its_code_after_content_indexing(fake_archive, engine):
    repo, indexer = _indexer(fake_archive, engine)
    _add(fake_archive, repo, f"{INBOX}/bill.pdf", "d1", modules(CODE))
    _add(fake_archive, repo, f"{INBOX}/letter.pdf", "d2")
    assert indexer.run_once(now=NOW) == 2
    assert repo.get("d1").index_state == "indexed"
    assert repo.barcode_for("d1") is None  # content first; barcodes come after
    assert indexer.run_barcodes_once(limit=10) == 2
    assert repo.barcode_for("d1") == CODE
    assert repo.barcode_for("d2") is None
    (d1, d2) = _rows(engine)
    assert d1.code == CODE and d1.sha256 == repo.get("d1").sha256 and d1.read_at > 0
    assert d2.code is None and d2.sha256 == repo.get("d2").sha256  # read, none found


def test_backfill_reads_files_indexed_before_0009_once(fake_archive, engine, monkeypatch):
    calls = _counting(monkeypatch)
    repo, indexer = _indexer(fake_archive, engine)
    _indexed_before_0009(fake_archive, repo, f"{INBOX}/bill.pdf", "d1", modules(CODE))
    _indexed_before_0009(fake_archive, repo, f"{INBOX}/letter.pdf", "d2")
    indexer.run_layouts_once = lambda limit=1: 0  # the layout pass is tested on its own
    assert indexer.run_once(now=NOW) == 0  # no content work
    assert indexer.step(now=NOW) == 1 and indexer.step(now=NOW) == 1
    assert repo.barcode_for("d1") == CODE
    assert repo.barcode_for("d2") is None
    assert sorted(calls) == ["bill.pdf", "letter.pdf"]
    assert indexer.step(now=NOW) == 0 and indexer.run_barcodes_once(limit=10) == 0
    assert len(calls) == 2  # never read again while the content is the same


def test_content_work_goes_before_the_barcode_pass(fake_archive, engine, monkeypatch):
    calls = _counting(monkeypatch)
    repo, indexer = _indexer(fake_archive, engine)
    _indexed_before_0009(fake_archive, repo, f"{INBOX}/old.pdf", "d1", modules(CODE))
    _add(fake_archive, repo, f"{INBOX}/new.pdf", "d2", modules(RF_CODE))
    assert indexer.step(now=NOW) == 1
    assert repo.get("d2").index_state == "indexed" and calls == []
    indexer.step(now=NOW)
    indexer.step(now=NOW)
    assert sorted(calls) == ["new.pdf", "old.pdf"]
    assert repo.barcode_for("d1") == CODE and repo.barcode_for("d2") == RF_CODE


def test_scope_is_the_inbox_and_open_items_of_trays_with_an_iban(fake_archive, engine):
    repo, indexer = _indexer(fake_archive, engine, trays=["to-pay"])
    for drive_id in ("a", "b", "c", "d"):
        _indexed_before_0009(
            fake_archive, repo, f"10. Financial/{drive_id}.pdf", drive_id, modules(CODE)
        )
    with write_tx(engine) as conn:
        for item_id, tray, state, drive_id in (
            (1, "to-pay", "open", "a"),
            (2, "to-pay", "done", "b"),
            (3, "letters", "open", "c"),
        ):
            conn.execute(
                text(
                    "INSERT INTO items(id, tray_id, title, fields, state, created) "
                    "VALUES (:id, :tray, 't', '{}', :state, 1)"
                ),
                {"id": item_id, "tray": tray, "state": state},
            )
            conn.execute(
                text("INSERT INTO item_files(item_id, drive_id) VALUES (:id, :d)"),
                {"id": item_id, "d": drive_id},
            )
    assert indexer.run_barcodes_once(limit=10) == 1
    assert [r.drive_id for r in _rows(engine)] == ["a"]


def test_changed_content_is_read_again(fake_archive, engine):
    repo, indexer = _indexer(fake_archive, engine)
    _add(fake_archive, repo, f"{INBOX}/bill.pdf", "d1", modules(CODE))
    indexer.step(now=NOW)
    indexer.step(now=NOW)
    assert repo.barcode_for("d1") == CODE
    _add(fake_archive, repo, f"{INBOX}/bill.pdf", "d1", modules(RF_CODE))
    repo.set_index_state("d1", "pending")
    indexer.step(now=NOW)
    assert repo.barcode_for("d1") is None  # the stored code was for other content
    indexer.step(now=NOW)
    assert repo.barcode_for("d1") == RF_CODE
    _add(fake_archive, repo, f"{INBOX}/bill.pdf", "d1")  # no barcode any more
    repo.set_index_state("d1", "pending")
    indexer.step(now=NOW)
    indexer.step(now=NOW)
    assert repo.barcode_for("d1") is None
    assert _rows(engine)[0].code is None


def test_a_file_changed_since_indexing_is_not_trusted(fake_archive, engine):
    repo, indexer = _indexer(fake_archive, engine)
    _indexed_before_0009(fake_archive, repo, f"{INBOX}/bill.pdf", "d1", modules(CODE))
    make_barcode_pdf(fake_archive.root / INBOX / "bill.pdf", modules(RF_CODE))  # not rescanned
    assert indexer.run_barcodes_once() == 1
    assert repo.barcode_for("d1") is None
    assert indexer.run_barcodes_once() == 0  # marked for this sha: no hot loop


def test_a_code_for_other_content_is_not_returned(fake_archive, engine):
    repo, indexer = _indexer(fake_archive, engine)
    _indexed_before_0009(fake_archive, repo, f"{INBOX}/bill.pdf", "d1", modules(CODE))
    indexer.run_barcodes_once()
    with write_tx(engine) as conn:
        conn.execute(text("UPDATE files SET sha256 = 'other' WHERE drive_id = 'd1'"))
    assert repo.barcode_for("d1") is None
    assert repo.save_barcode("d1", "stale-sha", CODE) is False


def test_barcode_errors_never_break_indexing(fake_archive, engine, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("zxing exploded")

    monkeypatch.setattr(barcodes.zxingcpp, "read_barcodes", boom)
    repo, indexer = _indexer(fake_archive, engine)
    _add(fake_archive, repo, f"{INBOX}/bill.pdf", "d1", modules(CODE))
    assert indexer.step(now=NOW) == 1 and indexer.step(now=NOW) == 1
    assert repo.get("d1").index_state == "indexed"
    assert repo.text_for("d1") == "Lasku 12,00 EUR"
    assert repo.barcode_for("d1") is None


def test_read_barcodes_crash_in_the_pass_is_contained(fake_archive, engine, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(content, "read_page1", boom)
    repo, indexer = _indexer(fake_archive, engine)
    _indexed_before_0009(fake_archive, repo, f"{INBOX}/bill.pdf", "d1", modules(CODE))
    assert indexer.run_barcodes_once() == 1
    assert repo.barcode_for("d1") is None
    assert indexer.run_barcodes_once() == 0  # not retried for the same content


class _Clock:
    """``time`` for content.py, with a monotonic clock the test can move forward."""

    def __init__(self) -> None:
        self.ahead = 0.0

    def monotonic(self) -> float:
        return time.monotonic() + self.ahead

    def __getattr__(self, name):
        return getattr(time, name)


def test_barcode_time_has_its_own_budget(fake_archive, engine, monkeypatch):
    release = threading.Event()

    def slow(*_a, **_k):
        release.wait(5)
        return [CODE], []

    monkeypatch.setattr(content, "read_page1", slow)
    clock = _Clock()
    monkeypatch.setattr(content, "time", clock)
    # extraction's timeout is tiny: barcode reading never runs inside it
    repo, indexer = _indexer(
        fake_archive, engine, extract_timeout_s=0.5, barcode_timeout_s=0.2, barcode_retry_s=600
    )
    _add(fake_archive, repo, f"{INBOX}/bill.pdf", "d1", modules(CODE))
    _indexed_before_0009(fake_archive, repo, f"{INBOX}/other.pdf", "d2", modules(CODE))
    assert indexer.run_once(now=NOW) == 1
    assert repo.get("d1").index_state == "indexed"
    started = time.monotonic()
    assert indexer.run_barcodes_once(limit=10) == 1  # the hung read pauses the pass
    assert time.monotonic() - started < 2
    assert _rows(engine) == []  # a timeout is not "none found": nothing is recorded
    assert indexer.run_barcodes_once(limit=10) == 0  # still busy: nothing new starts
    release.set()
    for _ in range(50):
        if indexer.run_barcodes_once(limit=10):
            break
        time.sleep(0.05)
    # the timed-out file waits for its retry time; the others go on
    assert {r.drive_id: r.code for r in _rows(engine)} == {"d2": CODE}
    assert indexer.run_barcodes_once(limit=10) == 0
    clock.ahead = 601
    assert indexer.run_barcodes_once(limit=10) == 1  # read again, and recorded this time
    assert {r.drive_id: r.code for r in _rows(engine)} == {"d1": CODE, "d2": CODE}


def test_a_finished_read_that_found_nothing_is_recorded(fake_archive, engine, monkeypatch):
    monkeypatch.setattr(content, "read_page1", lambda *_a, **_k: ([], []))
    repo, indexer = _indexer(fake_archive, engine)
    _indexed_before_0009(fake_archive, repo, f"{INBOX}/plain.pdf", "d1", OTHER)
    assert indexer.run_barcodes_once() == 1
    assert [(r.drive_id, r.code) for r in _rows(engine)] == [("d1", None)]
    assert indexer.run_barcodes_once() == 0  # not read again for the same content


def test_rekey_and_purge_carry_the_code(fake_archive, engine):
    repo, indexer = _indexer(fake_archive, engine)
    _indexed_before_0009(fake_archive, repo, f"{INBOX}/bill.pdf", "tmp-1", modules(CODE))
    indexer.run_barcodes_once()
    repo.rekey("tmp-1", "real-1")
    assert repo.barcode_for("real-1") == CODE
    repo.park(f"{INBOX}/bill.pdf")
    repo.purge_parked()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM file_barcodes")).scalar() == 0


def test_app_index_also_runs_the_barcode_pass(app, fake_archive):
    path = fake_archive.root / INBOX / "bill.pdf"
    make_barcode_pdf(path, modules(CODE))
    xattr.setxattr(path, DRIVE_ID_XATTR, b"b1")
    scan(app.paths, app.repo)
    app.registry._extractors.insert(0, _Fake())  # no OCR in this test
    app.index()
    assert app.repo.barcode_for("b1") == CODE


def test_migrations_upgrade_an_existing_db(tmp_path: Path, new_engine):
    engine = new_engine(tmp_path / "old.sqlite")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with write_tx(engine) as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "0008")
    with write_tx(engine) as conn:
        conn.execute(
            text("INSERT INTO files(drive_id, path, path_nfc, name) VALUES ('d1','a','a','a')")
        )
        tables = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master"))}
    assert "file_barcodes" not in tables
    with write_tx(engine) as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "0009")
    with write_tx(engine) as conn:
        conn.execute(text("INSERT INTO file_barcodes VALUES ('d1', :c, 's', 1.0)"), {"c": CODE})
    migrate(engine)
    with engine.connect() as conn:
        cols = {r[1]: r[3] for r in conn.execute(text("PRAGMA table_info(file_barcodes)"))}
        assert conn.execute(text("SELECT count(*) FROM files")).scalar() == 1
        assert conn.execute(text("SELECT code FROM file_barcodes")).scalar() == CODE
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0042"
    assert list(cols) == ["drive_id", "code", "sha256", "read_at"]
    assert cols["code"] == 0 and cols["read_at"] == 1  # code nullable: "none found"
    engine.dispose()


# --- prefill -------------------------------------------------------------------

TEXT_FOUND = DetectedFields(
    iban="FI2112345600000785",
    reference="RF185390075470344",
    due_date=date(2026, 11, 15),
    total=Decimal("84.2"),
)


def test_prefill_prefers_a_valid_barcode():
    out = prefill_of(TEXT_FOUND, "Northpower Oy", CODE)
    assert out == {
        "payee": "Northpower Oy",
        "iban": "FI7944052020036082",
        "total": "4883.15",
        "reference": "868516259619897",
        "due_date": "2010-06-12",
    }


def test_prefill_ignores_an_invalid_barcode_and_keeps_text_values():
    expected = prefill_of(TEXT_FOUND)
    assert prefill_of(TEXT_FOUND, None, "4" + "0" * 53) == expected
    assert prefill_of(TEXT_FOUND, None, None) == expected


def test_prefill_keeps_text_values_the_barcode_does_not_carry():
    # no due date (000000) and "payer chooses" amount (00000000)
    code = build("FI7944052020036082", Decimal("0"), "868516259619897", None)
    out = prefill_of(TEXT_FOUND, None, code)
    assert out["due_date"] == "2026-11-15" and out["total"] == "84.20"
    assert out["iban"] == "FI7944052020036082" and out["reference"] == "868516259619897"


BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}
NORTHPOWER_BILL = (
    "Northpower Oy lasku\nEräpäivä 15.11.2026\nYhteensä 84,20 €\n"
    "IBAN FI21 1234 5600 0007 85\nViitenumero RF18 5390 0754 7034"
)


@pytest.fixture
def client(app):
    with TestClient(create_api(app), base_url=BASE) as c:
        yield c


@pytest.fixture
def scanned(app, fake_archive):
    """s1: a Northpower bill whose scan carries CODE; s2: the same text, no barcode."""
    for drive_id in ("s1", "s2"):
        fake_archive.add(f"{INBOX}/{drive_id}.pdf", content=drive_id.encode(), drive_id=drive_id)
    scan(app.paths, app.repo)
    app.repo.save_content("s1", "sha-s1", ExtractedText(NORTHPOWER_BILL, "test"), "indexed")
    app.repo.save_barcode("s1", "sha-s1", CODE)
    app.repo.save_content("s2", "sha-s2", ExtractedText(NORTHPOWER_BILL, "test"), "indexed")
    return ["s1", "s2"]


def test_inbox_and_quick_items_use_the_barcode(app, client, scanned):
    entries = {e.record.drive_id: e for e in app.inbox.list()}
    assert entries["s1"].prefill["iban"] == "FI7944052020036082"
    assert entries["s2"].prefill["iban"] == "FI2112345600000785"
    assert app.inbox.prefill_for("s1")["total"] == "4883.15"
    r = client.post(
        "/api/items/quick", json={"tray": "to-pay", "drive_ids": ["s1"]}, headers=LOCAL_ORIGIN
    )
    fields = r.json()["created"][0]["fields"]
    assert fields["amount"] == "4883.15" and fields["reference"] == "868516259619897"
    assert fields["due_date"] == "2010-06-12"


def _create(client, drive_ids, fields):
    r = client.post(
        "/api/items",
        json={"tray": "to-pay", "drive_ids": drive_ids, "fields": fields},
        headers=LOCAL_ORIGIN,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


BILL_FIELDS = {
    "iban": "FI79 4405 2020 0360 82",
    "amount": "4883,15",
    "reference": "86851 62596 19897",
    "due_date": "2010-06-12",
}


# the printed CODE's values in the item field formats (as ItemOut sends them)
PRINTED_FIELDS = {
    "iban": "FI7944052020036082",
    "amount": "4883.15",
    "reference": "868516259619897",
    "due_date": "2010-06-12",
}


def test_barcode_api_builds_from_fields_and_reports_agreement(client, scanned):
    item = _create(client, ["s2", "s1"], BILL_FIELDS)
    body = client.get(f"/api/items/{item}/barcode").json()
    assert body == {
        "code": CODE,
        "modules": modules(CODE),
        "reason": None,
        "printed": CODE,
        "printed_fields": PRINTED_FIELDS,
        "mismatch": [],
    }


def test_barcode_api_names_the_fields_that_differ(client, scanned):
    item = _create(client, ["s1"], BILL_FIELDS)
    r = client.patch(
        f"/api/items/{item}",
        json={"fields": {"amount": "1000,00", "due_date": "2010-07-01"}},
        headers=LOCAL_ORIGIN,
    )
    assert r.status_code == 200, r.text
    body = client.get(f"/api/items/{item}/barcode").json()
    assert body["printed"] == CODE
    assert body["code"] == build(
        "FI7944052020036082", Decimal("1000.00"), "868516259619897", date(2010, 7, 1)
    )
    assert body["mismatch"] == ["amount", "due_date"]
    assert body["printed_fields"] == PRINTED_FIELDS


def test_patching_the_printed_values_makes_the_barcode_agree(client, scanned):
    """ "Use the printed barcode's values": PATCH the differing fields from
    ``printed_fields``; afterwards the built code is the printed one."""
    item = _create(client, ["s1"], {**BILL_FIELDS, "amount": "1000,00", "reference": ""})
    body = client.get(f"/api/items/{item}/barcode").json()
    assert body["mismatch"] == ["amount", "reference"]
    patch = {name: body["printed_fields"][name] for name in body["mismatch"]}
    r = client.patch(f"/api/items/{item}", json={"fields": patch}, headers=LOCAL_ORIGIN)
    assert r.status_code == 200, r.text
    assert r.json()["fields"]["amount"] == "4883.15"
    body = client.get(f"/api/items/{item}/barcode").json()
    assert body["mismatch"] == [] and body["code"] == CODE == body["printed"]


def test_printed_fields_leave_out_what_the_barcode_leaves_open(client, app, scanned):
    """An RF code with no due date and a 0 amount (the payer chooses): those fields are
    None, so nothing would be overwritten with them."""
    open_amount = build("FI58 1017 1000 0001 22", Decimal("0"), "RF06559582243294671", None)
    app.repo.save_barcode("s2", "sha-s2", open_amount)
    item = _create(client, ["s2"], {"due_date": "2026-11-01"})
    body = client.get(f"/api/items/{item}/barcode").json()
    assert body["printed_fields"] == {
        "iban": "FI5810171000000122",
        "amount": None,
        "reference": "RF06559582243294671",
        "due_date": None,
    }
    assert body["mismatch"] == ["iban", "reference"]


def test_barcode_api_gives_a_reason_and_no_code(client, scanned):
    item = _create(client, ["s2"], {**BILL_FIELDS, "iban": "DE89 3704 0044 0532 0130 00"})
    body = client.get(f"/api/items/{item}/barcode").json()
    assert body["code"] is None and body["modules"] is None
    assert "Finnish" in body["reason"]
    assert body["printed"] is None and body["mismatch"] == []
    assert body["printed_fields"] is None
    item = _create(client, ["s1"], {"due_date": "2010-06-12"})
    body = client.get(f"/api/items/{item}/barcode").json()
    assert body["code"] is None and body["reason"] == "no IBAN"
    assert body["printed"] == CODE
    assert body["mismatch"] == ["iban", "amount", "reference"]


def test_barcode_api_unknown_item(client):
    assert client.get("/api/items/999/barcode").status_code == 404


def test_a_printed_barcode_guesses_to_pay(app, fake_archive):
    """A letter with no due date or amount in its text, but a bank barcode on it."""
    fake_archive.add(f"{INBOX}/plain.pdf", content=b"p", drive_id="p1")
    scan(app.paths, app.repo)
    app.repo.save_content("p1", "sha-p1", ExtractedText("Hei!", "test"), "indexed")
    assert app.inbox.list()[0].tray_guess is None
    app.repo.save_barcode("p1", "sha-p1", CODE)
    assert app.inbox.list()[0].tray_guess == "to-pay"
