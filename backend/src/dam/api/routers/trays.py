"""Tray definitions (from config) and the items in a tray."""

from dataclasses import asdict
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from dam.api.deps import AppDep
from dam.api.routers.items import file_rows
from dam.api.schemas import (
    ApplyTrayDefaultsIn,
    ApplyTrayDefaultsOut,
    DismissTrayDefaultsIn,
    DismissTrayDefaultsOut,
    TrayDefaultsDiffOut,
    TrayItemOut,
    TraysOut,
)

router = APIRouter(prefix="/api/trays", tags=["trays"])


@router.get("", response_model=TraysOut)
def trays(app: AppDep) -> dict:
    return {"trays": app.tray_defs, "errors": app.tray_errors}


@router.get("/{tray_id}/items", response_model=list[TrayItemOut])
def tray_items(app: AppDep, tray_id: str, state: Literal["open", "done"] = "open") -> list:
    """The tray's items (open: by date, undated last; done: most recently done first)."""
    day = date.today()
    out = []
    items = app.trays.list(tray_id, state)
    marks = app.marks.marks_for([item.files[0] for item in items if item.files])
    for item in items:
        info = app.today.file_info(item)
        out.append(
            {
                **asdict(item),
                "level": app.today.level(item, day),
                "file_state": app.today.file_state(item, info),
                "has_note": bool(app.notes.get("item", str(item.id)).strip()),
                "first_file": (
                    file_rows(app, item.files[:1], info[:1], marks)[0] if item.files else None
                ),
            }
        )
    return out


@router.get("/{tray_id}/defaults-diff", response_model=TrayDefaultsDiffOut)
def defaults_diff(
    app: AppDep,
    tray_id: str,
    paths: Annotated[list[str] | None, Query()] = None,
    dismissed: bool = False,
) -> dict:
    """What the shipped default tray file of the same name would add: only missing,
    not dismissed keys (``added`` is empty when nothing is missing or there is no such
    default). ``new_text`` adds ``paths`` (repeatable; default: every valid key).
    With ``dismissed`` the answer also lists the dismissed keys still missing."""
    diff = app.tray_defaults_diff(tray_id, paths)
    if dismissed:
        diff.dismissed = app.dismissed_tray_defaults(tray_id)
    return asdict(diff)


@router.post("/{tray_id}/apply-defaults", response_model=ApplyTrayDefaultsOut)
def apply_defaults(app: AppDep, tray_id: str, body: ApplyTrayDefaultsIn) -> dict:
    """Add only ``paths``, if the file and the result are still the previewed texts
    (else 400 ``stale_preview``), after a backup; then reload the trays."""
    file, backup = app.apply_tray_defaults(
        tray_id, body.paths, body.expect_current_text, body.expect_new_text
    )
    return {"file": file, "backup": backup.name}


@router.post("/{tray_id}/defaults-dismiss", response_model=DismissTrayDefaultsOut)
def dismiss_defaults(app: AppDep, tray_id: str, body: DismissTrayDefaultsIn) -> dict:
    """Stop offering those default keys (stored in the data dir, not the tray file)."""
    return {"dismissed": app.dismiss_tray_defaults(tray_id, body.paths)}


@router.post("/{tray_id}/defaults-undismiss", response_model=DismissTrayDefaultsOut)
def undismiss_defaults(app: AppDep, tray_id: str, body: DismissTrayDefaultsIn) -> dict:
    """Offer those dismissed default keys again; answers the keys still dismissed."""
    return {"dismissed": app.undismiss_tray_defaults(tray_id, body.paths)}
