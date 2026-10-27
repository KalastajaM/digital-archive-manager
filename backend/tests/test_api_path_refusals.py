"""HTTP-level refusals for POST /api/folders/reveal and POST /api/maintenance/links/remove.

Reveal uses an injected runner (nothing opens Finder); link removal touches only a fake
archive."""

import os

import pytest
from fastapi.testclient import TestClient

from dam.api import create_api

BASE = "http://127.0.0.1:8765"
H = {"Origin": BASE}
BANKS = "10. Financial/Banks"
ONG = "##. Ongoing"
HOME = "20. Home"


@pytest.fixture
def calls(app):
    seen: list[list[str]] = []

    def runner(args: list[str]) -> int:
        seen.append(args)
        return 0

    app.launch.runner = runner
    app.launch.platform = "darwin"
    return seen


@pytest.fixture
def client(app):
    with TestClient(create_api(app), base_url=BASE) as c:
        yield c


def reveal(client, path):
    return client.post("/api/folders/reveal", json={"path": path}, headers=H)


# -- /api/folders/reveal ------------------------------------------------------------


def test_reveal_folder_opens_a_folder_in_the_archive(app, client, calls, fake_archive):
    r = reveal(client, "10. Financial/Banks")
    assert r.status_code == 204
    assert calls == [["/usr/bin/open", str((fake_archive.root / BANKS).resolve())]]
    assert reveal(client, "").status_code == 204  # "" is the archive folder itself


@pytest.mark.parametrize(
    "path",
    ["../", "..", "10. Financial/../../", "10. Financial/Banks/../../../etc", "/", "/etc"],
)
def test_reveal_folder_refuses_dotdot_and_absolute_paths(client, calls, path):
    r = reveal(client, path)
    assert r.status_code in (400, 404), (path, r.status_code)
    assert calls == []


def test_reveal_folder_refuses_an_absolute_path_to_a_real_outside_folder(
    client, calls, tmp_path
):
    outside = tmp_path / "outside"
    outside.mkdir()
    assert reveal(client, str(outside)).status_code in (400, 404)
    assert calls == []


def test_reveal_folder_refuses_a_symlink_that_leaves_the_archive(
    client, calls, fake_archive, tmp_path
):
    outside = tmp_path / "outside"
    outside.mkdir()
    (fake_archive.root / HOME).mkdir(exist_ok=True)
    (fake_archive.root / HOME / "escape").symlink_to(outside)
    r = reveal(client, f"{HOME}/escape")
    assert r.status_code in (400, 404), r.text
    assert calls == []


def test_reveal_folder_refuses_a_file(client, calls, fake_archive):
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="a1")
    assert reveal(client, f"{BANKS}/a.pdf").status_code in (400, 404)
    assert calls == []


# -- /api/maintenance/links/remove --------------------------------------------------


def broken_link(app, fake_archive):
    (fake_archive.root / ONG / "Sauna").mkdir()
    dead = fake_archive.root / ONG / "Sauna" / "dead.pdf"
    dead.symlink_to(fake_archive.root / "gone" / "x.pdf")
    app.scan()
    job = app.maintenance.start("broken_links", None)
    job.join(15)
    [link] = job.view().result.items
    return dead, link.drive_id


def remove(client, drive_ids, **extra):
    return client.post(
        "/api/maintenance/links/remove", json={"drive_ids": drive_ids, **extra}, headers=H
    )


def test_remove_links_dry_run_previews_and_changes_nothing(app, client, fake_archive):
    dead, drive_id = broken_link(app, fake_archive)
    r = remove(client, [drive_id], dry_run=True)
    assert r.status_code == 200, r.text
    assert [o["kind"] for o in r.json()["done"]] == ["unlink_symlink"]
    assert os.path.lexists(dead)
    assert app.activity.recent() == []  # nothing journaled


def test_remove_links_removes_a_broken_link_in_ongoing(app, client, fake_archive):
    dead, drive_id = broken_link(app, fake_archive)
    r = remove(client, [drive_id], dry_run=False)
    assert r.status_code == 200, r.text
    assert r.json()["error"] is None
    assert not os.path.lexists(dead)


def test_remove_links_refuses_ids_outside_the_publish_roots(app, client, fake_archive):
    (fake_archive.root / HOME).mkdir(exist_ok=True)
    dead = fake_archive.root / HOME / "dead.pdf"
    dead.symlink_to(fake_archive.root / "gone" / "x.pdf")
    real = fake_archive.add(f"{BANKS}/a.pdf", drive_id="a1")
    app.scan()
    job = app.maintenance.start("broken_links", None)
    job.join(15)
    [link] = job.view().result.items
    for ids in ([link.drive_id], ["a1"], ["nope"]):
        r = remove(client, ids, dry_run=False)
        assert r.status_code in (400, 404), (ids, r.status_code)
    assert os.path.lexists(dead) and real.exists()


def test_remove_links_needs_a_local_origin(app, client, fake_archive):
    dead, drive_id = broken_link(app, fake_archive)
    r = client.post("/api/maintenance/links/remove", json={"drive_ids": [drive_id]})
    assert r.status_code == 403
    assert os.path.lexists(dead)
