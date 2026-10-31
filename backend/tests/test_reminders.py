import logging
import os
import plistlib
import smtplib
import subprocess
import threading
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml
from pydantic import ValidationError
from sqlalchemy import select, update

from dam.config import AppPaths, EmailSettings, RemindersSettings, load_settings
from dam.db.tables import items, reminders_sent
from dam.reminders import launchd, notify
from dam.reminders.engine import Due, clear_unsent, collapse, due_reminders, mark_sent
from dam.reminders.notify import (
    EmailNotifier,
    MacNotifier,
    NotifyError,
    enabled_notifiers,
    plain,
    run_reminders,
)
from dam.trays.model import load_trays
from dam.trays.service import TrayService

HKI = ZoneInfo("Europe/Helsinki")
DEFAULTS = Path(__file__).resolve().parents[2] / "defaults" / "trays"


def at(y, m, d, h=0, minute=0):
    return datetime(y, m, d, h, minute, tzinfo=HKI)


def ts(when: datetime) -> float:
    return when.timestamp()


@pytest.fixture
def trays():
    defs, errors = load_trays(DEFAULTS)
    assert errors == []
    return defs


@pytest.fixture
def svc(engine, trays):
    return TrayService(engine, lambda: trays)


def created_at(engine, item_id, when: datetime) -> None:
    with engine.begin() as conn:
        conn.execute(update(items).where(items.c.id == item_id).values(created=ts(when)))


def due(engine, trays, now):
    return due_reminders(engine, trays, now, hour=8)


def keys(dues):
    return sorted((d.item_id, d.rule, d.occasion) for d in dues)


def sent_rows(engine):
    with engine.connect() as conn:
        return sorted(
            (r.item_id, r.rule, r.occasion, tuple(r.channels))
            for r in conn.execute(select(reminders_sent))
        )


class FakeNotifier:
    def __init__(self, id="fake", fail: str | None = None):
        self.id = id
        self.fail = fail
        self.calls: list[tuple[list[Due], str | None]] = []

    def send(self, dues, note=None):
        self.calls.append((list(dues), note))
        if self.fail:
            raise NotifyError(self.fail)


# --- engine: what fires --------------------------------------------------------------


def test_before0_for_item_created_on_its_due_day(engine, svc, trays):
    item = svc.create("to-pay", ["d1"], {"due_date": "2026-10-20", "amount": "84,20"}, "Bill")
    created_at(engine, item.id, at(2026, 10, 20, 9, 30))
    early = due(engine, trays, at(2026, 10, 20, 7, 59))
    assert keys(early) == [(item.id, "before:3", date(2026, 10, 17))]
    dues = due(engine, trays, at(2026, 10, 20, 9, 30))
    assert keys(dues) == [
        (item.id, "before:0", date(2026, 10, 20)),
        (item.id, "before:3", date(2026, 10, 17)),
    ]
    d0 = next(d for d in dues if d.rule == "before:0")
    assert d0.title == "Bill" and d0.date == date(2026, 10, 20)
    assert d0.amount == Decimal("84.20") and d0.tray_name == "To pay"
    send, silenced = collapse(dues)
    assert [d.rule for d in send] == ["before:0"]
    assert [d.rule for d in silenced] == ["before:3"]


def test_not_before_the_hour_on_the_day(engine, svc, trays):
    item = svc.create("to-action", ["d1"], {"action_date": "2026-10-21"}, "Call")
    assert due(engine, trays, at(2026, 10, 20, 7)) == []
    assert keys(due(engine, trays, at(2026, 10, 20, 8))) == [
        (item.id, "before:1", date(2026, 10, 20))
    ]
    # the hour is configurable
    assert due_reminders(engine, trays, at(2026, 10, 20, 8), hour=9) == []


def test_overdue_fires_the_day_after(engine, svc, trays):
    item = svc.create("to-pay", ["d1"], {"due_date": "2026-10-20"}, "Bill")
    now = at(2026, 10, 21, 8)
    dues = due(engine, trays, now)
    assert (item.id, "overdue", date(2026, 10, 21)) in keys(dues)
    send, silenced = collapse(dues)
    assert [d.rule for d in send] == ["overdue"]
    assert sorted(d.rule for d in silenced) == ["before:0", "before:3"]


def test_collapse_tie_prefers_overdue_then_before0():
    def due(rule, occasion):
        return Due(1, "t", "x", rule, occasion, date(2026, 10, 20), None)

    same = date(2026, 10, 20)
    send, silenced = collapse(
        [due("nudge", same), due("before:2", same), due("before:0", same), due("overdue", same)]
    )
    assert [d.rule for d in send] == ["overdue"]
    send, _ = collapse([due("nudge", same), due("before:2", same), due("before:0", same)])
    assert [d.rule for d in send] == ["before:0"]
    send, _ = collapse([due("nudge", same), due("before:2", same)])
    assert [d.rule for d in send] == ["before:2"]
    # a later occasion wins over rule priority
    send, _ = collapse([due("overdue", date(2026, 10, 1)), due("nudge", same)])
    assert [d.rule for d in send] == ["nudge"]


def test_fires_once(engine, svc, trays):
    svc.create("to-pay", ["d1"], {"due_date": "2026-10-20"}, "Bill")
    now = at(2026, 10, 25, 12)
    dues = due(engine, trays, now)
    assert len(dues) == 3
    mark_sent(engine, dues, ["mac"], now)
    mark_sent(engine, dues, ["mac"], now)  # a racing second run changes nothing
    assert due(engine, trays, now) == []


def test_done_items_never_due(engine, svc, trays):
    item = svc.create("to-pay", ["d1"], {"due_date": "2026-10-20"}, "Bill")
    svc.done(item.id, {})
    assert due(engine, trays, at(2026, 11, 30, 12)) == []


def test_removed_tray_items_never_due(engine, svc, trays):
    svc.create("to-pay", ["d1"], {"due_date": "2026-10-20"}, "Bill")
    others = [t for t in trays if t.id != "to-pay"]
    assert due(engine, others, at(2026, 11, 30, 12)) == []


def test_nudge_after_30_days_for_to_read_only(engine, svc, trays):
    read = svc.create("to-read", ["d1"], {}, "Article")
    pay = svc.create("to-pay", ["d2"], {"due_date": "2027-01-01"}, "Bill")
    created_at(engine, read.id, at(2026, 9, 1, 10))
    created_at(engine, pay.id, at(2026, 9, 1, 10))
    assert due(engine, trays, at(2026, 10, 1, 7)) == []
    dues = due(engine, trays, at(2026, 10, 1, 8))
    assert keys(dues) == [(read.id, "nudge", date(2026, 10, 1))]
    assert dues[0].date is None and dues[0].amount is None


def run_hourly(app, start_utc: datetime, hours: int, fake: FakeNotifier):
    fired: list[tuple[int, str, date, datetime]] = []
    for h in range(hours):
        now = (start_utc + timedelta(hours=h)).astimezone(HKI)
        result = run_reminders(app, now, notifiers=[fake])
        fired += [(d.item_id, d.rule, d.occasion, now) for d in result.sent]
    return fired


@pytest.mark.parametrize(
    ("due", "start"),
    [
        # before:3 falls on the October change (EEST -> EET on 2026-10-25)
        ("2026-10-28", datetime(2026, 10, 24, 0, tzinfo=UTC)),
        # before:3 falls on the March change (EET -> EEST on 2026-03-29)
        ("2026-04-01", datetime(2026, 3, 28, 0, tzinfo=UTC)),
    ],
)
def test_each_occasion_fires_exactly_once_across_dst(app, due, start):
    item = app.trays.create("to-pay", ["d1"], {"due_date": due}, "Bill")
    fake = FakeNotifier()
    fired = run_hourly(app, start, 24 * 6, fake)
    due_date = date.fromisoformat(due)
    assert [(i, r, o) for i, r, o, _ in fired] == [
        (item.id, "before:3", due_date - timedelta(days=3)),
        (item.id, "before:0", due_date),
        (item.id, "overdue", due_date + timedelta(days=1)),
    ]
    for _, _, occasion, now in fired:
        assert now.date() == occasion and now.hour == 8
    assert len(fake.calls) == 3


def test_clear_unsent_on_date_edit(app):
    item = app.trays.create("to-pay", ["d1"], {"due_date": "2026-10-20"}, "Bill")
    fake = FakeNotifier()
    first = run_reminders(app, at(2026, 10, 20, 9), notifiers=[fake])
    assert [d.rule for d in first.sent] == ["before:0"]
    assert [d.rule for d in first.silenced] == ["before:3"]
    assert sent_rows(app.engine) == [
        (item.id, "before:0", date(2026, 10, 20), ("fake",)),
        (item.id, "before:3", date(2026, 10, 17), ()),
    ]
    # the hook forgets only the silenced stale row; a delivered one is never deleted
    app.trays.update(item.id, {"due_date": "2026-10-30"}, None)
    assert sent_rows(app.engine) == [(item.id, "before:0", date(2026, 10, 20), ("fake",))]
    assert run_reminders(app, at(2026, 10, 20, 10), notifiers=[fake]).sent == []
    later = run_reminders(app, at(2026, 10, 27, 8), notifiers=[fake])
    assert keys(later.sent) == [(item.id, "before:3", date(2026, 10, 27))]


def test_clear_unsent_keeps_valid_and_delivered_rows(engine, svc, trays):
    read = svc.create("to-read", ["d1"], {}, "Article")
    pay = svc.create("to-pay", ["d2"], {"due_date": "2026-10-20"}, "Bill")
    other = svc.create("to-pay", ["d3"], {"due_date": "2026-10-20"}, "Other")
    created_at(engine, read.id, at(2026, 9, 1, 10))
    now = at(2026, 10, 18, 9)
    dues = due(engine, trays, now)
    mark_sent(engine, [d for d in dues if d.item_id == read.id], [], now)
    mark_sent(engine, [d for d in dues if d.item_id == pay.id], [], now)
    mark_sent(engine, [d for d in dues if d.item_id == other.id], ["mac"], now)
    assert len(sent_rows(engine)) == 3
    for i in (read.id, pay.id, other.id):  # dates unchanged: every row still valid
        assert clear_unsent(engine, i) == 0
    assert len(sent_rows(engine)) == 3
    # cleared dates: the silenced before:3 row goes, the delivered one stays
    svc.update(pay.id, {"due_date": ""}, None)
    svc.update(other.id, {"due_date": ""}, None)
    assert clear_unsent(engine, pay.id) == 1
    assert clear_unsent(engine, other.id) == 0
    assert sorted((r[0], r[1]) for r in sent_rows(engine)) == [
        (read.id, "nudge"),
        (other.id, "before:3"),
    ]
    assert due(engine, trays, now) == []


def test_date_round_trip_does_not_resend(app):
    item = app.trays.create("to-pay", ["d1"], {"due_date": "2026-10-20"}, "Bill")
    fake = FakeNotifier()
    now = at(2026, 10, 22, 9)
    assert [d.rule for d in run_reminders(app, now, notifiers=[fake]).sent] == ["overdue"]
    app.trays.update(item.id, {"due_date": "2026-10-21"}, None)  # a typo
    run_reminders(app, now, notifiers=[fake])
    app.trays.update(item.id, {"due_date": "2026-10-20"}, None)  # corrected back
    assert run_reminders(app, now, notifiers=[fake]).sent == []
    sent = [(d.rule, d.occasion) for call, _ in fake.calls for d in call]
    assert sent.count(("overdue", date(2026, 10, 21))) == 1


def test_broken_then_restored_config_does_not_resend(app):
    for day in (10, 12, 14):
        app.trays.create("to-pay", ["d1"], {"due_date": f"2026-10-{day}"}, f"B{day}")
    fake = FakeNotifier()
    now = at(2026, 10, 19, 9)
    assert len(run_reminders(app, now, notifiers=[fake]).sent) == 3
    good = app.tray_defs
    to_pay = next(t for t in good if t.id == "to-pay")
    data = to_pay.model_dump(by_alias=True)
    data["date_field"] = None
    data["reminders"] = []
    data["fields"]["due_date"]["type"] = "text"
    data["fields"]["due_date"]["prefill"] = None
    app.tray_defs = [type(to_pay).model_validate(data) if t.id == "to-pay" else t for t in good]
    app.trays.refresh_dates()  # the date field briefly broken
    app.tray_defs = good
    app.trays.refresh_dates()  # restored
    assert run_reminders(app, now, notifiers=[fake]).sent == []


def test_moving_the_date_earlier_keeps_its_reminders(app):
    item = app.trays.create("to-pay", ["d1"], {"due_date": "2026-10-20"}, "Bill")
    fake = FakeNotifier()
    first = run_reminders(app, at(2026, 10, 17, 8), notifiers=[fake])
    assert keys(first.sent) == [(item.id, "before:3", date(2026, 10, 17))]
    app.trays.update(item.id, {"due_date": "2026-10-15"}, None)  # an OCR misread fixed
    # the delivered row of the old date stays (a move back never re-fires it) ...
    assert (item.id, "before:3", date(2026, 10, 17), ("fake",)) in sent_rows(app.engine)
    # ... but it does not silence the new date's reminders
    early = run_reminders(app, at(2026, 10, 12, 8), notifiers=[fake])
    assert keys(early.sent) == [(item.id, "before:3", date(2026, 10, 12))]
    on_day = run_reminders(app, at(2026, 10, 15, 8), notifiers=[fake])
    assert keys(on_day.sent) == [(item.id, "before:0", date(2026, 10, 15))]
    app.trays.update(item.id, {"due_date": "2026-10-20"}, None)  # and back again
    assert run_reminders(app, at(2026, 10, 17, 9), notifiers=[fake]).sent == []


def with_nudge(app, days):
    to_pay = next(t for t in app.tray_defs if t.id == "to-pay")
    data = to_pay.model_dump(by_alias=True)
    data["nudge_after_days"] = days
    new = type(to_pay).model_validate(data)
    app.tray_defs = [new if t.id == "to-pay" else t for t in app.tray_defs]


def test_a_nudge_never_silences_date_reminders_after_a_date_move(app):
    with_nudge(app, 14)
    item = app.trays.create("to-pay", ["d1"], {"due_date": "2026-10-30"}, "Bill")
    created_at(app.engine, item.id, at(2026, 10, 1, 12))
    fake = FakeNotifier()
    first = run_reminders(app, at(2026, 10, 15, 9), notifiers=[fake])
    assert keys(first.sent) == [(item.id, "nudge", date(2026, 10, 15))]
    app.trays.update(item.id, {"due_date": "2026-10-10"}, None)  # a misread corrected
    result = run_reminders(app, at(2026, 10, 20, 9), notifiers=[fake])
    assert keys(result.sent) == [(item.id, "overdue", date(2026, 10, 11))]


def test_nudged_undated_item_given_a_past_date_gets_its_reminder(app):
    with_nudge(app, 14)
    item = app.trays.create("to-pay", ["d1"], {}, "Bill")  # due date not known yet
    created_at(app.engine, item.id, at(2026, 10, 1, 12))
    fake = FakeNotifier()
    assert [d.rule for d in run_reminders(app, at(2026, 10, 15, 9), [fake]).sent] == ["nudge"]
    app.trays.update(item.id, {"due_date": "2026-10-12"}, None)  # before the nudge day
    result = run_reminders(app, at(2026, 10, 16, 9), notifiers=[fake])
    assert keys(result.sent) == [(item.id, "overdue", date(2026, 10, 13))]
    assert run_reminders(app, at(2026, 10, 17, 9), notifiers=[fake]).sent == []


def test_new_earlier_rule_is_silenced(app):
    item = app.trays.create("to-pay", ["d1"], {"due_date": "2026-10-20"}, "Bill")
    fake = FakeNotifier()
    first = run_reminders(app, at(2026, 10, 20, 9), notifiers=[fake])
    assert [d.rule for d in first.sent] == ["before:0"]
    to_pay = next(t for t in app.tray_defs if t.id == "to-pay")
    data = to_pay.model_dump(by_alias=True)
    data["reminders"] = [*data["reminders"], {"days_before": 1}]  # added later
    app.tray_defs = [
        type(to_pay).model_validate(data) if t.id == "to-pay" else t for t in app.tray_defs
    ]
    result = run_reminders(app, at(2026, 10, 20, 10), notifiers=[fake])
    assert result.sent == []
    assert keys(result.silenced) == [(item.id, "before:1", date(2026, 10, 19))]


@pytest.fixture
def helsinki():
    """The process runs in Helsinki time (as on the user's Mac); restored afterwards."""
    if not hasattr(time, "tzset"):
        pytest.skip("sets the process time zone through TZ and time.tzset, which Windows lacks")
    old = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Helsinki"
    time.tzset()
    yield
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()


def prod_now(utc: datetime) -> datetime:
    """What ``datetime.now().astimezone()`` gives: a fixed-offset local datetime."""
    return datetime.fromtimestamp(utc.timestamp()).astimezone()


@pytest.mark.parametrize(
    ("created", "start"),
    [
        # created 00:30 EEST, nudge due 2026-10-10, then the October change
        (datetime(2026, 9, 10, 0, 30, tzinfo=HKI), datetime(2026, 10, 9, tzinfo=UTC)),
        # created 23:30 EET, nudge due 2026-03-28, then the March change
        (datetime(2026, 2, 26, 23, 30, tzinfo=HKI), datetime(2026, 3, 27, tzinfo=UTC)),
    ],
)
def test_nudge_fires_once_across_dst_with_fixed_offset_now(app, helsinki, created, start):
    item = app.trays.create("to-read", ["d1"], {}, "Article")
    created_at(app.engine, item.id, created)
    fake = FakeNotifier()
    fired = []
    for h in range(24 * 20):
        now = prod_now(start + timedelta(hours=h))
        fired += run_reminders(app, now, notifiers=[fake]).sent
    assert [(d.rule, d.occasion) for d in fired] == [("nudge", created.date() + timedelta(days=30))]


def test_dated_items_fire_once_with_fixed_offset_now(app, helsinki):
    for d in ("2026-10-28", "2026-04-01", "2026-10-25", "2026-03-29"):
        app.trays.create("to-pay", ["d1"], {"due_date": d}, f"Bill {d}")
    fake = FakeNotifier()
    fired = []
    for start in (datetime(2026, 3, 20, tzinfo=UTC), datetime(2026, 10, 15, tzinfo=UTC)):
        for h in range(24 * 20):
            fired += run_reminders(app, prod_now(start + timedelta(hours=h)), [fake]).sent
    fired_keys = keys(fired)
    assert len(fired_keys) == len(set(fired_keys)) == 12


def test_a_nudge_fires_at_most_once_per_item(engine, svc, trays):
    read = svc.create("to-read", ["d1"], {}, "Article")
    created_at(engine, read.id, at(2026, 9, 1, 10))
    (nudge,) = due(engine, trays, at(2026, 10, 1, 9))
    other_day = Due(read.id, "to-read", "Article", "nudge", date(2026, 9, 30), None, None)
    mark_sent(engine, [other_day], ["mac"], at(2026, 9, 30, 9))
    assert due(engine, trays, at(2026, 10, 1, 9)) == []
    assert nudge.occasion == date(2026, 10, 1)


def test_mark_sent_uses_now(engine, svc, trays):
    svc.create("to-pay", ["d1"], {"due_date": "2026-10-20"}, "Bill")
    now = at(2026, 10, 20, 9)
    mark_sent(engine, due(engine, trays, now), ["mac"], now)
    with engine.connect() as conn:
        assert set(conn.execute(select(reminders_sent.c.fired_at)).scalars()) == {now.timestamp()}


def test_hour_is_a_required_keyword(engine, trays):
    with pytest.raises(TypeError):
        due_reminders(engine, trays, at(2026, 10, 20, 9))
    with pytest.raises(TypeError):
        due_reminders(engine, trays, at(2026, 10, 20, 9), 8)


def test_lock_that_cannot_be_opened_skips_the_run(app):
    (app.app_paths.data_dir / "remind.lock").mkdir()
    app.trays.create("to-pay", ["d1"], {"due_date": "2026-10-20"}, "Bill")
    fake = FakeNotifier()
    result = run_reminders(app, at(2026, 10, 20, 9), notifiers=[fake])
    assert result.skipped.startswith("cannot open lock: ")
    assert fake.calls == [] and app.last_reminders is None


def test_lock_never_follows_a_symlink(app, tmp_path):
    victim = tmp_path / "victim"
    victim.write_text("keep", encoding="utf-8")
    (app.app_paths.data_dir / "remind.lock").symlink_to(victim)
    result = run_reminders(app, at(2026, 10, 20, 9), notifiers=[FakeNotifier()])
    assert result.skipped.startswith("cannot open lock: ")
    assert victim.read_text(encoding="utf-8") == "keep"


def test_concurrent_run_is_skipped(app):
    app.trays.create("to-pay", ["d1"], {"due_date": "2026-10-20"}, "Bill")
    entered, release = threading.Event(), threading.Event()

    class Slow:
        id = "mac"
        calls = 0

        def send(self, dues, note=None):
            Slow.calls += 1
            entered.set()
            assert release.wait(10)

    results = []
    worker = threading.Thread(
        target=lambda: results.append(run_reminders(app, at(2026, 10, 20, 9), [Slow()]))
    )
    worker.start()
    assert entered.wait(10)
    try:
        second = run_reminders(app, at(2026, 10, 20, 9), notifiers=[Slow()])
    finally:
        release.set()
        worker.join(10)
    assert second.skipped == "another run in progress"
    assert second.sent == [] and Slow.calls == 1
    assert [d.rule for d in results[0].sent] == ["before:0"] and results[0].skipped is None
    # the lock is released after the run: the next one runs (nothing left to send)
    third = run_reminders(app, at(2026, 10, 20, 10), notifiers=[Slow()])
    assert third.skipped is None and third.sent == []


def test_refresh_dates_calls_the_hook(engine, trays):
    changed = []
    svc = TrayService(engine, lambda: config, on_date_changed=changed.append)
    config = trays
    item = svc.create("to-pay", ["d1"], {"due_date": "2026-10-20"}, "Bill")
    to_pay = next(t for t in trays if t.id == "to-pay")
    data = to_pay.model_dump(by_alias=True)
    data["date_field"] = None
    data["reminders"] = []
    data["fields"]["due_date"]["type"] = "text"
    data["fields"]["due_date"]["prefill"] = None
    config = [type(to_pay).model_validate(data)]
    assert svc.refresh_dates() == 1
    assert changed == [item.id]


def test_hook_failure_is_logged_not_raised(engine, trays, caplog):
    def boom(item_id):
        raise RuntimeError("hook broke")

    svc = TrayService(engine, lambda: trays, on_date_changed=boom)
    item = svc.create("to-pay", ["d1"], {"due_date": "2026-10-20"}, "Bill")
    with caplog.at_level(logging.WARNING, logger="dam"):
        updated = svc.update(item.id, {"due_date": "2026-10-22"}, None)
    assert updated.date == date(2026, 10, 22)
    assert "hook broke" in caplog.text


# --- notifiers -------------------------------------------------------------------------


def dues_for(titles, start=date(2026, 10, 20)):
    return [
        Due(i + 1, "to-pay", t, "before:0", start, start + timedelta(days=i), None, "To pay")
        for i, t in enumerate(titles)
    ]


def test_plain_strips_control_and_bidi():
    assert plain("a‮b⁦c\x07d\ne\tf‏") == "abcd e f"


@pytest.fixture
def mac(monkeypatch, tmp_path):
    fake_osascript = tmp_path / "osascript"
    fake_osascript.write_text("", encoding="utf-8")
    fake_osascript.chmod(0o755)
    monkeypatch.setattr(notify, "OSASCRIPT", str(fake_osascript))
    monkeypatch.setattr(notify.sys, "platform", "darwin")
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(notify.subprocess, "run", fake_run)
    return calls, str(fake_osascript)


def test_mac_message_escaping_and_max_three_titles(mac):
    calls, osascript = mac
    titles = ['Say "hi"', "back\\slash", "line\nbreak", "fourth", "fifth"]
    MacNotifier().send(dues_for(titles))
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[:2] == [osascript, "-e"] and len(args) == 3
    assert kwargs["timeout"] == 10
    assert args[2] == (
        'display notification "Say \\"hi\\", back\\\\slash, line break +2 more" '
        'with title "Archive" subtitle "Due 20.10.2026"'
    )


def test_mac_without_dates_has_no_subtitle(mac):
    calls, _ = mac
    MacNotifier().send([Due(1, "to-read", "Article", "nudge", date(2026, 10, 1), None, None)])
    assert calls[0][0][2] == 'display notification "Article" with title "Archive"'


def test_mac_failure_is_an_error(mac, monkeypatch):
    def fail(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, "", "execution error")

    monkeypatch.setattr(notify.subprocess, "run", fail)
    with pytest.raises(NotifyError) as err:
        MacNotifier().send(dues_for(["x"]))
    assert str(err.value) == "osascript failed (exit 1)"  # no stderr text


def test_mac_timeout_is_an_error(mac, monkeypatch):
    def hang(args, **kwargs):
        raise subprocess.TimeoutExpired(args, 10, stderr=b"secret")

    monkeypatch.setattr(notify.subprocess, "run", hang)
    with pytest.raises(NotifyError) as err:
        MacNotifier().send(dues_for(["x"]))
    assert "secret" not in str(err.value) and str(err.value).startswith("osascript failed")


def test_mac_not_available_off_macos(monkeypatch):
    monkeypatch.setattr(notify.sys, "platform", "linux")
    with pytest.raises(NotifyError, match="not available"):
        MacNotifier().send(dues_for(["x"]))


def test_mac_not_available_without_osascript(monkeypatch, tmp_path):
    monkeypatch.setattr(notify.sys, "platform", "darwin")
    monkeypatch.setattr(notify, "OSASCRIPT", str(tmp_path / "missing"))
    with pytest.raises(NotifyError, match="not available"):
        MacNotifier().send(dues_for(["x"]))


class FakeSMTP:
    instances: list["FakeSMTP"] = []
    fail_login = False

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.log: list = []
        self.messages = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.log.append("quit")

    def starttls(self, context=None):
        self.log.append("starttls")

    def login(self, user, password):
        if FakeSMTP.fail_login:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
        self.log.append(("login", user, password))

    def send_message(self, msg, from_addr=None, to_addrs=None):
        self.envelope = (from_addr, to_addrs)
        self.messages.append(msg)


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.instances = []
    FakeSMTP.fail_login = False
    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


EMAIL = EmailSettings(to="me@example.org", smtp_host="smtp.example.org", smtp_user="me")


def test_email_body_has_only_tray_title_date_amount(smtp, monkeypatch):
    import keyring

    monkeypatch.setattr(
        keyring,
        "get_password",
        lambda service, user: "s3cret" if (service, user) == ("dam-reminders", "me") else None,
    )
    dues = [
        Due(
            1,
            "to-pay",
            "Northpower bill",
            "before:0",
            date(2026, 10, 20),
            date(2026, 10, 20),
            Decimal("84.20"),
            "To pay",
        ),
        Due(2, "to-read", "Article‮", "nudge", date(2026, 10, 1), None, None, "To read"),
    ]
    EmailNotifier(EMAIL).send(dues)
    (server,) = smtp.instances
    assert (server.host, server.port, server.timeout) == ("smtp.example.org", 587, 20)
    assert server.log == ["starttls", ("login", "me", "s3cret"), "quit"]
    assert server.envelope == ("me@example.org", ["me@example.org"])
    (msg,) = server.messages
    assert msg["Subject"] == "Archive reminders: 2 due"
    assert msg["From"] == msg["To"] == "me@example.org"
    assert msg.get("Cc") is None and msg.get("Bcc") is None
    assert msg.get_content() == ("To pay: Northpower bill, 20.10.2026, 84,20 €\nTo read: Article\n")


def test_email_note_when_archive_unavailable(smtp):
    EmailNotifier(EMAIL, password_lookup=lambda user: "pw").send(
        dues_for(["x"]), note="files can't be opened right now"
    )
    body = smtp.instances[0].messages[0].get_content()
    assert body.endswith("\nfiles can't be opened right now\n")


def test_email_missing_password_is_an_error_without_connecting(smtp):
    with pytest.raises(NotifyError, match="password not set"):
        EmailNotifier(EMAIL, password_lookup=lambda user: None).send(dues_for(["x"]))
    assert smtp.instances == []


def test_email_nothing_to_send_does_not_connect(smtp):
    EmailNotifier(EMAIL, password_lookup=lambda user: "pw").send([])
    assert smtp.instances == []


def test_email_without_tls_refuses_to_send_the_password(smtp):
    settings = EMAIL.model_copy(update={"starttls": False})
    with pytest.raises(NotifyError, match="refusing to send the password without TLS"):
        EmailNotifier(settings, password_lookup=lambda user: "pw").send(dues_for(["x"]))
    assert smtp.instances == []


class FakeSMTPSSL(FakeSMTP):
    def __init__(self, host, port, timeout=None, context=None):
        super().__init__(host, port, timeout)
        self.context = context


def test_email_port_465_uses_implicit_tls(smtp, monkeypatch):
    monkeypatch.setattr(notify.smtplib, "SMTP_SSL", FakeSMTPSSL)
    settings = EMAIL.model_copy(update={"smtp_port": 465, "starttls": False})
    EmailNotifier(settings, password_lookup=lambda user: "pw").send(dues_for(["x"]))
    (server,) = smtp.instances
    assert isinstance(server, FakeSMTPSSL) and server.context is not None
    assert (server.port, server.timeout) == (465, 20)
    assert server.log == [("login", "me", "pw"), "quit"]  # no STARTTLS on top of TLS


def test_email_non_ascii_password_error_does_not_leak_it(smtp, monkeypatch):
    def login(self, user, password):
        password.encode("ascii")

    monkeypatch.setattr(FakeSMTP, "login", login)
    with pytest.raises(NotifyError) as err:
        EmailNotifier(EMAIL, password_lookup=lambda user: "hunterä2").send(dues_for(["x"]))
    assert "ä" not in str(err.value) and "position" not in str(err.value)


def wait_keychain_idle():
    """The hung lookup thread has finished (so the next test may look up again)."""
    deadline = time.monotonic() + 5
    while notify._keychain_busy.is_set() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not notify._keychain_busy.is_set()


def test_email_keychain_timeout(smtp, monkeypatch):
    monkeypatch.setattr(notify, "KEYCHAIN_TIMEOUT", 0.2)
    stop = threading.Event()
    started = time.monotonic()
    with pytest.raises(NotifyError, match="keychain did not answer"):
        EmailNotifier(EMAIL, password_lookup=lambda user: stop.wait(5) and None).send(
            dues_for(["x"])
        )
    stop.set()
    assert time.monotonic() - started < 2
    assert smtp.instances == []
    wait_keychain_idle()


def test_email_hung_keychain_starts_no_second_lookup(smtp, monkeypatch):
    monkeypatch.setattr(notify, "KEYCHAIN_TIMEOUT", 0.1)
    stop = threading.Event()
    lookups = []

    def hang(user):
        lookups.append(user)
        stop.wait(5)
        return "pw"

    notifier = EmailNotifier(EMAIL, password_lookup=hang)
    try:
        for _ in range(3):
            with pytest.raises(NotifyError, match="keychain did not answer"):
                notifier.send(dues_for(["x"]))
        assert lookups == ["me"]  # one hung thread, not one per run
    finally:
        stop.set()
    wait_keychain_idle()
    EmailNotifier(EMAIL, password_lookup=lambda user: "pw").send(dues_for(["x"]))
    assert len(smtp.instances) == 1  # after it answered, lookups work again


def test_email_keychain_error_is_an_error(smtp):
    def broken(user):
        raise RuntimeError("No recommended backend")

    with pytest.raises(NotifyError, match="keychain"):
        EmailNotifier(EMAIL, password_lookup=broken).send(dues_for(["x"]))


@pytest.mark.parametrize(
    "bad", ["a@b.c,d@e.f", "<a@b.c>", "ä@b.fi", "a@b.c ", "a@b.c\x85", "a@b.c\r\nBcc: x"]
)
def test_email_to_is_one_plain_address(bad):
    with pytest.raises(ValidationError):
        EmailSettings(to=bad, smtp_host="h", smtp_user="u")


def test_email_host_and_user_have_no_line_breaks():
    with pytest.raises(ValidationError):
        EmailSettings(to="a@b.co", smtp_host="h\r\nX", smtp_user="u")
    with pytest.raises(ValidationError):
        EmailSettings(to="a@b.co", smtp_host="h", smtp_user="u\r\nRCPT TO:<x@y.z>")
    assert EmailSettings(to="a.b+c@mail.example.org", smtp_host="h", smtp_user="u@x").to


def test_email_settings_refuse_header_injection():
    with pytest.raises(ValidationError):
        EmailSettings(to="me@example.org\nBcc: x@y.z", smtp_host="h", smtp_user="u")
    with pytest.raises(ValidationError):
        EmailSettings(to="not an address", smtp_host="h", smtp_user="u")


# --- run_reminders ---------------------------------------------------------------------


def test_run_marks_sent_when_mac_ok_but_email_failed(app, smtp, caplog):
    item = app.trays.create("to-pay", ["d1"], {"due_date": "2026-10-20"}, "Secret title")
    smtp.fail_login = True
    mac = FakeNotifier("mac")
    email = EmailNotifier(EMAIL, password_lookup=lambda user: "pw")
    with caplog.at_level(logging.INFO, logger="dam"):
        result = run_reminders(app, at(2026, 10, 20, 9), notifiers=[mac, email])
    assert [d.rule for d in result.sent] == ["before:0"]
    assert set(result.errors) == {"email"} and "535" in result.errors["email"]
    assert result.ran_at == at(2026, 10, 20, 9)
    assert app.last_reminders is result
    assert (item.id, "before:0", date(2026, 10, 20), ("mac",)) in sent_rows(app.engine)
    info = [r.getMessage() for r in caplog.records if r.levelno >= logging.INFO]
    assert info and not any("Secret title" in m for m in info)


def test_run_all_channels_failed_retries_next_run(app):
    app.trays.create("to-pay", ["d1"], {"due_date": "2026-10-20"}, "Bill")
    failing = FakeNotifier("mac", fail="boom")
    result = run_reminders(app, at(2026, 10, 20, 9), notifiers=[failing])
    assert result.sent == [] and result.errors == {"mac": "boom"}
    assert [d.rule for d in result.silenced] == ["before:3"]
    ok = FakeNotifier("mac")
    again = run_reminders(app, at(2026, 10, 20, 10), notifiers=[ok])
    assert [d.rule for d in again.sent] == ["before:0"]


def test_run_unexpected_notifier_exception_is_recorded(app):
    app.trays.create("to-pay", ["d1"], {"due_date": "2026-10-20"}, "Bill")

    class Broken:
        id = "mac"

        def send(self, dues, note=None):
            raise OSError("disk on fire")

    result = run_reminders(app, at(2026, 10, 20, 9), notifiers=[Broken()])
    assert result.errors == {"mac": "disk on fire"}


def test_run_with_nothing_due_calls_no_notifier(app):
    fake = FakeNotifier()
    result = run_reminders(app, at(2026, 10, 20, 9), notifiers=[fake])
    assert result.sent == [] and result.errors == {} and fake.calls == []


def test_run_passes_archive_note(app, monkeypatch):
    app.trays.create("to-pay", ["d1"], {"due_date": "2026-10-20"}, "Bill")
    monkeypatch.setattr(type(app), "archive_available", property(lambda self: False))
    fake = FakeNotifier()
    run_reminders(app, at(2026, 10, 20, 9), notifiers=[fake])
    assert fake.calls[0][1] == "files can't be opened right now"


def test_enabled_notifiers(app_paths):
    settings = load_settings(app_paths)
    assert [n.id for n in enabled_notifiers(settings)] == ["mac"]
    settings.reminders = RemindersSettings(mac=False, email=EMAIL)
    assert [n.id for n in enabled_notifiers(settings)] == ["email"]
    assert set(notify.NOTIFIERS) == {"mac", "email"}


def test_enabled_notifiers_come_from_the_registry(app_paths, monkeypatch):
    class Extra:
        id = "extra"

        @classmethod
        def from_settings(cls, settings):
            return cls()

    monkeypatch.setitem(notify.NOTIFIERS, "extra", Extra)
    assert [n.id for n in enabled_notifiers(load_settings(app_paths))] == ["mac", "extra"]


def test_default_now_is_local_time(app, monkeypatch):
    seen = []
    monkeypatch.setattr(
        notify, "due_reminders", lambda engine, trays, now, *, hour: seen.append(now) or []
    )
    run_reminders(app, notifiers=[])
    assert seen[0].tzinfo is not None


# --- settings --------------------------------------------------------------------------


def test_settings_without_reminders_still_load(app_paths):
    settings = load_settings(app_paths)
    assert settings.reminders == RemindersSettings()
    assert settings.reminders.hour == 8 and settings.reminders.mac is True
    assert settings.reminders.email is None


def test_settings_with_email(app_paths, fake_archive):
    (app_paths.config_dir / "settings.yaml").write_text(
        yaml.safe_dump(
            {
                "archive_root": str(fake_archive.root),
                "reminders": {
                    "hour": 7,
                    "email": {"to": "me@example.org", "smtp_host": "h", "smtp_user": "me"},
                },
            }
        ),
        encoding="utf-8",
    )
    settings = load_settings(app_paths)
    assert settings.reminders.hour == 7
    assert settings.reminders.email.smtp_port == 587 and settings.reminders.email.starttls


def test_hour_out_of_range_refused():
    with pytest.raises(ValidationError):
        RemindersSettings(hour=24)


def test_default_settings_file_documents_reminders():
    text = (Path(__file__).resolve().parents[2] / "defaults" / "settings.yaml").read_text(
        encoding="utf-8"
    )
    assert "# reminders:" in text
    assert "reminders" not in (yaml.safe_load(text) or {})


# --- launchd ---------------------------------------------------------------------------


def test_plist_content(tmp_path):
    data_dir = tmp_path / "data"
    text = launchd.plist(["/venv/bin/dam"], data_dir, 8)
    parsed = plistlib.loads(text.encode())
    assert parsed["Label"] == "nl.dam.remind"
    assert parsed["ProgramArguments"] == [
        "/venv/bin/dam",
        "--data-dir",
        str(data_dir.resolve()),
        "remind",
    ]
    assert parsed["StartCalendarInterval"] == {"Hour": 8, "Minute": 0}
    assert parsed["RunAtLoad"] is True
    log = str(AppPaths(data_dir.resolve()).logs_dir / "remind.log")
    assert parsed["StandardOutPath"] == parsed["StandardErrorPath"] == log


def test_dam_command_is_absolute(monkeypatch):
    monkeypatch.setattr(launchd.shutil, "which", lambda name: None)
    monkeypatch.setattr(launchd.sys, "argv", ["dam", "remind"])
    (cmd,) = launchd.dam_command()
    assert Path(cmd).is_absolute()


@pytest.fixture
def home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    calls = []
    results = {}

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        planned = results.get(args[1], (0, ""))
        code, err = planned.pop(0) if isinstance(planned, list) else planned
        return subprocess.CompletedProcess(args, code, "", err)

    monkeypatch.setattr(launchd.subprocess, "run", fake_run)
    monkeypatch.setattr(launchd.os, "getuid", lambda: 501)
    monkeypatch.setattr(launchd.time, "sleep", lambda seconds: calls.append((["sleep"], {})))
    return home, calls, results


def test_install_writes_plist_and_bootstraps(home, tmp_path):
    home_dir, calls, _ = home
    path = launchd.install(["/venv/bin/dam"], tmp_path / "data", 8)
    expected = home_dir / "Library" / "LaunchAgents" / "nl.dam.remind.plist"
    assert path == expected
    assert path.read_text(encoding="utf-8") == launchd.plist(
        ["/venv/bin/dam"], tmp_path / "data", 8
    )
    assert [c[0] for c in calls if c[0][1] == "bootstrap"] == [
        ["/bin/launchctl", "bootstrap", "gui/501", str(expected)]
    ]
    assert all(isinstance(c[0], list) and "shell" not in c[1] for c in calls)


def test_install_refuses_to_overwrite_a_different_plist(home, tmp_path):
    launchd.install(["/venv/bin/dam"], tmp_path / "data", 8)
    launchd.install(["/venv/bin/dam"], tmp_path / "data", 8)  # same content: fine
    with pytest.raises(launchd.LaunchdError, match="already exists"):
        launchd.install(["/venv/bin/dam"], tmp_path / "data", 9)
    path = launchd.plist_path()
    assert "<integer>8</integer>" in path.read_text(encoding="utf-8")
    launchd.install(["/venv/bin/dam"], tmp_path / "data", 9, force=True)
    assert path.read_text(encoding="utf-8") == launchd.plist(
        ["/venv/bin/dam"], tmp_path / "data", 9
    )


def test_install_bootstrap_failure_raises(home, tmp_path):
    _, calls, results = home
    results["bootstrap"] = (5, "Bootstrap failed: 5: Input/output error")
    with pytest.raises(launchd.LaunchdError, match="Bootstrap failed"):
        launchd.install(["/venv/bin/dam"], tmp_path / "data", 8)
    assert [c[0][1] for c in calls if c[0][0] != "sleep"].count("bootstrap") == 2


def test_install_bootstrap_retries_once_on_error_5(home, tmp_path):
    _, calls, results = home
    results["bootstrap"] = [(5, "Bootstrap failed: 5: Input/output error"), (0, "")]
    launchd.install(["/venv/bin/dam"], tmp_path / "data", 8)
    steps = [c[0][1] if c[0][0] != "sleep" else "sleep" for c in calls]
    assert steps == ["bootout", "bootstrap", "sleep", "bootstrap"]


def test_install_other_bootstrap_errors_are_not_retried(home, tmp_path):
    _, calls, results = home
    results["bootstrap"] = (1, "Operation not permitted")
    with pytest.raises(launchd.LaunchdError):
        launchd.install(["/venv/bin/dam"], tmp_path / "data", 8)
    assert [c[0][1] for c in calls if c[0][0] != "sleep"].count("bootstrap") == 1


def test_install_never_follows_a_symlink(home, tmp_path):
    victim = tmp_path / "victim"
    victim.write_text("keep", encoding="utf-8")
    path = launchd.plist_path()
    path.parent.mkdir(parents=True)
    path.symlink_to(victim)
    with pytest.raises(launchd.LaunchdError):
        launchd.install(["/venv/bin/dam"], tmp_path / "data", 8, force=True)
    assert victim.read_text(encoding="utf-8") == "keep"


def test_uninstall_boots_out_and_removes_the_plist(home, tmp_path):
    _, calls, results = home
    path = launchd.install(["/venv/bin/dam"], tmp_path / "data", 8)
    calls.clear()
    results["bootout"] = (113, "Could not find specified service")  # not loaded: fine
    assert launchd.uninstall() is True
    assert calls[0][0] == ["/bin/launchctl", "bootout", "gui/501", str(path)]
    assert not path.exists()
    assert launchd.uninstall() is False  # nothing left to remove


def test_uninstall_refuses_any_other_path(home, tmp_path):
    other = tmp_path / "other.plist"
    other.write_text("x", encoding="utf-8")
    with pytest.raises(launchd.LaunchdError):
        launchd.uninstall(other)
    assert other.exists()


def test_uninstall_refuses_a_symlink(home, tmp_path):
    victim = tmp_path / "victim"
    victim.write_text("keep", encoding="utf-8")
    path = launchd.plist_path()
    path.parent.mkdir(parents=True)
    path.symlink_to(victim)
    with pytest.raises(launchd.LaunchdError):
        launchd.uninstall()
    assert path.is_symlink() and victim.read_text(encoding="utf-8") == "keep"


# --- lead rule: the item's own lead time ----------------------------------------------


def test_lead_reminder_uses_kind_default(engine, svc, trays):
    item = svc.create("renew", ["p1"], {"expires": "2027-06-30", "kind": "Passport"}, None)
    assert due(engine, trays, at(2026, 12, 31, 9)) == []
    dues = due(engine, trays, at(2027, 1, 1, 9))  # 180 days before 2027-06-30
    assert keys(dues) == [(item.id, "lead:180", date(2027, 1, 1))]


def test_lead_reminder_uses_item_override(engine, svc, trays):
    item = svc.create(
        "renew", ["p1"], {"expires": "2027-06-30", "kind": "Passport", "lead_days": "10"}, None
    )
    assert due(engine, trays, at(2027, 1, 1, 9)) == []
    dues = due(engine, trays, at(2027, 6, 20, 9))
    assert keys(dues) == [(item.id, "lead:10", date(2027, 6, 20))]


def test_lead_falls_back(engine, svc, trays):
    item = svc.create("renew", ["p1"], {"expires": "2027-06-30"}, None)
    assert keys(due(engine, trays, at(2027, 5, 31, 9))) == [(item.id, "lead:30", date(2027, 5, 31))]


def test_lead_with_unparseable_own_value_uses_kind_default(engine, svc, trays):
    item = svc.create("renew", ["p1"], {"expires": "2027-06-30", "kind": "Passport"}, None)
    with engine.begin() as conn:  # a stored value the type cannot parse (a config change)
        raw = dict(conn.execute(select(items.c.fields).where(items.c.id == item.id)).scalar_one())
        raw["lead_days"] = "soon"
        conn.execute(update(items).where(items.c.id == item.id).values(fields=raw))
    assert keys(due(engine, trays, at(2027, 1, 1, 9))) == [(item.id, "lead:180", date(2027, 1, 1))]


def test_lead_change_clears_silenced(engine, trays):
    svc = TrayService(
        engine, lambda: trays, on_date_changed=lambda i: clear_unsent(engine, i, trays)
    )
    item = svc.create("renew", ["p1"], {"expires": "2027-06-30", "kind": "Passport"}, None)
    now = at(2027, 6, 30, 9)
    dues = due(engine, trays, now)
    assert {d.rule for d in dues} == {"lead:180", "before:0"}
    mark_sent(engine, [d for d in dues if d.rule == "lead:180"], [], now)
    assert [r[1] for r in sent_rows(engine)] == ["lead:180"]
    svc.update(item.id, {"lead_days": "10"}, None)
    assert sent_rows(engine) == []  # the silenced row of the old lead time is gone
    assert "lead:10" in {d.rule for d in due(engine, trays, now)}
