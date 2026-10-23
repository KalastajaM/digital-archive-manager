"""Stage a fresh demo archive the way the README screenshots show it: Ongoing and
Important converted, three bills in To pay, a folder excluded from AI. It talks only to
the demo server on localhost:8766, never to a real archive.

    cd backend && uv run python -m dam.demo /tmp/dam-shots
    uv run dam --data-dir /tmp/dam-shots/data serve --no-open --port 8766
    python3 scripts/screenshots/stage.py        # once, on the fresh demo
    uv run --no-project --with playwright python scripts/screenshots/shoot.py docs/images

``shoot.py`` uses the installed Google Chrome (``channel="chrome"``).
"""

import json
import sys
import urllib.request

BASE = "http://localhost:8766"


def call(method: str, path: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json", "Origin": BASE})
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path}: {e.code} {e.read().decode()}")


def convert(kind: str, body: dict) -> None:
    left = {e["rel"] for e in call("GET", f"/api/{kind}/entries") if not e.get("managed")}
    if body["rel"] not in left:
        print("already converted", body["rel"])
        return
    plan = call("POST", f"/api/{kind}/preview", body)
    call("POST", f"/api/{kind}/convert", {**body, "fingerprint": plan["fingerprint"]})
    print("converted", body["rel"])


# Ongoing: two collections, two stars (as in the old Activity shot)
convert("ongoing", {"rel": "##. Ongoing/2026 Sauna conversion", "collection": "2026 Sauna conversion"})
convert("ongoing", {"rel": "##. Ongoing/Electricity contract", "star": True})
convert("ongoing", {"rel": "##. Ongoing/2026_Plan.txt", "star": True, "destination": "30. Home"})
convert("ongoing", {"rel": "##. Ongoing/Legal", "collection": "Legal", "destination": "30. Home/Legal"})
convert("important", {"rel": "##. Important/passport.pdf", "destination": "40. Family"})

# To pay: three bills with a payee and a title
BILLS = [
    ("demo-12", "Water bill — Q4", "Example Water Co"),
    ("demo-4", "Electricity — September", "Northpower"),
    ("demo-3", "Home insurance", "Northwind Insurance"),
]
for drive_id, title, payee in BILLS:
    created = call("POST", "/api/items/quick", {"tray": "to-pay", "drive_ids": [drive_id]})["created"]
    item = created[0]
    call("PATCH", f"/api/items/{item['id']}", {"title": title, "fields": {**item["fields"], "payee": payee}})
    print("item", item["id"], title)

# AI: exclude the family folder (it exists in the demo) besides the defaults
call("PUT", "/api/ai/exclude-folders", {"folders": ["40. Family", "50. Medical"]})
print("excluded folders set")
