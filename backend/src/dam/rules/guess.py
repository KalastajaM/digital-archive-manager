"""Tray guesses for inbox documents: plain code, no AI.

A rule's ``then.tray`` wins when that tray exists; otherwise a scan that found a due
date and an amount, plus an IBAN or a reference, or that carries a valid bank barcode,
is guessed "To pay".
"""

from collections.abc import Collection

from dam.bills.barcode import BarcodeError, parse
from dam.rules.fields import DetectedFields

TO_PAY = "to-pay"


def _valid(barcode: str | None) -> bool:
    if not barcode:
        return False
    try:
        parse(barcode)
    except BarcodeError:
        return False
    return True


def guess_tray(
    found: DetectedFields,
    rule_tray: str | None,
    tray_ids: Collection[str],
    barcode: str | None = None,
) -> str | None:
    """The tray an inbox document probably belongs in, or None. ``barcode`` is the bank
    barcode read from the scan, if any."""
    if rule_tray is not None and rule_tray in tray_ids:
        return rule_tray
    if TO_PAY not in tray_ids:
        return None
    if found.due_date and found.total and (found.iban or found.reference):
        return TO_PAY
    return TO_PAY if _valid(barcode) else None
