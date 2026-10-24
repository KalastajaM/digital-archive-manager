"""The layout pass: page 1 of files indexed before positions were kept."""

import hashlib
import threading
import time

import pytest
from sqlalchemy import text

from dam.config import Settings
from dam.core.paths import ArchivePaths
from dam.extract import ocr
from dam.extract.base import ExtractedText, ExtractorRegistry
from dam.extract.layout import Line, Page1Layout
from dam.index import content
from dam.index import layouts as layouts_module
from dam.index.content import ContentIndexer
from dam.index.repo import FileRecord, FileRepo
from pdfs import make_layout_pdf, make_scan_pdf, make_text_pdf

INBOX = "##. Organize"
NOW = 1_000_000.0


class _Fake:
    name = "fake"

    def supports(self, path):
        return path.suffix.lower() in {".pdf", ".png"}

    def extract(self, path, data=None):
        return ExtractedText("Lasku 12,00 EUR", self.name)


def _indexer(fake_archive, engine, **kw):
    paths = ArchivePaths(fake_archive.root, Settings(archive_root=fake_archive.root))
    repo = FileRepo(engine, inbox=paths.inbox)
    registry = ExtractorRegistry()
    registry.register(_Fake())
    return repo, ContentIndexer(paths, repo, engine, registry, 60, **kw)


def _indexed(fake_archive, repo, rel, drive_id, *, ocr_used=False, scan=False):
    path = fake_archive.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if scan:
        make_scan_pdf(path)
    else:
        make_layout_pdf(path, [(50, 700, "Pohjola Vakuutus"), (50, 680, "Michiel Visser")])
    st = path.stat()
    repo.upsert(
        FileRecord(drive_id=drive_id, path=rel, ext="pdf", size=st.st_size, mtime=st.st_mtime)
    )
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    repo.save_content(drive_id, sha, ExtractedText("Lasku", "test", ocr_used), "indexed")
    return path


def test_a_text_layer_pdf_is_read_without_ocr(fake_archive, engine, monkeypatch):
    monkeypatch.setattr(ocr, "engine", lambda: None)  # OCR is never needed here
    repo, indexer = _indexer(fake_archive, engine)
    _indexed(fake_archive, repo, f"{INBOX}/a.pdf", "d1")
    assert repo.layout_for("d1") is None
    assert indexer.run_layouts_once() == 1
    layout = repo.layout_for("d1")
    assert layout.source == "text-layer"
    assert [ln.text for ln in layout.lines] == ["Pohjola Vakuutus", "Michiel Visser"]
    assert indexer.run_layouts_once() == 0  # read once per content


def test_a_scan_is_rendered_and_read_with_the_indexers_languages(fake_archive, engine, monkeypatch):
    seen = {}

    def fake(image, languages):
        seen["size"], seen["languages"] = image.size, languages
        return Page1Layout([Line("Fortum", (0.1, 0.1, 0.3, 0.15))], "vision")

    monkeypatch.setattr(ocr, "ocr_page", fake)
    monkeypatch.setattr(ocr, "engine", lambda: "vision")
    repo, indexer = _indexer(fake_archive, engine, ocr_languages=["fi-FI"])
    _indexed(fake_archive, repo, f"{INBOX}/s.pdf", "d1", ocr_used=True, scan=True)
    assert indexer.run_layouts_once() == 1
    assert repo.layout_for("d1").source == "vision" and seen["languages"] == ["fi-FI"]
    assert seen["size"][0] > 500  # rendered at the OCR resolution, not thumbnail size


def test_without_an_ocr_engine_a_scan_waits_and_says_why(fake_archive, engine, monkeypatch):
    monkeypatch.setattr(ocr, "engine", lambda: None)
    repo, indexer = _indexer(fake_archive, engine)
    _indexed(fake_archive, repo, f"{INBOX}/s.pdf", "d1", ocr_used=True, scan=True)
    assert indexer.run_layouts_once() == 1
    assert repo.layout_for("d1") is None  # not "read, no text"
    assert indexer.layout_blocked("d1") == "no OCR engine installed"
    assert indexer.run_layouts_once() == 0  # waits for the retry time


def test_backfill_off_reads_only_the_inbox_and_wanted_files(fake_archive, engine):
    flag = {"on": False}
    repo, indexer = _indexer(fake_archive, engine, page1_backfill=lambda: flag["on"])
    _indexed(fake_archive, repo, "10. Home/old.pdf", "old")
    _indexed(fake_archive, repo, "10. Home/asked.pdf", "asked")
    _indexed(fake_archive, repo, f"{INBOX}/new.pdf", "new")
    assert indexer.run_layouts_once(limit=10) == 1
    assert repo.layout_for("new") is not None and repo.layout_for("old") is None
    indexer.want_layouts(["asked"])
    assert indexer.run_layouts_once(limit=10) == 1
    assert repo.layout_for("asked") is not None and repo.layout_for("old") is None
    assert indexer.run_layouts_once(limit=10) == 0
    flag["on"] = True
    assert indexer.run_layouts_once(limit=10) == 1
    assert repo.layout_for("old") is not None


def test_wanted_files_go_before_the_rest(fake_archive, engine):
    repo, indexer = _indexer(fake_archive, engine)
    _indexed(fake_archive, repo, "10. Home/a.pdf", "a")
    _indexed(fake_archive, repo, "20. Work/b.pdf", "b")
    indexer.want_layouts(["b"])
    assert indexer.run_layouts_once(limit=1) == 1
    assert repo.layout_for("b") is not None and repo.layout_for("a") is None


def test_content_and_barcodes_go_before_layouts(fake_archive, engine, monkeypatch):
    repo, indexer = _indexer(fake_archive, engine)
    path = fake_archive.root / INBOX / "new.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    make_text_pdf(path)
    st = path.stat()
    repo.upsert(
        FileRecord(
            drive_id="d1", path=f"{INBOX}/new.pdf", ext="pdf", size=st.st_size, mtime=st.st_mtime
        )
    )
    order = []
    monkeypatch.setattr(indexer, "run_barcodes_once", lambda limit=1: order.append("barcodes") or 0)
    real = indexer.run_layouts_once
    monkeypatch.setattr(
        indexer, "run_layouts_once", lambda limit=1: order.append("layouts") or real(limit)
    )
    assert indexer.step(now=NOW) == 1  # content first
    assert order == []
    assert indexer.step(now=NOW) == 1  # nothing for barcodes (stubbed), then layouts
    assert order == ["barcodes", "layouts"]
    assert repo.layout_for("d1") is not None  # the indexer's fake extractor gave none: read here


def test_a_file_changed_since_indexing_is_recorded_as_no_text_for_that_content(
    fake_archive, engine
):
    repo, indexer = _indexed_changed(fake_archive, engine)
    assert indexer.run_layouts_once() == 1
    assert indexer.run_layouts_once() == 0  # no hot loop
    assert repo.layout_for("d1").lines == []


def _indexed_changed(fake_archive, engine):
    repo, indexer = _indexer(fake_archive, engine)
    path = _indexed(fake_archive, repo, f"{INBOX}/a.pdf", "d1")
    make_layout_pdf(path, [(50, 700, "Something else")])  # not rescanned
    return repo, indexer


def test_a_hung_read_is_not_recorded_and_retried_later(fake_archive, engine, monkeypatch):
    release = threading.Event()

    def slow(*_a, **_k):
        release.wait(5)
        return Page1Layout([], "text-layer")

    monkeypatch.setattr(content, "read_layout", slow)
    repo, indexer = _indexer(fake_archive, engine, layout_timeout_s=0.2, layout_retry_s=600)
    _indexed(fake_archive, repo, f"{INBOX}/a.pdf", "d1")
    started = time.monotonic()
    assert indexer.run_layouts_once() == 1
    assert time.monotonic() - started < 2
    assert repo.layout_for("d1") is None
    assert indexer.run_layouts_once() == 0  # busy, then waiting for its retry time
    release.set()


def test_errors_in_reading_never_break_the_pass(fake_archive, engine, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("pdfium exploded")

    monkeypatch.setattr(layouts_module, "text_layer_lines", boom)
    repo, indexer = _indexer(fake_archive, engine)
    _indexed(fake_archive, repo, f"{INBOX}/a.pdf", "d1")
    assert indexer.run_layouts_once() == 1
    assert repo.layout_for("d1").lines == []
    assert repo.get("d1").index_state == "indexed"
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM file_layouts")).scalar() == 1


@pytest.mark.parametrize("closed", [True])
def test_a_closed_indexer_reads_nothing(fake_archive, engine, closed):
    repo, indexer = _indexer(fake_archive, engine)
    _indexed(fake_archive, repo, f"{INBOX}/a.pdf", "d1")
    indexer.close()
    assert indexer.run_layouts_once() == 0
