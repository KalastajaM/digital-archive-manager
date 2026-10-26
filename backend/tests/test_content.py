import hashlib
import threading
import time

from sqlalchemy import text

from dam.config import Settings
from dam.core.paths import ArchivePaths
from dam.extract import default_registry
from dam.extract.base import ExtractedText, ExtractorRegistry, UnsupportedContent
from dam.extract.pdf import PdfExtractor
from dam.index import content
from dam.index.content import ContentIndexer
from dam.index.repo import READING_MARK, FileRecord, FileRepo
from pdfs import make_text_pdf

NOW = 1_000_000.0


def setup(fake_archive, engine, **kw):
    paths = ArchivePaths(fake_archive.root, Settings(archive_root=fake_archive.root))
    repo = FileRepo(engine, inbox=paths.inbox)
    indexer = ContentIndexer(paths, repo, engine, default_registry(["en-US"]), 60, **kw)
    return paths, repo, indexer


def add_pdf(fake_archive, repo, rel="##. Organize/Kotihoito.pdf", drive_id="d1"):
    path = fake_archive.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    make_text_pdf(path)
    repo.upsert(FileRecord(drive_id=drive_id, path=rel))
    return path


def test_indexes_and_hashes(fake_archive, engine):
    _, repo, indexer = setup(fake_archive, engine)
    path = add_pdf(fake_archive, repo)
    assert indexer.run_once(now=NOW) == 1
    rec = repo.get("d1")
    assert rec.index_state == "indexed"
    assert rec.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_fts_row_written(fake_archive, engine):
    _, repo, indexer = setup(fake_archive, engine)
    add_pdf(fake_archive, repo)
    indexer.run_once(now=NOW)
    indexer.run_once(now=NOW)  # nothing pending; must not duplicate
    with engine.connect() as conn:
        ids = (
            conn.execute(text("SELECT drive_id FROM file_fts WHERE file_fts MATCH 'kotihoito'"))
            .scalars()
            .all()
        )
        n = conn.execute(text("SELECT count(*) FROM file_text")).scalar()
    assert ids == ["d1"]
    assert n == 1


def test_reindex_replaces_rows(fake_archive, engine):
    _, repo, indexer = setup(fake_archive, engine)
    add_pdf(fake_archive, repo)
    indexer.run_once(now=NOW)
    repo.set_index_state("d1", "pending")
    indexer.run_once(now=NOW)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM file_fts")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM file_text")).scalar() == 1


def test_unsupported_still_hashed(fake_archive, engine):
    _, repo, indexer = setup(fake_archive, engine)
    path = fake_archive.add("##. Organize/a.zip", b"PK1234")
    repo.upsert(FileRecord(drive_id="z1", path="##. Organize/a.zip"))
    indexer.run_once(now=NOW)
    rec = repo.get("z1")
    assert rec.index_state == "unsupported"
    assert rec.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_oserror_sets_cloud_pending(fake_archive, engine, monkeypatch):
    _, repo, indexer = setup(fake_archive, engine)
    add_pdf(fake_archive, repo)

    def boom(path):
        raise OSError(11, "Resource deadlock avoided")

    monkeypatch.setattr(content, "_read_file", boom)
    assert indexer.run_once(now=NOW) == 1
    rec = repo.get("d1")
    assert rec.index_state == "cloud_pending"
    assert rec.attempts == 1
    assert rec.retry_at == NOW + 120


def test_timeout_sets_cloud_pending(fake_archive, engine, monkeypatch):
    _, repo, indexer = setup(fake_archive, engine, read_timeout_s=0.05)
    add_pdf(fake_archive, repo)
    monkeypatch.setattr(content, "_read_file", lambda p: time.sleep(0.5) or ("x", b""))
    indexer.run_once(now=NOW)
    rec = repo.get("d1")
    assert rec.index_state == "cloud_pending" and rec.retry_at > NOW


def test_retry_after_backoff(fake_archive, engine, monkeypatch):
    _, repo, indexer = setup(fake_archive, engine)
    add_pdf(fake_archive, repo)
    real = content._read_file
    monkeypatch.setattr(content, "_read_file", lambda p: (_ for _ in ()).throw(OSError(5, "x")))
    indexer.run_once(now=NOW)
    retry_at = repo.get("d1").retry_at
    monkeypatch.setattr(content, "_read_file", real)
    assert indexer.run_once(now=NOW) == 0
    assert indexer.run_once(now=retry_at + 1) == 1
    rec = repo.get("d1")
    assert rec.index_state == "indexed" and rec.retry_at is None and rec.attempts == 0


class FakeExtractor:
    name = "fake"

    def __init__(self, fn, suffix=".pdf"):
        self.fn = fn
        self.suffix = suffix

    def supports(self, path):
        return path.suffix == self.suffix

    def extract(self, path, data=None):
        return self.fn(path)


def fake_indexer(fake_archive, engine, fn, suffix=".pdf", **kw):
    paths, repo, _ = setup(fake_archive, engine)
    registry = ExtractorRegistry()
    registry.register(FakeExtractor(fn, suffix))
    return repo, ContentIndexer(paths, repo, engine, registry, 60, **kw)


def add_file(fake_archive, repo, rel, drive_id, data=b"x"):
    fake_archive.add(rel, data)
    repo.upsert(FileRecord(drive_id=drive_id, path=rel, size=len(data), mtime=1.0))


def fts_count(engine, drive_id):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM file_fts WHERE drive_id = :d"), {"d": drive_id}
        ).scalar()


def test_extractor_crash_sets_error(fake_archive, engine, caplog):
    def crash(path):
        raise RuntimeError("boom")

    repo, indexer = fake_indexer(fake_archive, engine, crash)
    add_file(fake_archive, repo, "##. Organize/bad.pdf", "b1")
    with caplog.at_level("WARNING", logger="dam.index.content"):
        assert indexer.run_once(now=NOW) == 1
    assert repo.get("b1").index_state == "error"
    assert any("bad.pdf" in r.getMessage() for r in caplog.records)
    assert fts_count(engine, "b1") == 1


def test_extractor_oserror_sets_cloud_pending(fake_archive, engine):
    def gone(path):
        raise FileNotFoundError(2, "vanished")

    repo, indexer = fake_indexer(fake_archive, engine, gone)
    add_file(fake_archive, repo, "##. Organize/a.pdf", "a1")
    indexer.run_once(now=NOW)
    rec = repo.get("a1")
    assert rec.index_state == "cloud_pending" and rec.attempts == 1 and rec.retry_at > NOW


def test_change_mid_index_leaves_pending(fake_archive, engine):
    holder = {}

    def changes_meanwhile(path):
        holder["repo"].upsert(
            FileRecord(drive_id="c1", path="##. Organize/c.pdf", size=99, mtime=2)
        )
        return ExtractedText(text="stale", extractor="fake")

    repo, indexer = fake_indexer(fake_archive, engine, changes_meanwhile)
    holder["repo"] = repo
    add_file(fake_archive, repo, "##. Organize/c.pdf", "c1")
    indexer.run_once(now=NOW)
    rec = repo.get("c1")
    assert rec.index_state == "pending" and rec.sha256 is None
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM file_text")).scalar() == 0


def test_unsupported_content_exception(fake_archive, engine):
    def refuse(path):
        raise UnsupportedContent("encrypted")

    repo, indexer = fake_indexer(fake_archive, engine, refuse)
    path = fake_archive.add("##. Organize/e.pdf", b"secret")
    repo.upsert(FileRecord(drive_id="e1", path="##. Organize/e.pdf"))
    indexer.run_once(now=NOW)
    rec = repo.get("e1")
    assert rec.index_state == "unsupported"
    assert rec.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert fts_count(engine, "e1") == 1


def test_heic_is_unsupported(fake_archive, engine):
    _, repo, indexer = setup(fake_archive, engine)
    add_file(fake_archive, repo, "##. Organize/p.heic", "h1", b"heicdata")
    indexer.run_once(now=NOW)
    rec = repo.get("h1")
    assert rec.index_state == "unsupported" and rec.sha256 is not None


def test_garbage_pdf_is_unsupported(fake_archive, engine):
    _, repo, indexer = setup(fake_archive, engine)
    add_file(fake_archive, repo, "##. Organize/g.pdf", "g1", b"not a pdf")
    indexer.run_once(now=NOW)
    assert repo.get("g1").index_state == "unsupported"


def test_poison_record_isolated(fake_archive, engine, caplog):
    _, repo, indexer = setup(fake_archive, engine)
    repo.upsert(FileRecord(drive_id="p1", path="../escape.pdf"))
    add_pdf(fake_archive, repo, "zz/good.pdf", "g1")
    with caplog.at_level("WARNING", logger="dam.index.content"):
        indexer.run_once(now=NOW)
    assert repo.get("p1").index_state == "error"
    assert repo.get("g1").index_state == "indexed"
    assert any("escape.pdf" in r.getMessage() for r in caplog.records)


def test_stuck_read_does_not_starve_next_file(fake_archive, engine, monkeypatch):
    _, repo, indexer = setup(fake_archive, engine, read_timeout_s=0.2)
    add_pdf(fake_archive, repo, "##. Organize/a-hang.pdf", "h1")
    add_pdf(fake_archive, repo, "##. Organize/b-ok.pdf", "k1")
    release = threading.Event()
    real = content._read_file

    def reader(path):
        if "hang" in path.name:
            release.wait(10)
        return real(path)

    monkeypatch.setattr(content, "_read_file", reader)
    try:
        indexer.run_once(now=NOW)
        hung, ok = repo.get("h1"), repo.get("k1")
        assert hung.index_state == "cloud_pending" and hung.attempts == 1
        assert ok.index_state == "indexed" and ok.attempts == 0
        # still in flight when retry is due: skipped, no new attempt
        assert indexer.run_once(now=hung.retry_at + 1) == 0
        assert repo.get("h1").attempts == 1
    finally:
        release.set()
        indexer.close()


def test_all_slots_stuck_returns_zero(fake_archive, engine, monkeypatch):
    _, repo, indexer = setup(fake_archive, engine, read_timeout_s=0.05)
    for i in range(4):
        add_pdf(fake_archive, repo, f"##. Organize/f{i}.pdf", f"d{i}")
    release = threading.Event()
    monkeypatch.setattr(content, "_read_file", lambda p: release.wait(10))
    try:
        assert indexer.run_once(now=NOW) == 3
        assert indexer.run_once(now=NOW + 10_000) == 0
        assert repo.get("d3").index_state == "pending"
    finally:
        release.set()
        indexer.close()


def test_close_stops_work(fake_archive, engine):
    _, repo, indexer = setup(fake_archive, engine)
    add_pdf(fake_archive, repo)
    indexer.close()
    assert indexer.run_once(now=NOW) == 0


def test_reads_per_minute_validated(fake_archive, engine):
    import pytest

    paths = ArchivePaths(fake_archive.root, Settings(archive_root=fake_archive.root))
    with pytest.raises(ValueError):
        ContentIndexer(paths, FileRepo(engine, "x"), engine, ExtractorRegistry(), 0)


def test_run_forever_stops(fake_archive, engine):
    paths, repo, _ = setup(fake_archive, engine)
    indexer = ContentIndexer(paths, repo, engine, default_registry(["en-US"]), 6000)
    add_pdf(fake_archive, repo)
    stop = threading.Event()
    t = threading.Thread(target=indexer.run_forever, args=(stop,))
    t.start()
    deadline = time.time() + 30
    while repo.get("d1").index_state != "indexed" and time.time() < deadline:
        time.sleep(0.02)
    stop.set()
    t.join(timeout=30)
    assert not t.is_alive()
    assert repo.get("d1").index_state == "indexed"


def test_run_forever_wake_ends_idle_wait(fake_archive, engine, monkeypatch):
    import dam.index.content as content_mod

    monkeypatch.setattr(content_mod, "IDLE_WAIT_S", 60.0)
    paths, repo, _ = setup(fake_archive, engine)
    indexer = ContentIndexer(paths, repo, engine, default_registry(["en-US"]), 6000)
    stop, wake = threading.Event(), threading.Event()
    t = threading.Thread(target=indexer.run_forever, args=(stop, wake))
    t.start()
    try:
        time.sleep(0.2)  # nothing to do: idle for up to 60 s
        add_pdf(fake_archive, repo)
        wake.set()
        deadline = time.time() + 5
        while repo.get("d1").index_state != "indexed" and time.time() < deadline:
            time.sleep(0.02)
        assert repo.get("d1").index_state == "indexed"
    finally:
        stop.set()
        wake.set()
        t.join(timeout=2)
    assert not t.is_alive()


def test_wake_during_a_pass_is_not_lost(fake_archive, engine, monkeypatch):
    """A scan finishing while a pass runs (wake set mid-pass) gets a prompt next pass."""
    import dam.index.content as content_mod

    monkeypatch.setattr(content_mod, "IDLE_WAIT_S", 60.0)
    paths, repo, _ = setup(fake_archive, engine)
    indexer = ContentIndexer(paths, repo, engine, default_registry(["en-US"]), 6000)
    stop, wake = threading.Event(), threading.Event()
    real_run_once = indexer.run_once
    passes = []

    def run_once(limit=20, now=None):
        n = real_run_once(limit, now)
        if not passes:  # the "scan" lands after this pass looked and found nothing
            add_pdf(fake_archive, repo)
            wake.set()
        passes.append(n)
        return n

    monkeypatch.setattr(indexer, "run_once", run_once)
    t = threading.Thread(target=indexer.run_forever, args=(stop, wake))
    t.start()
    try:
        deadline = time.time() + 5
        while repo.get("d1") is None or repo.get("d1").index_state != "indexed":
            assert time.time() < deadline, passes
            time.sleep(0.02)
    finally:
        stop.set()
        wake.set()
        t.join(timeout=2)
    assert passes[0] == 0 and not t.is_alive()


def test_poison_records_do_not_leak_slots(fake_archive, engine):
    _, repo, indexer = setup(fake_archive, engine)
    for i in range(4):
        repo.upsert(FileRecord(drive_id=f"p{i}", path=f"../escape{i}.pdf"))
    add_pdf(fake_archive, repo, "zz/good.pdf", "g1")
    indexer.run_once(now=NOW)
    assert all(repo.get(f"p{i}").index_state == "error" for i in range(4))
    assert repo.get("g1").index_state == "indexed"
    assert indexer._slots._value == 3


def test_ocr_runs_without_pdfium_lock(tmp_path, monkeypatch):
    from dam.extract import ocr
    from dam.extract.layout import Line, Page1Layout
    from dam.pdfium import PDFIUM_LOCK
    from pdfs import make_scan_pdf

    held = []

    def fake_ocr(image, languages):
        held.append(PDFIUM_LOCK.locked())
        return Page1Layout([Line("Kotihoito", (0.1, 0.1, 0.5, 0.2))], "tesseract")

    monkeypatch.setattr(ocr, "ocr_page", fake_ocr)
    monkeypatch.setattr(ocr, "engine", lambda: "tesseract")  # ocr_image is faked: no engine needed
    pdf = make_scan_pdf(tmp_path / "s.pdf")
    got = PdfExtractor(["en-US"]).extract(pdf, pdf.read_bytes())
    assert got.ocr_used and held == [False]


def test_pdf_extracts_from_bytes_not_path(tmp_path):
    pdf = make_text_pdf(tmp_path / "t.pdf")
    data = pdf.read_bytes()
    pdf.write_bytes(b"garbage")  # proves the extractor does not reopen the path
    assert "Kotihoito" in PdfExtractor(["en-US"]).extract(pdf, data).text


def test_extraction_timeout_sets_error_without_backoff(fake_archive, engine):
    release = threading.Event()
    repo, indexer = fake_indexer(
        fake_archive, engine, lambda p: release.wait(10), extract_timeout_s=0.1
    )
    add_file(fake_archive, repo, "##. Organize/slow.pdf", "s1")
    try:
        indexer.run_once(now=NOW)
        rec = repo.get("s1")
        assert rec.index_state == "error" and rec.attempts == 0 and rec.retry_at is None
    finally:
        release.set()
        indexer.close()


def test_oversize_is_hashed_but_unsupported(fake_archive, engine, monkeypatch):
    monkeypatch.setattr(content, "MAX_BYTES", 5)
    called = []
    repo, indexer = fake_indexer(fake_archive, engine, lambda p: called.append(p))
    path = fake_archive.add("##. Organize/big.pdf", b"0123456789")
    repo.upsert(FileRecord(drive_id="o1", path="##. Organize/big.pdf"))
    indexer.run_once(now=NOW)
    rec = repo.get("o1")
    assert rec.index_state == "unsupported" and not called
    assert rec.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_late_read_skips_extraction(fake_archive, engine, monkeypatch):
    release, called = threading.Event(), []
    repo, indexer = fake_indexer(
        fake_archive, engine, lambda p: called.append(p), read_timeout_s=0.1
    )
    add_file(fake_archive, repo, "##. Organize/late.pdf", "l1")

    def slow(path):
        release.wait(10)
        return "abc", b"x"

    monkeypatch.setattr(content, "_read_file", slow)
    indexer.run_once(now=NOW)
    assert repo.get("l1").index_state == "cloud_pending"
    release.set()
    deadline = time.time() + 5
    while indexer._slots._value != 3 and time.time() < deadline:
        time.sleep(0.01)
    assert indexer._slots._value == 3 and not called


def test_cloud_pending_respects_scanner_change(fake_archive, engine, monkeypatch):
    repo, indexer = fake_indexer(fake_archive, engine, lambda p: None)
    add_file(fake_archive, repo, "##. Organize/m.pdf", "m1")

    def changes_then_fails(path):
        repo.upsert(FileRecord(drive_id="m1", path="##. Organize/m.pdf", size=99, mtime=2))
        raise OSError(11, "busy")

    monkeypatch.setattr(content, "_read_file", changes_then_fails)
    indexer.run_once(now=NOW)
    rec = repo.get("m1")
    assert rec.index_state == "pending" and rec.attempts == 0


def last_error(engine, drive_id):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT last_error FROM files WHERE drive_id = :d"), {"d": drive_id}
        ).scalar()


def test_a_read_is_marked_until_its_outcome_is_recorded(fake_archive, engine):
    seen = []

    def read(path):
        seen.append(last_error(engine, "m1"))
        return ExtractedText(text="hello", extractor="fake")

    repo, indexer = fake_indexer(fake_archive, engine, read)
    add_file(fake_archive, repo, "##. Organize/m.pdf", "m1")
    assert indexer.run_once(now=NOW) == 1
    assert seen == [READING_MARK]  # set before the read started
    assert repo.get("m1").index_state == "indexed"
    assert last_error(engine, "m1") is None


def test_a_read_that_cannot_happen_yet_clears_its_mark(fake_archive, engine):
    def offline(path):
        raise OSError("not downloaded")

    repo, indexer = fake_indexer(fake_archive, engine, offline)
    add_file(fake_archive, repo, "##. Organize/m.pdf", "m1")
    indexer.run_once(now=NOW)
    assert repo.get("m1").index_state == "cloud_pending"
    assert last_error(engine, "m1") is None


def test_a_file_whose_read_stopped_dam_is_skipped_until_retried(fake_archive, engine):
    calls = []

    def read(path):
        calls.append(path)
        return ExtractedText(text="hello", extractor="fake")

    repo, indexer = fake_indexer(fake_archive, engine, read)
    add_file(fake_archive, repo, "##. Organize/bomb.pdf", "b1")
    add_file(fake_archive, repo, "##. Organize/ok.pdf", "ok")
    # dam was killed while reading bomb.pdf: its mark is still there on the next start
    repo.mark_reading("b1")
    stop = threading.Event()
    stop.set()
    indexer.run_forever(stop)  # the start clears up before the first pass
    rec = repo.get("b1")
    assert rec.index_state == "error"
    [problem] = repo.index_problems()
    assert problem.drive_id == "b1" and problem.reason == content.READING_STOPPED
    # not read again by the indexer; the other file is
    assert indexer.run_once(now=NOW) == 1
    assert [p.name for p in calls] == ["ok.pdf"]
    assert repo.get("ok").index_state == "indexed"
    # the explicit retry reads it again
    assert repo.retry_index(["b1"]) == 1
    assert indexer.run_once(now=NOW) == 1
    assert repo.get("b1").index_state == "indexed"


def test_closing_mid_read_does_not_count_as_a_crash(fake_archive, engine):
    started, release = threading.Event(), threading.Event()

    def slow(path):
        started.set()
        release.wait(30)
        return ExtractedText(text="hello", extractor="fake")

    repo, indexer = fake_indexer(fake_archive, engine, slow)
    add_file(fake_archive, repo, "##. Organize/m.pdf", "m1")
    t = threading.Thread(target=indexer.run_once, kwargs={"now": NOW})
    t.start()
    assert started.wait(30)
    assert last_error(engine, "m1") == READING_MARK
    indexer.close()  # dam quits while the file is being read
    assert last_error(engine, "m1") is None
    release.set()
    t.join(30)
    assert indexer.recover_interrupted() == 0
