"""Printable filing-code sticker sheets: grid positions, sticker geometry, the API."""

import re
from html import unescape
from html.parser import HTMLParser

import pytest
import zxingcpp
from PIL import Image, ImageDraw

from dam.codes import sheets, sticker
from dam.codes.model import FilingCode
from dam.config import AppPaths
from test_api import LOCAL_ORIGIN, make_client

MODULE_MM = 12 / 21
CODES = [
    FilingCode(code="P", label="To pay"),
    FilingCode(code="A", label="<b>To</b> action & more"),
]


class _Doc(HTMLParser):
    """Every element as ``(tag, attrs, depth)`` plus the text inside each label."""

    def __init__(self) -> None:
        super().__init__()
        self.elements: list[tuple[str, dict[str, str]]] = []
        self.labels: list[dict] = []
        self.pages = 0
        self._stack: list[str] = []
        self._label_depth: int | None = None

    def handle_starttag(self, tag, attrs):
        a = {k: v or "" for k, v in attrs}
        self.elements.append((tag, a))
        classes = a.get("class", "").split()
        if "page" in classes:
            self.pages += 1
        if "label" in classes:
            self.labels.append({**a, "page": self.pages, "text": "", "svgs": []})
            self._label_depth = len(self._stack)
        if tag == "svg" and self._label_depth is not None:
            self.labels[-1]["svgs"].append(a)
        if tag not in ("rect", "path", "polygon", "br", "meta"):
            self._stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()
        if self._label_depth is not None and len(self._stack) <= self._label_depth:
            self._label_depth = None

    def handle_data(self, data):
        if self._label_depth is not None:
            self.labels[-1]["text"] += data


def parse(html: str) -> _Doc:
    doc = _Doc()
    doc.feed(html)
    return doc


def mm(style: str, prop: str) -> float:
    m = re.search(rf"(?:^|;)\s*{prop}:\s*([\d.]+)mm", style)
    assert m, f"{prop} not in {style!r}"
    return float(m.group(1))


def l7651() -> sheets.SheetLayout:
    return next(lay for lay in sheets.builtin_layouts() if lay.id == "l7651")


def printed(doc: _Doc) -> list[dict]:
    return [lab for lab in doc.labels if lab.get("data-code")]


def test_builtin_layouts():
    lays = {lay.id: lay for lay in sheets.builtin_layouts()}
    assert set(lays) == {"l7651", "plain"}
    a = lays["l7651"]
    assert a.name == "Avery Zweckform L7651 (65 per sheet, 38.1 x 21.2 mm)"
    assert (a.columns, a.rows, a.label_w_mm, a.label_h_mm) == (5, 13, 38.1, 21.2)
    assert (a.top_mm, a.left_mm, a.gap_x_mm, a.gap_y_mm, a.cut_lines) == (10.7, 4.7, 2.5, 0, False)
    p = lays["plain"]
    assert p.name == "Plain paper, cut out (65 per sheet, 38.1 x 21.2 mm)" and p.cut_lines
    grid = ("columns", "rows", "label_w_mm", "label_h_mm")
    grid += ("top_mm", "left_mm", "gap_x_mm", "gap_y_mm")
    assert all(getattr(p, k) == getattr(a, k) for k in grid)


def test_sheet_positions_match_layout():
    html = sheets.render_sheet(CODES, {"P": 65, "A": 0}, l7651())
    assert "@page { size: A4; margin: 0 }" in html
    labels = printed(parse(html))
    assert len(labels) == 65
    for n, lab in enumerate(labels):
        col, row = n % 5, n // 5
        style = lab["style"]
        assert mm(style, "left") == pytest.approx(4.7 + col * 40.6)
        assert mm(style, "top") == pytest.approx(10.7 + row * 21.2)
        assert mm(style, "width") == pytest.approx(38.1)
        assert mm(style, "height") == pytest.approx(21.2)
    # the grid is symmetric on the page: same margin right and bottom as left and top
    assert mm(labels[-1]["style"], "left") + 38.1 + 4.7 == pytest.approx(209.9)
    assert mm(labels[-1]["style"], "top") + 21.2 + 10.7 == pytest.approx(297)


def test_box_positions_match_reader():
    """The boxes sit where the reader looks: ``box_rects`` modules from the QR's corner."""
    html = sheets.render_sheet(CODES[:1], {"P": 1}, l7651())
    doc = parse(html)
    (lab,) = printed(doc)
    (svg,) = [s for s in lab["svgs"] if "sticker" in s.get("class", "")]
    # the drawing's origin is the QR's top-left and one unit is one module (12/21 mm)
    vx, vy, vw, vh = (float(v) for v in svg["viewbox"].split())
    assert (vx, vy, vh) == (0, 0, 21)
    assert float(svg["width"].removesuffix("mm")) == pytest.approx(vw * MODULE_MM)
    assert float(svg["height"].removesuffix("mm")) == pytest.approx(12)
    assert mm(svg["style"], "left") == 0 and mm(svg["style"], "top") == 0
    boxes = {
        a["data-box"]: (float(a["x"]), float(a["y"]), float(a["width"]), float(a["height"]))
        for tag, a in doc.elements
        if tag == "rect" and a.get("data-box")
    }
    want = sticker.box_rects(1)
    assert {k: v[:3] for k, v in boxes.items()} == want
    assert all(v[2] == v[3] for v in boxes.values())
    # in mm from the QR's top-left
    assert boxes["star"][0] * MODULE_MM == pytest.approx(31 * 12 / 21)


def test_no_boxes_plain_payload():
    html = sheets.render_sheet(CODES[:1], {"P": 1}, l7651(), boxes=False)
    doc = parse(html)
    assert not [a for tag, a in doc.elements if tag == "rect" and a.get("data-box")]
    assert "<polygon" not in html  # no star
    assert [decode(s) for s in qr_drawings(html)] == ["dam:P"]


def test_start_at_skips_labels():
    html = sheets.render_sheet(CODES[:1], {"P": 3}, l7651(), start_at=7)
    labels = printed(parse(html))
    assert len(labels) == 3
    # label 7 is row 2, column 2
    assert mm(labels[0]["style"], "left") == pytest.approx(4.7 + 40.6)
    assert mm(labels[0]["style"], "top") == pytest.approx(10.7 + 21.2)
    with pytest.raises(ValueError):
        sheets.render_sheet(CODES[:1], {"P": 1}, l7651(), start_at=66)
    with pytest.raises(ValueError):
        sheets.render_sheet(CODES[:1], {"P": 1}, l7651(), start_at=0)


def test_counts_and_overflow():
    html = sheets.render_sheet(CODES, {"P": 60, "A": 10}, l7651(), start_at=3)
    doc = parse(html)
    labels = printed(doc)
    assert [lab["data-code"] for lab in labels] == ["P"] * 60 + ["A"] * 10
    assert doc.pages == 2
    # 63 fit on page 1 after skipping two; the rest start at the top-left of page 2
    assert [lab["page"] for lab in labels].count(1) == 63
    first_on_2 = labels[63]
    assert first_on_2["page"] == 2
    assert mm(first_on_2["style"], "left") == pytest.approx(4.7)
    assert mm(first_on_2["style"], "top") == pytest.approx(10.7)


def qr_drawings(html: str) -> list[str]:
    return re.findall(r'<g class="qr"[^>]*>.*?</g>', html, re.S)


def decode(group: str) -> str:
    """Rasterise one QR group (module rectangles) and read it back with zxing."""
    shift = re.search(r'translate\((-?[\d.]+)[ ,](-?[\d.]+)\)', group)
    dx, dy = (float(shift.group(1)), float(shift.group(2))) if shift else (0, 0)
    scale, quiet = 10, 4
    img = Image.new("L", ((21 + 2 * quiet) * scale,) * 2, 255)
    draw = ImageDraw.Draw(img)
    d = re.search(r' d="([^"]+)"', group).group(1)
    for x, y, w, h in re.findall(r"M(\d+) (\d+)h(\d+)v(\d+)h-\d+Z", d):
        x0 = (int(x) + dx + quiet) * scale
        y0 = (int(y) + dy + quiet) * scale
        draw.rectangle([x0, y0, x0 + int(w) * scale - 1, y0 + int(h) * scale - 1], fill=0)
    hits = zxingcpp.read_barcodes(img, formats=zxingcpp.BarcodeFormat.QRCode)
    assert len(hits) == 1
    return hits[0].text


def test_qr_payloads():
    html = sheets.render_sheet(CODES, {"P": 1, "A": 1}, l7651())
    assert [decode(g) for g in qr_drawings(html)] == ["dam:1:P", "dam:1:A"]
    plain = sheets.render_sheet(CODES, {"P": 1, "A": 1}, l7651(), boxes=False)
    assert [decode(g) for g in qr_drawings(plain)] == ["dam:P", "dam:A"]


def test_labels_escaped_and_blank():
    html = sheets.render_sheet(CODES, {"A": 1, "P": 0}, l7651())
    (lab,) = printed(parse(html))
    assert "<b>To</b> action & more" in lab["text"]
    assert "<b>To</b>" not in html and "&lt;b&gt;To&lt;/b&gt; action &amp; more" in html


def test_blank_labels():
    html = sheets.render_sheet(CODES, {"P": 2, "A": 1}, l7651(), blank_labels=True)
    labels = printed(parse(html))
    assert len(labels) == 3
    for lab in labels:
        # only the code and the "!" by the important box are left
        assert lab["text"].split() == [lab["data-code"] + "!"]
    assert "To pay" not in html and "action" not in html


def test_outlines_only():
    html = sheets.render_sheet(CODES, {"P": 70}, l7651(), outlines_only=True)
    doc = parse(html)
    assert doc.pages == 2
    assert not printed(doc)
    assert "<svg" not in html and "To pay" not in html
    outlines = [lab for lab in doc.labels if "outline" in lab.get("class", "")]
    assert len(outlines) == 130  # every label on each page the print would use


def test_cut_lines_and_note():
    plain = next(lay for lay in sheets.builtin_layouts() if lay.id == "plain")
    html = sheets.render_sheet(CODES[:1], {"P": 1}, plain)
    assert "cut" in printed(parse(html))[0]["class"].split()
    avery = sheets.render_sheet(CODES[:1], {"P": 1}, l7651())
    assert "cut" not in printed(parse(avery))[0]["class"].split()
    assert "Print at 100 %, without fit to page." in avery
    assert re.search(r"@media print\s*{[^}]*\.note\s*{\s*display:\s*none", avery)
    # local-first: nothing loaded from elsewhere
    assert "http" not in avery.replace('xmlns="http://www.w3.org/2000/svg"', "")
    assert "<script" not in avery


def test_label_shrinks_to_fit():
    short = sheets.label_pt("To pay", l7651())
    long = sheets.label_pt("File as suggested and more words", l7651())
    assert short == sticker.LABEL_PT_MAX
    assert long == sticker.LABEL_PT_MIN


def test_custom_layout_saved(tmp_path):
    custom = sheets.SheetLayout(
        id="x", name="Mine", columns=3, rows=8, label_w_mm=63.5, label_h_mm=33.9,
        top_mm=12.9, left_mm=7.2, gap_x_mm=2.5, gap_y_mm=0, cut_lines=False,
    )
    sheets.save_custom(tmp_path, custom)
    lays = {lay.id: lay for lay in sheets.load_layouts(tmp_path)}
    assert set(lays) == {"l7651", "plain", "custom"}
    assert lays["custom"].name == "Mine" and lays["custom"].columns == 3
    sheets.save_custom(tmp_path, custom.model_copy(update={"columns": 2}))
    assert {lay.id: lay for lay in sheets.load_layouts(tmp_path)}["custom"].columns == 2
    assert list(tmp_path.glob("sticker_sheets.yaml.bak-*"))  # the old file is kept


def test_fresh_install_has_no_sheet_file(tmp_path):
    """The built-in layouts are not config: a fresh data folder gets no sheet file."""
    paths = AppPaths(tmp_path / "data")
    paths.ensure()
    assert not (paths.config_dir / "sticker_sheets.yaml").exists()
    assert [lay.id for lay in sheets.load_layouts(paths.config_dir)] == ["l7651", "plain"]


def test_dev_seeded_list_is_ignored_quietly(tmp_path, caplog):
    """An early build of this branch seeded a list of built-ins into config."""
    (tmp_path / "sticker_sheets.yaml").write_text(
        "- id: l7651\n  name: x\n", encoding="utf-8"
    )
    assert [lay.id for lay in sheets.load_layouts(tmp_path)] == ["l7651", "plain"]
    assert not caplog.records


def test_empty_file_is_no_custom_layout(tmp_path, caplog):
    (tmp_path / "sticker_sheets.yaml").write_bytes(b"")
    assert sheets.custom_layout(tmp_path) is None
    assert not caplog.records


def test_failed_first_save_leaves_no_custom_layout(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(sheets, "custom_layout", lambda _d: None)  # read-back mismatch
    with pytest.raises(OSError):
        sheets.save_custom(tmp_path, l7651())
    monkeypatch.undo()
    assert (tmp_path / "sticker_sheets.yaml").read_bytes() == b""
    assert sheets.custom_layout(tmp_path) is None
    assert not caplog.records


def test_failed_save_restores_previous(tmp_path, monkeypatch):
    first = l7651().model_copy(update={"name": "First"})
    sheets.save_custom(tmp_path, first)
    before = (tmp_path / "sticker_sheets.yaml").read_bytes()
    monkeypatch.setattr(sheets, "custom_layout", lambda _d: None)
    with pytest.raises(OSError):
        sheets.save_custom(tmp_path, l7651().model_copy(update={"name": "Second"}))
    monkeypatch.undo()
    assert (tmp_path / "sticker_sheets.yaml").read_bytes() == before
    assert sheets.custom_layout(tmp_path).name == "First"


def test_minimum_label_size():
    base = {
        "id": "custom", "name": "Small", "columns": 1, "rows": 1, "top_mm": 0, "left_mm": 0,
        "gap_x_mm": 0, "gap_y_mm": 0,
    }
    assert sheets.MIN_LABEL_W == pytest.approx(52 * 12 / 21 + 2)  # about 31.7 mm
    sheets.SheetLayout(**base, label_w_mm=31.8, label_h_mm=14)
    for w, h in ((31.6, 14), (31.8, 13.9)):
        with pytest.raises(ValueError):
            sheets.SheetLayout(**base, label_w_mm=w, label_h_mm=h)


def test_nothing_to_print():
    with pytest.raises(ValueError, match="Nothing to print"):
        sheets.render_sheet(CODES, {"P": 0, "A": 0}, l7651())
    html = sheets.render_sheet(CODES, {"P": 0, "A": 0}, l7651(), outlines_only=True)
    assert parse(html).pages == 1


def test_too_many_stickers():
    sheets.render_sheet(CODES, {"P": 1000, "A": 1000}, l7651(), outlines_only=True)
    with pytest.raises(ValueError, match="2000"):
        sheets.render_sheet(CODES, {"P": 1000, "A": 1001}, l7651())


def test_custom_must_fit_a4():
    with pytest.raises(ValueError):
        sheets.SheetLayout(
            id="custom", name="Too big", columns=6, rows=13, label_w_mm=38.1, label_h_mm=21.2,
            top_mm=10.7, left_mm=4.7, gap_x_mm=2.5, gap_y_mm=0, cut_lines=False,
        )


# --- the API ---


def get_sheet(c, body):
    """The sheet by GET (the tab the UI opens), from a body like ``{"codes": {"P": 2},
    "layout": "l7651", "start_at": 2}``."""
    params = {
        "codes": ",".join(f"{k}:{n}" for k, n in body["codes"].items()),
        "layout": body["layout"],
    }
    for key in ("start_at", "boxes", "blank_labels", "outlines_only"):
        if key in body:
            params[key] = str(body[key]).lower()
    return c.get("/api/filing-codes/sheet", params=params)


def error_of(r):
    """The message of a sheet's HTML 400 page."""
    found = re.search(r'<p class="error">(.*?)</p>', r.text)
    assert found, r.text
    return unescape(found.group(1))


def test_there_is_no_post_sheet_route(app):
    """The UI opens the sheet by GET; one print path."""
    body = {"codes": {"P": 1}, "layout": "l7651"}
    with make_client(app) as c:
        r = c.post("/api/filing-codes/sheet", json=body, headers=LOCAL_ORIGIN)
    assert r.status_code == 405


def test_api_sheet_html(app):
    with make_client(app) as c:
        r = get_sheet(c, {"codes": {"P": 2, "A": 1}, "layout": "l7651", "start_at": 2})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    labels = printed(parse(r.text))
    assert [lab["data-code"] for lab in labels] == ["P", "P", "A"]
    assert mm(labels[0]["style"], "left") == pytest.approx(4.7 + 40.6)


def test_unknown_code_400(app):
    with make_client(app) as c:
        r = get_sheet(c, {"codes": {"P": 1, "ZZZ": 1}, "layout": "l7651"})
        assert r.status_code == 400
        assert "ZZZ" in error_of(r)
        r = get_sheet(c, {"codes": {"P": 1}, "layout": "nope"})
        assert r.status_code == 400
        r = get_sheet(c, {"codes": {"P": 1}, "layout": "l7651", "start_at": 99})
        assert r.status_code == 400
        r = get_sheet(c, {"codes": {"P": -1}, "layout": "l7651"})
        assert r.status_code == 400 and "negative" in error_of(r)
        r = get_sheet(c, {"codes": {"P": 0}, "layout": "l7651"})
        assert r.status_code == 400 and error_of(r) == "Nothing to print"
        r = get_sheet(c, {"codes": {"P": 2001}, "layout": "l7651"})
        assert r.status_code == 400 and "2000" in error_of(r)
        r = get_sheet(c, {"codes": {"P": 1000, "A": 1001}, "layout": "l7651"})
        assert r.status_code == 400 and "2000" in error_of(r)


SHEET_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)


def test_api_sheet_page_get(app):
    """The tab the UI opens: the same sheet by GET, with a policy of its own."""
    with make_client(app) as c:
        r = c.get(
            "/api/filing-codes/sheet",
            params={"codes": "P:2,A:1", "layout": "l7651", "start_at": "2", "boxes": "false"},
        )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["content-security-policy"] == SHEET_CSP
    labels = printed(parse(r.text))
    assert [lab["data-code"] for lab in labels] == ["P", "P", "A"]
    assert mm(labels[0]["style"], "left") == pytest.approx(4.7 + 40.6)
    assert "<polygon" not in r.text  # boxes=false: no tick boxes


def test_api_sheet_page_get_outlines_and_repeats(app):
    with make_client(app) as c:
        r = c.get("/api/filing-codes/sheet", params={"layout": "plain", "outlines_only": "true"})
        assert r.status_code == 200 and "Filing code test print" in r.text
        r = c.get("/api/filing-codes/sheet", params={"codes": "P:1,p:2", "layout": "l7651"})
        assert [lab["data-code"] for lab in printed(parse(r.text))] == ["P", "P", "P"]


def test_api_sheet_page_get_400_is_html(app):
    with make_client(app) as c:
        for params, says in [
            (
                {"codes": "P:1,<b>Z</b>:1", "layout": "l7651"},
                "unknown filing code: &lt;b&gt;Z&lt;/b&gt;",
            ),
            ({"codes": "P:0", "layout": "l7651"}, "Nothing to print"),
            ({"codes": "P", "layout": "l7651"}, "codes must look like P:12,A:3"),
            ({"codes": "P:x", "layout": "l7651"}, "must be a whole number"),
            ({"codes": "P:1", "layout": "l7651", "start_at": "99"}, "start at a label"),
            ({"codes": "P:1", "layout": "l7651", "boxes": "maybe"}, "boxes must be true or false"),
        ]:
            r = c.get("/api/filing-codes/sheet", params=params)
            assert r.status_code == 400, params
            assert r.headers["content-type"].startswith("text/html")
            assert r.headers["content-security-policy"] == SHEET_CSP
            assert says in r.text, (params, r.text)


def test_huge_count_is_refused_before_any_sticker_is_built(app, monkeypatch):
    """The limit is checked before any sticker is built: building one fails the test."""

    def no_sticker(*args, **kwargs):
        raise AssertionError("a sticker was built")

    monkeypatch.setattr(sheets, "_sticker", no_sticker)
    with make_client(app) as c:
        r = get_sheet(c, {"codes": {"P": 10**9}, "layout": "l7651"})
        assert r.status_code == 400 and "too many" in error_of(r)
        r = get_sheet(c, {"codes": {"P": 2000, "A": 2000}, "layout": "l7651"})
        assert r.status_code == 400 and "too many" in error_of(r)
    with pytest.raises(ValueError, match="too many"):
        sheets.render_sheet(CODES, {"P": 10**9}, l7651())


def test_api_layouts_and_custom(app):
    body = {
        "name": "Mine", "columns": 3, "rows": 8, "label_w_mm": 63.5, "label_h_mm": 33.9,
        "top_mm": 12.9, "left_mm": 7.2, "gap_x_mm": 2.5, "gap_y_mm": 0, "cut_lines": True,
    }
    with make_client(app) as c:
        ids = [lay["id"] for lay in c.get("/api/filing-codes/sheets").json()]
        assert ids == ["l7651", "plain"]
        r = c.put("/api/filing-codes/sheets/custom", json=body, headers=LOCAL_ORIGIN)
        assert r.status_code == 200, r.text
        lays = c.get("/api/filing-codes/sheets").json()
        assert [lay["id"] for lay in lays] == ["l7651", "plain", "custom"]
        r = get_sheet(c, {"codes": {"P": 1}, "layout": "custom"})
        assert r.status_code == 200
        assert mm(printed(parse(r.text))[0]["style"], "width") == pytest.approx(63.5)
        too_big = {**body, "columns": 4}
        r = c.put("/api/filing-codes/sheets/custom", json=too_big, headers=LOCAL_ORIGIN)
        assert r.status_code == 400
    assert (app.app_paths.config_dir / "sticker_sheets.yaml").exists()


def test_restore_failure_keeps_first_error(tmp_path, monkeypatch):
    """If writing the old content back fails too, the original error is raised."""
    from dam.codes import configfile

    path = tmp_path / "x.yaml"
    path.write_text("old\n", encoding="utf-8")
    real_open = open
    calls = {"n": 0}

    def flaky_open(file, mode="r", *args, **kwargs):
        if str(file) == str(path) and mode == "wb":
            raise PermissionError("restore failed")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", flaky_open)

    def verify() -> bool:
        calls["n"] += 1
        raise ValueError("read-back broke")

    with pytest.raises(ValueError, match="read-back broke"):
        configfile.write_config_file(path, "new\n", verify)
    assert calls["n"] == 1


def test_sticker_preview_draws_the_code_as_typed():
    """The Settings preview: QR, code, label and boxes from unsaved values, on white."""
    svg = sheets.sticker_preview("p", "To pay & bills")
    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"')
    assert [decode(g) for g in qr_drawings(svg)] == ["dam:1:P"]
    assert 'font-weight="bold">P</text>' in svg
    assert ">To pay &amp; bills</text>" in svg
    assert svg.count("data-box=") == 2 and '<rect x="-1" y="-1"' in svg
    plain = sheets.sticker_preview("A", "", boxes=False)
    assert [decode(g) for g in qr_drawings(plain)] == ["dam:A"]
    assert "data-box=" not in plain and plain.count("</text>") == 1


@pytest.mark.parametrize("code,label", [("", "x"), ("ABCDE", "x"), ("P-1", "x"), ("P", "y" * 25)])
def test_sticker_preview_refuses(code, label):
    with pytest.raises(ValueError):
        sheets.sticker_preview(code, label)


def test_api_sticker_preview(app):
    with make_client(app) as c:
        r = c.get("/api/filing-codes/sticker", params={"code": "R", "label": "To read"})
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("image/svg+xml")
        assert r.headers["content-security-policy"] == "default-src 'none'"
        assert [decode(g) for g in qr_drawings(r.text)] == ["dam:1:R"]
        r = c.get("/api/filing-codes/sticker", params={"code": "R", "boxes": "false"})
        assert [decode(g) for g in qr_drawings(r.text)] == ["dam:R"]
        r = c.get("/api/filing-codes/sticker", params={"code": "TOOLONG"})
        assert r.status_code == 400 and "1 to 4 letters or digits" in r.json()["error"]
