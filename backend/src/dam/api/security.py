"""ASGI middleware: local-only access and the generic 500.

The API serves medical, financial and ID documents on 127.0.0.1. Other websites open in
the user's browser must not be able to read or change anything:

* DNS rebinding: a request whose ``Host`` is not exactly ``127.0.0.1:<port>`` or
  ``localhost:<port>`` (the port the server is bound to) is refused.
* Cross-site requests: ``Sec-Fetch-Site: cross-site`` is refused for every method. A
  mutating request (anything but GET/HEAD) must carry a local ``Origin``, or, without
  ``Origin``, ``Sec-Fetch-Site: same-origin``/``none``. Browsers always send at least one
  of these, so a form POST from another site is refused; non-browser clients (curl)
  must send ``Origin`` themselves to mutate. GETs without these headers are allowed.
* A POST must be ``Content-Type: application/json``, which a plain cross-site form can
  never send. The exceptions are the file uploads (``POST /api/inbox/upload`` and
  ``POST /api/snapshots/import``, body ``application/octet-stream``): a type a plain form
  cannot send either, and they pass the same host and origin checks as every other
  mutating request.

``DAM_DEV_ORIGIN`` (e.g. ``http://localhost:5173`` for the Vite dev server) adds one more
accepted origin; it is off unless set, and only ``http://localhost:<port>`` or
``http://127.0.0.1:<port>`` is accepted (anything else is ignored with a warning). It needs
the Vite dev server to proxy ``/api`` with ``changeOrigin: true``: the proxy then sends
``Host: 127.0.0.1:<port>`` (which the host check requires) and keeps the browser's
``Origin``, which this setting allows.

Every response gets ``X-Content-Type-Options: nosniff``.
"""

import json
import logging
import os
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

from dam.locks import _TOKENS, UNLOCK_HEADER, parse_tokens
from dam.logging_setup import log_internal_error

log = logging.getLogger(__name__)

Scope = dict
Receive = Callable[[], Awaitable[dict]]
Send = Callable[[dict], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

SAFE_METHODS = frozenset({"GET", "HEAD"})
UPLOAD_PATHS = frozenset({"/api/inbox/upload", "/api/snapshots/import"})
LOCAL_FETCH_SITES = frozenset({"same-origin", "none"})
DEV_ORIGIN_ENV = "DAM_DEV_ORIGIN"
_DEV_ORIGIN = re.compile(r"http://(localhost|127\.0\.0\.1):[0-9]{1,5}")
_NOSNIFF = (b"x-content-type-options", b"nosniff")


def dev_origin() -> str | None:
    """The validated ``DAM_DEV_ORIGIN``, or None (unset or invalid: ignored with a warning)."""
    value = os.environ.get(DEV_ORIGIN_ENV)
    if not value:
        return None
    if not _DEV_ORIGIN.fullmatch(value):
        log.warning(
            "ignoring %s=%r: only http://localhost:<port> or http://127.0.0.1:<port> is allowed",
            DEV_ORIGIN_ENV,
            value,
        )
        return None
    return value


async def send_json(send: Send, status: int, body: dict) -> None:
    payload = json.dumps(body).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode()),
                _NOSNIFF,
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})


def _headers(scope: Scope) -> dict[str, str]:
    # Duplicate headers: the last one wins; latin-1 keeps every byte decodable.
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}


class LocalOnlyMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.dev_origin = dev_origin()

    def refusal(self, scope: Scope) -> tuple[int, str] | None:
        """Why the request is refused (status, message), or None if it may pass."""
        server = scope.get("server")
        if not server or server[1] is None:
            return 403, "forbidden: unknown server address"
        port = server[1]
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        headers = _headers(scope)
        if headers.get("host") not in hosts:
            return 403, "forbidden: host not allowed"
        site = headers.get("sec-fetch-site")
        if site == "cross-site":
            return 403, "forbidden: cross-site request"
        method = scope["method"]
        if method in SAFE_METHODS:
            return None
        origins = {f"http://{h}" for h in hosts}
        if self.dev_origin:
            origins.add(self.dev_origin)
        origin = headers.get("origin")
        if origin is not None:
            if origin not in origins:
                return 403, "forbidden: origin not allowed"
        elif site not in LOCAL_FETCH_SITES:
            return 403, "forbidden: request origin unknown"
        if method == "POST":
            media_type = headers.get("content-type", "").split(";")[0].strip().lower()
            is_upload = (
                media_type == "application/octet-stream" and scope.get("path") in UPLOAD_PATHS
            )
            if media_type != "application/json" and not is_upload:
                return 415, "unsupported media type: expected application/json"
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            refused = self.refusal(scope)
            if refused is not None:
                await send_json(send, refused[0], {"error": refused[1]})
                return

            async def nosniff_send(message: dict) -> None:
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    if not any(k.lower() == _NOSNIFF[0] for k, _ in headers):
                        headers.append(_NOSNIFF)
                    message = {**message, "headers": headers}
                await send(message)

            await self.app(scope, receive, nosniff_send)
        elif scope["type"] == "websocket":
            return  # no websockets: drop the connection without accepting it
        else:
            await self.app(scope, receive, send)


ARCHIVE_HEADER = "x-dam-archive"
ARCHIVE_PREFIX = "/api/archives"
STALE_WINDOW = (
    "This window shows a different archive than the one that is open now. "
    "Reload the page, then try again."
)


class ArchiveGuardMiddleware:
    """A mutating request names the archive the page believes is open (``X-Dam-Archive``);
    one that names another archive than this server shows is refused with 409. A stale
    browser tab can thereby never change the wrong archive after a switch. Requests
    without the header (curl, scripts) pass, and so do the ``/api/archives`` routes,
    which name their target explicitly."""

    def __init__(self, app: ASGIApp, archive_id: str) -> None:
        self.app = app
        self.archive_id = archive_id

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] not in SAFE_METHODS:
            path = scope.get("path", "")
            named = _headers(scope).get(ARCHIVE_HEADER)
            on_registry = path == ARCHIVE_PREFIX or path.startswith(ARCHIVE_PREFIX + "/")
            if named is not None and named != self.archive_id and not on_registry:
                await send_json(send, 409, {"error": STALE_WINDOW})
                return
        await self.app(scope, receive, send)


class UnlockTokenMiddleware:
    """Put the page's unlock tokens (``X-Dam-Unlock``) where the operation layer finds
    them for this request. A token only counts if the server issued it and it is still
    live (``dam.locks``); the header itself unlocks nothing."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        reset = _TOKENS.set(parse_tokens(_headers(scope).get(UNLOCK_HEADER)))
        try:
            await self.app(scope, receive, send)
        finally:
            _TOKENS.reset(reset)


class InternalErrorMiddleware:
    """Turn any unhandled exception into ``500 {"error": "internal error"}``.

    The traceback goes to the Python log and ``<logs_dir>/dam.log``, never the response.
    If the response has already started, the exception is re-raised (the server then
    aborts the connection) since a second response cannot be sent.
    """

    def __init__(self, app: ASGIApp, logs_dir: Path) -> None:
        self.app = app
        self.logs_dir = logs_dir

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: dict) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            where = f"{scope.get('method')} {scope.get('path')}"
            log_path = log_internal_error(self.logs_dir, f"internal error in {where}")
            log.error("internal error in %s (traceback in %s)", where, log_path)
            if started:
                raise
            await send_json(send, 500, {"error": "internal error"})
