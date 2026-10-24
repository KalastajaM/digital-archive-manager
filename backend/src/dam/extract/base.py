"""Extractor protocol and registry."""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from dam.extract.layout import Page1Layout


class UnsupportedContent(Exception):
    """Recognised file type whose content cannot be read (encrypted, corrupt, bad image)."""


@dataclass
class ExtractedText:
    text: str
    extractor: str
    ocr_used: bool = False
    # where the text of page 1 sits (PDFs and images); the page-1 part of ``text`` is
    # taken from the same read
    page1: Page1Layout | None = None


class Extractor(Protocol):
    name: str

    def supports(self, path: Path) -> bool: ...

    def extract(self, path: Path, data: bytes | None = None) -> ExtractedText:
        """Extract text; ``data`` is the file's bytes when already read (else open ``path``)."""
        ...


class ExtractorRegistry:
    def __init__(self) -> None:
        self._extractors: list[Extractor] = []

    def register(self, ex: Extractor) -> None:
        self._extractors.append(ex)

    def for_path(self, path: Path) -> Extractor | None:
        """First registered extractor that supports ``path``."""
        return next((ex for ex in self._extractors if ex.supports(path)), None)

    def extract(self, path: Path, data: bytes | None = None) -> ExtractedText | None:
        ex = self.for_path(path)
        return ex.extract(path, data) if ex else None


def default_registry(ocr_languages: list[str]) -> ExtractorRegistry:
    from dam.extract.docx import DocxExtractor
    from dam.extract.iwork import IworkExtractor
    from dam.extract.msg import MsgExtractor
    from dam.extract.ocr import ImageOcrExtractor
    from dam.extract.office import PptxExtractor, XlsExtractor, XlsxExtractor
    from dam.extract.pdf import PdfExtractor
    from dam.extract.text import TextExtractor
    from dam.extract.textutil import TextutilExtractor

    registry = ExtractorRegistry()
    registry.register(PdfExtractor(ocr_languages))
    registry.register(TextExtractor())
    registry.register(MsgExtractor())
    registry.register(DocxExtractor())
    registry.register(XlsxExtractor())
    registry.register(XlsExtractor())
    registry.register(PptxExtractor())
    if sys.platform == "darwin":  # textutil ships with macOS only
        registry.register(TextutilExtractor())
    registry.register(IworkExtractor(ocr_languages))
    registry.register(ImageOcrExtractor(ocr_languages))
    return registry
