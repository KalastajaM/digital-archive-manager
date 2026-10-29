"""Page 1 of a sample letter the owner picked to draw the address area on (Settings >
Reading documents). The file is never added to the archive or the index: the caller keeps
it in a temporary file, which is gone once this has read it."""

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from dam.api.preview import RENDER_SEMAPHORE, render_page
from dam.errors import InvalidRequest, NotFound
from dam.extract import ocr
from dam.extract.base import UnsupportedContent
from dam.extract.layout import Line
from dam.index.layouts import IMAGE_EXTS, read_layout

log = logging.getLogger(__name__)

SAMPLE_EXTS = frozenset({"pdf", *IMAGE_EXTS})
SAMPLE_WIDTH = 900  # the width of page 1 as shown (an image is never made larger)
CANNOT_READ = "dam could not read page 1 of that file."
NO_TEXT = "page 1 has no text, and there is no OCR engine to read it"


@dataclass
class SamplePage:
    png: bytes
    lines: list[Line] = field(default_factory=list)
    # why there are no lines: no text and no OCR engine, say (None: they were read)
    unavailable: str | None = None


def sample_ext(name: str) -> str:
    """The kind of file ``name`` is; InvalidRequest when it cannot be a sample letter."""
    ext = Path(name).suffix.lower().lstrip(".")
    if ext not in SAMPLE_EXTS:
        raise InvalidRequest("A sample letter is a PDF, JPG or PNG file.")
    return ext


def read_sample(path: Path, ext: str, languages: list[str]) -> SamplePage:
    """Page 1 of the PDF or image at ``path`` as a PNG, with its lines where they can be
    read: a PDF's text layer, or OCR of a scan or an image when there is an engine.
    InvalidRequest when the page cannot be shown."""
    png = _picture(path, ext)
    try:
        layout = read_layout(path, ext, None, ocr_used=False, languages=languages)
        if not layout.lines and ext == "pdf":
            # a scan without a text layer
            if ocr.engine() is None:
                return SamplePage(png, unavailable=NO_TEXT)
            layout = read_layout(path, ext, None, ocr_used=True, languages=languages)
    except UnsupportedContent as e:
        return SamplePage(png, unavailable=str(e))
    except Exception:  # noqa: BLE001 - the picture alone is still worth showing
        log.warning("could not read the lines of a sample letter", exc_info=True)
        return SamplePage(png, unavailable="dam could not read the text of page 1.")
    return SamplePage(png, layout.lines)


def _picture(path: Path, ext: str) -> bytes:
    with RENDER_SEMAPHORE:
        if ext == "pdf":
            try:
                return render_page(path, 1, SAMPLE_WIDTH)
            except NotFound as e:
                raise InvalidRequest(CANNOT_READ) from e
        try:
            with Image.open(path) as img:
                img.load()
                # upright like the OCR reads it, so the lines sit where they show
                shown = ocr.upright(img).convert("RGB")
        except Exception as e:  # noqa: BLE001 - OSError, DecompressionBombError, ...
            raise InvalidRequest(CANNOT_READ) from e
        if shown.width > SAMPLE_WIDTH:
            shown = shown.resize(
                (SAMPLE_WIDTH, max(1, round(shown.height * SAMPLE_WIDTH / shown.width)))
            )
        out = io.BytesIO()
        shown.save(out, format="PNG")
        return out.getvalue()
