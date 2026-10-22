"""Test helper: the demo archive generator lives in the package (``dam.demo``) so it ships.

uv run python -m tests.make_demo_archive <dir>
"""

import sys
from pathlib import Path

from dam.demo import (  # noqa: F401 - re-exported for the tests
    BARCODE_BILL,
    BARCODE_CODE,
    DEMO_COLLECTION,
    PDFS,
    SPECIAL,
    build_into,
)
from dam.demo import build as _build
from dam.demo import main as _main
from dam.services.errors import InvalidRequest


def build(root: Path) -> tuple[Path, Path]:
    try:
        return _build(root)
    except InvalidRequest as e:
        raise SystemExit(str(e)) from None


def main(argv: list[str]) -> None:
    _main(argv)


if __name__ == "__main__":
    main(sys.argv[1:])
