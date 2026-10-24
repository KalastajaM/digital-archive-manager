"""Read where the text of page 1 sits, for files indexed before positions were kept
(the layout pass of ``ContentIndexer``). New files get theirs while their content is
extracted (``dam.extract``).

The same pass makes the page-1 picture (``dam.extract.picture``): a read that renders the
page for OCR gives it along; a text-layer PDF is rendered once more for it, and
``render_picture`` makes it alone for a file whose layout is read already."""

import io
import logging
from pathlib import Path

import pypdfium2
from PIL import Image

from dam.extract import ocr
from dam.extract.base import UnsupportedContent
from dam.extract.layout import TEXT_LAYER, Page1Layout, text_layer_lines
from dam.extract.pdf import OCR_DPI
from dam.extract.picture import PICTURE_PAGE_WIDTH, page_picture
from dam.pdfium import PDFIUM_LOCK

log = logging.getLogger(__name__)

IMAGE_EXTS = {"jpg", "jpeg", "png"}


def _render_page(page) -> Image.Image | None:
    """The page-1 picture of an open PDFium page (call it with the lock held); None if it
    cannot be rendered, which never fails a layout read."""
    try:
        width = page.get_size()[0] or 1.0
        return page_picture(page.render(scale=PICTURE_PAGE_WIDTH / width).to_pil())
    except Exception:
        log.warning("could not render page 1 for its picture", exc_info=True)
        return None


def render_picture(path: Path, ext: str, data: bytes | None) -> Image.Image:
    """The grayscale page-1 picture of a PDF or image, in the frame of the positions (the
    page's own rotation, the EXIF orientation of an image). ``UnsupportedContent`` when the
    file cannot be rendered. No OCR engine is needed."""
    ext = ext.lower().lstrip(".")
    if ext == "pdf":
        with PDFIUM_LOCK:
            doc = _open(path, data)
            try:
                if len(doc) == 0:
                    raise UnsupportedContent("a PDF without pages")
                page = doc[0]
                try:
                    width = page.get_size()[0] or 1.0
                    image = page.render(scale=PICTURE_PAGE_WIDTH / width).to_pil()
                finally:
                    page.close()
            finally:
                doc.close()
        return page_picture(image)
    if ext in IMAGE_EXTS:
        try:
            with Image.open(io.BytesIO(data) if data is not None else path) as img:
                img.load()
                return page_picture(ocr.upright(img))
        except (OSError, Image.DecompressionBombError) as exc:
            raise UnsupportedContent(f"unreadable image: {exc}") from exc
    raise UnsupportedContent(f"no page 1 to render in a .{ext} file")


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
                        return Page1Layout(
                            text_layer_lines(page), TEXT_LAYER, picture=_render_page(page)
                        )
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
            return ocr.ocr_page(ocr.upright(img), languages)
    raise UnsupportedContent(f"no page 1 to read in a .{ext} file")


def _open(path: Path, data: bytes | None) -> pypdfium2.PdfDocument:
    try:
        return pypdfium2.PdfDocument(data if data is not None else str(path))
    except pypdfium2.PdfiumError as exc:
        raise UnsupportedContent(f"cannot open PDF: {exc}") from exc
