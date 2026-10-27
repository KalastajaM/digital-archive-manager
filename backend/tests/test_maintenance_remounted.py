"""Maintenance, "Left alone after a Drive restart": when Google Drive for desktop is
remounted, the links and folders dam made in ##. Ongoing and ##. Important come back with
a new device number, and the publisher leaves them alone ("looks different from before").
When only the device number changed, the same way for every changed entry under a root,
taking it over records the new number; Undo puts the old one back. Database only; fake
archives only."""

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from dam.api import create_api
from dam.db.tables import ongoing_entries
from dam.errors import InvalidRequest, NotFound

ONG = "##. Ongoing"
BANKS = "10. Financial/Banks"
BASE = "http://127.0.0.1:8765"
H = {"Origin": BASE}


def records(app) -> dict[str, tuple[str, str]]:
    with app.engine.connect() as conn:
        rows = conn.execute(select(ongoing_entries).order_by(ongoing_entries.c.rel)).all()
    return {r.rel: (r.st_dev, r.st_ino) for r in rows}


def remount(app, dev_of=lambda rel, dev: str(int(dev) + 1000)) -> None:
    """Pretend the entries were recorded on another device (as before a Drive remount)."""
    with app.engine.begin() as conn:
        for row in conn.execute(select(ongoing_entries)).all():
            conn.execute(
                update(ongoing_entries)
                .where(ongoing_entries.c.id == row.id)
                .values(st_dev=dev_of(row.rel, row.st_dev))
            )


def run(app):
    job = app.maintenance.start("remounted")
    job.join(15)
    assert job.view().state == "done", job.view().error
    return app.maintenance.result_of(job)[1]


@pytest.fixture
def published(app, fake_archive):
    """A collection of two files, published as a folder of two links in ##. Ongoing."""
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="id-a")
    fake_archive.add(f"{BANKS}/b.pdf", drive_id="id-b")
    app.scan()
    c = app.collections.create("Sauna")
    app.collections.add_members(c.id, ["id-a", "id-b"])
    assert app.ongoing.sync().problems == []
    return records(app)


def test_a_remount_is_found_taken_over_and_undone(app, published):
    remount(app)
    assert any("looks different from before" in p for p in app.ongoing.sync().problems)
    [root] = run(app).roots
    assert (root.root, root.offered, root.reason) == (ONG, True, None)
    assert sorted(e.rel for e in root.entries) == sorted(published)
    assert {(e.old_dev, e.new_dev) for e in root.entries} == {
        (str(int(dev) + 1000), dev) for dev, _ in published.values()
    }

    preview = app.maintenance.readopt([ONG], dry_run=True)
    assert preview.dry_run and [r.root for r in preview.roots] == [ONG]
    assert records(app) != published  # a preview changes nothing

    done = app.maintenance.readopt([ONG])
    assert done.errors == [] and done.undo_id
    assert records(app) == published
    assert app.ongoing.sync().problems == []  # no longer left alone
    assert run(app).roots == []

    undone = app.maintenance.undo_readopt(done.undo_id)
    assert undone.errors == [] and [r.root for r in undone.roots] == [ONG]
    assert records(app) != published and len(records(app)) == len(published)
    assert any("looks different from before" in p for p in app.ongoing.sync().problems)
    with pytest.raises(InvalidRequest, match="already undone"):
        app.maintenance.undo_readopt(done.undo_id)


def test_an_entry_with_a_new_inode_keeps_its_root_left_alone(app, published):
    first = sorted(published)[0]
    remount(app)
    with app.engine.begin() as conn:
        conn.execute(
            update(ongoing_entries).where(ongoing_entries.c.rel == first).values(st_ino="1")
        )
    [root] = run(app).roots
    assert not root.offered and "inode" in root.reason and first in root.reason
    with pytest.raises(InvalidRequest, match="nothing to take over"):
        app.maintenance.readopt([ONG])
    assert records(app)[first][1] == "1"


def test_entries_from_two_old_devices_are_left_alone(app, published):
    names = sorted(published)
    remount(app, lambda rel, dev: str(int(dev) + (1 if rel == names[0] else 2)))
    [root] = run(app).roots
    assert not root.offered and "more than one device" in root.reason


def test_entries_that_still_match_are_not_listed(app, published):
    assert run(app).roots == []
    with pytest.raises(InvalidRequest, match="nothing to take over"):
        app.maintenance.readopt([ONG])


def test_undo_leaves_an_entry_changed_since(app, published):
    remount(app)
    done = app.maintenance.readopt([ONG])
    changed = sorted(published)[0]
    with app.engine.begin() as conn:
        conn.execute(
            update(ongoing_entries).where(ongoing_entries.c.rel == changed).values(st_dev="7")
        )
    undone = app.maintenance.undo_readopt(done.undo_id)
    assert len(undone.errors) == 1 and changed in undone.errors[0]
    assert records(app)[changed][0] == "7"
    for rel, (dev, _) in records(app).items():
        if rel != changed:
            assert dev == str(int(published[rel][0]) + 1000)


def test_unknown_roots_and_undo_ids_are_refused(app, published):
    with pytest.raises(InvalidRequest, match="not a publish root"):
        app.maintenance.readopt(["10. Financial"])
    with pytest.raises(NotFound):
        app.maintenance.undo_readopt("nope")


def test_api_remounted_flow(app, published):
    remount(app)
    with TestClient(create_api(app, None), base_url=BASE) as c:
        job = c.post("/api/maintenance/jobs", json={"kind": "remounted"}, headers=H)
        assert job.status_code == 200, job.text
        for _ in range(100):
            body = c.get(f"/api/maintenance/jobs/{job.json()['job_id']}", headers=H).json()
            if body["state"] != "running":
                break
            time.sleep(0.05)
        [root] = body["remounted"]["roots"]
        assert root["root"] == ONG and root["offered"] and len(root["entries"]) == 3
        choice = {"roots": [ONG]}
        dry = c.post(
            "/api/maintenance/remounted/readopt", json={**choice, "dry_run": True}, headers=H
        )
        assert dry.status_code == 200 and dry.json()["undo_id"] is None
        done = c.post("/api/maintenance/remounted/readopt", json=choice, headers=H)
        assert done.status_code == 200 and done.json()["errors"] == [], done.text
        assert records(app) == published
        undo = {"undo_id": done.json()["undo_id"]}
        back = c.post("/api/maintenance/remounted/undo", json=undo, headers=H)
        assert back.status_code == 200 and back.json()["errors"] == []
        assert c.post("/api/maintenance/remounted/undo", json=undo, headers=H).status_code == 400
        unknown = c.post("/api/maintenance/remounted/undo", json={"undo_id": "x"}, headers=H)
        assert unknown.status_code == 404
