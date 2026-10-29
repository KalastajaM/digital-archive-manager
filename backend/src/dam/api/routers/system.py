"""Status of the index, the rules and crash recovery."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Query

from dam import countries, packs
from dam.api.deps import AppDep, ArchivesDep
from dam.api.schemas import IndexErrorsOut, IndexSummaryOut, RetryIndexIn, RetryIndexOut, StatusOut
from dam.app import App
from dam.ops.primitives import can_make_links

router = APIRouter(prefix="/api", tags=["system"])


def _is_real_dir(app, rel: str) -> bool:
    try:
        p = app.paths.abs(rel)
        return p.is_dir() and not p.is_symlink()
    except OSError:
        return False


@router.get("/status", response_model=StatusOut)
def status(app: AppDep, archives: ArchivesDep) -> dict:
    counts = app.repo.counts()
    return {
        "files": counts["total"],
        "indexed": counts.get("indexed", 0),
        "pending": counts.get("pending", 0),
        "cloud_pending": counts.get("cloud_pending", 0),
        "errors": counts.get("error", 0),
        "unsupported": counts.get("unsupported", 0),
        "missing": counts["missing"],
        "inbox_count": counts["inbox"],
        "rule_errors": app.rule_errors,
        "tray_errors": app.tray_errors,
        "recovery_pending": len(app.activity.pending()),
        "archive_available": app.archive_available,
        "special_folders": app.settings.special_folders.model_dump(),
        "inbox_exists": _is_real_dir(app, app.paths.inbox),
        "can_link": can_make_links(),
        "page1": _page1(app),
        "identifiers": _identifiers(app),
        **archives.summary(),
    }


def _identifiers(app: App) -> dict:
    read, total = app.repo.identifier_progress(countries.signature())
    return {"read": read, "total": total}


def _found(app: App) -> list[dict]:
    """How many files carry a business ID, an IBAN, a web or mail domain (enabled packs)."""
    profile = packs.active()
    business = packs.business_id_kinds(profile)
    every = [s.kind for p in profile.countries for s in p.identifiers]
    groups = [
        ("business IDs", business),
        ("IBANs", [k for k in every if k.endswith(".iban")]),
        ("web or mail domains", [k for k in every if k.endswith(".domain")]),
    ]
    return [{"label": label, "count": app.repo.files_with_kinds(kinds)} for label, kinds in groups]


def _page1(app: App) -> dict:
    read, total = app.repo.layout_progress()
    text, scans = app.repo.layout_unread()
    return {
        "text_left": text,
        "scans_left": scans,
        "text_per_min": app.settings.page1_text_reads_per_minute,
        "scans_per_min": app.settings.indexer_reads_per_minute,
        "read": read,
        "total": total,
        "backfill": app.settings.page1_backfill,
        "rate_per_min": app.content.layout_rate(),
        "blocked": [{"reason": r, "count": n} for r, n in app.content.layout_waiting()],
    }


ERRORS_LIMIT = 200


@router.get("/index/errors", response_model=IndexErrorsOut)
def index_errors(
    app: AppDep,
    all: bool = False,
    limit: Annotated[int, Query(ge=1, le=1000)] = ERRORS_LIMIT,
) -> dict:
    """Files whose content could not be indexed (``error``; with ``all`` also
    ``unsupported``), with the stored reason, newest file first: at most ``limit``
    rows, the ``total`` count, and (with ``all``) the unsupported files per type."""
    repo = app.repo
    return {
        "rows": [asdict(p) for p in repo.index_problems(include_unsupported=all, limit=limit)],
        "total": repo.count_index_problems(include_unsupported=all),
        "unsupported_by_type": (
            [{"ext": e, "count": n} for e, n in repo.unsupported_by_type()] if all else []
        ),
    }


@router.get("/index/summary", response_model=IndexSummaryOut)
def index_summary(
    app: AppDep,
    limit: Annotated[int, Query(ge=1, le=1000)] = ERRORS_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """File counts per index state, the not readable (``unsupported``) files per type,
    and one page (``limit``, ``offset``) of those files with their reasons."""
    repo = app.repo
    counts = repo.counts()
    return {
        "searchable": counts.get("indexed", 0),
        "waiting": counts.get("pending", 0) + counts.get("cloud_pending", 0),
        "not_readable": counts.get("unsupported", 0),
        "errors": counts.get("error", 0),
        "missing": counts["missing"],
        "not_readable_by_type": [{"ext": e, "count": n} for e, n in repo.unsupported_by_type()],
        "rows": [
            asdict(p)
            for p in repo.index_problems(limit=limit, offset=offset, only_unsupported=True)
        ],
        "offset": offset,
        "page1": {**_page1(app), "with_text": repo.layout_with_text()},
        "identifiers": {**_identifiers(app), "found": _found(app)},
    }


@router.post("/index/retry", response_model=RetryIndexOut)
def index_retry(app: AppDep, body: RetryIndexIn) -> dict:
    """Queue those files (in ``error`` or ``unsupported``) for indexing again."""
    return {"queued": app.retry_index(body.drive_ids)}
