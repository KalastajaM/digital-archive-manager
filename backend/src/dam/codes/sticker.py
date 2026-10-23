"""Sticker layout and QR payload: the one geometry shared by printing and reading.

All distances are in QR modules, relative to the QR's top-left corner. The QR is
version 1 (21 modules) at error correction M, so every payload must fit that.

Layout 1 puts a text column right of the QR (code, label, tick boxes). Everything in
it is left-aligned on ``X0`` (ink edge, not font origin): row 1 the bold code with its
ink top on the QR's top edge, row 2 the label (one line, shrunk from 6.5 pt to 5 pt to
fit) centred on the QR's middle, row 3 the boxes bottom-aligned with the QR. Before
the star box sits ``STAR_SLOT`` modules holding a drawn 5-point star (about 65 % of the
box height); after it ``GAP`` modules, then ``BANG_SLOT`` modules holding a bold ``!``
before the important box. The QR plus text block is centred on the label.
"""

import re
from typing import Literal

import zxingcpp

QR_VERSION_MODULES = 21
PLAIN = "dam:{code}"
BOXED = "dam:1:{code}"

X0 = 25
BOX = 8
STAR_SLOT = 6
GAP = 2
BANG_SLOT = 3
LABEL_PT_MAX = 6.5
LABEL_PT_MIN = 5.0
STAR_HEIGHT_RATIO = 0.65

_PAYLOAD_RE = re.compile(r"^dam:(?:(1):)?([A-Za-z0-9]{1,4})$")


def parse_payload(text: str) -> tuple[str, int] | None:
    """``(code, layout)`` for a dam sticker payload (layout 0 plain, 1 boxes), else None."""
    m = _PAYLOAD_RE.fullmatch(text)
    if m is None:
        return None
    return m.group(2).upper(), 1 if m.group(1) else 0


def payload(code: str, layout: int) -> str:
    return (BOXED if layout == 1 else PLAIN).format(code=code.upper())


def box_rects(layout: int = 1) -> dict[Literal["star", "important"], tuple[float, float, float]]:
    """``(x, y, side)`` of each tick box in modules; empty for the plain layout."""
    if layout != 1:
        return {}
    y = QR_VERSION_MODULES - BOX
    return {
        "star": (X0 + STAR_SLOT, y, BOX),
        "important": (X0 + STAR_SLOT + BOX + GAP + BANG_SLOT, y, BOX),
    }


def qr_svg(code: str, layout: int) -> str:
    text = payload(code, layout)
    barcode = zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.QRCode, ec_level="M")
    modules = barcode.to_image(scale=1, add_quiet_zones=False).shape[0]
    assert modules == QR_VERSION_MODULES, f"payload {text!r} does not fit QR version 1"
    return barcode.to_svg()
