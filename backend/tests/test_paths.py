import unicodedata
from pathlib import Path

import pytest

from dam.config import Settings
from dam.core.paths import ArchivePaths, OutsideArchiveError, nfc


@pytest.fixture
def paths(fake_archive) -> ArchivePaths:
    return ArchivePaths(fake_archive.root, Settings(archive_root=fake_archive.root))


def test_rel_and_abs_roundtrip(paths):
    p = paths.root / "10. Financial" / "Banks" / "a.pdf"
    assert paths.rel(p) == "10. Financial/Banks/a.pdf"
    assert paths.abs("10. Financial/Banks/a.pdf") == p
    assert paths.rel(paths.root) == ""
    assert paths.is_root("")


def test_root_is_resolved(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    ap = ArchivePaths(link, Settings(archive_root=link))
    assert ap.root == real.resolve()
    assert ap.rel(link / "x.pdf") == "x.pdf"


def test_outside_raises(paths):
    with pytest.raises(OutsideArchiveError):
        paths.rel(paths.root.parent / "x")
    assert not paths.is_inside(paths.root.parent / "x")


def test_dotdot_escape_raises(paths):
    with pytest.raises(OutsideArchiveError):
        paths.rel(paths.root / "a/../../x")
    assert paths.rel(paths.root / "a" / "..") == ""
    with pytest.raises(OutsideArchiveError):
        paths.rel(paths.root / "..")


def test_symlink_item_not_resolved(fake_archive, paths):
    fake_archive.add("10. Financial/real.pdf")
    link = fake_archive.link("##. Ongoing/real.pdf", "10. Financial/real.pdf")
    assert paths.rel(link) == "##. Ongoing/real.pdf"


def test_top_level(paths):
    assert paths.is_top_level("10. Financial")
    assert not paths.is_top_level("10. Financial/Banks")
    assert not paths.is_top_level("")


def test_protected(paths):
    assert paths.is_protected("##. Important/Tilly/a.pdf")
    assert paths.is_protected("##. Important")
    assert not paths.is_protected("##. Importantx")
    assert not paths.is_protected("10. Financial")


def test_protected_nfd(fake_archive):
    name = "Päivä"
    s = Settings(archive_root=fake_archive.root, protected_paths=[name])
    ap = ArchivePaths(fake_archive.root, s)
    assert ap.is_protected(unicodedata.normalize("NFD", name) + "/a.pdf")


def test_special_folder_rels(paths):
    assert paths.inbox == "##. Organize"
    assert paths.ongoing == "##. Ongoing"
    assert paths.quarantine == "##. To Delete"


def test_nfc():
    assert nfc(unicodedata.normalize("NFD", "ä")) == "ä"


def test_abs_rejects_escape(paths):
    with pytest.raises(OutsideArchiveError):
        paths.abs("../x")
    assert isinstance(paths.abs("a"), Path)


@pytest.fixture
def linkdir(fake_archive, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "f.pdf").write_bytes(b"x")
    link = fake_archive.root / "linkdir"
    link.symlink_to(outside)
    return link


def test_abs_rejects_symlinked_dir_escape(paths, linkdir):
    with pytest.raises(OutsideArchiveError):
        paths.abs("linkdir/x")


def test_rel_through_symlinked_dir_raises(paths, linkdir):
    with pytest.raises(OutsideArchiveError):
        paths.rel(linkdir / "x")
    assert not paths.is_inside(linkdir / "x")


def test_symlink_item_pointing_outside_has_rel(paths, fake_archive, tmp_path):
    target = tmp_path / "elsewhere.pdf"
    target.write_bytes(b"x")
    link = fake_archive.root / "ext.pdf"
    link.symlink_to(target)
    assert paths.rel(link) == "ext.pdf"


def test_symlink_loop_does_not_crash(paths, fake_archive, monkeypatch):
    a = fake_archive.root / "loop_a"
    a.symlink_to(fake_archive.root / "loop_b")
    (fake_archive.root / "loop_b").symlink_to(a)
    assert isinstance(paths.is_inside(a / "x"), bool)


def test_resolve_errors_fail_closed(paths, monkeypatch):
    def boom(self, strict=False):
        raise RuntimeError("Symlink loop")

    monkeypatch.setattr(Path, "resolve", boom)
    assert not paths.is_inside(paths.root / "a" / "x")
    with pytest.raises(OutsideArchiveError):
        paths.rel(paths.root / "a" / "x")


def test_protected_casefold(paths):
    assert paths.is_protected("##. important/x.pdf")
