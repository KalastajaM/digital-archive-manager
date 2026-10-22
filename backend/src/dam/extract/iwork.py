"""Apple Pages, Numbers and Keynote files: the preview inside the zip bundle.

Newer files keep their content in protobuf (.iwa), which is not parsed here; the
bundle's QuickLook preview (a PDF, else a JPEG) is read instead, with OCR for pictures.
"""

import io
import zipfile
from pathlib import Path

from dam.extract.base import ExtractedText, UnsupportedContent
from dam.extract.ocr import ImageOcrExtractor
from dam.extract.pdf import PdfExtractor

NOT_IWORK = "not a valid iWork file"
NO_PREVIEW = "iWork file without a preview to read"
_PDFS = ("QuickLook/Preview.pdf", "preview.pdf")
_IMAGES = ("QuickLook/Thumbnail.jpg", "preview.jpg", "QuickLook/Preview.jpg")


class IworkExtractor:
    name = "iwork"
    suffixes = {".pages", ".numbers", ".key"}

    def __init__(self, languages: list[str]) -> None:
        self.languages = languages

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self.suffixes

    def extract(self, path: Path, data: bytes | None = None) -> ExtractedText:
        try:
            with zipfile.ZipFile(io.BytesIO(data) if data is not None else str(path)) as zf:
                names = set(zf.namelist())
                pdf = next((n for n in _PDFS if n in names), None)
                if pdf:
                    preview, extractor = zf.read(pdf), PdfExtractor(self.languages)
                else:
                    image = next((n for n in _IMAGES if n in names), None)
                    if image is None:
                        raise UnsupportedContent(NO_PREVIEW)
                    preview, extractor = zf.read(image), ImageOcrExtractor(self.languages)
        except zipfile.BadZipFile as exc:
            raise UnsupportedContent(NOT_IWORK) from exc
        got = extractor.extract(path, preview)
        return ExtractedText(text=got.text, extractor=self.name, ocr_used=got.ocr_used)
