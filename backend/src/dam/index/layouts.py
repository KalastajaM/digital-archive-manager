"""Read where the text of page 1 sits, for files indexed before positions were kept
(the layout pass of ``ContentIndexer``). New files get theirs while their content is
extracted (``dam.extract``)."""

import io
from pathlib import Path

import pypdfium2
from PIL import Image

from dam.extract import ocr
from dam.extract.base import UnsupportedContent
from dam.extract.layout import TEXT_LAYER, Page1Layout, text_layer_lines
from dam.extract.pdf import OCR_DPI
from dam.pdfium import PDFIUM_LOCK

IMAGE_EXTS = {"jpg", "jpeg", "png"}


def read_layout(
    path: Path, ext: str, data: bytes | None, *, ocr_used: bool, languages: list[str]
) -> Page1Layout:
    """Page 1 of a PDF or image with the position of each line. A PDF whose indexed text
    came from its text layer (``ocr_used`` false) is read from that layer, with no OCR;
    a scan is rendered at the indexer's resolution and read by the OCR engine with the
    indexer's languages. ``UnsupportedContent`` when OCR is needed and no engine is
    installed (or the file cannot be read)."""
    ext = ext.lower().lstrip(".")
    if ext == "pdf":
        if not ocr_used:
            with PDFIUM_LOCK:
                doc = _open(path, data)
                try:
                    if len(doc) == 0:
                        return Page1Layout([], TEXT_LAYER)
                    page = doc[0]
                    try:
                        return Page1Layout(text_layer_lines(page), TEXT_LAYER)
                    finally:
                        page.close()
                finally:
                    doc.close()
        if ocr.engine() is None:
            raise UnsupportedContent(ocr.NO_OCR)
        with PDFIUM_LOCK:
            doc = _open(path, data)
            try:
                if len(doc) == 0:
                    return Page1Layout([], TEXT_LAYER)
                page = doc[0]
                try:
                    image = page.render(scale=OCR_DPI / 72).to_pil()
                finally:
                    page.close()
            finally:
                doc.close()
        return ocr.ocr_page(image, languages)  # the PDFium lock is not held during OCR
    if ext in IMAGE_EXTS:
        if ocr.engine() is None:
            raise UnsupportedContent(ocr.NO_OCR)
        with Image.open(io.BytesIO(data) if data is not None else path) as img:
            img.load()
            return ocr.ocr_page(img, languages)
    raise UnsupportedContent(f"no page 1 to read in a .{ext} file")


def _open(path: Path, data: bytes | None) -> pypdfium2.PdfDocument:
    try:
        return pypdfium2.PdfDocument(data if data is not None else str(path))
    except pypdfium2.PdfiumError as exc:
        raise UnsupportedContent(f"cannot open PDF: {exc}") from exc
