"""The README screenshots, light and dark, from the staged demo server (see stage.py):
1600x1000 PNGs written to the folder given; more arguments take only those shots (the
shots taken only when named are in AFTER_CODES, and ``sticker-sheet``).

    uv run --no-project --with playwright python scripts/screenshots/shoot.py docs/images [inbox ...]
"""

import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8766"
OUT = Path(sys.argv[1])
ONLY = set(sys.argv[2:])

# A demo is staged whenever it is run: show its times as about 14:00 (a fixed-offset zone
# from UTC-12 to UTC+14; the Etc/GMT names have the sign the other way round).
_offset = (14 - datetime.now(UTC).hour + 12) % 24 - 12
TZ = f"Etc/GMT{-_offset:+d}"


def unmark_tags(page):
    """The sidebar marks every tag as the current page on /browse, whatever the filter
    (NavLink adds aria-current itself). Show only the one whose filter is open."""
    page.evaluate(
        """() => {
          const tag = new URLSearchParams(location.search).get("tag");
          document.querySelectorAll("a.sidebar-row[href^='/browse?tag=']").forEach((a) => {
            const name = new URLSearchParams(a.getAttribute("href").split("?")[1]).get("tag");
            if (name !== tag) a.removeAttribute("aria-current");
          });
        }"""
    )


def paymode(page):
    page.get_by_role("button", name="Show large barcode").click()
    page.get_by_role("dialog").wait_for()


def expand(page):
    page.get_by_role("button", name="Expand all").click()


def ai(page):
    page.get_by_role("button", name="AI", exact=True).click()
    page.wait_for_selector("[aria-label='Excluded folders']")


def boxes_letter(page, boxes):
    """Switch on Draw a box and drag each box over page 1, given as fractions of the page."""
    page.get_by_role("button", name="Draw a box").click()
    surface = page.get_by_test_id("box-surface")
    surface.wait_for()
    area = surface.bounding_box()
    for n, (x0, y0, x1, y1) in enumerate(boxes, start=1):
        page.mouse.move(area["x"] + area["width"] * x0, area["y"] + area["height"] * y0)
        page.mouse.down()
        page.mouse.move(area["x"] + area["width"] * x1, area["y"] + area["height"] * y1, steps=8)
        page.mouse.up()
        expect_count(page, "kept-box", n)
    page.get_by_text("Boxes on page 1").wait_for()
    page.get_by_text("Reading the box").first.wait_for(state="detached")
    page.get_by_text("Drag over page 1").wait_for()


def expect_count(page, test_id, n):
    page.wait_for_function(
        "([id, n]) => document.querySelectorAll(`[data-testid='${id}']`).length === n", arg=[test_id, n]
    )


def areas_off(page):
    # the address area would be drawn across the letterhead
    page.get_by_role("button", name="Show areas").click()


def areas_off_if_shown(page):
    page.get_by_role("button", name="Draw a box").wait_for()  # the preview is up
    shown = page.get_by_role("button", name="Show areas")
    try:
        shown.wait_for(timeout=5000)  # the file's rule areas come a moment later
    except PlaywrightTimeoutError:
        return
    shown.click()


def boxes(page):
    areas_off(page)
    # the letterhead and the line with the due date and total
    boxes_letter(page, [(0.05, 0.06, 0.6, 0.14), (0.05, 0.23, 0.5, 0.30)])


def rule_sheet(page):
    # one box over the letterhead of a tax letter; the rule is tested against the filed tax papers
    boxes_letter(page, [(0.0, 0.0, 1.0, 0.2)])
    page.get_by_role("button", name="Make a rule\u2026").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_text("Make a rule", exact=True).wait_for()
    # the tax office as well as the form's name: the papers filed before only have the first
    dialog.get_by_role("button", name="verohallinto").click()
    # test it against the papers already filed: drop the "only in the inbox" condition
    more = dialog.get_by_role("button", name="More conditions")
    more.click()
    dialog.get_by_label("Document is in folder").fill("")
    more.click()
    dialog.get_by_label("Folder", exact=True).fill("13. Taxes")
    tags = dialog.get_by_label("Tags")
    tags.fill("tax")
    tags.press("Enter")
    dialog.get_by_text(re.compile(r"Matches \d+ documents? you filed before")).wait_for(timeout=90000)
    dialog.get_by_role("button", name="Save", exact=True).wait_for()
    page.evaluate("document.activeElement.blur()")  # no focus ring on the tags field


AFTER_CODES = {"filing-codes", "rules"}  # taken only when named: see stage.py
TALL = (1920, 1200)
TALL_SHOTS = {"rule-sheet"}


def rules_settings(page):
    page.get_by_role("button", name="Filing rules").or_(page.get_by_text("Filing rules", exact=True)).first.click()
    page.get_by_text("Address area (percent of page 1)").wait_for()
    page.get_by_role("button", name="Add a person").scroll_into_view_if_needed()


def marked(page):
    page.get_by_text("Marked files").wait_for()
    page.get_by_role("button", name=re.compile(r"^File \d+$")).wait_for()


SHOTS = {
    "inbox": ("/inbox?file=demo-12", areas_off),
    "today": ("/", None),
    "paymode": ("/trays/to-pay?item=1", paymode),
    "browse": ("/browse?path=30.%20Home&select=demo-15", None),
    "activity": ("/activity", expand),
    "collection": ("/collections/3", areas_off_if_shown),
    "ai-settings": ("/activity", ai),
    "tags": ("/tags", None),
    "boxes": ("/inbox?file=demo-12", boxes),
    "rule-sheet": ("/inbox?file=demo-1", rule_sheet),
    # after ``stage.py codes`` only (it moves inbox files into the code folders)
    "filing-codes": ("/inbox?marked=1", marked),
    "rules": ("/settings", rules_settings),
}

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    for scheme in ("light", "dark"):
        for name, (url, then) in SHOTS.items():
            if (ONLY and name not in ONLY) or (not ONLY and name in AFTER_CODES):
                continue
            # the rule sheet is tall: a taller window at a smaller scale, same 1600x1000 image
            width, height = TALL if name in TALL_SHOTS else (1440, 900)
            ctx = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=1600 / width,
                color_scheme=scheme,
                timezone_id=TZ,
            )
            page = ctx.new_page()
            page.goto(BASE + url)
            page.wait_for_load_state("networkidle")
            if then:
                then(page)
                page.wait_for_load_state("networkidle")
            unmark_tags(page)
            page.mouse.move(width - 1, height - 1)  # no hover highlight
            page.wait_for_timeout(800)  # previews and fonts settle
            path = OUT / f"{name}-{scheme}.png"
            page.screenshot(path=str(path))
            print(path.name)
            ctx.close()
    if "sticker-sheet" in ONLY:  # only when named: its QR codes differ on every print
        # the printable sticker sheet (plain paper), the top of the page at 800 px wide, doubled
        ctx = browser.new_context(viewport={"width": 800, "height": 500}, device_scale_factor=2)
        page = ctx.new_page()
        page.goto(BASE + "/api/filing-codes/sheet?layout=plain&codes=P:10,A:10,R:10")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(OUT / "sticker-sheet.png"))
        print("sticker-sheet.png")
        ctx.close()
    browser.close()
