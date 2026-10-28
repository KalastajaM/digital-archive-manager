"""The system folder dialog behind the "Choose…" buttons (the runner is faked: no window)."""

import subprocess

import pytest
from fastapi.testclient import TestClient

from dam import folder_dialog as fd
from dam.api.setup_mode import create_setup_api
from dam.config import AppPaths

BASE = "http://127.0.0.1:8797"
ORIGIN = {"Origin": BASE}


class Fake:
    """Records the command and answers with a fixed result (or raises)."""

    def __init__(self, code=0, out=b"", raises=None):
        self.code, self.out, self.raises, self.calls = code, out, raises, []

    def __call__(self, args, env):
        self.calls.append((args, env))
        if self.raises:
            raise self.raises
        return fd.Run(self.code, self.out)


@pytest.fixture
def desktop(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)


def test_mac_returns_the_path_without_the_trailing_slash(tmp_path):
    run = Fake(out="/Users/me/Documents/Åre arkisto/\n".encode())
    got = fd.choose_folder(str(tmp_path), platform="darwin", runner=run)
    assert got == fd.Choice(path="/Users/me/Documents/Åre arkisto")
    args, _ = run.calls[0]
    assert args[0] == fd.OSASCRIPT and args[-2:] == [fd.PROMPT, str(tmp_path)]


def test_a_root_folder_keeps_its_slash(tmp_path):
    got = fd.choose_folder(None, platform="darwin", runner=Fake(out=b"/\n"), home=tmp_path)
    assert got.path == "/"


def test_mac_cancel_and_failure(tmp_path):
    assert fd.choose_folder(None, platform="darwin", runner=Fake(code=1), home=tmp_path).cancelled
    other = fd.choose_folder(None, platform="darwin", runner=Fake(code=2), home=tmp_path)
    assert other.unavailable == fd.FAILED and other.path is None


def test_windows_passes_the_start_folder_in_the_environment(tmp_path):
    run = Fake(out=b"C:\\Users\\me\\Arkisto")
    got = fd.choose_folder(str(tmp_path), platform="win32", runner=run)
    assert got.path == "C:\\Users\\me\\Arkisto"
    args, env = run.calls[0]
    assert "-STA" in args and "-NoProfile" in args and env["DAM_START"] == str(tmp_path)


def test_windows_drive_root_keeps_its_backslash(tmp_path):
    got = fd.choose_folder(None, platform="win32", runner=Fake(out=b"D:\\"), home=tmp_path)
    assert got.path == "D:\\"


def test_windows_cancel(tmp_path):
    run = Fake(code=fd.CANCEL_CODE)
    assert fd.choose_folder(None, platform="win32", runner=run, home=tmp_path).cancelled


def test_linux_uses_zenity_first(desktop, monkeypatch, tmp_path):
    monkeypatch.setattr(fd.shutil, "which", lambda name: f"/usr/bin/{name}")
    run = Fake(out=b"/home/me/archive\n")
    got = fd.choose_folder(str(tmp_path), platform="linux", runner=run)
    assert got.path == "/home/me/archive"
    assert run.calls[0][0][0] == "zenity" and len(run.calls) == 1


def test_linux_falls_back_to_kdialog(desktop, monkeypatch, tmp_path):
    monkeypatch.setattr(
        fd.shutil, "which", lambda name: "/usr/bin/kdialog" if name == "kdialog" else None
    )
    run = Fake(out=b"/home/me/archive\n")
    assert (
        fd.choose_folder(None, platform="linux", runner=run, home=tmp_path).path
        == "/home/me/archive"
    )
    assert run.calls[0][0][0] == "kdialog"


def test_linux_cancel(desktop, monkeypatch, tmp_path):
    monkeypatch.setattr(fd.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert fd.choose_folder(None, platform="linux", runner=Fake(code=1), home=tmp_path).cancelled


def test_linux_without_a_dialog_program_or_desktop(desktop, monkeypatch, tmp_path):
    monkeypatch.setattr(fd.shutil, "which", lambda name: None)
    run = Fake()
    got = fd.choose_folder(None, platform="linux", runner=run, home=tmp_path)
    assert got.unavailable == fd.NO_DIALOG_HERE and not run.calls
    monkeypatch.delenv("DISPLAY")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    got = fd.choose_folder(None, platform="linux", runner=run, home=tmp_path)
    assert got.unavailable == fd.NO_DESKTOP and not run.calls


def test_a_name_that_is_not_utf8_is_refused_not_guessed(tmp_path):
    got = fd.choose_folder(
        None, platform="darwin", runner=Fake(out=b"/tmp/\xff\xfe\n"), home=tmp_path
    )
    assert got == fd.Choice(unavailable=fd.NOT_TEXT)


def test_empty_output_counts_as_cancelled(tmp_path):
    assert fd.choose_folder(
        None, platform="darwin", runner=Fake(out=b"\n"), home=tmp_path
    ).cancelled


def test_a_program_that_cannot_run_or_times_out_is_unavailable(tmp_path):
    gone = Fake(raises=FileNotFoundError("osascript"))
    assert fd.choose_folder(None, platform="darwin", runner=gone, home=tmp_path).unavailable
    slow = Fake(raises=subprocess.TimeoutExpired("osascript", 1))
    assert (
        fd.choose_folder(None, platform="darwin", runner=slow, home=tmp_path).unavailable
        == fd.TIMED_OUT
    )


def test_only_one_window_at_a_time(tmp_path):
    inner = []

    def nested(args, env):
        inner.append(fd.choose_folder(None, platform="darwin", runner=Fake(), home=tmp_path))
        return fd.Run(1)

    assert fd.choose_folder(None, platform="darwin", runner=nested, home=tmp_path).cancelled
    assert inner == [fd.Choice(unavailable=fd.BUSY)]
    assert fd.choose_folder(None, platform="darwin", runner=Fake(code=1), home=tmp_path).cancelled


def test_start_folder_is_the_nearest_existing_folder(tmp_path):
    (tmp_path / "a").mkdir()
    home = tmp_path / "home"
    assert fd.start_folder(str(tmp_path / "a" / "new" / "deeper"), home) == tmp_path / "a"
    assert fd.start_folder("relative/path", home) == home
    assert fd.start_folder("", home) == home
    assert fd.start_folder(None, home) == home
    assert fd.start_folder("/bad\0path", home) == home


def test_the_api_returns_the_choice(monkeypatch, tmp_path):
    seen = []

    def fake(start):
        seen.append(start)
        return fd.Choice(path=str(tmp_path))

    monkeypatch.setattr(fd, "choose_folder", fake)
    paths = AppPaths(tmp_path / "data")
    api = create_setup_api(paths, None, home=tmp_path)
    with TestClient(api, base_url=BASE) as c:
        r = c.post("/api/system/choose-folder", json={"start": "/x"}, headers=ORIGIN)
        assert r.status_code == 200
        assert r.json() == {"path": str(tmp_path), "cancelled": False, "unavailable": None}
        assert seen == ["/x"]
        monkeypatch.setattr(fd, "choose_folder", lambda start: fd.Choice(cancelled=True))
        assert (
            c.post("/api/system/choose-folder", json={}, headers=ORIGIN).json()["cancelled"] is True
        )
        monkeypatch.setattr(fd, "choose_folder", lambda start: fd.Choice(unavailable="nope"))
        assert (
            c.post("/api/system/choose-folder", json={}, headers=ORIGIN).json()["unavailable"]
            == "nope"
        )
        bad = c.post(
            "/api/system/choose-folder",
            json={"start": "/x"},
            headers={"Origin": "http://evil.example"},
        )
        assert bad.status_code in (400, 403)
        assert (
            c.post("/api/system/choose-folder", json={"extra": 1}, headers=ORIGIN).status_code
            == 422
        )
