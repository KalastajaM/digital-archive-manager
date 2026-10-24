"""Picture areas: does the picture of a rule's area appear where the area is on page 1?

A rule's picture zone has a crop (a grayscale PNG kept with the rule, ``config/rules/areas``)
and the page-1 picture of a document (``dam.extract.picture``, in the cache). The score is
the best normalised cross-correlation (0 to 1) of the crop over a search window (the zone's
box grown by ``SEARCH_GROW`` of the page on every side) at a few scales, after a light blur
of both. It tolerates a shift, another DPI (the scales), a lighter or darker scan (the
correlation ignores brightness and contrast) and noise; it is not for large rotations.

Everything runs on numpy at ``MATCH_WIDTH`` pixels across the page: the correlation is done
with FFTs, the local sums with integral images.
"""

from __future__ import annotations

import io
import re
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import numpy as np
from PIL import Image, ImageFilter

from dam.extract.layout import Box, clamp_box
from dam.extract.picture import PICTURE_PAGE_WIDTH, picture_path

DEFAULT_MIN_SCORE = 0.85
SEARCH_GROW = 0.05  # the search window: the box grown by this share of the page on each side
SCALES = (0.9, 0.95, 1.0, 1.05, 1.1)
MATCH_WIDTH = 500  # pixels across the page while matching (half of the stored picture)
BLUR = 1.2  # radius of the light blur, in pixels of the matching resolution
CROP_MAX_SIDE = 300  # the long side of a stored crop, in pixels
MIN_STD = 2.0  # a flat crop or a flat patch (grey levels) has no picture to match
AREAS_DIR = "areas"

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.png")


class PictureError(ValueError):
    """A picture path or crop that cannot be used."""


def check_image_path(image: str) -> str:
    """``image`` is ``areas/<name>.png``: a plain name inside the rules' ``areas`` folder.
    Returns it; ``ValueError`` otherwise."""
    parts = PurePosixPath(image).parts
    if (
        "\\" in image
        or len(parts) != 2
        or parts[0] != AREAS_DIR
        or not _NAME.fullmatch(parts[1])
        or ".." in parts[1]
    ):
        raise ValueError("a picture is areas/<name>.png, a file in the rules' areas folder")
    return image


def crop_file(rules_dir: Path, image: str) -> Path:
    """The file ``image`` names, inside ``rules_dir/areas`` (``PictureError`` when the
    path would leave it, symbolic links included)."""
    try:
        check_image_path(image)
    except ValueError as e:
        raise PictureError(str(e)) from e
    folder = (Path(rules_dir) / AREAS_DIR).resolve()
    path = (folder / PurePosixPath(image).name).resolve()
    if path.parent != folder:
        raise PictureError("a picture must lie in the rules' areas folder")
    return path


# -- cutting a crop ---------------------------------------------------------------------


def cut_crop(page: Image.Image, box: Box) -> Image.Image:
    """The part of the page-1 picture inside ``box`` (fractions of the page), 8-bit
    grayscale, its long side at most ``CROP_MAX_SIDE`` pixels."""
    width, height = page.size
    x0, y0, x1, y1 = clamp_box(box)
    left, top = int(x0 * width), int(y0 * height)
    right, bottom = max(left + 1, round(x1 * width)), max(top + 1, round(y1 * height))
    crop = page.convert("L").crop((left, top, min(right, width), min(bottom, height)))
    long_side = max(crop.size)
    if long_side > CROP_MAX_SIDE:
        k = CROP_MAX_SIDE / long_side
        crop = crop.resize(
            (max(1, round(crop.width * k)), max(1, round(crop.height * k))),
            Image.Resampling.LANCZOS,
        )
    return crop


def png_bytes(crop: Image.Image) -> bytes:
    out = io.BytesIO()
    crop.save(out, "PNG", optimize=True)
    return out.getvalue()


# -- loading ---------------------------------------------------------------------------


def _gray(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("L"), dtype=np.float32)


def load_page(path: Path) -> np.ndarray:
    """The page-1 picture at ``MATCH_WIDTH`` across, lightly blurred, as float32. The JPEG
    is decoded at half size straight away (cheap)."""
    with Image.open(path) as img:
        img.draft("L", (MATCH_WIDTH, 1))
        img.load()
        gray = img.convert("L")
    if gray.width != MATCH_WIDTH:
        height = max(1, round(gray.height * MATCH_WIDTH / gray.width))
        gray = gray.resize((MATCH_WIDTH, height), Image.Resampling.LANCZOS)
    return _gray(gray.filter(ImageFilter.GaussianBlur(BLUR)))


def _fast_len(n: int) -> int:
    """The smallest 2^a 3^b 5^c at least ``n`` (a good FFT length)."""
    best = 1
    while best < n:
        best *= 2
    p5 = 1
    while p5 < best:
        p3 = p5
        while p3 < best:
            p2 = p3
            while p2 < n:
                p2 *= 2
            best = min(best, p2)
            p3 *= 3
        p5 *= 5
    return best


@dataclass(frozen=True)
class Match:
    """How well a crop appears on a page: ``score`` 0 to 1 and, when it was found, ``box``
    (fractions of the page) where it fits best."""

    score: float
    box: Box | None = None


class Template:
    """A crop prepared for matching: resized for each scale, with its FFTs kept for the
    window sizes met so far (pages of one format share them)."""

    def __init__(self, crop: Image.Image, box: Box) -> None:
        self.box = clamp_box(box)
        self.crop = crop.convert("L")
        # the crop is the box: one factor from crop pixels to matching pixels
        self.factor = (self.box[2] - self.box[0]) * MATCH_WIDTH / max(1, self.crop.width)
        self._scaled: dict[float, np.ndarray | None] = {}
        self._fft: dict[tuple[float, int, int], tuple[np.ndarray, float]] = {}
        flat = np.asarray(self.crop, dtype=np.float32)
        self.flat = float(flat.std()) < MIN_STD

    def at(self, scale: float) -> np.ndarray | None:
        """The zero-mean template at ``scale`` (None: it would be empty or flat)."""
        if scale not in self._scaled:
            w = max(1, round(self.crop.width * self.factor * scale))
            h = max(1, round(self.crop.height * self.factor * scale))
            if w < 4 or h < 4 or self.flat:
                self._scaled[scale] = None
            else:
                img = self.crop.resize((w, h), Image.Resampling.LANCZOS)
                t = _gray(img.filter(ImageFilter.GaussianBlur(BLUR)))
                t -= t.mean()
                self._scaled[scale] = None if float(np.sqrt((t * t).sum())) < 1e-3 else t
        return self._scaled[scale]

    def spectrum(self, scale: float, shape: tuple[int, int]) -> tuple[np.ndarray, float]:
        """The conjugate FFT of the template at ``scale`` padded to ``shape``, and its
        norm."""
        key = (scale, *shape)
        if key not in self._fft:
            t = self._scaled[scale]
            assert t is not None
            norm = float(np.sqrt((t.astype(np.float64) ** 2).sum()))
            self._fft[key] = (np.conj(np.fft.rfft2(t, s=shape)), norm)
        return self._fft[key]


def match(template: Template, page: np.ndarray) -> Match:
    """The best score of ``template`` on the page (``load_page``), searching the template's
    box grown by ``SEARCH_GROW`` at each of ``SCALES``."""
    page_h, page_w = page.shape
    x0, y0, x1, y1 = template.box
    gx0, gy0, gx1, gy1 = clamp_box(
        (x0 - SEARCH_GROW, y0 - SEARCH_GROW, x1 + SEARCH_GROW, y1 + SEARCH_GROW)
    )
    wx0, wy0 = int(gx0 * page_w), int(gy0 * page_h)
    wx1, wy1 = min(page_w, round(gx1 * page_w)), min(page_h, round(gy1 * page_h))
    window = page[wy0:wy1, wx0:wx1]
    win_h, win_w = window.shape
    best, where = 0.0, None
    if win_h < 4 or win_w < 4:
        return Match(0.0)
    shape = (_fast_len(win_h), _fast_len(win_w))
    w64 = window.astype(np.float64)
    # integral images of the window and its square: the mean and variance of each patch
    s1 = np.pad(w64, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    s2 = np.pad(w64 * w64, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    spectrum = None
    for scale in SCALES:
        t = template.at(scale)
        if t is None or t.shape[0] > win_h or t.shape[1] > win_w:
            continue
        th, tw = t.shape
        out_h, out_w = win_h - th + 1, win_w - tw + 1
        if spectrum is None:
            spectrum = np.fft.rfft2(window, s=shape)
        tf, norm = template.spectrum(scale, shape)
        corr = np.fft.irfft2(spectrum * tf, s=shape)[:out_h, :out_w].astype(np.float64)
        n = th * tw

        total1 = s1[th : th + out_h, tw : tw + out_w] - s1[:out_h, tw : tw + out_w]
        total1 = total1 - s1[th : th + out_h, :out_w] + s1[:out_h, :out_w]
        total2 = s2[th : th + out_h, tw : tw + out_w] - s2[:out_h, tw : tw + out_w]
        total2 = total2 - s2[th : th + out_h, :out_w] + s2[:out_h, :out_w]
        var = total2 - total1 * total1 / n
        ok = var > (MIN_STD * MIN_STD) * n
        ncc = np.zeros_like(corr)
        np.divide(corr, np.sqrt(np.where(ok, var, 1.0)) * norm, out=ncc, where=ok)
        i = int(np.argmax(ncc))
        y, x = divmod(i, out_w)
        value = float(ncc[y, x])
        if value > best:
            best = value
            where = (wx0 + x, wy0 + y, tw, th)
    score = min(1.0, max(0.0, best))
    if where is None or score <= 0.0:
        return Match(0.0)
    px, py, tw, th = where
    found = clamp_box((px / page_w, py / page_h, (px + tw) / page_w, (py + th) / page_h))
    return Match(round(score, 4), found)


# -- what a check uses -------------------------------------------------------------------


class _Lru:
    """A small cache shared by the request threads and the indexer."""

    def __init__(self, size: int) -> None:
        self.size = size
        self.items: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            if key in self.items:
                self.items.move_to_end(key)
                return self.items[key]
        return None

    def put(self, key, value) -> None:
        with self._lock:
            self.items[key] = value
            self.items.move_to_end(key)
            while len(self.items) > self.size:
                self.items.popitem(last=False)


@dataclass
class Pictures:
    """What picture areas need to be checked: the rules' folder (the crops) and the cache
    (the page-1 pictures). Pages are read from the cache, never from the archive. Scores
    are remembered for a while (the same document is looked at again and again while a rule
    is edited, replayed and explained)."""

    rules_dir: Callable[[], Path]
    cache_dir: Path
    _pages: _Lru = field(default_factory=lambda: _Lru(6), repr=False)
    _templates: _Lru = field(default_factory=lambda: _Lru(64), repr=False)
    _scores: _Lru = field(default_factory=lambda: _Lru(20000), repr=False)

    def has_page(self, drive_id: str, sha256: str | None) -> bool:
        return bool(sha256) and picture_path(self.cache_dir, drive_id, sha256 or "").is_file()

    def _template(self, image: str, box: Box) -> tuple[Template | None, object]:
        """The prepared crop and a token that changes when the file does (None: no usable
        crop file)."""
        try:
            path = crop_file(self.rules_dir(), image)
            stat = path.stat()
            token = (str(path), stat.st_mtime_ns, stat.st_size, tuple(box))
            found = self._templates.get(token)
            if found is None:
                with Image.open(path) as img:
                    img.load()
                    found = Template(img.copy(), box)
                self._templates.put(token, found)
            return found, token
        except (OSError, PictureError, ValueError, Image.DecompressionBombError):
            return None, None

    def match(self, image: str, box: Box, drive_id: str, sha256: str | None) -> Match | None:
        """How well the crop ``image`` (the zone's picture, for ``box``) appears on page 1
        of the document. None when the document has no page-1 picture yet. A crop that
        cannot be read scores 0."""
        if not sha256:
            return None
        template, token = self._template(image, box)
        if template is None:
            return Match(0.0) if self.has_page(drive_id, sha256) else None
        path = picture_path(self.cache_dir, drive_id, sha256)
        key = (token, str(path))
        found = self._scores.get(key)
        if found is not None:
            return found
        page = self._pages.get(str(path))
        if page is None:
            try:
                page = load_page(path)
            except (OSError, ValueError, Image.DecompressionBombError):
                return None  # not there, or not all written yet: as if not made
            self._pages.put(str(path), page)
        result = match(template, page)
        self._scores.put(key, result)
        return result


__all__ = [
    "AREAS_DIR",
    "CROP_MAX_SIDE",
    "DEFAULT_MIN_SCORE",
    "PICTURE_PAGE_WIDTH",
    "Match",
    "PictureError",
    "Pictures",
    "Template",
    "check_image_path",
    "crop_file",
    "cut_crop",
    "load_page",
    "match",
    "png_bytes",
]
