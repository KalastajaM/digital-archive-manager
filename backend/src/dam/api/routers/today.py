"""The Today page: what needs attention, the overview, Ongoing and reminder status."""

from datetime import date

from fastapi import APIRouter

from dam.api.deps import AppDep
from dam.api.marks import with_marks
from dam.api.schemas import TodayOut
from dam.codes.batch import marked_count

router = APIRouter(prefix="/api", tags=["today"])


@router.get("/today", response_model=TodayOut)
def today(app: AppDep) -> dict:
    day = date.today()
    last = app.last_reminders
    inbox = app.today.inbox_entries()
    return {
        "attention": app.today.attention(day),
        "overview": app.today.overview(day, inbox),
        "unmanaged_ongoing": app.today.unmanaged_ongoing(),
        "unmanaged_important": app.today.unmanaged_important(),
        "ongoing_sync_failure": app.ongoing.last_failure,
        "reminders": {
            "last_run": last.ran_at if last else None,
            "errors": dict(last.errors) if last else {},
            "skipped": last.skipped if last else None,
        },
        "tray_errors": app.tray_errors,
        "inbox_stats": app.today.inbox_stats(day, inbox),
        "found": with_marks(app, app.today.found_in_inbox(day, inbox)),
        "open_items": app.today.open_items(),
        "marked": marked_count(app, inbox),
    }
