"""HTTP API tests.

Every client talks to ``http://127.0.0.1:8765`` (the default port), so the ``Host`` header
is local. Mutating requests (POST) must say where they come from: the local-only
middleware refuses a POST that has neither a local ``Origin`` nor ``Sec-Fetch-Site:
same-origin``/``none``. Browsers always send these headers; ``TestClient`` (like curl)
does not, so the tests send ``Origin`` explicitly through ``post()``.
"""

import io
import json
import os
import sys
import threading
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from typer.testing import CliRunner

from dam.api import create_api, preview
from dam.cli import main as cli_main
from dam.db.tables import operations
from dam.ops.model import OpFailed
from dam.serve import start_background
from dam.services.browse import BrowseService
from dam.services.inbox import InboxService
from pdfs import make_text_pdf

BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}
INBOX = "##. Organize"
BANKS = "10. Financial/Banks"
QUAR = "##. To Delete"


def make_client(app, static_dir=None) -> TestClient:
    return TestClient(create_api(app, static_dir), base_url=BASE)


@pytest.fixture
def client(app):
    with make_client(app) as c:
        yield c


def post(client: TestClient, url: str, body=None, **kw):
    """POST as the UI would: JSON content type and a local ``Origin`` header."""
    headers = {**LOCAL_ORIGIN, **kw.pop("headers", {})}
    return client.post(url, json=body if body is not None else {}, headers=headers, **kw)


def journal(app) -> list:
    with app.engine.connect() as conn:
        return list(conn.execute(select(operations).order_by(operations.c.id)).mappings())


@pytest.fixture
def inbox_file(app, fake_archive):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-1")
    app.scan()
    return "id-1"


def req(drive_id="id-1", name="b.pdf", folder=BANKS, tags=()):
    return {"drive_id": drive_id, "name": name, "folder": folder, "tags": list(tags)}


# -- status -----------------------------------------------------------------


def test_status(client, app, fake_archive):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-1")
    fake_archive.add(f"{INBOX}/b.pdf", drive_id="id-2")
    fake_archive.add(f"{BANKS}/s.txt", content=b"hello", drive_id="id-3")
    fake_archive.add(f"{BANKS}/gone.txt", drive_id="id-4")
    app.scan()
    (fake_archive.root / BANKS / "gone.txt").unlink()
    app.scan()
    app.repo.set_index_state("id-2", "cloud_pending")
    app.repo.set_index_state("id-3", "indexed")
    r = client.get("/api/status")
    assert r.status_code == 200
    assert r.json() == {
        "configured": True,
        "archive": {"id": "main", "name": "Main", "color": "#3b6fd4"},
        "profiles_count": 1,
        "inbox_exists": True,
        "page1": {"read": 0, "total": 0, "backfill": True},
        "files": 3,
        "indexed": 1,
        "pending": 1,
        "cloud_pending": 1,
        "errors": 0,
        "unsupported": 0,
        "missing": 1,
        "inbox_count": 2,
        "rule_errors": [],
        "tray_errors": [],
        "recovery_pending": 0,
        "archive_available": True,
        "special_folders": {
            "inbox": "##. Organize",
            "ongoing": "##. Ongoing",
            "important": "##. Important",
            "quarantine": "##. To Delete",
        },
    }


def test_status_reports_archive_unavailable(client, app, fake_archive, tmp_path):
    os.rename(fake_archive.root, tmp_path / "archive-away")
    try:
        assert client.get("/api/status").json()["archive_available"] is False
    finally:
        os.rename(tmp_path / "archive-away", fake_archive.root)
    assert client.get("/api/status").json()["archive_available"] is True


def test_initial_scan_with_archive_gone_warns(app, fake_archive, tmp_path, caplog):
    import logging

    from dam.serve import _initial_scan

    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-a")
    app.scan()
    os.rename(fake_archive.root, tmp_path / "archive-away")
    wake = threading.Event()
    with caplog.at_level(logging.WARNING, logger="dam.serve"):
        _initial_scan(app, wake)
    assert wake.is_set()
    assert any("not available" in r.message for r in caplog.records)
    assert app.repo.get("id-a").missing is False


def test_status_reports_rule_errors(client, app):
    (app.rules_dir / "broken.yaml").write_text("- nonsense: [", encoding="utf-8")
    app.reload_rules()
    errors = client.get("/api/status").json()["rule_errors"]
    assert errors and errors[0]["file"].endswith("broken.yaml") and errors[0]["message"]


# -- inbox ------------------------------------------------------------------


def test_inbox_flow_preview_then_file(client, app, fake_archive, inbox_file):
    entries = client.get("/api/inbox").json()
    assert [e["record"]["drive_id"] for e in entries] == ["id-1"]
    assert entries[0]["suggestion"]["name"] and "text_excerpt" in entries[0]

    r = post(client, "/api/inbox/preview", [req(tags=["bank"])])
    assert r.status_code == 200, r.text
    assert r.json() == [
        {
            "kind": "move",
            "src": f"{INBOX}/a.pdf",
            "dst": f"{BANKS}/b.pdf",
            "drive_id": "id-1",
            "note": None,
        }
    ]
    assert journal(app) == []  # a preview changes nothing

    r = post(client, "/api/inbox/file", {"requests": [req(tags=["bank"])], "dry_run": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is False and body["batch_id"]
    assert [op["dst"] for op in body["done"]] == [f"{BANKS}/b.pdf"]
    assert body["tag_error"] is None and body["untagged"] == []
    assert (fake_archive.root / BANKS / "b.pdf").exists()
    assert app.tags.for_file("id-1") == ["bank"]
    assert {row["origin"] for row in journal(app)} == {"ui"}


def test_file_dry_run_changes_nothing(client, app, fake_archive, inbox_file):
    r = post(client, "/api/inbox/file", {"requests": [req()], "dry_run": True})
    assert r.status_code == 200 and r.json()["dry_run"] is True
    assert (fake_archive.root / INBOX / "a.pdf").exists()
    assert journal(app) == []


def test_file_reports_tag_error(client, inbox_file, monkeypatch):
    def broken(self, drive_id, names):
        raise RuntimeError("db locked")

    monkeypatch.setattr("dam.index.repo.TagRepo.add", broken)
    r = post(client, "/api/inbox/file", {"requests": [req(tags=["t"])], "dry_run": False})
    assert r.status_code == 200
    assert "db locked" in r.json()["tag_error"] and r.json()["untagged"] == ["id-1"]


@pytest.mark.parametrize(
    "body",
    [
        {"requests": [req()], "dry_run": False, "origin": "workflow"},
        {"requests": [{**req(), "origin": "cli"}], "dry_run": False},
    ],
)
def test_body_cannot_carry_origin(client, app, inbox_file, body):
    r = post(client, "/api/inbox/file", body)
    assert r.status_code == 422 and "error" in r.json()
    assert journal(app) == []


def test_guard_error_is_400(client, app, inbox_file):
    r = post(client, "/api/inbox/preview", [req(folder="")])  # the archive root
    assert r.status_code == 400
    assert r.json() == {"error": "Files cannot go directly in the archive folder."}


@pytest.mark.parametrize(
    "request_",
    [req(folder="../outside"), req(name="a/b.pdf")],
)
def test_invalid_requests_are_400(client, inbox_file, request_):
    r = post(client, "/api/inbox/preview", [request_])
    assert r.status_code == 400 and set(r.json()) == {"error"}


def test_unknown_drive_id_is_404_json(client, inbox_file):
    r = post(client, "/api/inbox/preview", [req(drive_id="nope")])
    assert r.status_code == 404 and r.json() == {"error": "nope"}
    for url in ("/api/files/nope", "/api/files/nope/raw", "/api/files/nope/page/1.png"):
        r = client.get(url)
        assert r.status_code == 404 and r.json() == {"error": "nope"}, url


def test_op_failed_is_409(client, inbox_file, monkeypatch):
    def failing(self, reqs, dry_run=False, origin="ui", via="form"):
        raise OpFailed("disk went away")

    monkeypatch.setattr(InboxService, "file_it", failing)
    r = post(client, "/api/inbox/file", {"requests": [req()], "dry_run": False})
    assert r.status_code == 409 and r.json() == {"error": "disk went away"}


def test_internal_error_is_generic_500(client, app, monkeypatch):
    def boom(self):
        raise RuntimeError("secret detail /Users/someone/medical.pdf")

    monkeypatch.setattr(BrowseService, "folders", boom)
    r = client.get("/api/folders")
    assert r.status_code == 500
    assert r.json() == {"error": "internal error"}
    assert "Traceback" not in r.text and "secret" not in r.text
    log = (app.app_paths.logs_dir / "dam.log").read_text(encoding="utf-8")
    assert "Traceback" in log and "secret detail" in log


def test_error_after_response_started_is_reraised(app):
    import asyncio

    from dam.api.security import InternalErrorMiddleware

    async def streams_then_fails(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("mid-stream")

    sent = []

    async def send(message):
        sent.append(message)

    mw = InternalErrorMiddleware(streams_then_fails, app.app_paths.logs_dir)
    with pytest.raises(RuntimeError, match="mid-stream"):
        asyncio.run(mw({"type": "http", "method": "GET", "path": "/x"}, None, send))
    assert [m["status"] for m in sent] == [200]  # no second response start


# -- files ------------------------------------------------------------------


def test_file_detail_with_tags(client, app, inbox_file):
    app.tags.add("id-1", ["b", "a"])
    r = client.get("/api/files/id-1")
    assert r.status_code == 200
    assert r.json()["record"]["path"] == f"{INBOX}/a.pdf" and r.json()["tags"] == ["a", "b"]
    assert "path_nfc" not in r.json()["record"]


def test_raw_file_headers(client, app, fake_archive):
    fake_archive.add(f"{BANKS}/evil.html", content=b"<script>alert(1)</script>", drive_id="h1")
    app.scan()
    r = client.get("/api/files/h1/raw")
    assert r.status_code == 200 and r.content == b"<script>alert(1)</script>"
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["content-disposition"].startswith("inline")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-security-policy"] == "sandbox; default-src 'none'"
    assert r.headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize("url", ["/api/status", "/api/files/nope", "/api/nope"])
def test_json_responses_are_nosniff(client, url):
    assert client.get(url).headers["x-content-type-options"] == "nosniff"


def test_refusals_are_nosniff(client):
    r = client.get("/api/status", headers={"Host": "evil.com"})
    assert r.status_code == 403 and r.headers["x-content-type-options"] == "nosniff"


def test_raw_refuses_dir_link_missing_and_parked(client, app, fake_archive, tmp_path):
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="a")
    fake_archive.add(f"{BANKS}/gone.pdf", drive_id="gone")
    fake_archive.add(f"{BANKS}/parked.pdf", drive_id="parked")
    # a link serves its target only inside the archive (tests/test_links.py)
    (tmp_path / "outside.pdf").write_bytes(b"secret")
    (fake_archive.root / "##. Ongoing/l.pdf").symlink_to(tmp_path / "outside.pdf")
    app.scan()
    (fake_archive.root / BANKS / "gone.pdf").unlink()
    app.scan()
    app.repo.park(f"{BANKS}/parked.pdf")
    folder_id = app.repo.by_path(BANKS).drive_id
    link_id = app.repo.by_path("##. Ongoing/l.pdf").drive_id
    for drive_id in (folder_id, link_id, "gone", "parked"):
        r = client.get(f"/api/files/{drive_id}/raw")
        assert r.status_code == 404 and set(r.json()) == {"error"}, drive_id


def test_page_png_for_pdf(client, app, fake_archive):
    make_text_pdf(fake_archive.add(f"{BANKS}/doc.pdf", drive_id="p1"))
    app.scan()
    r = client.get("/api/files/p1/page/1.png?w=400")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")
    assert Image.open(io.BytesIO(r.content)).width == 400


@pytest.mark.parametrize(
    ("w", "expected"), [(10, 400), (400, 400), (401, 900), (1400, 1400), (99999, 2000)]
)
def test_page_width_is_bucketed(client, app, fake_archive, w, expected):
    make_text_pdf(fake_archive.add(f"{BANKS}/doc.pdf", drive_id="p1"))
    app.scan()
    r = client.get(f"/api/files/p1/page/1.png?w={w}")
    assert Image.open(io.BytesIO(r.content)).width == expected


def test_nearby_widths_share_a_cache_file(client, app, fake_archive, monkeypatch):
    make_text_pdf(fake_archive.add(f"{BANKS}/doc.pdf", drive_id="p1"))
    app.scan()
    calls = []
    real = preview.render_page
    monkeypatch.setattr(preview, "render_page", lambda *a: calls.append(a) or real(*a))
    assert client.get("/api/files/p1/page/1.png?w=901").status_code == 200
    assert client.get("/api/files/p1/page/1.png?w=1400").status_code == 200
    assert len(calls) == 1
    [cached] = (app.app_paths.cache_dir / "pages").iterdir()
    assert cached.name.endswith("_1_1400.png")


def test_tall_page_stays_within_pixel_cap(client, app, fake_archive):
    make_text_pdf(fake_archive.add(f"{BANKS}/tall.pdf", drive_id="t1"), mediabox="0 0 200 14400")
    app.scan()
    r = client.get("/api/files/t1/page/1.png?w=2000")
    assert r.status_code == 200
    img = Image.open(io.BytesIO(r.content))
    assert img.width * img.height <= preview.MAX_PIXELS
    assert img.height > 10 * img.width  # still the whole page, just at a lower scale


@pytest.mark.parametrize("size", [(0, 792), (612, 0), (-5, 792)])
def test_zero_size_page_is_404(client, app, fake_archive, monkeypatch, size):
    import pypdfium2

    make_text_pdf(fake_archive.add(f"{BANKS}/doc.pdf", drive_id="p1"))
    app.scan()
    monkeypatch.setattr(pypdfium2.PdfPage, "get_size", lambda self: size)
    r = client.get("/api/files/p1/page/1.png")
    assert r.status_code == 404 and set(r.json()) == {"error"}


@pytest.mark.parametrize(
    "error", [lambda: __import__("pypdfium2").PdfiumError("bitmap"), lambda: MemoryError()]
)
def test_render_failure_is_404_and_logged(client, app, fake_archive, monkeypatch, caplog, error):
    import pypdfium2

    make_text_pdf(fake_archive.add(f"{BANKS}/doc.pdf", drive_id="p1"))
    app.scan()

    def broken(self, *a, **kw):
        raise error()

    monkeypatch.setattr(pypdfium2.PdfPage, "render", broken)
    r = client.get("/api/files/p1/page/1.png")
    assert r.status_code == 404 and set(r.json()) == {"error"}
    assert "doc.pdf" in caplog.text


def test_oversize_pdf_is_404_without_reading(client, app, fake_archive, monkeypatch):

    make_text_pdf(fake_archive.add(f"{BANKS}/doc.pdf", drive_id="p1"))
    app.scan()
    monkeypatch.setattr(preview, "MAX_BYTES", 10)
    monkeypatch.setattr(preview, "_read", lambda path: pytest.fail("read the file"))
    r = client.get("/api/files/p1/page/1.png")
    assert r.status_code == 404 and set(r.json()) == {"error"}


def test_page_png_served_from_cache(client, app, fake_archive, monkeypatch):
    make_text_pdf(fake_archive.add(f"{BANKS}/doc.pdf", drive_id="p1"))
    app.scan()
    calls = []
    real = preview.render_page

    def counting(path, n, width):
        calls.append((n, width))
        return real(path, n, width)

    monkeypatch.setattr(preview, "render_page", counting)
    first = client.get("/api/files/p1/page/1.png")
    second = client.get("/api/files/p1/page/1.png")
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert calls == [(1, 900)]
    [cached] = (app.app_paths.cache_dir / "pages").iterdir()
    assert cached.name.startswith("p1_") and cached.name.endswith("_1_900.png")


def test_page_cache_uses_sha_when_known(client, app, fake_archive):
    make_text_pdf(fake_archive.add(f"{BANKS}/doc.pdf", drive_id="p1"))
    app.scan()
    app.index()
    sha = app.repo.get("p1").sha256
    assert sha
    assert client.get("/api/files/p1/page/1.png?w=400").status_code == 200
    assert (app.app_paths.cache_dir / "pages" / f"{sha}_1_400.png").exists()


def test_truncated_cache_file_is_not_served(client, app, fake_archive):
    make_text_pdf(fake_archive.add(f"{BANKS}/doc.pdf", drive_id="p1"))
    app.scan()
    good = client.get("/api/files/p1/page/1.png").content
    [cached] = (app.app_paths.cache_dir / "pages").iterdir()
    cached.write_bytes(good[:50])  # e.g. a crash while writing
    assert client.get("/api/files/p1/page/1.png").content == good
    assert cached.read_bytes() == good  # repaired (overwritten, never deleted)


def test_page_png_404_for_non_pdf_and_bad_page(client, app, fake_archive):
    make_text_pdf(fake_archive.add(f"{BANKS}/doc.pdf", drive_id="p1"))
    fake_archive.add(f"{BANKS}/photo.jpg", drive_id="j1")
    fake_archive.add(f"{BANKS}/broken.pdf", content=b"not a pdf", drive_id="b1")
    app.scan()
    for url in (
        "/api/files/j1/page/1.png",
        "/api/files/p1/page/2.png",
        "/api/files/p1/page/0.png",
        "/api/files/b1/page/1.png",
    ):
        r = client.get(url)
        assert r.status_code == 404 and set(r.json()) == {"error"}, url


def test_at_most_two_renders_hold_file_bytes(client, app, fake_archive, monkeypatch):
    for i in range(4):
        make_text_pdf(fake_archive.add(f"{BANKS}/doc{i}.pdf", drive_id=f"c{i}"))
    app.scan()
    release = threading.Event()
    lock = threading.Lock()
    active = [0]
    peak = [0]
    real_read = preview._read

    def blocking_read(path):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        try:
            release.wait(10)
            return real_read(path)
        finally:
            with lock:
                active[0] -= 1

    monkeypatch.setattr(preview, "_read", blocking_read)
    results = []
    threads = [
        threading.Thread(
            target=lambda i=i: results.append(client.get(f"/api/files/c{i}/page/1.png"))
        )
        for i in range(4)
    ]
    for t in threads:
        t.start()
    deadline = time.monotonic() + 5
    while active[0] < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.3)  # give a third render every chance to start
    assert peak[0] == 2
    release.set()
    for t in threads:
        t.join(10)
    assert sorted(r.status_code for r in results) == [200] * 4
    assert peak[0] == 2


def test_cache_hits_bypass_the_render_limit(client, app, fake_archive):
    make_text_pdf(fake_archive.add(f"{BANKS}/doc.pdf", drive_id="p1"))
    app.scan()
    first = client.get("/api/files/p1/page/1.png").content
    with preview.RENDER_SEMAPHORE, preview.RENDER_SEMAPHORE:  # every render slot taken
        assert client.get("/api/files/p1/page/1.png").content == first


def test_vanished_file_is_404(app, fake_archive):
    from dam.services.errors import NotFound

    path = make_text_pdf(fake_archive.add(f"{BANKS}/doc.pdf", drive_id="p1"))
    app.scan()
    rec = app.repo.get("p1")
    path.unlink()
    with pytest.raises(NotFound):
        preview.cached_page(app.app_paths.cache_dir / "pages", rec, path, 1, 900)
    with pytest.raises(NotFound):
        preview.render_page(path, 1, 900)


def test_page_render_holds_the_pdfium_lock(app, fake_archive):
    from dam.pdfium import PDFIUM_LOCK

    path = make_text_pdf(fake_archive.add(f"{BANKS}/doc.pdf", drive_id="p1"))
    done = threading.Event()
    with PDFIUM_LOCK:
        t = threading.Thread(target=lambda: (preview.render_page(path, 1, 300), done.set()))
        t.start()
        assert not done.wait(0.3)  # blocked while another thread holds the lock
    assert done.wait(10)
    t.join()


# -- browse, search, quarantine, activity, recovery ----------------------------


def test_browse_folders_and_search(client, app, fake_archive):
    fake_archive.add(f"{BANKS}/statement.txt", content=b"quarterly zebra report", drive_id="s1")
    app.scan()
    app.index()
    names = [e["name"] for e in client.get("/api/browse", params={"path": BANKS}).json()]
    assert names == ["statement.txt"]
    root = client.get("/api/browse").json()
    assert root[0]["is_dir"] and "10. Financial" in [e["name"] for e in root]
    folders = client.get("/api/folders").json()
    assert BANKS in folders and QUAR not in folders and INBOX not in folders
    hits = client.get("/api/search", params={"q": "zebra", "folder": "10. Financial"}).json()
    assert [h["drive_id"] for h in hits] == ["s1"] and "[zebra]" in hits[0]["snippet"]
    # the Browse columns: size and date, as the folder listing has them
    assert hits[0]["size"] == len(b"quarterly zebra report") and hits[0]["mtime"] > 0
    assert client.get("/api/search", params={"q": "zebra", "folder": INBOX}).json() == []


def test_quarantine_endpoint(client, app, fake_archive):
    fake_archive.add(f"{BANKS}/old.pdf", drive_id="q1")
    app.scan()
    r = post(client, "/api/quarantine", {"drive_ids": ["q1"], "dry_run": True})
    assert r.status_code == 200 and r.json()["dry_run"] is True
    assert (fake_archive.root / BANKS / "old.pdf").exists()
    r = post(client, "/api/quarantine", {"drive_ids": ["q1"], "dry_run": False})
    assert r.status_code == 200 and r.json()["done"][-1]["dst"] == f"{QUAR}/{BANKS}/old.pdf"
    assert (fake_archive.root / QUAR / BANKS / "old.pdf").exists()
    assert post(client, "/api/quarantine", {"drive_ids": ["nope"]}).status_code == 404


def test_activity_batches_carry_a_label(client, app, fake_archive, inbox_file):
    """Each workflow states what the user did; an undo batch names what it reverted."""
    fake_archive.add(f"{BANKS}/old.pdf", drive_id="q1")
    app.scan()
    filed = post(client, "/api/inbox/file", {"requests": [req()], "dry_run": False}).json()
    trashed = post(client, "/api/quarantine", {"drive_ids": ["q1"], "dry_run": False}).json()
    by_id = {b["batch_id"]: b for b in client.get("/api/activity").json()}
    assert by_id[filed["batch_id"]]["label"].startswith("Filed ")
    assert by_id[filed["batch_id"]]["label"].endswith(f" into {BANKS}")
    assert by_id[trashed["batch_id"]]["label"] == "Moved old.pdf to To Delete"
    assert post(client, f"/api/activity/{trashed['batch_id']}/undo").status_code == 200
    undo = next(b for b in client.get("/api/activity").json() if b["is_undo"])
    assert undo["undo_of"] == trashed["batch_id"]
    assert undo["undoes_label"] == "Moved old.pdf to To Delete"
    # a dry run journals nothing, so labels only ever come from applied batches
    assert all(row["label"] for row in journal(app) if row["origin"] == "ui")


def test_undo_endpoint(client, app, fake_archive, inbox_file):
    batch = post(client, "/api/inbox/file", {"requests": [req()], "dry_run": False}).json()
    activity = client.get("/api/activity", params={"limit": 5}).json()
    assert [b["batch_id"] for b in activity] == [batch["batch_id"]]
    assert activity[0]["origin"] == "ui" and activity[0]["ops"][0]["kind"] == "move"

    r = post(client, f"/api/activity/{batch['batch_id']}/undo")
    assert r.status_code == 200 and not r.json()["error"]
    assert r.json()["follow_up_error"] is None
    assert (fake_archive.root / INBOX / "a.pdf").exists()
    assert not (fake_archive.root / BANKS / "b.pdf").exists()
    newest, original = client.get("/api/activity").json()
    assert newest["is_undo"] and original["undone"]
    assert post(client, "/api/activity/nope/undo").status_code == 404


def _journal_count(app) -> int:
    with app.engine.connect() as conn:
        return len(conn.execute(select(operations.c.id)).all())


def test_undo_preview_is_what_undo_then_applies(client, app, fake_archive, inbox_file):
    body = {"requests": [req(folder=f"{BANKS}/2026")], "dry_run": False}  # a new folder too
    batch = post(client, "/api/inbox/file", body).json()
    before = _journal_count(app)
    r = post(client, f"/api/activity/{batch['batch_id']}/undo/preview")
    assert r.status_code == 200, r.text
    preview = r.json()
    # read only: nothing moved, nothing journaled
    assert _journal_count(app) == before
    assert (fake_archive.root / BANKS / "2026" / "b.pdf").exists()
    assert preview == [
        {
            "kind": "move",
            "src": f"{BANKS}/2026/b.pdf",
            "dst": f"{INBOX}/a.pdf",
            "drive_id": "id-1",
            "note": None,
        }
    ]  # the created folder stays: no op for it
    undone = post(client, f"/api/activity/{batch['batch_id']}/undo").json()
    assert undone["done"] == preview
    # the undo batch itself: refused like undo (409), and still nothing journaled
    newest = client.get("/api/activity").json()[0]
    assert newest["is_undo"]
    before = _journal_count(app)
    r = post(client, f"/api/activity/{newest['batch_id']}/undo/preview")
    assert r.status_code == 409 and "cannot be undone" in r.json()["error"]
    assert _journal_count(app) == before
    assert post(client, "/api/activity/nope/undo/preview").status_code == 404


def test_undo_preview_refuses_a_changed_file(client, app, fake_archive, inbox_file):
    batch = post(client, "/api/inbox/file", {"requests": [req()], "dry_run": False}).json()
    os.rename(fake_archive.root / BANKS / "b.pdf", fake_archive.root / BANKS / "c.pdf")
    r = post(client, f"/api/activity/{batch['batch_id']}/undo/preview")
    assert r.status_code == 409 and "cannot be undone" in r.json()["error"]


def test_recovery_endpoints(client, app):
    assert client.get("/api/recovery").json() == []
    r = post(client, "/api/recovery")
    assert r.status_code == 200 and r.json() == {"entries": [], "index_errors": []}


# -- local-only middleware ---------------------------------------------------------


def test_foreign_host_rejected(client):
    r = client.get("/api/status", headers={"Host": "evil.com"})
    assert r.status_code == 403 and set(r.json()) == {"error"}


@pytest.mark.parametrize("host", ["127.0.0.1:9999", "127.0.0.1", "evil.com:8765", "localhost"])
def test_host_must_match_port_exactly(client, host):
    assert client.get("/api/status", headers={"Host": host}).status_code == 403


def test_localhost_host_allowed(client):
    assert client.get("/api/status", headers={"Host": "localhost:8765"}).status_code == 200


def test_get_without_origin_allowed(client):
    """Non-browser clients (curl) send no Origin; reads are fine."""
    assert client.get("/api/status").status_code == 200


def test_cross_origin_post_rejected(client, app, inbox_file):
    r = post(
        client, "/api/inbox/file", {"requests": [req()]}, headers={"Origin": "http://evil.com"}
    )
    assert r.status_code == 403
    assert journal(app) == []


@pytest.mark.parametrize("origin", ["null", "http://127.0.0.1:9999", "https://127.0.0.1:8765"])
def test_non_local_origins_rejected(client, origin):
    assert post(client, "/api/recovery", headers={"Origin": origin}).status_code == 403


def test_localhost_origin_allowed(client):
    r = post(client, "/api/recovery", headers={"Origin": "http://localhost:8765"})
    assert r.status_code == 200


def test_post_without_origin_or_fetch_site_rejected(client):
    assert client.post("/api/recovery", json={}).status_code == 403


@pytest.mark.parametrize("site", ["same-origin", "none"])
def test_post_with_local_fetch_site_allowed(client, site):
    r = client.post("/api/recovery", json={}, headers={"Sec-Fetch-Site": site})
    assert r.status_code == 200


@pytest.mark.parametrize("method", ["get", "post"])
def test_cross_site_fetch_rejected(client, method):
    headers = {**LOCAL_ORIGIN, "Sec-Fetch-Site": "cross-site"}
    if method == "get":
        r = client.get("/api/status", headers=headers)
    else:
        r = client.post("/api/recovery", json={}, headers=headers)
    assert r.status_code == 403


@pytest.mark.parametrize("content_type", [None, "application/x-www-form-urlencoded", "text/plain"])
def test_post_requires_json_content_type(client, content_type):
    headers = dict(LOCAL_ORIGIN)
    if content_type:
        headers["Content-Type"] = content_type
    r = client.post("/api/recovery", content=b"{}", headers=headers)
    assert r.status_code == 415 and set(r.json()) == {"error"}


def test_json_content_type_with_charset_allowed(client):
    headers = {**LOCAL_ORIGIN, "Content-Type": "application/json; charset=utf-8"}
    assert client.post("/api/recovery", content=b"{}", headers=headers).status_code == 200


VITE = {"Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-origin"}


def test_dev_origin_off_by_default(client):
    # What the browser sends through the Vite proxy (changeOrigin rewrites only Host).
    assert post(client, "/api/recovery", headers=VITE).status_code == 403


def test_dev_origin_allowance(app, monkeypatch):
    monkeypatch.setenv("DAM_DEV_ORIGIN", "http://localhost:5173")
    with make_client(app) as c:
        assert post(c, "/api/recovery", headers=VITE).status_code == 200
        assert post(c, "/api/recovery", headers={"Origin": "http://evil.com"}).status_code == 403
        assert c.get("/api/status", headers={"Host": "localhost:5173"}).status_code == 403


@pytest.mark.parametrize(
    "value", ["http://evil.com", "https://localhost:5173", "http://localhost", "*", "null"]
)
def test_invalid_dev_origin_is_ignored_with_warning(app, monkeypatch, caplog, value):
    monkeypatch.setenv("DAM_DEV_ORIGIN", value)
    with make_client(app) as c:
        r = post(c, "/api/recovery", headers={"Origin": value, "Sec-Fetch-Site": "same-site"})
        assert r.status_code == 403
    assert "DAM_DEV_ORIGIN" in caplog.text


def _scope(headers, method="GET", server=("127.0.0.1", 8765)):
    return {
        "type": "http",
        "method": method,
        "server": server,
        "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
    }


def test_missing_host_or_server_refused():
    from dam.api.security import LocalOnlyMiddleware

    gate = LocalOnlyMiddleware(None)
    assert gate.refusal(_scope({}))[0] == 403
    assert gate.refusal(_scope({"host": "127.0.0.1:8765"}, server=None))[0] == 403
    assert gate.refusal(_scope({"host": "127.0.0.1:8765"})) is None


@pytest.mark.parametrize("host", ["LOCALHOST:8765", "localhost.:8765", "127.0.0.1.:8765"])
def test_host_variants_refused(client, host):
    """Exact match only: browsers send the lower-case host as typed, without a dot."""
    assert client.get("/api/status", headers={"Host": host}).status_code == 403


def test_preflight_from_foreign_origin_refused(client):
    r = client.options(
        "/api/inbox/file",
        headers={
            "Origin": "http://evil.com",
            "Access-Control-Request-Method": "POST",
            "Sec-Fetch-Site": "cross-site",
        },
    )
    assert r.status_code == 403
    assert "access-control-allow-origin" not in r.headers


def test_head_passes_the_gate_but_not_a_foreign_host(client):
    assert client.head("/api/status").status_code == 405  # gate passed; no HEAD route
    assert client.head("/api/status", headers={"Host": "evil.com"}).status_code == 403


def test_docs_are_disabled(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404


# -- static files ---------------------------------------------------------------


INDEX_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)


@pytest.fixture
def static_dir(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><title>dam</title>", encoding="utf-8")
    (d / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
    return d


def test_static_and_spa_fallback(app, static_dir):
    with make_client(app, static_dir) as c:
        for url in ("/", "/inbox/some/route"):
            r = c.get(url)
            assert r.status_code == 200 and "<title>dam</title>" in r.text, url
            assert r.headers["x-content-type-options"] == "nosniff"
            assert r.headers["x-frame-options"] == "DENY"
            assert r.headers["referrer-policy"] == "no-referrer"
            assert r.headers["content-security-policy"] == INDEX_CSP
        r = c.get("/assets/app.js")
        assert r.status_code == 200 and r.text == "console.log(1)"
        assert "javascript" in r.headers["content-type"]
        r = c.get("/api/nope")
        assert r.status_code == 404 and r.json() == {"error": "Not Found"}
        r = c.get("/..%2Fsecret.txt")
        assert r.status_code == 200 and r.text == "<!doctype html><title>dam</title>"
        assert c.get("/", headers={"Host": "evil.com"}).status_code == 403


def test_no_static_dir_means_api_only(app, tmp_path):
    with make_client(app, tmp_path / "missing") as c:
        assert c.get("/").status_code == 404
        r = c.get("/api/nope")
        assert r.status_code == 404 and r.json() == {"error": "Not Found"}


# -- openapi + serve --------------------------------------------------------------


def test_openapi_schema_is_typed(app):
    schema = create_api(app).openapi()
    for path in ("/api/status", "/api/inbox", "/api/inbox/file", "/api/files/{drive_id}"):
        assert path in schema["paths"]
    ok = schema["paths"]["/api/inbox/file"]["post"]["responses"]["200"]
    assert ok["content"]["application/json"]["schema"]["$ref"].endswith("FileItResultOut")
    assert "ErrorBody" in schema["components"]["schemas"]


runner = CliRunner()


def test_openapi_command_outputs_json(app_paths):
    r = runner.invoke(cli_main.app, ["--data-dir", str(app_paths.data_dir), "openapi"])
    assert r.exit_code == 0, r.output
    schema = json.loads(r.stdout)
    assert "/api/status" in schema["paths"]


def test_openapi_command_needs_no_archive(tmp_path, monkeypatch):
    monkeypatch.setenv("DAM_DATA_DIR", str(tmp_path / "fresh"))
    r = runner.invoke(cli_main.app, ["openapi"])
    assert r.exit_code == 0, r.output
    assert "/api/inbox" in json.loads(r.stdout)["paths"]


def test_start_background_and_stop(app, fake_archive):
    fake_archive.add(f"{INBOX}/a.txt", content=b"hello", drive_id="bg-1")
    bg = start_background(app)
    deadline = time.monotonic() + 10
    while app.repo.get("bg-1") is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert app.repo.get("bg-1") is not None  # the initial scan ran in the background
    # The scan wakes the idle indexer: indexed well before IDLE_WAIT_S (30 s).
    while app.repo.get("bg-1").index_state == "pending" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert app.repo.get("bg-1").index_state == "indexed"
    bg.stop()
    assert not any(t.is_alive() for t in bg.threads)
    assert app.content.run_once() == 0  # the indexer is closed
    bg.stop()  # idempotent


def test_watcher_change_wakes_indexer(app, fake_archive):
    bg = start_background(app)
    try:
        bg.scan_thread.join(10)
        time.sleep(0.2)  # the indexer is now idle (nothing pending)
        fake_archive.add(f"{INBOX}/late.txt", content=b"late", drive_id="late-1")
        bg.watcher._note(str(fake_archive.root / INBOX / "late.txt"))
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            rec = app.repo.get("late-1")
            if rec is not None and rec.index_state == "indexed":
                break
            time.sleep(0.05)
        assert rec is not None and rec.index_state == "indexed"
    finally:
        bg.stop()


def _scan_threads():
    return [t for t in threading.enumerate() if t.name == "dam-initial-scan" and t.is_alive()]


def test_start_background_failure_stops_started_threads(app, monkeypatch):
    from dam.index.watcher import Watcher

    def broken(self):
        raise OSError("no fsevents")

    monkeypatch.setattr(Watcher, "start", broken)
    with pytest.raises(OSError, match="no fsevents"):
        start_background(app)
    assert _scan_threads() == []
    assert app.content.run_once() == 0  # the indexer was closed too


class FakeServer:
    """Stands in for DamServer: reports started, then waits for the background to start."""

    events: list
    fail_with: BaseException | None = None
    start_up = True

    def __init__(self, config):
        self.events.append(("config", config.host, config.port))
        self.started = False
        self.events.append(("graceful", config.timeout_graceful_shutdown))

    def run(self):
        if self.start_up:
            self.started = True
            deadline = time.monotonic() + 5
            while "start" not in self.events and time.monotonic() < deadline:
                time.sleep(0.01)
        self.events.append("run")
        if self.fail_with is not None:
            raise self.fail_with


@pytest.fixture
def fake_serve(monkeypatch):
    import dam.serve as serve_mod
    from dam.app import App

    events: list = []

    class Background:
        def stop(self):
            events.append("stop")

    class Server(FakeServer):
        pass

    Server.events = events
    monkeypatch.setattr(
        serve_mod, "start_background", lambda a: events.append("start") or Background()
    )
    monkeypatch.setattr(serve_mod, "DamServer", Server)
    monkeypatch.setattr(serve_mod.webbrowser, "open", lambda url: events.append(("open", url)))
    real_close = App.close
    monkeypatch.setattr(App, "close", lambda self: events.append("close") or real_close(self))
    return events, Server


def serve_cmd(app_paths, *args):
    return runner.invoke(cli_main.app, ["--data-dir", str(app_paths.data_dir), "serve", *args])


def test_serve_command_wires_lifecycle(app_paths, fake_serve):
    events, _ = fake_serve
    r = serve_cmd(app_paths, "--port", "9123", "--no-open")
    assert r.exit_code == 0, r.output
    assert events == [
        ("config", "127.0.0.1", 9123),
        ("graceful", 10),
        "start",
        "run",
        "stop",
        "close",
    ]
    assert "stopped" in r.stderr


def test_serve_opens_browser_after_start(app_paths, fake_serve, tmp_path, monkeypatch):
    import dam.serve as serve_mod

    built = tmp_path / "dist"
    built.mkdir()
    (built / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(serve_mod, "STATIC_DIR", built)
    events, _ = fake_serve
    assert serve_cmd(app_paths, "--port", "9124").exit_code == 0
    assert events.index("start") < events.index(("open", "http://127.0.0.1:9124/"))


def test_serve_without_built_frontend_warns_and_does_not_open_browser(
    app_paths, fake_serve, tmp_path, monkeypatch
):
    import dam.serve as serve_mod

    monkeypatch.setattr(serve_mod, "STATIC_DIR", tmp_path / "no-dist")
    events, _ = fake_serve
    r = serve_cmd(app_paths, "--port", "9125")
    assert r.exit_code == 0, r.output
    assert "frontend not built — run `cd frontend && npm ci && npm run build`" in r.stderr
    assert "start" in events  # the API is still served
    assert not any(isinstance(e, tuple) and e[0] == "open" for e in events)


def test_serve_run_failure_still_stops_and_closes(app_paths, fake_serve):
    events, server = fake_serve
    server.fail_with = RuntimeError("boom")
    r = serve_cmd(app_paths, "--no-open")
    assert r.exit_code == 3 and "boom" in r.stderr
    assert events[-2:] == ["stop", "close"]


def test_failed_bind_starts_no_background_work(app_paths, fake_serve):
    events, server = fake_serve
    server.start_up = False
    server.fail_with = SystemExit(1)  # what uvicorn does when it cannot bind
    r = serve_cmd(app_paths, "--no-open")
    assert r.exit_code == 1
    assert "start" not in events and "stop" not in events and events[-1] == "close"


def test_serve_warns_about_pending_recovery(app_paths, fake_serve, monkeypatch):
    from dam.services.activity import ActivityService

    monkeypatch.setattr(ActivityService, "pending", lambda self: ["x"])
    r = serve_cmd(app_paths, "--no-open")
    assert r.exit_code == 0 and "dam recover" in r.stderr


def _free_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows cannot send SIGINT/SIGTERM to another process (SIGTERM kills it outright)",
)
@pytest.mark.parametrize("sig", ["SIGTERM", "SIGINT"])
def test_serve_shuts_down_cleanly_on_signal(app_paths, sig):
    """A real `dam serve` process: the signal ends it with exit 0 after a full shutdown."""
    import signal
    import subprocess
    import sys
    import urllib.request

    port = _free_port()
    cmd = [sys.executable, "-c", "from dam.cli.main import app; app()"]
    cmd += ["--data-dir", str(app_paths.data_dir), "serve", "--no-open", "--port", str(port)]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8"
    )
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=1):
                    break
            except OSError:
                assert proc.poll() is None, proc.communicate()
                assert time.monotonic() < deadline, "server did not start"
                time.sleep(0.1)
        proc.send_signal(getattr(signal, sig))
        out, err = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
    assert proc.returncode == 0, err
    assert "stopped" in err and "Aborted" not in err


def test_undo_endpoint_reports_follow_up_error(client, app, fake_archive, inbox_file, monkeypatch):
    from dam.trays.service import TrayService

    batch = post(client, "/api/inbox/file", {"requests": [req()], "dry_run": False}).json()

    def boom(self, batch_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(TrayService, "remove_created_by", boom)
    r = post(client, f"/api/activity/{batch['batch_id']}/undo")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None and body["follow_up_error"] == "RuntimeError: db down"
    assert (fake_archive.root / INBOX / "a.pdf").exists()
