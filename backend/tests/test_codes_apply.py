"""Filing codes are the strongest suggestion source (``dam.codes.apply``)."""

from datetime import date

from fastapi.testclient import TestClient

from dam.ai.tasks._common import rules_point_excluded
from dam.api import create_api
from dam.codes.apply import CodeHit, apply_codes, codes_for
from dam.codes.batch import marked_rows
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
    add_in(app, fake_archive, f"{INBOX}/To pay/bill.pdf", "b1", NORTHPOWER_BILL)
    found = app.inbox.suggestion("b1")
    assert found.folder == "10. Financial/Northpower"
    assert found.folder_source == "rule:northpower"
    # the text's date (Eräpäivä 15.11.2026) through the rule's name template
    assert (found.name, found.name_source) == ("20261115_Northpower.pdf", "rule:northpower")
    assert found.tray == "to-pay"
    assert found.tray_source == "code:P"
    assert found.conflict is False


def test_as_suggested_keeps_the_suggestion_and_clears_the_tray(app, fake_archive):
    add_rule(app, folder="10. Financial/Northpower", tags=["energy"], tray="to-pay")
    add_in(app, fake_archive, f"{INBOX}/bill.pdf", "b0", NORTHPOWER_BILL)
    add_in(app, fake_archive, f"{INBOX}/File as suggested/bill.pdf", "b1", NORTHPOWER_BILL)
    plain = app.inbox.suggestion("b0")
    found = app.inbox.suggestion("b1")
    assert plain.tray == "to-pay"
    assert found.codes == [CodeHit("D", "folder")]
    assert (found.folder, found.name, found.tags) == (plain.folder, plain.name, plain.tags)
    assert (found.folder_source, found.name_source) == (plain.folder_source, plain.name_source)
    # "already handled": a paid bill marked D does not land in To pay
    assert (found.tray, found.tray_source) == (None, "code:D")
    assert found.conflict is False
    [row] = marked_rows(app)
    assert row.drive_id == "b1"
    assert row.request.tray is None
    assert row.tray_fields == {}
    # Today's "Found in the inbox" no longer offers the tray for it (the scan alone
    # would guess To pay: due date, amount and IBAN)
    guesses = {e.record.drive_id: e.tray_guess for e in app.inbox.list()}
    assert guesses == {"b0": "to-pay", "b1": None}
    assert [f.drive_id for f in app.today.found_in_inbox()] == ["b0"]


def test_as_suggested_alone_clears_a_scan_tray_guess(app, fake_archive):
    add_in(app, fake_archive, f"{INBOX}/File as suggested/bill.pdf", "b1", NORTHPOWER_BILL)
    [entry] = app.inbox.list()
    assert entry.suggestion.tray is None
    assert entry.tray_guess is None
    assert app.today.found_in_inbox() == []


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


def name_code(template):
    return {"N": FilingCode(code="N", name=template)}


def test_code_name_skips_a_conventional_name():
    out = apply_codes(
        Suggestion(name="20261015_bill.pdf"),
        [CodeHit("N", "folder")],
        name_code("{doc_date:%Y%m%d}_{stem}"),
        date(2026, 10, 15),
        "20261015_bill",
        "pdf",
        SPECIAL,
    )
    assert (out.name, out.name_source) == ("20261015_bill.pdf", "scan")


def test_code_name_renames_a_non_conventional_name():
    out = apply_codes(
        Suggestion(name="bill.pdf"),
        [CodeHit("N", "folder")],
        name_code("{doc_date:%Y%m%d}_{stem}"),
        date(2026, 10, 15),
        "bill",
        "pdf",
        SPECIAL,
    )
    assert (out.name, out.name_source) == ("20261015_bill.pdf", "code:N")


def test_ai_guard_checks_the_rule_folder_under_a_code_folder(app, fake_archive):
    app.settings.ai.exclude_folders = ["50. Medical"]
    add_rule(app, folder="50. Medical/Lab")
    set_code(app, "P", folder="Bills/{year}")
    add_in(app, fake_archive, f"{INBOX}/To pay/bill.pdf", "b1", NORTHPOWER_BILL)
    found = app.inbox.suggestion("b1")
    assert (found.folder, found.folder_before_codes) == ("Bills/2026", "50. Medical/Lab")
    why = rules_point_excluded(app, app.repo.get("b1"))
    assert why is not None and "50. Medical/Lab" in why and "never sent" in why


def test_ai_guard_checks_the_code_folder(app, fake_archive):
    app.settings.ai.exclude_folders = ["50. Medical"]
    add_rule(app, folder="10. Financial/Northpower")
    set_code(app, "P", folder="50. Medical/{year}")
    add_in(app, fake_archive, f"{INBOX}/To pay/bill.pdf", "b1", NORTHPOWER_BILL)
    why = rules_point_excluded(app, app.repo.get("b1"))
    assert why is not None and "50. Medical/2026" in why


SEVERAL = {
    "P": FilingCode(code="P", tray="to-pay"),
    "D": FilingCode(code="D", as_suggested=True),
    "X": FilingCode(code="X", folder="Bills/{year}", tags=["bill"]),
}


def several(*hits):
    base = Suggestion(name="bill.pdf", folder="Rule/Folder", folder_source="rule:r")
    return apply_codes(base, list(hits), SEVERAL, date(2026, 10, 15), "bill", "pdf", SPECIAL)


def test_as_suggested_and_tray_code_conflict():
    assert several(CodeHit("P", "folder"), CodeHit("D", "pen", raw="D")).conflict is True
    assert several(CodeHit("D", "folder"), CodeHit("P", "pen", raw="P")).conflict is True


def test_as_suggested_sets_no_tray():
    out = several(CodeHit("D", "folder"), CodeHit("D", "pen", raw="D"))
    assert (out.tray, out.tray_source) == (None, "code:D")
    assert (out.folder, out.name) == ("Rule/Folder", "bill.pdf")


def test_same_codes_twice_do_not_conflict():
    assert several(CodeHit("D", "folder"), CodeHit("D", "pen", raw="D")).conflict is False
    out = several(CodeHit("P", "folder"), CodeHit("P", "qr", raw="P"))
    assert out.conflict is False
    assert out.tray == "to-pay"


def test_tray_code_and_folder_code_combine():
    out = several(CodeHit("P", "folder"), CodeHit("X", "pen", raw="X"))
    assert out.conflict is False
    assert (out.tray, out.tray_source) == ("to-pay", "code:P")
    assert (out.folder, out.folder_source) == ("Bills/2026", "code:X")
    assert out.tags == ["bill"]
