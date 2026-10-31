"""The social preview image (1280x640, light): the headline and pills on the left,
the Inbox shot as an app window on the right, cut off by the edge. Run it after shoot.py
has written ``inbox.png`` to the folder given:

    uv run --no-project --with playwright python scripts/screenshots/social.py docs/images
"""

import base64
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

FOLDER = Path(sys.argv[1])
ICON = Path(__file__).resolve().parents[2] / "frontend" / "public" / "icon.svg"

COLORS = dict(bg="#f5f6fa", glow="#e2e6f0", text="#1d1d1f", muted="#515154", blue="#0071e3",
              pill_bg="#ffffff", pill_line="rgba(0,0,0,.12)", shadow="0 24px 70px rgba(30,40,80,.28)")

PAGE = """<!doctype html><meta charset="utf-8"><style>
* { box-sizing: border-box; margin: 0; }
body { width: 1280px; height: 640px; overflow: hidden; position: relative;
  background: radial-gradient(900px 300px at 70%% 112%%, %(glow)s, transparent 70%%), %(bg)s;
  font-family: -apple-system, "SF Pro Display", "Inter", "Helvetica Neue", Arial, sans-serif; color: %(text)s; }
.brand { position: absolute; left: 72px; top: 111px; display: flex; align-items: center; gap: 14px;
  font-size: 21px; font-weight: 600; color: %(muted)s; }
.brand img { width: 52px; height: 52px; }
h1 { position: absolute; left: 72px; top: 196px; font-size: 54px; line-height: 64px; font-weight: 800;
  letter-spacing: -1.6px; }
h1 span { color: %(blue)s; }
p { position: absolute; left: 72px; top: 326px; width: 480px; font-size: 22px; line-height: 31px; color: %(muted)s; }
.pills { position: absolute; left: 72px; top: 447px; width: 470px; display: flex; flex-wrap: wrap; gap: 10px; }
.pills b { padding: 9px 16px; font-size: 17px; font-weight: 600; border-radius: 999px;
  background: %(pill_bg)s; border: 1px solid %(pill_line)s; }
.window { position: absolute; left: 590px; top: 70px; width: 800px; height: 500px; border-radius: 12px;
  overflow: hidden; box-shadow: %(shadow)s, 0 0 0 1px %(pill_line)s; }
.window img { width: 800px; height: 500px; display: block; }
</style>
<div class="brand"><img src="%(icon)s" alt="">Digital Archive Manager</div>
<h1>Your paperwork,<br><span>filed and findable.</span></h1>
<p>A local-first app that sorts, searches and keeps track of the documents in your Google Drive, OneDrive, Dropbox or any folder.</p>
<div class="pills"><b>Never deletes a file</b><b>Every change undoable</b><b>macOS &middot; Windows &middot; Linux</b></div>
<div class="window"><img src="%(shot)s" alt=""></div>
"""


def data_uri(path: Path, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    page = browser.new_page(viewport={"width": 1280, "height": 640})
    html = PAGE % {
        **COLORS,
        "icon": data_uri(ICON, "image/svg+xml"),
        "shot": data_uri(FOLDER / "inbox.png", "image/png"),
    }
    page.set_content(html)
    page.evaluate("document.fonts.ready")
    page.wait_for_function("[...document.images].every((i) => i.complete)")
    page.screenshot(path=str(FOLDER / "social-preview.png"))
    print("social-preview.png")
    page.close()
    browser.close()
