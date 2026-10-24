"""The page-1 picture: a small grayscale picture of page 1, kept in the cache for picture
areas (a rule that recognises a logo, ``dam.rules.picture``).

It is made at a fixed width (``PICTURE_PAGE_WIDTH``) in the frame of the positions: the
page as shown, after the page's own rotation (PDFium) and the EXIF orientation of an image
(``ocr.upright``). Grayscale and low resolution on purpose: a few tens of KB, tolerant of
the colour and the DPI of a scan. It is cache: made again when missing or when the file's
content (its sha256) changes. ``prune_page1_pictures`` removes the stale ones; it is the only
remover here (pinned in the AST no-delete test) and touches only this cache folder, never
the archive.
"""

from __future__ import annotations

import io
import logging
import re
import stat
from collections.abc import Iterable
from pathlib import Path

from PIL import Image

PICTURE_PAGE_WIDTH = 1000
JPEG_QUALITY = 70
PICTURE_DIR = "page1"
MAX_HEIGHT = 8000  # a very long scan is cut here, never larger in memory

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
_CACHE_NAME = re.compile(r"[A-Za-z0-9_-]+-[0-9a-f]{16}\.jpg")
log = logging.getLogger(__name__)


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


def prune_page1_pictures(cache_dir: Path, current: Iterable[tuple[str, str]]) -> list[str]:
    """Remove the stale page-1 pictures from ``<cache_dir>/page1``; returns the removed
    names. ``current`` is the (drive id, sha256) of every indexed file: a picture stays
    only when its name is one of theirs, so a picture of an unknown file or of content the
    file no longer has goes.

    This is dam's own cache, never the archive. Only regular, non-symlink files directly
    inside the resolved folder, named exactly like ``picture_name`` makes them, are
    touched; a folder that is a symlink or does not resolve to inside ``cache_dir`` is
    left alone."""
    keep = {picture_name(d, s) for d, s in current if s}
    base = Path(cache_dir).resolve()
    folder = base / PICTURE_DIR
    try:
        if folder.is_symlink() or not folder.is_dir():
            return []
        folder = folder.resolve()
        if folder.parent != base:
            return []
        names = sorted(p.name for p in folder.iterdir())
    except OSError:
        return []
    removed: list[str] = []
    for name in names:
        if name in keep or not _CACHE_NAME.fullmatch(name):
            continue
        entry = folder / name
        try:
            if not stat.S_ISREG(entry.lstat().st_mode) or entry.resolve().parent != folder:
                continue
            entry.unlink()
            removed.append(name)
        except OSError:
            log.warning("could not remove the stale page-1 picture %s", entry, exc_info=True)
    return removed
