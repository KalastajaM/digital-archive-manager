"""The page-1 picture: a small grayscale picture of page 1, kept in the cache for picture
areas (a rule that recognises a logo, ``dam.rules.picture``).

It is made at a fixed width (``PICTURE_PAGE_WIDTH``) in the frame of the positions: the
page as shown, after the page's own rotation (PDFium) and the EXIF orientation of an image
(``ocr.upright``). Grayscale and low resolution on purpose: a few tens of KB, tolerant of
the colour and the DPI of a scan. It is cache: made again when missing or when the file's
content (its sha256) changes; nothing is ever deleted.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from PIL import Image

PICTURE_PAGE_WIDTH = 1000
JPEG_QUALITY = 70
PICTURE_DIR = "page1"
MAX_HEIGHT = 8000  # a very long scan is cut here, never larger in memory

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def picture_name(drive_id: str, sha256: str) -> str:
    """The cache file name for a file's content: ``<drive id>-<sha256[:16]>.jpg`` (a
    character that is not safe in a file name on every platform, such as the colon of a
    ``local:`` id, becomes ``_``)."""
    return f"{_UNSAFE.sub('_', drive_id)}-{sha256[:16]}.jpg"


def picture_path(cache_dir: Path, drive_id: str, sha256: str) -> Path:
    return Path(cache_dir) / PICTURE_DIR / picture_name(drive_id, sha256)


def page_picture(image: Image.Image) -> Image.Image:
    """``image`` (page 1 as shown) as an 8-bit grayscale picture ``PICTURE_PAGE_WIDTH``
    wide."""
    width, height = image.size
    if width <= 0 or height <= 0:
        raise ValueError("an empty picture")
    gray = image if image.mode == "L" else image.convert("L")
    new_height = min(MAX_HEIGHT, max(1, round(height * PICTURE_PAGE_WIDTH / width)))
    method = Image.Resampling.LANCZOS if width > PICTURE_PAGE_WIDTH else Image.Resampling.BICUBIC
    return gray.resize((PICTURE_PAGE_WIDTH, new_height), method)


def encode(picture: Image.Image) -> bytes:
    out = io.BytesIO()
    picture.save(out, "JPEG", quality=JPEG_QUALITY)
    return out.getvalue()


def write_picture(cache_dir: Path, drive_id: str, sha256: str, picture: Image.Image) -> Path:
    """Keep ``picture`` as the page-1 picture of this content (replacing one with the same
    name). One write of the whole file, so a reader sees all of it or fails to decode it
    (which counts as no picture)."""
    path = picture_path(cache_dir, drive_id, sha256)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode(picture))
    return path


def have_pictures(cache_dir: Path) -> set[str]:
    """The names of the page-1 pictures in the cache (one directory listing)."""
    folder = Path(cache_dir) / PICTURE_DIR
    try:
        return {p.name for p in folder.iterdir() if p.suffix == ".jpg"}
    except OSError:
        return set()
