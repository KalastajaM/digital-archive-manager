"""Check digits of account numbers and payment references, in one place: field detection,
the bank barcode, the tray field types and the country packs all use these."""


def iban_mod97(compact: str) -> int:
    """ISO 13616 mod 97: the first four characters moved to the end, letters as base-36
    digits. A valid IBAN or RF reference gives 1."""
    rearranged = compact[4:] + compact[:4]
    digits = "".join(str(int(c, 36)) for c in rearranged)
    return int(digits) % 97


def valid_iban(compact: str) -> bool:
    return iban_mod97(compact) == 1


def valid_rf(compact: str) -> bool:
    """An RF creditor reference (ISO 11649), compact."""
    return 5 <= len(compact) <= 25 and iban_mod97(compact) == 1


def check_731(digits: str) -> int:
    """Finnish domestic reference check digit for ``digits`` (without the check digit)."""
    total = sum(int(d) * (7, 3, 1)[i % 3] for i, d in enumerate(reversed(digits)))
    return (10 - total % 10) % 10
