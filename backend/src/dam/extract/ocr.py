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

from PIL import Image, ImageOps, UnidentifiedImageError

from dam.extract.base import ExtractedText, UnsupportedContent
from dam.extract.layout import Line, Page1Layout, clamp_box

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


def _vision_lines(image: Image.Image, languages: list[str]) -> list[Line]:
    from ocrmac import ocrmac

    results = ocrmac.OCR(
        image, language_preference=usable_languages(languages), recognition_level="accurate"
    ).recognize()
    lines = []
    for text, _confidence, (x, y, w, h) in results:
        # Vision boxes are fractions of the image with the origin at the bottom left
        lines.append(Line(text, clamp_box((x, 1 - (y + h), x + w, 1 - y))))
    return lines


def _tesseract_lines(image: Image.Image, languages: list[str]) -> list[Line]:
    import pytesseract

    try:
        data = pytesseract.image_to_data(
            image, lang=tesseract_languages(languages), output_type=pytesseract.Output.DICT
        )
    except pytesseract.TesseractError as exc:  # typically a missing language pack
        raise UnsupportedContent(f"OCR failed: {str(exc).strip()[:200]}") from exc
    width, height = image.size
    grouped: dict[tuple[int, int, int], list[tuple[str, int, int, int, int]]] = {}
    for i, word in enumerate(data["text"]):
        if not str(word).strip():
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        grouped.setdefault(key, []).append(
            (
                str(word).strip(),
                data["left"][i],
                data["top"][i],
                data["width"][i],
                data["height"][i],
            )
        )
    lines = []
    for words in grouped.values():
        box = clamp_box(
            (
                min(w[1] for w in words) / width,
                min(w[2] for w in words) / height,
                max(w[1] + w[3] for w in words) / width,
                max(w[2] + w[4] for w in words) / height,
            )
        )
        lines.append(Line(" ".join(w[0] for w in words), box))
    return lines


def ocr_page(image: Image.Image, languages: list[str]) -> Page1Layout:
    """The lines of text of ``image`` with their boxes and the engine that read them;
    ``UnsupportedContent`` when no OCR engine is installed. The text of the page is
    ``Page1Layout.text``: the very lines the boxes belong to."""
    which = engine()
    if which == VISION:
        return Page1Layout(_vision_lines(image, languages), VISION)
    if which == TESSERACT:
        return Page1Layout(_tesseract_lines(image, languages), TESSERACT)
    raise UnsupportedContent(NO_OCR)


def ocr_image(image: Image.Image, languages: list[str]) -> str:
    """Text of ``image``; ``UnsupportedContent`` when no OCR engine is installed."""
    which = engine()
    if which == VISION:
        return _ocr_vision(image, languages)
    if which == TESSERACT:
        return _ocr_tesseract(image, languages)
    raise UnsupportedContent(NO_OCR)


def upright(img: Image.Image) -> Image.Image:
    """``img`` turned the way it is shown (EXIF orientation applied), so the OCR boxes are
    in the frame of what the browser displays."""
    return ImageOps.exif_transpose(img) or img


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
                page = ocr_page(upright(img), self.languages)
        except (UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise UnsupportedContent(f"unreadable image: {exc}") from exc
        # the indexed text and the page-1 lines are one read
        return ExtractedText(text=page.text, extractor=self.name, ocr_used=True, page1=page)
