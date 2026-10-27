"""The filing codes' inbox folders (``<inbox>/To pay``): which are missing, which inbox
subfolders belong to no code, and making the missing ones.

Only read here; the folders are made by the operation layer (a ``Plan.new_folders``
plan with ``inbox_folders``), previewed first and undoable from Activity (undo removes
them again while they are still empty).
"""

import logging
import os
from typing import TYPE_CHECKING

from dam.core.text import fold_name
from dam.errors import InvalidRequest
from dam.ops.guards import join
from dam.ops.model import BatchResult, Op, OpKind, Plan, ResolvedOp
from dam.services import check_origin

if TYPE_CHECKING:
    from dam.app import App

log = logging.getLogger(__name__)


def _inbox_subfolders(app: "App") -> list[str]:
    """Names of the real folders (no links) directly in the inbox; ``[]`` if the inbox
    cannot be read."""
    try:
        with os.scandir(app.paths.abs(app.settings.special_folders.inbox)) as entries:
            return [e.name for e in entries if e.is_dir(follow_symlinks=False)]
    except (OSError, ValueError):
        return []


def missing_inbox_folders(app: "App") -> list[str]:
    """The codes' inbox folder names (table order) with no folder in the inbox."""
    there = {fold_name(n) for n in _inbox_subfolders(app)}
    return [
        c.inbox_folder
        for c in app.codes
        if c.inbox_folder is not None and fold_name(c.inbox_folder) not in there
    ]


def stray_inbox_folders(app: "App") -> list[str]:
    """Folders directly in the inbox that are no code's inbox folder (hidden ones left
    out), by name. Files in them are not inbox files."""
    ours = {fold_name(c.inbox_folder) for c in app.codes if c.inbox_folder is not None}
    return sorted(
        (n for n in _inbox_subfolders(app) if not n.startswith(".") and fold_name(n) not in ours),
        key=fold_name,
    )


def create_inbox_folders_plan(app: "App", origin: str) -> Plan:
    """One MKDIR per missing code folder, directly in the inbox (no ops: none missing)."""
    check_origin(origin)
    inbox = app.settings.special_folders.inbox
    return Plan(
        [Op(OpKind.MKDIR, None, join(inbox, name)) for name in missing_inbox_folders(app)],
        origin=origin,
        label=f"Created the filing code folders in {inbox}",
        new_folders=True,
        inbox_folders=True,
    )


def preview_inbox_folders(app: "App", origin: str = "ui") -> list[ResolvedOp]:
    """The folders that would be made. Nothing is changed or journaled."""
    plan = create_inbox_folders_plan(app, origin)
    return app.executor.preview(plan) if plan.ops else []


def create_inbox_folders(app: "App", origin: str = "ui") -> BatchResult:
    """Make the missing code folders as one journaled batch that undo can reverse while
    they are empty, and list them in the index at once."""
    plan = create_inbox_folders_plan(app, origin)
    if not plan.ops:
        raise InvalidRequest("Every filing code folder is already there.")
    batch = app.executor.apply(plan)
    for op in batch.done:
        try:
            app.scan(op.dst)
        except Exception:  # made all the same; the watcher's next scan lists it
            log.warning("indexing the new folder %s failed", op.dst, exc_info=True)
    return batch
