"""A rule test in the background: start, poll for the result so far, stop, one per sheet,
a few at most, ends by itself when nobody asks, picks up page 1 reads as they arrive, and
changes nothing."""

import threading
import time

import pytest

import bigfake
from dam.extract.layout import Line, Page1Layout
from dam.rules import jobs as jobs_module
from dam.rules.jobs import ReplayJobs
from dam.rules.replay import ReplayRun, replay
from test_api import LOCAL_ORIGIN, make_client, post
from test_api_rules import add_filed, rule_body


@pytest.fixture
def fake(tmp_path):
    f = bigfake.build(tmp_path / "fake", 400, seed=21)
    yield f
    f.engine.dispose()


def make_run(fake, rule, gate: threading.Event | None = None):
    """A run whose first layout load waits for ``gate`` (so a test can look at a job
    that is part way)."""

    def layouts_for(ids):
        if gate is not None:
            assert gate.wait(20), "the test never opened the gate"
        return fake.repo.layouts_for(ids)

    return lambda: ReplayRun(
        fake.engine,
        rule,
        [rule],
        fake.special,
        layouts_for=layouts_for,
        pictures=fake.pictures,
    )


def wait_for(cond, seconds=15.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def jobs():
    j = ReplayJobs()
    yield j
    j.close()


def test_a_job_runs_to_the_end_and_gives_the_result_of_the_plain_test(fake, jobs):
    rule = bigfake.rules()["c_text_picture"]
    job = jobs.start("sheet-1", make_run(fake, rule))
    assert wait_for(lambda: job.view(False).state not in ("running",))
    view = job.view()
    plain = replay(
        fake.engine,
        rule,
        [rule],
        fake.special,
        60.0,
        layouts_for=fake.repo.layouts_for,
        pictures=fake.pictures,
    )
    got = view.result
    assert got is not None and view.state in ("done", "waiting")
    assert (got.matched, got.same, got.checked, got.total, got.inbox) == (
        plain.matched,
        plain.same,
        plain.checked,
        plain.total,
        plain.inbox,
    )
    assert [n.path for n in got.not_checked] == [n.path for n in plain.not_checked]
    assert view.looked_at == view.total == plain.total
    assert view.version > 1 and view.error is None


def test_a_job_that_is_part_way_shows_what_it_has_and_can_be_stopped(fake, jobs):
    rule = bigfake.rules()["d_text_area"]
    gate = threading.Event()
    job = jobs.start("s", make_run(fake, rule, gate))
    assert wait_for(lambda: job.view(False).version >= 1)
    first = job.view()
    assert first.state == "running" and first.looked_at == 0 and first.total == fake.n_files
    job.stop()
    gate.set()
    job.join(10)
    view = job.view()
    assert view.state == "stopped"
    assert view.looked_at < view.total  # stopped before the end
    # what it found is kept
    assert view.result is not None and view.result.total == fake.n_files


def test_the_result_is_left_out_when_nothing_is_new(fake, jobs):
    rule = bigfake.rules()["d_text_area"]
    job = jobs.start("s", make_run(fake, rule))
    assert wait_for(lambda: job.view(False).state != "running")
    view = job.view()
    assert view.result is not None
    assert job.view(with_result=False).result is None


def test_starting_another_test_for_a_sheet_ends_the_first(fake, jobs):
    rule = bigfake.rules()["d_text_area"]
    gate = threading.Event()
    first = jobs.start("sheet", make_run(fake, rule, gate))
    assert wait_for(lambda: first.view(False).version >= 1)
    second = jobs.start("sheet", make_run(fake, rule))
    gate.set()
    first.join(10)
    assert first.view(False).state == "stopped" and jobs.get(first.job_id) is None
    assert wait_for(lambda: second.view(False).state != "running")
    assert jobs.get(second.job_id) is second


def test_only_a_few_tests_are_kept(fake, jobs):
    rule = bigfake.rules()["a_word"]
    # one after the other: the oldest finished job goes first, and jobs running side by
    # side may finish in any order
    started = []
    for i in range(jobs_module.MAX_JOBS + 2):
        job = jobs.start(f"s{i}", make_run(fake, rule))
        assert wait_for(lambda job=job: job.view(False).state != "running")
        started.append(job)
    kept = [j for j in started if jobs.get(j.job_id) is not None]
    assert len(kept) == jobs_module.MAX_JOBS
    assert kept == started[-jobs_module.MAX_JOBS :]  # the oldest went first


def test_a_test_nobody_asks_about_ends_by_itself(fake, jobs, monkeypatch):
    monkeypatch.setattr(jobs_module, "ABANDONED_S", 0.2)
    rule = bigfake.rules()["d_text_area"]
    gate = threading.Event()
    job = jobs.start("s", make_run(fake, rule, gate))
    # nobody polls: wait until the job counts as abandoned
    assert wait_for(lambda: time.monotonic() - job.seen > jobs_module.ABANDONED_S)
    gate.set()
    job.join(10)
    assert job.state == "stopped"


def test_a_test_that_fails_says_so_without_details(fake, jobs):
    def boom():
        raise RuntimeError("secret detail at /home/someone/Documents")

    job = jobs.start("s", boom)
    job.join(10)
    view = job.view()
    assert view.state == "error" and view.error and "someone" not in view.error


def test_documents_waiting_for_page_1_are_looked_at_again_as_it_arrives(fake, jobs, monkeypatch):
    monkeypatch.setattr(jobs_module, "RECHECK_EVERY_S", 0.05)
    rule = bigfake.rules()["d_text_area"]
    job = jobs.start("s", make_run(fake, rule))
    assert wait_for(lambda: job.view(False).state == "waiting")
    waiting = job.view().result.not_checked
    assert waiting and job.view(False).waiting == len(waiting)
    # page 1 of each is read: the header is not the sender's, so none of them matches
    from sqlalchemy import select

    from dam.db.tables import files

    with fake.engine.connect() as conn:
        shas = dict(conn.execute(select(files.c.drive_id, files.c.sha256)).all())
    for n in waiting:
        fake.repo.save_layout(n.drive_id, shas[n.drive_id], Page1Layout([Line("x", (0, 0, 1, 1))]))
    assert wait_for(lambda: job.view(False).state == "done")
    view = job.view()
    assert view.waiting == 0 and view.result.not_checked == []
    assert view.result.checked == view.result.total  # all of them are checked now


def test_blocked_documents_do_not_keep_a_test_waiting(fake, jobs, monkeypatch):
    monkeypatch.setattr(jobs_module, "RECHECK_EVERY_S", 0.05)
    rule = bigfake.rules()["d_text_area"]
    blocked = {"on": False}

    def make():
        return ReplayRun(
            fake.engine,
            rule,
            [rule],
            fake.special,
            layouts_for=fake.repo.layouts_for,
            layout_blocked=lambda d: "no OCR engine" if blocked["on"] else None,
        )

    job = jobs.start("s", make)
    assert wait_for(lambda: job.view(False).state == "waiting")
    blocked["on"] = True
    assert wait_for(lambda: job.view(False).state == "done")
    reasons = {n.reason for n in job.view().result.not_checked}
    assert reasons == {"no OCR engine"}


# -- through the API ---------------------------------------------------------------------


def start(api, rule, sheet="sheet-a", **extra):
    return post(api, "/api/rules/replay/jobs", {"rule": rule, "sheet": sheet, **extra})


def poll_done(api, job_id, seconds=15.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        data = api.get(f"/api/rules/replay/jobs/{job_id}").json()
        if data["state"] not in ("running", "waiting"):
            return data
        time.sleep(0.05)
    raise AssertionError("the test did not finish")


@pytest.fixture
def api(app):
    with make_client(app) as c:
        for r in list(app.rules):
            app.delete_rule(r.id)
        yield c


def test_the_api_starts_polls_and_drops_a_test(app, api, fake_archive):
    add_filed(app, fake_archive, "11. Bills/2026/20260210_Fortum.pdf", "a", "Fortum")
    add_filed(app, fake_archive, "20. Home/20260301_Fortum.pdf", "b", "Fortum")
    r = start(api, rule_body("fortum"))
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    data = poll_done(api, job_id)
    assert data["state"] == "done" and (data["looked_at"], data["total"]) == (2, 2)
    result = data["result"]
    assert (result["matched"], result["same"], result["looked_at"]) == (2, 1, 2)
    assert result["different"][0]["path_rule"] == "11. Bills/2026/20260301_Fortum.pdf"
    # the same version again: nothing new, so no result
    again = api.get(f"/api/rules/replay/jobs/{job_id}", params={"since": data["version"]}).json()
    assert again["result"] is None and again["state"] == "done"
    # the sheet closes: the test is dropped
    assert api.delete(f"/api/rules/replay/jobs/{job_id}", headers=LOCAL_ORIGIN).status_code == 200
    assert api.get(f"/api/rules/replay/jobs/{job_id}").status_code == 404
    # nothing was changed in the archive or the rules
    assert api.get("/api/rules").json()["rules"] == []


def test_the_api_stops_a_test_and_refuses_what_it_cannot_run(app, api, fake_archive):
    add_filed(app, fake_archive, "20. Home/20260301_Fortum.pdf", "b", "Fortum")
    job_id = start(api, rule_body("fortum")).json()["job_id"]
    stopped = post(api, f"/api/rules/replay/jobs/{job_id}/stop")
    assert stopped.status_code == 200 and stopped.json()["state"] in ("stopped", "done")
    assert post(api, "/api/rules/replay/jobs/nope/stop").status_code == 404
    bad = start(api, {"id": "x", "when": {"filename_matches": "("}})
    assert bad.status_code == 400 and "invalid regex" in bad.json()["error"]
    assert start(api, rule_body("x"), replaces="nope").status_code == 404
    assert start(api, rule_body("x"), sheet="").status_code == 422


def test_a_second_test_for_the_same_sheet_drops_the_first(app, api, fake_archive):
    add_filed(app, fake_archive, "20. Home/20260301_Fortum.pdf", "b", "Fortum")
    first = start(api, rule_body("fortum")).json()["job_id"]
    second = start(api, rule_body("fortum", "home"), near_drive_id="b").json()["job_id"]
    assert first != second
    assert api.get(f"/api/rules/replay/jobs/{first}").status_code == 404
    assert poll_done(api, second)["state"] == "done"
