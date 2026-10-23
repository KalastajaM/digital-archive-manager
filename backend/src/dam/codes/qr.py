"""Read filing-code QR stickers, and the tick boxes beside them, off a scanned page.

The QR's corner points give a frame in modules (``sticker`` geometry), so a sticker
read at any angle or scale maps onto the printed layout. Print and scan never line up
exactly, so each box pair is first registered on its printed outline: the offset (within
``SEARCH`` modules, in ``STEP`` steps) where the outlines of both boxes are darkest.
Then the share of dark pixels inside each box, ``INSET`` in from its outline, says
whether it is ticked. The thresholds come from a blind trial on real scans.
"""

import math
from dataclasses import dataclass
from typing import Literal

import zxingcpp
from PIL import Image

from dam.codes import sticker

Tick = Literal["ticked", "empty", "unclear"]

DARK = 128  # a pixel darker than this is ink
INSET = 0.15  # of the box side, measured in from each edge
TICKED = 0.01  # dark share at or above: ticked
EMPTY = 0.005  # dark share below: empty; in between: unclear
SEARCH = 1.5  # registration search, modules either way
STEP = 0.25  # registration step, modules
EDGE_SAMPLES = 30  # points along each box edge when registering
SAMPLES_PER_PX = 2  # inside a box, sample points per pixel along each side


@dataclass(frozen=True)
class QrRead:
    """A dam sticker found on a page. ``star``/``important``: the tick boxes (None for
    the plain layout, which has none)."""

    code: str
    layout: int
    star: Tick | None = None
    important: Tick | None = None


def read_qr(image: Image.Image) -> list[QrRead]:
    """The dam stickers on ``image`` (one page), in the order zxing finds them, without
    duplicates. QR codes that are not dam payloads are ignored."""
    page = image if image.mode == "L" else image.convert("L")
    reads: list[QrRead] = []
    for hit in zxingcpp.read_barcodes(page, formats=(zxingcpp.BarcodeFormat.QRCode,)):
        parsed = sticker.parse_payload(hit.text)
        if parsed is None:
            continue
        code, layout = parsed
        read = QrRead(code, layout)
        if layout == 1:
            star, important = _Frame(page, hit.position).ticks()
            read = QrRead(code, layout, star, important)
        if read not in reads:
            reads.append(read)
    return reads


def judge(share: float) -> Tick:
    if share >= TICKED:
        return "ticked"
    if share < EMPTY:
        return "empty"
    return "unclear"


class _Frame:
    """Module coordinates of one QR (origin its top-left corner) mapped onto the page."""

    def __init__(self, page: Image.Image, position) -> None:
        n = sticker.QR_VERSION_MODULES
        tl, tr, bl = position.top_left, position.top_right, position.bottom_left
        self.pixels = page.load()
        self.width, self.height = page.size
        self.origin = (tl.x, tl.y)
        self.ux = ((tr.x - tl.x) / n, (tr.y - tl.y) / n)  # one module along x
        self.uy = ((bl.x - tl.x) / n, (bl.y - tl.y) / n)  # one module along y

    def _pixel(self, mx: float, my: float) -> tuple[int, int] | None:
        x = self.origin[0] + mx * self.ux[0] + my * self.uy[0]
        y = self.origin[1] + mx * self.ux[1] + my * self.uy[1]
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        return int(x), int(y)

    def _dark_share(self, points: list[tuple[float, float]]) -> float:
        """Dark share of the on-page ``points``; 0 when none is on the page."""
        on_page = [p for p in (self._pixel(x, y) for x, y in points) if p is not None]
        if not on_page:
            return 0.0
        return sum(self.pixels[p] < DARK for p in on_page) / len(on_page)

    def ticks(self) -> tuple[Tick, Tick]:
        rects = sticker.box_rects(1)
        dx, dy = self._register(list(rects.values()))
        star, important = (self._judge_box(x + dx, y + dy, side) for x, y, side in rects.values())
        return star, important

    def _register(self, rects: list[tuple[float, float, float]]) -> tuple[float, float]:
        """The offset, in modules, that puts the box outlines on the darkest pixels."""
        steps = round(SEARCH / STEP)
        grid = [i * STEP for i in range(-steps, steps + 1)]
        best = (-1.0, 0.0, 0.0)
        for dx in grid:
            for dy in grid:
                score = self._dark_share(
                    [p for x, y, side in rects for p in _outline(x + dx, y + dy, side)]
                )
                # ties go to the offset nearest the printed position
                if score > best[0] or (
                    score == best[0] and math.hypot(dx, dy) < math.hypot(best[1], best[2])
                ):
                    best = (score, dx, dy)
        return best[1], best[2]

    def _judge_box(self, x: float, y: float, side: float) -> Tick:
        corners = [(x, y), (x + side, y), (x, y + side), (x + side, y + side)]
        if any(self._pixel(*c) is None for c in corners):
            return "unclear"  # partly off the page
        inset = side * INSET
        inner = side - 2 * inset
        module_px = max(math.hypot(*self.ux), math.hypot(*self.uy))
        n = max(8, math.ceil(inner * module_px * SAMPLES_PER_PX))
        points = [
            (x + inset + inner * (a + 0.5) / n, y + inset + inner * (b + 0.5) / n)
            for a in range(n)
            for b in range(n)
        ]
        return judge(self._dark_share(points))


def _outline(x: float, y: float, side: float) -> list[tuple[float, float]]:
    points = []
    for k in range(EDGE_SAMPLES):
        t = side * (k + 0.5) / EDGE_SAMPLES
        points += [(x + t, y), (x + t, y + side), (x, y + t), (x + side, y + t)]
    return points
