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
from pdfs import make_layout_pdf, make_scan_pdf, make_text_pdf, make_words_pdf

LANGS = ["fi-FI", "en-US"]


# --- geometry ---------------------------------------------------------------------


def test_a_line_is_in_the_box_by_half_its_area_with_a_margin():
    box = (0.1, 0.1, 0.5, 0.2)
    assert in_zone(Line("a", (0.12, 0.12, 0.3, 0.18)), box)
    assert not in_zone(Line("b", (0.12, 0.5, 0.3, 0.55)), box)
    # just outside the box, but inside the 0.6 % margin down
    assert in_zone(Line("c", (0.12, 0.202, 0.3, 0.208)), box)
    # half in, half out of the grown box: counts; a bit less than half: does not
    grown_right = 0.5 + 0.02
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


def test_words_drawn_one_by_one_stay_in_one_line(tmp_path: Path):
    from dam.config import Person
    from dam.rules.people import detect_people

    pdf = make_words_pdf(
        tmp_path / "w.pdf", [(50, 700, "Michiel"), (95, 700, "Visser"), (135, 700, "Kotikatu")]
    )
    doc = pypdfium2.PdfDocument(str(pdf))
    try:
        page = doc[0]
        lines = text_layer_lines(page)
        full = page.get_textpage().get_text_range()
        page.close()
    finally:
        doc.close()
    assert [ln.text for ln in lines] == ["Michiel Visser Kotikatu"]
    assert "Michiel Visser Kotikatu" in full.replace("\r\n", " ")
    layout = Page1Layout(lines, "text-layer")
    zone = (0.0, 0.0, 1.0, 1.0)
    people = [
        Person(name="Michiel", match=["Michiel Visser"]),
        Person(name="Kati", match=["Michiel Visser Kotikatu"]),
    ]
    assert detect_people(layout, zone, people) == ["Michiel", "Kati"]


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


def _rotated_jpeg(path: Path) -> Path:
    exif = Image.Exif()
    exif[0x0112] = 6  # shown turned a quarter clockwise: width and height swap
    Image.new("RGB", (40, 20), "white").save(path, exif=exif)
    return path


def test_exif_orientation_is_applied_before_ocr(tmp_path: Path, monkeypatch):
    from dam.index.layouts import read_layout

    seen = []

    def fake(image, languages):
        seen.append(image.size)
        return Page1Layout([], "vision")

    monkeypatch.setattr(ocr, "ocr_page", fake)
    monkeypatch.setattr(ocr, "engine", lambda: "vision")
    jpg = _rotated_jpeg(tmp_path / "a.jpg")
    ImageOcrExtractor(LANGS).extract(jpg)
    read_layout(jpg, "jpg", jpg.read_bytes(), ocr_used=True, languages=LANGS)
    assert seen == [(20, 40), (20, 40)]


# --- word positions -----------------------------------------------------------------


def test_words_are_kept_in_json_and_old_rows_without_them_still_load():
    from dam.extract.layout import Word

    line = Line(
        "Asiakastiedote 1.11.2019",
        (0.1, 0.1, 0.6, 0.13),
        [Word("Asiakastiedote", (0.1, 0.1, 0.35, 0.13)), Word("1.11.2019", (0.4, 0.1, 0.6, 0.13))],
    )
    back = Page1Layout.from_json(Page1Layout([line], "text-layer").lines_json(), "text-layer")
    assert back.lines == [line]
    old = '[{"text": "Pohjola", "box": [0.1, 0.1, 0.3, 0.13]}]'
    assert Page1Layout.from_json(old, "vision").lines == [Line("Pohjola", (0.1, 0.1, 0.3, 0.13))]
    assert Page1Layout.from_json(old, "vision").lines[0].words == []


def test_in_a_box_only_the_words_inside_count_and_old_lines_count_whole():
    from dam.extract.layout import Word

    line = Line(
        "Asiakastiedote 1.11.2019",
        (0.1, 0.1, 0.6, 0.13),
        [Word("Asiakastiedote", (0.1, 0.1, 0.35, 0.13)), Word("1.11.2019", (0.4, 0.1, 0.6, 0.13))],
    )
    box = (0.08, 0.09, 0.37, 0.14)
    (found,) = lines_in_zone([line], box)
    assert found.text == "Asiakastiedote" and found.box == (0.1, 0.1, 0.35, 0.13)
    # all words inside: the line as it is; no word inside: nothing
    assert lines_in_zone([line], (0, 0, 1, 1)) == [line]
    assert lines_in_zone([line], (0.7, 0.5, 0.9, 0.6)) == []
    # a line without word positions is matched whole, as before
    old = Line(line.text, line.box)
    assert [ln.text for ln in lines_in_zone([old], box)] == ["Asiakastiedote 1.11.2019"]


def test_a_box_around_one_word_of_a_text_layer_line_gives_only_that_word(tmp_path: Path):
    pdf = make_words_pdf(tmp_path / "w.pdf", [(50, 700, "Asiakastiedote"), (138, 700, "1.11.2019")])
    doc = pypdfium2.PdfDocument(str(pdf))
    try:
        page = doc[0]
        lines = text_layer_lines(page)
        page.close()
    finally:
        doc.close()
    (line,) = lines
    assert line.text == "Asiakastiedote 1.11.2019"
    assert [w.text for w in line.words] == ["Asiakastiedote", "1.11.2019"]
    first = line.words[0].box
    assert first[2] < line.words[1].box[0]
    around = (first[0] - 0.005, first[1] - 0.005, first[2] + 0.005, first[3] + 0.005)
    assert [ln.text for ln in lines_in_zone(lines, around, margin=0.0)] == ["Asiakastiedote"]


def test_text_layer_words_split_on_real_spaces_too(tmp_path: Path):
    pdf = make_layout_pdf(tmp_path / "p.pdf", [(50, 550, "Pohjola Vakuutus Oy")])
    doc = pypdfium2.PdfDocument(str(pdf))
    try:
        page = doc[0]
        (line,) = text_layer_lines(page)
        page.close()
    finally:
        doc.close()
    assert [w.text for w in line.words] == ["Pohjola", "Vakuutus", "Oy"]
    assert line.words[0].box[0] == pytest.approx(line.box[0])
    assert line.words[-1].box[2] == pytest.approx(line.box[2])


def test_tesseract_keeps_word_boxes(monkeypatch):
    import pytesseract

    data = {
        "text": ["Pohjola", "Vakuutus"],
        "block_num": [1, 1],
        "par_num": [1, 1],
        "line_num": [1, 1],
        "left": [100, 300],
        "top": [50, 52],
        "width": [150, 200],
        "height": [40, 38],
    }
    monkeypatch.setattr(pytesseract, "image_to_data", lambda *a, **k: data)
    monkeypatch.setattr(ocr, "engine", lambda: ocr.TESSERACT)
    page = ocr.ocr_page(Image.new("RGB", (1000, 2000)), LANGS)
    (line,) = page.lines
    assert [w.text for w in line.words] == ["Pohjola", "Vakuutus"]
    assert line.words[0].box == pytest.approx((0.1, 0.025, 0.25, 0.045))
    assert line.words[1].box == pytest.approx((0.3, 0.026, 0.5, 0.045))


def test_vision_word_boxes_are_estimated_by_character_count(monkeypatch):
    _fake_vision(monkeypatch, [("ab cdef", 0.9, [0.0, 0.9, 0.7, 0.05])])
    page = ocr.ocr_page(Image.new("RGB", (10, 10)), LANGS)
    (line,) = page.lines
    # 7 characters in all: "ab" takes 2/7 of the width, "cdef" the last 4/7
    assert [w.text for w in line.words] == ["ab", "cdef"]
    assert line.words[0].box == pytest.approx((0.0, 0.05, 0.2, 0.1))
    assert line.words[1].box == pytest.approx((0.3, 0.05, 0.7, 0.1))


# --- a box holds what is drawn in it; matching keeps a small margin ---------------------


def _page1_lines(pdf: Path) -> list:
    doc = pypdfium2.PdfDocument(str(pdf))
    try:
        page = doc[0]
        lines = text_layer_lines(page)
        page.close()
    finally:
        doc.close()
    return lines


def _two_lines(tmp_path: Path, name: str, dy: float = 0.0, term_first: bool = True):
    # normal letter spacing: 12 pt type on a 14 pt pitch (about 5 mm on a 792 pt page)
    first, second = ("Vesilaitos Oy - Lasku", "Vesimaksu 10/2026")
    if not term_first:
        first, second = second, first
    pdf = make_words_pdf(tmp_path / name, [(50, 700 - dy, first), (50, 686 - dy, second)])
    return _page1_lines(pdf)


def test_a_box_drawn_tightly_around_one_line_lists_only_that_line(tmp_path: Path):
    lines = _two_lines(tmp_path, "a.pdf")
    assert [ln.text for ln in lines] == ["Vesilaitos Oy - Lasku", "Vesimaksu 10/2026"]
    x0, y0, x1, y1 = lines[0].box
    tight = (x0, y0, x1, y1)
    assert [ln.text for ln in lines_in_zone(lines, tight)] == ["Vesilaitos Oy - Lasku"]
    # a rule from that box would otherwise see the line below on the same letter
    from dam.extract.layout import ZONE_MARGIN

    assert [ln.text for ln in lines_in_zone(lines, tight, ZONE_MARGIN)] == ["Vesilaitos Oy - Lasku"]


def test_a_rule_from_a_tight_box_matches_a_shifted_copy_but_not_the_next_line(tmp_path: Path):
    from dam.extract.layout import ZONE_MARGIN, Page1Layout
    from dam.rules.engine import zone_matches
    from dam.rules.model import Rule

    drawn = _two_lines(tmp_path, "a.pdf")
    rule = Rule.model_validate(
        {
            "id": "vesi",
            "when": {"zones": [{"box": list(drawn[0].box), "text_contains": ["lasku"]}]},
            "then": {"folder": "Water"},
        }
    )
    assert ZONE_MARGIN == (0.02, 0.006)
    same = Page1Layout(drawn, "text-layer")
    shifted = Page1Layout(_two_lines(tmp_path, "b.pdf", dy=8.5), "text-layer")  # about 3 mm
    other = Page1Layout(_two_lines(tmp_path, "c.pdf", term_first=False), "text-layer")
    assert zone_matches(rule, 0, same)
    assert zone_matches(rule, 0, shifted)
    assert not zone_matches(rule, 0, other)
