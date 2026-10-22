"""Today: what needs attention, and the overview."""

import time
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import update

from dam.db.tables import items

INBOX = "##. Organize"
BANKS = "10. Financial/Banks"
QUAR = "##. To Delete"
TODAY = date(2026, 10, 19)


def bill(app, fake_archive, drive_id, due, amount=None, name=None):
    fake_archive.add(f"{BANKS}/{name or drive_id}.pdf", drive_id=drive_id)
    app.scan()
    fields = {} if due is None else {"due_date": due.isoformat()}
    if amount is not None:
        fields["amount"] = amount
    return app.trays.create("to-pay", [drive_id], fields, title=None)


def test_attention_levels(app, fake_archive):
    overdue = bill(app, fake_archive, "b1", TODAY - timedelta(days=1))
    due_today = bill(app, fake_archive, "b2", TODAY)
    soon = bill(app, fake_archive, "b3", TODAY + timedelta(days=3))
    bill(app, fake_archive, "b4", TODAY + timedelta(days=4))  # later: not yet
    undated = bill(app, fake_archive, "b5", None)
    done = bill(app, fake_archive, "b6", TODAY - timedelta(days=5))
    app.trays.done(done.id, {})
    got = app.today.attention(TODAY)
    assert [(a.item.id, a.level) for a in got] == [
        (overdue.id, "overdue"),
        (due_today.id, "today"),
        (soon.id, "soon"),
        (undated.id, "undated"),
    ]
    assert got[0].tray == "to-pay"
    assert got[0].missing_required == [] and got[3].missing_required == ["due_date"]
    assert all(a.file_state == "ok" for a in got)


def test_attention_note_excerpt(app, fake_archive):
    noted = bill(app, fake_archive, "n1", TODAY)
    plain = bill(app, fake_archive, "n2", TODAY)
    app.notes.set("item", str(noted.id), "fill buckets\nthe evening before " + "x" * 300)
    got = {a.item.id: a.note_excerpt for a in app.today.attention(TODAY)}
    assert got[plain.id] is None
    excerpt = got[noted.id]
    assert excerpt.startswith("fill buckets the evening before x")
    assert len(excerpt) == 121 and excerpt.endswith("…")


def test_attention_ignores_undated_items_of_trays_without_a_date(app, fake_archive):
    fake_archive.add(f"{BANKS}/r.pdf", drive_id="r1")
    app.scan()
    app.trays.create("to-read", ["r1"], {}, title=None)
    assert app.today.attention(TODAY) == []


def test_follow_up_tray_loads_and_its_date_is_optional(app, fake_archive):
    tray = next(t for t in app.tray_defs if t.id == "follow-up")
    assert tray.date_field == "check_by" and not tray.fields["check_by"].required
    assert tray.done.label == "Done"
    fake_archive.add(f"{BANKS}/f1.pdf", drive_id="f1")
    fake_archive.add(f"{BANKS}/f2.pdf", drive_id="f2")
    app.scan()
    undated = app.trays.create("follow-up", ["f1"], {"waiting_for": "Posti"}, title=None)
    late = app.trays.create(
        "follow-up", ["f2"], {"check_by": (TODAY - timedelta(days=2)).isoformat()}, title=None
    )
    assert undated.missing_required == []  # no "needs a date"
    # undated: not in attention; the dated one is overdue; undated sorts last in the tray
    assert [(a.item.id, a.level) for a in app.today.attention(TODAY)] == [(late.id, "overdue")]
    assert [i.id for i in app.trays.list("follow-up")] == [late.id, undated.id]


def test_file_state_missing_and_to_delete(app, fake_archive):
    gone = bill(app, fake_archive, "g1", TODAY)
    trashed = bill(app, fake_archive, "t1", TODAY)
    (fake_archive.root / BANKS / "g1.pdf").unlink()
    (fake_archive.root / BANKS / "t1.pdf").rename(fake_archive.root / QUAR / "t1.pdf")
    app.scan()
    states = {a.item.id: a.file_state for a in app.today.attention(TODAY)}
    assert states == {gone.id: "missing", trashed.id: "to_delete"}


def test_overview_counts_sums_and_waiting(app, fake_archive):
    fake_archive.add(f"{INBOX}/new.pdf", drive_id="in-1")
    bill(app, fake_archive, "b1", TODAY - timedelta(days=1), amount="84,20")
    bill(app, fake_archive, "b2", TODAY + timedelta(days=9), amount="10.00")
    bill(app, fake_archive, "b3", None)
    fake_archive.add(f"{BANKS}/read1.pdf", drive_id="r1")
    fake_archive.add(f"{BANKS}/read2.pdf", drive_id="r2")
    app.scan()
    old = app.trays.create("to-read", ["r1"], {}, title=None)
    app.trays.create("to-read", ["r2"], {}, title=None)
    with app.engine.begin() as conn:
        long_ago = time.time() - 40 * 86400
        conn.execute(update(items).where(items.c.id == old.id).values(created=long_ago))
    c = app.collections.create("Sauna")
    app.collections.add_members(c.id, ["b1", "b2"])
    app.notes.set("collection", str(c.id), "Builder: Marco\n" + "x" * 300)
    app.notes.add_check("collection", str(c.id), "call Marco")
    done_check = app.notes.add_check("collection", str(c.id), "order wood")
    app.notes.set_check(done_check.id, done=True)
    closed = app.collections.create("Old")
    app.collections.close(closed.id)

    ov = app.today.overview(TODAY)
    assert ov.inbox == 1
    by_tray = {t.tray_id: t for t in ov.trays}
    assert [t.tray_id for t in ov.trays] == ["to-pay", "to-action", "to-read", "follow-up"]
    assert by_tray["to-pay"].name == "To pay"
    assert (by_tray["to-pay"].open, by_tray["to-pay"].overdue) == (3, 1)
    assert by_tray["to-pay"].sum == Decimal("94.20")
    assert by_tray["to-action"].sum is None and by_tray["to-action"].open == 0
    assert by_tray["to-read"].waiting_long == 1 and by_tray["to-pay"].waiting_long == 0
    assert [(s.name, s.files, s.open_checks) for s in ov.collections] == [("Sauna", 2, 1)]
    excerpt = ov.collections[0].note_excerpt
    assert excerpt.startswith("Builder: Marco x") and len(excerpt) <= 121 and "\n" not in excerpt


def test_unmanaged_ongoing_counts_convertible_entries(app, fake_archive):
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="a1")
    fake_archive.link("##. Ongoing/A link", f"{BANKS}/a.pdf")
    fake_archive.add("##. Ongoing/Legal/x.pdf", drive_id="x1")
    (fake_archive.root / "##. Ongoing" / "Empty").mkdir()  # not convertible
    app.scan()
    assert app.today.unmanaged_ongoing() == 2


def test_unmanaged_ongoing_is_a_shallow_count(app, fake_archive, monkeypatch):
    from dam.collections.convert import OngoingConverter

    fake_archive.add(f"{BANKS}/a.pdf", drive_id="a1")
    fake_archive.link("##. Ongoing/A link", f"{BANKS}/a.pdf")
    fake_archive.add("##. Ongoing/Legal/sub/deep.pdf", drive_id="x1")
    fake_archive.add("##. Ongoing/Loose.pdf", drive_id="l1")
    app.scan()

    def deep(*args, **kwargs):
        raise AssertionError("Today must not walk Ongoing deeply")

    monkeypatch.setattr(OngoingConverter, "_deep_links", deep)
    monkeypatch.setattr(OngoingConverter, "_child_problem", deep)
    assert app.today.unmanaged_ongoing() == 3


def test_unmanaged_ongoing_is_zero_without_archive(app, fake_archive, tmp_path):
    import os

    os.rename(fake_archive.root, tmp_path / "away")
    try:
        assert app.today.unmanaged_ongoing() == 0
    finally:
        os.rename(tmp_path / "away", fake_archive.root)


def test_level_and_file_info_per_item(app, fake_archive):
    overdue = bill(app, fake_archive, "l1", TODAY - timedelta(days=1))
    later = bill(app, fake_archive, "l2", TODAY + timedelta(days=9))
    undated = bill(app, fake_archive, "l3", None)
    assert app.today.level(overdue, TODAY) == "overdue"
    assert app.today.level(later, TODAY) is None
    assert app.today.level(undated, TODAY) == "undated"
    app.trays.done(overdue.id, {})
    assert app.today.level(app.trays.get(overdue.id), TODAY) is None  # done: no level

    (fake_archive.root / BANKS / "l2.pdf").rename(fake_archive.root / QUAR / "l2.pdf")
    app.scan()
    [(rec, state)] = app.today.file_info(later)
    assert state == "to_delete" and rec.path == f"{QUAR}/l2.pdf"
    (fake_archive.root / BANKS / "l3.pdf").unlink()
    app.scan()
    [(rec, state)] = app.today.file_info(undated)
    assert state == "missing"


def test_open_items_per_tray_by_date_undated_last_capped(app, fake_archive):
    later = bill(app, fake_archive, "o1", TODAY + timedelta(days=20), amount="80.00")
    undated = bill(app, fake_archive, "o2", None)
    overdue = bill(app, fake_archive, "o3", TODAY - timedelta(days=4))
    done = bill(app, fake_archive, "o4", TODAY - timedelta(days=9))
    app.trays.done(done.id, {})
    soon = bill(app, fake_archive, "o5", TODAY + timedelta(days=2))
    fake_archive.add(f"{BANKS}/read.pdf", drive_id="r9")
    app.scan()
    read = app.trays.create("to-read", ["r9"], {}, title=None)

    got = {t.tray_id: [i.id for i in t.items] for t in app.today.open_items()}
    assert list(got) == ["to-pay", "to-action", "to-read", "follow-up"]
    assert got["to-pay"] == [overdue.id, soon.id, later.id, undated.id]
    assert got["to-action"] == [] and got["to-read"] == [read.id]

    for n in range(10):
        bill(app, fake_archive, f"x{n}", TODAY + timedelta(days=30 + n))
    capped = app.today.open_items()[0].items
    assert len(capped) == 8
    assert [i.id for i in capped[:3]] == [overdue.id, soon.id, later.id]
    assert undated.id not in [i.id for i in capped]


def test_open_items_reads_no_files(app, fake_archive, monkeypatch):
    bill(app, fake_archive, "f1", TODAY)
    monkeypatch.setattr(app.today, "file_info", lambda item: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(app.today.repo, "get", lambda *a: (_ for _ in ()).throw(AssertionError))
    assert [len(t.items) for t in app.today.open_items()] == [1, 0, 0, 0]


def test_overview_counts_collection_members_still_in_the_inbox(app, fake_archive):
    fake_archive.add(f"{INBOX}/new.pdf", drive_id="in-1")
    fake_archive.add(f"{INBOX}/gone.pdf", drive_id="in-2")
    fake_archive.add(f"{BANKS}/filed.pdf", drive_id="f1")
    app.scan()
    c = app.collections.create("House sale")
    app.collections.add_members(c.id, ["in-1", "in-2", "f1"])
    (fake_archive.root / INBOX / "gone.pdf").unlink()  # missing: not "in the inbox"
    app.scan()
    app.collections.create("Riverside")
    got = {s.name: s.in_inbox for s in app.today.overview(TODAY).collections}
    assert got == {"House sale": 1, "Riverside": 0}
