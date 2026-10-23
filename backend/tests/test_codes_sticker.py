import zxingcpp

from dam.codes import sticker


def test_parse_payload():
    assert sticker.parse_payload("dam:P") == ("P", 0)
    assert sticker.parse_payload("dam:1:v3") == ("V3", 1)
    for bad in ("dam:2:P", "dam:", "dam:TOOLONG", "dam:1:", "dam:1:TOOLONG", "https://x", ""):
        assert sticker.parse_payload(bad) is None


def test_longest_payload_is_version_1():
    barcode = zxingcpp.create_barcode(
        sticker.BOXED.format(code="ABCD"), zxingcpp.BarcodeFormat.QRCode, ec_level="M"
    )
    img = barcode.to_image(scale=1, add_quiet_zones=False)
    assert tuple(img.shape[:2]) == (sticker.QR_VERSION_MODULES,) * 2 == (21, 21)
    svg = sticker.qr_svg("ABCD", 1)
    assert svg.lstrip().startswith(("<svg", "<?xml"))
    big = zxingcpp.create_barcode(
        sticker.BOXED.format(code="ABCD"), zxingcpp.BarcodeFormat.QRCode, ec_level="M"
    ).to_image(scale=8, add_quiet_zones=True)
    hits = zxingcpp.read_barcodes(big, formats=(zxingcpp.BarcodeFormat.QRCode,))
    assert [h.text for h in hits] == ["dam:1:ABCD"]


def test_box_rects():
    assert sticker.box_rects(1) == {"star": (31, 13, 8), "important": (44, 13, 8)}
