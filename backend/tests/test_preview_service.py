"""Quick Look thumbnails (``qlmanage`` injected) and the text preview."""

import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, insert

from dam.api import create_api
from dam.api.routers.files import INDEXED_TEXT_MAX_CHARS
from dam.db.engine import write_tx
from dam.db.tables import file_text
from dam.services import preview

BASE = "http://127.0.0.1:8765"
BANKS = "10. Financial/Banks"
PNG = b"\x89PNG\r\n\x1a\nfake-image-data" + b"IEND\xaeB`\x82"


class FakeQl:
    """Stands in for qlmanage: writes ``<name>.png`` into the ``-o`` folder."""

    def __init__(self, output: bytes | None = PNG, hang: bool = False) -> None:
        self.calls: list[tuple[list[str], float]] = []
        self.output = output
        self.hang = hang

    def __call__(self, args: list[str], timeout: float) -> None:
        self.calls.append((args, timeout))
        if self.hang:
            raise subprocess.TimeoutExpired(args, timeout)
        out = Path(args[args.index("-o") + 1])
        if self.output is not None:
            (out / (Path(args[-1]).name + ".png")).write_bytes(self.output)


@pytest.fixture
def client(app):
    with TestClient(create_api(app), base_url=BASE) as c:
        yield c


@pytest.fixture
def ql(app):
    fake = FakeQl()
    app.previews.runner = fake
    app.previews.platform = "darwin"
    return fake


@pytest.fixture
def doc(app, fake_archive):
    fake_archive.add(f"{BANKS}/report.docx", content=b"PK word", drive_id="d1")
    app.scan()
    return "d1"


def test_thumbnail_rendered_with_qlmanage(app, client, ql, doc, fake_archive):
    r = client.get(f"/api/files/{doc}/thumb.png", params={"width": 800})
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content == PNG
    ((args, timeout),) = ql.calls
    assert args[:4] == ["/usr/bin/qlmanage", "-t", "-s", "1200"]  # 800 -> the 1200 step
    assert args[4] == "-o"
    out_dir = Path(args[5])
    assert out_dir.is_relative_to(app.app_paths.cache_dir)
    assert not out_dir.is_relative_to(fake_archive.root)
    assert args[6] == str((fake_archive.root / BANKS / "report.docx").resolve())
    assert timeout == 20


def test_thumbnail_cached(app, client, ql, doc):
    assert client.get(f"/api/files/{doc}/thumb.png").content == PNG
    assert client.get(f"/api/files/{doc}/thumb.png").content == PNG
    assert len(ql.calls) == 1
    assert ql.calls[0][0][3] == "1200"  # the default width
    # a width within the same step is the same cache entry
    assert client.get(f"/api/files/{doc}/thumb.png", params={"width": 700}).status_code == 200
    assert len(ql.calls) == 1
    # another step is another cache entry
    assert client.get(f"/api/files/{doc}/thumb.png", params={"width": 300}).status_code == 200
    assert len(ql.calls) == 2
    assert ql.calls[1][0][3] == "600"
    client.get(f"/api/files/{doc}/thumb.png", params={"width": 1201})
    assert ql.calls[2][0][3] == "2000"
    assert sorted(
        p.name.rsplit("_", 1)[1] for p in (app.app_paths.cache_dir / "thumbs").iterdir()
    ) == [
        "1200",
        "2000",
        "600",
    ]


def test_thumbnail_cache_key_follows_content(app, client, ql, doc, fake_archive):
    client.get(f"/api/files/{doc}/thumb.png")
    path = fake_archive.root / BANKS / "report.docx"
    path.write_bytes(b"PK word, edited and longer")
    app.scan()
    client.get(f"/api/files/{doc}/thumb.png")
    assert len(ql.calls) == 2


def test_thumbnail_timeout(app, client, doc):
    hung = FakeQl(hang=True)
    app.previews.runner = hung
    app.previews.platform = "darwin"
    r = client.get(f"/api/files/{doc}/thumb.png")
    assert r.status_code == 404
    assert r.json() == {"error": "no preview"}
    assert hung.calls[0][1] == 20


@pytest.mark.skipif(sys.platform == "win32", reason="runs /bin/sleep, which Windows lacks")
def test_real_runner_enforces_the_timeout():
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        preview.run_qlmanage(["/bin/sleep", "5"], 0.2)
    assert time.monotonic() - started < 3


def test_thumbnail_no_output_is_no_preview(app, client, doc):
    app.previews.runner = FakeQl(output=None)
    app.previews.platform = "darwin"
    r = client.get(f"/api/files/{doc}/thumb.png")
    assert r.status_code == 404
    assert r.json() == {"error": "no preview"}


def test_thumbnail_partial_output_is_no_preview(app, client, doc):
    app.previews.runner = FakeQl(output=b"\x89PNG half")
    app.previews.platform = "darwin"
    assert client.get(f"/api/files/{doc}/thumb.png").status_code == 404


def test_thumbnail_not_on_other_platforms(app, client, ql, doc):
    app.previews.platform = "linux"
    r = client.get(f"/api/files/{doc}/thumb.png")
    assert r.status_code == 404
    assert r.json() == {"error": "no preview"}
    assert ql.calls == []


def test_thumbnail_width_bounds(app, client, ql, doc):
    assert client.get(f"/api/files/{doc}/thumb.png", params={"width": 299}).status_code == 422
    assert client.get(f"/api/files/{doc}/thumb.png", params={"width": 2001}).status_code == 422
    assert ql.calls == []


def test_thumbnail_refuses_outside_archive(app, client, ql, fake_archive, tmp_path):
    secret = tmp_path / "secret.pdf"
    secret.write_bytes(b"x")
    fake_archive.add(f"{BANKS}/s.pdf", drive_id="s1")
    app.scan()
    target = fake_archive.root / BANKS / "s.pdf"
    target.unlink()
    target.symlink_to(secret)
    assert client.get("/api/files/s1/thumb.png").status_code == 404
    assert ql.calls == []


def test_text_preview_truncates(app, client, fake_archive):
    body = ("äö" * 60_000).encode("utf-8")  # 240 000 bytes, two-byte characters
    fake_archive.add(f"{BANKS}/notes.txt", content=body, drive_id="t1")
    fake_archive.add(f"{BANKS}/short.md", content=b"# hi\n\xff bad byte", drive_id="t2")
    app.scan()
    r = client.get("/api/files/t1/text")
    assert r.status_code == 200
    data = r.json()
    assert data["truncated"] is True
    assert len(data["text"].encode("utf-8")) <= 200 * 1024
    assert "�" not in data["text"]  # a character cut in half is dropped, not mangled
    assert data["text"].startswith("äöäö")
    r = client.get("/api/files/t1/text", params={"max": 10})
    assert r.json() == {"text": "äöäöä", "truncated": True}
    r = client.get("/api/files/t2/text")
    assert r.json() == {"text": "# hi\n� bad byte", "truncated": False}
    assert client.get("/api/files/t1/text", params={"max": 200 * 1024 + 1}).status_code == 422


def test_text_preview_only_text_like(app, client, fake_archive):
    fake_archive.add(f"{BANKS}/s.pdf", drive_id="p1")
    app.scan()
    assert client.get("/api/files/p1/text").status_code == 404


def test_thumbnail_slot_wait_times_out_without_recording(app, client, ql, doc):
    app.previews.wait_s = 0.05
    taken = [preview.THUMB_SEMAPHORE.acquire(timeout=1) for _ in range(2)]
    try:
        r = client.get(f"/api/files/{doc}/thumb.png")
    finally:
        for got in taken:
            if got:
                preview.THUMB_SEMAPHORE.release()
    assert r.status_code == 404 and r.json() == {"error": "no preview"}
    assert ql.calls == [] and app.previews._failed == {}
    # a slot is free again: it renders (the busy wait was not a failure of this file)
    assert client.get(f"/api/files/{doc}/thumb.png").status_code == 200


def test_expired_failures_are_pruned(app, client, doc, fake_archive, monkeypatch):
    app.previews.runner = FakeQl(output=None)
    app.previews.platform = "darwin"
    clock = [1000.0]
    monkeypatch.setattr(preview.time, "monotonic", lambda: clock[0])
    assert client.get(f"/api/files/{doc}/thumb.png").status_code == 404
    assert len(app.previews._failed) == 1
    clock[0] += preview.FAILED_TTL_S + 1
    fake_archive.add(f"{BANKS}/other.docx", content=b"PK", drive_id="d2")
    app.scan()
    assert client.get("/api/files/d2/thumb.png").status_code == 404
    assert len(app.previews._failed) == 1  # the expired entry went on insert
    assert next(iter(app.previews._failed)).startswith("d2_")


class BlockingQl(FakeQl):
    """Holds each render until ``release`` is set; ``started`` counts renders begun."""

    def __init__(self) -> None:
        super().__init__()
        import threading

        self.release = threading.Event()
        self.started = threading.Semaphore(0)

    def __call__(self, args: list[str], timeout: float) -> None:
        self.started.release()
        assert self.release.wait(10)
        super().__call__(args, timeout)


def test_thumbnail_busy_answers_503(app, client, fake_archive, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from dam.api.routers import files as files_router

    monkeypatch.setattr(files_router, "THUMB_ACQUIRE_S", 0.2)
    for i in range(3):
        fake_archive.add(f"{BANKS}/doc {i}.docx", content=f"PK {i}".encode(), drive_id=f"b{i}")
    app.scan()
    slow = BlockingQl()
    app.previews.runner = slow
    app.previews.platform = "darwin"
    with ThreadPoolExecutor(2) as pool:
        held = [pool.submit(client.get, f"/api/files/b{i}/thumb.png") for i in range(2)]
        for _ in range(2):
            assert slow.started.acquire(timeout=5)  # both slots are rendering
        r = client.get("/api/files/b2/thumb.png")
        assert r.status_code == 503
        assert r.json() == {"error": "busy"}
        slow.release.set()
        assert [f.result().status_code for f in held] == [200, 200]
    assert len(slow.calls) == 2  # the busy request rendered nothing
    # with the slots free again it renders
    assert client.get("/api/files/b2/thumb.png").status_code == 200


def test_thumbnail_not_rendered_for_a_disconnected_request(app, ql, doc):
    import asyncio

    api = create_api(app)
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": f"/api/files/{doc}/thumb.png",
        "raw_path": f"/api/files/{doc}/thumb.png".encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"127.0.0.1:8765")],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8765),
        "state": {},
    }
    asyncio.run(api(scope, receive, send))
    assert ql.calls == []  # never handed to Quick Look
    assert sent and sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] != 200


def test_thumb_route_documents_503(app):
    op = create_api(app).openapi()["paths"]["/api/files/{drive_id}/thumb.png"]["get"]
    assert "503" in op["responses"]


def _index_text(app, drive_id: str, body: str, ocr_used: bool = False) -> None:
    with write_tx(app.engine) as conn:
        conn.execute(delete(file_text).where(file_text.c.drive_id == drive_id))
        conn.execute(insert(file_text), {"drive_id": drive_id, "text": body, "ocr_used": ocr_used})


def test_indexed_text_is_what_was_read(app, client, doc):
    _index_text(app, doc, "Kela päätös 2026")
    r = client.get(f"/api/files/{doc}/indexed-text")
    assert r.status_code == 200
    assert r.json() == {"text": "Kela päätös 2026", "truncated": False, "ocr_used": False}


def test_indexed_text_says_when_it_came_from_ocr(app, client, doc):
    _index_text(app, doc, "scanned words", ocr_used=True)
    assert client.get(f"/api/files/{doc}/indexed-text").json()["ocr_used"] is True


def test_indexed_text_is_empty_when_none_was_read(client, doc):
    r = client.get(f"/api/files/{doc}/indexed-text")
    assert r.status_code == 200
    assert r.json() == {"text": "", "truncated": False, "ocr_used": False}


def test_indexed_text_is_capped(app, client, doc):
    _index_text(app, doc, "ä" * (INDEXED_TEXT_MAX_CHARS + 1))
    data = client.get(f"/api/files/{doc}/indexed-text").json()
    assert data["truncated"] is True
    assert len(data["text"]) == INDEXED_TEXT_MAX_CHARS


def test_indexed_text_of_an_unknown_file_is_404(client):
    assert client.get("/api/files/nope/indexed-text").status_code == 404
