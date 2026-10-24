"""Synthetic pages for picture-area tests: a letterhead logo drawn with PIL on a page of
text-like bars, which can be shifted, scaled, brightened, noised and skewed."""

import random

import numpy as np
from PIL import Image, ImageDraw

PAGE = (1000, 1414)
LOGO_BOX = (0.05, 0.03, 0.35, 0.10)  # where the logo sits on the page, as fractions


def _logo(d: ImageDraw.ImageDraw, x: int, y: int, kind: int) -> None:
    if kind == 0:
        d.rectangle((x, y, x + 260, y + 90), fill=40)
        d.ellipse((x + 10, y + 10, x + 80, y + 80), fill=230)
        d.polygon([(x + 110, y + 78), (x + 150, y + 12), (x + 190, y + 78)], fill=200)
        d.rectangle((x + 205, y + 14, x + 245, y + 76), outline=220, width=6)
    else:  # another logo in the same place and about the same size
        d.rectangle((x, y, x + 260, y + 90), fill=70)
        d.polygon([(x + 20, y + 10), (x + 100, y + 80), (x + 20, y + 80)], fill=240)
        d.ellipse((x + 130, y + 20, x + 250, y + 70), outline=230, width=8)


def _bars(d: ImageDraw.ImageDraw, seed: int) -> None:
    rnd = random.Random(seed)
    for i in range(30):
        y = 400 + i * 30
        d.rectangle((80, y, 80 + rnd.randint(300, 800), y + 10), fill=90)


def letter(
    kind: int = 0,
    *,
    shift: tuple[int, int] = (0, 0),
    logo_scale: float = 1.0,
    seed: int = 1,
) -> Image.Image:
    """A grayscale page with the logo (``kind``) at its place, moved by ``shift`` pixels and
    drawn ``logo_scale`` times its size."""
    page = Image.new("L", PAGE, 255)
    tile = Image.new("L", (300, 130), 255)
    _logo(ImageDraw.Draw(tile), 10, 10, kind)
    if logo_scale != 1.0:
        tile = tile.resize(
            (round(300 * logo_scale), round(130 * logo_scale)), Image.Resampling.BICUBIC
        )
    page.paste(tile, (50 + shift[0], 20 + shift[1]))
    _bars(ImageDraw.Draw(page), seed)
    return page


def brightened(img: Image.Image, factor: float) -> Image.Image:
    arr = np.asarray(img, dtype=np.float32) * factor
    return Image.fromarray(np.clip(arr, 0, 255).astype("uint8"))


def noisy(img: Image.Image, sigma: float, seed: int = 0) -> Image.Image:
    arr = np.asarray(img, dtype=np.float32)
    arr = arr + np.random.default_rng(seed).normal(0, sigma, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype("uint8"))


def skewed(img: Image.Image, degrees: float) -> Image.Image:
    return img.rotate(degrees, resample=Image.Resampling.BICUBIC, fillcolor=255)


# -- dark logos and small text on white, as real letterheads have them ------------------

TEXT_LOGO_BOX = (0.05, 0.02, 0.40, 0.10)
TEXT_BLOCK_BOX = (0.05, 0.02, 0.45, 0.08)
BLOCK_A = [
    "Kansaneläkelaitos  PL 450",
    "00101 Helsinki  puh 020 634 11",
    "www.kela.fi  kela@kela.fi",
    "Y-tunnus 0000000-0 Hakemus",
    "Päätös annettu ajalla 1.2.2025",
]
BLOCK_B = [
    "Pohjola Vakuutus Oy  PL 1",
    "00013 Pohjola  puh 010 253 01",
    "www.pohjola.fi  info@pohjola.fi",
    "Y-tunnus 1111111-1 Vakuutus",
    "Maksettu ajalla 3.4.2025",
]


def _font(size: int):
    from PIL import ImageFont

    return ImageFont.load_default(size=size)


def dark_logo(kind: str) -> Image.Image:
    """A page with a dark logo on white: ``kela`` (a word), ``KELA`` (the same word in
    capitals), ``circle`` (a ring and a word), ``folk`` and ``wide`` (other words)."""
    page = Image.new("L", PAGE, 255)
    d = ImageDraw.Draw(page)
    if kind == "kela":
        d.text((60, 40), "Kela", font=_font(60), fill=20)
    elif kind == "KELA":
        d.text((60, 40), "KELA", font=_font(64), fill=0)
    elif kind == "circle":
        d.ellipse((55, 30, 125, 100), fill=20)
        d.ellipse((75, 50, 105, 80), fill=255)
        d.text((135, 50), "Pohjola", font=_font(40), fill=20)
    elif kind == "folk":
        d.text((60, 40), "Folkhalsan", font=_font(50), fill=20)
    else:
        d.text((60, 45), "Kansaneläkelaitos", font=_font(40), fill=20)
    return page


def text_block(lines: list[str]) -> Image.Image:
    """A page with a block of small text (about 8 pt) at the top: other words, same layout."""
    page = Image.new("L", PAGE, 255)
    d = ImageDraw.Draw(page)
    for i, line in enumerate(lines):
        d.text((60, 40 + i * 14), line, font=_font(11), fill=40)
    return page
