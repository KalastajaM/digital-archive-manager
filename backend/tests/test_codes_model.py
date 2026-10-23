import pytest
from pydantic import ValidationError

from dam.codes.model import FilingCode, confusable_with, load_codes, save_codes
from dam.config import AppPaths

TRAYS = {"to-action", "to-pay"}


def test_seed_on_ensure(tmp_path):
    paths = AppPaths(tmp_path)
    paths.ensure()
    assert paths.filing_codes_path == tmp_path / "config" / "filing_codes.yaml"
    assert paths.filing_codes_path.exists()
    codes, problems = load_codes(paths.filing_codes_path, TRAYS)
    assert problems == []
    assert [c.code for c in codes] == ["A", "P", "F"]
    assert codes[0].tray == "to-action" and codes[0].inbox_folder == "To action"
    assert codes[2].as_suggested is True and codes[2].label == "File as suggested"


def test_seed_into_existing_config(tmp_path):
    paths = AppPaths(tmp_path)
    paths.ensure()
    paths.filing_codes_path.unlink()
    paths.ensure()
    assert paths.filing_codes_path.exists()


def test_deleted_seed_stays_deleted(tmp_path):
    paths = AppPaths(tmp_path)
    paths.ensure()
    save_codes(paths.filing_codes_path, [])
    paths.ensure()
    assert load_codes(paths.filing_codes_path, TRAYS) == ([], [])


def test_missing_file(tmp_path):
    assert load_codes(tmp_path / "none.yaml", TRAYS) == ([], [])


def test_code_is_upper_cased():
    assert FilingCode(code="v3").code == "V3"


def test_code_too_long_is_invalid():
    with pytest.raises(ValidationError):
        FilingCode(code="ABCDE")


def test_unknown_tray_is_invalid(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("- code: X\n  tray: gone\n- code: Y\n", encoding="utf-8")
    codes, problems = load_codes(path, TRAYS)
    assert [c.code for c in codes] == ["Y"]
    assert len(problems) == 1 and "gone" in problems[0].message


def test_duplicate_inbox_folder_folded(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text(
        "- code: A\n  inbox_folder: To pay\n- code: B\n  inbox_folder: to pay\n", encoding="utf-8"
    )
    codes, problems = load_codes(path, TRAYS)
    assert [c.code for c in codes] == ["A"]
    assert len(problems) == 1 and problems[0].code == "B"


def test_duplicate_code_and_bad_entry(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("- code: a\n- code: A\n- 5\n- code: TOOLONG\n", encoding="utf-8")
    codes, problems = load_codes(path, TRAYS)
    assert [c.code for c in codes] == ["A"]
    assert len(problems) == 3


def test_bad_template_is_invalid():
    with pytest.raises(ValidationError):
        FilingCode(code="X", folder="{nope}")


def test_save_round_trip_and_backup(tmp_path):
    path = tmp_path / "filing_codes.yaml"
    codes = [
        FilingCode(code="a", label="To action", tray="to-action", inbox_folder="To action"),
        FilingCode(code="K9", folder="Taxes/{year}", tags=["tax"], as_suggested=True),
    ]
    save_codes(path, codes)
    assert list(tmp_path.glob("*.bak-*")) == []
    save_codes(path, codes)
    assert len(list(tmp_path.glob("*.bak-*"))) == 1
    assert load_codes(path, TRAYS) == (codes, [])


def test_confusable():
    assert confusable_with("O", ["0", "A"]) == ["0"]
    assert confusable_with("S1", ["5I", "SI"]) == ["SI"]
