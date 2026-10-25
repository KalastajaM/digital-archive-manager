import unicodedata
from pathlib import Path

import pytest

from dam.config import ExtraFolder, Settings
from dam.core.fs import resolve
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


def _with_extra(tmp_path, attached=True):
    main, extra = tmp_path / "main", tmp_path / "disk" / "old"
    main.mkdir()
    extra.mkdir(parents=True)
    s = Settings(
        archive_root=main,
        extra_folders=[ExtraFolder(label="Old years", path=extra, attached=attached)],
    )
    return main, extra, ArchivePaths(main, s)


def test_extra_folder_paths_map_to_their_root(tmp_path):
    main, extra, p = _with_extra(tmp_path)
    assert p.abs("Old years/2009/a.pdf") == resolve(extra) / "2009" / "a.pdf"
    assert p.rel(extra / "2009" / "a.pdf") == "Old years/2009/a.pdf"
    assert p.rel(extra) == "Old years"
    assert p.abs("Taxes/a.pdf") == resolve(main) / "Taxes" / "a.pdf"
    assert p.join("Old years/2009") == resolve(extra) / "2009"
    assert p.join("Taxes") == resolve(main) / "Taxes"
    assert [f.label for f in p.folders] == ["", "Old years"]
    assert p.extra_labels == ("Old years",)
    assert p.folder_of("Old years/x").root == resolve(extra)
    assert p.folder_of("Taxes").label == ""


def test_label_of_matches_whole_components(tmp_path):
    _, _, p = _with_extra(tmp_path)
    assert p.label_of("Old years") == "Old years"
    assert p.label_of("Old years 2/x") == ""
    assert p.label_of("old years/x") == "Old years"
    assert p.label_of(unicodedata.normalize("NFD", "Old years/x")) == "Old years"
    assert p.label_of("") == ""


def test_escape_from_extra_folder_refused(tmp_path):
    _, _, p = _with_extra(tmp_path)
    with pytest.raises(OutsideArchiveError):
        p.abs("Old years/../x")
    with pytest.raises(OutsideArchiveError):
        p.abs("Old years/..")


def test_detached_folder_is_not_mapped(tmp_path):
    main, _, p = _with_extra(tmp_path, attached=False)
    assert p.abs("Old years/a") == resolve(main) / "Old years" / "a"
    assert p.extra_labels == ()
    assert len(p.folders) == 1


def test_disconnected_labels(tmp_path):
    _, extra, p = _with_extra(tmp_path)
    assert p.disconnected_labels() == ()
    assert p.is_connected("Old years") and p.is_connected("")
    extra.rename(extra.with_name("gone"))
    assert p.disconnected_labels() == ("Old years",)
    assert not p.is_connected("Old years")
