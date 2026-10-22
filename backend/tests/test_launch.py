"""Open and reveal (macOS ``open`` shown here), with an injected runner (nothing launches)."""

import os
import sys

import pytest
from fastapi.testclient import TestClient

from dam.api import create_api

BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}
BANKS = "10. Financial/Banks"


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


def post(client, url):
    return client.post(url, json={}, headers=LOCAL_ORIGIN)


def test_open_runs_open_with_list_args(app, client, calls, fake_archive):
    path = fake_archive.add(f"{BANKS}/statement 1.pdf", drive_id="s1")
    app.scan()
    r = post(client, "/api/files/s1/open")
    assert r.status_code == 204
    r = post(client, "/api/files/s1/reveal")
    assert r.status_code == 204
    real = str(path.resolve())
    assert calls == [["/usr/bin/open", real], ["/usr/bin/open", "-R", real]]
    assert all(isinstance(a, list) for a in calls)


def test_open_refuses_outside_archive(app, client, calls, fake_archive, tmp_path):
    fake_archive.add(f"{BANKS}/s.pdf", drive_id="s1")
    fake_archive.add("20. Home/h.pdf", drive_id="h1")
    app.scan()
    # a stale index: the folder is now a symlink to a folder outside the archive
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "s.pdf").write_bytes(b"secret")
    banks = fake_archive.root / BANKS
    os.rename(banks, tmp_path / "moved-away")
    banks.symlink_to(outside)
    r = post(client, "/api/files/s1/open")
    assert r.status_code == 400
    assert "outside the archive" in r.json()["error"]
    # a file symlink pointing outside
    (fake_archive.root / "20. Home" / "h.pdf").unlink()
    (fake_archive.root / "20. Home" / "h.pdf").symlink_to(outside / "s.pdf")
    assert post(client, "/api/files/h1/reveal").status_code == 400
    assert calls == []


def test_open_refuses_missing_and_unknown(app, client, calls, fake_archive):
    fake_archive.add(f"{BANKS}/gone.pdf", drive_id="g1")
    app.scan()
    (fake_archive.root / BANKS / "gone.pdf").unlink()
    assert post(client, "/api/files/g1/open").status_code == 404  # vanished, not rescanned
    app.scan()
    assert post(client, "/api/files/g1/open").status_code == 404  # missing
    assert post(client, "/api/files/nope/reveal").status_code == 404
    assert calls == []


def test_open_is_unsupported_on_other_platforms(app, client, calls, fake_archive):
    fake_archive.add(f"{BANKS}/s.pdf", drive_id="s1")
    app.scan()
    app.launch.platform = "freebsd14"
    r = post(client, "/api/files/s1/open")
    assert r.status_code == 501
    assert post(client, "/api/files/s1/reveal").status_code == 501
    assert calls == []


def test_open_failure_is_reported(app, client, fake_archive):
    fake_archive.add(f"{BANKS}/s.pdf", drive_id="s1")
    app.scan()
    app.launch.platform = "darwin"
    app.launch.runner = lambda args: 1
    r = post(client, "/api/files/s1/open")
    assert r.status_code == 409


@pytest.mark.parametrize(
    "name",
    [
        "Tool.app",
        "run.command",
        "x.terminal",
        "a.workflow",
        "s.sh",
        "i.pkg",
        "m.mpkg",
        "s.scpt",
        "a.action",
        "plain-binary",
    ],
)
def test_open_refuses_apps_and_scripts(app, client, calls, fake_archive, name):
    if name == "plain-binary" and sys.platform == "win32":
        pytest.skip("Windows has no executable permission bit")
    path = fake_archive.add(f"{BANKS}/{name}", drive_id="x1")
    if name == "plain-binary":
        path.chmod(0o755)
    app.scan()
    r = post(client, "/api/files/x1/open")
    assert r.status_code == 409
    assert r.json() == {"error": "Won't open apps or scripts from the archive — use Show in Finder"}
    assert calls == []
    # Show in Finder still works
    assert post(client, "/api/files/x1/reveal").status_code == 204
    assert calls == [["/usr/bin/open", "-R", str(path.resolve())]]


WIDENED = [
    ".jar",
    ".prefpane",
    ".saver",
    ".kext",
    ".webloc",
    ".url",
    ".inetloc",
    ".fileloc",
    ".appex",
    ".qlgenerator",
    ".mdimporter",
    ".plugin",
    ".bundle",
    ".framework",
    ".dmg",
    ".iso",
    ".tool",
    ".mobileconfig",
    ".shortcut",
    ".scptd",
    ".osax",
    ".xpc",
    ".service",
    ".photoslibrary",
    ".musiclibrary",
    ".fcpbundle",
]


@pytest.mark.parametrize("ext", WIDENED)
def test_open_refuses_launchers_bundles_and_disk_images(app, client, calls, fake_archive, ext):
    path = fake_archive.add(f"{BANKS}/thing{ext.upper() if ext == '.dmg' else ext}", drive_id="w1")
    app.scan()
    r = post(client, "/api/files/w1/open")
    assert r.status_code == 409
    assert r.json() == {"error": "Won't open apps or scripts from the archive — use Show in Finder"}
    assert calls == []
    assert post(client, "/api/files/w1/reveal").status_code == 204
    assert calls == [["/usr/bin/open", "-R", str(path.resolve())]]


def test_app_bundle_folder_refused(app, client, calls, fake_archive):
    fake_archive.add(f"{BANKS}/Thing.app/Contents/Info.plist", drive_id=None)
    (fake_archive.root / BANKS / "Thing.app").chmod(0o755)
    app.scan()
    rec = app.repo.by_path(f"{BANKS}/Thing.app")
    r = post(client, f"/api/files/{rec.drive_id}/open")
    assert r.status_code == 409
    assert "apps or scripts" in r.json()["error"]
    assert calls == []


def test_open_refuses_folders_but_reveals_them(app, client, calls, fake_archive):
    fake_archive.add(f"{BANKS}/2024/s.pdf", drive_id="s1")
    app.scan()
    rec = app.repo.by_path(f"{BANKS}/2024")
    assert rec.is_dir
    r = post(client, f"/api/files/{rec.drive_id}/open")
    assert r.status_code == 409
    assert r.json() == {"error": "Won't open folders from the archive — use Show in Finder"}
    assert calls == []
    assert post(client, f"/api/files/{rec.drive_id}/reveal").status_code == 204
    real = str((fake_archive.root / BANKS / "2024").resolve())
    assert calls == [["/usr/bin/open", "-R", real]]


def test_open_refuses_folder_the_index_thinks_is_a_file(app, client, calls, fake_archive):
    path = fake_archive.add(f"{BANKS}/report", drive_id="r1")
    app.scan()
    path.unlink()
    path.mkdir()  # replaced by a folder after indexing; the record still says file
    assert not app.repo.by_path(f"{BANKS}/report").is_dir
    r = post(client, "/api/files/r1/open")
    assert r.status_code == 409
    assert "folders" in r.json()["error"]
    assert calls == []


@pytest.mark.parametrize("bundle", ["Thing.app", "Lib.photoslibrary", "x.framework", "S.scptd"])
def test_open_refuses_files_inside_runnable_bundles(app, client, calls, fake_archive, bundle):
    path = fake_archive.add(f"{BANKS}/{bundle}/Contents/Resources/readme.txt", drive_id="in1")
    app.scan()
    r = post(client, "/api/files/in1/open")
    assert r.status_code == 409
    assert r.json() == {"error": "Won't open apps or scripts from the archive — use Show in Finder"}
    assert calls == []
    assert post(client, "/api/files/in1/reveal").status_code == 204
    assert calls == [["/usr/bin/open", "-R", str(path.resolve())]]


def test_open_refuses_file_whose_resolved_ancestor_is_a_bundle(app, client, calls, fake_archive):
    fake_archive.add(f"{BANKS}/Real.app/Contents/notes.txt", drive_id=None)
    link = fake_archive.root / BANKS / "notes.txt"
    link.symlink_to(fake_archive.root / BANKS / "Real.app" / "Contents" / "notes.txt")
    app.scan()
    rec = app.repo.by_path(f"{BANKS}/notes.txt")
    if rec is None or not rec.drive_id:
        pytest.skip("scanner does not index symlinked files")
    assert post(client, f"/api/files/{rec.drive_id}/open").status_code == 409
    assert calls == []


def test_open_uses_absolute_open_binary(app, client, calls, fake_archive):
    fake_archive.add(f"{BANKS}/s.pdf", drive_id="s1")
    app.scan()
    assert post(client, "/api/files/s1/open").status_code == 204
    assert calls[0][0] == "/usr/bin/open"


def test_501_only_on_open_and_reveal(app):
    schema = create_api(app).openapi()
    with_501 = sorted(
        (path, method)
        for path, ops in schema["paths"].items()
        for method, op in ops.items()
        if "501" in op.get("responses", {})
    )
    assert with_501 == [
        ("/api/files/{drive_id}/open", "post"),
        ("/api/files/{drive_id}/reveal", "post"),
    ]
