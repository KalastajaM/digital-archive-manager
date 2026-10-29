"""Archive settings the app writes to ``settings.yaml``."""

from fastapi import APIRouter
from pydantic import ValidationError

from dam import countries, languages
from dam.api.deps import AppDep
from dam.api.schemas import (
    CountriesIn,
    CountriesOut,
    Page1BackfillIn,
    Page1BackfillOut,
    Page1SpeedIn,
    Page1SpeedOut,
    PeopleIn,
    PeopleOut,
)
from dam.codes.model import format_validation
from dam.config import Person, Settings
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
        "default_address_zone": list(app.settings.countries_zone()),
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


def _countries_out(app) -> dict:
    s = app.settings
    on_countries, on_languages = set(s.country_codes()), s.language_codes()
    return {
        "chosen": s.countries is not None,
        "countries": [
            {
                "code": p.code,
                "name": p.name,
                "enabled": p.code in on_countries,
                "adds": list(p.adds),
                "languages": list(p.languages),
            }
            for p in countries.PACKS.values()
        ],
        # the enabled ones in their order, then the others
        "languages": [
            {
                "code": p.code,
                "name": p.name,
                "enabled": p.code in on_languages,
                "always": p.code == "en",
            }
            for p in sorted(
                languages.PACKS.values(),
                key=lambda p: (
                    on_languages.index(p.code) if p.code in on_languages else len(on_languages)
                ),
            )
        ],
    }


@router.get("/countries", response_model=CountriesOut)
def get_countries(app: AppDep) -> dict:
    """The country and language packs documents can be read with, and which are on."""
    return _countries_out(app)


@router.put("/countries", response_model=CountriesOut)
def put_countries(app: AppDep, body: CountriesIn) -> dict:
    """Save the countries and languages to settings.yaml; used at once. 400 for an unknown
    or repeated code; nothing is written then."""
    try:
        Settings.model_validate({"countries": body.countries, "languages": body.languages})
    except ValidationError as e:
        raise InvalidRequest(format_validation(e)) from e
    app.set_countries(body.countries, body.languages)
    return _countries_out(app)
