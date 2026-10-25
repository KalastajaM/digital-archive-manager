# ruff: noqa: E402
import inspect
import os
import sys
import tempfile
from pathlib import Path

import pytest

import xattr_shim

xattr_shim.install()  # before anything imports xattr (not on Windows; Linux needs a prefix)

import xattr
import yaml
from sqlalchemy import Engine

from dam.config import AppPaths, SpecialFolders
from dam.db.engine import make_engine, migrate
from dam.index.driveid import DRIVE_ID_XATTR
from dam.ops import primitives

needs_dir_fd = pytest.mark.skipif(
    not primitives._HAS_DIR_FD,
    reason="a .DS_Store is only removed through an open folder (dir_fd), which Windows lacks;"
    " there the app leaves such a folder in place",
)
posix_permissions = pytest.mark.skipif(
    sys.platform == "win32", reason="Windows ignores chmod: a folder cannot be made unreadable"
)
posix_names = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows file names cannot hold control characters, a trailing dot or a colon",
)


def _can_symlink() -> bool:
    """False on Windows without Developer Mode / the symlink privilege."""
    with tempfile.TemporaryDirectory() as d:
        try:
            os.symlink(Path(d) / "target", Path(d) / "link")
        except OSError:
            return False
    return True


# whole files about links the app publishes (skipped on Windows without the privilege)
_LINK_MODULES = {"test_ongoing", "test_links", "test_two_roots"}


def _source(item) -> str:
    func = getattr(item, "function", None)
    try:
        return inspect.getsource(func) if func else ""
    except (OSError, TypeError):
        return ""


# tests that drive the macOS-only helpers (LaunchAgent, osascript); they are skipped
# elsewhere, where the "not available on this platform" paths are tested instead
_MAC_ONLY_WORDS = ("launchd", "osascript")


def pytest_collection_modifyitems(config, items):
    mac_only = pytest.mark.skip(reason="macOS only (launchd, osascript)")
    no_links = pytest.mark.skip(reason="needs the Windows symlink privilege (Developer Mode)")
    links_ok = sys.platform != "win32" or _can_symlink()
    for item in items:
        source = _source(item)
        if sys.platform != "darwin" and any(w in source for w in _MAC_ONLY_WORDS):
            item.add_marker(mac_only)
        if not links_ok and (
            item.module.__name__ in _LINK_MODULES or "symlink" in source or ".link(" in source
        ):
            item.add_marker(no_links)


class FakeArchive:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._counter = 0
        root.mkdir(parents=True, exist_ok=True)
        folders = SpecialFolders()
        for name in (folders.inbox, folders.ongoing, folders.important, folders.quarantine):
            (root / name).mkdir(exist_ok=True)
        (root / "10. Financial" / "Banks").mkdir(parents=True, exist_ok=True)

    def add(self, rel: str, content: bytes = b"x", drive_id: str | None = "auto") -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        if drive_id == "auto":
            self._counter += 1
            drive_id = f"fake-{self._counter}"
        if drive_id is not None:
            xattr.setxattr(path, DRIVE_ID_XATTR, drive_id.encode("utf-8"))
        return path

    def link(self, rel: str, target_rel: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(self.root / target_rel)
        return path


@pytest.fixture(autouse=True)
def _reset_dam_logging():
    """Handlers added by ``configure_logging`` (CLI tests) never outlive a test."""
    yield
    from dam.logging_setup import reset_logging

    reset_logging()


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A bare ``App.create()`` must never reach the real archive or data dir."""
    monkeypatch.setenv("DAM_DATA_DIR", str(tmp_path / "default-data"))


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Setup detection looks in the home folder: tests get an empty fake one, never the
    real one."""
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))


@pytest.fixture
def fake_archive(tmp_path: Path) -> FakeArchive:
    return FakeArchive(tmp_path / "archive")


@pytest.fixture
def app_paths(tmp_path: Path, fake_archive: FakeArchive) -> AppPaths:
    paths = AppPaths(tmp_path / "data")
    paths.ensure()
    (paths.config_dir / "settings.yaml").write_text(
        yaml.safe_dump({"archive_root": str(fake_archive.root)}), encoding="utf-8"
    )
    return paths


@pytest.fixture
def extra_folder(tmp_path: Path, app_paths: AppPaths) -> FakeArchive:
    """A second archive folder ("Old years") on another fake disk, listed in the settings."""
    extra = FakeArchive(tmp_path / "disk" / "Archive 2000-2015")
    settings_file = app_paths.config_dir / "settings.yaml"
    data = yaml.safe_load(settings_file.read_text(encoding="utf-8"))
    data["extra_folders"] = [{"label": "Old years", "path": str(extra.root)}]
    settings_file.write_text(yaml.safe_dump(data), encoding="utf-8")
    return extra


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    eng = make_engine(tmp_path / "dam.sqlite")
    migrate(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def new_engine():
    """``make_engine`` for a test's own database, disposed at teardown even when the
    test fails (a leaked engine's connections would surface later as an unraisable
    ResourceWarning in an unrelated test)."""
    made: list[Engine] = []

    def make(path: Path) -> Engine:
        eng = make_engine(path)
        made.append(eng)
        return eng

    yield make
    for eng in made:
        eng.dispose()


@pytest.fixture
def app(app_paths: AppPaths):
    from dam.app import App

    application = App.create(app_paths.data_dir)
    yield application
    application.close()


class MemoryKeyring:
    """A keyring backend that lives in this process: tests never touch the Keychain."""

    priority = 1

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        import keyring.errors

        if (service, username) not in self.store:
            raise keyring.errors.PasswordDeleteError(username)
        del self.store[(service, username)]


@pytest.fixture(autouse=True)
def fake_keyring():
    """Every test runs against an in-memory keyring (never the macOS Keychain)."""
    import keyring
    import keyring.backend

    class Backend(MemoryKeyring, keyring.backend.KeyringBackend):
        priority = 1

        def __init__(self) -> None:
            MemoryKeyring.__init__(self)

    backend = Backend()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(Backend())


@pytest.fixture(autouse=True)
def _no_real_anthropic_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real Anthropic client is never built in tests (no network, no key use)."""
    import anthropic

    def refuse(self, *args, **kwargs):
        raise AssertionError("tests must never construct anthropic.Anthropic")

    monkeypatch.setattr(anthropic.Anthropic, "__init__", refuse)
