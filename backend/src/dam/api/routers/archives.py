"""Archives (profiles): list, add, switch, rename/recolour, forget, show in the file manager.

Behind the same local-only protections as every route. Forgetting only edits the list of
archives: no data folder and no archive folder is ever deleted.
"""

from fastapi import APIRouter, Response

from dam.api.deps import ArchivesDep
from dam.api.schemas import (
    ArchiveAddIn,
    ArchiveForgetIn,
    ArchiveForgetOut,
    ArchiveOut,
    ArchiveRevealIn,
    ArchivesOut,
    ArchiveSwitchOut,
    ArchiveUpdateIn,
)

router = APIRouter(prefix="/api/archives", tags=["archives"])


@router.get("", response_model=ArchivesOut)
def list_archives(archives: ArchivesDep) -> dict:
    return archives.overview()


@router.post("", response_model=ArchiveOut)
def add_archive(archives: ArchivesDep, body: ArchiveAddIn) -> dict:
    """Add an archive (not opened yet). With ``demo_folder``: builds the demo archive
    in that new or empty folder."""
    return archives.add(body.name, body.color, body.demo_folder)


@router.post("/{archive_id}/switch", response_model=ArchiveSwitchOut)
def switch_archive(archives: ArchivesDep, archive_id: str) -> dict:
    """Close this archive's background work and open the other one in this server.
    409 when another dam process already serves it."""
    outcome = archives.switch(archive_id)
    return {
        "archive": {
            **archives.describe(outcome.profile),
            "current": True,  # this process serves it now (not "another window")
            "in_use_elsewhere": False,
            "port": None,
        },
        "restart_needed": outcome.restart_needed,
    }


@router.patch("/{archive_id}", response_model=ArchiveOut)
def update_archive(archives: ArchivesDep, archive_id: str, body: ArchiveUpdateIn) -> dict:
    return archives.update(archive_id, body.name, body.color)


@router.post("/{archive_id}/forget", response_model=ArchiveForgetOut)
def forget_archive(archives: ArchivesDep, archive_id: str, body: ArchiveForgetIn) -> dict:
    """Remove the archive from the list. Nothing is deleted; the response says where
    its folders are."""
    return archives.forget(archive_id, body.switch_to)


@router.post("/{archive_id}/reveal", status_code=204, response_class=Response)
def reveal_archive(archives: ArchivesDep, archive_id: str, body: ArchiveRevealIn) -> Response:
    """Show its data folder, archive folder or an extra archive folder in Finder /
    Explorer."""
    archives.reveal(archive_id, body.what, body.label)
    return Response(status_code=204)
