"""Printable sticker sheets: the label grids and the HTML page that prints them.

A sheet is one HTML document (A4, no page margin) with every label absolutely placed in
mm. Each sticker is drawn in one inline SVG whose origin is the QR's top-left corner and
whose unit is one QR module (``MODULE_MM``), so the tick boxes land exactly where the
reader looks for them (``sticker.box_rects``). The code and the ``!`` are SVG text; the
label is HTML text so its width centres the sticker on the label. Nothing is loaded from
elsewhere: no fonts, scripts or images.
"""

import html
import logging
import math
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from dam.codes import sticker
from dam.codes.model import FilingCode
from dam.config import DEFAULTS_DIR
from dam.rules.model import read_yaml

log = logging.getLogger(__name__)

DEFAULTS_FILE = DEFAULTS_DIR / "sticker_sheets.yaml"
CUSTOM_FILE = "sticker_sheets.yaml"  # in the config folder
CUSTOM_ID = "custom"
A4_W, A4_H = 210.0, 297.0
FIT_SLACK = 0.05  # mm of rounding a grid may overshoot the page by
MAX_STICKERS = 2000

QR_MM = 12.0
MODULE_MM = QR_MM / sticker.QR_VERSION_MODULES
N = sticker.QR_VERSION_MODULES
BOXES_W = sticker.STAR_SLOT + sticker.BOX + sticker.GAP + sticker.BANG_SLOT + sticker.BOX
CODE_PT = 11.0
BANG_PT = 11.0
CAP = 0.716  # cap height of Arial/Helvetica, in em
FONT = "Arial, Helvetica, 'Liberation Sans', sans-serif"
LABEL_MARGIN_MM = 2.0  # kept free across the label (1 mm each side)
MIN_LABEL_W = (sticker.X0 + BOXES_W) * MODULE_MM + 1.0
MIN_LABEL_H = QR_MM + 1.0
NOTE = "Print at 100 %, without fit to page."


class SheetLayout(BaseModel):
    """A grid of labels on an A4 page, in mm."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=80)
    columns: int = Field(ge=1, le=20)
    rows: int = Field(ge=1, le=40)
    label_w_mm: float = Field(gt=0)
    label_h_mm: float = Field(gt=0)
    top_mm: float = Field(ge=0)
    left_mm: float = Field(ge=0)
    gap_x_mm: float = Field(ge=0)
    gap_y_mm: float = Field(ge=0)
    cut_lines: bool = False

    @model_validator(mode="after")
    def _fits(self) -> "SheetLayout":
        if self.label_w_mm < MIN_LABEL_W or self.label_h_mm < MIN_LABEL_H:
            raise ValueError(
                f"a label must be at least {MIN_LABEL_W:.1f} x {MIN_LABEL_H:.1f} mm "
                "to hold a sticker"
            )
        right = self.left_mm + self.columns * self.label_w_mm + (self.columns - 1) * self.gap_x_mm
        bottom = self.top_mm + self.rows * self.label_h_mm + (self.rows - 1) * self.gap_y_mm
        if right > A4_W + FIT_SLACK or bottom > A4_H + FIT_SLACK:
            raise ValueError(
                f"the labels reach {right:.1f} x {bottom:.1f} mm, beyond an A4 page (210 x 297 mm)"
            )
        return self

    @property
    def per_page(self) -> int:
        return self.columns * self.rows

    def position(self, i: int) -> tuple[float, float]:
        """``(left, top)`` in mm of label ``i`` (0-based) on its page."""
        col, row = i % self.columns, i // self.columns
        return (
            self.left_mm + col * (self.label_w_mm + self.gap_x_mm),
            self.top_mm + row * (self.label_h_mm + self.gap_y_mm),
        )


def _read_list(path: Path) -> list:
    _, data = read_yaml(path)
    if not isinstance(data, list):
        raise ValueError("the file must be a list of layouts")
    return data


def builtin_layouts() -> list[SheetLayout]:
    return [SheetLayout.model_validate(d) for d in _read_list(DEFAULTS_FILE)]


def custom_layout(config_dir: Path) -> SheetLayout | None:
    """The saved custom layout, or None. Only the entry with id ``custom`` counts (a
    fresh install copies the defaults file here; its built-ins are ignored)."""
    path = config_dir / CUSTOM_FILE
    if not path.exists():
        return None
    try:
        for d in _read_list(path):
            if isinstance(d, dict) and d.get("id") == CUSTOM_ID:
                return SheetLayout.model_validate(d)
    except (ValueError, ValidationError):
        log.warning("custom sticker sheet in %s skipped", path, exc_info=True)
    return None


def load_layouts(config_dir: Path) -> list[SheetLayout]:
    """The built-in layouts, then the saved custom one if there is one."""
    custom = custom_layout(config_dir)
    return [*builtin_layouts(), *([custom] if custom else [])]


def save_custom(config_dir: Path, layout: SheetLayout) -> SheetLayout:
    """Write ``layout`` as the custom layout (the file it replaces is kept as
    ``.bak-<time>``; restored if the new file does not read back)."""
    layout = layout.model_copy(update={"id": CUSTOM_ID})
    path = config_dir / CUSTOM_FILE
    original = path.read_bytes() if path.exists() else None
    if original is not None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            with open(path.with_name(f"{path.name}.bak-{stamp}"), "xb") as fh:
                fh.write(original)
        except FileExistsError:
            pass  # a backup from this very second exists already
    text = "# The custom sticker sheet layout (mm), written by dam.\n" + yaml.safe_dump(
        [layout.model_dump(mode="json")], allow_unicode=True, sort_keys=False
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        if custom_layout(config_dir) != layout:
            raise OSError("the custom layout did not read back as written")
    except (OSError, ValueError, yaml.YAMLError):
        with open(path, "wb") as f:  # no file before: an empty one (never delete)
            f.write(original or b"")
        raise
    return layout


# --- text widths (Helvetica metrics, em) to shrink a label to one line ---

_W = {" ": 0.278, "!": 0.278, ".": 0.278, ",": 0.278, "-": 0.333, "(": 0.333, ")": 0.333}
_W.update(dict.fromkeys("0123456789", 0.556))
_W.update(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", (
    0.667, 0.667, 0.722, 0.722, 0.667, 0.611, 0.778, 0.722, 0.278, 0.5, 0.667, 0.556, 0.833,
    0.722, 0.778, 0.667, 0.778, 0.722, 0.667, 0.611, 0.722, 0.667, 0.944, 0.667, 0.667, 0.611,
), strict=True))
_W.update(zip("abcdefghijklmnopqrstuvwxyz", (
    0.556, 0.556, 0.5, 0.556, 0.556, 0.278, 0.556, 0.556, 0.222, 0.222, 0.5, 0.222, 0.833,
    0.556, 0.556, 0.556, 0.556, 0.333, 0.5, 0.278, 0.556, 0.5, 0.722, 0.5, 0.5, 0.5,
), strict=True))


def _em(text: str) -> float:
    total = 0.0
    for ch in text:
        base = unicodedata.normalize("NFD", ch)[:1] or ch
        total += _W.get(base, 0.6)
    return total


def _room_mm(layout: SheetLayout) -> float:
    return layout.label_w_mm - LABEL_MARGIN_MM - sticker.X0 * MODULE_MM


def label_pt(label: str, layout: SheetLayout) -> float:
    """The label's font size: 6.5 pt, shrunk in 0.25 pt steps to 5 pt to fit one line."""
    room_pt = _room_mm(layout) / 25.4 * 72
    pt = sticker.LABEL_PT_MAX
    while pt > sticker.LABEL_PT_MIN and _em(label) * pt > room_pt:
        pt -= 0.25
    return max(pt, sticker.LABEL_PT_MIN)


# --- HTML ---


def _n(v: float) -> str:
    return f"{v:.4f}".rstrip("0").rstrip(".") or "0"


_SVG_SIZE = re.compile(r'<svg[^>]*\bwidth="(\d+)"')
_SVG_PATH = re.compile(r'<path d="([^"]*)"')


def _qr_group(code: str, layout: int) -> str:
    """The QR's modules as one SVG path, shifted so module (0, 0) is at the origin."""
    svg = sticker.qr_svg(code, layout)
    size = int(_SVG_SIZE.search(svg).group(1))
    paths = _SVG_PATH.findall(svg)
    if len(paths) != 1:
        raise ValueError("unexpected QR drawing")
    quiet = _n((size - N) / 2)
    return f'<g class="qr" transform="translate(-{quiet} -{quiet})"><path d="{paths[0]}"/></g>'


def _star(x: float, y: float, side: float) -> str:
    """A solid 5-point star in the slot left of a box at ``(x, y)``, about 65 % of its height."""
    r, cx, cy = side * 0.34, x + side * 0.33, y + side * 0.53
    pts = []
    for k in range(10):
        rr = r if k % 2 == 0 else r * 0.42
        a = k * math.pi / 5
        pts.append(f"{_n(cx + rr * math.sin(a))},{_n(cy - rr * math.cos(a))}")
    return f'<polygon points="{" ".join(pts)}"/>'


def _sticker(fc: FilingCode, layout: SheetLayout, boxes: bool, blank: bool) -> str:
    code = html.escape(fc.code)
    em = CODE_PT / 72 * 25.4 / MODULE_MM  # code font size in modules
    width = sticker.X0 + BOXES_W if boxes else N
    parts = [
        _qr_group(fc.code, 1 if boxes else 0),
        f'<text x="{sticker.X0}" y="{_n(em * CAP)}" font-size="{_n(em)}" '
        f'font-weight="bold">{code}</text>',
    ]
    if boxes:
        rects = sticker.box_rects(1)
        sx, sy, side = rects["star"]
        parts.append(_star(sx - sticker.STAR_SLOT, sy, side))
        ix, iy, iside = rects["important"]
        bang = BANG_PT / 72 * 25.4 / MODULE_MM
        parts.append(
            f'<text x="{_n(ix - sticker.BANG_SLOT)}" y="{_n(iy + iside / 2 + bang * CAP / 2)}" '
            f'font-size="{_n(bang)}" font-weight="bold">!</text>'
        )
        for name, (x, y, s) in rects.items():
            parts.append(
                f'<rect data-box="{name}" x="{_n(x)}" y="{_n(y)}" width="{_n(s)}" height="{_n(s)}" '
                'fill="none" stroke="#000" stroke-width="0.35"/>'
            )
    svg = (
        f'<svg class="sticker" xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width} {N}" width="{_n(width * MODULE_MM)}mm" height="{_n(QR_MM)}mm" '
        f'style="left:0mm;top:0mm">{"".join(parts)}</svg>'
    )
    label = "" if blank else fc.label
    column = BOXES_W * MODULE_MM if boxes else _em(fc.code) * 0.8 * CODE_PT / 72 * 25.4
    min_w = sticker.X0 * MODULE_MM + column  # border-box: the padding (QR + gap) counts
    text = (
        f'<div class="text" style="font-size:{_n(label_pt(label, layout))}pt;'
        f'max-width:{_n(_room_mm(layout))}mm">{html.escape(label)}</div>'
    )
    return (
        f'<div class="st" style="padding-left:{_n(sticker.X0 * MODULE_MM)}mm;'
        f'min-width:{_n(min_w)}mm">{svg}{text}</div>'
    )


_CSS = f"""
@page {{ size: A4; margin: 0 }}
* {{ box-sizing: border-box }}
html, body {{ margin: 0; padding: 0; background: #fff; color: #000 }}
body {{ font-family: {FONT} }}
.note {{ margin: 4mm; font-size: 11pt }}
.page {{ position: relative; width: {_n(A4_W)}mm; height: {_n(A4_H)}mm; overflow: hidden;
  break-after: page; page-break-after: always }}
.page:last-child {{ break-after: auto; page-break-after: auto }}
.label {{ position: absolute; display: flex; align-items: center; justify-content: center;
  overflow: hidden }}
.label.cut {{ border: 0.1mm dashed #999 }}
.label.outline {{ border: 0.2mm solid #000 }}
.st {{ position: relative; height: {_n(QR_MM)}mm }}
.st svg {{ position: absolute; overflow: visible; fill: #000; font-family: {FONT} }}
.text {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  line-height: {_n(QR_MM)}mm }}
@media screen {{
  body {{ background: #ddd }}
  .page {{ background: #fff; margin: 0 auto 6mm; box-shadow: 0 0 2mm #888 }}
}}
@media print {{ .note {{ display: none }} }}
"""


def render_sheet(
    codes: list[FilingCode],
    counts: dict[str, int],
    layout: SheetLayout,
    start_at: int = 1,
    boxes: bool = True,
    blank_labels: bool = False,
    outlines_only: bool = False,
) -> str:
    """The printable sheet as a complete HTML document.

    Each code is printed ``counts[code]`` times (1 when absent), in the order of
    ``codes``, from label ``start_at`` (1-based) on the first page; the rest flow onto
    more pages. ``boxes`` adds the star and important tick boxes (payload ``dam:1:``);
    ``blank_labels`` leaves the label text out to write by hand; ``outlines_only`` (the
    test print) draws only the outlines of every label on the pages the print would use.
    Raises ``ValueError`` for a ``start_at`` off the sheet or too many stickers.
    """
    if not 1 <= start_at <= layout.per_page:
        raise ValueError(f"start at a label from 1 to {layout.per_page}")
    queue = [fc for fc in codes for _ in range(max(0, counts.get(fc.code, 1)))]
    if len(queue) > MAX_STICKERS:
        raise ValueError(f"at most {MAX_STICKERS} stickers at once")
    slots = start_at - 1 + len(queue)
    n_pages = max(1, math.ceil(slots / layout.per_page))

    pages: list[list[str]] = [[] for _ in range(n_pages)]
    w, h = _n(layout.label_w_mm), _n(layout.label_h_mm)

    def box(i: int) -> str:
        left, top = layout.position(i)
        return f"left:{_n(left)}mm;top:{_n(top)}mm;width:{w}mm;height:{h}mm"

    if outlines_only:
        for page in pages:
            page.extend(
                f'<div class="label outline" style="{box(i)}"></div>'
                for i in range(layout.per_page)
            )
    else:
        cls = "label cut" if layout.cut_lines else "label"
        for k, fc in enumerate(queue):
            slot = start_at - 1 + k
            p, i = divmod(slot, layout.per_page)
            pages[p].append(
                f'<div class="{cls}" data-code="{html.escape(fc.code)}" style="{box(i)}">'
                f"{_sticker(fc, layout, boxes, blank_labels)}</div>"
            )
    body = "".join(f'<div class="page">{"".join(labels)}</div>' for labels in pages)
    title = "Filing code test print" if outlines_only else "Filing code stickers"
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        f"<title>{title}</title><style>{_CSS}</style></head>"
        f'<body><p class="note">{NOTE}</p>{body}</body></html>\n'
    )
