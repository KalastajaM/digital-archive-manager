"""The tags in use, for the tag field's suggestions."""

from typing import Annotated

from fastapi import APIRouter, Query

from dam.api.deps import AppDep
from dam.api.schemas import TagCountOut

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("", response_model=list[TagCountOut])
def list_tags(
    app: AppDep,
    prefix: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=50)] = 8,
) -> list[dict]:
    """Tags that start with ``prefix`` (case and accents ignored; all when empty), most
    used first, then by name, at most ``limit``."""
    return [{"name": name, "files": n} for name, n in app.tags.popular(prefix, limit)]
