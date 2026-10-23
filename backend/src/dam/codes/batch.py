"""The File N marked batch: one row per inbox file with a filing code, with the request
that files it and a flag when it should not be filed without a look.

Reads only. Each row is checked with the existing dry run (``InboxService.preview``):
first alone, then all unflagged rows together (in pairs when the whole batch is
refused), so two rows that would take the same name in the same folder are caught:
the planner gives the later one a collision suffix, and a row whose destination
differs from its own dry run would file something other than what it shows. Filing
goes through ``POST /api/inbox/file`` with the ticked rows' requests, so it is one
journaled batch with one undo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from dam.codes.apply import CodeHit, unclear_boxes
from dam.core.paths import OutsideArchiveError
from dam.ops.guards import fold_parts
from dam.ops.model import GuardError, OpKind, ResolvedOp
from dam.services.errors import InvalidRequest, NotFound
from dam.services.inbox import FileRequest

if TYPE_CHECKING:
    from dam.app import App
    from dam.services.inbox import InboxEntry

Flag = Literal["unclear", "conflict", "needs_input"]

log = logging.getLogger(__name__)

# what a dry run may refuse with
_REFUSED = (InvalidRequest, GuardError, NotFound, OutsideArchiveError)
# the problem of a row whose dry run failed unexpectedly (a bug, logged): the batch is
# still listed, and the row is filed from the form
UNCHECKED = "could not be checked"


@dataclass
class BatchRow:
    drive_id: str
    codes: list[CodeHit]
    request: FileRequest
    # the tray fields that will be stored (scan prefill), as strings; empty without a tray
    tray_fields: dict[str, str] = field(default_factory=dict)
    flag: Flag | None = None
    # what the owner has to fix: "folder", a missing required tray field, or the
    # refusal's message; None when the row is not flagged
    problem: str | None = None


def valid_hits(app: App, entry: InboxEntry) -> list[CodeHit]:
    """The entry's code hits whose code is in the loaded table."""
    known = {c.code for c in app.codes}
    return [h for h in entry.suggestion.codes if h.code.upper() in known]


def marked_count(app: App, entries: list[InboxEntry] | None = None) -> int:
    """How many inbox files have a valid code (the rows ``marked_rows`` gives), without
    the dry runs (``entries``: an ``app.inbox.list()`` result to reuse)."""
    entries = app.inbox.list() if entries is None else entries
    return sum(1 for e in entries if valid_hits(app, e))


def marked_rows(app: App, entries: list[InboxEntry] | None = None) -> list[BatchRow]:
    """One row per inbox file with at least one valid code hit, in Inbox order.

    Flags, first that applies: ``unclear`` (a code or a sticker's tick box read
    uncertainly: "Tick box unclear: star"), ``conflict``
    (codes disagree), ``needs_input`` (no folder, a required tray field missing, or the
    dry run refuses the request, alone or next to the other rows; a dry run that fails
    unexpectedly gives ``UNCHECKED``, so listing the batch never fails)."""
    entries = app.inbox.list() if entries is None else entries
    rows: list[BatchRow] = []
    # an unflagged row's drive id -> (its folded source, its destination alone)
    alone: dict[str, tuple[str, str | None]] = {}
    for entry in entries:
        hits = valid_hits(app, entry)
        if hits:
            row, target = _row(app, entry, hits)
            rows.append(row)
            if row.flag is None:
                alone[row.drive_id] = target
    _check_together(app, [r for r in rows if r.flag is None], alone)
    return rows


def _row(
    app: App, entry: InboxEntry, hits: list[CodeHit]
) -> tuple[BatchRow, tuple[str, str | None]]:
    """The row, and its folded source with its destination in its own dry run (None
    when it needs no move or was not previewed)."""
    s = entry.suggestion
    src = fold_parts(entry.record.path)
    request = FileRequest(
        drive_id=entry.record.drive_id,
        name=s.name,
        folder=s.folder or "",
        tags=list(s.tags),
        tray=s.tray,
        collections=list(s.collections),
        star=bool(s.star),
        important=bool(s.important),
    )
    row = BatchRow(entry.record.drive_id, hits, request)

    def flag(kind: Flag, problem: str) -> tuple[BatchRow, tuple[str, str | None]]:
        row.flag, row.problem = kind, problem
        return row, (src, None)

    tray_error: str | None = None
    if s.tray is not None:
        try:
            raw = app.trays.filing_fields(s.tray, {}, entry.prefill)
        except InvalidRequest as e:
            tray_error = str(e)
        else:
            row.tray_fields = {k: str(v) for k, v in raw.items() if v is not None}
            # a field shown empty is sent as "": filing must not fill in a value the
            # owner never saw
            tray = next((t for t in app.tray_defs if t.id == s.tray), None)
            for name in tray.fields if tray is not None else ():
                row.tray_fields.setdefault(name, "")
            request.tray_fields = dict(row.tray_fields)

    if any(h.unclear for h in hits):
        return flag("unclear", "a code was read unclearly")
    if s.marks_unclear:
        return flag("unclear", "Tick box unclear: " + ", ".join(unclear_boxes(s)))
    if s.conflict:
        return flag("conflict", "the codes give different values")
    if s.folder is None:
        return flag("needs_input", "folder")
    if tray_error is not None:
        return flag("needs_input", tray_error)
    if s.tray is not None:
        tray = next((t for t in app.tray_defs if t.id == s.tray), None)
        if tray is not None:
            for name, fdef in tray.fields.items():
                if fdef.required and not row.tray_fields.get(name):
                    return flag("needs_input", name.replace("_", " "))
    try:
        resolved = app.inbox.preview([request])
    except _REFUSED as e:
        return flag("needs_input", _message(e))
    except Exception:
        log.exception("dry run of marked file %s failed", row.drive_id)
        return flag("needs_input", UNCHECKED)
    return row, (src, _targets(resolved).get(src))


def _message(e: Exception) -> str:
    # NotFound is a KeyError: its str() is the repr of the key
    return str(e.args[0]) if isinstance(e, KeyError) and e.args else str(e)


def _targets(resolved: list[ResolvedOp]) -> dict[str, str]:
    """Each moved or renamed file's source (folded) -> its resolved destination."""
    return {
        fold_parts(op.src): op.dst
        for op in resolved
        if op.kind in (OpKind.MOVE, OpKind.RENAME) and op.src is not None
    }


def _check_together(
    app: App, rows: list[BatchRow], alone: dict[str, tuple[str, str | None]]
) -> None:
    """Flag rows that pass alone but clash with an earlier row: the dry run of all of
    them gives a row another destination than its own dry run (a collision suffix:
    what would be filed is not what the row shows). If the dry run of all of them is
    refused, check in pairs instead."""
    if len(rows) < 2:
        return
    try:
        together = _targets(app.inbox.preview([r.request for r in rows]))
    except _REFUSED:
        _check_pairs(app, rows, alone)
        return
    except Exception:
        log.exception("dry run of %d marked files together failed", len(rows))
        _check_pairs(app, rows, alone)
        return
    taken: dict[str, BatchRow] = {}
    for row in rows:
        src, dst = alone[row.drive_id]
        if dst is None:
            continue
        if together.get(src) != dst:
            _clash(app, row, taken.get(fold_parts(dst)))
        else:
            taken[fold_parts(dst)] = row


def _check_pairs(app: App, rows: list[BatchRow], alone: dict[str, tuple[str, str | None]]) -> None:
    """The batch was refused as a whole: keep each row whose dry run next to every row
    kept before it is accepted and leaves its destination as its own dry run gave it;
    flag the others (refused: the refusal; moved aside: a clash)."""
    kept: list[BatchRow] = []
    for row in rows:
        src, dst = alone[row.drive_id]
        for other in kept:
            try:
                pair = _targets(app.inbox.preview([other.request, row.request]))
            except _REFUSED as e:
                row.flag, row.problem = "needs_input", _message(e)
                break
            except Exception:
                log.exception("dry run of marked file %s next to another failed", row.drive_id)
                row.flag, row.problem = "needs_input", UNCHECKED
                break
            if dst is not None and pair.get(src) != dst:
                _clash(app, row, other)
                break
        if row.flag is None:
            kept.append(row)


def _clash(app: App, row: BatchRow, other: BatchRow | None) -> None:
    where = f"{row.request.folder}/{row.request.name}"
    rec = app.repo.get(other.drive_id) if other is not None else None
    whom = rec.name if rec is not None and rec.name else "another marked file"
    row.flag = "needs_input"
    row.problem = f"{where} is also where {whom} would go"
