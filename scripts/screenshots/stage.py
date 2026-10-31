"""Stage a fresh demo archive the way the README screenshots show it: Ongoing and
Important converted, three bills in To pay (one with a note, one with a checklist), a
folder excluded from AI, tagged files with a tag group and a pinned tag, a person, a
learned rule made from an area on a letterhead, summaries, a checklist and a locked file.
It talks only to the demo server on localhost:8766, never to a real archive.

    cd backend && uv run python -m dam.demo /tmp/dam-shots
    uv run dam --data-dir /tmp/dam-shots/data serve --no-open --port 8766
    export DAM_TOKEN=$(cat /tmp/dam-shots/data/api-token)  # the demo's sign-in token
    python3 scripts/screenshots/stage.py        # once, on the fresh demo
    uv run --no-project --with playwright python scripts/screenshots/shoot.py docs/images
    uv run --no-project --with playwright python scripts/screenshots/social.py docs/images

``shoot.py`` uses the installed Google Chrome (``channel="chrome"``).
"""

import json
import sys
import time
import urllib.error
import os
import urllib.request

BASE = "http://localhost:8766"
# the demo server's API token (its data folder's api-token file): every API call needs it
TOKEN = os.environ.get("DAM_TOKEN") or sys.exit("set DAM_TOKEN to the demo's api-token")


def call(method: str, path: str, body: dict | None = None, fail: bool = True):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json", "Origin": BASE, "X-Dam-Token": TOKEN})
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        if not fail:
            raise
        sys.exit(f"{method} {path}: {e.code} {e.read().decode()}")


def wait_idle(reminders: bool = True) -> None:
    """Wait until the indexer has nothing left (files, page 1, filing codes) and the first
    reminder check has run (it is a minute after the start), so no shot shows a half-read
    state such as "Reading filing codes" or "Not checked yet"."""
    for _ in range(240):
        status = call("GET", "/api/status")
        today = call("GET", "/api/today")
        page1 = status.get("page1") or {}
        busy = (
            status["pending"]
            or page1.get("text_left")
            or page1.get("scans_left")
            or today["reading_codes"]
            or (reminders and not today["reminders"]["last_run"])
        )
        if not busy:
            return
        time.sleep(1)
    sys.exit("the demo did not settle within four minutes")


def convert(kind: str, body: dict) -> None:
    left = {e["rel"] for e in call("GET", f"/api/{kind}/entries") if not e.get("managed")}
    if body["rel"] not in left:
        print("already converted", body["rel"])
        return
    plan = call("POST", f"/api/{kind}/preview", body)
    call("POST", f"/api/{kind}/convert", {**body, "fingerprint": plan["fingerprint"]})
    print("converted", body["rel"])


def wait_read(drive_ids: list[str]) -> None:
    """A fresh demo is still being read (the scan's barcode, page 1): bills made before
    that would have empty fields."""
    for _ in range(180):
        found = {e["record"]["drive_id"]: e["suggestion"]["fields"] for e in call("GET", "/api/inbox")}
        if all(found.get(d, {}).get("iban") for d in drive_ids):
            return
        time.sleep(1)
    sys.exit(f"the demo files {drive_ids} were not read within three minutes")


wait_read(["demo-18", "demo-4", "demo-3"])

# Ongoing: two collections, two stars (as in the old Activity shot)
convert("ongoing", {"rel": "##. Ongoing/2026 Sauna conversion", "collection": "2026 Sauna conversion"})
convert("ongoing", {"rel": "##. Ongoing/Electricity contract", "star": True})
convert("ongoing", {"rel": "##. Ongoing/2026_Plan.txt", "star": True, "destination": "30. Home"})
convert("ongoing", {"rel": "##. Ongoing/Legal", "collection": "Legal", "destination": "30. Home/Legal"})
convert("important", {"rel": "##. Important/passport.pdf", "destination": "40. Family"})

# To pay: three bills with a payee and a title
BILLS = [
    ("demo-18", "Water bill — Q4", "Example Water Co"),
    ("demo-4", "Electricity — September", "Northpower"),
    ("demo-3", "Home insurance", "Northwind Insurance"),
]
ITEM_IDS: dict[str, int] = {}
have = {i["files"][0]: i for i in call("GET", "/api/trays/to-pay/items") if i["files"]}
for drive_id, title, payee in BILLS:
    created = [] if drive_id in have else call("POST", "/api/items/quick", {"tray": "to-pay", "drive_ids": [drive_id]})["created"]
    item = have.get(drive_id) or created[0]
    call("PATCH", f"/api/items/{item['id']}", {"title": title, "fields": {**item["fields"], "payee": payee}})
    ITEM_IDS[drive_id] = item["id"]
    print("item", item["id"], title)

# AI: exclude the family folder (it exists in the demo) besides the defaults
call("PUT", "/api/ai/exclude-folders", {"folders": ["40. Family", "50. Medical"]})
print("excluded folders set")


# Tags: a few tagged files, a group with a pinned tag (sidebar Tags section, Tags screen)
FILE_TAGS = {
    "demo-21": ["plan", "2026", "home"],
    "demo-11": ["electricity", "contract", "home"],
    "demo-5": ["bank", "2026"],
    "demo-6": ["tax", "2026"],
    "demo-9": ["photos", "2026"],
    "demo-4": ["electricity"],
    "demo-3": ["insurance", "home"],
    "demo-19": ["legal", "contract"],
    "demo-20": ["legal"],
}
for drive_id, tags in FILE_TAGS.items():
    call("PUT", f"/api/files/{drive_id}/tags", {"tags": tags})
known = call("GET", "/api/tags/all")
groups = {g["name"]: g["id"] for g in known["groups"]}
for name, members in {"Money": ["bank", "tax", "insurance"], "House": ["electricity", "home"], "Legal": ["legal", "contract"]}.items():
    if name not in groups:
        groups[name] = call("POST", "/api/tags/groups", {"name": name})["id"]
    call("POST", "/api/tags/group", {"names": members, "group_id": groups[name]})
call("POST", "/api/tags/pin", {"names": ["2026", "home"], "pinned": True})
print("tags staged")

# A person for the For row and the people list in Settings
call("PUT", "/api/settings/people", {"people": [{"name": "Maija Virtanen", "match": ["Maija Virtanen", "M. Virtanen"]}]})
print("person set")

# A learned rule made from an area on page 1: the letterhead of the bank. (The water bill
# in the Inbox gets no rule, so the shots can make one from it.)
BANK = "demo-5"
draft = None
for _ in range(60):  # page 1 of a fresh demo is read by the indexer in the background
    try:
        draft = call("POST", "/api/rules/draft-zone", {"drive_id": BANK, "boxes": [[0.0, 0.0, 1.0, 0.2]]}, fail=False)
        break
    except urllib.error.HTTPError:
        time.sleep(1)
if draft is None:
    sys.exit("page 1 of the bank letter was not read within a minute")
rule = {
    "id": "northbank",
    "when": {"zones": [{"box": draft["zones"][0]["box"], "text_contains": ["northbank"], "match": "word_start"}]},
    "then": {"folder": "10. Financial/Banks", "tags": ["bank"]},
}
call("PUT", "/api/rules/northbank", rule)
# the water bill's letterhead (as the boxes shot draws it) gives the inbox shot its folder
call("PUT", "/api/rules/vesilaitos", {
    "id": "vesilaitos",
    "when": {"folder_is": "##. Organize", "zones": [{"box": [0.05, 0.06, 0.6, 0.14], "text_contains": ["vesilaitos"], "match": "word_start"}]},
    "then": {"folder": "30. Home", "tags": ["water"]},
})
print("rules saved")
WATER = "demo-18"

# Notes, checklists and a summary, so the row icons show. The files were just moved: a
# summary saved before they are read again would show as outdated.
wait_idle(reminders=False)
call("PUT", f"/api/notes/item/{ITEM_IDS['demo-4']}", {"text": "Ask Northpower why the September bill is higher than last year."})
for text in ("Compare with last year's bill", "Call Northpower about the meter reading"):
    call("POST", f"/api/checklist/item/{ITEM_IDS['demo-4']}", {"text": text})
call("POST", f"/api/checklist/file/{WATER}", {"text": "Check the reference number before paying"})
call("POST", "/api/checklist/file/demo-21", {"text": "Send the plan to the architect"})
call("PUT", "/api/notes/file/demo-21", {"text": "Draft from the spring meeting, still to be agreed."})
call("PUT", "/api/files/demo-21/summary", {"source": "user", "summary": "The 2026 plan for the house: the sauna conversion and the electricity contract.", "key_facts": [], "replace": True})
call("PUT", "/api/files/demo-11/summary", {"source": "user", "summary": "Fixed-price electricity contract for the house.", "key_facts": [], "replace": True})
print("notes, checklists and summaries added")

# A locked file (shown with its lock in Browse)
call("POST", "/api/files/demo-21/lock")
print("locked demo-21")

wait_idle()
print("settled")
