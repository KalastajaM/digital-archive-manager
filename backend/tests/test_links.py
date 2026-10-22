"""A link (symlink) in the archive previews, opens and shows in Finder as its target,
only when the target resolves to a regular file inside the archive root. Every launch
refusal applies to the target. Nothing launches: runners are injected."""

import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from dam.api import create_api
from pdfs import make_text_pdf
from test_preview_service import PNG, FakeQl

BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}
HOUSES = "##. Important/Houses/Hillside"
DEEDS = "20. Home/Deeds"


@pytest.fixture
def client(app):
    with TestClient(create_api(app), base_url=BASE) as c:
        yield c


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
def ql(app):
    fake = FakeQl()
    app.previews.runner = fake
    app.previews.platform = "darwin"
    return fake


def post(client, url):
    return client.post(url, json={}, headers=LOCAL_ORIGIN)


def link_id(app, rel: str) -> str:
    rec = app.repo.by_path(rel)
    assert rec is not None and rec.is_link
    return rec.drive_id


@pytest.fixture
def deed(app, fake_archive):
    """A PDF and a link to it, as under ``##. Important/Houses/Hillside``."""
    target = fake_archive.add(f"{DEEDS}/20010315_Kauppakirja_Hillside.pdf", drive_id="t1")
    make_text_pdf(target)
    fake_archive.link(
        f"{HOUSES}/20010315_Kauppakirja_Hillside.pdf", f"{DEEDS}/20010315_Kauppakirja_Hillside.pdf"
    )
    app.scan()
    return link_id(app, f"{HOUSES}/20010315_Kauppakirja_Hillside.pdf"), target


def test_detail_names_the_in_archive_target(client, deed):
    lid, _ = deed
    body = client.get(f"/api/files/{lid}").json()
    assert body["record"]["is_link"] is True
    assert body["link_target_id"] == "t1"
    assert body["link_target_path"] == f"{DEEDS}/20010315_Kauppakirja_Hillside.pdf"
    assert body["link_target_inside"] is True


def test_detail_of_a_plain_file_has_no_target(client, deed):
    body = client.get("/api/files/t1").json()
    assert body["link_target_id"] is None
    assert body["link_target_path"] is None
    assert body["link_target_inside"] is False


def test_page_png_follows_the_link(client, deed):
    lid, _ = deed
    r = client.get(f"/api/files/{lid}/page/1.png?w=400")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(r.content)).width == 400


def test_raw_follows_the_link(client, deed):
    lid, target = deed
    r = client.get(f"/api/files/{lid}/raw")
    assert r.status_code == 200
    assert r.content == target.read_bytes()
    assert r.headers["content-security-policy"] == "sandbox; default-src 'none'"


def test_thumbnail_follows_the_link(client, ql, deed):
    lid, target = deed
    r = client.get(f"/api/files/{lid}/thumb.png")
    assert r.status_code == 200 and r.content == PNG
    ((args, _),) = ql.calls
    assert args[-1] == str(target.resolve())
    # the cache entry is the target's: asking for the target itself renders nothing new
    assert client.get("/api/files/t1/thumb.png").status_code == 200
    assert len(ql.calls) == 1


def test_text_follows_the_link(app, client, fake_archive):
    fake_archive.add(f"{DEEDS}/notes.txt", content=b"hello from the target", drive_id="n1")
    fake_archive.link(f"{HOUSES}/notes.txt", f"{DEEDS}/notes.txt")
    app.scan()
    r = client.get(f"/api/files/{link_id(app, f'{HOUSES}/notes.txt')}/text")
    assert r.status_code == 200
    assert r.json() == {"text": "hello from the target", "truncated": False}


def test_text_follows_the_target_type_not_the_link_name(app, client, fake_archive):
    fake_archive.add(f"{DEEDS}/notes.txt", content=b"plain text", drive_id="n1")
    fake_archive.link(f"{HOUSES}/notes", f"{DEEDS}/notes.txt")
    app.scan()
    r = client.get(f"/api/files/{link_id(app, f'{HOUSES}/notes')}/text")
    assert r.status_code == 200 and r.json()["text"] == "plain text"


def test_open_and_reveal_follow_the_link(client, calls, deed):
    lid, target = deed
    assert post(client, f"/api/files/{lid}/open").status_code == 204
    assert post(client, f"/api/files/{lid}/reveal").status_code == 204
    real = str(target.resolve())
    assert calls == [["/usr/bin/open", real], ["/usr/bin/open", "-R", real]]


def test_a_chain_of_links_is_followed_to_its_end(app, client, calls, fake_archive):
    target = fake_archive.add(f"{DEEDS}/end.pdf", drive_id="e1")
    make_text_pdf(target)
    fake_archive.link(f"{DEEDS}/middle.pdf", f"{DEEDS}/end.pdf")
    fake_archive.link(f"{HOUSES}/start.pdf", f"{DEEDS}/middle.pdf")
    app.scan()
    lid = link_id(app, f"{HOUSES}/start.pdf")
    body = client.get(f"/api/files/{lid}").json()
    assert body["link_target_id"] == "e1" and body["link_target_inside"] is True
    assert client.get(f"/api/files/{lid}/page/1.png").status_code == 200
    assert post(client, f"/api/files/{lid}/open").status_code == 204
    assert calls == [["/usr/bin/open", str(target.resolve())]]


def _outside_link(app, fake_archive, tmp_path: Path) -> tuple[str, Path]:
    secret = tmp_path / "outside" / "secret.pdf"
    secret.parent.mkdir()
    make_text_pdf(secret)
    link = fake_archive.root / HOUSES / "secret.pdf"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(secret)
    app.scan()
    return link_id(app, f"{HOUSES}/secret.pdf"), link


def test_link_target_outside_archive_refused(app, client, calls, ql, fake_archive, tmp_path):
    lid, link = _outside_link(app, fake_archive, tmp_path)
    body = client.get(f"/api/files/{lid}").json()
    assert body["link_target_id"] is None
    assert body["link_target_inside"] is False
    assert body["link_target_path"] == str(tmp_path / "outside" / "secret.pdf")
    for url in ("raw", "page/1.png", "thumb.png", "text"):
        r = client.get(f"/api/files/{lid}/{url}")
        assert r.status_code == 404, url
    assert ql.calls == []
    r = post(client, f"/api/files/{lid}/open")
    assert r.status_code == 409
    assert r.json() == {
        "error": "Won't open a link to outside the archive or to nothing — use Show in Finder"
    }
    assert calls == []
    # Show in Finder shows the link itself, never the outside file
    assert post(client, f"/api/files/{lid}/reveal").status_code == 204
    assert calls == [["/usr/bin/open", "-R", str(link.parent.resolve() / link.name)]]


def test_chain_through_an_outside_link_is_refused(app, client, calls, fake_archive, tmp_path):
    secret = tmp_path / "outside.pdf"
    make_text_pdf(secret)
    (fake_archive.root / DEEDS).mkdir(parents=True)
    (fake_archive.root / DEEDS / "hop.pdf").symlink_to(secret)
    fake_archive.link(f"{HOUSES}/start.pdf", f"{DEEDS}/hop.pdf")
    app.scan()
    lid = link_id(app, f"{HOUSES}/start.pdf")
    assert client.get(f"/api/files/{lid}").json()["link_target_inside"] is False
    assert client.get(f"/api/files/{lid}/page/1.png").status_code == 404
    assert post(client, f"/api/files/{lid}/open").status_code == 409
    assert calls == []


def test_missing_target_is_no_preview_and_no_open(app, client, calls, ql, fake_archive):
    fake_archive.link(f"{HOUSES}/gone.pdf", f"{DEEDS}/gone.pdf")
    app.scan()
    lid = link_id(app, f"{HOUSES}/gone.pdf")
    body = client.get(f"/api/files/{lid}").json()
    assert body["link_target_id"] is None and body["link_target_inside"] is False
    for url in ("raw", "page/1.png", "thumb.png", "text"):
        assert client.get(f"/api/files/{lid}/{url}").status_code == 404, url
    assert post(client, f"/api/files/{lid}/open").status_code == 409
    assert ql.calls == [] and calls == []


def test_target_gone_since_the_scan_is_refused(app, client, calls, deed):
    lid, target = deed
    target.unlink()  # not rescanned: the index still has t1
    assert client.get(f"/api/files/{lid}/page/1.png").status_code == 404
    assert post(client, f"/api/files/{lid}/open").status_code == 409
    assert calls == []


def test_link_to_a_folder_does_not_preview_or_open(app, client, calls, ql, fake_archive):
    fake_archive.add(f"{DEEDS}/a.pdf", drive_id="a1")
    fake_archive.link(f"{HOUSES}/Deeds", DEEDS)
    app.scan()
    lid = link_id(app, f"{HOUSES}/Deeds")
    assert client.get(f"/api/files/{lid}/thumb.png").status_code == 404
    r = post(client, f"/api/files/{lid}/open")
    assert r.status_code == 409 and "folders" in r.json()["error"]
    assert ql.calls == [] and calls == []


@pytest.mark.parametrize("name", ["tool.sh", "Run.command", "x.webloc", "plain-binary"])
def test_executable_target_is_refused(app, client, calls, fake_archive, name):
    if name == "plain-binary" and sys.platform == "win32":
        pytest.skip("Windows has no executable permission bit")
    target = fake_archive.add(f"{DEEDS}/{name}", drive_id="x1")
    if name == "plain-binary":
        target.chmod(0o755)
    fake_archive.link(f"{HOUSES}/harmless.pdf", f"{DEEDS}/{name}")
    app.scan()
    r = post(client, f"/api/files/{link_id(app, f'{HOUSES}/harmless.pdf')}/open")
    assert r.status_code == 409
    assert r.json() == {"error": "Won't open apps or scripts from the archive — use Show in Finder"}
    assert calls == []


def test_target_inside_a_bundle_is_refused(app, client, calls, fake_archive):
    fake_archive.add(f"{DEEDS}/Thing.app/Contents/readme.txt", drive_id="in1")
    fake_archive.link(f"{HOUSES}/readme.txt", f"{DEEDS}/Thing.app/Contents/readme.txt")
    app.scan()
    r = post(client, f"/api/files/{link_id(app, f'{HOUSES}/readme.txt')}/open")
    assert r.status_code == 409 and "apps or scripts" in r.json()["error"]
    assert calls == []


def _case_insensitive(root: Path) -> bool:
    return (root / "##. ONGOING").exists()


def test_case_only_mismatch_finds_the_target(app, client, calls, fake_archive):
    if not _case_insensitive(fake_archive.root):
        pytest.skip("needs a case-insensitive file system")
    target = fake_archive.add(f"{DEEDS}/Kauppakirja.pdf", drive_id="t1")
    make_text_pdf(target)
    link = fake_archive.root / HOUSES / "deed.pdf"
    link.parent.mkdir(parents=True)
    link.symlink_to(fake_archive.root / "20. HOME" / "deeds" / "KAUPPAKIRJA.pdf")
    app.scan()
    lid = link_id(app, f"{HOUSES}/deed.pdf")
    body = client.get(f"/api/files/{lid}").json()
    assert body["link_target_id"] == "t1" and body["link_target_inside"] is True
    assert body["link_target_path"] == f"{DEEDS}/Kauppakirja.pdf"
    assert client.get(f"/api/files/{lid}/page/1.png").status_code == 200
    assert post(client, f"/api/files/{lid}/open").status_code == 204
    assert calls == [["/usr/bin/open", str(target.resolve())]]


def test_root_spelled_in_another_case_is_still_inside(app, client, fake_archive):
    if not _case_insensitive(fake_archive.root):
        pytest.skip("needs a case-insensitive file system")
    target = fake_archive.add(f"{DEEDS}/a.pdf", drive_id="t1")
    make_text_pdf(target)
    root = fake_archive.root
    other_root = root.parent / root.name.upper()  # the archive root itself, other spelling
    link = root / HOUSES / "a.pdf"
    link.parent.mkdir(parents=True)
    link.symlink_to(other_root / DEEDS / "a.pdf")
    app.scan()
    lid = link_id(app, f"{HOUSES}/a.pdf")
    assert client.get(f"/api/files/{lid}").json()["link_target_id"] == "t1"
    assert client.get(f"/api/files/{lid}/page/1.png").status_code == 200


def test_case_lookup_needs_the_same_file(app, fake_archive, monkeypatch):
    """A folded match is only accepted when it is the same file on disk (samestat)."""
    if sys.platform == "win32":
        pytest.skip("resolve() gives the on-disk spelling: no folded fallback is reached")
    if not _case_insensitive(fake_archive.root):
        pytest.skip("needs a case-insensitive file system")
    fake_archive.add(f"{DEEDS}/a.pdf", drive_id="t1")
    link = fake_archive.root / HOUSES / "a.pdf"
    link.parent.mkdir(parents=True)
    link.symlink_to(fake_archive.root / DEEDS / "A.PDF")
    app.scan()
    from dam.services import links

    rec = app.repo.by_path(f"{HOUSES}/a.pdf")
    assert links.link_target(app.paths, app.repo, rec).drive_id == "t1"
    monkeypatch.setattr(links.os.path, "samestat", lambda a, b: False)
    assert links.link_target(app.paths, app.repo, rec) is None


def test_link_named_like_a_launcher_is_refused(app, client, calls, fake_archive):
    target = fake_archive.add(f"{DEEDS}/deed.pdf", drive_id="t1")
    make_text_pdf(target)
    fake_archive.link(f"{HOUSES}/x.webloc", f"{DEEDS}/deed.pdf")
    app.scan()
    r = post(client, f"/api/files/{link_id(app, f'{HOUSES}/x.webloc')}/open")
    assert r.status_code == 409
    assert r.json() == {"error": "Won't open apps or scripts from the archive — use Show in Finder"}
    assert calls == []


def test_a_loop_of_links_has_no_target(app, client, calls, ql, fake_archive):
    fake_archive.link(f"{HOUSES}/a.pdf", f"{HOUSES}/b.pdf")
    fake_archive.link(f"{HOUSES}/b.pdf", f"{HOUSES}/a.pdf")
    app.scan()
    lid = link_id(app, f"{HOUSES}/a.pdf")
    assert client.get(f"/api/files/{lid}").json()["link_target_inside"] is False
    for url in ("raw", "page/1.png", "thumb.png", "text"):
        assert client.get(f"/api/files/{lid}/{url}").status_code == 404, url
    assert post(client, f"/api/files/{lid}/open").status_code == 409
    assert ql.calls == [] and calls == []


def test_no_target_wording(app, client, fake_archive):
    fake_archive.link(f"{HOUSES}/gone.pdf", f"{DEEDS}/gone.pdf")
    app.scan()
    r = client.get(f"/api/files/{link_id(app, f'{HOUSES}/gone.pdf')}/raw")
    assert r.json() == {"error": "No preview (the link points outside the archive or to nothing)"}
