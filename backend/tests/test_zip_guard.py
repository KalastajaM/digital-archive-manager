"""Zip-based documents (Word, Excel, PowerPoint, iWork) that would unpack to too much
are refused before any library reads them: a zip bomb is "could not read", never a
crash of the server."""

import struct
import zipfile

import pytest

from dam.extract import zip_guard
from dam.extract.base import UnsupportedContent
from dam.extract.docx import DocxExtractor
from dam.extract.iwork import IworkExtractor
from dam.extract.office import PptxExtractor, XlsxExtractor
from pdfs import make_text_pdf

LANGS = ["en-US"]
MB = 1024 * 1024

# a member each kind of file has, so the bomb sits where the reader looks
CASES = [
    ("a.docx", DocxExtractor, "word/document.xml"),
    ("a.pptx", PptxExtractor, "ppt/presentation.xml"),
    ("a.xlsx", XlsxExtractor, "xl/workbook.xml"),
    ("a.pages", None, "QuickLook/Preview.pdf"),
]


def _extractor(cls):
    return IworkExtractor(LANGS) if cls is None else cls()


def _ratio_bomb(path, member):
    """``member`` is 4 MB of zeros, deflated to a few kB (a ratio near 1000)."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", b"<Types/>")
        zf.writestr(member, b"\0" * (4 * MB))
    return path


def _declared_bomb(path, member, declared=600 * MB):
    """``member`` claims ``declared`` bytes, packed and unpacked alike (so its ratio
    is 1): only the declared size gives it away."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("[Content_Types].xml", b"<Types/>")
        zf.writestr(member, b"x" * 100)
    raw = bytearray(path.read_bytes())
    name = member.encode()
    at = raw.find(b"PK\x01\x02")  # the central directory: sizes at +20, name length at +28
    while at != -1:
        name_len = struct.unpack_from("<H", raw, at + 28)[0]
        if bytes(raw[at + 46 : at + 46 + name_len]) == name:
            struct.pack_into("<II", raw, at + 20, declared, declared)  # packed, unpacked
            break
        at = raw.find(b"PK\x01\x02", at + 4)
    else:
        raise AssertionError("member not found")
    path.write_bytes(bytes(raw))
    assert zipfile.ZipFile(path).getinfo(member).file_size == declared
    return path


@pytest.mark.parametrize(("name", "cls", "member"), CASES)
def test_a_ratio_bomb_is_refused(tmp_path, name, cls, member):
    f = _ratio_bomb(tmp_path / name, member)
    with pytest.raises(UnsupportedContent, match="compressed too tightly"):
        _extractor(cls).extract(f)
    with pytest.raises(UnsupportedContent, match="compressed too tightly"):
        _extractor(cls).extract(f, f.read_bytes())  # the indexer hands over the bytes


@pytest.mark.parametrize(("name", "cls", "member"), CASES)
def test_a_declared_size_bomb_is_refused(tmp_path, name, cls, member):
    f = _declared_bomb(tmp_path / name, member)
    with pytest.raises(UnsupportedContent, match="over 512 MB unpacked"):
        _extractor(cls).extract(f)
    with pytest.raises(UnsupportedContent, match="over 512 MB unpacked"):
        _extractor(cls).extract(f, f.read_bytes())


def test_too_many_members_are_refused(tmp_path):
    f = tmp_path / "a.docx"
    with zipfile.ZipFile(f, "w") as zf:
        for i in range(zip_guard.MAX_MEMBERS + 1):
            zf.writestr(f"p/{i}", b"")
    with pytest.raises(UnsupportedContent, match="too many parts"):
        DocxExtractor().extract(f)


def test_a_small_tight_member_and_a_normal_file_pass(tmp_path):
    # under 1 MB unpacked, any ratio is fine (XML of a short document packs tightly)
    f = tmp_path / "a.zip"
    with zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("styles.xml", b"\0" * (MB - 1))
    zip_guard.check(f, None)
    zip_guard.check(f, f.read_bytes())
    # not a zip: left to the reader, which says what it is (password-protected, ...)
    bad = tmp_path / "b.docx"
    bad.write_bytes(b"not a zip")
    zip_guard.check(bad, None)


def test_iwork_reads_its_preview_with_a_bound(tmp_path, monkeypatch):
    pdf = make_text_pdf(tmp_path / "p.pdf")
    f = tmp_path / "a.pages"
    with zipfile.ZipFile(f, "w") as zf:
        zf.writestr("QuickLook/Preview.pdf", pdf.read_bytes())
    assert "Kotihoito" in IworkExtractor(LANGS).extract(f).text
    # a preview larger than the cap is not read past it
    monkeypatch.setattr(zip_guard, "MAX_TOTAL", 100)
    with zipfile.ZipFile(f) as zf, pytest.raises(UnsupportedContent, match="over"):
        zip_guard.read_member(zf, "QuickLook/Preview.pdf")
