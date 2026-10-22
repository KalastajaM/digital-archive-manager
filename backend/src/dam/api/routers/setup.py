"""First-run setup: choose the archive folder. Available only while none is configured.

In the normal app these routes answer 409; ``dam serve`` without an archive folder runs a
setup-mode server (``dam.api.setup_mode``) that answers them for real.
"""

from pathlib import Path

from fastapi import APIRouter

from dam.api.deps import SetupDep
from dam.api.schemas import (
    LayoutPreviewOut,
    SetupCandidatesOut,
    SetupIn,
    SetupLayoutPreviewIn,
    SetupOut,
    SetupPathIn,
    SetupValidateOut,
)

router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("/candidates", response_model=SetupCandidatesOut)
def candidates(setup: SetupDep) -> dict:
    """Cloud-drive and sync folders found on this computer, and the special folders the
    app expects inside the archive."""
    return setup.candidates()


@router.post("/validate", response_model=SetupValidateOut)
def validate(setup: SetupDep, body: SetupPathIn) -> dict:
    """Can this folder be the archive? Never changes anything."""
    return setup.validate(body.path)


@router.post("/layout-preview", response_model=LayoutPreviewOut)
def layout_preview(setup: SetupDep, body: SetupLayoutPreviewIn) -> dict:
    """The folders a new archive at this path would get. Never changes anything."""
    return setup.layout_preview(body.path, body.layout.model_dump())


@router.post("", response_model=SetupOut)
def configure(setup: SetupDep, body: SetupIn) -> dict:
    """Save the archive folder (``create``: make that one missing folder first). With a
    ``layout`` (start a new archive): also write the special folder names to the settings
    and make the layout's folders, as a journaled batch you can undo."""
    layout = body.layout.model_dump() if body.layout is not None else None
    return setup.apply(body.archive_root, body.create, layout)


__all__ = ["Path", "router"]
