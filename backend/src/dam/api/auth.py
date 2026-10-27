"""Sign-in to the local API: only the owner's browser and the ``dam`` command line.

The host and origin checks in ``dam.api.security`` keep other web pages out, but not
other programs on the same machine: any local process can reach ``127.0.0.1``. So every
request for archive data or a change (everything under ``/api``) must carry a secret
token, either as the cookie ``dam_auth_<port>`` or as the header ``X-Dam-Token``.

* The token is random (``secrets.token_urlsafe(32)``) and lives in ``<base>/api-token``
  (``<base>``: the folder with ``archives.yaml``, so one token serves every archive a
  server can switch to). It is made on first use with mode 0600 on POSIX; on Windows
  the file inherits the user profile folder's permissions, which only the user (and
  administrators) can read. It is never logged.
* ``dam serve`` (and ``dam open``) open ``http://127.0.0.1:<port>/auth?t=<token>``.
  ``/auth`` checks the token in constant time, sets the cookie (HttpOnly,
  SameSite=Strict, Path=/, one year) and redirects (303) to ``/``, so the token leaves
  the address bar. The cookie name carries the port: cookies are shared by every port
  of one host, and a demo server on another port with another token must not sign the
  owner's own app out.
* With ``DAM_DEV_ORIGIN`` set (the Vite dev server), the link names the dev origin's
  host and ``/auth`` redirects to the dev origin: the cookie is then on that host, and
  the browser sends it with the dev server's requests, which Vite proxies to the API.
* The start page and its assets stay open: a browser that is not signed in loads the
  page, gets 401 from the API and shows how to sign in.
"""

import hmac
import logging
import os
import re
import secrets
import stat
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from starlette.requests import cookie_parser

from dam.api.security import ASGIApp, Receive, Scope, Send, dev_origin, send_json
from dam.core.fs import open_nofollow

TOKEN_NAME = "api-token"
COOKIE_PREFIX = "dam_auth_"
TOKEN_HEADER = "x-dam-token"
AUTH_PATH = "/auth"
COOKIE_MAX_AGE = 365 * 24 * 3600
NOT_SIGNED_IN = (
    "This page is not signed in to dam. Open dam with `dam serve` (or `dam open` if it is "
    "already running) and it signs this browser in."
)
BAD_LINK = (
    "This sign-in link is not valid for this dam. Open dam with `dam serve` (or `dam open` "
    "if it is already running) to get a new one.\n"
)
_TOKEN = re.compile(r"[A-Za-z0-9_-]{32,128}")
_CREATE_WAIT_S = 1.0  # another process that just created the file is writing it
_NOSNIFF = (b"x-content-type-options", b"nosniff")


def token_path(base: Path) -> Path:
    return Path(base) / TOKEN_NAME


def _read(path: Path) -> str | None:
    try:
        fd = open_nofollow(path, os.O_RDONLY)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as fh:
        value = fh.read(256).decode("ascii", "replace").strip()
    return value if _TOKEN.fullmatch(value) else ""


def _write(path: Path, flags: int) -> str:
    token = secrets.token_urlsafe(32)
    fd = open_nofollow(path, os.O_WRONLY | flags, 0o600)
    try:
        os.write(fd, token.encode("ascii"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return token


def _tighten(path: Path) -> None:
    """A token file readable by others (copied in by hand, say) is made 0600 again."""
    if sys.platform == "win32":
        return
    mode = path.lstat().st_mode
    if stat.S_IMODE(mode) & 0o077:
        os.chmod(path, 0o600)


def read_token(base: Path) -> str | None:
    """The token in ``<base>/api-token``, or None when there is none (yet) or it is not
    a valid token. Writes nothing."""
    return _read(token_path(base)) or None


def load_token(base: Path) -> str:
    """The token in ``<base>/api-token``, made (0600) on first use. A file that holds no
    valid token is written again in place."""
    path = token_path(base)
    Path(base).mkdir(parents=True, exist_ok=True)
    try:
        token = _write(path, os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        deadline = time.monotonic() + _CREATE_WAIT_S
        while True:
            value = _read(path)
            if value:
                token = value
                break
            if time.monotonic() >= deadline:
                token = _write(path, os.O_TRUNC)
                break
            time.sleep(0.05)
    _tighten(path)
    return token


def cookie_name(port: int) -> str:
    return f"{COOKIE_PREFIX}{port}"


def auth_url(port: int, token: str) -> str:
    """The sign-in link for the server on ``port``."""
    host = "127.0.0.1"
    dev = dev_origin()
    if dev:
        host = urlsplit(dev).hostname or host
    return f"http://{host}:{port}{AUTH_PATH}?t={token}"


def _same(given: str | None, token: str) -> bool:
    if not given:
        return False
    return hmac.compare_digest(given.encode("utf-8", "replace"), token.encode("ascii"))


def _protected(path: str) -> bool:
    """Everything under /api (whatever the case or extra slashes)."""
    first = path.lstrip("/").split("/", 1)[0].lower()
    return first == "api"


def _headers(scope: Scope) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}


class ApiTokenMiddleware:
    """Outermost layer of ``dam serve``: ``/auth`` signs a browser in; every ``/api``
    request needs the token (cookie or ``X-Dam-Token``), else 401. The other routes
    (the start page and its assets) pass to the app, whose own checks still run."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token
        self.dev_origin = dev_origin()

    def signed_in(self, scope: Scope, headers: dict[str, str]) -> bool:
        if _same(headers.get(TOKEN_HEADER), self.token):
            return True
        port = (scope.get("server") or (None, None))[1]
        if port is None:
            return False
        cookies = cookie_parser(headers.get("cookie", ""))
        return _same(cookies.get(cookie_name(port)), self.token)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path == AUTH_PATH:
            await self.sign_in(scope, send)
            return
        if _protected(path) and not self.signed_in(scope, _headers(scope)):
            await send_json(send, 401, {"error": NOT_SIGNED_IN, "code": "not_signed_in"})
            return
        await self.app(scope, receive, send)

    async def sign_in(self, scope: Scope, send: Send) -> None:
        server = scope.get("server") or (None, None)
        port = server[1]
        headers = _headers(scope)
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port is None or headers.get("host") not in hosts:
            await send_json(send, 403, {"error": "forbidden: host not allowed"})
            return
        if scope["method"] not in ("GET", "HEAD"):
            await send_json(send, 405, {"error": "method not allowed"})
            return
        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        given = (query.get("t") or [None])[0]
        if not _same(given, self.token):
            await _send(send, 401, [(b"content-type", b"text/plain; charset=utf-8")], BAD_LINK)
            return
        cookie = (
            f"{cookie_name(port)}={self.token}; HttpOnly; SameSite=Strict; Path=/; "
            f"Max-Age={COOKIE_MAX_AGE}"
        )
        target = f"{self.dev_origin}/" if self.dev_origin else "/"
        await _send(
            send,
            303,
            [
                (b"location", target.encode("latin-1")),
                (b"set-cookie", cookie.encode("latin-1")),
                (b"cache-control", b"no-store"),
                (b"referrer-policy", b"no-referrer"),
            ],
            "",
        )


async def _send(send: Send, status: int, headers: list[tuple[bytes, bytes]], text: str) -> None:
    body = text.encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [*headers, (b"content-length", str(len(body)).encode()), _NOSNIFF],
        }
    )
    await send({"type": "http.response.body", "body": body})


_SECRET_QUERY = re.compile(r"([?&]t=)[^&\s]*")


class RedactTokenFilter(logging.Filter):
    """Keep the sign-in token out of uvicorn's access log (``GET /auth?t=...``)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                _SECRET_QUERY.sub(r"\1<hidden>", a) if isinstance(a, str) else a
                for a in record.args
            )
        elif isinstance(record.msg, str):
            record.msg = _SECRET_QUERY.sub(r"\1<hidden>", record.msg)
        return True


_FILTER = RedactTokenFilter()


def hide_token_in_logs() -> None:
    """Install the filter on uvicorn's access log (once)."""
    access = logging.getLogger("uvicorn.access")
    if _FILTER not in access.filters:
        access.addFilter(_FILTER)
