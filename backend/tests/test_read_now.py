"""Read page 1 of the documents a test waits for now: queued first, read at full speed
(still one at a time, with the usual time limit), picked up by the test as they arrive."""

import time

import pytest

from dam.extract import ocr
from dam.extract.layout import Page1Layout
from dam.index import content
from dam.rules import jobs as jobs_module
from test_api import LOCAL_ORIGIN, make_client, post
from test_index_layouts import _indexed, _indexer
from test_rules_zone import HEADER, LETTER, add


def indexer_with(fake_archive, engine, monkeypatch, n=3):
    monkeypatch.setattr(ocr, "engine", lambda: None)  # text-layer PDFs need no OCR
    repo, indexer = _indexer(fake_archive, engine)
    indexer.page1_fast_per_minute = lambda: 300
    for i in range(1, n + 1):
        _indexed(fake_archive, repo, f"20. Home/f{i}.pdf", f"d{i}")
    return repo, indexer


def test_the_files_asked_for_are_read_first_and_without_the_pause(
    fake_archive, engine, monkeypatch
):
    repo, indexer = indexer_with(fake_archive, engine, monkeypatch)
    assert indexer.read_now(["d3", "d3"]) == 1
    assert indexer.reading_now() == 1
    assert indexer.pause_s() == pytest.approx(content.BURST_PAUSE_S)
    assert indexer.run_layouts_once(limit=1, backfill=True) == 1
    assert repo.layout_for("d3") is not None
    assert repo.layout_for("d1") is None and repo.layout_for("d2") is None  # only d3 went first
    # read: no longer waiting, and the pause is the usual one again
    assert indexer.reading_now() == 0
    indexer._last_slow = True
    assert indexer.pause_s() == pytest.approx(1.0)


def test_a_file_that_cannot_be_read_now_does_not_keep_the_fast_pace(
    fake_archive, engine, monkeypatch
):
    repo, indexer = indexer_with(fake_archive, engine, monkeypatch, n=1)
    indexer.read_now(["d1"])
    indexer._retry_layout_later("d1", content.LAYOUT_TIMEOUT)
    assert indexer.reading_now() == 0
    indexer._last_slow = True
    assert indexer.pause_s() == pytest.approx(1.0)


def test_read_now_gives_up_after_a_while(fake_archive, engine, monkeypatch):
    repo, indexer = indexer_with(fake_archive, engine, monkeypatch, n=1)
    monkeypatch.setattr(content, "BURST_S", -1.0)
    indexer.read_now(["d1"])
    assert indexer.reading_now() == 0
    indexer._last_slow = True
    assert indexer.pause_s() == pytest.approx(1.0)


def test_a_read_that_hangs_still_times_out_and_is_not_read_again_at_once(
    fake_archive, engine, monkeypatch
):
    import threading

    repo, indexer = indexer_with(fake_archive, engine, monkeypatch, n=1)
    indexer.layout_timeout_s = 0.2
    release = threading.Event()

    def hang(*a, **k):
        release.wait(5)
        return Page1Layout([], "text-layer")

    monkeypatch.setattr(content, "read_layout", hang)
    indexer.read_now(["d1"])
    started = time.monotonic()
    indexer.run_layouts_once(limit=1, backfill=True)
    assert time.monotonic() - started < 2  # the usual time limit
    assert indexer.layout_blocked("d1") == content.LAYOUT_TIMEOUT
    assert indexer.reading_now() == 0
    release.set()


@pytest.fixture
def api(app):
    with make_client(app) as c:
        for r in list(app.rules):
            app.delete_rule(r.id)
        yield c


def test_read_now_queues_exactly_the_documents_the_test_waits_for_and_the_test_picks_them_up(
    app, api, fake_archive, monkeypatch
):
    monkeypatch.setattr(jobs_module, "RECHECK_EVERY_S", 0.05)
    for i in range(3):
        add(app, fake_archive, f"10. Bank/p{i}.pdf", f"p{i}", "Pohjola Vakuutus")
    add(app, fake_archive, "10. Bank/other.pdf", "o", "something else")
    rule = {
        "id": "pohjola",
        "when": {"zones": [{"box": list(HEADER), "text_contains": ["pohjola"]}]},
        "then": {"folder": "Insurance/Pohjola"},
    }
    job_id = api.post(
        "/api/rules/replay/jobs", json={"rule": rule, "sheet": "s"}, headers=LOCAL_ORIGIN
    ).json()["job_id"]
    for _ in range(200):
        job = api.get(f"/api/rules/replay/jobs/{job_id}").json()
        if job["state"] == "waiting":
            break
        time.sleep(0.02)
    assert job["state"] == "waiting" and job["waiting"] == 3
    r = post(api, f"/api/rules/replay/jobs/{job_id}/read-now")
    assert r.status_code == 200 and r.json() == {"queued": 3}
    assert app.content.reading_now() == 3  # exactly those three, not the other document
    # page 1 of each is read: the test picks them up and finishes
    for i in range(3):
        app.repo.save_layout(f"p{i}", f"sha-p{i}", LETTER)
    for _ in range(300):
        job = api.get(f"/api/rules/replay/jobs/{job_id}").json()
        if job["state"] == "done":
            break
        time.sleep(0.02)
    assert job["state"] == "done" and job["waiting"] == 0
    assert (job["result"]["matched"], job["result"]["not_checked"]) == (3, [])


def test_read_now_for_a_test_that_is_gone_is_404_and_for_nothing_waiting_queues_nothing(
    app, api, fake_archive
):
    assert post(api, "/api/rules/replay/jobs/nope/read-now").status_code == 404
    add(app, fake_archive, "20. Home/20260301_Fortum.pdf", "b", "Fortum")
    body = {
        "rule": {"id": "f", "when": {"text_contains": ["fortum"]}, "then": {"folder": "X"}},
        "sheet": "s",
    }
    job_id = api.post("/api/rules/replay/jobs", json=body, headers=LOCAL_ORIGIN).json()["job_id"]
    for _ in range(200):
        if api.get(f"/api/rules/replay/jobs/{job_id}").json()["state"] == "done":
            break
        time.sleep(0.02)
    r = post(api, f"/api/rules/replay/jobs/{job_id}/read-now")
    assert r.json() == {"queued": 0} and app.content.reading_now() == 0
