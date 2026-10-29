"""Setup mode: the server ``dam serve`` runs while no archive folder is configured.

It answers ``/api/status`` with ``{"configured": false}`` and the ``/api/setup/*`` routes,
refuses everything else under ``/api`` (409), and serves the frontend (which then shows
its first-run screen). Choosing a folder writes ``archive_root`` and, through
``on_configured``, lets ``dam serve`` switch to the normal app without a restart.
"""

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI

from dam import layouts, setup
from dam.api.main import (
    ERROR_RESPONSES,
    add_error_handlers,
    mount_frontend,
)
from dam.api.routers import archives as archives_router
from dam.api.routers import dialogs as dialogs_router
from dam.api.routers import setup as setup_router
from dam.api.security import ArchiveGuardMiddleware, InternalErrorMiddleware, LocalOnlyMiddleware
from dam.api.setup_ctl import SetupMode
from dam.config import AppPaths
from dam.errors import Conflict
from dam.services.archives import ArchiveService, solo
from dam.services.layout import LayoutOutcome
from dam.snapshots import app_version


def create_setup_api(
    app_paths: AppPaths,
    static_dir: Path | None = None,
    on_configured: Callable[[], bool] | None = None,
    home: Path | None = None,
    on_layout: Callable[[layouts.Spec], LayoutOutcome] | None = None,
    archives: ArchiveService | None = None,
) -> FastAPI:
    """The setup-mode API. Bind it to 127.0.0.1 only (``dam serve`` does). It also
    answers ``/api/archives`` (adding or switching to another archive needs no folder)."""
    api = FastAPI(
        title="Digital Archive Manager (setup)",
        version=app_version(),
        responses=ERROR_RESPONSES,
        docs_url=None,
        redoc_url=None,
    )
    service = archives if archives is not None else solo(app_paths)
    api.state.archives = service
    api.state.setup = SetupMode(
        app_paths,
        on_configured,
        home,
        on_layout,
        guard=service.store.root_guard(service.current_id),
    )

    @api.get("/api/status", include_in_schema=False)
    def status() -> dict:
        return {"configured": False, **service.summary()}

    api.include_router(setup_router.router)
    api.include_router(archives_router.router)
    api.include_router(dialogs_router.router)

    @api.api_route(
        "/api/{rest:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    def not_yet(rest: str) -> dict:
        raise Conflict(setup.NOT_CONFIGURED)

    add_error_handlers(api)
    if static_dir is not None and (static_dir / "index.html").is_file():
        mount_frontend(api, static_dir)
    if archives is not None:
        api.add_middleware(ArchiveGuardMiddleware, archive_id=archives.current_id)
    api.add_middleware(InternalErrorMiddleware, logs_dir=app_paths.logs_dir)
    api.add_middleware(LocalOnlyMiddleware)
    return api
