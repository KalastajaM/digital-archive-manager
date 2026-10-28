"""The system's folder dialog, for the "Choose…" buttons next to a folder path."""

from fastapi import APIRouter

from dam import folder_dialog
from dam.api.schemas import ChooseFolderIn, ChooseFolderOut

router = APIRouter(prefix="/api/system", tags=["system"])


@router.post("/choose-folder", response_model=ChooseFolderOut)
def choose_folder(body: ChooseFolderIn) -> dict:
    """Open the operating system's folder dialog on this computer and return the chosen
    absolute ``path``, or ``cancelled``, or why it is ``unavailable``. Never changes
    anything. A plain ``def``: it runs in the thread pool, so it does not block the server."""
    choice = folder_dialog.choose_folder(body.start)
    return {"path": choice.path, "cancelled": choice.cancelled, "unavailable": choice.unavailable}
