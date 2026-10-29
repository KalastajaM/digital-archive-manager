"""Rename the special folders (Inbox, Ongoing, Important, To Delete).

The rename is previewed (``dry_run``), journaled in Activity and undone from there
(``POST /api/activity/{batch}/undo`` also restores the settings, rules and stored paths).
It closes the archive, renames the folder through the operation layer, changes the
settings and stored paths, and opens the archive again, so it needs ``dam serve`` (409
otherwise), and it is refused (409) while a job runs or a disk is away.
"""

from dataclasses import asdict

from fastapi import APIRouter

from dam import special_folders
from dam.api.deps import AppDep, SnapshotsDep
from dam.api.schemas import SpecialFolderRenameIn, SpecialFolderRenameOut
from dam.errors import Conflict, NotFound

router = APIRouter(prefix="/api/special-folders", tags=["special-folders"])


@router.post("/{key}/rename", response_model=SpecialFolderRenameOut)
def rename_special_folder(
    app: AppDep, snaps: SnapshotsDep, key: str, body: SpecialFolderRenameIn
) -> dict:
    """Rename the folder ``key`` (inbox, ongoing, important or quarantine). The dry run
    answers with every place that changes, and why the rest stays. Applying renames the
    folder on its disk(s) and updates the settings, rules and stored paths; 400 for a
    name that cannot be used or a setting that cannot be edited safely."""
    if key not in special_folders.KEYS:
        raise NotFound(f"special folder {key}")
    with app.held():  # 409 while a job or a batch of changes runs; none starts meanwhile
        shown = special_folders.preview(
            app.app_paths, app.paths, app.engine, app.executor, key, body.name
        )
        if body.dry_run:
            return asdict(shown)
        if snaps.reopener is None:
            raise Conflict(
                "This window cannot rename a special folder. Start dam with `dam serve`."
            )
        done = snaps.reopener.close_and_reopen(
            lambda: special_folders.rename_folder(app.app_paths, key, body.name)
        )
        return {**asdict(shown), "batch_id": done.batch_id}
