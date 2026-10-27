"""Only a signed-in browser (or a client with the token) can use the local API.

``dam serve`` wraps everything it serves in ``ApiTokenMiddleware``; ``create_api`` alone
(the other API tests) has no sign-in, so those tests need no token.
"""

import hmac
import logging
import os
import stat
import sys

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import dam.api.auth as auth
import dam.serve as serve_mod
from conftest import FakeArchive
from dam import setup
from dam.api import create_api
from dam.api.auth import ApiTokenMiddleware, load_token, read_token
from dam.api.setup_mode import create_setup_api
from dam.cli import main as cli_main
from dam.config import AppPaths
from dam.profiles import ProfileStore, ServeLock
from dam.serve import Host, Switchboard

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
ORIGIN = {"Origin": BASE}
COOKIE = f"dam_auth_{PORT}"
INBOX = "##. Organize"
TOKEN = "t" * 43

runner = CliRunner()


@pytest.fixture
def static_dir(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>dam</title>", encoding="utf-8")
    (dist / "assets" / "app-abc.js").write_text("console.log(1)", encoding="utf-8")
    return dist


@pytest.fixture
def guarded(app, fake_archive, static_dir):
    """The app as ``dam serve`` serves it, with no cookie in the client."""
    fake_archive.add(f"{INBOX}/a.pdf", content=b"%PDF-secret", drive_id="id-1")
    app.scan()
    with TestClient(ApiTokenMiddleware(create_api(app, static_dir), TOKEN), base_url=BASE) as c:
        yield c


def signed_in(client: TestClient) -> TestClient:
    client.cookies.set(COOKIE, TOKEN, domain="127.0.0.1")
    return client


# -- what needs the token ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "kw"),
    [
        ("GET", "/api/status", {}),
        ("GET", "/api/files/id-1/raw", {}),
        ("GET", "/api/files/id-1/page/1.png?w=400", {}),
        ("GET", "/api/snapshots", {}),
        ("POST", "/api/files/id-1/unlock", {"json": {"mode": "now"}}),
        ("POST", "/api/snapshots/import", {"content": b"PK", "type": "octet"}),
        ("GET", "/API/status", {}),
    ],
)
def test_without_the_token_every_api_route_is_refused(guarded, method, path, kw):
    headers = dict(ORIGIN)
    if kw.pop("type", None) == "octet":
        headers["Content-Type"] = "application/octet-stream"
    r = guarded.request(method, path, headers=headers, **kw)
    assert r.status_code == 401
    assert r.json() == {"error": auth.NOT_SIGNED_IN, "code": "not_signed_in"}
    assert b"secret" not in r.content


def test_the_cookie_signs_in(guarded):
    c = signed_in(guarded)
    assert c.get("/api/status").status_code == 200
    raw = c.get("/api/files/id-1/raw")
    assert raw.status_code == 200 and raw.content == b"%PDF-secret"
    # the other checks still run behind the sign-in: a POST needs a local Origin
    assert c.post("/api/files/id-1/lock", json={}).status_code == 403


def test_the_header_signs_in(guarded):
    r = guarded.get("/api/files/id-1/raw", headers={"X-Dam-Token": TOKEN})
    assert r.status_code == 200 and r.content == b"%PDF-secret"
    r = guarded.post(
        "/api/snapshots/import",
        content=b"not a zip",
        headers={**ORIGIN, "X-Dam-Token": TOKEN, "Content-Type": "application/octet-stream"},
    )
    assert r.status_code not in (401, 403, 415)  # it reached the import itself


@pytest.mark.parametrize("wrong", ["", "x", TOKEN[:-1], TOKEN + "x", TOKEN.upper(), "t%C3%B6t"])
def test_a_wrong_token_is_refused(guarded, wrong):
    assert guarded.get("/api/status", headers={"X-Dam-Token": wrong}).status_code == 401
    guarded.cookies.set(COOKIE, wrong, domain="127.0.0.1")
    assert guarded.get("/api/status").status_code == 401


def test_the_cookie_of_another_port_does_not_count(guarded):
    guarded.cookies.set("dam_auth_8766", TOKEN, domain="127.0.0.1")
    assert guarded.get("/api/status").status_code == 401


def test_tokens_are_compared_in_constant_time(guarded, monkeypatch):
    calls = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(auth.hmac, "compare_digest", spy)
    guarded.get("/api/status", headers={"X-Dam-Token": "nope"})
    assert calls and calls[-1][1] == TOKEN.encode()


def test_the_start_page_and_its_assets_need_no_token(guarded):
    for path in ("/", "/index.html", "/browse", "/assets/app-abc.js"):
        r = guarded.get(path)
        assert r.status_code == 200, path
    assert "dam" in guarded.get("/").text


# -- /auth ------------------------------------------------------------------------------


def test_auth_sets_the_cookie_and_redirects_to_the_start_page(guarded):
    r = guarded.get(f"/auth?t={TOKEN}", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    cookie = r.headers["set-cookie"]
    parts = [p.strip() for p in cookie.split(";")]
    assert parts[0] == f"{COOKIE}={TOKEN}"
    assert {"HttpOnly", "SameSite=Strict", "Path=/", "Max-Age=31536000"} <= set(parts)
    assert r.headers["cache-control"] == "no-store"
    # the client now holds the cookie: the API answers
    assert guarded.get("/api/status").status_code == 200


def test_auth_with_a_wrong_token_sets_nothing(guarded):
    r = guarded.get("/auth?t=wrong", follow_redirects=False)
    assert r.status_code == 401 and "set-cookie" not in r.headers
    assert "dam open" in r.text
    assert guarded.get("/auth", follow_redirects=False).status_code == 401


def test_auth_checks_the_host(app, static_dir):
    api = ApiTokenMiddleware(create_api(app, static_dir), TOKEN)
    with TestClient(api, base_url=f"http://evil.example:{PORT}") as c:
        r = c.get(f"/auth?t={TOKEN}", follow_redirects=False)
    assert r.status_code == 403 and "set-cookie" not in r.headers


def test_in_dev_mode_auth_returns_to_the_dev_server(app, static_dir, monkeypatch):
    monkeypatch.setenv("DAM_DEV_ORIGIN", "http://localhost:5173")
    api = ApiTokenMiddleware(create_api(app, static_dir), TOKEN)
    with TestClient(api, base_url=f"http://localhost:{PORT}") as c:
        r = c.get(f"/auth?t={TOKEN}", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "http://localhost:5173/"
    assert auth.auth_url(PORT, TOKEN) == f"http://localhost:{PORT}/auth?t={TOKEN}"


def test_the_access_log_never_shows_the_token():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", f"/auth?t={TOKEN}", "1.1", 303),
        None,
    )
    auth.RedactTokenFilter().filter(record)
    assert TOKEN not in record.getMessage() and "/auth?t=<hidden>" in record.getMessage()


# -- the token file ---------------------------------------------------------------------


def test_the_token_is_made_once_and_kept(tmp_path):
    base = tmp_path / "base"
    assert read_token(base) is None
    first = load_token(base)
    assert len(first) >= 43 and read_token(base) == first
    assert load_token(base) == first  # a restart reads the same token
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(base / "api-token").st_mode) == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_a_token_file_others_can_read_is_made_private(tmp_path):
    token = load_token(tmp_path)
    os.chmod(tmp_path / "api-token", 0o644)
    assert load_token(tmp_path) == token
    assert stat.S_IMODE(os.stat(tmp_path / "api-token").st_mode) == 0o600


def test_a_broken_token_file_is_written_again(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "_CREATE_WAIT_S", 0.0)
    (tmp_path / "api-token").write_bytes(b"short")
    assert read_token(tmp_path) is None
    token = load_token(tmp_path)
    assert read_token(tmp_path) == token


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Two archives in one server, wrapped as ``dam serve`` wraps it."""
    monkeypatch.setattr(serve_mod, "start_background", lambda app: None)
    base = tmp_path / "base"
    paths = AppPaths(base)
    paths.ensure()
    arch_a, arch_b = FakeArchive(tmp_path / "archA"), FakeArchive(tmp_path / "archB")
    setup.write_archive_root(paths, arch_a.root)
    store = ProfileStore(base)
    store.load(persist=True)
    test = store.add("Test")
    setup.write_archive_root(test.paths, arch_b.root)
    host = Host(store, None, PORT)
    main = store.active()
    lock = ServeLock(main.data_dir)
    lock.acquire(PORT)
    host.profile_id, host.first_lock = main.id, lock
    opened = host._open(main, lock)
    opened.owns_app = False
    board = Switchboard(opened.api)
    host.attach(board, opened)
    token = load_token(serve_mod._token_base(host, main.data_dir))
    client = TestClient(ApiTokenMiddleware(board, token), base_url=BASE)
    yield host, client, store, token
    client.close()
    host.shutdown()
    opened.app.close()


def test_one_token_serves_every_archive_of_the_server(world):
    host, c, store, token = world
    assert token == read_token(store.base)
    assert not (store.find("test").data_dir / "api-token").exists()
    c.cookies.set(COOKIE, token, domain="127.0.0.1")
    r = c.post("/api/archives/test/switch", json={}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert c.get("/api/status").json()["archive"]["id"] == "test"
    c.cookies.clear()
    assert c.get("/api/status").status_code == 401


def test_setup_mode_needs_the_token_too(tmp_path, static_dir):
    paths = AppPaths(tmp_path / "fresh")
    paths.ensure()
    api = ApiTokenMiddleware(create_setup_api(paths, static_dir), TOKEN)
    with TestClient(api, base_url=BASE) as c:
        assert c.get("/api/status").status_code == 401
        assert c.get("/").status_code == 200
        c.get(f"/auth?t={TOKEN}")
        assert c.get("/api/status").json()["configured"] is False


# -- dam serve and dam open -------------------------------------------------------------


class RecordingServer:
    configs: list

    def __init__(self, config):
        self.configs.append(config)
        self.started = False
        self.should_exit = False

    def run(self):
        return None


@pytest.fixture
def recording(monkeypatch):
    RecordingServer.configs = []
    monkeypatch.setattr(serve_mod, "DamServer", RecordingServer)
    monkeypatch.setattr(serve_mod, "start_background", lambda app: None)
    return RecordingServer.configs


def test_dam_serve_wraps_the_whole_server_in_the_sign_in(app_paths, recording):
    r = runner.invoke(
        cli_main.app,
        ["--data-dir", str(app_paths.data_dir), "serve", "--port", "9131", "--no-open"],
    )
    assert r.exit_code == 0, r.output
    [config] = recording
    assert isinstance(config.app, ApiTokenMiddleware)
    token = read_token(app_paths.data_dir)
    assert config.app.token == token
    # --no-open prints the sign-in link once
    assert r.stdout.count(f"http://127.0.0.1:9131/auth?t={token}") == 1


def test_setup_mode_serve_is_wrapped_and_prints_the_link(tmp_path, recording):
    data = tmp_path / "unset"
    r = runner.invoke(
        cli_main.app, ["--data-dir", str(data), "serve", "--port", "9132", "--no-open"]
    )
    if "frontend not built" in r.stderr:
        pytest.skip("setup mode needs the built frontend")
    assert r.exit_code == 0, r.output
    [config] = recording
    assert isinstance(config.app, ApiTokenMiddleware)
    assert f"http://127.0.0.1:9132/auth?t={read_token(data)}" in r.stdout


def test_dam_open_prints_the_link_of_the_running_server(app_paths):
    token = load_token(app_paths.data_dir)
    lock = ServeLock(app_paths.data_dir)
    lock.acquire()
    lock.publish(8799)
    try:
        r = runner.invoke(cli_main.app, ["--data-dir", str(app_paths.data_dir), "open", "--print"])
    finally:
        lock.release()
    assert r.exit_code == 0, r.output
    assert r.stdout.strip() == f"http://127.0.0.1:8799/auth?t={token}"


def test_dam_open_opens_the_browser(app_paths, monkeypatch):
    load_token(app_paths.data_dir)
    opened = []
    import webbrowser

    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)
    lock = ServeLock(app_paths.data_dir)
    lock.acquire()
    lock.publish(8799)
    try:
        r = runner.invoke(cli_main.app, ["--data-dir", str(app_paths.data_dir), "open"])
    finally:
        lock.release()
    assert r.exit_code == 0, r.output
    assert opened == [f"http://127.0.0.1:8799/auth?t={read_token(app_paths.data_dir)}"]
    assert r.stdout == ""  # the token is not printed when the browser opened


def test_dam_open_without_a_server_says_so(app_paths):
    load_token(app_paths.data_dir)
    r = runner.invoke(cli_main.app, ["--data-dir", str(app_paths.data_dir), "open", "--print"])
    assert r.exit_code == 1 and "dam serve" in r.stderr


def test_dam_open_ignores_a_command_holding_the_lock(app_paths):
    load_token(app_paths.data_dir)
    lock = ServeLock(app_paths.data_dir)
    lock.acquire(command="dam scan")
    try:
        r = runner.invoke(cli_main.app, ["--data-dir", str(app_paths.data_dir), "open", "--print"])
    finally:
        lock.release()
    assert r.exit_code == 1


def test_every_api_route_is_under_api(app):
    """Raw files, page images, exports, sticker sheets and snapshot downloads are all
    under /api, which the sign-in covers (the rest is the static frontend)."""
    paths = create_api(app).openapi()["paths"]
    assert paths and all(p.startswith("/api/") for p in paths)


@pytest.mark.parametrize(
    ("path", "protected"),
    [
        ("/api", True),
        ("/api/status", True),
        ("//api/status", True),
        ("/API/files/x/raw", True),
        ("/", False),
        ("/apiary", False),
        ("/assets/app.js", False),
        ("/auth", False),
    ],
)
def test_what_counts_as_api(path, protected):
    assert auth._protected(path) is protected
