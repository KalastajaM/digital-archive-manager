"""The page-1 picture in the cache: its name, when it is made (while indexing a scan, in the
layout pass for the rest) and that it is rebuilt when the content changes."""

import hashlib

import pytest
from PIL import Image

from dam.extract import ocr
from dam.extract.layout import Line, Page1Layout
from dam.extract.picture import (
    PICTURE_PAGE_WIDTH,
    have_pictures,
    page_picture,
    picture_name,
    picture_path,
)
from dam.index import content
from dam.index.layouts import render_picture
from dam.rules.picture import load_page
from pdfs import make_layout_pdf
from test_index_layouts import INBOX, _indexed, _indexer


def test_the_cache_name_is_the_drive_id_and_a_sha_prefix_safe_on_every_platform(tmp_path):
    sha = "ab" * 32
    assert picture_name("1AbC-d_e", sha) == "1AbC-d_e-abababababababab.jpg"
    # the colon of a local id is not a valid file name character on Windows
    assert picture_name("local:1234-5678", sha) == "local_1234-5678-abababababababab.jpg"
    assert picture_path(tmp_path, "x", sha) == tmp_path / "page1" / f"x-{sha[:16]}.jpg"


def test_page_picture_is_grayscale_at_a_fixed_width():
    for size, mode in [((2480, 3508), "RGB"), ((400, 300), "L"), ((1000, 1500), "RGBA")]:
        out = page_picture(Image.new(mode, size, "white"))
        assert out.mode == "L" and out.width == PICTURE_PAGE_WIDTH
        assert abs(out.height - size[1] * 1000 / size[0]) <= 1


def test_the_layout_pass_makes_the_picture_of_a_text_layer_pdf_without_ocr(
    fake_archive, engine, tmp_path, monkeypatch
):
    monkeypatch.setattr(ocr, "engine", lambda: None)  # a text layer needs no OCR
    cache = tmp_path / "cache"
    repo, indexer = _indexer(fake_archive, engine, cache_dir=cache)
    _indexed(fake_archive, repo, f"{INBOX}/a.pdf", "d1")
    sha = repo.get("d1").sha256
    assert not have_pictures(cache)
    assert indexer.run_layouts_once() == 1  # the layout, and the picture with it
    path = picture_path(cache, "d1", sha)
    assert path.is_file() and repo.layout_for("d1") is not None
    with Image.open(path) as img:
        assert img.mode == "L" and img.width == PICTURE_PAGE_WIDTH
    assert indexer.run_layouts_once() == 0  # made once per content


def test_a_file_with_a_layout_but_no_picture_gets_only_the_picture(
    fake_archive, engine, tmp_path, monkeypatch
):
    cache = tmp_path / "cache"
    repo, indexer = _indexer(fake_archive, engine, cache_dir=cache)
    _indexed(fake_archive, repo, f"{INBOX}/a.pdf", "d1")
    sha = repo.get("d1").sha256
    repo.save_layout("d1", sha, Page1Layout([Line("Pohjola", (0.1, 0.1, 0.3, 0.15))], "vision"))
    # a read of the layout would need OCR, which is not there: the picture needs none
    monkeypatch.setattr(ocr, "engine", lambda: None)
    assert indexer.run_layouts_once() == 1
    assert picture_path(cache, "d1", sha).is_file()
    assert repo.layout_for("d1").source == "vision"  # the layout is left alone


def test_a_scan_gets_its_picture_from_the_ocr_render(fake_archive, engine, tmp_path, monkeypatch):
    def fake(image, languages):
        layout = Page1Layout([Line("Fortum", (0.1, 0.1, 0.3, 0.15))], "vision")
        layout.picture = page_picture(image)
        return layout

    monkeypatch.setattr(ocr, "ocr_page", fake)
    monkeypatch.setattr(ocr, "engine", lambda: "vision")
    cache = tmp_path / "cache"
    repo, indexer = _indexer(fake_archive, engine, cache_dir=cache)
    _indexed(fake_archive, repo, f"{INBOX}/s.pdf", "d1", ocr_used=True, scan=True)
    assert indexer.run_layouts_once() == 1
    assert picture_path(cache, "d1", repo.get("d1").sha256).is_file()


def test_the_picture_follows_the_content_and_is_rebuilt_when_it_changes(
    fake_archive, engine, tmp_path, monkeypatch
):
    monkeypatch.setattr(ocr, "engine", lambda: None)
    cache = tmp_path / "cache"
    repo, indexer = _indexer(fake_archive, engine, cache_dir=cache)
    path = _indexed(fake_archive, repo, f"{INBOX}/a.pdf", "d1")
    assert indexer.run_layouts_once() == 1
    first = picture_path(cache, "d1", repo.get("d1").sha256)
    assert first.is_file()
    # the file is replaced by another one: a new sha256, so a new picture, the old one is left
    make_layout_pdf(path, [(50, 700, "Fortum Oyj")])
    new_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    repo.save_content("d1", new_sha, content.ExtractedText("Fortum", "t", False), "indexed")
    assert repo.get("d1").sha256 == new_sha != first.stem.split("-")[-1]
    assert indexer.run_layouts_once() == 1
    second = picture_path(cache, "d1", new_sha)
    assert second.is_file() and first.is_file()
    # a picture that is gone is made again
    second.write_bytes(b"")
    second.unlink()
    assert indexer.run_layouts_once() == 1 and second.is_file()


def test_backfill_off_makes_pictures_for_the_inbox_and_wanted_files_only(
    fake_archive, engine, tmp_path
):
    flag = {"on": False}
    cache = tmp_path / "cache"
    repo, indexer = _indexer(
        fake_archive, engine, cache_dir=cache, page1_backfill=lambda: flag["on"]
    )
    for rel, drive_id in [("10. Home/old.pdf", "old"), (f"{INBOX}/new.pdf", "new")]:
        _indexed(fake_archive, repo, rel, drive_id)
        repo.save_layout(drive_id, repo.get(drive_id).sha256, Page1Layout([], "text-layer"))
    assert indexer.run_layouts_once(limit=10) == 1
    names = have_pictures(cache)
    assert [n.split("-")[0] for n in names] == ["new"]
    indexer.want_layouts(["old"])
    assert indexer.run_layouts_once(limit=10) == 1
    assert len(have_pictures(cache)) == 2


def test_a_picture_that_cannot_be_made_is_not_tried_again_and_says_why(
    fake_archive, engine, tmp_path
):
    cache = tmp_path / "cache"
    repo, indexer = _indexer(fake_archive, engine, cache_dir=cache)
    path = _indexed(fake_archive, repo, f"{INBOX}/a.pdf", "d1")
    repo.save_layout("d1", repo.get("d1").sha256, Page1Layout([], "text-layer"))
    path.write_bytes(path.read_bytes()[:50])  # no longer the content that was indexed
    assert indexer.run_layouts_once() == 1
    assert indexer.layout_blocked("d1") == content.LAYOUT_NO_PICTURE
    assert indexer.run_layouts_once() == 0
    assert not have_pictures(cache)


def test_without_a_cache_folder_no_picture_is_kept(fake_archive, engine, tmp_path):
    repo, indexer = _indexer(fake_archive, engine)
    _indexed(fake_archive, repo, f"{INBOX}/a.pdf", "d1")
    assert indexer.run_layouts_once() == 1
    assert not (tmp_path / "cache").exists()


def test_render_picture_follows_the_pages_rotation(tmp_path):
    pytest.importorskip("pypdfium2")
    path = tmp_path / "r.pdf"
    make_layout_pdf(path, [(50, 700, "Pohjola")])
    upright = render_picture(path, "pdf", None)
    assert upright.height > upright.width  # portrait, as the page is shown
    make_layout_pdf(path, [(50, 400, "Pohjola")], mediabox="0 0 792 612", rotate=90)
    turned = render_picture(path, "pdf", None)
    # the page has a /Rotate: the picture is the page as it is shown, not the raw media
    assert turned.width == PICTURE_PAGE_WIDTH and turned.height > turned.width


def test_render_picture_applies_the_exif_orientation(tmp_path):
    path = tmp_path / "p.jpg"
    img = Image.new("RGB", (300, 200), "white")
    exif = Image.Exif()
    exif[0x0112] = 6  # rotated 90 degrees: shown portrait
    img.save(path, exif=exif)
    out = render_picture(path, "jpg", None)
    assert out.height > out.width


def test_a_stored_picture_loads_at_the_matching_width(tmp_path):
    from dam.extract.picture import write_picture
    from dam.rules.picture import MATCH_WIDTH

    write_picture(tmp_path, "d", "f" * 64, Image.new("L", (1000, 1414), 200))
    page = load_page(picture_path(tmp_path, "d", "f" * 64))
    assert page.shape[1] == MATCH_WIDTH and page.dtype.name == "float32"
