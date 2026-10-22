import hashlib
import os
import sys
import time
import zipfile
from pathlib import Path

import pypdfium2
import pytest
from PIL import Image

import dam.collections.export as ex
from dam.collections.export import (
    build_pdf,
    build_zip,
    estimate_size,
    prune_exports,
    safe_name,
)
from dam.config import load_settings
from dam.core.paths import ArchivePaths
from dam.index.repo import FileRecord
from dam.services.errors import InvalidRequest
from pdfs import make_text_pdf


@pytest.fixture
def paths(app_paths, fake_archive) -> ArchivePaths:
    return ArchivePaths(fake_archive.root, load_settings(app_paths))


def rec(rel: str, size: int | None = None) -> FileRecord:
    return FileRecord(drive_id=rel, path=rel, size=size)


def tree_digest(root: Path) -> dict[str, str]:
    out = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        out[rel] = (
            "link"
            if p.is_symlink()
            else ("dir" if p.is_dir() else hashlib.sha256(p.read_bytes()).hexdigest())
        )
    return out


def pdf_pages(path: Path) -> int:
    doc = pypdfium2.PdfDocument(str(path))
    try:
        return len(doc)
    finally:
        doc.close()


def page_text(path: Path, n: int) -> str:
    doc = pypdfium2.PdfDocument(str(path))
    try:
        return doc[n].get_textpage().get_text_range()
    finally:
        doc.close()


CONTENTS_PAGES_80 = 8


@pytest.fixture
def members(fake_archive):
    a = fake_archive.root / "10. Financial/Banks/a.pdf"
    a.parent.mkdir(parents=True, exist_ok=True)
    make_text_pdf(a)
    b = fake_archive.add("10. Financial/Banks/note.txt", b"hello " * 50)
    return [rec("10. Financial/Banks/a.pdf"), rec("10. Financial/Banks/note.txt")], a, b


def test_zip_has_members_and_contents(app_paths, paths, members):
    files, a, _ = members
    out = build_zip(app_paths, paths, files, "Sauna / 2026")
    assert out.parent.parent == app_paths.cache_dir / "exports"
    assert out.name == "Sauna _ 2026.zip"
    with zipfile.ZipFile(out) as zf:
        assert sorted(zf.namelist()) == [
            "10. Financial/Banks/a.pdf",
            "10. Financial/Banks/note.txt",
            "contents.txt",
        ]
        assert zf.read("10. Financial/Banks/a.pdf") == a.read_bytes()
        assert zf.getinfo("10. Financial/Banks/a.pdf").compress_type == zipfile.ZIP_STORED
        assert zf.getinfo("10. Financial/Banks/note.txt").compress_type == zipfile.ZIP_DEFLATED
        text = zf.read("contents.txt").decode("utf-8")
    assert f"10. Financial/Banks/a.pdf\t{a.stat().st_size}" in text
    assert "10. Financial/Banks/note.txt\t300" in text


def test_zip_lists_unreadable_and_oversize_and_unsafe(app_paths, paths, members, monkeypatch):
    files, _, _ = members
    monkeypatch.setattr(ex, "MAX_BYTES", 100)
    files = [*files, rec("10. Financial/gone.pdf"), rec("../evil.txt")]
    out = build_zip(app_paths, paths, files, "x")
    with zipfile.ZipFile(out) as zf:
        assert "10. Financial/Banks/note.txt" not in zf.namelist()
        text = zf.read("contents.txt").decode()
    assert "not included: too large" in text
    assert "gone.pdf\t?\tnot included: could not read (file not found)" in text
    assert "../evil.txt\t?\tnot included: unsafe name" in text


def test_zip_nfc_arcnames(app_paths, paths, fake_archive):
    fake_archive.add("10. Financial/Banks/Äiti.txt", b"x")  # decomposed a-umlaut
    out = build_zip(app_paths, paths, [rec("10. Financial/Banks/Äiti.txt")], "n")
    with zipfile.ZipFile(out) as zf:
        assert "10. Financial/Banks/Äiti.txt" in zf.namelist()


def test_hung_read_becomes_not_downloaded(app_paths, paths, members, monkeypatch):
    files, _, _ = members
    import threading

    release = threading.Event()
    real_open = open

    def slow_open(p, *a, **k):
        if str(p).endswith("note.txt"):
            release.wait(5)
        return real_open(p, *a, **k)

    monkeypatch.setattr("builtins.open", slow_open)
    t0 = time.monotonic()
    out = build_zip(app_paths, paths, files, "x", read_timeout_s=0.2)
    release.set()
    assert time.monotonic() - t0 < 3
    with zipfile.ZipFile(out) as zf:
        assert "not included: could not read (not downloaded)" in zf.read("contents.txt").decode()


def test_pdf_pages_images_and_not_included(app_paths, paths, fake_archive, tmp_path):
    p1 = fake_archive.root / "10. Financial/one.pdf"
    make_text_pdf(p1)
    p2 = fake_archive.root / "10. Financial/two.pdf"
    make_text_pdf(p2, "Second")
    img = fake_archive.root / "10. Financial/pic.png"
    Image.new("RGBA", (300, 100), (255, 0, 0, 128)).save(img)
    jpg = fake_archive.root / "10. Financial/wide.jpg"
    Image.new("RGB", (4000, 100), "blue").save(jpg)
    fake_archive.add("10. Financial/letter.docx", b"PK")
    files = [
        rec("10. Financial/one.pdf"),
        rec("10. Financial/two.pdf"),
        rec("10. Financial/pic.png"),
        rec("10. Financial/wide.jpg"),
        rec("10. Financial/letter.docx"),
    ]
    out, notes = build_pdf(app_paths, paths, files, "Mix")
    assert out.name == "Mix.pdf"
    assert pdf_pages(out) == 1 + 2 + 2
    assert notes == ["10. Financial/letter.docx: not included: file type is not included in a PDF"]
    # member order after the contents page
    assert "Kotihoito" in page_text(out, 1)
    assert "Second" in page_text(out, 2)
    first = pypdfium2.PdfDocument(str(out))
    try:
        # the contents page is an image: it must not be blank
        pix = first[0].render(scale=0.3).to_pil().convert("L")
        assert pix.getextrema()[0] < 128
    finally:
        first.close()
    doc = pypdfium2.PdfDocument(str(out))
    try:
        assert doc[3].get_size() == pytest.approx((595, 842), abs=2)
    finally:
        doc.close()


def test_pdf_contents_wraps_and_paginates(app_paths, paths, fake_archive):
    files = [
        rec("10. Financial/" + ("very long folder name " * 8).strip() + f"/{i:03d}.docx")
        for i in range(80)
    ]
    out, notes = build_pdf(app_paths, paths, files, "Many")
    assert len(notes) == 80
    assert pdf_pages(out) == CONTENTS_PAGES_80


def test_pdf_encrypted_and_corrupt_listed(app_paths, paths, fake_archive):
    fake_archive.add("a/bad.pdf", b"%PDF-1.4 not really")
    good = fake_archive.root / "a/good.pdf"
    make_text_pdf(good)
    # an encrypted PDF: PDFium reports a password error
    enc = fake_archive.root / "a/enc.pdf"
    doc = pypdfium2.PdfDocument(str(good))
    doc.save(enc)
    doc.close()
    raw = enc.read_bytes().replace(b"/Root", b"/Encrypt << /Filter /Standard /V 1 /R 2 >> /Root", 1)
    enc.write_bytes(raw)
    out, notes = build_pdf(
        app_paths, paths, [rec("a/bad.pdf"), rec("a/enc.pdf"), rec("a/good.pdf")], "e"
    )
    assert pdf_pages(out) == 2
    assert sorted(notes) == [
        "a/bad.pdf: not included: could not read (corrupt PDF)",
        "a/enc.pdf: not included: encrypted (password protected)",
    ]
    assert "a/bad.pdf: not included: could not read (corrupt PDF)" in notes


def test_pdf_page_limit(app_paths, paths, fake_archive, monkeypatch):
    for n in "abc":
        make_text_pdf(fake_archive.root / f"{n}.pdf")
    monkeypatch.setattr(ex, "MAX_PAGES", 3)  # 1 contents page + 2 members
    out, notes = build_pdf(app_paths, paths, [rec("a.pdf"), rec("b.pdf"), rec("c.pdf")], "p")
    assert notes == ["c.pdf: not included: page limit"]
    assert pdf_pages(out) == 3


def test_pdf_unreadable_listed(app_paths, paths):
    out, notes = build_pdf(app_paths, paths, [rec("missing.pdf")], "m")
    assert notes == ["missing.pdf: not included: could not read (file not found)"]
    assert pdf_pages(out) == 1


def test_oversize_needs_confirm(app_paths, paths, members):
    files, _, _ = members
    big = [FileRecord(drive_id="x", path="10. Financial/Banks/note.txt", size=300 * 1024**2)]
    assert estimate_size(big) == 300 * 1024**2
    with pytest.raises(InvalidRequest):
        build_zip(app_paths, paths, big, "x")
    with pytest.raises(InvalidRequest):
        build_pdf(app_paths, paths, big, "x")
    assert build_zip(app_paths, paths, big, "x", confirm_large=True).exists()


def test_export_never_writes_into_archive(app_paths, paths, members, fake_archive):
    files, _, _ = members
    before = tree_digest(fake_archive.root)
    build_zip(app_paths, paths, files, "z")
    build_pdf(app_paths, paths, files, "p")
    assert tree_digest(fake_archive.root) == before


def test_safe_name():
    assert safe_name("a/b\\c\nd") == "a_b_c_d"
    assert len(safe_name("x" * 300)) == 100
    assert safe_name("  ") == "export"


# --- prune ------------------------------------------------------------------------


def mk(app_paths, name, age_s):
    d = app_paths.cache_dir / "exports" / name
    d.mkdir(parents=True)
    (d / "f.zip").write_bytes(b"z")
    t = time.time() - age_s
    os.utime(d, (t, t))
    return d


def test_prune_removes_only_old_export_dirs(app_paths):
    old = mk(app_paths, "a" * 32, 2 * 86400)
    new = mk(app_paths, "b" * 32, 60)
    other = mk(app_paths, "not-an-export", 5 * 86400)
    assert prune_exports(app_paths) == ["a" * 32]
    assert not old.exists() and new.exists() and other.exists()


def test_inside_check_is_strict(app_paths, tmp_path):
    root = app_paths.cache_dir / "exports"
    root.mkdir(parents=True, exist_ok=True)
    deeper = root / ("c" * 32) / "deeper"
    deeper.mkdir(parents=True)  # exists on disk: the check really resolves it
    outside = tmp_path / "outside"
    outside.mkdir()
    assert ex._is_export_child(root, root / ("c" * 32))
    for bad in (outside, root, deeper, app_paths.cache_dir):
        assert not ex._is_export_child(root, bad)


def test_prune_removes_symlink_inside_old_dir_not_target(app_paths, tmp_path):
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("k", encoding="utf-8")
    old = mk(app_paths, "f" * 32, 3 * 86400)
    (old / "link").symlink_to(victim)
    os.utime(old, (time.time() - 3 * 86400,) * 2)
    assert prune_exports(app_paths) == ["f" * 32]
    assert (victim / "keep.txt").read_text(encoding="utf-8") == "k"


def test_prune_never_follows_symlinks(app_paths, tmp_path):
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("k", encoding="utf-8")
    root = app_paths.cache_dir / "exports"
    root.mkdir(parents=True, exist_ok=True)
    link = root / ("d" * 32)
    link.symlink_to(victim, target_is_directory=True)
    t = time.time() - 5 * 86400
    if os.utime in os.supports_follow_symlinks:  # not on Windows; a link is never pruned anyway
        os.utime(link, (t, t), follow_symlinks=False)
    assert prune_exports(app_paths) == []
    assert (victim / "keep.txt").exists()
    assert not ex._is_export_child(root, link)
    # a symlinked exports dir is refused outright
    link.unlink()
    root.rmdir()
    root.symlink_to(victim, target_is_directory=True)
    with pytest.raises(InvalidRequest):
        prune_exports(app_paths)
    assert (victim / "keep.txt").exists()


def test_build_prunes_old_exports(app_paths, paths, members):
    files, _, _ = members
    old = mk(app_paths, "e" * 32, 3 * 86400)
    build_zip(app_paths, paths, files, "z")
    assert not old.exists()


# --- fix round 1 ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "10. Financial/..\\..\\evil.txt",
        "a\\b.txt",
        "../x.txt",
        "a/./b.txt",
        "a//b.txt",
        "/abs.txt",
    ],
)
def test_zip_refuses_unsafe_names(app_paths, paths, bad):
    out = build_zip(app_paths, paths, [rec(bad)], "x")
    with zipfile.ZipFile(out) as zf:
        assert zf.namelist() == ["contents.txt"]
        assert "not included: unsafe name" in zf.read("contents.txt").decode()


def test_exports_root_must_not_overlap_archive(app_paths, paths, fake_archive, tmp_path):
    inside = fake_archive.root / "cache"
    inside.mkdir()
    real = app_paths.cache_dir
    real.rmdir()
    real.symlink_to(inside)
    with pytest.raises(InvalidRequest):
        build_zip(app_paths, paths, [], "x")
    assert list(inside.iterdir()) == []


def test_dataless_file_skipped(app_paths, paths, members, monkeypatch):
    files, _, _ = members
    monkeypatch.setattr(ex, "_is_dataless", lambda p: p.name == "note.txt")
    out = build_zip(app_paths, paths, files, "x")
    with zipfile.ZipFile(out) as zf:
        text = zf.read("contents.txt").decode()
        assert "note.txt" not in "".join(zf.namelist())
    assert "not downloaded \u2014 open it once in Finder, then export again" in text


def test_export_deadline(app_paths, paths, members):
    files, _, _ = members
    out = build_zip(app_paths, paths, files, "x", export_deadline_s=0)
    with zipfile.ZipFile(out) as zf:
        assert zf.namelist() == ["contents.txt"]
        assert zf.read("contents.txt").decode().count("export time limit reached") == 2
    _, notes = build_pdf(app_paths, paths, files[:1], "x", export_deadline_s=0)
    assert notes == ["10. Financial/Banks/a.pdf: not included: export time limit reached"]


def test_pdf_byte_ceiling_even_with_confirm(app_paths, paths, fake_archive, monkeypatch):
    for n in "ab":
        make_text_pdf(fake_archive.root / f"{n}.pdf")
    size = (fake_archive.root / "a.pdf").stat().st_size
    monkeypatch.setattr(ex, "PDF_CEILING_BYTES", size + 10)
    out, notes = build_pdf(app_paths, paths, [rec("a.pdf"), rec("b.pdf")], "c", confirm_large=True)
    assert notes == ["b.pdf: not included: size limit for a combined PDF \u2014 use zip"]
    assert pdf_pages(out) == 2


@pytest.mark.skipif(
    sys.platform == "win32", reason="a newline or tab cannot be part of a Windows file name"
)
def test_contents_txt_fields_sanitised(app_paths, paths, fake_archive):
    name = "a/x\ny\tz.txt"
    fake_archive.add(name, b"1")
    out = build_zip(app_paths, paths, [rec(name)], "x")
    with zipfile.ZipFile(out) as zf:
        lines = zf.read("contents.txt").decode().splitlines()
    assert lines == ["a/x?y?z.txt\t1"]


def test_zip_duplicate_names_case_folded(app_paths, paths, fake_archive):
    (fake_archive.root / "d").mkdir()
    fake_archive.add("d/A.txt", b"1")
    dup = rec("d/a.txt")  # a second record with the same folded name
    out = build_zip(app_paths, paths, [rec("d/A.txt"), dup], "x")  # no zipfile warning
    with zipfile.ZipFile(out) as zf:
        assert zf.namelist() == ["d/A.txt", "contents.txt"]
        assert "d/a.txt\t?\tnot included: duplicate name" in zf.read("contents.txt").decode()


def test_pdf_total_pages_exact_cap_with_contents(app_paths, paths, fake_archive, monkeypatch):
    for i in range(6):
        make_text_pdf(fake_archive.root / f"{i}.pdf")
    monkeypatch.setattr(ex, "MAX_PAGES", 5)
    files = [rec(f"{i}.pdf") for i in range(6)]
    out, notes = build_pdf(app_paths, paths, files, "p")
    assert pdf_pages(out) == 5  # 1 contents page + 4 members
    assert notes == [f"{i}.pdf: not included: page limit" for i in (4, 5)]


def test_image_too_large_and_bomb(app_paths, paths, fake_archive, monkeypatch):
    Image.new("L", (400, 300)).save(fake_archive.root / "big.png")
    monkeypatch.setattr(ex, "MAX_IMAGE_PIXELS", 1000)
    _, notes = build_pdf(app_paths, paths, [rec("big.png")], "i")
    assert notes == ["big.png: not included: image too large"]
    monkeypatch.setattr(ex, "MAX_IMAGE_PIXELS", 50_000_000)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100_000)
    _, notes = build_pdf(app_paths, paths, [rec("big.png")], "i")
    assert notes == ["big.png: not included: image too large"]


def test_build_survives_prune_failure(app_paths, paths, members, monkeypatch):
    files, _, _ = members

    def boom(*a, **k):
        raise InvalidRequest("nope")

    monkeypatch.setattr(ex, "prune_exports", boom)
    assert build_zip(app_paths, paths, files, "x").exists()


# --- fix round 2 ---------------------------------------------------------------------


def test_page_cap_trim_is_not_quadratic(app_paths, paths, fake_archive, monkeypatch):
    make_text_pdf(fake_archive.root / "base.pdf")
    data = (fake_archive.root / "base.pdf").read_bytes()
    for i in range(300):
        (fake_archive.root / f"m{i:03d}.pdf").write_bytes(data)
    monkeypatch.setattr(ex, "MAX_PAGES", 60)
    files = [rec(f"m{i:03d}.pdf") for i in range(300)]
    t0 = time.monotonic()
    out, notes = build_pdf(app_paths, paths, files, "big")
    assert time.monotonic() - t0 < 5
    assert pdf_pages(out) == 60
    kept = 300 - len(notes)
    assert all(n.endswith("not included: page limit") for n in notes)
    assert kept > 20  # contents pages + kept members fill the cap exactly


def test_contents_alone_over_cap_lists_no_members(app_paths, paths, fake_archive, monkeypatch):
    make_text_pdf(fake_archive.root / "base.pdf")
    data = (fake_archive.root / "base.pdf").read_bytes()
    for i in range(3000):
        (fake_archive.root / f"m{i:04d}.pdf").write_bytes(data)
    monkeypatch.setattr(ex, "MAX_PAGES", 60)
    files = [rec(f"m{i:04d}.pdf") for i in range(3000)]
    members_added = []
    real_append = ex._append_pdf

    def counting_append(body, blob):
        if blob == data:  # a member's bytes
            members_added.append(1)
        return real_append(body, blob)

    monkeypatch.setattr(ex, "_append_pdf", counting_append)
    out, notes = build_pdf(app_paths, paths, files, "huge")
    # members stop being opened at the page cap, not after all 3000 (counted, not timed:
    # CI runners vary in speed)
    assert len(members_added) <= 60
    assert pdf_pages(out) == 60
    assert len(notes) == 3000
    assert all(n.endswith("not included: page limit") for n in notes)


def test_small_cap_contents_get_more_line(app_paths, paths, fake_archive, monkeypatch):
    make_text_pdf(fake_archive.root / "a.pdf")
    monkeypatch.setattr(ex, "MAX_PAGES", 1)
    files = [rec("a.pdf")] + [rec(f"{i}.docx") for i in range(100)]
    out, notes = build_pdf(app_paths, paths, files, "s")
    assert pdf_pages(out) == 1
    assert notes[0] == "a.pdf: not included: page limit"
    assert len(notes) == 101


def test_stream_enforces_max_bytes_after_stat(app_paths, paths, members, monkeypatch):
    files, _, _ = members

    def small(paths_, r):
        return paths_.abs(r.path), 1  # stat said 1 byte; the file has grown since

    monkeypatch.setattr(ex, "_precheck", small)
    monkeypatch.setattr(ex, "MAX_BYTES", 100)
    out = build_zip(app_paths, paths, files, "g")
    with zipfile.ZipFile(out) as zf:
        assert zf.namelist() == ["contents.txt"]
        assert zf.read("contents.txt").decode().count("not included: too large") == 2
    _, notes = build_pdf(app_paths, paths, files[:1], "g")
    assert notes == ["10. Financial/Banks/a.pdf: not included: too large"]
