"""Today's inbox card: counts, age buckets by mtime, overdue scans and "Found in the inbox"."""

import os
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from dam.api import create_api
from dam.extract.base import ExtractedText
from dam.index.scanner import scan

INBOX = "##. Organize"
TODAY = date(2026, 10, 20)
NORTHPOWER_BILL = (
    "Northpower Oy lasku\nEräpäivä 15.11.2026\nYhteensä 84,20 €\n"
    "IBAN FI21 1234 5600 0007 85\nViitenumero RF18 5390 0754 7034"
)
LATE_BILL = "Lasku\nEräpäivä 01.10.2026\nYhteensä 12,00 €\nViitenumero RF18 5390 0754 7034"


def noon(days_ago: int, base: date = TODAY) -> float:
    """A local-time timestamp at noon, ``days_ago`` days before ``base``."""
    day = base - timedelta(days=days_ago)
    return datetime(day.year, day.month, day.day, 12).timestamp()


def add_scan(app, fake_archive, drive_id, text="", days_ago=0, rel=None, base=TODAY):
    path = fake_archive.add(
        rel or f"{INBOX}/{drive_id}.pdf", content=drive_id.encode(), drive_id=drive_id
    )
    os.utime(path, (noon(days_ago, base), noon(days_ago, base)))
    scan(app.paths, app.repo)
    app.repo.save_content(drive_id, None, ExtractedText(text, "test"), "indexed")


def test_empty_inbox(app):
    stats = app.today.inbox_stats(TODAY)
    assert (stats.count, stats.oldest_days) == (0, None)
    assert (stats.this_week, stats.last_week, stats.older, stats.overdue) == (0, 0, 0, 0)
    assert app.today.found_in_inbox(TODAY) == []


def test_bucket_boundaries(app, fake_archive):
    for days in (0, 6, 7, 13, 14, 40):
        add_scan(app, fake_archive, f"d{days}", days_ago=days)
    stats = app.today.inbox_stats(TODAY)
    assert stats.count == 6
    assert stats.oldest_days == 40
    assert (stats.this_week, stats.last_week, stats.older) == (2, 2, 2)


@pytest.mark.parametrize(
    ("days", "bucket"), [(6, "this_week"), (7, "last_week"), (13, "last_week"), (14, "older")]
)
def test_each_boundary_on_its_own(app, fake_archive, days, bucket):
    add_scan(app, fake_archive, "one", days_ago=days)
    stats = app.today.inbox_stats(TODAY)
    got = {b: getattr(stats, b) for b in ("this_week", "last_week", "older")}
    assert got == {b: int(b == bucket) for b in got}
    assert stats.oldest_days == days


def test_only_inbox_files_count(app, fake_archive):
    add_scan(app, fake_archive, "in", days_ago=1)
    add_scan(app, fake_archive, "elsewhere", days_ago=30, rel="10. Financial/Banks/x.pdf")
    (fake_archive.root / INBOX / "sub").mkdir()
    fake_archive.link(f"{INBOX}/link.pdf", "10. Financial/Banks/x.pdf")
    add_scan(app, fake_archive, "gone", days_ago=50)
    (fake_archive.root / INBOX / "gone.pdf").unlink()
    scan(app.paths, app.repo)
    stats = app.today.inbox_stats(TODAY)
    assert stats.count == 1 and stats.oldest_days == 1


def test_overdue_counts_inbox_scans_due_before_today(app, fake_archive):
    add_scan(app, fake_archive, "late", LATE_BILL)
    add_scan(app, fake_archive, "later", NORTHPOWER_BILL)
    add_scan(app, fake_archive, "plain", "a letter")
    assert app.today.inbox_stats(TODAY).overdue == 1
    assert app.today.inbox_stats(date(2026, 11, 15)).overdue == 1  # due today: not overdue
    assert app.today.inbox_stats(date(2026, 11, 16)).overdue == 2


def test_found_lists_guessed_files_not_yet_in_their_tray(app, fake_archive):
    add_scan(app, fake_archive, "late", LATE_BILL, days_ago=2)
    add_scan(app, fake_archive, "northpower", NORTHPOWER_BILL, days_ago=1)
    add_scan(app, fake_archive, "plain", "a letter")
    found = app.today.found_in_inbox(TODAY)
    assert [f.drive_id for f in found] == ["northpower", "late"]
    northpower, late = found
    assert (northpower.name, northpower.tray, northpower.tray_name) == (
        "northpower.pdf",
        "to-pay",
        "To pay",
    )
    assert northpower.due_date == date(2026, 11, 15) and str(northpower.total) == "84.20"
    assert northpower.overdue is False and late.overdue is True


def test_found_excludes_a_file_already_in_to_pay(app, fake_archive):
    add_scan(app, fake_archive, "northpower", NORTHPOWER_BILL)
    add_scan(app, fake_archive, "late", LATE_BILL)
    app.trays.create("to-pay", ["northpower"], {}, None)
    assert [f.drive_id for f in app.today.found_in_inbox(TODAY)] == ["late"]


def test_today_does_not_walk_the_tree(app, fake_archive, monkeypatch):
    add_scan(app, fake_archive, "northpower", NORTHPOWER_BILL)

    def boom(*a, **kw):
        raise AssertionError("no tree walk on Today")

    monkeypatch.setattr(app.repo, "walk", boom, raising=False)
    monkeypatch.setattr(os, "walk", boom)
    monkeypatch.setattr(os, "scandir", boom)
    app.today.inbox_stats(TODAY)
    app.today.found_in_inbox(TODAY)


def test_today_api_has_inbox_stats_and_found(app, fake_archive, freeze_today):
    freeze_today(TODAY)
    add_scan(app, fake_archive, "northpower", NORTHPOWER_BILL, days_ago=3)
    with TestClient(create_api(app), base_url="http://127.0.0.1:8765") as client:
        body = client.get("/api/today").json()
    stats = body["inbox_stats"]
    assert stats["count"] == 1 and stats["this_week"] == 1
    assert set(stats) == {"count", "oldest_days", "this_week", "last_week", "older", "overdue"}
    [found] = body["found"]
    assert found == {
        "drive_id": "northpower",
        "name": "northpower.pdf",
        "tray": "to-pay",
        "tray_name": "To pay",
        "due_date": "2026-11-15",
        "total": "84.20",
        "overdue": False,  # due 15 Nov, today is frozen at 20 Oct
        "marks": [],
    }


def test_today_found_rows_carry_their_marks(app, fake_archive, freeze_today):
    freeze_today(TODAY)
    add_scan(app, fake_archive, "northpower", NORTHPOWER_BILL, days_ago=3)
    add_scan(app, fake_archive, "late", LATE_BILL, days_ago=2)
    app.marks.star(["northpower"])
    app.marks.mark_important(["northpower", "late"], "Bills")
    with TestClient(create_api(app), base_url="http://127.0.0.1:8765") as client:
        body = client.get("/api/today").json()
    marks = {row["drive_id"]: row["marks"] for row in body["found"]}
    assert marks == {"northpower": ["starred", "important"], "late": ["important"]}


def test_inbox_api_entry_has_tray_guess_and_open_trays(app, fake_archive):
    add_scan(app, fake_archive, "northpower", NORTHPOWER_BILL)
    with TestClient(create_api(app), base_url="http://127.0.0.1:8765") as client:
        [entry] = client.get("/api/inbox").json()
    assert entry["tray_guess"] == "to-pay" and entry["open_trays"] == []


def test_overview_inbox_count_agrees_with_inbox_stats(app, fake_archive):
    add_scan(app, fake_archive, "in", days_ago=1)
    add_scan(app, fake_archive, "elsewhere", rel="10. Financial/Banks/x.pdf")
    (fake_archive.root / INBOX / "sub").mkdir()
    fake_archive.add(f"{INBOX}/sub/deep.pdf", drive_id="deep")
    fake_archive.link(f"{INBOX}/link.pdf", "10. Financial/Banks/x.pdf")
    add_scan(app, fake_archive, "gone")
    (fake_archive.root / INBOX / "gone.pdf").unlink()
    scan(app.paths, app.repo)
    entries = app.today.inbox_entries()
    assert app.today.overview(TODAY, entries).inbox == 1
    assert app.today.inbox_stats(TODAY, entries).count == 1
    assert app.today.overview(TODAY).inbox == 1  # the count query agrees too
    with TestClient(create_api(app), base_url="http://127.0.0.1:8765") as client:
        body = client.get("/api/today").json()
    assert body["overview"]["inbox"] == body["inbox_stats"]["count"] == 1
