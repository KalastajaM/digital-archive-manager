from dam.checks import check_731, iban_mod97, valid_iban, valid_rf


def test_iban():
    assert valid_iban("FI2112345600000785")
    assert not valid_iban("FI2112345600000786")
    assert iban_mod97("FI2112345600000785") == 1


def test_rf():
    assert valid_rf("RF18123456789") and valid_rf("RF2350001")
    assert not valid_rf("RF2450001")
    assert not valid_rf("RF18")  # too short


def test_check_731():
    assert check_731("123456") == 1
    assert check_731("123") == 2
