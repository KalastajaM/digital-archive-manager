"""PDF page previews: render one page to PNG, cached under ``cache_dir/pages``."""

import io
import logging
import math
import re
import threading
from pathlib import Path

import pypdfium2

from dam.errors import NotFound
from dam.index.content import MAX_BYTES
from dam.index.repo import FileRecord
from dam.pdfium import PDFIUM_LOCK

log = logging.getLogger(__name__)

# Requested widths are rounded up to a bucket, so the cache holds at most four sizes.
WIDTH_BUCKETS = (400, 900, 1400, 2000)
MAX_PIXELS = 25_000_000  # bitmap cap (width x height); a tall page renders at lower scale
_PNG_END = b"IEND\xaeB`\x82"  # the last chunk of every complete PNG file
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
# Each uncached render holds the whole PDF in memory (up to MAX_BYTES): at most two at
# once. Cache hits never wait for it.
RENDER_SEMAPHORE = threading.BoundedSemaphore(2)


def bucket_width(width: int) -> int:
    """The smallest bucket >= ``width``; the largest bucket for anything above it."""
    return next((b for b in WIDTH_BUCKETS if b >= width), WIDTH_BUCKETS[-1])


def _scale(page_w: float, page_h: float, width: int) -> float:
    scale = (width - 0.01) / page_w  # render() rounds up: land on exactly ``width``
    if (page_w * scale) * (page_h * scale) > MAX_PIXELS:
        scale = math.sqrt(MAX_PIXELS / (page_w * page_h))
    # render() rounds each side up: step down until the bitmap really fits.
    while math.ceil(page_w * scale) * math.ceil(page_h * scale) > MAX_PIXELS:
        scale *= 0.999
    return scale


def _check_size(path: Path) -> None:
    try:
        size = path.stat().st_size
    except OSError as exc:  # vanished since the request was checked, or unreadable
        raise NotFound(f"Cannot read {path.name}") from exc
    if size > MAX_BYTES:
        raise NotFound(f"{path.name} is too large to preview")


def _read(path: Path) -> bytes:
    return path.read_bytes()


def render_page(path: Path, n: int, width: int) -> bytes:
    """Page ``n`` (1-based) of the PDF at ``path`` as PNG bytes, ``width`` pixels wide.

    The bitmap never exceeds ``MAX_PIXELS`` (a very tall page comes out narrower).
    Raises ``NotFound`` for a file over ``MAX_BYTES``, a page out of range or without
    size, a file that cannot be read, and any render failure (logged). Every PDFium
    call holds ``PDFIUM_LOCK``; the PNG is encoded after the lock is released.
    """
    _check_size(path)
    try:
        data = _read(path)  # outside PDFIUM_LOCK: a slow cloud read never stalls the indexer
        with PDFIUM_LOCK:
            doc = pypdfium2.PdfDocument(data)
            try:
                if not 1 <= n <= len(doc):
                    raise NotFound(f"Page {n} of {path.name}")
                page = doc[n - 1]
                try:
                    page_w, page_h = page.get_size()
                    if not (page_w > 0 and page_h > 0):
                        raise NotFound(f"Page {n} of {path.name} has no size")
                    bitmap = page.render(scale=_scale(page_w, page_h, width))
                    try:
                        # The image keeps the Python-allocated pixel buffer alive (or
                        # holds its own copy), so it stays valid after close().
                        image = bitmap.to_pil()
                    finally:
                        bitmap.close()
                finally:
                    page.close()
            finally:
                doc.close()
        out = io.BytesIO()
        image.save(out, format="PNG")
        return out.getvalue()
    except NotFound:
        raise
    except Exception as exc:  # noqa: BLE001 - PdfiumError, MemoryError, PIL errors, ...
        log.warning("cannot render page %d of %s", n, path, exc_info=True)
        raise NotFound(f"Cannot render page {n} of {path.name}") from exc


def cache_key(rec: FileRecord) -> str:
    """The content hash when known (the scanner clears it when the file changes), else
    the drive id plus mtime."""
    if rec.sha256:
        return rec.sha256
    return f"{_UNSAFE.sub('_', rec.drive_id)}_{rec.mtime or 0:.6f}".replace(".", "-")


def _complete_png(data: bytes) -> bool:
    return data.startswith(b"\x89PNG") and data.endswith(_PNG_END)


def cached_page(cache_dir: Path, rec: FileRecord, path: Path, n: int, width: int) -> bytes:
    """``render_page`` through the cache ``cache_dir/<key>_<n>_<bucket>.png``.

    ``width`` is rounded up to a bucket first. Rendering (stat, read, render, write)
    holds ``RENDER_SEMAPHORE``; a cache hit does not. A new cache file is written with
    exclusive create (another request may have written it first: its copy is kept);
    a cache file that is not a complete PNG (an interrupted write) is overwritten in
    place. Nothing is renamed or deleted.
    """
    width = bucket_width(width)
    target = cache_dir / f"{cache_key(rec)}_{n}_{width}.png"
    cached = _read_cache(target)
    if cached is not None and _complete_png(cached):
        return cached
    with RENDER_SEMAPHORE:
        cached = _read_cache(target)  # rendered by another request while we waited?
        if cached is not None and _complete_png(cached):
            return cached
        png = render_page(path, n, width)
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(target, "wb" if cached is not None else "xb") as f:
                f.write(png)
        except FileExistsError:
            pass  # written concurrently: serve what we rendered
        return png


def _read_cache(target: Path) -> bytes | None:
    try:
        return target.read_bytes()
    except FileNotFoundError:
        return None
