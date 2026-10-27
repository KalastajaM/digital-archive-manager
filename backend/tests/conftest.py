# ruff: noqa: E402
import inspect
import os
import sys
import tempfile
from pathlib import Path

import pytest

import archive_guard
import xattr_shim

xattr_shim.install()  # before anything imports xattr (not on Windows; Linux needs a prefix)

import xattr
import yaml
from sqlalchemy import Connection, Engine, text

from dam.config import AppPaths, SpecialFolders
from dam.db.engine import make_engine, migrate
from dam.index.driveid import DRIVE_ID_XATTR
from dam.ops import primitives

archive_guard.install()  # one audit hook for the session: archive writes come from dam/ops

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


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "archive_write_allowed(*places, reason): let these non-ops places "
        '("dam/<file>.py:<function>") write to the fake archive in this test (a known bug)',
    )


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


def put_fts_row(conn: Connection, drive_id: str, name: str, path: str, body: str) -> None:
    """Write the FTS row of ``drive_id`` (replacing any) with its ``file_fts_map`` entry,
    as the repo does."""
    conn.execute(
        text(
            "DELETE FROM file_fts WHERE rowid IN "
            "(SELECT fts_rowid FROM file_fts_map WHERE drive_id = :d)"
        ),
        {"d": drive_id},
    )
    conn.execute(
        text("INSERT INTO file_fts(drive_id, name, path, text) VALUES (:d, :n, :p, :t)"),
        {"d": drive_id, "n": name, "p": path, "t": body},
    )
    conn.execute(
        text("INSERT OR REPLACE INTO file_fts_map VALUES (:d, last_insert_rowid())"),
        {"d": drive_id},
    )


class FakeArchive:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._counter = 0
        archive_guard.register(root)
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
def _archive_write_guard(request: pytest.FixtureRequest):
    """Every ``FakeArchive`` of the test is watched; a write to it from outside dam/ops
    fails the test even if the code under test swallowed the AssertionError."""
    allowed = frozenset(
        place for mark in request.node.iter_markers("archive_write_allowed") for place in mark.args
    )
    archive_guard.reset(allowed)
    yield
    violations = archive_guard.state.violations
    archive_guard.reset()
    if violations:
        pytest.fail("\n".join(dict.fromkeys(violations)), pytrace=False)


@pytest.fixture(autouse=True)
def _reset_dam_logging():
    """Handlers added by ``configure_logging`` (CLI tests) never outlive a test."""
    yield
    from dam.logging_setup import reset_logging

    reset_logging()


@pytest.fixture(autouse=True)
def _connectivity_asked_afresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """A test that unplugs a folder sees it at once; ``test_paths`` tests the cache."""
    from dam.core.paths import ArchivePaths

    monkeypatch.setattr(ArchivePaths, "connected_ttl_s", 0.0)


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


@pytest.fixture
def freeze_today(monkeypatch: pytest.MonkeyPatch):
    """``freeze_today(day)``: ``date.today()`` returns ``day`` in the modules that ask for
    today's date, so a test cannot flip with the calendar or across midnight. Returns
    ``day``."""
    import datetime

    from dam.api.routers import collections, today, trays
    from dam.rules import fields
    from dam.services import today as today_service
    from dam.trays import service

    def freeze(day: datetime.date) -> datetime.date:
        class _Meta(type):
            def __instancecheck__(cls, obj):  # real dates still count as dates
                return isinstance(obj, datetime.date)

        class FrozenDate(datetime.date, metaclass=_Meta):
            @classmethod
            def today(cls):
                return day

        for module in (collections, today, trays, fields, service, today_service):
            monkeypatch.setattr(module, "date", FrozenDate)
        return day

    return freeze
