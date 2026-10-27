"""Archive settings the app writes to ``settings.yaml``."""

from fastapi import APIRouter
from pydantic import ValidationError

from dam.api.deps import AppDep
from dam.api.schemas import (
    Page1BackfillIn,
    Page1BackfillOut,
    Page1SpeedIn,
    Page1SpeedOut,
    PeopleIn,
    PeopleOut,
)
from dam.codes.model import format_validation
from dam.config import DEFAULT_ADDRESS_ZONE, Person, Settings
from dam.errors import InvalidRequest

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.put("/page1-backfill", response_model=Page1BackfillOut)
def put_page1_backfill(app: AppDep, body: Page1BackfillIn) -> dict:
    """Turn the backfill of page-1 positions for documents outside the inbox on or off.
    400 when settings.yaml could not be written (it is left as it was)."""
    app.set_page1_backfill(body.enabled)
    return {"enabled": app.settings.page1_backfill}


@router.put("/page1-speed", response_model=Page1SpeedOut)
def put_page1_speed(app: AppDep, body: Page1SpeedIn) -> dict:
    """Set how many PDFs with a text layer have page 1 read per minute (scans, photos and
    slow downloads keep the indexer's pace). 400 for a rate outside 1 to 6000, or when
    settings.yaml could not be written (it is left as it was)."""
    app.set_page1_speed(body.reads_per_minute)
    return {"reads_per_minute": app.settings.page1_text_reads_per_minute}


def _people_out(app) -> dict:
    return {
        "people": [p.model_dump() for p in app.settings.people],
        "address_zone": list(app.settings.address_zone),
        "default_address_zone": list(DEFAULT_ADDRESS_ZONE),
    }


@router.get("/people", response_model=PeopleOut)
def get_people(app: AppDep) -> dict:
    """The people documents can be for, and where on page 1 their address is (x0, y0, x1,
    y1 as fractions of the page, origin top left)."""
    return _people_out(app)


@router.put("/people", response_model=PeopleOut)
def put_people(app: AppDep, body: PeopleIn) -> dict:
    """Save the people list (the whole list) and, when given, the address zone to
    settings.yaml; used at once. 400 for a bad name, a repeated name, an empty or blank
    ``match``, or a bad zone; nothing is written then."""
    try:
        checked = Settings.model_validate(
            {
                "people": [p.model_dump() for p in body.people],
                **({"address_zone": body.address_zone} if body.address_zone else {}),
            }
        )
    except ValidationError as e:
        raise InvalidRequest(format_validation(e)) from e
    app.set_people(
        [Person.model_validate(p.model_dump()) for p in checked.people],
        checked.address_zone if body.address_zone else None,
    )
    return _people_out(app)
