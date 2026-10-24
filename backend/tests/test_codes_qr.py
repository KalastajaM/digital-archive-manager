"""Filing-code QR stickers read off scans: payload, tick boxes, and the barcode pass."""

import hashlib
from pathlib import Path

import zxingcpp
from alembic import command
from alembic.config import Config
from PIL import Image, ImageDraw, ImageOps
from sqlalchemy import text

from dam.bills.barcode import modules
from dam.codes import sticker
from dam.codes.qr import INSET, QrRead, read_qr
from dam.config import Settings
from dam.core.paths import ArchivePaths
from dam.db.engine import MIGRATIONS_DIR, migrate, write_tx
from dam.extract.base import ExtractedText, ExtractorRegistry
from dam.index import barcodes
from dam.index.barcodes import read_page1
from dam.index.content import ContentIndexer
from dam.index.repo import FileRecord, FileRepo
from pdfs import barcode_image
from test_index_barcodes import CODE

PX = 7  # pixels per module: a 21-module QR about 12 mm wide at 300 dpi
LINE = 2  # printed box outline, pixels
INBOX = "##. Organize"


def _qr(text_: str) -> Image.Image:
    barcode = zxingcpp.create_barcode(text_, zxingcpp.BarcodeFormat.QRCode, ec_level="M")
    img = barcode.to_image(scale=PX, add_quiet_zones=False)
    height, width = img.shape
    return Image.frombytes("L", (width, height), bytes(memoryview(img)))


def _box(at: tuple[int, int], name: str) -> tuple[int, int, int, int]:
    """Pixel rect (x0, y0, x1, y1) of tick box ``name`` for a sticker whose QR is at ``at``."""
    x, y, side = sticker.box_rects(1)[name]
    x0, y0 = at[0] + round(x * PX), at[1] + round(y * PX)
    return x0, y0, x0 + round(side * PX), y0 + round(side * PX)


def _inner(rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    inset = round((rect[2] - rect[0]) * INSET) + 1
    return rect[0] + inset, rect[1] + inset, rect[2] - inset, rect[3] - inset


def _page(size=(1240, 900)) -> Image.Image:
    return Image.new("L", size, 255)


def _sticker(page: Image.Image, code: str, layout: int, at=(300, 300)) -> None:
    page.paste(_qr(sticker.payload(code, layout)), at)
    draw = ImageDraw.Draw(page)
    for name in sticker.box_rects(layout):
        draw.rectangle(_box(at, name), outline=0, width=LINE)


def _cross(page: Image.Image, rect) -> None:
    x0, y0, x1, y1 = rect
    draw = ImageDraw.Draw(page)
    draw.line([(x0 + 4, y0 + 4), (x1 - 4, y1 - 4)], fill=0, width=2)
    draw.line([(x0 + 4, y1 - 4), (x1 - 4, y0 + 4)], fill=0, width=2)


def test_plain_sticker_read():
    page = _page()
    _sticker(page, "p", 0)
    assert read_qr(page) == [QrRead("P", 0, None, None)]


def test_boxed_sticker_ticks():
    page = _page()
    _sticker(page, "V3", 1)
    assert read_qr(page) == [QrRead("V3", 1, "empty", "empty")]
    _cross(page, _box((300, 300), "star"))
    assert read_qr(page) == [QrRead("V3", 1, "ticked", "empty")]


def test_rotated_page_still_reads():
    page = _page()
    _sticker(page, "AB", 1)
    _cross(page, _box((300, 300), "important"))
    turned = page.rotate(178, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=255)
    assert read_qr(turned) == [QrRead("AB", 1, "empty", "ticked")]


def test_faint_mark_is_unclear():
    page = _page()
    _sticker(page, "F", 1)
    x0, y0, x1, y1 = _inner(_box((300, 300), "star"))
    area = (x1 - x0) * (y1 - y0)
    dots = [(x0 + 8, y0 + 8), (x0 + 20, y0 + 14), (x0 + 12, y0 + 26)]
    draw = ImageDraw.Draw(page)
    for x, y in dots:
        draw.rectangle([x, y, x + 1, y + 1], fill=0)  # 2 x 2 pixels each
    assert 0.005 < 4 * len(dots) / area < 0.01
    assert read_qr(page) == [QrRead("F", 1, "unclear", "empty")]


def test_box_off_the_page_is_unclear():
    at = (300, 300)
    page = _page()
    _sticker(page, "E", 1, at)
    # cut the page through the important box: its far edge is gone
    rect = _box(at, "important")
    cut = page.crop((0, 0, (rect[0] + rect[2]) // 2, page.height))
    assert read_qr(cut) == [QrRead("E", 1, "empty", "unclear")]


def test_mirrored_sticker_reads_through_the_transposed_frame():
    page = _page()
    _sticker(page, "M", 1)
    _cross(page, _box((300, 300), "important"))
    assert read_qr(ImageOps.mirror(page)) == [QrRead("M", 1, "empty", "ticked")]


def test_boxes_without_outlines_are_unclear():
    page = _page()
    _sticker(page, "W", 1)
    draw = ImageDraw.Draw(page)
    for name in ("star", "important"):
        draw.rectangle(_box((300, 300), name), fill=255)  # outline gone, inside blank
    assert read_qr(page) == [QrRead("W", 1, "unclear", "unclear")]


def test_huge_sticker_is_sampled_cheaply():
    page = _page((2400, 1400))
    big = _qr(sticker.payload("H", 1)).resize((21 * 40, 21 * 40), Image.Resampling.NEAREST)
    page.paste(big, (100, 100))
    draw = ImageDraw.Draw(page)
    for x, y, side in sticker.box_rects(1).values():
        x0, y0 = 100 + x * 40, 100 + y * 40
        draw.rectangle([x0, y0, x0 + side * 40, y0 + side * 40], outline=0, width=6)
    assert read_qr(page) == [QrRead("H", 1, "empty", "empty")]


def test_foreign_qr_ignored():
    page = _page()
    page.paste(_qr("https://example.com"), (100, 100))
    _sticker(page, "K", 0, (600, 500))
    assert read_qr(page) == [QrRead("K", 0, None, None)]
    blank = _page()
    blank.paste(_qr("https://example.com"), (100, 100))
    assert read_qr(blank) == []


def test_bank_barcode_still_read_with_qr(tmp_path: Path):
    sheet = _page((2480, 3508))
    sheet.paste(barcode_image(modules(CODE)), (300, 2800))
    _sticker(sheet, "B1", 1, (1800, 200))
    _cross(sheet, _box((1800, 200), "star"))
    pdf = tmp_path / "bill.pdf"
    sheet.save(pdf, "PDF", resolution=300)
    found = ([CODE], [QrRead("B1", 1, "ticked", "empty")])
    assert read_page1(pdf, "pdf", pdf.read_bytes()) == found
    png = tmp_path / "bill.png"
    sheet.save(png)
    assert read_page1(png, "png") == found


def test_a_failing_qr_read_keeps_the_bank_code(tmp_path: Path, monkeypatch, caplog):
    def boom(_image):
        raise RuntimeError("qr exploded")

    monkeypatch.setattr(barcodes, "read_qr", boom)
    sheet = _page((2480, 3508))
    sheet.paste(barcode_image(modules(CODE)), (300, 2800))
    png = tmp_path / "bill.png"
    sheet.save(png)
    assert read_page1(png, "png") == ([CODE], [])
    assert "QR sticker reading failed" in caplog.text


def test_qr_only_on_page_one(tmp_path: Path):
    first, second = _page((2480, 3508)), _page((2480, 3508))
    _sticker(second, "Z", 0, (600, 600))
    pdf = tmp_path / "two.pdf"
    first.save(pdf, "PDF", resolution=300, save_all=True, append_images=[second])
    assert read_page1(pdf, "pdf") == ([], [])


def test_unreadable_file_gives_nothing(tmp_path: Path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 not really")
    assert read_page1(bad, "pdf") == ([], [])
    assert read_page1(tmp_path / "x.docx", "docx") == ([], [])


# --- storing: the barcode pass -------------------------------------------------


class _Fake:
    name = "fake"

    def supports(self, path):
        return path.suffix.lower() in {".pdf", ".png"}

    def extract(self, path, data=None):
        return ExtractedText("Kirje", self.name)


def _indexer(fake_archive, engine, trays=()):
    paths = ArchivePaths(fake_archive.root, Settings(archive_root=fake_archive.root))
    repo = FileRepo(engine, inbox=paths.inbox)
    registry = ExtractorRegistry()
    registry.register(_Fake())
    indexer = ContentIndexer(paths, repo, engine, registry, 60, barcode_trays=lambda: trays)
    return repo, indexer


def _sticker_pdf(path: Path, code: str, tick: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet = _page((2480, 3508))
    _sticker(sheet, code, 1, (1800, 200))
    if tick:
        _cross(sheet, _box((1800, 200), tick))
    sheet.save(path, "PDF", resolution=300)
    return path


def _indexed(fake_archive, repo, rel: str, drive_id: str, code: str, tick=None) -> str:
    path = _sticker_pdf(fake_archive.root / rel, code, tick)
    st = path.stat()
    repo.upsert(FileRecord(drive_id=drive_id, path=rel, size=st.st_size, mtime=st.st_mtime))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    repo.save_content(drive_id, sha, ExtractedText("Kirje", "test"), "indexed")
    return sha


def test_pass_records_qr_reads(fake_archive, engine):
    repo, indexer = _indexer(fake_archive, engine)
    _indexed(fake_archive, repo, f"{INBOX}/a.pdf", "d1", "V3", tick="important")
    assert indexer.run_barcodes_once(limit=10) == 1
    assert repo.qr_for("d1") == [QrRead("V3", 1, "empty", "ticked")]
    assert repo.barcode_for("d1") is None
    assert indexer.run_barcodes_once(limit=10) == 0


def test_reads_recorded_per_content(fake_archive, engine):
    repo, indexer = _indexer(fake_archive, engine)
    sha = _indexed(fake_archive, repo, f"{INBOX}/a.pdf", "d1", "V3")
    reads = [QrRead("V3", 1, "ticked", "unclear"), QrRead("P", 0, None, None)]
    assert repo.qr_for("d1") == []
    assert repo.save_qr("d1", sha, reads) is True
    assert repo.qr_for("d1") == reads
    assert repo.save_qr("d1", "stale-sha", []) is False
    assert repo.qr_for("d1") == reads
    with write_tx(engine) as conn:
        conn.execute(text("UPDATE files SET sha256 = 'other' WHERE drive_id = 'd1'"))
    assert repo.qr_for("d1") == []  # the row is for other content: ignored
    assert [r.drive_id for r in repo.next_for_barcodes(10, [])] == ["d1"]
    assert repo.save_qr("d1", "other", []) is True
    assert repo.qr_for("d1") == []
    with engine.connect() as conn:
        assert conn.execute(text("SELECT reads FROM file_qr_codes")).scalar() == "[]"


def test_existing_inbox_file_gets_qr_read_once(fake_archive, engine):
    repo, indexer = _indexer(fake_archive, engine, trays=["to-pay"])
    # read by the bank-barcode pass before 0026: a barcode row, no QR row
    sha = _indexed(fake_archive, repo, f"{INBOX}/a.pdf", "d1", "AB", tick="star")
    repo.save_barcode("d1", sha, None)
    # an open item's file outside the inbox is not read again for QR stickers
    other = _indexed(fake_archive, repo, "10. Financial/b.pdf", "d2", "CD")
    repo.save_barcode("d2", other, None)
    with write_tx(engine) as conn:
        conn.execute(
            text(
                "INSERT INTO items(id, tray_id, title, fields, state, created) "
                "VALUES (1, 'to-pay', 't', '{}', 'open', 1)"
            )
        )
        conn.execute(text("INSERT INTO item_files(item_id, drive_id) VALUES (1, 'd2')"))
    assert [r.drive_id for r in repo.next_for_barcodes(10, ["to-pay"])] == ["d1"]
    assert indexer.run_barcodes_once(limit=10) == 1
    assert repo.qr_for("d1") == [QrRead("AB", 1, "ticked", "empty")]
    assert repo.qr_for("d2") == []
    assert indexer.run_barcodes_once(limit=10) == 0


def test_rekey_and_purge_carry_the_reads(fake_archive, engine):
    repo, indexer = _indexer(fake_archive, engine)
    _indexed(fake_archive, repo, f"{INBOX}/a.pdf", "tmp-1", "V3")
    indexer.run_barcodes_once()
    repo.rekey("tmp-1", "real-1")
    assert repo.qr_for("real-1") == [QrRead("V3", 1, "empty", "empty")]
    repo.park(f"{INBOX}/a.pdf")
    repo.purge_parked()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM file_qr_codes")).scalar() == 0


def test_migration_0026_adds_the_table(tmp_path: Path, new_engine):
    engine = new_engine(tmp_path / "old.sqlite")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with write_tx(engine) as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "0025")
    with write_tx(engine) as conn:
        conn.execute(
            text("INSERT INTO files(drive_id, path, path_nfc, name) VALUES ('d1','a','a','a')")
        )
        conn.execute(text("INSERT INTO file_barcodes VALUES ('d1', NULL, 's', 1.0)"))
    migrate(engine)
    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(file_qr_codes)"))]
        assert conn.execute(text("SELECT count(*) FROM file_barcodes")).scalar() == 1
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0030"
    assert cols == ["drive_id", "sha256", "reads", "read_at"]
    engine.dispose()
