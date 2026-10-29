"""Country and language packs are reached through their registries, and the registries
do not import the settings (``dam.config`` imports them)."""

import re
import subprocess
import sys
from pathlib import Path

import dam


def test_countries_does_not_import_config():
    out = subprocess.run(
        [sys.executable, "-c", "import sys, dam.countries; print('dam.config' in sys.modules)"],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    assert out.stdout.strip() == "False"


PRIVATE = re.compile(
    r"^\s*(?:from|import)\s+dam\.(?:countries\.(?:core|fi)|languages\.\w+)\b", re.MULTILINE
)


def test_packs_are_reached_through_the_registry():
    src = Path(dam.__file__).parent
    offenders = [
        str(p.relative_to(src))
        for p in src.rglob("*.py")
        if p.parent.name not in ("countries", "languages")
        and PRIVATE.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []
