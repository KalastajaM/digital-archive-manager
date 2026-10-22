import unicodedata
from datetime import date

from dam.core.naming import matches_convention, parse_doc_date, unique_name


def test_parse_date():
    assert parse_doc_date("20261009_Apteekki_Pia.pdf") == date(2026, 10, 9)
    assert parse_doc_date("20261009-x.pdf") == date(2026, 10, 9)
    assert parse_doc_date("20261009 x.pdf") == date(2026, 10, 9)
    assert parse_doc_date("20261009.pdf") == date(2026, 10, 9)


def test_parse_date_invalid():
    assert parse_doc_date("202060822_Sketchers.pdf") is None
    assert parse_doc_date("20261341_x.pdf") is None


def test_parse_date_none():
    assert parse_doc_date("File_000.pdf") is None


def test_matches_convention():
    assert matches_convention("20261009_Apteekki.pdf")
    assert not matches_convention("20261341_Apteekki.pdf")
    assert not matches_convention("File_000.pdf")


def test_unique_name_free(tmp_path):
    assert unique_name(tmp_path, "a.pdf") == "a.pdf"


def test_unique_name_collision(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"x")
    (tmp_path / "a_2.pdf").write_bytes(b"x")
    assert unique_name(tmp_path, "a.pdf") == "a_3.pdf"


def test_unique_name_nfd_collision(tmp_path):
    nfc_name = "Kyynärpää.pdf"
    (tmp_path / unicodedata.normalize("NFD", nfc_name)).write_bytes(b"x")
    assert unique_name(tmp_path, nfc_name) == "Kyynärpää_2.pdf"


def test_unique_name_case_insensitive(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"x")
    assert unique_name(tmp_path, "A.pdf") == "A_2.pdf"


def test_unique_name_exclude_self(tmp_path):
    (tmp_path / "File.pdf").write_bytes(b"x")
    assert unique_name(tmp_path, "file.pdf", exclude="File.pdf") == "file.pdf"


def test_parse_date_unicode_digits():
    assert parse_doc_date("٢٠٢٦١٠٠٩_x.pdf") is None
    assert not matches_convention("٢٠٢٦١٠٠٩_x.pdf")


def test_unique_name_extra_taken(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"x")
    assert unique_name(tmp_path, "a.pdf", taken=["A_2.pdf"]) == "a_3.pdf"
    assert unique_name(tmp_path / "missing", "b.pdf", taken=["b.pdf"]) == "b_2.pdf"


def test_fix_mojibake_repairs_utf8_read_as_latin1():
    import unicodedata

    from dam.core.naming import fix_mojibake

    bad = "Benefits for NÃ¤kymÃ¤'s occupational health care customers (5).pdf"
    assert fix_mojibake(bad) == bad.replace("Ã¤", "ä")
    nfd = unicodedata.normalize("NFD", "NÃ¤kymÃ¤ TyÃ¶elÃ¤mÃ¤palvelut hinnasto 2027 en.pdf")
    assert fix_mojibake(nfd) == "Näkymä Työelämäpalvelut hinnasto 2027 en.pdf"
    assert fix_mojibake("CafÃ© Ã…ngstrÃ¶m") == "Café Ångström"


def test_fix_mojibake_leaves_correct_names_alone():
    import unicodedata

    from dam.core.naming import fix_mojibake

    for name in ("Käynti.pdf", "Hämeenlinna 2026.pdf", "Ã.pdf", "plain.txt"):
        assert fix_mojibake(name) == unicodedata.normalize("NFC", name)
    assert fix_mojibake(unicodedata.normalize("NFD", "Käynti.pdf")) == "Käynti.pdf"
