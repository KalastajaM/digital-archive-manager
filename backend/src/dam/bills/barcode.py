"""The Finnish bank barcode (pankkiviivakoodi), versions 4 and 5.

Per Finance Finland's "Pankkiviivakoodi-opas" v5.3: 54 digits, drawn as Code 128 set C.

- Version 4 (national reference): ``4`` + the 16 IBAN digits after "FI" + euros (6)
  + cents (2) + ``000`` + the reference (20, zero-padded) + due date ``YYMMDD``.
- Version 5 (RF reference): ``5`` + the 16 IBAN digits + euros (6) + cents (2) + the
  RF check digits (2) + the reference body (21, zero-padded) + due date ``YYMMDD``.

The due date is ``000000`` when there is none; an amount of ``00000000`` means the payer
chooses the amount. A wrong barcode is worse than none: ``build`` refuses anything it
cannot encode exactly, and checks its own result by parsing it back.
"""

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

CODE_LENGTH = 54
MAX_AMOUNT = Decimal("999999.99")
_CENT = Decimal("0.01")
_DIGITS = frozenset("0123456789")


class BarcodeError(ValueError):
    """The values cannot make (or the digits are not) a valid bank barcode."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class BarcodeData:
    iban: str  # compact, "FI" + 16 digits
    amount: Decimal  # two decimals; 0.00 when the payer chooses
    reference: str  # compact: national digits without leading zeros, or "RFnn" + digits
    due: date | None


def _digits(s: str) -> bool:
    return bool(s) and set(s) <= _DIGITS  # ASCII only: str.isdigit() takes "٤" too


def _mod97(compact: str) -> int:
    rearranged = compact[4:] + compact[:4]
    return int("".join(str(int(c, 36)) for c in rearranged)) % 97


def _check_731(digits: str) -> int:
    total = sum(int(d) * (7, 3, 1)[i % 3] for i, d in enumerate(reversed(digits)))
    return (10 - total % 10) % 10


def _iban_digits(iban: str) -> str:
    compact = "".join(iban.split()).upper()
    if not compact.startswith("FI"):
        raise BarcodeError("the IBAN is not a Finnish (FI) account")
    if len(compact) != 18 or not _digits(compact[2:]) or _mod97(compact) != 1:
        raise BarcodeError("the IBAN is not valid")
    return compact[2:]


def _amount_digits(amount: Decimal) -> str:
    try:
        if not isinstance(amount, Decimal) or not amount.is_finite():
            raise BarcodeError("the amount is not a number")
        cents = amount.quantize(_CENT)
    except InvalidOperation as e:
        raise BarcodeError("the amount is not a number") from e
    if cents != amount:
        raise BarcodeError("the amount has more than two decimals (cents)")
    if cents < 0:
        raise BarcodeError("the amount is negative")
    if cents > MAX_AMOUNT:
        raise BarcodeError("the amount is over 999 999,99 €")
    return f"{int(cents * 100):08d}"


def _national(digits: str) -> str:
    """A national reference without leading zeros; BarcodeError unless its 7-3-1 holds."""
    if len(digits) > 20:
        raise BarcodeError("the reference is too long (over 20 digits)")
    if not _digits(digits):
        raise BarcodeError("a national reference has only digits")
    body = digits.lstrip("0")
    if not body:
        raise BarcodeError("the reference is not valid")
    if len(body) < 4:
        raise BarcodeError("the reference is too short (at least 4 digits)")
    if _check_731(body[:-1]) != int(body[-1]):
        raise BarcodeError("the reference fails its check digit")
    return body


def _rf(compact: str) -> tuple[str, str]:
    """(check digits, body without leading zeros) of an RF reference."""
    check, body = compact[2:4], compact[4:]
    if not _digits(check) or not body:
        raise BarcodeError("the RF reference is not valid")
    if not _digits(body):
        raise BarcodeError("an RF reference in a bank barcode has only digits")
    if len(body.lstrip("0")) > 21:
        raise BarcodeError("the RF reference is too long (over 21 digits)")
    body = body.lstrip("0")
    if not body or _mod97(f"RF{check}{body}") != 1:
        raise BarcodeError("the RF reference fails its check (ISO 11649)")
    return check, body


def _due_digits(due: date | None) -> str:
    if due is None:
        return "000000"
    if not 2000 <= due.year <= 2099:
        raise BarcodeError("the due date is outside 2000–2099")
    return due.strftime("%y%m%d")


def build(iban: str, amount: Decimal, reference: str, due: date | None) -> str:
    """The 54-digit code; ``BarcodeError(reason)`` when a value cannot be encoded."""
    account = _iban_digits(iban)
    money = _amount_digits(amount)
    ref = "".join(reference.split()).upper()
    if not ref:
        raise BarcodeError("there is no reference")
    if ref.startswith("RF"):
        check, body = _rf(ref)
        code = f"5{account}{money}{check}{body:0>21}{_due_digits(due)}"
        canonical = f"RF{check}{body}"
    else:
        body = _national(ref)
        code = f"4{account}{money}000{body:0>20}{_due_digits(due)}"
        canonical = body
    expected = BarcodeData(f"FI{account}", amount.quantize(_CENT), canonical, due)
    if len(code) != CODE_LENGTH or parse(code) != expected:  # never show a wrong one
        raise BarcodeError("the barcode could not be built")
    return code


def parse(code: str) -> BarcodeData:
    """The values of a 54-digit code; ``BarcodeError(reason)`` unless it is valid."""
    if not isinstance(code, str) or len(code) != CODE_LENGTH or not _digits(code):
        raise BarcodeError("a bank barcode has 54 digits")
    version = code[0]
    if version not in "45":
        raise BarcodeError(f"unknown barcode version {version}")
    iban = f"FI{code[1:17]}"
    if _mod97(iban) != 1:
        raise BarcodeError("the IBAN is not valid")
    amount = Decimal(int(code[17:25])) / 100
    if version == "4":
        if code[25:28] != "000":
            raise BarcodeError("the reserved digits are not 000")
        digits = code[28:48]
        if not digits.strip("0"):
            raise BarcodeError("there is no reference")
        reference = _national(digits)
    else:
        if not code[27:48].strip("0"):
            raise BarcodeError("there is no reference")
        check, body = _rf(f"RF{code[25:27]}{code[27:48]}")
        reference = f"RF{check}{body}"
    raw_due = code[48:54]
    due = None
    if raw_due != "000000":
        try:
            due = date(2000 + int(raw_due[:2]), int(raw_due[2:4]), int(raw_due[4:]))
        except ValueError as e:
            raise BarcodeError("the due date is not a date") from e
    return BarcodeData(iban, amount.quantize(_CENT), reference, due)


# Code 128 bar/space widths (bar first), values 0..105, then STOP with its final bar.
_TABLE = """
212222 222122 222221 121223 121322 131222 122213 122312 132212 221213
221312 231212 112232 122132 122231 113222 123122 123221 223211 221132
221231 213212 223112 312131 311222 321122 321221 312212 322112 322211
212123 212321 232121 111323 131123 131321 112313 132113 132311 211313
231113 231311 112133 112331 132131 113123 113321 133121 313121 211331
231131 213113 213311 213131 311123 311321 331121 312113 312311 332111
314111 221411 431111 111224 111422 121124 121421 141122 141221 112214
112412 122114 122411 142112 142211 241211 221114 413111 241112 134111
111242 121142 121241 114212 124112 124211 411212 421112 421211 212141
214121 412121 111143 111341 131141 114113 114311 411113 411311 113141
114131 311141 411131 211412 211214 211232 2331112
"""
PATTERNS: tuple[tuple[int, ...], ...] = tuple(
    tuple(int(c) for c in word) for word in _TABLE.split()
)
START_C, STOP = 105, 106


def code128c_values(code: str) -> list[int]:
    """Start C, the 27 digit pairs, the mod-103 check character, Stop."""
    parse(code)
    pairs = [int(code[i : i + 2]) for i in range(0, CODE_LENGTH, 2)]
    check = (START_C + sum(i * v for i, v in enumerate(pairs, 1))) % 103
    return [START_C, *pairs, check, STOP]


def modules(code: str) -> list[int]:
    """Bar and space widths in modules, bar first and last (no quiet zones)."""
    return [w for v in code128c_values(code) for w in PATTERNS[v]]


# --- an item's barcode ---------------------------------------------------------

# tray field name -> what the barcode needs it for (the To pay tray's fields)
ITEM_FIELDS = {"iban": "IBAN", "amount": "amount", "reference": "reference", "due_date": None}


def _canonical_reference(reference: str) -> str:
    ref = "".join(reference.split()).upper()
    if ref.startswith("RF"):
        check, body = _rf(ref)
        return f"RF{check}{body}"
    return _national(ref)


def for_fields(fields: dict, invalid: Collection[str] = ()) -> tuple[str | None, str | None]:
    """(code, None) built from an item's ``iban``, ``amount``, ``reference`` and
    ``due_date`` (parsed values); (None, one-line reason) when it cannot be built."""
    for name, label in ITEM_FIELDS.items():
        if name in invalid:
            return None, f"the {label or 'due date'} is not valid"
        if label and fields.get(name) in (None, ""):
            return None, f"no {label}"
    due = fields.get("due_date")
    try:
        return build(fields["iban"], fields["amount"], fields["reference"], due), None
    except BarcodeError as e:
        return None, e.reason


def mismatch(fields: dict, printed: BarcodeData) -> list[str]:
    """The item field names whose value differs from the printed barcode's. An amount
    of 0 (the payer chooses) or no due date in the barcode disagrees with nothing."""
    out = []
    iban = fields.get("iban")
    if not isinstance(iban, str) or "".join(iban.split()).upper() != printed.iban:
        out.append("iban")
    if printed.amount and fields.get("amount") != printed.amount:
        out.append("amount")
    try:
        same_ref = _canonical_reference(fields.get("reference") or "") == printed.reference
    except (BarcodeError, AttributeError):
        same_ref = False
    if not same_ref:
        out.append("reference")
    if printed.due is not None and fields.get("due_date") != printed.due:
        out.append("due_date")
    return out


def printed_fields(printed: BarcodeData) -> dict:
    """A read barcode's values as item fields (the To pay tray's names and stored forms):
    what "Use the printed barcode's values" patches. The amount and due date are None
    where the barcode leaves them open (0: the payer chooses; no due date)."""
    return {
        "iban": printed.iban,
        "amount": str(printed.amount) if printed.amount else None,
        "reference": printed.reference,
        "due_date": printed.due,
    }


def item_barcode(fields: dict, invalid: Collection[str], printed: Iterable[str | None]) -> dict:
    """What ``GET /api/items/{id}/barcode`` returns: the code built from the fields (or
    the reason there is none), and the first valid code read from the item's files with
    its values and the fields that disagree with it."""
    code, reason = for_fields(fields, invalid)
    read: tuple[str, BarcodeData] | None = None
    for candidate in printed:
        if candidate:
            try:
                read = candidate, parse(candidate)
                break
            except BarcodeError:
                continue
    return {
        "code": code,
        "modules": modules(code) if code else None,
        "reason": reason,
        "printed": read[0] if read else None,
        "printed_fields": printed_fields(read[1]) if read else None,
        "mismatch": mismatch(fields, read[1]) if read else [],
    }
