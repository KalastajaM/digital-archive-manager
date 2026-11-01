"""Archive settings the app writes to ``settings.yaml``."""

import base64
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from dam import countries, languages
from dam.api.deps import AppDep
from dam.api.sample_letter import read_sample, sample_ext
from dam.api.schemas import (
    CountriesIn,
    CountriesOut,
    ExpiredFolderIn,
    ExpiredFolderOut,
    Page1BackfillIn,
    Page1BackfillOut,
    Page1SpeedIn,
    Page1SpeedOut,
    PeopleIn,
    PeopleOut,
    SampleLetterOut,
)
from dam.codes.model import format_validation
from dam.config import Person, Settings
from dam.errors import InvalidRequest, TooLarge

router = APIRouter(prefix="/api/settings", tags=["settings"])

SAMPLE_MAX_BYTES = 50 * 1024 * 1024  # a letter, not an archive: 50 MB is plenty
SAMPLE_LIMIT_MB = SAMPLE_MAX_BYTES // (1024 * 1024)


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


@router.get("/expired-folder", response_model=ExpiredFolderOut)
def get_expired_folder(app: AppDep) -> dict:
    """The name of the Expired folder."""
    return {"name": app.settings.expired_folder_name}


@router.get("/versions-folder", response_model=ExpiredFolderOut)
def get_versions_folder(app: AppDep) -> dict:
    """The name of the subfolder older versions of a file move to."""
    return {"name": app.settings.versions_folder_name}


@router.put("/versions-folder", response_model=ExpiredFolderOut)
def put_versions_folder(app: AppDep, body: ExpiredFolderIn) -> dict:
    """Rename that subfolder (setting only; no folder is moved). 400 with the reason for a
    name that cannot be a folder name or is one of the app's own folders."""
    return {"name": app.set_versions_folder(body.name)}


@router.put("/expired-folder", response_model=ExpiredFolderOut)
def put_expired_folder(app: AppDep, body: ExpiredFolderIn) -> dict:
    """Rename the Expired folder (setting only; no folder is moved). 400 with the reason
    for a name that cannot be a folder name, starts with ``##.`` or is one of the special
    folders' names, or when settings.yaml could not be written."""
    return {"name": app.set_expired_folder(body.name)}


def _people_out(app) -> dict:
    return {
        "people": [p.model_dump() for p in app.settings.people],
        "address_zone": list(app.settings.address_zone),
        "default_address_zone": list(app.settings.countries_zone()),
        "address_zone_set": app.settings.zone_is_set(),
    }


@router.get("/people", response_model=PeopleOut)
def get_people(app: AppDep) -> dict:
    """The people documents can be for, and where on page 1 their address is (x0, y0, x1,
    y1 as fractions of the page, origin top left)."""
    return _people_out(app)


@router.put("/people", response_model=PeopleOut)
def put_people(app: AppDep, body: PeopleIn) -> dict:
    """Save the people list (the whole list) and, when given, the address zone to
    settings.yaml; used at once. A null zone takes it out of the file, so it follows the
    countries again. 400 for a bad name, a repeated name, an empty or blank
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
        follow_countries="address_zone" in body.model_fields_set and body.address_zone is None,
    )
    return _people_out(app)


@router.post("/address-area/sample", response_model=SampleLetterOut)
async def address_area_sample(
    app: AppDep, request: Request, name: Annotated[str, Query(max_length=255)]
) -> dict:
    """Page 1 of a sample letter, to draw the address area on. The body is the file itself
    (``Content-Type: application/octet-stream``, a PDF, JPG or PNG; ``name`` is its file
    name). It is never added to the archive or the index: it is kept in a temporary file in
    the cache while page 1 is read, and removed then. 400 for another kind of file or one
    whose page 1 cannot be shown, 413 over 50 MB."""
    ext = sample_ext(name)
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > SAMPLE_MAX_BYTES:
        raise TooLarge(f"A sample letter can be at most {SAMPLE_LIMIT_MB} MB.")
    uploads = app.app_paths.cache_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=uploads, suffix=f".{ext}", delete=True, delete_on_close=False
    ) as tmp:
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > SAMPLE_MAX_BYTES:
                raise TooLarge(f"A sample letter can be at most {SAMPLE_LIMIT_MB} MB.")
            await run_in_threadpool(tmp.write, chunk)
        if total == 0:
            raise InvalidRequest("That file is empty.")
        await run_in_threadpool(tmp.flush)
        page = await run_in_threadpool(read_sample, Path(tmp.name), ext, app.settings.ocr_languages)
    return {
        "image": "data:image/png;base64," + base64.b64encode(page.png).decode("ascii"),
        "read": page.unavailable is None,
        "lines": [
            {
                "text": ln.text,
                "box": list(ln.box),
                "words": [{"text": w.text, "box": list(w.box)} for w in ln.words],
            }
            for ln in page.lines
        ],
        "unavailable": page.unavailable,
    }


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
