"""PDF text layer via pypdfium2, falling back to OCR for scans."""

import logging
from pathlib import Path

import pypdfium2

from dam.extract import ocr
from dam.extract.base import ExtractedText, UnsupportedContent
from dam.extract.layout import TEXT_LAYER, Page1Layout, text_layer_lines
from dam.pdfium import PDFIUM_LOCK

MIN_CHARS_PER_PAGE = 20
OCR_MAX_PAGES = 20
OCR_DPI = 200
PASSWORD_PDF = "password-protected PDF"

log = logging.getLogger(__name__)


def _text_layer_page1(page) -> Page1Layout | None:
    """Page 1's lines from the text layer (PDFium lock held); None if they cannot be
    placed, which never fails the extraction."""
    try:
        return Page1Layout(text_layer_lines(page), TEXT_LAYER)
    except Exception:
        log.warning("could not place the text of page 1", exc_info=True)
        return None


class PdfExtractor:
    name = "pdf"

    def __init__(self, languages: list[str]) -> None:
        self.languages = languages

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".pdf"

    def extract(self, path: Path, data: bytes | None = None) -> ExtractedText:
        # The PDFium lock is held only for PDFium work, never during OCR.
        with PDFIUM_LOCK:
            try:
                doc = pypdfium2.PdfDocument(data if data is not None else str(path))
            except pypdfium2.PdfiumError as exc:  # encrypted or corrupt
                if getattr(exc, "err_code", None) == pypdfium2.raw.FPDF_ERR_PASSWORD:
                    raise UnsupportedContent(PASSWORD_PDF) from exc
                raise UnsupportedContent(f"cannot open PDF: {exc}") from exc
        try:
            with PDFIUM_LOCK:
                pages = len(doc)
                texts = []
                page1 = None
                for i in range(pages):
                    page = doc[i]
                    textpage = page.get_textpage()
                    texts.append(textpage.get_text_range())
                    textpage.close()
                    if i == 0:
                        page1 = _text_layer_page1(page)
                    page.close()
            text = "\n".join(texts)
            if not pages or len(text.strip()) / pages >= MIN_CHARS_PER_PAGE:
                return ExtractedText(text=text, extractor=self.name, ocr_used=False, page1=page1)
            if ocr.engine() is None:  # a scan we cannot read
                if text.strip():
                    return ExtractedText(
                        text=text, extractor=self.name, ocr_used=False, page1=page1
                    )
                raise UnsupportedContent(ocr.NO_OCR)
            ocr_texts = []
            ocr_page1 = None
            for i in range(min(pages, OCR_MAX_PAGES)):
                with PDFIUM_LOCK:
                    page = doc[i]
                    image = page.render(scale=OCR_DPI / 72).to_pil()
                    page.close()
                if i == 0:
                    # one OCR call gives page 1's text and its lines: the zone words
                    # are always in the indexed text
                    ocr_page1 = ocr.ocr_page(image, self.languages)
                    ocr_texts.append(ocr_page1.text)
                else:
                    ocr_texts.append(ocr.ocr_image(image, self.languages))
            return ExtractedText(
                text="\n".join(ocr_texts), extractor=self.name, ocr_used=True, page1=ocr_page1
            )
        finally:
            with PDFIUM_LOCK:
                doc.close()
