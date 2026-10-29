"""Index errors: the stored reason, the unsupported classification, list and retry."""

import pypdfium2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from typer.testing import CliRunner

from dam.api import create_api
from dam.cli.main import app as cli
from dam.db.tables import files
from dam.extract.base import ExtractedText
from dam.extract.pdf import PdfExtractor

BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}
BANKS = "10. Financial/Banks"


class Exploding:
    name = "boom"

    def supports(self, path):
        return path.suffix == ".boom"

    def extract(self, path, data=None) -> ExtractedText:
        raise ValueError("the parser fell over")


@pytest.fixture
def client(app):
    with TestClient(create_api(app), base_url=BASE) as c:
        yield c


def state_of(app, drive_id):
    with app.engine.connect() as conn:
        row = conn.execute(
            select(files.c.index_state, files.c.last_error, files.c.attempts).where(
                files.c.drive_id == drive_id
            )
        ).one()
    return row.index_state, row.last_error, row.attempts


def test_failing_extractor_stores_its_reason(app, fake_archive):
    app.registry._extractors.insert(0, Exploding())
    fake_archive.add(f"{BANKS}/x.boom", drive_id="b1")
    app.scan()
    app.index()
    state, reason, _ = state_of(app, "b1")
    assert state == "error"
    assert reason == "ValueError: the parser fell over"


def test_dam_index_skips_a_file_whose_read_stopped_dam(app, fake_archive):
    from dam.index.content import READING_STOPPED

    fake_archive.add(f"{BANKS}/x.txt", content=b"hello", drive_id="t1")
    app.scan()
    app.repo.mark_reading("t1")  # left over from a run that was killed mid-read
    assert app.index() == 0
    assert state_of(app, "t1")[:2] == ("error", READING_STOPPED)
    assert app.retry_index(["t1"]) == 1
    assert app.index() == 1
    assert state_of(app, "t1")[:2] == ("indexed", None)


def test_badzip_is_unsupported_with_reason(app, fake_archive):
    fake_archive.add(f"{BANKS}/letter.docx", content=b"not a zip at all", drive_id="w1")
    app.scan()
    app.index()
    assert state_of(app, "w1")[:2] == ("unsupported", "not a valid Word file")


def test_password_pdf_is_unsupported_with_reason(app, fake_archive, monkeypatch):
    def locked(*a, **kw):
        raise pypdfium2.PdfiumError(
            "Failed to load document (PDFium: Incorrect password error).",
            err_code=pypdfium2.raw.FPDF_ERR_PASSWORD,
        )

    monkeypatch.setattr(pypdfium2, "PdfDocument", locked)
    fake_archive.add(f"{BANKS}/locked.pdf", content=b"%PDF-1.7 ...", drive_id="p1")
    app.scan()
    app.index()
    assert state_of(app, "p1")[:2] == ("unsupported", "password-protected PDF")


def test_other_pdfium_failures_keep_their_message(monkeypatch, tmp_path):
    def broken(*a, **kw):
        raise pypdfium2.PdfiumError("Failed to load document (PDFium: Data format error).", 3)

    monkeypatch.setattr(pypdfium2, "PdfDocument", broken)
    with pytest.raises(Exception, match="cannot open PDF: Failed to load"):
        PdfExtractor(["en-US"]).extract(tmp_path / "x.pdf", b"%PDF")


def test_errors_list_and_retry(app, client, fake_archive):
    app.registry._extractors.insert(0, Exploding())
    fake_archive.add(f"{BANKS}/x.boom", drive_id="b1")
    fake_archive.add(f"{BANKS}/letter.docx", content=b"nope", drive_id="w1")
    fake_archive.add(f"{BANKS}/fine.txt", content=b"hello", drive_id="t1")
    app.scan()
    app.index()

    body = client.get("/api/index/errors").json()
    assert body["total"] == 1
    rows = body["rows"]
    assert rows == [
        {
            "drive_id": "b1",
            "path": f"{BANKS}/x.boom",
            "name": "x.boom",
            "state": "error",
            "reason": "ValueError: the parser fell over",
            "retry_at": None,
        }
    ]
    every = client.get("/api/index/errors", params={"all": 1}).json()["rows"]
    assert {(r["drive_id"], r["state"], r["reason"]) for r in every} == {
        ("b1", "error", "ValueError: the parser fell over"),
        ("w1", "unsupported", "not a valid Word file"),
    }

    woken = []
    app.wake_indexer = lambda: woken.append(True)
    # an indexed file and an unknown id are not re-queued
    r = client.post(
        "/api/index/retry", json={"drive_ids": ["b1", "w1", "t1", "nope"]}, headers=LOCAL_ORIGIN
    )
    assert r.status_code == 200
    assert r.json() == {"queued": 2}
    assert woken == [True]
    assert state_of(app, "b1") == ("pending", None, 0)
    assert state_of(app, "w1") == ("pending", None, 0)
    assert state_of(app, "t1")[0] == "indexed"
    assert client.get("/api/index/errors", params={"all": 1}).json() == {
        "rows": [],
        "total": 0,
        "unsupported_by_type": [],
    }


def test_errors_newest_first(app, client, fake_archive):
    import os

    app.registry._extractors.insert(0, Exploding())
    old = fake_archive.add(f"{BANKS}/old.boom", drive_id="o1")
    fake_archive.add(f"{BANKS}/new.boom", drive_id="n1")
    os.utime(old, (1_000_000, 1_000_000))
    app.scan()
    app.index()
    rows = client.get("/api/index/errors").json()["rows"]
    assert [r["drive_id"] for r in rows] == ["n1", "o1"]


def test_cli_errors_and_retry(app, app_paths, fake_archive):
    app.registry._extractors.insert(0, Exploding())
    fake_archive.add(f"{BANKS}/letter.docx", content=b"nope", drive_id="w1")
    app.scan()
    app.index()
    run = CliRunner()
    prefix = ["--data-dir", str(app_paths.data_dir)]
    out = run.invoke(cli, [*prefix, "errors"])
    assert out.exit_code == 0, out.output
    assert "no index errors" in out.output
    out = run.invoke(cli, [*prefix, "errors", "--all"])
    assert out.exit_code == 0, out.output
    assert "letter.docx" in out.output and "not a valid Word file" in out.output
    assert "TRIES" not in out.output and "ATTEMPTS" not in out.output
    # --retry queues error rows only, even with --all
    out = run.invoke(cli, [*prefix, "errors", "--all", "--retry"])
    assert out.exit_code == 0, out.output
    assert "queued 0 file(s)" in out.output
    assert state_of(app, "w1")[0] == "unsupported"
    out = run.invoke(cli, [*prefix, "errors", "--retry-unsupported"])
    assert out.exit_code == 0, out.output
    assert "letter.docx" in out.output
    assert "queued 1 file(s)" in out.output
    assert state_of(app, "w1")[0] == "pending"


def test_cli_retry_queues_errors_not_unsupported(app, app_paths, fake_archive):
    app.registry._extractors.insert(0, Exploding())
    fake_archive.add(f"{BANKS}/x.boom", drive_id="b1")
    fake_archive.add(f"{BANKS}/letter.docx", content=b"nope", drive_id="w1")
    app.scan()
    app.index()
    run = CliRunner()
    prefix = ["--data-dir", str(app_paths.data_dir)]
    out = run.invoke(cli, [*prefix, "errors", "--all", "--retry"])
    assert out.exit_code == 0, out.output
    assert "queued 1 file(s)" in out.output
    assert state_of(app, "b1")[0] == "pending"
    assert state_of(app, "w1")[0] == "unsupported"


def mark(app, state: str, drive_ids: list[str], **values) -> None:
    from sqlalchemy import update

    with app.engine.begin() as conn:
        conn.execute(
            update(files).where(files.c.drive_id.in_(drive_ids)).values(index_state=state, **values)
        )


def test_errors_list_is_limited_with_total_and_type_summary(app, client, fake_archive):
    ids = []
    for i in range(5):
        fake_archive.add(f"{BANKS}/photo {i}.heic", drive_id=f"h{i}")
        ids.append(f"h{i}")
    for i in range(3):
        fake_archive.add(f"{BANKS}/clip {i}.MOV", drive_id=f"m{i}")
        ids.append(f"m{i}")
    fake_archive.add(f"{BANKS}/README", drive_id="r0")
    ids.append("r0")
    fake_archive.add(f"{BANKS}/broken.pdf", drive_id="e0")
    app.scan()
    mark(app, "unsupported", ids)
    mark(app, "error", ["e0"], last_error="boom")

    body = client.get("/api/index/errors", params={"all": 1, "limit": 4}).json()
    assert len(body["rows"]) == 4
    assert body["total"] == 10
    assert body["unsupported_by_type"] == [
        {"ext": "heic", "count": 5},
        {"ext": "mov", "count": 3},
        {"ext": None, "count": 1},
    ]
    # the default limit is 200
    body = client.get("/api/index/errors", params={"all": 1}).json()
    assert len(body["rows"]) == 10
    # errors only: same shape, limited too; no unsupported summary
    body = client.get("/api/index/errors", params={"limit": 1}).json()
    assert body == {
        "rows": [
            {
                "drive_id": "e0",
                "path": f"{BANKS}/broken.pdf",
                "name": "broken.pdf",
                "state": "error",
                "reason": "boom",
                "retry_at": None,
            }
        ],
        "total": 1,
        "unsupported_by_type": [],
    }
    assert client.get("/api/index/errors", params={"limit": 0}).status_code == 422
    assert client.get("/api/index/errors", params={"limit": 1001}).status_code == 422


def test_default_errors_limit_is_200(app, client, fake_archive):
    for i in range(205):
        fake_archive.add(f"{BANKS}/f{i}.heic", drive_id=f"h{i}")
    app.scan()
    mark(app, "unsupported", [f"h{i}" for i in range(205)])
    body = client.get("/api/index/errors", params={"all": 1}).json()
    assert len(body["rows"]) == 200
    assert body["total"] == 205


def test_errors_list_leaves_out_links_like_counts(app, client, fake_archive):
    fake_archive.add(f"{BANKS}/real.heic", drive_id="h1")
    fake_archive.link(f"{BANKS}/alias.heic", f"{BANKS}/real.heic")
    app.scan()
    with app.engine.begin() as conn:
        conn.execute(files.update().values(index_state="unsupported"))
        n_links = conn.execute(
            select(func.count()).select_from(files).where(files.c.is_link.is_(True))
        ).scalar()
    assert n_links == 1
    body = client.get("/api/index/errors", params={"all": 1}).json()
    assert [r["drive_id"] for r in body["rows"]] == ["h1"]
    assert body["total"] == 1
    assert body["unsupported_by_type"] == [{"ext": "heic", "count": 1}]
    assert app.repo.counts()["unsupported"] == 1


def test_zip_that_is_not_word_and_encrypted_docx(app, fake_archive):
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "not a Word package")
    fake_archive.add(f"{BANKS}/zip.docx", content=buf.getvalue(), drive_id="z1")
    ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 504
    fake_archive.add(f"{BANKS}/secret.docx", content=ole, drive_id="e1")
    app.scan()
    app.index()
    assert state_of(app, "z1")[:2] == ("unsupported", "not a Word document")
    assert state_of(app, "e1")[:2] == ("unsupported", "password-protected Word file")


def test_index_summary_counts_types_and_pages(app, client, fake_archive):
    app.registry._extractors.insert(0, Exploding())
    fake_archive.add(f"{BANKS}/x.boom", drive_id="b1")
    fake_archive.add(f"{BANKS}/fine.txt", content=b"hello", drive_id="t1")
    for i in range(3):
        fake_archive.add(f"{BANKS}/a{i}.zip", content=b"PK", drive_id=f"z{i}")
    fake_archive.add(f"{BANKS}/letter.docx", content=b"nope", drive_id="w1")
    app.scan()
    app.index()

    body = client.get("/api/index/summary", params={"limit": 2}).json()
    assert {k: body[k] for k in ("searchable", "waiting", "not_readable", "errors", "missing")} == {
        "searchable": 1,
        "waiting": 0,
        "not_readable": 4,
        "errors": 1,
        "missing": 0,
    }
    assert body["not_readable_by_type"] == [
        {"ext": "zip", "count": 3},
        {"ext": "docx", "count": 1},
    ]
    # the identifiers pass will read the text of the searchable file (index() did not run it)
    assert (body["identifiers"]["read"], body["identifiers"]["total"]) == (0, 1)
    assert len(body["rows"]) == 2 and body["offset"] == 0
    assert all(r["state"] == "unsupported" for r in body["rows"])
    rest = client.get("/api/index/summary", params={"limit": 2, "offset": 2}).json()["rows"]
    assert len(rest) == 2
    ids = {r["drive_id"] for r in body["rows"]} | {r["drive_id"] for r in rest}
    assert ids == {"z0", "z1", "z2", "w1"}
