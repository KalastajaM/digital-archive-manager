"""PDF fixtures generated on the fly (no committed binaries)."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from dam.demo import TEXT, barcode_image, make_text_pdf  # noqa: F401 - shipped with the demo


def make_scan_pdf(path: Path, text: str = TEXT) -> Path:
    """Image-only PDF: the text is drawn into a bitmap, no text layer."""
    img = Image.new("RGB", (1600, 400), "white")
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 96)
    except OSError:
        font = ImageFont.load_default(size=96)
    ImageDraw.Draw(img).text((40, 120), text, fill="black", font=font)
    img.save(path, "PDF")
    return path


def make_barcode_pdf(path: Path, widths: list[int], page: int = 1) -> Path:
    """Image-only PDF (300 dpi, A4-ish) with the barcode drawn on page ``page``; any
    earlier pages are blank."""
    blank = Image.new("L", (2480, 3508), 255)
    sheet = blank.copy()
    sheet.paste(barcode_image(widths), (300, 2800))
    pages = [blank.copy() for _ in range(page - 1)] + [sheet]
    pages[0].save(path, "PDF", resolution=300, save_all=True, append_images=pages[1:])
    return path
