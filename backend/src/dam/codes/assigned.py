"""Filing codes the owner gives inbox files in the app, as if a sticker were on them.

This is dam's own record of a decision, kept in the index: nothing in the archive
changes, so it needs no operation, preview or journal entry. Filing the file later goes
through the usual preview."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from dam.services.errors import InvalidRequest, NotFound

if TYPE_CHECKING:
    from dam.app import App


def assign_code(app: App, drive_ids: Sequence[str], code: str | None) -> str | None:
    """Give each file ``code`` (None: take its assigned code away); the code as stored.
    ``InvalidRequest`` for a code not in the loaded table, no files, or a file not in
    the inbox; ``NotFound`` for an unknown file. All or nothing."""
    ids = list(dict.fromkeys(drive_ids))
    if not ids:
        raise InvalidRequest("no files given")
    if code is not None:
        code = code.strip().upper()
        if code not in {c.code for c in app.codes}:
            raise InvalidRequest(f"unknown filing code: {code}")
    for drive_id in ids:
        rec = app.repo.get(drive_id)
        if rec is None:
            raise NotFound(f"no file {drive_id}")
        if not app.repo.in_inbox_path(rec.path):
            raise InvalidRequest(f"{rec.name or rec.path} is not in the inbox")
    app.repo.set_assigned_code(ids, code)
    return code
