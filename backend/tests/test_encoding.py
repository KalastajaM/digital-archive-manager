"""Text files are read and written as UTF-8 on every platform: Windows' default text
encoding is cp1252, which garbles names with accents."""

from pathlib import Path

from encoding_scan import offenders

ROOT = Path(__file__).resolve().parents[1]


def test_no_text_io_relies_on_the_platform_encoding():
    bad = []
    for folder in ("src", "tests"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            bad += [f"{path.relative_to(ROOT)}:{c.lineno}" for c in offenders(path)]
    assert bad == [], "pass encoding='utf-8' to: " + ", ".join(bad)
