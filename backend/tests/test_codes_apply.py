"""Filing codes are the strongest suggestion source (``dam.codes.apply``)."""

import dataclasses
from datetime import date

from fastapi.testclient import TestClient

from dam.api import create_api
from dam.codes.apply import CodeHit, apply_codes, codes_for
from dam.codes.model import FilingCode
from dam.config import SpecialFolders
from dam.rules.engine import Suggestion
from test_api import BASE
from test_inbox import NORTHPOWER_BILL, add_rule

INBOX = SpecialFolders().inbox
SPECIAL = SpecialFolders()


def add_in(app, fake_archive, rel, drive_id, text):
    from dam.extract.base import ExtractedText

    fake_archive.add(rel, content=drive_id.encode(), drive_id=drive_id)
    app.scan()
    app.repo.save_content(drive_id, None, ExtractedText(text, "test"), "indexed")


def set_code(app, code, **fields):
    codes = [c if c.code != code else c.model_copy(update=fields) for c in app.codes]
    assert app.save_codes(codes) == []


def test_code_folder_beats_rule(app, fake_archive):
    add_rule(app, folder="10. Financial/Northpower")
    set_code(app, "P", folder="Bills/{year}")
    add_in(app, fake_archive, f"{INBOX}/To pay/20261015_bill.pdf", "b1", NORTHPOWER_BILL)
    found = app.inbox.suggestion("b1")
    assert found.folder == "Bills/2026"
    assert found.folder_source == "code:P"
    assert "code:P" in found.sources
    assert found.codes == [CodeHit("P", "folder")]


def test_unset_fields_fall_back(app, fake_archive):
    add_rule(app, folder="10. Financial/Northpower", name="{doc_date:%Y%m%d}_Northpower")
    add_in(app, fake_archive, f"{INBOX}/To pay/20261015_bill.pdf", "b1", NORTHPOWER_BILL)
    found = app.inbox.suggestion("b1")
    assert found.folder == "10. Financial/Northpower"
    assert found.folder_source == "rule:northpower"
    # the name is already conventional, so the rule's name template is not used
    assert (found.name, found.name_source) == ("20261015_bill.pdf", "scan")
    assert found.tray == "to-pay"
    assert found.tray_source == "code:P"
    assert found.conflict is False


def test_as_suggested_changes_nothing(app, fake_archive):
    add_rule(app, folder="10. Financial/Northpower", tags=["energy"])
    add_in(app, fake_archive, f"{INBOX}/bill.pdf", "b0", NORTHPOWER_BILL)
    add_in(app, fake_archive, f"{INBOX}/File as suggested/bill.pdf", "b1", NORTHPOWER_BILL)
    plain = app.inbox.suggestion("b0")
    found = app.inbox.suggestion("b1")
    assert found.codes == [CodeHit("F", "folder")]
    assert dataclasses.replace(found, codes=[]) == plain


def test_two_codes_conflict_on_folder():
    codes = {
        "A": FilingCode(code="A", folder="Bills/{year}", tags=["x"], collections=["C1"]),
        "B": FilingCode(code="B", folder="Receipts", tags=["y", "x"], collections=["C2"]),
    }
    base = Suggestion(name="20261015_bill.pdf", folder="Rule/Folder", folder_source="rule:r")
    hits = [CodeHit("A", "folder"), CodeHit("B", "pen", raw="B")]
    out = apply_codes(base, hits, codes, date(2026, 10, 15), "bill", "pdf", SPECIAL)
    assert out.conflict is True
    assert out.folder == "Bills/2026"
    assert out.folder_source == "code:A"
    assert out.tags == ["x", "y"]
    assert out.tag_sources == {"x": "code:A", "y": "code:B"}
    assert out.collections == ["C1", "C2"]
    assert out.collection_sources == {"C1": "code:A", "C2": "code:B"}
    assert out.codes == hits


def test_same_value_from_two_codes_is_no_conflict():
    codes = {
        "A": FilingCode(code="A", folder="Bills/{year}"),
        "B": FilingCode(code="B", folder="Bills/2026"),
    }
    base = Suggestion(name="bill.pdf")
    hits = [CodeHit("A", "folder"), CodeHit("B", "qr")]
    out = apply_codes(base, hits, codes, date(2026, 10, 15), "bill", "pdf", SPECIAL)
    assert out.conflict is False
    assert out.folder == "Bills/2026"


def test_code_name_template_and_template_error():
    codes = {
        "N": FilingCode(code="N", name="{doc_date:%Y%m%d}_Invoice", folder="Bills/{year}"),
    }
    base = Suggestion(name="bill.pdf", folder="Rule/Folder", folder_source="rule:r")
    out = apply_codes(
        base, [CodeHit("N", "folder")], codes, date(2026, 10, 15), "bill", "pdf", SPECIAL
    )
    assert out.name == "20261015_Invoice.pdf"
    assert out.name_source == "code:N"
    # no date: both templates fail to render; the rule's fields stay, the source notes it
    out = apply_codes(
        Suggestion(name="bill.pdf", folder="Rule/Folder", folder_source="rule:r"),
        [CodeHit("N", "folder")],
        codes,
        None,
        "bill",
        "pdf",
        SPECIAL,
    )
    assert out.name == "bill.pdf"
    assert out.folder == "Rule/Folder"
    assert out.folder_source == "rule:r"
    assert "code:N (template error)" in out.sources


def test_unknown_code_is_kept_as_hit_but_sets_nothing():
    base = Suggestion(name="bill.pdf")
    out = apply_codes(base, [CodeHit("Q", "pen", raw="Q")], {}, None, "bill", "pdf", SPECIAL)
    assert out.codes == [CodeHit("Q", "pen", raw="Q")]
    assert out.folder is None and out.tray is None


def test_codes_for_gives_the_folder_hit(app, fake_archive):
    add_in(app, fake_archive, f"{INBOX}/To pay/bill.pdf", "b1", "x")
    add_in(app, fake_archive, f"{INBOX}/scan.pdf", "s1", "x")
    assert codes_for(app, app.repo.get("b1")) == [CodeHit("P", "folder")]
    assert codes_for(app.repo, app.repo.get("s1")) == []


def test_api_inbox_entry_has_code_fields(app, fake_archive):
    add_in(app, fake_archive, f"{INBOX}/To pay/bill.pdf", "b1", NORTHPOWER_BILL)
    with TestClient(create_api(app), base_url=BASE) as client:
        rows = client.get("/api/inbox").json()
    (row,) = [r for r in rows if r["record"]["path"] == f"{INBOX}/To pay/bill.pdf"]
    s = row["suggestion"]
    assert s["tray"] == "to-pay"
    assert s["tray_source"] == "code:P"
    assert s["codes"][0]["via"] == "folder"
    assert s["codes"][0]["code"] == "P"
    assert s["conflict"] is False
    assert s["collections"] == []
    assert s["collection_sources"] == {}
    assert row["tray_guess"] == "to-pay"
