"""Saved searches: the sidebar's list with each one's number of matches, and save,
rename and delete."""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from dam.api.deps import AppDep
from dam.api.schemas.saved_searches import (
    SavedSearchDeletedOut,
    SavedSearchIn,
    SavedSearchOut,
    SavedSearchRenameIn,
    SavedSearchRowOut,
)
from dam.query import QueryError
from dam.saved_searches import SavedSearchError

router = APIRouter(prefix="/api/saved-searches", tags=["saved-searches"])

# The number of matches shown in the sidebar stops here ("500+"), as Browse's list does.
COUNT_CAP = 500

_STATUS = {"exists": 409, "missing": 404, "invalid": 422}


def _guard(call):
    try:
        return call()
    except SavedSearchError as e:
        raise HTTPException(_STATUS[e.kind], str(e)) from e


def counted(hits: int) -> dict:
    """``count`` as shown (at most ``COUNT_CAP``) and whether there are ``more``."""
    return {"count": min(hits, COUNT_CAP), "more": hits > COUNT_CAP}


@router.get("", response_model=list[SavedSearchRowOut])
def list_saved(app: AppDep) -> list[dict]:
    """Every saved search by name, each with its number of matches now (the search Browse
    runs; ``more`` past 500). A query that is refused now (a bad date) has no count and
    says why in ``error``."""
    out = []
    for s in app.saved_searches.list():
        row = {**asdict(s), "count": None, "more": False, "error": None}
        try:
            hits = app.search(s.query, limit=COUNT_CAP + 1, tag_mode=s.tag_mode)
            row.update(counted(len(hits)))
        except QueryError as e:
            row["error"] = str(e)
        out.append(row)
    return out


@router.post("", response_model=SavedSearchOut)
def save(app: AppDep, body: SavedSearchIn) -> dict:
    """Save a search under a name. 409 when a search has that name (case ignored), unless
    ``replace``: then that one takes the new query and mode. 422 for an empty or too long
    name or query."""
    return asdict(
        _guard(lambda: app.saved_searches.save(body.name, body.query, body.tag_mode, body.replace))
    )


@router.patch("/{search_id}", response_model=SavedSearchOut)
def rename(app: AppDep, search_id: int, body: SavedSearchRenameIn) -> dict:
    """Rename a saved search. 404 when it is gone, 409 when another has the name."""
    return asdict(_guard(lambda: app.saved_searches.set_name(search_id, body.name)))


@router.delete("/{search_id}", response_model=SavedSearchDeletedOut)
def delete(app: AppDep, search_id: int) -> dict:
    """Delete a saved search (its files are not touched). 404 when it is gone."""
    _guard(lambda: app.saved_searches.delete(search_id))
    return {"deleted": search_id}
