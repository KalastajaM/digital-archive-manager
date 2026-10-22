"""A small fictional archive for trying the app (and the "demo archive" an extra archive
can be created as): about a dozen files including two bills, one of them with a printed
Finnish bank barcode, a ``##. Ongoing`` with links, a folder and a file, fake Drive ids,
and a demo collection with nested groups. Nothing outside the folders given is touched.

    uv run python -m dam.demo <dir>      # <dir>/archive and <dir>/data

The archive folder must be empty or not exist yet.
"""

import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

from dam import setup
from dam.bills.barcode import build as build_barcode
from dam.bills.barcode import modules
from dam.config import AppPaths, SpecialFolders
from dam.index.driveid import DRIVE_ID_XATTR
from dam.services.errors import InvalidRequest

TEXT = "Kotihoito lasku 123,45 EUR"

SPECIAL = SpecialFolders()
INBOX = SPECIAL.inbox

# (archive-relative path, PDF text or None for a non-PDF)
PDFS = [
    (f"{INBOX}/scan_20261001.pdf", "Verohallinto veroilmoitus 2025 RF18 5390 0754 7034"),
    (f"{INBOX}/scan_20260915.pdf", "Apteekki kuitti 23,40 EUR 15.09.2026"),
    (f"{INBOX}/scan_0003.pdf", "Lasku 54,20 EUR FI21 1234 5600 0007 85 erapaiva 31.10.2026"),
    (
        f"{INBOX}/scan_bill.pdf",
        "Sahkoyhtio lasku. Eräpäivä 15.10.2026 Yhteensä 84,20 € "
        "IBAN FI21 1234 5600 0007 85 Viitenumero RF18 5390 0754 7034",
    ),
    ("10. Financial/Banks/20260131_Northbank statement.pdf", "Northbank tiliote tammikuu 2026"),
    ("13. Taxes/20250930_Verohallinto.pdf", "Verohallinto paatos 2024"),
    (f"{SPECIAL.important}/passport.pdf", "Passport copy"),
]


# A water bill as a scan (image only) with the bank barcode printed at its foot, drawn
# from the same modules the app's own barcode uses: indexing reads it back.
BARCODE_BILL = f"{INBOX}/scan_water_bill.pdf"
BARCODE_CODE = build_barcode("FI21 1234 5600 0007 85", Decimal("47.90"), "12344", date(2026, 11, 5))
BARCODE_BILL_LINES = [
    "Vesilaitos Oy - Lasku",
    "Vesimaksu 10/2026",
    "Saaja: Vesilaitos Oy",
    "Tilinumero: FI21 1234 5600 0007 85",
    "Viitenumero: 12344",
    "Eräpäivä: 05.11.2026",
    "Yhteensä: 47,90 EUR",
]

# A collection with nested groups: (group path, member paths); () is "Ungrouped".
DEMO_COLLECTION = "2026 House sale"
DEMO_SUMMARY = "Selling the house in spring 2026: the bank's papers, taxes and photos."
DEMO_GROUPS: list[tuple[tuple[str, ...], list[str]]] = [
    (("Paperwork",), []),
    (("Paperwork", "Bank"), ["10. Financial/Banks/20260131_Northbank statement.pdf"]),
    (("Paperwork", "Taxes"), ["13. Taxes/20250930_Verohallinto.pdf"]),
    (("Photos",), ["40. Family/beach.jpg"]),
    ((), [f"{INBOX}/scan_0003.pdf"]),  # still in the inbox: the attention strip shows it
]


_FONTS = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
)


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for name in _FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def make_text_pdf(path: Path, text: str = TEXT, mediabox: str = "0 0 612 792") -> Path:
    """Minimal hand-built one-page PDF 1.4 with a Helvetica text layer."""
    # Non-ASCII text (Finnish letters, the euro sign) is cp1252 with WinAnsiEncoding;
    # ASCII fixtures stay byte-identical to what they always were.
    stream = b"BT /F1 24 Tf 50 700 Td (%s) Tj ET" % text.encode("cp1252")
    encoding = b"" if text.isascii() else b" /Encoding /WinAnsiEncoding"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [%s] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>" % mediabox.encode(),
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica" + encoding + b" >>",
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


def barcode_image(widths: list[int], module_px: int = 4, height_px: int = 160) -> Image.Image:
    """A 1D barcode drawn from bar/space ``widths`` (bar first) as filled rectangles,
    with a 20-module quiet zone on each side."""
    quiet = 20 * module_px
    img = Image.new("L", (sum(widths) * module_px + 2 * quiet, height_px + 2 * quiet), 255)
    draw = ImageDraw.Draw(img)
    x = quiet
    for i, w in enumerate(widths):
        if i % 2 == 0:  # bars at even positions
            draw.rectangle([x, quiet, x + w * module_px - 1, quiet + height_px - 1], fill=0)
        x += w * module_px
    return img


def _make_barcode_bill(path: Path) -> Path:
    """An A4 page at 300 dpi: the bill's text, then the printed barcode."""
    page = Image.new("L", (2480, 3508), 255)
    draw = ImageDraw.Draw(page)
    y = 300
    for i, line in enumerate(BARCODE_BILL_LINES):
        draw.text((240, y), line, fill=0, font=_font(84 if i == 0 else 56))
        y += 150 if i == 0 else 100
    page.paste(barcode_image(modules(BARCODE_CODE)), (240, 2700))
    draw.text((240, 3300), BARCODE_CODE, fill=0, font=_font(40))
    page.save(path, "PDF", resolution=300)
    return path


def _tag(path: Path, n: int) -> None:
    """Give the file a fake Drive id (where the file system can hold one; without it the
    file keeps the id the scan makes up)."""
    try:
        import xattr

        xattr.setxattr(path, DRIVE_ID_XATTR, f"demo-{n}".encode())
    except (ImportError, OSError):
        pass


def _build_ongoing(archive: Path, n: int) -> None:
    """``##. Ongoing`` as in the real archive: two links, a real folder, a real file."""
    ongoing = archive / SPECIAL.ongoing
    (ongoing / "Legal").mkdir()
    for name, body in [("contract.txt", "Draft contract."), ("notes.txt", "Lawyer's notes.")]:
        n += 1
        (ongoing / "Legal" / name).write_text(body, encoding="utf-8")
        _tag(ongoing / "Legal" / name, n)
    n += 1
    (ongoing / "2026_Plan.txt").write_text("Plan for 2026.", encoding="utf-8")
    _tag(ongoing / "2026_Plan.txt", n)
    # relative links, like Finder aliases of archive items
    try:
        # separators native to the platform: Windows does not follow "/" in a relative link
        (ongoing / "2026 Sauna conversion").symlink_to(
            os.path.join("..", "30. Home"), target_is_directory=True
        )
        (ongoing / "Electricity contract").symlink_to(
            os.path.join("..", "30. Home", "Electricity", "contract.txt")
        )
    except OSError:  # Windows without the symlink privilege: no links in the demo
        pass


def check_target(archive: Path) -> None:
    """The demo archive folder must not exist yet or hold nothing (OS junk apart)."""
    if archive.exists() and not archive.is_dir():
        raise InvalidRequest(f"{archive} is a file. Pick a new or empty folder.")
    if archive.exists() and not setup.is_empty_folder(archive):
        raise InvalidRequest(f"{archive} is not empty. Pick a new or empty folder.")


def build_into(archive: Path, data_dir: Path) -> None:
    """Make the demo archive in ``archive`` (empty or new) and point the data folder
    ``data_dir`` at it (default settings; reminders off; the index scanned once)."""
    check_target(archive)
    for name in (SPECIAL.inbox, SPECIAL.ongoing, SPECIAL.important, SPECIAL.quarantine):
        (archive / name).mkdir(parents=True, exist_ok=True)
    # "11. Bills & Receipts/2026" is where the default apteekki rule files 2026 receipts.
    for folder in (
        "10. Financial/Banks",
        "11. Bills & Receipts/2026",
        "13. Taxes",
        "30. Home/Electricity",
        "40. Family",
    ):
        (archive / folder).mkdir(parents=True, exist_ok=True)

    n = 0
    for rel, text in PDFS:
        n += 1
        _tag(make_text_pdf(archive / rel, text), n)
    extras = [
        (f"{INBOX}/receipt photo.png", "png"),
        ("40. Family/beach.jpg", "jpeg"),
    ]
    for rel, fmt in extras:
        n += 1
        Image.new("RGB", (640, 480), (90, 140, 200)).save(archive / rel, fmt)
        _tag(archive / rel, n)
    for rel, body in [
        (f"{INBOX}/notes.txt", "Remember to file the electricity bill."),
        ("30. Home/Electricity/contract.txt", "Electricity contract, fixed price."),
    ]:
        n += 1
        (archive / rel).write_text(body, encoding="utf-8")
        _tag(archive / rel, n)

    n += 1
    _tag(_make_barcode_bill(archive / BARCODE_BILL), n)

    _build_ongoing(archive, n)

    data = AppPaths(data_dir)
    data.ensure()  # default settings and example rules
    settings_file = data.config_dir / "settings.yaml"
    settings = yaml.safe_load(settings_file.read_text(encoding="utf-8")) or {}
    settings["archive_root"] = str(archive)
    # a demo must never raise real notifications (dam serve checks reminders hourly)
    settings["reminders"] = {"mac": False}
    settings_file.write_text(
        yaml.safe_dump(settings, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    _build_collection(data.data_dir)


def build(root: Path) -> tuple[Path, Path]:
    """Create ``root/archive`` and ``root/data``; returns (archive, data dir). ``root``
    must be empty or not exist."""
    if root.exists() and not root.is_dir():
        raise InvalidRequest(f"{root} exists and is not a directory; pick a new or empty directory")
    if root.exists() and any(root.iterdir()):
        raise InvalidRequest(f"{root} is not empty; pick a new or empty directory")
    build_into(root / "archive", root / "data")
    return root / "archive", root / "data"


def _build_collection(data_dir: Path) -> None:
    """Scan the index, then create the demo collection with its nested groups and
    publish it: ``##. Ongoing/<collection>/<group>/<subgroup>`` links, made through
    ``dam/ops`` like every other archive write."""
    from dam.app import App

    app = App.create(data_dir)
    try:
        app.scan()
        service = app.collections
        c = service.create(DEMO_COLLECTION)
        service.set_summary(c.id, DEMO_SUMMARY, notify=False)
        groups: dict[tuple[str, ...], int | None] = {(): None}
        for path, members in DEMO_GROUPS:
            if path not in groups:
                parent = groups[path[:-1]]
                groups[path] = service.create_group(c.id, path[-1], parent, notify=False).id
            ids = []
            for rel in members:
                rec = app.repo.by_path(rel)
                assert rec is not None, rel
                ids.append(rec.drive_id)
            if ids:
                service.set_member_group(c.id, ids, groups[path], notify=False)
        service.set_summary(c.id, DEMO_SUMMARY)  # notifies: the Ongoing sync runs once
    finally:
        app.close()


def main(argv: list[str]) -> None:
    if len(argv) != 1:
        raise SystemExit("usage: python -m dam.demo <dir>")
    try:
        archive, data_dir = build(Path(argv[0]).resolve())
    except InvalidRequest as e:
        raise SystemExit(str(e)) from None
    print(f"demo archive: {archive}")
    print(f"data dir:     {data_dir}")
    print(f"serve it:     uv run dam --data-dir '{data_dir}' serve --port 8766 --no-open")


if __name__ == "__main__":
    main(sys.argv[1:])
