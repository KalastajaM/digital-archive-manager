"""OCR and the image extractor built on it.

The engine is chosen at run time: Apple Vision (via ocrmac) on macOS, otherwise
Tesseract (via pytesseract) when the ``tesseract`` program is installed. With neither,
images are "unsupported: no OCR engine installed".
"""

import functools
import io
import logging
import shutil
import sys
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from dam.extract.base import ExtractedText, UnsupportedContent

log = logging.getLogger(__name__)

VISION = "vision"
TESSERACT = "tesseract"
NO_OCR = "no OCR engine installed"

# settings use Vision-style codes (fi-FI, en-US); Tesseract wants ISO 639-2 ones
TESSERACT_LANGUAGES = {"fi": "fin", "en": "eng", "sv": "swe", "de": "deu", "fr": "fra"}


def engine() -> str | None:
    """The OCR engine to use now: ``"vision"`` (macOS), ``"tesseract"`` (the program is
    on PATH and pytesseract is importable) or None."""
    if sys.platform == "darwin":
        try:
            import ocrmac  # noqa: F401
        except ImportError:
            pass
        else:
            return VISION
    if shutil.which("tesseract") is None:
        return None
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return None
    return TESSERACT


def tesseract_languages(languages: list[str]) -> str:
    """``["fi-FI", "en-US"]`` -> ``"fin+eng"``; unknown codes are skipped, none left
    means English."""
    codes: list[str] = []
    for lang in languages:
        code = TESSERACT_LANGUAGES.get(lang.split("-")[0].split("_")[0].lower())
        if code and code not in codes:
            codes.append(code)
    return "+".join(codes) or "eng"


@functools.cache
def _supported_languages() -> frozenset[str]:
    import Vision

    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(0)
    return frozenset(request.supportedRecognitionLanguagesAndReturnError_(None)[0])


def usable_languages(languages: list[str]) -> list[str] | None:
    """Languages Vision supports (it has no Finnish); None means the Vision default (en-US)."""
    supported = _supported_languages()
    usable = [lang for lang in languages if lang in supported]
    if len(usable) < len(languages):
        log.debug(
            "OCR languages not supported by Vision, skipped: %s", set(languages) - set(usable)
        )
    return usable or None


def _ocr_vision(image: Image.Image, languages: list[str]) -> str:
    from ocrmac import ocrmac

    results = ocrmac.OCR(
        image, language_preference=usable_languages(languages), recognition_level="accurate"
    ).recognize()
    return "\n".join(text for text, _confidence, _box in results)


def _ocr_tesseract(image: Image.Image, languages: list[str]) -> str:
    import pytesseract

    lang = tesseract_languages(languages)
    try:
        return pytesseract.image_to_string(image, lang=lang)
    except pytesseract.TesseractError as exc:  # typically a missing language pack
        raise UnsupportedContent(f"OCR failed: {str(exc).strip()[:200]}") from exc


def ocr_image(image: Image.Image, languages: list[str]) -> str:
    """Text of ``image``; ``UnsupportedContent`` when no OCR engine is installed."""
    which = engine()
    if which == VISION:
        return _ocr_vision(image, languages)
    if which == TESSERACT:
        return _ocr_tesseract(image, languages)
    raise UnsupportedContent(NO_OCR)


class ImageOcrExtractor:
    name = "image-ocr"
    suffixes = {".jpg", ".jpeg", ".png"}

    def __init__(self, languages: list[str]) -> None:
        self.languages = languages

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self.suffixes

    def extract(self, path: Path, data: bytes | None = None) -> ExtractedText:
        if engine() is None:
            raise UnsupportedContent(NO_OCR)
        try:
            with Image.open(io.BytesIO(data) if data is not None else path) as img:
                img.load()
                text = ocr_image(img, self.languages)
        except (UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise UnsupportedContent(f"unreadable image: {exc}") from exc
        return ExtractedText(text=text, extractor=self.name, ocr_used=True)
