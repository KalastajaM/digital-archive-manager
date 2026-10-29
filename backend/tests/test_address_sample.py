"""Settings > Reading documents: page 1 of a sample letter, read from a file that is never
added to the archive (``POST /api/settings/address-area/sample``)."""

import base64
import io

from PIL import Image

from dam.extract import ocr
from pdfs import make_layout_pdf, make_scan_pdf
from test_api import LOCAL_ORIGIN, make_client

URL = "/api/settings/address-area/sample"
RAW = {**LOCAL_ORIGIN, "Content-Type": "application/octet-stream"}


def _png_of(image_url: str) -> Image.Image:
    head, data = image_url.split(",", 1)
    assert head == "data:image/png;base64"
    return Image.open(io.BytesIO(base64.b64decode(data)))


def _letter(tmp_path) -> bytes:
    path = make_layout_pdf(
        tmp_path / "letter.pdf", [(60, 680, "Anna Example"), (60, 664, "Main Street 1")]
    )
    return path.read_bytes()


def test_a_pdf_gives_page_1_and_its_lines(app, app_paths, tmp_path):
    with make_client(app) as c:
        r = c.post(f"{URL}?name=letter.pdf", content=_letter(tmp_path), headers=RAW)
    assert r.status_code == 200, r.text
    got = r.json()
    img = _png_of(got["image"])
    assert img.width == 900 and abs(img.height / img.width - 792 / 612) < 0.01
    assert got["read"] is True and got["unavailable"] is None
    texts = [ln["text"] for ln in got["lines"]]
    assert texts == ["Anna Example", "Main Street 1"]
    first = got["lines"][0]
    assert 0.09 < first["box"][0] < 0.11 and 0.1 < first["box"][1] < 0.16
    assert [w["text"] for w in first["words"]] == ["Anna", "Example"]
    # nothing kept: not in the archive, not in the index, not in the cache
    assert not any((app_paths.cache_dir / "uploads").iterdir())
    assert app.repo.count_live() == 0


def test_an_image_is_shown_upright_and_read_when_there_is_ocr(app, tmp_path, monkeypatch):
    buf = io.BytesIO()
    Image.new("RGB", (2000, 1000), "white").save(buf, "PNG")
    monkeypatch.setattr(ocr, "engine", lambda: None)
    with make_client(app) as c:
        r = c.post(f"{URL}?name=Scan.PNG", content=buf.getvalue(), headers=RAW)
    assert r.status_code == 200, r.text
    got = r.json()
    assert _png_of(got["image"]).size == (900, 450)
    assert got["read"] is False and got["lines"] == []
    assert got["unavailable"] == ocr.NO_OCR


def test_a_scan_without_ocr_says_so(app, tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "engine", lambda: None)
    scan = make_scan_pdf(tmp_path / "scan.pdf").read_bytes()
    with make_client(app) as c:
        r = c.post(f"{URL}?name=scan.pdf", content=scan, headers=RAW)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["read"] is False and got["lines"] == []
    assert "no OCR engine" in got["unavailable"]


def test_a_small_image_is_not_blown_up(app, tmp_path, monkeypatch):
    buf = io.BytesIO()
    Image.new("L", (300, 400), 255).save(buf, "JPEG")
    monkeypatch.setattr(ocr, "engine", lambda: None)
    with make_client(app) as c:
        r = c.post(f"{URL}?name=small.jpg", content=buf.getvalue(), headers=RAW)
    assert r.status_code == 200, r.text
    assert _png_of(r.json()["image"]).size == (300, 400)


def test_refusals(app, app_paths, tmp_path, monkeypatch):
    with make_client(app) as c:
        kind = c.post(f"{URL}?name=notes.docx", content=b"PK..", headers=RAW)
        assert kind.status_code == 400 and "PDF" in kind.json()["error"]
        assert c.post(f"{URL}?name=a.pdf", content=b"", headers=RAW).status_code == 400
        broken = c.post(f"{URL}?name=a.pdf", content=b"%PDF-1.4 not really", headers=RAW)
        assert broken.status_code == 400 and "page 1" in broken.json()["error"]
        bad_image = c.post(f"{URL}?name=a.png", content=b"not a picture", headers=RAW)
        assert bad_image.status_code == 400
        monkeypatch.setattr("dam.api.routers.settings.SAMPLE_MAX_BYTES", 10)
        big = c.post(f"{URL}?name=big.pdf", content=b"x" * 11, headers=RAW)
        assert big.status_code == 413
        # local only, like the other uploads
        no_origin = c.post(
            f"{URL}?name=a.pdf",
            content=b"x",
            headers={"Content-Type": "application/octet-stream"},
        )
        assert no_origin.status_code == 403
        form = c.post(
            f"{URL}?name=a.pdf",
            content=b"x",
            headers={**LOCAL_ORIGIN, "Content-Type": "multipart/form-data; boundary=x"},
        )
        assert form.status_code == 415
    assert not any((app_paths.cache_dir / "uploads").iterdir())
