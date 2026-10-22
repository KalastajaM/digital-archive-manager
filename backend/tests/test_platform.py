"""Platform fallbacks: OCR engine choice, open/reveal commands, reminders off macOS,
links on Windows, junk files, the default data dir. Everything is simulated, so the
suite checks every platform's branch on any platform."""

import os
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest
from PIL import Image
from platformdirs import user_data_dir
from typer.testing import CliRunner

from dam import config
from dam.cli.main import app as cli_app
from dam.config import default_data_dir
from dam.core.paths import OutsideArchiveError
from dam.extract import ocr
from dam.extract.base import UnsupportedContent, default_registry
from dam.extract.msg import NO_MSG, MsgExtractor
from dam.index import driveid
from dam.index.scanner import is_ignored
from dam.ops import primitives
from dam.ops.model import GuardError, OpFailed
from dam.reminders import notify
from dam.services.launch import EXPLORER, OPEN_BIN, STARTFILE, XDG_OPEN, LaunchService

# -- data dir ---------------------------------------------------------------------------


def test_default_data_dir_is_the_platformdirs_one():
    assert default_data_dir() == Path(user_data_dir("DigitalArchiveManager", appauthor=False))


@pytest.mark.skipif(sys.platform != "darwin", reason="the macOS location")
def test_default_data_dir_is_unchanged_on_macos():
    assert (
        default_data_dir()
        == Path.home() / "Library" / "Application Support" / "DigitalArchiveManager"
    )


def test_config_uses_it(monkeypatch):
    monkeypatch.delenv("DAM_DATA_DIR", raising=False)
    assert config.AppPaths().data_dir == default_data_dir()


# -- OCR --------------------------------------------------------------------------------


def _no_vision(monkeypatch):
    monkeypatch.setattr(ocr.sys, "platform", "linux")


def test_engine_none_without_tesseract(monkeypatch):
    _no_vision(monkeypatch)
    monkeypatch.setattr(ocr.shutil, "which", lambda name: None)
    assert ocr.engine() is None


def test_engine_tesseract_when_installed(monkeypatch):
    _no_vision(monkeypatch)
    monkeypatch.setattr(ocr.shutil, "which", lambda name: "/usr/bin/tesseract")
    assert ocr.engine() == ocr.TESSERACT


@pytest.mark.skipif(sys.platform != "darwin", reason="Apple Vision needs macOS")
def test_engine_vision_on_macos():
    assert ocr.engine() == ocr.VISION


def test_tesseract_language_codes():
    assert ocr.tesseract_languages(["fi-FI", "en-US"]) == "fin+eng"
    assert ocr.tesseract_languages(["en-US", "fi"]) == "eng+fin"
    assert ocr.tesseract_languages(["xx-XX"]) == "eng"
    assert ocr.tesseract_languages([]) == "eng"


def test_tesseract_gets_the_mapped_languages(monkeypatch):
    import pytesseract

    _no_vision(monkeypatch)
    monkeypatch.setattr(ocr.shutil, "which", lambda name: "/usr/bin/tesseract")
    seen = {}

    def fake(image, lang=None):
        seen["lang"] = lang
        return "Kotihoito"

    monkeypatch.setattr(pytesseract, "image_to_string", fake)
    assert ocr.ocr_image(Image.new("RGB", (4, 4)), ["fi-FI", "en-US"]) == "Kotihoito"
    assert seen["lang"] == "fin+eng"


def test_images_are_unsupported_without_an_engine(monkeypatch, tmp_path):
    _no_vision(monkeypatch)
    monkeypatch.setattr(ocr.shutil, "which", lambda name: None)
    png = tmp_path / "a.png"
    Image.new("RGB", (8, 8), "white").save(png)
    with pytest.raises(UnsupportedContent, match="no OCR engine installed"):
        default_registry(["en-US"]).extract(png)


def test_scanned_pdf_without_engine_is_unsupported(monkeypatch, tmp_path):
    from pdfs import make_scan_pdf, make_text_pdf

    _no_vision(monkeypatch)
    monkeypatch.setattr(ocr.shutil, "which", lambda name: None)
    reg = default_registry(["en-US"])
    with pytest.raises(UnsupportedContent, match="no OCR engine installed"):
        reg.extract(make_scan_pdf(tmp_path / "scan.pdf"))
    # a PDF with a text layer needs no OCR at all
    assert "Kotihoito" in reg.extract(make_text_pdf(tmp_path / "t.pdf")).text


# -- .msg without the optional package ---------------------------------------------------


def test_msg_without_extra_is_unsupported(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "extract_msg", None)  # import raises ImportError
    f = tmp_path / "mail.msg"
    f.write_bytes(b"x")
    with pytest.raises(UnsupportedContent) as exc:
        MsgExtractor().extract(f)
    assert str(exc.value) == NO_MSG and "dam[msg]" in NO_MSG


# -- drive ids ---------------------------------------------------------------------------


def test_drive_id_is_none_without_xattr(monkeypatch, tmp_path):
    f = tmp_path / "a"
    f.write_bytes(b"x")
    monkeypatch.setattr(driveid, "xattr", None)
    assert driveid.read_drive_id(f) is None


# -- open / reveal -----------------------------------------------------------------------


class _Paths:
    pass


@pytest.mark.parametrize(
    ("platform", "reveal", "expected"),
    [
        ("darwin", False, [OPEN_BIN, "{p}"]),
        ("darwin", True, [OPEN_BIN, "-R", "{p}"]),
        ("win32", False, [STARTFILE, "{p}"]),
        ("win32", True, [EXPLORER, "/select,{p}"]),
        ("linux", False, [XDG_OPEN, "{p}"]),
        ("linux", True, [XDG_OPEN, "{d}"]),
    ],
)
def test_launch_command_per_platform(platform, reveal, expected):
    svc = LaunchService(_Paths(), platform=platform)  # type: ignore[arg-type]
    path = Path("/a/b/c.pdf")
    want = [x.format(p=path, d=path.parent) for x in expected]
    assert svc.command(reveal, path) == want


def test_launch_unknown_platform_is_not_supported(app, fake_archive):
    from dam.services.errors import NotSupported

    fake_archive.add("10. Financial/Banks/s.pdf", drive_id="s1")
    app.scan()
    app.launch.platform = "freebsd14"
    with pytest.raises(NotSupported):
        app.launch.open(app.repo.get("s1"))


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_open_and_reveal_run_the_platform_command(app, fake_archive, platform):
    path = fake_archive.add("10. Financial/Banks/s.pdf", drive_id="s1")
    app.scan()
    seen = []
    app.launch.runner = lambda args: seen.append(args) or 0
    app.launch.platform = platform
    rec = app.repo.get("s1")
    app.launch.open(rec)
    app.launch.reveal(rec)
    real = path.resolve()
    if platform == "linux":
        assert seen == [[XDG_OPEN, str(real)], [XDG_OPEN, str(real.parent)]]
    else:
        assert seen == [[STARTFILE, str(real)], [EXPLORER, f"/select,{real}"]]


def test_windows_explorer_exit_1_is_not_a_failure(app, fake_archive):
    fake_archive.add("10. Financial/Banks/s.pdf", drive_id="s1")
    app.scan()
    app.launch.platform = "win32"
    app.launch.runner = lambda args: 1
    app.launch.reveal(app.repo.get("s1"))  # explorer reports 1 on success
    from dam.services.errors import Conflict

    with pytest.raises(Conflict):
        app.launch.open(app.repo.get("s1"))


@pytest.mark.parametrize("name", ["setup.exe", "run.bat", "x.ps1", "l.lnk", "a.desktop"])
def test_launcher_types_are_never_opened(app, fake_archive, name):
    from dam.services.errors import Conflict

    fake_archive.add(f"10. Financial/Banks/{name}", drive_id="p1")
    app.scan()
    app.launch.platform = "linux"
    app.launch.runner = lambda args: pytest.fail("must not launch")
    with pytest.raises(Conflict):
        app.launch.open(app.repo.get("p1"))


# -- reminders off macOS -----------------------------------------------------------------


def test_mac_notification_is_not_available_elsewhere(monkeypatch):
    monkeypatch.setattr(notify.sys, "platform", "linux")
    from dam.reminders.engine import Due

    due = Due(1, "t", "Pay", "t", None, None, None, "T")
    with pytest.raises(notify.NotifyError, match="not available on this platform"):
        notify.MacNotifier().send([due])


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_remind_install_explains_and_changes_nothing(tmp_path, monkeypatch, platform):
    from dam.cli import main as cli

    monkeypatch.setattr(cli, "_platform", lambda: platform)
    monkeypatch.setattr(cli.launchd, "install", lambda *a, **k: pytest.fail("installed"))
    data = tmp_path / "data"
    r = CliRunner().invoke(cli_app, ["--data-dir", str(data), "remind", "--install", "--yes"])
    assert r.exit_code == 1
    out = r.output
    assert ("Task Scheduler" if platform == "win32" else "systemd") in out
    assert "Nothing was changed" in out


# -- links on Windows --------------------------------------------------------------------


def test_windows_link_privilege_error_is_a_clear_refusal(monkeypatch, tmp_path):
    monkeypatch.setattr(primitives, "_is_windows", lambda: True)

    def refuse(src, dst, target_is_directory=False):
        err = OSError(1314, "A required privilege is not held by the client")
        err.winerror = 1314
        raise err

    monkeypatch.setattr(primitives.os, "symlink", refuse)
    with pytest.raises(OpFailed, match="Windows needs Developer Mode"):
        primitives.make_symlink(tmp_path / "t", tmp_path / "l")


def test_other_link_errors_still_raise(monkeypatch, tmp_path):
    def boom(src, dst):
        raise FileExistsError("exists")

    monkeypatch.setattr(primitives.os, "symlink", boom)
    with pytest.raises(FileExistsError):
        primitives.make_symlink(tmp_path / "t", tmp_path / "l")


# -- junk files --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", [".DS_Store", "Thumbs.db", "desktop.ini", "THUMBS.DB", "Desktop.ini"]
)
def test_os_junk_is_ignored(name):
    assert is_ignored(name)


def test_junk_is_not_indexed_and_never_deleted(app, fake_archive):
    fake_archive.add("10. Financial/Banks/a.pdf", drive_id="a")
    junk = [
        fake_archive.add(f"10. Financial/Banks/{n}", drive_id=None)
        for n in ("Thumbs.db", "desktop.ini")
    ]
    app.scan()
    names = {r.name for r in app.repo.list_dir("10. Financial/Banks")}
    assert "a.pdf" in names
    assert "Thumbs.db" not in names and "desktop.ini" not in names
    assert all(p.exists() for p in junk)


# -- remove_empty_dir without dir_fd (Windows) -------------------------------------------


@pytest.fixture
def by_path(monkeypatch):
    monkeypatch.setattr(primitives, "_HAS_DIR_FD", False)


def _root(tmp_path):
    root = tmp_path / "##. Ongoing"
    (root / "a" / "b").mkdir(parents=True)
    return root


def test_remove_empty_dir_by_path(by_path, tmp_path):
    root = _root(tmp_path)
    primitives.remove_empty_dir(root / "a" / "b", root)
    assert not (root / "a" / "b").exists() and (root / "a").exists()


def test_remove_empty_dir_by_path_refuses_non_empty(by_path, tmp_path):
    root = _root(tmp_path)
    (root / "a" / "b" / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(GuardError, match="not empty"):
        primitives.remove_empty_dir(root / "a" / "b", root)
    assert (root / "a" / "b" / "keep.txt").exists()


def test_remove_empty_dir_by_path_refuses_root_and_identity(by_path, tmp_path):
    root = _root(tmp_path)
    with pytest.raises(GuardError):
        primitives.remove_empty_dir(root, root)
    st = os.lstat(root / "a" / "b")
    with pytest.raises(GuardError, match="identity"):
        primitives.remove_empty_dir(root / "a" / "b", root, identity=(st.st_dev, st.st_ino + 1))
    primitives.remove_empty_dir(root / "a" / "b", root, identity=(st.st_dev, st.st_ino))


@pytest.mark.skipif(not hasattr(os, "symlink") or sys.platform == "win32", reason="needs links")
def test_remove_empty_dir_by_path_refuses_a_link(by_path, tmp_path):
    root = _root(tmp_path)
    real = tmp_path / "real"
    real.mkdir()
    (root / "ln").symlink_to(real)
    with pytest.raises(GuardError):
        primitives.remove_empty_dir(root / "ln", root)
    assert real.exists()


def test_ds_store_cannot_be_vetted_without_dir_fd(by_path, tmp_path):
    folder = tmp_path / "f"
    folder.mkdir()
    assert primitives.finder_cache_problem(folder) is None
    (folder / ".DS_Store").write_bytes(b"x")
    assert "cannot be checked" in primitives.finder_cache_problem(folder)


# -- paths: disk <-> archive-relative ------------------------------------------------------


def test_rel_is_posix_style(app, fake_archive):
    p = fake_archive.add("10. Financial/Banks/a.pdf")
    rel = app.paths.rel(p)
    assert rel == "10. Financial/Banks/a.pdf" and "\\" not in rel
    assert app.paths.abs(rel) == p.resolve()


@pytest.mark.parametrize("rel", ["../x", "/abs/x", "a/../../x"])
def test_abs_refuses_escapes(app, rel):
    with pytest.raises(OutsideArchiveError):
        app.paths.abs(rel)


def test_windows_style_paths_convert_to_posix_rels():
    disk = PureWindowsPath(r"C:\Archive\10. Financial\Banks\a.pdf")
    root = PureWindowsPath(r"c:\archive")  # Windows paths compare case-insensitively
    assert disk.relative_to(root).as_posix() == "10. Financial/Banks/a.pdf"
    assert PurePosixPath(disk.relative_to(root).as_posix()).parts == (
        "10. Financial",
        "Banks",
        "a.pdf",
    )


@pytest.mark.skipif(sys.platform != "win32", reason="drive letters and backslashes")
def test_abs_refuses_drive_and_backslash_escapes_on_windows(app):
    for rel in ("C:/Windows", "..\\x", "C:\\x"):
        with pytest.raises(OutsideArchiveError):
            app.paths.abs(rel)
