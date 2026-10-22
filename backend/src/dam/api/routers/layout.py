"""Start an archive from scratch (layouts) and make folders (New folder).

User-initiated only. Both go through the journaled operation layer: previewed first,
undoable from Activity (undo removes only folders that are still empty).
"""

from fastapi import APIRouter, Response

from dam import layouts
from dam.api.deps import UI_ORIGIN, AppDep
from dam.api.schemas import (
    BatchResultOut,
    FolderPathIn,
    LayoutIn,
    LayoutPreviewOut,
    LayoutResultOut,
    LayoutTemplatesOut,
    NewFolderIn,
    ResolvedOpOut,
)
from dam.services.layout import LayoutService

router = APIRouter(prefix="/api", tags=["layout"])


def _spec(service: LayoutService, body: LayoutIn) -> layouts.Spec:
    # the special folders are the configured ones; ``body.special`` only matters in
    # first-run setup, before the settings exist
    return service.spec(body.template, body.numbered, [(r.key, r.name) for r in body.folders])


@router.get("/layout/templates", response_model=LayoutTemplatesOut)
def templates(app: AppDep) -> dict:
    """The starter layouts, and the special folders with a one-line purpose each."""
    from dam import setup

    return {
        "templates": [
            {
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "folders": [{"key": r.key, "name": r.name} for r in t.folders],
            }
            for t in app.layout.templates()
        ],
        "special_folders": setup.special_folders(app.settings.special_folders),
    }


@router.post("/layout/preview", response_model=LayoutPreviewOut)
def preview(app: AppDep, body: LayoutIn):
    """Every folder of the layout and which of them would be made. Changes nothing."""
    return app.layout.preview(_spec(app.layout, body), origin=UI_ORIGIN)


@router.post("/layout", response_model=LayoutResultOut)
def create(app: AppDep, body: LayoutIn):
    """Make the missing folders as one journaled batch (Activity: "Created the archive
    layout"), then write example rules if the archive has none of its own."""
    outcome = app.layout.apply(_spec(app.layout, body), origin=UI_ORIGIN)
    return {
        "batch": outcome.batch,
        "created": outcome.created,
        "rules_written": outcome.rules_written,
        "rule_ids": outcome.rule_ids,
        "rules_error": outcome.rules_error,
    }


@router.post("/folders/new/preview", response_model=list[ResolvedOpOut])
def new_folder_preview(app: AppDep, body: NewFolderIn) -> list:
    return app.layout.new_folder_preview(body.parent, body.name, origin=UI_ORIGIN)


@router.post("/folders/new", response_model=BatchResultOut)
def new_folder(app: AppDep, body: NewFolderIn):
    """Make one folder (top level when ``parent`` is empty): journaled, undoable."""
    return app.layout.new_folder(body.parent, body.name, origin=UI_ORIGIN)


@router.post("/folders/reveal", status_code=204, response_class=Response)
def reveal_folder(app: AppDep, body: FolderPathIn) -> Response:
    """Show an archive folder in Finder / Explorer / the file manager."""
    app.launch.reveal_folder(body.path)
    return Response(status_code=204)
