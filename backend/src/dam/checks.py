"""Check digits of account numbers and payment references, in one place: field detection,
the bank barcode, the tray field types and the country packs all use these."""


def iban_mod97(compact: str) -> int:
    """ISO 13616 mod 97: the first four characters moved to the end, letters as base-36
    digits. A valid IBAN or RF reference gives 1."""
    rearranged = compact[4:] + compact[:4]
    digits = "".join(str(int(c, 36)) for c in rearranged)
    return int(digits) % 97


# The IBAN length of each SEPA country (ISO 13616 registry).
IBAN_LENGTHS: dict[str, int] = {
    "AT": 20, "BE": 16, "BG": 22, "CH": 21, "CY": 28, "CZ": 24, "DE": 22, "DK": 18,
    "EE": 20, "ES": 24, "FI": 18, "FR": 27, "GB": 22, "GR": 27, "HR": 21, "HU": 28,
    "IE": 22, "IS": 26, "IT": 27, "LI": 21, "LT": 20, "LU": 20, "LV": 21, "MC": 27,
    "MT": 31, "NL": 18, "NO": 15, "PL": 28, "PT": 25, "RO": 24, "SE": 24, "SI": 19,
    "SK": 24, "SM": 27,
}  # fmt: skip


def valid_iban(compact: str) -> bool:
    """Mod 97, and the country's length when it is a SEPA country."""
    length = IBAN_LENGTHS.get(compact[:2])
    if length is not None and len(compact) != length:
        return False
    return iban_mod97(compact) == 1


def valid_rf(compact: str) -> bool:
    """An RF creditor reference (ISO 11649), compact."""
    return 5 <= len(compact) <= 25 and iban_mod97(compact) == 1


def check_731(digits: str) -> int:
    """Finnish domestic reference check digit for ``digits`` (without the check digit)."""
    total = sum(int(d) * (7, 3, 1)[i % 3] for i, d in enumerate(reversed(digits)))
    return (10 - total % 10) % 10
