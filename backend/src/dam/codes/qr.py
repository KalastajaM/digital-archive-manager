"""Read filing-code QR stickers, and the tick boxes beside them, off a scanned page.

The QR's corner points give a frame in modules (``sticker`` geometry), so a sticker
read at any angle or scale maps onto the printed layout. Print and scan never line up
exactly, so each box pair is first registered on its printed outline: the offset (within
``SEARCH`` modules, in ``STEP`` steps) where the outlines of both boxes are darkest.
Then the share of dark pixels inside each box, ``INSET`` in from its outline, says
whether it is ticked. The thresholds come from a blind trial on real scans. When the
outlines are not found (``OUTLINE_FLOOR``), both boxes are unclear.
"""

import math

import zxingcpp
from PIL import Image

from dam.codes import sticker
from dam.codes.qr_model import QrRead, Tick

__all__ = ["QrRead", "Tick", "judge", "read_qr"]

DARK = 128  # a pixel darker than this is ink
INSET = 0.15  # of the box side, measured in from each edge
TICKED = 0.01  # dark share at or above: ticked
EMPTY = 0.005  # dark share below: empty; in between: unclear
SEARCH = 1.5  # registration search, modules either way
STEP = 0.25  # registration step, modules
EDGE_SAMPLES = 30  # points along each box edge when registering
SAMPLES_PER_PX = 2  # inside a box, sample points per pixel along each side ...
MAX_SAMPLES = 64  # ... but at most this many, so a huge QR stays cheap
# Below this best outline score the printed boxes were not found (a foreign or old
# layout, a damaged sticker), so both boxes are unclear rather than guessed. In the
# owner's blind trial of real 300 dpi B/W ballpoint scans, correctly registered stickers
# scored as low as 27 % (thin printed lines break up in B/W); a mirrored page scores
# about 0 %.
OUTLINE_FLOOR = 0.15


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
            read = QrRead(code, layout, *_ticks(page, hit.position))
        if read not in reads:
            reads.append(read)
    return reads


def judge(share: float) -> Tick:
    if share >= TICKED:
        return "ticked"
    if share < EMPTY:
        return "empty"
    return "unclear"


def _ticks(page: Image.Image, position) -> tuple[Tick, Tick]:
    """Star and important box of the boxed sticker at ``position``. zxing reports a
    mirrored QR (a scan of the back through thin paper, a mirrored copy) as its
    transpose with no flag, so the boxes are looked for in both frames and the frame
    whose outlines register better is used."""
    rects = list(sticker.box_rects(1).values())
    best: tuple[float, float, float, _Frame] | None = None
    for transposed in (False, True):  # on a tie the normal frame wins
        frame = _Frame(page, position, transposed)
        score, dx, dy = frame.register(rects)
        if best is None or score > best[0]:
            best = (score, dx, dy, frame)
    assert best is not None
    score, dx, dy, frame = best
    if score < OUTLINE_FLOOR:
        return "unclear", "unclear"
    star, important = (frame.judge_box(x + dx, y + dy, side) for x, y, side in rects)
    return star, important


class _Frame:
    """Module coordinates of one QR (origin its top-left corner) mapped onto the page;
    ``transposed`` swaps the module axes (a mirrored sticker)."""

    def __init__(self, page: Image.Image, position, transposed: bool = False) -> None:
        n = sticker.QR_VERSION_MODULES
        tl, tr, bl = position.top_left, position.top_right, position.bottom_left
        self.pixels = page.load()
        self.width, self.height = page.size
        self.origin = (tl.x, tl.y)
        self.ux = ((tr.x - tl.x) / n, (tr.y - tl.y) / n)  # one module along x
        self.uy = ((bl.x - tl.x) / n, (bl.y - tl.y) / n)  # one module along y
        if transposed:
            self.ux, self.uy = self.uy, self.ux

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

    def register(self, rects: list[tuple[float, float, float]]) -> tuple[float, float, float]:
        """``(score, dx, dy)``: the offset, in modules, that puts the box outlines on the
        darkest pixels, and the dark share of the outlines there."""
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
        return best

    def judge_box(self, x: float, y: float, side: float) -> Tick:
        corners = [(x, y), (x + side, y), (x, y + side), (x + side, y + side)]
        if any(self._pixel(*c) is None for c in corners):
            return "unclear"  # partly off the page
        inset = side * INSET
        inner = side - 2 * inset
        module_px = max(math.hypot(*self.ux), math.hypot(*self.uy))
        n = min(MAX_SAMPLES, max(8, math.ceil(inner * module_px * SAMPLES_PER_PX)))
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
