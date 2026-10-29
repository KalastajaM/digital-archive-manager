"""First-run setup: detection per platform (fake homes), folder checks, the settings
write, ``dam init``, the setup API and setup mode."""

import os
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from conftest import posix_permissions
from dam import setup
from dam.api import create_api
from dam.api.setup_mode import create_setup_api
from dam.app import App
from dam.cli.main import app as cli
from dam.config import AppPaths, load_settings
from dam.serve import Switchboard

runner = CliRunner()
BASE = "http://127.0.0.1:8796"
ORIGIN = {"Origin": BASE}


def mk(*parts: Path | str) -> Path:
    p = Path(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p


def by_provider(cands):
    return {(c.provider, c.path.name) for c in cands}


# -- detection ----------------------------------------------------------------------


def test_detect_nothing_in_an_empty_home(tmp_path):
    for system in ("darwin", "windows", "linux"):
        assert setup.detect_candidates(mk(tmp_path / "h"), system, []) == []


def test_detect_macos(tmp_path):
    h = mk(tmp_path / "h")
    cs = h / "Library" / "CloudStorage"
    mk(cs / "GoogleDrive-a@example.org" / "My Drive")
    mk(cs / "OneDrive-Personal")
    mk(cs / "Dropbox")
    mk(cs / "Box-Box")
    mk(cs / "SomethingElse")
    (cs / "stray-file").write_text("x", encoding="utf-8")
    mk(h / "Library" / "Mobile Documents" / "com~apple~CloudDocs")
    mk(h / "Dropbox")
    mk(h / "OneDrive - Work")
    mk(h / "Google Drive")
    got = setup.detect_candidates(h, "darwin")
    assert {c.provider for c in got} == {
        setup.GOOGLE_DRIVE,
        setup.ONEDRIVE,
        setup.DROPBOX,
        setup.BOX,
        setup.ICLOUD,
    }
    google = [c for c in got if c.provider == setup.GOOGLE_DRIVE]
    assert any(c.path.name == "My Drive" for c in google)  # the folder with the files
    assert "GoogleDrive-a@example.org" in next(c.label for c in google if c.path.name == "My Drive")
    assert not any("SomethingElse" in str(c.path) for c in got)
    assert [c.provider for c in got].count(setup.DROPBOX) == 2  # CloudStorage and ~/Dropbox


def test_detect_macos_google_drive_without_my_drive(tmp_path):
    h = mk(tmp_path / "h")
    gd = mk(h / "Library" / "CloudStorage" / "GoogleDrive-b@example.org")
    assert setup.detect_candidates(h, "darwin")[0].path == gd


def test_detect_windows(tmp_path):
    h = mk(tmp_path / "h")
    mk(h / "OneDrive")
    mk(h / "OneDrive - Contoso")
    mk(h / "Dropbox")
    mk(h / "iCloudDrive")
    g = mk(tmp_path / "G")
    mk(g / "My Drive")
    plain = mk(tmp_path / "D")  # a drive without My Drive
    got = setup.detect_candidates(h, "windows", [g, plain])
    assert by_provider(got) == {
        (setup.ONEDRIVE, "OneDrive"),
        (setup.ONEDRIVE, "OneDrive - Contoso"),
        (setup.DROPBOX, "Dropbox"),
        (setup.ICLOUD, "iCloudDrive"),
        (setup.GOOGLE_DRIVE, "My Drive"),
    }
    # macOS-only places are not looked at on Windows
    mk(h / "Library" / "CloudStorage" / "Dropbox")
    assert len(setup.detect_candidates(h, "windows", [])) == 4


def test_detect_linux(tmp_path):
    h = mk(tmp_path / "h")
    mk(h / "Dropbox")
    mk(h / "Nextcloud")
    mk(h / "OneDrive")
    mk(h / "pCloudDrive")
    mk(h / "Insync" / "me@example.org")
    mk(h / "Insync" / "you@example.org")
    mk(h / "Documents")
    got = setup.detect_candidates(h, "linux")
    assert by_provider(got) == {
        (setup.DROPBOX, "Dropbox"),
        (setup.NEXTCLOUD, "Nextcloud"),
        (setup.ONEDRIVE, "OneDrive"),
        (setup.PCLOUD, "pCloudDrive"),
        (setup.INSYNC, "me@example.org"),
        (setup.INSYNC, "you@example.org"),
    }


def test_detect_ignores_files_and_lists_a_folder_once(tmp_path):
    h = mk(tmp_path / "h")
    (h / "Dropbox").write_text("a file, not a folder", encoding="utf-8")
    assert setup.detect_candidates(h, "linux") == []
    real = mk(tmp_path / "real")
    mk(h / "Insync")
    (h / "Nextcloud").symlink_to(real)
    (h / "Dropbox").unlink()
    (h / "Dropbox").symlink_to(real)
    assert len(setup.detect_candidates(h, "linux")) == 1


def test_list_subfolders_skips_files_and_hidden(tmp_path):
    root = mk(tmp_path / "r")
    mk(root / "b")
    mk(root / "A")
    mk(root / ".hidden")
    (root / "f.txt").write_text("x", encoding="utf-8")
    assert setup.list_subfolders(root) == ["A", "b"]
    assert setup.list_subfolders(root / "nope") == []


# -- checking a folder --------------------------------------------------------------


@pytest.fixture
def home(tmp_path):
    return Path(os.environ["HOME"])


def check(raw, app_paths, home):
    return setup.check_archive_path(str(raw), app_paths, home)


def test_check_accepts_a_writable_folder(tmp_path, app_paths, home):
    folder = mk(tmp_path / "Archive")
    r = check(folder, app_paths, home)
    assert r.ok and r.path == folder.resolve() and r.exists and r.message == ""


def test_check_refuses(tmp_path, app_paths, home):
    f = tmp_path / "file.txt"
    f.write_text("x", encoding="utf-8")
    cases = {
        "": "Enter",
        "relative/dir": "full path",
        str(Path(tmp_path.anchor)): "top of a disk",
        str(home): "whole home folder",
        str(home.parent): "contains your home",
        str(f): "file, not a folder",
        str(app_paths.data_dir): "data folder",
        str(app_paths.config_dir): "data folder",
    }
    for raw, text in cases.items():
        r = setup.check_archive_path(raw, app_paths, home)
        assert not r.ok and text in r.message, (raw, r)


@posix_permissions
def test_check_read_only_folder(tmp_path, app_paths, home):
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root can write anywhere")
    folder = mk(tmp_path / "ro")
    folder.chmod(0o500)
    try:
        r = check(folder, app_paths, home)
        assert not r.ok and "cannot write" in r.message
    finally:
        folder.chmod(0o700)


def test_check_missing_folder_can_be_created_when_the_parent_exists(tmp_path, app_paths, home):
    parent = mk(tmp_path / "parent")
    r = check(parent / "New", app_paths, home)
    assert not r.ok and r.can_create and not (parent / "New").exists()
    r = check(parent / "a" / "b", app_paths, home)  # the parent is missing too
    assert not r.ok and not r.can_create
    setup.create_archive_folder(check(parent / "New", app_paths, home))
    assert (parent / "New").is_dir()
    with pytest.raises(ValueError):
        setup.create_archive_folder(r)
    assert not (parent / "a").exists()


# -- the settings file --------------------------------------------------------------


def test_default_settings_have_no_archive_root(tmp_path):
    p = AppPaths(tmp_path / "d")
    p.ensure()
    text = (p.config_dir / "settings.yaml").read_text(encoding="utf-8")
    assert yaml.safe_load(text).get("archive_root") is None
    assert "gmail.com" not in text.lower() and "CloudStorage/GoogleDrive-you@example.com" in text
    assert load_settings(p).archive_root is None and not setup.is_configured(p)


def test_write_archive_root_changes_only_that_line(tmp_path):
    p = AppPaths(tmp_path / "d")
    p.ensure()
    before = (p.config_dir / "settings.yaml").read_text(encoding="utf-8")
    archive = mk(tmp_path / "My Archive é")
    setup.write_archive_root(p, archive)
    after = (p.config_dir / "settings.yaml").read_text(encoding="utf-8")
    added = [ln for ln in after.splitlines() if ln not in before.splitlines()]
    assert added == [setup.planned_line(archive)]
    assert load_settings(p).archive_root == archive
    assert setup.is_configured(p)


def test_write_archive_root_replaces_an_existing_value(tmp_path):
    p = AppPaths(tmp_path / "d")
    p.ensure()
    a, b = mk(tmp_path / "a"), mk(tmp_path / "b")
    setup.write_archive_root(p, a)
    setup.write_archive_root(p, b)
    text = (p.config_dir / "settings.yaml").read_text(encoding="utf-8")
    assert text.count("\narchive_root:") + text.startswith("archive_root:") == 1
    assert load_settings(p).archive_root == b
    assert [f.name for f in p.config_dir.iterdir() if f.name.startswith(".settings-")] == []


def test_write_archive_root_windows_style_path_round_trips(tmp_path):
    p = AppPaths(tmp_path / "d")
    p.ensure()
    (p.config_dir / "settings.yaml").write_text("ocr_languages: [en-US]\n", encoding="utf-8")
    line = setup.planned_line(Path("C:\\Users\\me\\OneDrive\\Archive"))
    assert yaml.safe_load(line) == {"archive_root": "C:\\Users\\me\\OneDrive\\Archive"}


def test_write_archive_root_into_a_file_without_comments(tmp_path):
    p = AppPaths(tmp_path / "d")
    p.ensure()
    (p.config_dir / "settings.yaml").write_text("server_port: 9000\n", encoding="utf-8")
    archive = mk(tmp_path / "x")
    setup.write_archive_root(p, archive)
    s = load_settings(p)
    assert s.archive_root == archive and s.server_port == 9000


def test_blank_archive_root_is_unset(tmp_path):
    p = AppPaths(tmp_path / "d")
    p.ensure()
    (p.config_dir / "settings.yaml").write_text('archive_root: ""\n', encoding="utf-8")
    assert load_settings(p).archive_root is None


# -- commands without an archive ----------------------------------------------------


@pytest.fixture
def bare(tmp_path):
    """A data dir with the default (unconfigured) settings."""
    p = AppPaths(tmp_path / "bare-data")
    p.ensure()
    return p


def run(p, *args, input=None):
    return runner.invoke(cli, ["--data-dir", str(p.data_dir), *map(str, args)], input=input)


def test_commands_that_need_the_archive_say_so(bare):
    for args in (["scan"], ["inbox"], ["activity"], ["recover"]):
        r = run(bare, *args)
        assert r.exit_code == 1, (args, r.output)
        assert setup.NOT_CONFIGURED in r.output
    assert not (bare.data_dir / "no-archive-configured").exists()


def test_openapi_works_unconfigured(bare):
    r = run(bare, "openapi")
    assert r.exit_code == 0 and '"/api/setup"' in r.stdout


def test_app_create_refuses_unconfigured(bare):
    from dam.errors import NotConfigured

    with pytest.raises(NotConfigured):
        App.create(bare.data_dir)
    app = App.create(bare.data_dir, require_archive=False)
    try:
        assert not app.settings.configured and not app.archive_available
    finally:
        app.close()


# -- dam init -----------------------------------------------------------------------


def test_init_non_interactive(bare, tmp_path):
    archive = mk(tmp_path / "Archive")
    r = run(bare, "init", "--archive", archive, "--yes")
    assert r.exit_code == 0, r.output
    assert load_settings(bare).archive_root == archive.resolve()
    assert "##. Organize" in r.output and "not there yet" in r.output
    assert not (archive / "##. Organize").exists()  # nothing was created in the archive
    assert list(archive.iterdir()) == []


def test_init_asks_before_writing(bare, tmp_path):
    archive = mk(tmp_path / "Archive")
    r = run(bare, "init", "--archive", archive, input="n\nn\n")  # no new archive; no write
    assert r.exit_code == 1 and "Nothing written" in r.output
    assert not setup.is_configured(bare)
    r = run(bare, "init", "--archive", archive, input="n\ny\n")  # no new archive; write
    assert r.exit_code == 0 and setup.is_configured(bare)


def test_init_rejects_a_bad_folder(bare, tmp_path):
    r = run(bare, "init", "--archive", tmp_path / "nope" / "deeper", "--yes")
    assert r.exit_code == 1 and "does not exist" in r.output
    assert not setup.is_configured(bare)
    assert not (tmp_path / "nope").exists()
    r = run(bare, "init", "--archive", Path(os.environ["HOME"]), "--yes")
    assert r.exit_code == 1 and "home folder" in r.output


def test_init_creates_a_missing_folder_only_after_a_yes(bare, tmp_path):
    parent = mk(tmp_path / "parent")
    r = run(bare, "init", "--archive", parent / "New", input="n\n")
    assert r.exit_code == 1 and not (parent / "New").exists()
    r = run(
        bare, "init", "--archive", parent / "New", input="y\nn\ny\n"
    )  # create, no layout, write
    assert r.exit_code == 0 and (parent / "New").is_dir()
    assert load_settings(bare).archive_root == (parent / "New").resolve()


def test_init_interactive_picks_a_cloud_folder_and_subfolder(bare, tmp_path, monkeypatch):
    home = Path(os.environ["HOME"])
    if setup.current_system() == "darwin":
        drive = mk(home / "Library" / "CloudStorage" / "Dropbox")
    else:
        drive = mk(home / "Dropbox")
    mk(drive / "Docs")
    mk(drive / "Papers")
    r = run(
        bare, "init", input="1\n2\nn\ny\n"
    )  # first location, second subfolder, no layout, write
    assert r.exit_code == 0, r.output
    assert "Dropbox" in r.output
    assert load_settings(bare).archive_root == (drive / "Papers").resolve()


def test_init_interactive_creates_a_new_folder_in_a_location(bare, tmp_path):
    home = Path(os.environ["HOME"])
    drive = mk(home / "Dropbox")
    mk(drive / "Docs")
    # location 1, "Create a new folder here" is after "Docs/" and "use itself": option 3
    r = run(bare, "init", input="1\n3\nDigital Archive\ny\nn\ny\n")
    assert r.exit_code == 0, r.output
    assert (drive / "Digital Archive").is_dir()
    assert load_settings(bare).archive_root == (drive / "Digital Archive").resolve()


def test_init_interactive_other_folder_and_retry(bare, tmp_path):
    archive = mk(tmp_path / "Mine")
    # no locations found: option 1 is "another folder"; a bad path first, then a good one
    r = run(bare, "init", input=f"1\n{tmp_path / 'missing' / 'x'}\nn\n1\n{archive}\nn\ny\n")
    assert r.exit_code == 0, r.output
    assert "does not exist" in r.output
    assert load_settings(bare).archive_root == archive.resolve()


def test_init_when_already_configured(bare, tmp_path):
    a, b = mk(tmp_path / "a"), mk(tmp_path / "b")
    assert run(bare, "init", "--archive", a, "--yes").exit_code == 0
    r = run(bare, "init", "--archive", a, "--yes")
    assert "Already set" in r.output
    r = run(bare, "init", "--archive", b, "--yes")
    assert r.exit_code == 0 and "replacing" in r.output
    assert load_settings(bare).archive_root == b.resolve()


# -- the setup API ------------------------------------------------------------------


@pytest.fixture
def setup_client(bare):
    switched = []
    api = create_setup_api(bare, None, on_configured=lambda: switched.append(1) or True)
    with TestClient(api, base_url=BASE) as c:
        c.switched = switched
        yield c


def post(c, url, body):
    return c.post(url, json=body, headers=ORIGIN)


def test_setup_status_and_other_routes(setup_client):
    status = setup_client.get("/api/status").json()
    assert status["configured"] is False and status["archive"]["id"] == "main"
    r = setup_client.get("/api/inbox")
    assert r.status_code == 409 and "dam init" in r.json()["error"]


def test_setup_candidates_lists_the_fake_home(bare):
    home = mk(bare.data_dir.parent / "api-home")
    mk(home / "Dropbox")
    system = setup.current_system()
    if system == "darwin":
        mk(home / "Library" / "CloudStorage" / "Dropbox")
    api = create_setup_api(bare, None, home=home)
    with TestClient(api, base_url=BASE) as c:
        body = c.get("/api/setup/candidates").json()
    assert {x["provider"] for x in body["candidates"]} == {"Dropbox"}
    assert [f["role"] for f in body["special_folders"]] == [
        "inbox",
        "ongoing",
        "important",
        "quarantine",
    ]
    assert all("exists" not in f for f in body["special_folders"])


def test_setup_validate(setup_client, tmp_path):
    folder = mk(tmp_path / "A")
    mk(folder / "sub")
    ok = post(setup_client, "/api/setup/validate", {"path": str(folder)}).json()
    assert ok["ok"] and ok["subfolders"] == ["sub"] and ok["path"] == str(folder.resolve())
    bad = post(setup_client, "/api/setup/validate", {"path": str(tmp_path / "new")}).json()
    assert not bad["ok"] and bad["can_create"] and bad["subfolders"] == []
    assert not (tmp_path / "new").exists()
    assert not post(setup_client, "/api/setup/validate", {"path": ""}).json()["ok"]


def test_setup_writes_the_setting_and_switches(setup_client, bare, tmp_path):
    folder = mk(tmp_path / "Chosen")
    r = post(setup_client, "/api/setup", {"archive_root": str(folder)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["archive_root"] == str(folder.resolve()) and body["restart_needed"] is False
    assert [f["exists"] for f in body["special_folders"]] == [False] * 4
    assert load_settings(bare).archive_root == folder.resolve()
    assert setup_client.switched == [1]
    assert list(folder.iterdir()) == []  # no special folders were created
    # a second call is refused, and nothing changed
    other = mk(tmp_path / "Other")
    r = post(setup_client, "/api/setup", {"archive_root": str(other)})
    assert r.status_code == 409
    assert load_settings(bare).archive_root == folder.resolve()


def test_setup_refuses_an_invalid_folder(setup_client, bare, tmp_path):
    r = post(setup_client, "/api/setup", {"archive_root": str(tmp_path / "missing")})
    assert r.status_code == 400 and "does not exist" in r.json()["error"]
    assert not setup.is_configured(bare)
    assert not (tmp_path / "missing").exists()


def test_setup_creates_a_folder_only_when_asked(setup_client, bare, tmp_path):
    target = tmp_path / "Brand New"
    assert post(setup_client, "/api/setup", {"archive_root": str(target)}).status_code == 400
    assert not target.exists()
    r = post(setup_client, "/api/setup", {"archive_root": str(target), "create": True})
    assert r.status_code == 200 and target.is_dir()
    deep = tmp_path / "no" / "parent"
    r = post(setup_client, "/api/setup", {"archive_root": str(deep), "create": True})
    assert r.status_code == 409  # already configured wins
    assert not deep.exists()


def test_setup_does_not_create_missing_parents(bare, tmp_path):
    api = create_setup_api(bare, None)
    with TestClient(api, base_url=BASE) as c:
        deep = tmp_path / "no" / "parent"
        r = post(c, "/api/setup", {"archive_root": str(deep), "create": True})
        assert r.status_code == 400 and not (tmp_path / "no").exists()


def test_setup_restart_needed_when_switching_fails(bare, tmp_path):
    def boom():
        raise RuntimeError("no")

    api = create_setup_api(bare, None, on_configured=boom)
    folder = mk(tmp_path / "F")
    with TestClient(api, base_url=BASE) as c:
        r = post(c, "/api/setup", {"archive_root": str(folder)})
    assert r.status_code == 200 and r.json()["restart_needed"] is True
    assert load_settings(bare).archive_root == folder.resolve()


def test_setup_routes_follow_the_local_only_rules(setup_client, tmp_path):
    body = {"archive_root": str(mk(tmp_path / "X"))}
    for url in ("/api/setup", "/api/setup/validate"):
        payload = body if url == "/api/setup" else {"path": body["archive_root"]}
        # another site's origin, no origin, and a form post are all refused
        r = setup_client.post(url, json=payload, headers={"Origin": "http://evil.example"})
        assert r.status_code == 403
        assert setup_client.post(url, json=payload).status_code == 403
        r = setup_client.post(url, content="a=b", headers={**ORIGIN, "Content-Type": "text/plain"})
        assert r.status_code == 415
    r = setup_client.get("/api/setup/candidates", headers={"Host": "evil.example"})
    assert r.status_code == 403
    r = setup_client.get("/api/status", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert not setup.is_configured(AppPaths(setup_client.app.state.setup.app_paths.data_dir))


def test_setup_rejects_unknown_fields(setup_client, tmp_path):
    r = post(setup_client, "/api/setup", {"archive_root": str(mk(tmp_path / "Y")), "origin": "x"})
    assert r.status_code == 422


def test_setup_endpoints_are_409_once_configured(app):
    with TestClient(create_api(app), base_url="http://127.0.0.1:8765") as c:
        origin = {"Origin": "http://127.0.0.1:8765"}
        assert c.get("/api/setup/candidates").status_code == 409
        assert c.post("/api/setup/validate", json={"path": "/"}, headers=origin).status_code == 409
        r = c.post("/api/setup", json={"archive_root": "/tmp"}, headers=origin)
        assert r.status_code == 409
        assert c.get("/api/status").json()["configured"] is True


def test_switchboard_swaps_the_target_but_keeps_the_lifespan(bare, app):
    first = create_setup_api(bare, None)
    board = Switchboard(first)
    seen = []

    async def other(scope, receive, send):
        seen.append(scope["type"])

    import asyncio

    board.target = other
    asyncio.run(board({"type": "http"}, None, None))
    assert seen == ["http"]

    async def first_app(scope, receive, send):
        seen.append("first:" + scope["type"])

    board.first = first_app
    asyncio.run(board({"type": "lifespan"}, None, None))
    assert seen[-1] == "first:lifespan"


def test_replacing_a_value_keeps_a_backup_and_the_first_write_needs_none(tmp_path):
    p = AppPaths(tmp_path / "d")
    p.ensure()
    a, b = mk(tmp_path / "a"), mk(tmp_path / "b")
    setup.write_archive_root(p, a)
    assert [f for f in p.config_dir.iterdir() if ".bak-" in f.name] == []
    setup.write_archive_root(p, b)
    backups = [f for f in p.config_dir.iterdir() if ".bak-" in f.name]
    assert len(backups) == 1 and setup.planned_line(a) in backups[0].read_text(encoding="utf-8")


def test_a_failed_write_puts_the_file_back(tmp_path, monkeypatch):
    p = AppPaths(tmp_path / "d")
    p.ensure()
    before = (p.config_dir / "settings.yaml").read_text(encoding="utf-8")
    # reading back fails -> the original bytes are restored
    monkeypatch.setattr(setup, "current_archive_root", lambda _p: None)
    with pytest.raises(OSError):
        setup.write_archive_root(p, mk(tmp_path / "a"))
    assert (p.config_dir / "settings.yaml").read_text(encoding="utf-8") == before


def test_setup_writes_the_chosen_countries(setup_client, bare, tmp_path):
    folder = mk(tmp_path / "Chosen")
    r = post(setup_client, "/api/setup", {"archive_root": str(folder), "countries": []})
    assert r.status_code == 200, r.text
    assert load_settings(bare).countries == []


def test_setup_without_countries_leaves_them_unset(setup_client, bare, tmp_path):
    folder = mk(tmp_path / "Chosen")
    assert post(setup_client, "/api/setup", {"archive_root": str(folder)}).status_code == 200
    assert load_settings(bare).countries is None


def test_setup_refuses_an_unknown_country(setup_client, bare, tmp_path):
    folder = mk(tmp_path / "Chosen")
    r = post(setup_client, "/api/setup", {"archive_root": str(folder), "countries": ["zz"]})
    assert r.status_code == 400 and "zz" in r.json()["error"]
    assert not setup.is_configured(bare)
