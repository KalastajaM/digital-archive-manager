"""Where the text of page 1 sits: lines with boxes, as fractions of the page.

A box is ``(x0, y0, x1, y1)`` with the origin at the top left of the page as it is shown
(after the page's own rotation). Lines come from a PDF's text layer or from the OCR that
reads a scan; ``source`` says which (``"text-layer"``, ``"vision"`` or ``"tesseract"``).
"""

from __future__ import annotations

import ctypes
import json
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

TEXT_LAYER = "text-layer"
SCALE = 10000  # PDFium's device matrix works in whole pixels: ask for a fine one

Box = tuple[float, float, float, float]

# What a box CONTAINS (what the owner sees listed for a drawn box) uses no margin: words
# at least half inside the box itself. Matching a rule on other documents grows the box
# by ZONE_MARGIN = (across, down), as fractions of the page, because scans shift a few
# millimetres between letters. Across 0.02 is about 4 mm on A4 (210 mm), down 0.006 about
# 1.8 mm (297 mm). Down is much smaller on purpose: in a normal letter (12 pt type on a
# 14 pt pitch) the boxes of two lines are only about 1 mm apart, so a tight box grown by
# 0.01 already holds more than half of the line below. With 0.006 that neighbour stays
# at about a fifth inside, while a copy shifted 3 mm up or down still has more than half
# of the line in the box (it holds up to about 4 mm) and a sideways shift of 4 mm is fine.
ZONE_MARGIN = (0.02, 0.006)
NO_MARGIN = (0.0, 0.0)

Margin = float | tuple[float, float]


@dataclass(frozen=True)
class Word:
    text: str
    box: Box


@dataclass(frozen=True)
class Line:
    """A line of text with its box. ``words`` (each with its own box) is empty for a line
    read before word positions were kept: such a line is matched as a whole."""

    text: str
    box: Box
    words: list[Word] = field(default_factory=list, compare=True)


@dataclass
class Page1Layout:
    lines: list[Line] = field(default_factory=list)
    source: str = TEXT_LAYER
    # the grayscale page-1 picture (a PIL image, ``dam.extract.picture``) when this read
    # rendered the page anyway: kept in the cache by whoever saves the layout, never stored
    # with the lines
    picture: Any = field(default=None, repr=False, compare=False)

    @property
    def text(self) -> str:
        """The lines joined, one per row: page 1's text as this read saw it."""
        return "\n".join(line.text for line in self.lines)

    def lines_json(self) -> str:
        rows = []
        for ln in self.lines:
            row: dict[str, Any] = {"text": ln.text, "box": [round(v, 5) for v in ln.box]}
            if ln.words:
                row["words"] = [
                    {"text": w.text, "box": [round(v, 5) for v in w.box]} for w in ln.words
                ]
            rows.append(row)
        return json.dumps(rows, ensure_ascii=False)

    def stored(self) -> bytes:
        """``lines_json`` as ``file_layouts.lines`` keeps it: zlib-compressed (migration
        0045; about a fifth of the size)."""
        return zlib.compress(self.lines_json().encode(), 6)

    @classmethod
    def from_stored(cls, lines: bytes | str, source: str) -> Page1Layout:
        """``from_json`` of a ``file_layouts.lines`` value (a str: JSON stored before
        0045). ``zlib.error`` or ``ValueError`` when it cannot be read."""
        if isinstance(lines, bytes):
            lines = zlib.decompress(lines).decode()
        return cls.from_json(lines, source)

    @classmethod
    def from_json(cls, lines: str, source: str) -> Page1Layout:
        raw = json.loads(lines)
        return cls(
            [
                Line(
                    r["text"],
                    tuple(float(v) for v in r["box"]),
                    # rows stored before word positions were kept have no "words"
                    [
                        Word(w["text"], tuple(float(v) for v in w["box"]))
                        for w in r.get("words") or []
                    ],
                )
                for r in raw
            ],
            source,
        )


def clamp_box(box: Sequence[float]) -> Box:
    x0, y0, x1, y1 = (min(1.0, max(0.0, float(v))) for v in box)
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def check_box(box: Sequence[float]) -> Box:
    """``box`` as ``(x0, y0, x1, y1)`` with 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1;
    ``ValueError`` otherwise."""
    if len(box) != 4 or not all(isinstance(v, int | float) and 0 <= v <= 1 for v in box):
        raise ValueError("a box is four numbers between 0 and 1: x0, y0, x1, y1")
    x0, y0, x1, y1 = (float(v) for v in box)
    if not (x0 < x1 and y0 < y1):
        raise ValueError("a box needs x0 < x1 and y0 < y1")
    return (x0, y0, x1, y1)


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


def grown(box: Sequence[float], margin: Margin = ZONE_MARGIN) -> Box:
    """``box`` grown by ``margin`` on every side: one number for both axes, or
    ``(across, down)``."""
    mx, my = (margin, margin) if isinstance(margin, (int, float)) else margin
    x0, y0, x1, y1 = box
    return clamp_box((x0 - mx, y0 - my, x1 + mx, y1 + my))


def in_zone(line: Line, box: Sequence[float], margin: Margin = ZONE_MARGIN) -> bool:
    """The line lies in ``box``: at least half of it is inside the box grown by ``margin``."""
    return share_inside(line.box, grown(box, margin)) >= 0.5


def estimate_words(text: str, box: Box) -> list[Word]:
    """Word boxes for a line whose engine gives only the box of the whole line (Apple
    Vision through ocrmac): an ESTIMATE that shares the line's width among its words in
    proportion to their characters, spaces included. Good enough to tell the left part of
    a line from the right; a proportional font is off by a few letters."""
    parts = text.split()
    if not parts:
        return []
    x0, y0, x1, y1 = box
    total = sum(len(p) for p in parts) + len(parts) - 1
    step = (x1 - x0) / total
    out: list[Word] = []
    at = 0
    for p in parts:
        out.append(Word(p, (x0 + at * step, y0, x0 + (at + len(p)) * step, y1)))
        at += len(p) + 1
    return out


def union(boxes: Sequence[Box]) -> Box:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def lines_in_zone(
    lines: Sequence[Line], box: Sequence[float], margin: Margin = NO_MARGIN
) -> list[Line]:
    """The text of page 1 in ``box``, one ``Line`` per line of the page that has any.
    No margin by default: this is what the box contains. Pass ``ZONE_MARGIN`` to match.

    A line with word positions contributes the words that are at least half inside the
    grown box (joined with spaces, in reading order, with the box that holds those words);
    a line that has all its words in comes back as it is. A line without word positions (an
    old row) counts whole when half of it is inside."""
    area = grown(box, margin)
    out: list[Line] = []
    for ln in lines:
        if not ln.words:
            if share_inside(ln.box, area) >= 0.5:
                out.append(ln)
            continue
        inside = [w for w in ln.words if share_inside(w.box, area) >= 0.5]
        if not inside:
            continue
        if len(inside) == len(ln.words):
            out.append(ln)
        else:
            out.append(
                Line(" ".join(w.text for w in inside), union([w.box for w in inside]), inside)
            )
    return out


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
    chars: list[tuple[str, Box]] = []  # characters with a real box: the geometry
    parts: list[str] = []  # the text of the line, which also has the boxless characters
    words: list[Word] = []  # the words of the line so far
    word_text: list[str] = []  # the word being read, and the boxes of its sized characters
    word_boxes: list[Box] = []

    def end_word() -> None:
        text = "".join(word_text).strip()
        if text and word_boxes:
            words.append(Word(text, union(word_boxes)))
        word_text.clear()
        word_boxes.clear()

    def flush() -> None:
        end_word()
        text = "".join(parts).strip()
        if text and chars:
            lines.append(Line(text, union([b for _, b in chars]), list(words)))
        chars.clear()
        parts.clear()
        words.clear()

    for ch, raw_box in zip(texts, boxes, strict=True):
        if ch in "\r\n":
            flush()
            continue
        if raw_box[2] - raw_box[0] == 0 and raw_box[3] - raw_box[1] == 0:
            # PDFium's generated spaces (and other boxless characters) have no size:
            # they are text but take no part in the geometry
            if ch.isspace():
                if parts and not parts[-1].isspace():
                    parts.append(" ")
                end_word()
            else:
                parts.append(ch)
                word_text.append(ch)
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
        parts.append(ch)
        if ch.isspace():
            end_word()
        else:
            word_text.append(ch)
            word_boxes.append(box)
    flush()
    return lines
