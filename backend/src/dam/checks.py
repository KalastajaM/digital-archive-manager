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


def ytunnus_check(seven: str) -> int | None:
    """The check digit of a Finnish business ID (Y-tunnus) from its seven digits: weights
    7, 9, 10, 5, 8, 4, 2, mod 11; None when the remainder is 1 (no such ID)."""
    r = sum(int(d) * w for d, w in zip(seven, (7, 9, 10, 5, 8, 4, 2), strict=True)) % 11
    return None if r == 1 else (0 if r == 0 else 11 - r)


def mod97_10(compact: str) -> int:
    """ISO 7064 mod 97-10 of the string as it stands (not rearranged), letters as A=10 to
    Z=35. A valid Dutch btw-id of a sole proprietor (from 2020) gives 1."""
    return int("".join(str(int(c, 36)) for c in compact)) % 97


def elfproef(nine: str) -> bool:
    """The Dutch eleven test on nine digits: weights 9 to 2 on the first eight, -1 on the
    last, a sum divisible by 11. Both the RSIN and the BSN (a personal number) pass it."""
    if len(nine) != 9 or not nine.isdigit():
        return False
    weights = (9, 8, 7, 6, 5, 4, 3, 2, -1)
    return sum(int(d) * w for d, w in zip(nine, weights, strict=True)) % 11 == 0


def kenmerk_check(digits: str) -> int:
    """The check digit of a Dutch betalingskenmerk for the ``digits`` after it: weights 2,
    4, 8, 5, 10, 9, 7, 3, 6, 1 from the rightmost digit, repeating; 11 minus the sum mod
    11, with 11 giving 0 and 10 giving 1 (nl.wikipedia.org "Elfproef")."""
    weights = (2, 4, 8, 5, 10, 9, 7, 3, 6, 1)
    total = sum(int(d) * weights[i % 10] for i, d in enumerate(reversed(digits)))
    check = 11 - total % 11
    return {11: 0, 10: 1}.get(check, check)


# The length code (second digit) of a betalingskenmerk shorter than 16 digits: how many
# digits follow it.
_KENMERK_LENGTHS = {"0": 10, "1": 11, "2": 12, "7": 7, "8": 8, "9": 9}


def valid_kenmerk(digits: str) -> bool:
    """A Dutch betalingskenmerk, compact: 16 digits, or 9 to 14 whose second digit gives
    the length; the first digit checks the rest. The 7-digit form has no check digit and is
    never valid here."""
    if not digits.isdigit() or digits.strip("0") == "":
        return False
    if len(digits) != 16 and _KENMERK_LENGTHS.get(digits[1:2]) != len(digits) - 2:
        return False
    return kenmerk_check(digits[1:]) == int(digits[0])
