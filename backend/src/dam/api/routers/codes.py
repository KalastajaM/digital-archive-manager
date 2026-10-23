"""Filing codes: read the table and replace it as a whole."""

from dataclasses import asdict

from fastapi import APIRouter
from pydantic import ValidationError

from dam.api.deps import AppDep
from dam.api.schemas import FilingCodeIn, FilingCodesOut
from dam.app import App
from dam.codes.model import FilingCode, confusable_with, format_validation
from dam.services.errors import InvalidRequest

router = APIRouter(prefix="/api/filing-codes", tags=["filing-codes"])


def _out(app: App) -> dict:
    codes = [c.code for c in app.codes]
    warnings = []
    for c in codes:
        others = confusable_with(c, [o for o in codes if o != c])
        if others:
            warnings.append({"code": c, "confusable_with": others})
    return {
        "codes": [c.model_dump() for c in app.codes],
        "problems": [asdict(p) for p in app.code_problems],
        "warnings": warnings,
    }


@router.get("", response_model=FilingCodesOut)
def list_codes(app: AppDep) -> dict:
    """The loaded codes, entries of the file that were skipped (``problems``) and codes
    that look like each other (``warnings``)."""
    return _out(app)


@router.put("", response_model=FilingCodesOut)
def replace_codes(app: AppDep, body: list[FilingCodeIn]) -> dict:
    """Replace the whole table (the old file is kept as a backup); 400 with the reason
    if any code is invalid, repeated or names an unknown tray."""
    codes = []
    for entry in body:
        try:
            codes.append(FilingCode.model_validate(entry.model_dump()))
        except ValidationError as e:
            raise InvalidRequest(f"{entry.code}: {format_validation(e)}") from e
    app.save_codes(codes)
    return _out(app)
