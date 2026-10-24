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
import threading
import time
from collections.abc import Iterable, Mapping
from pathlib import Path

import numpy as np
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


# -- tiny thumbnails of the pictures, to rank documents before the precise match -----------

THUMB_W = 48
THUMB_H = 68  # about the proportion of an A4 page
THUMBS_FILE = "page1-thumbs.npz"
FLUSH_EVERY_S = 60.0


def thumb_of(image: Image.Image) -> bytes:
    """The whole page as a ``THUMB_W`` x ``THUMB_H`` grayscale thumbnail (area average, the
    page stretched to the thumbnail: only the proportions of the page matter)."""
    gray = image if image.mode == "L" else image.convert("L")
    return gray.resize((THUMB_W, THUMB_H), Image.Resampling.BOX).tobytes()


def thumb_of_file(path: Path) -> bytes | None:
    """``thumb_of`` a page-1 picture in the cache (None: not there, or not all written)."""
    try:
        with Image.open(path) as img:
            img.draft("L", (THUMB_W * 4, THUMB_H * 4))
            img.load()
            return thumb_of(img)
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


class PageThumbs:
    """A tiny grayscale thumbnail of every page-1 picture, kept in one array file in the
    cache (``THUMBS_FILE``) and in memory. A rule test with a picture area scores them all
    in one numpy operation to look at the likely documents first.

    It is cache and can always be built again from the pictures: a thumbnail is added when
    the picture is made, the missing ones are made from the pictures in the cache
    (``ensure``), and a file that is torn or unreadable counts as empty. Writing is one
    write of the whole file. Nothing here removes a file."""

    def __init__(self, cache_dir: Path | None) -> None:
        self.path = None if cache_dir is None else Path(cache_dir) / THUMBS_FILE
        self._thumbs: dict[str, bytes] | None = None
        self._dirty = False
        self._flushed = float("-inf")  # the first write is not held back
        self._lock = threading.Lock()

    def _loaded(self) -> dict[str, bytes]:
        """The thumbnails (call it with the lock held)."""
        if self._thumbs is None:
            self._thumbs = {}
            if self.path is not None and self.path.is_file():
                try:
                    with np.load(self.path, allow_pickle=False) as z:
                        names, data = z["names"], z["data"]
                        if data.ndim == 2 and data.shape == (len(names), THUMB_W * THUMB_H):
                            self._thumbs = {str(n): data[i].tobytes() for i, n in enumerate(names)}
                except Exception:  # torn, empty or another format: as if there was none
                    self._thumbs = {}
                    log.warning("the page-1 thumbnails could not be read; making them again")
        return self._thumbs

    def __len__(self) -> int:
        with self._lock:
            return len(self._loaded())

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._loaded()

    def add(self, name: str, image: Image.Image) -> None:
        """Keep the thumbnail of a picture that was just made (written with the next flush)."""
        data = thumb_of(image)
        with self._lock:
            self._loaded()[name] = data
            self._dirty = True

    def add_bytes(self, name: str, data: bytes) -> None:
        with self._lock:
            self._loaded()[name] = data
            self._dirty = True

    def get_many(self, names: list[str]) -> tuple[np.ndarray, np.ndarray]:
        """``(thumbnails, present)``: an array ``(len(names), THUMB_H, THUMB_W)`` of uint8
        and which of the names have one (the others are zero rows)."""
        out = np.zeros((len(names), THUMB_H * THUMB_W), dtype=np.uint8)
        present = np.zeros(len(names), dtype=bool)
        with self._lock:
            have = self._loaded()
            for i, name in enumerate(names):
                data = have.get(name)
                if data is not None:
                    out[i] = np.frombuffer(data, dtype=np.uint8)
                    present[i] = True
        return out.reshape(len(names), THUMB_H, THUMB_W), present

    def ensure(self, wanted: Mapping[str, Path], budget_s: float = 2.0) -> int:
        """Make the thumbnails of the pictures ``wanted`` (name -> file in the cache) that
        are missing, for at most ``budget_s`` seconds. Returns how many are still missing."""
        with self._lock:
            have = self._loaded()
            todo = [n for n in wanted if n not in have]
        started = time.monotonic()
        made = 0
        for name in todo:
            if time.monotonic() - started >= budget_s:
                self.flush()
                return len(todo) - made
            data = thumb_of_file(wanted[name])
            if data is None:
                continue
            self.add_bytes(name, data)
            made += 1
        if made:
            self.flush()
        return 0

    def forget_missing(self, present: set[str]) -> int:
        """Drop thumbnails of pictures no longer in the cache (``present``: their names).
        Returns how many were dropped."""
        with self._lock:
            have = self._loaded()
            gone = [n for n in have if n not in present]
            for n in gone:
                del have[n]
            if gone:
                self._dirty = True
        return len(gone)

    def flush(self, force: bool = False) -> bool:
        """Write the thumbnails to the cache when they changed (and, unless ``force``, not
        more often than every ``FLUSH_EVERY_S``). Failure to write is only logged."""
        if self.path is None:
            return False
        with self._lock:
            if self._thumbs is None or not self._dirty:
                return False
            if not force and time.monotonic() - self._flushed < FLUSH_EVERY_S:
                return False
            names = list(self._thumbs)
            data = np.frombuffer(b"".join(self._thumbs[n] for n in names), dtype=np.uint8)
            data = data.reshape(len(names), THUMB_W * THUMB_H)
            self._dirty = False
            self._flushed = time.monotonic()
        buf = io.BytesIO()
        np.savez(buf, names=np.array(names, dtype=str), data=data)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_bytes(buf.getvalue())  # one write: a torn file reads as empty
        except OSError:
            log.warning("could not keep the page-1 thumbnails", exc_info=True)
            with self._lock:
                self._dirty = True
            return False
        return True
