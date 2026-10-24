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


def make_layout_pdf(
    path: Path,
    items: list[tuple[float, float, str]],
    *,
    size: int = 12,
    mediabox: str = "0 0 612 792",
    rotate: int = 0,
) -> Path:
    """One-page PDF with a text layer: each ``(x, y, text)`` is drawn with its baseline
    start at ``x, y`` points of the page *as shown* (origin bottom left), as one text
    line. With ``rotate`` (0, 90, 180, 270: the page's own /Rotate) the content is turned
    the other way, so the page shows the same upright text."""
    w0, h0 = (float(v) for v in mediabox.split()[2:])
    shown_w, shown_h = (w0, h0) if rotate in (0, 180) else (h0, w0)
    stream = b"BT /F1 %d Tf\n" % size
    for x, y, text in items:
        a, b, c, d, u, v = {
            0: (1, 0, 0, 1, x, y),
            90: (0, 1, -1, 0, shown_h - y, x),
            180: (-1, 0, 0, -1, shown_w - x, shown_h - y),
            270: (0, -1, 1, 0, y, shown_w - x),
        }[rotate]
        stream += b"%d %d %d %d %f %f Tm (%s) Tj\n" % (a, b, c, d, u, v, text.encode("cp1252"))
    stream += b"ET"
    rot = b" /Rotate %d" % rotate if rotate else b""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [%s] /Contents 4 0 R%s "
        b"/Resources << /Font << /F1 5 0 R >> >> >>" % (mediabox.encode(), rot),
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    path.write_bytes(bytes(out))
    return path
