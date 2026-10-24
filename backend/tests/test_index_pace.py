"""Page 1 is read at its own pace: a PDF with a text layer fast (no OCR, a local read), a
scan and anything slow at the indexer's pace; the setting for it; what is left to read by
kind, for the time estimate."""

import pytest

from dam.extract import ocr
from dam.extract.layout import Line, Page1Layout
from dam.index import content
from test_api import LOCAL_ORIGIN, make_client
from test_index_layouts import INBOX, _indexed, _indexer


def read_page1(indexer, repo, drive_id):
    """Step the indexer until page 1 of the file is read (the barcode pass goes first)."""
    for _ in range(6):
        indexer.step()
        if repo.layout_for(drive_id) is not None:
            return
    raise AssertionError("page 1 was not read")


def with_fast_rate(indexer, per_minute=300):
    indexer.page1_fast_per_minute = lambda: per_minute
    return indexer


def test_a_quick_text_layer_read_is_followed_by_the_fast_pause(fake_archive, engine, monkeypatch):
    monkeypatch.setattr(ocr, "engine", lambda: None)
    repo, indexer = _indexer(fake_archive, engine)  # the indexer's pace: 60 a minute here
    with_fast_rate(indexer, 600)
    _indexed(fake_archive, repo, f"{INBOX}/a.pdf", "d1")
    read_page1(indexer, repo, "d1")  # the layout read of a text-layer PDF
    assert indexer.pause_s() == pytest.approx(0.1)  # 600 a minute
    indexer.step()  # the picture's thumbnail, if any: still the fast pace
    assert indexer.pause_s() == pytest.approx(0.1)


def test_a_scan_is_followed_by_the_indexers_pause(fake_archive, engine, monkeypatch):
    monkeypatch.setattr(
        ocr, "ocr_page", lambda image, languages: Page1Layout([Line("x", (0, 0, 1, 1))], "vision")
    )
    monkeypatch.setattr(ocr, "engine", lambda: "vision")
    repo, indexer = _indexer(fake_archive, engine)
    with_fast_rate(indexer, 600)
    _indexed(fake_archive, repo, f"{INBOX}/s.pdf", "d1", ocr_used=True, scan=True)
    read_page1(indexer, repo, "d1")
    assert indexer.pause_s() == pytest.approx(1.0)  # 60 a minute: the OCR pace


def test_a_slow_read_is_followed_by_the_slow_pause_even_for_a_text_layer(
    fake_archive, engine, monkeypatch
):
    monkeypatch.setattr(ocr, "engine", lambda: None)
    monkeypatch.setattr(content, "CLOUD_SLOW_S", -1.0)  # every read counts as slow
    repo, indexer = _indexer(fake_archive, engine)
    with_fast_rate(indexer, 600)
    _indexed(fake_archive, repo, f"{INBOX}/a.pdf", "d1")
    read_page1(indexer, repo, "d1")
    assert indexer.pause_s() == pytest.approx(1.0)


def test_content_and_barcode_work_keeps_the_indexers_pause(fake_archive, engine):
    repo, indexer = _indexer(fake_archive, engine)
    with_fast_rate(indexer, 600)
    indexer._last_slow = False
    assert indexer.pause_s() == pytest.approx(0.1)
    path = fake_archive.add("10. Bank/new.pdf", b"%PDF-1.4 x", drive_id="n1")
    from dam.index.scanner import scan

    scan(indexer.paths, repo)
    assert indexer.step() == 1 and path.exists()  # a pending file's content
    assert indexer.pause_s() == pytest.approx(1.0)


def test_the_fast_pace_is_never_slower_than_the_indexers(fake_archive, engine):
    repo, indexer = _indexer(fake_archive, engine)
    with_fast_rate(indexer, 10)  # slower than the 60 a minute of the indexer
    indexer._last_slow = False
    assert indexer.pause_s() == pytest.approx(1.0)
    indexer.page1_fast_per_minute = None  # no setting: one pace for all
    assert indexer.pause_s() == pytest.approx(1.0)
    indexer.page1_fast_per_minute = lambda: 1 / 0  # a broken setting is not a crash
    assert indexer.pause_s() == pytest.approx(1.0)


def test_what_is_left_to_read_is_counted_by_kind(fake_archive, engine):
    repo, indexer = _indexer(fake_archive, engine)
    _indexed(fake_archive, repo, f"{INBOX}/a.pdf", "text1")
    _indexed(fake_archive, repo, f"{INBOX}/b.pdf", "text2")
    _indexed(fake_archive, repo, f"{INBOX}/s.pdf", "scan1", ocr_used=True, scan=True)
    assert repo.layout_unread() == (2, 1)
    repo.save_layout("text1", repo.get("text1").sha256, Page1Layout([], "text-layer"))
    assert repo.layout_unread() == (1, 1)


@pytest.fixture
def api(app):
    with make_client(app) as c:
        yield c


def test_the_speed_is_a_setting_with_a_default_that_is_much_faster_than_the_indexer(app, api):
    assert app.settings.page1_text_reads_per_minute == 300 > app.settings.indexer_reads_per_minute
    page1 = api.get("/api/status").json()["page1"]
    assert (page1["text_per_min"], page1["scans_per_min"]) == (300, 30)
    r = api.put("/api/settings/page1-speed", json={"reads_per_minute": 120}, headers=LOCAL_ORIGIN)
    assert r.status_code == 200 and r.json() == {"reads_per_minute": 120}
    assert app.settings.page1_text_reads_per_minute == 120
    assert api.get("/api/status").json()["page1"]["text_per_min"] == 120
    # it is kept in settings.yaml, so a restart has it
    from dam.config import load_settings

    assert load_settings(app.app_paths).page1_text_reads_per_minute == 120
    assert app.content.page1_fast_per_minute() == 120


@pytest.mark.parametrize("bad", [0, -5, 6001])
def test_a_speed_outside_the_range_is_refused_and_changes_nothing(app, api, bad):
    r = api.put("/api/settings/page1-speed", json={"reads_per_minute": bad}, headers=LOCAL_ORIGIN)
    assert r.status_code == 400
    assert app.settings.page1_text_reads_per_minute == 300


def test_the_indexer_loop_waits_the_pause_of_the_last_kind_of_work(fake_archive, engine):
    import threading

    repo, indexer = _indexer(fake_archive, engine)
    waits: list[float] = []
    stop = threading.Event()
    kinds = iter([(1, True), (1, False), (1, False)])

    def step():
        count, slow = next(kinds)
        indexer._last_slow = slow
        if not slow:
            indexer.page1_fast_per_minute = lambda: 600
        return count

    indexer.step = step
    real_wait = stop.wait

    def wait(timeout=None):
        waits.append(timeout)
        if len(waits) == 3:
            stop.set()
        return real_wait(0)

    stop.wait = wait
    indexer.run_forever(stop)
    assert waits == pytest.approx([1.0, 0.1, 0.1])
