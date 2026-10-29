"""One version: the package's (pyproject.toml), which the API and snapshots report."""

import tomllib
from pathlib import Path

from dam.api import create_api
from dam.snapshots import app_version

PYPROJECT = Path(__file__).parents[1] / "pyproject.toml"


def test_the_installed_version_is_the_pyproject_one():
    declared = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    assert app_version() == declared


def test_the_api_reports_it(app):
    assert create_api(app, None).version == app_version()
