"""Where the text of page 1 sits: lines with boxes, as fractions of the page.

A box is ``(x0, y0, x1, y1)`` with the origin at the top left of the page as it is shown
(after the page's own rotation). Lines come from a PDF's text layer or from the OCR that
reads a scan; ``source`` says which (``"text-layer"``, ``"vision"`` or ``"tesseract"``).
"""

from __future__ import annotations

import ctypes
import json
from collections.abc import Sequence
from dataclasses import dataclass, field

TEXT_LAYER = "text-layer"
SCALE = 10000  # PDFium's device matrix works in whole pixels: ask for a fine one

Box = tuple[float, float, float, float]

# a line is in a box when at least half of its area is inside the box grown by this
# much of the page on every side (scans shift a few millimetres between letters)
ZONE_MARGIN = 0.03


@dataclass(frozen=True)
class Line:
    text: str
    box: Box


@dataclass
class Page1Layout:
    lines: list[Line] = field(default_factory=list)
    source: str = TEXT_LAYER

    @property
    def text(self) -> str:
        """The lines joined, one per row: page 1's text as this read saw it."""
        return "\n".join(line.text for line in self.lines)

    def lines_json(self) -> str:
        return json.dumps(
            [{"text": ln.text, "box": [round(v, 5) for v in ln.box]} for ln in self.lines],
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, lines: str, source: str) -> Page1Layout:
        raw = json.loads(lines)
        return cls([Line(r["text"], tuple(float(v) for v in r["box"])) for r in raw], source)


def clamp_box(box: Sequence[float]) -> Box:
    x0, y0, x1, y1 = (min(1.0, max(0.0, float(v))) for v in box)
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def share_inside(line: Box, area: Box) -> float:
    """How much of ``line``'s area lies inside ``area`` (0..1). A line without area
    (a zero-height box) counts by its length, or as inside when it is a point there."""
    lx0, ly0, lx1, ly1 = line
    w, h = lx1 - lx0, ly1 - ly0
    ix = max(0.0, min(lx1, area[2]) - max(lx0, area[0]))
    iy = max(0.0, min(ly1, area[3]) - max(ly0, area[1]))
    if w > 0 and h > 0:
        return (ix * iy) / (w * h)
    if w > 0:  # a flat line: by its length, if it is at the right height
        ok = area[1] <= ly0 <= area[3]
        return ix / w if ok else 0.0
    if h > 0:
        ok = area[0] <= lx0 <= area[2]
        return iy / h if ok else 0.0
    return 1.0 if area[0] <= lx0 <= area[2] and area[1] <= ly0 <= area[3] else 0.0


def grown(box: Sequence[float], margin: float = ZONE_MARGIN) -> Box:
    x0, y0, x1, y1 = box
    return clamp_box((x0 - margin, y0 - margin, x1 + margin, y1 + margin))


def in_zone(line: Line, box: Sequence[float], margin: float = ZONE_MARGIN) -> bool:
    """The line lies in ``box``: at least half of it is inside the box grown by ``margin``."""
    return share_inside(line.box, grown(box, margin)) >= 0.5


def lines_in_zone(
    lines: Sequence[Line], box: Sequence[float], margin: float = ZONE_MARGIN
) -> list[Line]:
    area = grown(box, margin)
    return [ln for ln in lines if share_inside(ln.box, area) >= 0.5]


# -- the text layer of a PDF page ----------------------------------------------------


def text_layer_lines(page) -> list[Line]:
    """The lines of text of a pypdfium2 ``PdfPage`` with their boxes (call it with the
    PDFium lock held). Characters are grouped into lines after they are placed on the
    page as shown, so a rotated page reads the same as an upright one."""
    import pypdfium2.raw as raw

    textpage = page.get_textpage()
    try:
        count = textpage.count_chars()
        if count <= 0:
            return []
        full = textpage.get_text_range(0, count)
        # a character outside the BMP makes the string longer than the char count
        texts = (
            list(full)
            if len(full) == count
            else [textpage.get_text_range(i, 1) for i in range(count)]
        )
        boxes = [textpage.get_charbox(i) for i in range(count)]
    finally:
        textpage.close()

    # page space -> fractions of the shown page, from three probe points (rotation and
    # crop box are all in PDFium's own device matrix, which has integer output)
    left, bottom, right, top = page.get_mediabox()
    width, height = (right - left) or 1.0, (top - bottom) or 1.0

    def device(x: float, y: float) -> tuple[float, float]:
        dx, dy = ctypes.c_int(), ctypes.c_int()
        raw.FPDF_PageToDevice(
            page.raw, 0, 0, SCALE, SCALE, 0, x, y, ctypes.byref(dx), ctypes.byref(dy)
        )
        return dx.value / SCALE, dy.value / SCALE

    o, ux, uy = device(left, bottom), device(right, bottom), device(left, top)
    a, b = (ux[0] - o[0]) / width, (uy[0] - o[0]) / height
    c, d = (ux[1] - o[1]) / width, (uy[1] - o[1]) / height

    def place(box) -> Box:
        corners = [(box[0] - left, box[1] - bottom), (box[2] - left, box[3] - bottom)]
        pts = [(o[0] + a * x + b * y, o[1] + c * x + d * y) for x, y in corners]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return clamp_box((min(xs), min(ys), max(xs), max(ys)))

    lines: list[Line] = []
    chars: list[tuple[str, Box]] = []

    def flush() -> None:
        text = "".join(t for t, _ in chars).strip()
        if text:
            lines.append(
                Line(
                    text,
                    (
                        min(b[0] for _, b in chars),
                        min(b[1] for _, b in chars),
                        max(b[2] for _, b in chars),
                        max(b[3] for _, b in chars),
                    ),
                )
            )
        chars.clear()

    for ch, raw_box in zip(texts, boxes, strict=True):
        if ch in "\r\n" or (raw_box[2] - raw_box[0] == 0 and raw_box[3] - raw_box[1] == 0):
            flush()
            continue
        box = place(raw_box)
        if chars:
            ly0 = min(b[1] for _, b in chars)
            ly1 = max(b[3] for _, b in chars)
            lx1 = max(b[2] for _, b in chars)
            height = ly1 - ly0
            overlap = min(ly1, box[3]) - max(ly0, box[1])
            small = min(height, box[3] - box[1]) or height or 1e-6
            same_row = overlap / small >= 0.5
            gap = box[0] - lx1
            if not same_row or gap > 2.5 * max(height, box[3] - box[1]) or gap < -0.05:
                flush()
        chars.append((ch, box))
    flush()
    return lines
