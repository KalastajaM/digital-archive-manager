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
