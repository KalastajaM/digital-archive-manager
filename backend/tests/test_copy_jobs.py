"""Moves across disks run in the background: start, progress, stop, one at a time."""

import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from dam.api import create_api
from dam.db.tables import operations
from dam.maintenance import jobs as maintenance_jobs
from dam.ops import primitives
from dam.ops.jobs import COPY_RUNNING, CopyJobs
from dam.services.errors import Conflict

BANKS = "10. Financial/Banks"
QUAR = "##. To Delete"
BASE = "http://127.0.0.1:8765"


@pytest.fixture
def across(extra_folder, app, fake_archive, monkeypatch):
    fake_archive.add(f"{BANKS}/a.pdf", b"aaaa", drive_id="id-a")
    fake_archive.add(f"{BANKS}/b.pdf", b"bb", drive_id="id-b")
    app.scan()
    monkeypatch.setattr(primitives, "same_disk", lambda a, b: False)
    return app


def _wait(job, timeout: float = 10.0):
    job.join(timeout)
    assert job.state != "running"
    return job


def test_job_not_abandoned(monkeypatch):
    monkeypatch.setattr(maintenance_jobs, "ABANDONED_S", 0.0)
    jobs = CopyJobs()

    def work(ctx):
        time.sleep(0.05)
        return "stopped" if ctx.stopped() else "finished"

    job = _wait(jobs.start(work))
    assert job.result == "finished" and job.state == "done"


def test_second_job_conflicts():
    jobs = CopyJobs()
    release = threading.Event()
    first = jobs.start(lambda ctx: release.wait(5))
    with pytest.raises(Conflict) as e:
        jobs.start(lambda ctx: None)
    assert str(e.value) == COPY_RUNNING
    release.set()
    _wait(first)
    _wait(jobs.start(lambda ctx: None))  # one at a time, then the next


def test_move_across_starts_job_and_finishes(across, fake_archive, extra_folder):
    across.tags.add("id-a", ["bank"])
    result = across.browse.move(["id-a", "id-b"], "Old years/2010", origin="ui")
    assert result.job_id is not None and result.done == []
    job = _wait(across.copy_jobs.get(result.job_id))
    assert job.state == "done"
    assert (job.done, job.total) == (2, 2)
    assert (job.bytes_done, job.bytes_total) == (6, 6)
    batch = job.result
    assert batch.failed is None and batch.batch_id
    assert (extra_folder.root / "2010" / "a.pdf").exists()
    assert (fake_archive.root / QUAR / BANKS / "b.pdf").exists()
    assert across.executor.undo(batch.batch_id).failed is None
    assert (fake_archive.root / BANKS / "a.pdf").exists()


def test_stopped_job_says_how_far(across, monkeypatch):
    real = across.executor.apply

    def stop_after_first(plan, **kw):
        ask = kw.get("should_stop")
        if ask is None:  # the request's own planning, before the job starts
            return real(plan, **kw)
        def should_stop():  # stop once the first file's pair is done
            with across.engine.connect() as conn:
                pair = conn.execute(
                    select(operations.c.id).where(operations.c.kind == "quarantine")
                ).first()
            return pair is not None or ask()

        kw["should_stop"] = should_stop
        return real(plan, **kw)

    monkeypatch.setattr(across.executor, "apply", stop_after_first)
    result = across.browse.move(["id-a", "id-b"], "Old years/2010", origin="ui")
    job = _wait(across.copy_jobs.get(result.job_id))
    assert job.result.stopped
    assert job.result.error == "Stopped: 1 of 2 files moved."


def test_same_disk_move_stays_synchronous(extra_folder, app, fake_archive):
    fake_archive.add(f"{BANKS}/a.pdf", b"a", drive_id="id-a")
    app.scan()
    result = app.browse.move(["id-a"], "Old years/2010", origin="ui")
    assert result.job_id is None and result.failed is None and result.done


def test_restore_across_disks_runs_as_job(across, fake_archive):
    assert across.browse.quarantine(["id-a"], origin="ui").failed is None
    result = across.browse.restore(["id-a"], to="folder", origin="ui", folder="Old years/2010")
    job = _wait(across.copy_jobs.get(result.job_id))
    assert job.result.failed is None
    assert (fake_archive.root / QUAR / BANKS / "a.pdf").exists()  # the original stays


def test_move_preview_reports_size_and_cloud_only(across, monkeypatch):
    monkeypatch.setattr(primitives, "is_dataless", lambda p: p.name == "b.pdf")
    resolved = across.browse.move_preview(["id-a", "id-b"], "Old years/2010", origin="ui")
    copies = {r.src.rsplit("/", 1)[1]: r for r in resolved if r.kind == "copy_across"}
    assert (copies["a.pdf"].size, copies["a.pdf"].cloud_only) == (4, False)
    assert (copies["b.pdf"].size, copies["b.pdf"].cloud_only) == (2, True)


def test_jobs_running_includes_copy_jobs(across):
    release = threading.Event()
    job = across.copy_jobs.start(lambda ctx: release.wait(5))
    assert across.jobs_running()
    release.set()
    _wait(job)
    assert not across.jobs_running()


@pytest.fixture
def client(across):
    with TestClient(create_api(across, None), base_url=BASE, headers={"Origin": BASE}) as c:
        yield c


def test_api_move_returns_job_and_polls(client, across):
    body = {"drive_ids": ["id-a"], "folder": "Old years/2010"}
    preview = client.post("/api/browse/move/preview", json=body).json()
    copy = next(op for op in preview if op["kind"] == "copy_across")
    assert copy["size"] == 4 and copy["cloud_only"] is False
    started = client.post("/api/browse/move", json=body).json()
    assert started["job_id"] and started["done"] == []
    _wait(across.copy_jobs.get(started["job_id"]))
    polled = client.get(f"/api/browse/move/jobs/{started['job_id']}").json()
    assert polled["state"] == "done" and polled["done"] == 1
    assert polled["result"]["failed"] is None and polled["result"]["batch_id"]
    latest = client.get("/api/browse/move/jobs/latest").json()
    assert latest["job_id"] == started["job_id"]
    stopped = client.post(f"/api/browse/move/jobs/{started['job_id']}/stop", json={})
    assert stopped.status_code == 200 and stopped.json()["state"] == "done"
    assert client.get("/api/browse/move/jobs/nope").status_code == 404


def test_api_latest_is_null_without_jobs(client):
    assert client.get("/api/browse/move/jobs/latest").json() is None
