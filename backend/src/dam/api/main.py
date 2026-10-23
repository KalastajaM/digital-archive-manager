"""Build the FastAPI application: routers, error mapping, security, static frontend."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from dam.api.routers import (
    activity,
    ai,
    browse,
    codes,
    collections,
    export,
    files,
    important,
    inbox,
    items,
    layout,
    marks,
    notes,
    ongoing,
    setup,
    system,
    tags,
    today,
    trays,
)
from dam.api.routers import archives as archives_router
from dam.api.schemas import ErrorBody
from dam.api.security import ArchiveGuardMiddleware, InternalErrorMiddleware, LocalOnlyMiddleware
from dam.app import App
from dam.core.paths import OutsideArchiveError
from dam.ops.model import GuardError, OpFailed
from dam.services.archives import ArchiveService
from dam.services.errors import (
    Conflict,
    InvalidRequest,
    NotFound,
    NotSupported,
    StalePreview,
    TooLarge,
)

# Known errors -> HTTP status; anything else is a 500 with a generic body.
ERROR_STATUS: dict[type[Exception], int] = {
    NotFound: 404,
    InvalidRequest: 400,
    TooLarge: 413,
    Conflict: 409,
    GuardError: 400,
    OutsideArchiveError: 400,
    OpFailed: 409,
    NotSupported: 501,
}

STATIC_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    ),
}

_ERROR = {"model": ErrorBody}
ERROR_RESPONSES = {
    400: _ERROR,
    403: _ERROR,
    404: _ERROR,
    409: _ERROR,
    413: _ERROR,
    415: _ERROR,
    422: _ERROR,
    500: _ERROR,
}


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _add_error_handlers(api: FastAPI) -> None:
    for exc_type, status in ERROR_STATUS.items():

        def handler(request: Request, exc: Exception, status: int = status) -> JSONResponse:
            return _error(status, str(exc))

        api.add_exception_handler(exc_type, handler)

    def stale_preview(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"error": str(exc), "code": "stale_preview"}, status_code=400)

    api.add_exception_handler(StalePreview, stale_preview)

    def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            {"error": str(exc.detail)}, status_code=exc.status_code, headers=exc.headers
        )

    def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        return _error(422, f"invalid request: {problems}")

    api.add_exception_handler(StarletteHTTPException, http_error)
    api.add_exception_handler(RequestValidationError, validation_error)


def _mount_frontend(api: FastAPI, static_dir: Path) -> None:
    """Serve the built frontend; unknown non-API paths get index.html (SPA routing)."""
    root = static_dir.resolve()
    index = root / "index.html"

    @api.get("/{full_path:path}", include_in_schema=False)
    def frontend(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise StarletteHTTPException(404, "Not Found")
        candidate = (root / full_path).resolve()
        if full_path and candidate.is_relative_to(root) and candidate.is_file():
            return FileResponse(candidate, headers=STATIC_HEADERS)
        return FileResponse(index, headers=STATIC_HEADERS)


def create_api(
    app: App, static_dir: Path | None = None, archives: ArchiveService | None = None
) -> FastAPI:
    """The HTTP API over ``app``. Bind it to 127.0.0.1 only (``dam serve`` does).
    ``archives``: the archives (profiles) service of the server running it; it also
    makes mutating requests naming another archive (``X-Dam-Archive``) fail with 409."""
    # No /docs or /redoc: they load unpinned CDN scripts onto the app's origin.
    api = FastAPI(
        title="Digital Archive Manager",
        version="0.1.0",
        responses=ERROR_RESPONSES,
        docs_url=None,
        redoc_url=None,
    )
    api.state.dam = app
    if archives is not None:
        api.state.archives = archives
    for module in (
        system,
        inbox,
        layout,
        files,
        browse,
        activity,
        today,
        trays,
        items,
        collections,
        marks,
        notes,
        ongoing,
        important,
        export,
        ai,
        codes,
        archives_router,
        setup,
        tags,
    ):
        api.include_router(module.router)
    api.include_router(collections.groups_router)  # /api/collection-groups
    _add_error_handlers(api)
    if static_dir is not None and (static_dir / "index.html").is_file():
        _mount_frontend(api, static_dir)
    if archives is not None:
        api.add_middleware(ArchiveGuardMiddleware, archive_id=archives.current_id)
    # Added last = outermost: the host/origin checks run before anything else.
    api.add_middleware(InternalErrorMiddleware, logs_dir=app.app_paths.logs_dir)
    api.add_middleware(LocalOnlyMiddleware)
    return api
