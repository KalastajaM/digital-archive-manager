"""Page-1 positions: the text layer and OCR give lines with boxes, stored per content."""

import sys
import types
from pathlib import Path

import pypdfium2
import pytest
from PIL import Image

from dam.extract import ocr
from dam.extract.base import ExtractedText, UnsupportedContent
from dam.extract.layout import (
    Line,
    Page1Layout,
    clamp_box,
    in_zone,
    lines_in_zone,
    text_layer_lines,
)
from dam.extract.ocr import ImageOcrExtractor
from dam.extract.pdf import PdfExtractor
from pdfs import make_layout_pdf, make_scan_pdf, make_text_pdf

LANGS = ["fi-FI", "en-US"]


# --- geometry ---------------------------------------------------------------------


def test_a_line_is_in_the_box_by_half_its_area_with_a_margin():
    box = (0.1, 0.1, 0.5, 0.2)
    assert in_zone(Line("a", (0.12, 0.12, 0.3, 0.18)), box)
    assert not in_zone(Line("b", (0.12, 0.5, 0.3, 0.55)), box)
    # just outside the box, but inside the 3 % margin
    assert in_zone(Line("c", (0.12, 0.21, 0.3, 0.225)), box)
    # half in, half out of the grown box: counts; a bit less than half: does not
    grown_right = 0.5 + 0.03
    assert in_zone(Line("d", (grown_right - 0.1, 0.12, grown_right + 0.1, 0.18)), box)
    assert not in_zone(Line("e", (grown_right - 0.09, 0.12, grown_right + 0.11, 0.18)), box)
    assert [ln.text for ln in lines_in_zone([Line("a", (0.2, 0.12, 0.3, 0.18))], box)] == ["a"]


def test_flat_lines_and_clamping():
    assert clamp_box((-1, 0.5, 2, 0.1)) == (0.0, 0.1, 1.0, 0.5)
    assert in_zone(Line("flat", (0.2, 0.15, 0.4, 0.15)), (0.1, 0.1, 0.5, 0.2))


def test_layout_json_round_trip():
    layout = Page1Layout([Line("Pohjola ääkköset", (0.1, 0.05, 0.4, 0.09))], "vision")
    back = Page1Layout.from_json(layout.lines_json(), "vision")
    assert back.lines == layout.lines and back.source == "vision"
    assert back.text == "Pohjola ääkköset"
    assert Page1Layout.from_json("[]", "text-layer").lines == []


# --- the text layer -----------------------------------------------------------------

ITEMS = [(50, 550, "Pohjola Vakuutus"), (50, 530, "Michiel Visser"), (400, 550, "Page right")]


@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
def test_text_layer_lines_are_placed_as_the_page_is_shown(tmp_path: Path, rotate: int):
    pdf = make_layout_pdf(tmp_path / "p.pdf", ITEMS, rotate=rotate)
    doc = pypdfium2.PdfDocument(str(pdf))
    try:
        page = doc[0]
        width, height = page.get_size()
        lines = text_layer_lines(page)
        page.close()
    finally:
        doc.close()
    assert [ln.text for ln in lines] == ["Pohjola Vakuutus", "Michiel Visser", "Page right"]
    first, second, right = (ln.box for ln in lines)
    assert first[0] == pytest.approx(50 / width, abs=0.01)
    assert first[1] == pytest.approx(1 - 550 / height - 0.02, abs=0.02)  # top left origin
    assert second[1] > first[1] and second[0] == pytest.approx(first[0], abs=0.01)
    assert right[0] > first[2] and right[1] == pytest.approx(first[1], abs=0.01)
    assert all(0 <= v <= 1 for ln in lines for v in ln.box)


def test_a_wide_gap_starts_a_new_line(tmp_path: Path):
    pdf = make_layout_pdf(tmp_path / "p.pdf", [(50, 700, "Left"), (300, 700, "Right")])
    doc = pypdfium2.PdfDocument(str(pdf))
    try:
        page = doc[0]
        assert [ln.text for ln in text_layer_lines(page)] == ["Left", "Right"]
        page.close()
    finally:
        doc.close()


def test_pdf_extractor_gives_page1_from_the_text_layer(tmp_path: Path):
    pdf = make_layout_pdf(tmp_path / "p.pdf", ITEMS)
    got = PdfExtractor(LANGS).extract(pdf, pdf.read_bytes())
    assert got.ocr_used is False
    assert got.page1 is not None and got.page1.source == "text-layer"
    assert [ln.text for ln in got.page1.lines][0] == "Pohjola Vakuutus"
    for line in got.page1.lines:
        assert line.text in got.text  # a word in a zone is always in the indexed text


def test_a_failing_layout_never_fails_the_extraction(tmp_path: Path, monkeypatch):
    from dam.extract import pdf as pdf_module

    def boom(page):
        raise RuntimeError("no boxes")

    monkeypatch.setattr(pdf_module, "text_layer_lines", boom)
    got = PdfExtractor(LANGS).extract(make_text_pdf(tmp_path / "t.pdf"))
    assert "Kotihoito" in got.text and got.page1 is None


# --- OCR ----------------------------------------------------------------------------


def _fake_vision(monkeypatch, results):
    module = types.ModuleType("ocrmac")
    sub = types.ModuleType("ocrmac.ocrmac")

    class OCR:
        def __init__(self, image, language_preference=None, recognition_level=None):
            pass

        def recognize(self):
            return results

    sub.OCR = OCR
    module.ocrmac = sub
    monkeypatch.setitem(sys.modules, "ocrmac", module)
    monkeypatch.setitem(sys.modules, "ocrmac.ocrmac", sub)
    monkeypatch.setattr(ocr, "engine", lambda: ocr.VISION)
    monkeypatch.setattr(ocr, "usable_languages", lambda languages: ["en-US"])


def test_vision_boxes_are_flipped_to_a_top_left_origin(monkeypatch):
    # Vision: x, y, w, h as fractions with the origin at the bottom left
    _fake_vision(
        monkeypatch,
        [("Pohjola", 0.9, [0.1, 0.9, 0.3, 0.05]), ("Lasku", 0.9, [0.1, 0.1, 0.2, 0.04])],
    )
    page = ocr.ocr_page(Image.new("RGB", (10, 10)), LANGS)
    assert page.source == "vision"
    (a, b) = page.lines
    assert a.text == "Pohjola" and a.box == pytest.approx((0.1, 0.05, 0.4, 0.1))
    assert b.box == pytest.approx((0.1, 0.86, 0.3, 0.9))
    assert page.text == "Pohjola\nLasku"


def test_tesseract_words_are_grouped_into_lines(monkeypatch):
    import pytesseract

    data = {
        "text": ["", "Pohjola", "Vakuutus", "Lasku"],
        "block_num": [1, 1, 1, 2],
        "par_num": [1, 1, 1, 1],
        "line_num": [0, 1, 1, 1],
        "left": [0, 100, 300, 100],
        "top": [0, 50, 52, 400],
        "width": [0, 150, 200, 100],
        "height": [0, 40, 38, 40],
    }
    seen = {}

    def fake(image, lang=None, output_type=None):
        seen["lang"] = lang
        return data

    monkeypatch.setattr(pytesseract, "image_to_data", fake)
    monkeypatch.setattr(ocr, "engine", lambda: ocr.TESSERACT)
    page = ocr.ocr_page(Image.new("RGB", (1000, 2000)), LANGS)
    assert seen["lang"] == "fin+eng" and page.source == "tesseract"
    assert [ln.text for ln in page.lines] == ["Pohjola Vakuutus", "Lasku"]
    assert page.lines[0].box == pytest.approx((0.1, 0.025, 0.5, 0.045))


def test_ocr_page_without_an_engine(monkeypatch):
    monkeypatch.setattr(ocr, "engine", lambda: None)
    with pytest.raises(UnsupportedContent, match="no OCR engine"):
        ocr.ocr_page(Image.new("RGB", (4, 4)), LANGS)


def test_scanned_pdf_reads_page_1_once_and_its_text_is_the_lines(tmp_path: Path, monkeypatch):
    calls = []

    def fake(image, languages):
        calls.append(1)
        return Page1Layout(
            [Line("Pohjola", (0.1, 0.1, 0.3, 0.15)), Line("Lasku", (0.1, 0.2, 0.3, 0.25))], "vision"
        )

    monkeypatch.setattr(ocr, "ocr_page", fake)
    monkeypatch.setattr(ocr, "engine", lambda: "vision")
    pdf = make_scan_pdf(tmp_path / "s.pdf")
    got = PdfExtractor(LANGS).extract(pdf, pdf.read_bytes())
    assert got.ocr_used and calls == [1]
    assert got.text == "Pohjola\nLasku" and got.page1.source == "vision"


def test_image_extractor_gives_page1(tmp_path: Path, monkeypatch):
    lines = Page1Layout([Line("Fortum", (0.1, 0.1, 0.3, 0.15))], "tesseract")
    monkeypatch.setattr(ocr, "ocr_page", lambda image, languages: lines)
    monkeypatch.setattr(ocr, "engine", lambda: "tesseract")
    png = tmp_path / "a.png"
    Image.new("RGB", (20, 20), "white").save(png)
    got = ImageOcrExtractor(LANGS).extract(png)
    assert got == ExtractedText("Fortum", "image-ocr", True, lines)


# --- storage ------------------------------------------------------------------------

from sqlalchemy import text  # noqa: E402

from dam.index.repo import FileRecord, FileRepo  # noqa: E402

INBOX = "##. Organize"


def _repo(engine) -> FileRepo:
    return FileRepo(engine, inbox=INBOX)


def _file(repo, drive_id, rel="10. Home/a.pdf", ext="pdf"):
    repo.upsert(FileRecord(drive_id=drive_id, path=rel, ext=ext, name=Path(rel).name))


LAYOUT = Page1Layout([Line("Pohjola", (0.1, 0.05, 0.3, 0.08))], "text-layer")


def test_save_content_stores_the_layout_with_the_text(engine):
    repo = _repo(engine)
    _file(repo, "a")
    repo.save_content("a", "sha1", ExtractedText("Pohjola", "pdf", False, LAYOUT), "indexed")
    assert repo.layout_for("a") == LAYOUT
    assert repo.layouts_for(["a", "zzz"]) == {"a": LAYOUT}
    # the same text without a layout leaves the earlier row alone (it is for the same sha)
    repo.save_content("a", "sha1", ExtractedText("Pohjola", "pdf"), "indexed")
    assert repo.layout_for("a") == LAYOUT


def test_a_layout_for_other_content_is_ignored(engine):
    repo = _repo(engine)
    _file(repo, "a")
    repo.save_content("a", "sha1", ExtractedText("x", "pdf", False, LAYOUT), "indexed")
    repo.save_content("a", "sha2", ExtractedText("x", "pdf"), "indexed")
    assert repo.layout_for("a") is None
    assert repo.save_layout("a", "sha1", LAYOUT) is False
    assert repo.save_layout("a", "sha2", Page1Layout([], "text-layer")) is True
    assert repo.layout_for("a") == Page1Layout([], "text-layer")  # read, no text


def test_layout_rows_go_with_the_file(engine):
    repo = _repo(engine)
    _file(repo, "a")
    repo.save_content("a", "s", ExtractedText("x", "pdf", False, LAYOUT), "indexed")
    repo.park("10. Home/a.pdf")
    repo.purge_parked()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM file_layouts")).scalar() == 0


def test_rekey_carries_the_layout(engine):
    repo = _repo(engine)
    _file(repo, "old")
    repo.save_content("old", "s", ExtractedText("x", "pdf", False, LAYOUT), "indexed")
    repo.rekey("old", "new")
    assert repo.layout_for("new") == LAYOUT


def test_next_for_layouts_orders_inbox_then_wanted_then_path(engine):
    repo = _repo(engine)
    for drive_id, rel in (
        ("z", "10. Home/z.pdf"),
        ("w", "20. Work/w.pdf"),
        ("a", "10. Home/a.pdf"),
        ("i", f"{INBOX}/i.pdf"),
        ("t", f"{INBOX}/t.txt"),
    ):
        _file(repo, drive_id, rel, ext=Path(rel).suffix.lstrip("."))
        repo.save_content(drive_id, f"sha-{drive_id}", ExtractedText("x", "x"), "indexed")
    assert [r.drive_id for r in repo.next_for_layouts(10, wanted={"w"})] == ["i", "w", "a", "z"]
    assert [r.drive_id for r in repo.next_for_layouts(10, wanted={"w"}, everything=False)] == [
        "i",
        "w",
    ]
    assert [r.drive_id for r in repo.next_for_layouts(10, skip={"i"})] == ["a", "z", "w"]
    repo.save_layout("a", "sha-a", LAYOUT)
    assert [r.drive_id for r in repo.next_for_layouts(10)] == ["i", "z", "w"]
    assert repo.layout_progress() == (1, 4)


def test_migration_0028_adds_the_table(engine):
    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(file_layouts)"))]
    assert cols == ["drive_id", "sha256", "lines", "source", "read_at"]
