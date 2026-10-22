"""Read Finnish bank barcodes off scans (PDF and JPG/PNG) with zxing-cpp."""

import io
import logging
from pathlib import Path

import pypdfium2
import zxingcpp
from PIL import Image

from dam.bills.barcode import BarcodeError, parse
from dam.pdfium import PDFIUM_LOCK

log = logging.getLogger(__name__)

MAX_PAGES = 2
DPI = 300
IMAGE_EXTS = {"jpg", "jpeg", "png"}


def _pdf_pages(path: Path, data: bytes | None) -> list[Image.Image]:
    # The PDFium lock is held only for PDFium work, never while decoding.
    with PDFIUM_LOCK:
        doc = pypdfium2.PdfDocument(data if data is not None else str(path))
        try:
            images = []
            for i in range(min(len(doc), MAX_PAGES)):
                page = doc[i]
                images.append(page.render(scale=DPI / 72, grayscale=True).to_pil())
                page.close()
            return images
        finally:
            doc.close()


def _image(path: Path, data: bytes | None) -> list[Image.Image]:
    with Image.open(io.BytesIO(data) if data is not None else path) as img:
        return [img.convert("L")]


def read_barcodes(path: Path, ext: str, data: bytes | None = None) -> list[str]:
    """Bank barcodes (Code 128) on the first pages of a PDF or in an image, in reading
    order, without duplicates; only codes ``parse`` accepts. ``data`` is the file's bytes
    when already read (else ``path`` is opened). Never raises: any error is logged and
    gives no codes."""
    ext = ext.lower().lstrip(".")
    try:
        if ext == "pdf":
            images = _pdf_pages(path, data)
        elif ext in IMAGE_EXTS:
            images = _image(path, data)
        else:
            return []
        found: list[str] = []
        for image in images:
            for hit in zxingcpp.read_barcodes(
                image, formats=zxingcpp.BarcodeFormat.Code128, text_mode=zxingcpp.TextMode.Plain
            ):
                try:
                    parse(hit.text)
                except BarcodeError:
                    continue
                if hit.text not in found:
                    found.append(hit.text)
        return found
    except Exception:
        log.warning("barcode reading failed for %s", path, exc_info=True)
        return []
