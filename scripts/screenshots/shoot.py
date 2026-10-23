"""The README screenshots, light and dark, from the staged demo server (see stage.py):
1600x1000 PNGs written to the folder given; more arguments take only those shots.

    uv run --no-project --with playwright python scripts/screenshots/shoot.py docs/images [inbox ...]
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8766"
OUT = Path(sys.argv[1])
ONLY = set(sys.argv[2:])

# A demo is staged whenever it is run: show its times as about 14:00 (a fixed-offset zone
# from UTC-12 to UTC+14; the Etc/GMT names have the sign the other way round).
_offset = (14 - datetime.now(UTC).hour + 12) % 24 - 12
TZ = f"Etc/GMT{-_offset:+d}"


def paymode(page):
    page.get_by_role("button", name="Show large barcode").click()
    page.get_by_role("dialog").wait_for()


def expand(page):
    page.get_by_role("button", name="Expand all").click()


def ai(page):
    page.get_by_role("button", name="AI", exact=True).click()
    page.wait_for_selector("[aria-label='Excluded folders']")


SHOTS = {
    "inbox": ("/inbox?file=demo-12", None),
    "today": ("/", None),
    "paymode": ("/trays/to-pay?item=1", paymode),
    "browse": ("/browse?path=30.%20Home&select=demo-15", None),
    "activity": ("/activity", expand),
    "collection": ("/collections/3", None),
    "ai-settings": ("/activity", ai),
}

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    for scheme in ("light", "dark"):
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=1600 / 1440,
            color_scheme=scheme,
            timezone_id=TZ,
        )
        page = ctx.new_page()
        for name, (url, then) in SHOTS.items():
            if ONLY and name not in ONLY:
                continue
            page.goto(BASE + url)
            page.wait_for_load_state("networkidle")
            if then:
                then(page)
                page.wait_for_load_state("networkidle")
            page.mouse.move(1439, 899)  # no hover highlight
            page.wait_for_timeout(800)  # previews and fonts settle
            path = OUT / f"{name}-{scheme}.png"
            page.screenshot(path=str(path))
            print(path.name)
        ctx.close()
    browser.close()
