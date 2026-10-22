"""Export a collection as a zip or one PDF, and download the result."""

from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import FileResponse

from dam.api.deps import AppDep
from dam.api.schemas import ExportBody, ExportOut
from dam.collections import export as exports

router = APIRouter(prefix="/api", tags=["export"])

DOWNLOAD_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "sandbox; default-src 'none'",
}


@router.post("/collections/{collection_id}/export", response_model=ExportOut)
def export_collection(app: AppDep, collection_id: int, body: ExportBody):
    """Build the export now (bounded by the export deadline and size ceilings)."""
    c = app.collections.get(collection_id)
    return exports.export_collection(
        app.app_paths,
        app.paths,
        app.collections.expand(collection_id),
        c.name,
        body.format,
        body.confirm_large,
    )


@router.get(
    "/exports/{token}",
    response_class=FileResponse,
    responses={200: {"content": {"application/zip": {}, "application/pdf": {}}}},
)
def download(app: AppDep, token: str) -> FileResponse:
    """The built export as a download (exports are pruned after a day: then 404)."""
    path, media_type = exports.export_file(app.app_paths, token)
    disposition = f"attachment; filename*=UTF-8''{quote(path.name, safe='')}"
    return FileResponse(
        path,
        media_type=media_type,
        headers={**DOWNLOAD_HEADERS, "Content-Disposition": disposition},
    )
