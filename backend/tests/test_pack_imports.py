"""Country and language packs are reached through their registries, and the registries
do not import the settings (``dam.config`` imports them)."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

import dam


@pytest.mark.parametrize("module", ["dam.countries", "dam.languages", "dam.packs"])
def test_the_registries_do_not_import_config(module):
    out = subprocess.run(
        [sys.executable, "-c", f"import sys, {module}; print('dam.config' in sys.modules)"],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    assert out.stdout.strip() == "False"


SRC = Path(dam.__file__).parent


def _packs(package: str) -> str:
    """The pack modules of a registry package, as a regex alternation."""
    names = {p.stem for p in (SRC / package).glob("*.py")} - {"__init__", "model"}
    return "|".join(sorted(names))


# "import dam.countries.fi", "from dam.countries.fi import X", "from dam.countries import fi"
PRIVATE = re.compile(
    rf"^\s*(?:(?:from|import)\s+dam\.(?:countries\.(?:{_packs('countries')})|"
    rf"languages\.(?:{_packs('languages')}))\b"
    rf"|from\s+dam\.countries\s+import\s+[^\n]*\b(?:{_packs('countries')})\b"
    rf"|from\s+dam\.languages\s+import\s+[^\n]*\b(?:{_packs('languages')})\b)",
    re.MULTILINE,
)


def test_the_check_catches_every_form():
    for line in (
        "import dam.countries.fi",
        "from dam.languages.nl import DUTCH",
        "from dam.countries import fi",
        "from dam.languages import CountryPack, sv",
    ):
        assert PRIVATE.search(line), line
    assert not PRIVATE.search("from dam.countries import ALL, get")


def test_packs_are_reached_through_the_registry():
    src = Path(dam.__file__).parent
    offenders = [
        str(p.relative_to(src))
        for p in src.rglob("*.py")
        if p.parent.name not in ("countries", "languages")
        and PRIVATE.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []
