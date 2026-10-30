import xattr
import yaml

from dam.config import SpecialFolders
from dam.index.driveid import DRIVE_ID_XATTR
from make_demo_archive import build


def test_build_demo_archive(tmp_path):
    archive, data_dir = build(tmp_path / "demo")
    special = SpecialFolders()
    for name in (special.inbox, special.ongoing, special.important, special.quarantine):
        assert (archive / name).is_dir()
    files = [p for p in archive.rglob("*") if p.is_file() and not p.is_symlink()]
    assert 8 <= len(files) <= 24
    for path in files:
        assert xattr.getxattr(path, DRIVE_ID_XATTR).decode().startswith("demo-")
    inbox_pdfs = list((archive / special.inbox).glob("*.pdf"))
    assert inbox_pdfs and inbox_pdfs[0].read_bytes().startswith(b"%PDF")
    settings = yaml.safe_load((data_dir / "config" / "settings.yaml").read_text(encoding="utf-8"))
    assert settings["archive_root"] == str(archive)
    assert settings["reminders"]["mac"] is False


def test_build_refuses_a_non_empty_dir(tmp_path):
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "x").write_text("x", encoding="utf-8")
    try:
        build(tmp_path / "demo")
    except SystemExit as e:
        assert "not empty" in str(e)
    else:
        raise AssertionError("expected SystemExit")


def test_build_refuses_a_file(tmp_path):
    (tmp_path / "demo").write_text("x", encoding="utf-8")
    try:
        build(tmp_path / "demo")
    except SystemExit as e:
        assert "not a directory" in str(e)
    else:
        raise AssertionError("expected SystemExit")


def test_demo_has_the_folder_the_example_rule_suggests(tmp_path):
    archive, _ = build(tmp_path / "demo")
    assert (archive / "11. Bills & Receipts" / "2026").is_dir()


def test_demo_has_a_bill_and_an_ongoing_like_the_real_one(tmp_path):
    archive, _ = build(tmp_path / "demo")
    special = SpecialFolders()
    ongoing = archive / special.ongoing
    links = sorted(p.name for p in ongoing.iterdir() if p.is_symlink())
    assert links == ["2026 Sauna conversion", "Electricity contract"]
    assert (ongoing / "2026 Sauna conversion").is_dir()
    assert (ongoing / "Electricity contract").is_file()
    assert sorted(p.name for p in (ongoing / "Legal").iterdir()) == ["contract.txt", "notes.txt"]
    assert (ongoing / "2026_Plan.txt").is_file() and not (ongoing / "2026_Plan.txt").is_symlink()


def test_bill_text_prefills_a_tray_item(tmp_path):
    from dam.extract.pdf import PdfExtractor
    from dam.rules.fields import detect_fields

    archive, _ = build(tmp_path / "demo")
    pdf = archive / SpecialFolders().inbox / "scan_bill.pdf"
    text = PdfExtractor(["en-US"]).extract(pdf).text
    found = detect_fields(text)
    assert str(found.due_date) == "2026-10-15"
    assert str(found.total) == "84.20"
    assert found.iban == "FI2112345600000785"
    assert found.reference == "RF18539007547034"


def test_ascii_pdf_fixtures_are_byte_identical_to_before(tmp_path):
    import hashlib

    from pdfs import make_text_pdf

    data = make_text_pdf(tmp_path / "a.pdf", "Hello 12,50 EUR").read_bytes()
    assert len(data) == 590
    assert hashlib.sha256(data).hexdigest() == (
        "91c8fe252119103d73222bdfa3b7e73b628824cf55df11bff5925dae12b68271"
    )


def test_demo_has_a_bill_with_a_printed_bank_barcode_the_scan_reads(tmp_path):
    from dam.bills.barcode import parse
    from dam.index.barcodes import read_barcodes
    from make_demo_archive import BARCODE_BILL, BARCODE_CODE

    archive, _ = build(tmp_path / "demo")
    pdf = archive / BARCODE_BILL
    assert pdf.parent == archive / SpecialFolders().inbox
    assert read_barcodes(pdf, "pdf") == [BARCODE_CODE]
    printed = parse(BARCODE_CODE)
    assert printed.iban == "FI2112345600000785"
    assert str(printed.amount) == "47.90"
    assert printed.reference == "12344"
    assert str(printed.due) == "2026-11-05"


def test_demo_has_a_collection_with_nested_collections_published_in_ongoing(tmp_path):
    from dam.app import App
    from make_demo_archive import DEMO_COLLECTION

    archive, data_dir = build(tmp_path / "demo")
    app = App.create(data_dir)
    try:
        c = app.collections.by_name(DEMO_COLLECTION)
        assert c is not None and c.state == "open"
        everything = app.collections.list(None)
        by_id = {x.id: x for x in everything}
        inside = [x for x in everything if x.parent_id == c.id]
        nested = [x for x in everything if x.parent_id in {y.id for y in inside}]
        assert inside and nested, "a collection inside a collection inside the collection"
        assert all(x.parent_id in by_id for x in inside + nested)
        assert c.groups == [] and all(x.groups == [] for x in inside + nested)
        assert c.summary
        inner = {m.drive_id for x in inside + nested for m in x.members}
        assert len(inner) >= 2 and c.members
        # one member is still in the inbox: the attention strip has something to show
        assert any(m.path and m.path.startswith(SpecialFolders().inbox) for m in c.members)
    finally:
        app.close()
    # the inner collections are subfolders of the collection's Ongoing folder, made of links
    folder = archive / SpecialFolders().ongoing / DEMO_COLLECTION
    assert folder.is_dir() and not folder.is_symlink()
    links = [p for p in folder.rglob("*") if p.is_symlink()]
    assert any(len(p.relative_to(folder).parts) >= 3 for p in links), (
        "a link in a nested collection"
    )
