"""Renewed… on a Renew item (Task 4): the new date, the new first file, the marks that
follow it, and the Undo by batch id."""

from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from dam.collections.marks import MarkState
from dam.db.tables import collection_groups, collection_members
from dam.errors import InvalidRequest
from dam.trays.renewal import RenewalService

BANKS = "10. Financial/Banks"
OLD_DATE = date(2027, 6, 30)
NEW_DATE = date(2037, 6, 30)


@pytest.fixture
def renew_item(app, fake_archive):
    fake_archive.add(f"{BANKS}/passport-old.pdf", drive_id="old")
    fake_archive.add(f"{BANKS}/passport-new.pdf", drive_id="new")
    fake_archive.add(f"{BANKS}/terms.pdf", drive_id="terms")
    app.scan()
    return app.trays.create(
        "renew", ["old", "terms"], {"expires": OLD_DATE.isoformat(), "kind": "Passport"}, None
    )


@pytest.fixture
def renew_item_important(app, renew_item):
    app.marks.star(["old"])
    app.marks.mark_important(["old"], "Docs/ID")
    return renew_item


def _events(app, item_id, kind="renewed"):
    return [e for e in app.trays.history(item_id) if e.kind == kind]


def _important_group(app, drive_id):
    """The names of the drive id's Important group, from the top (None: not Important)."""
    important = app.collections.builtin("important").id
    with app.engine.connect() as conn:
        row = conn.execute(
            select(collection_members.c.group_id).where(
                collection_members.c.collection_id == important,
                collection_members.c.drive_id == drive_id,
            )
        ).first()
        if row is None:
            return None
        names, gid = [], row.group_id
        while gid is not None:
            g = conn.execute(select(collection_groups).where(collection_groups.c.id == gid)).one()
            names.insert(0, g.name)
            gid = g.parent_id
        return names


def test_the_app_wires_the_service(app):
    assert isinstance(app.renewals, RenewalService)


def test_record_without_file_only_moves_date(app, renew_item):
    item = app.renewals.record(renew_item.id, NEW_DATE, None, "b1")
    assert item.files == ["old", "terms"]
    assert item.date == NEW_DATE and item.fields["expires"] == NEW_DATE
    (ev,) = _events(app, item.id)
    assert ev.data["new_drive_id"] is None and ev.data["marks"] is None
    assert ev.data["old_date"] == OLD_DATE.isoformat()
    assert ev.data["new_date"] == NEW_DATE.isoformat()
    assert ev.data["batch_id"] == "b1"


def test_record_fires_the_date_hook(app, renew_item, monkeypatch):
    fired: list[int] = []
    monkeypatch.setattr(app.trays, "_on_date_changed", fired.append)
    app.renewals.record(renew_item.id, NEW_DATE, None, "b1")
    assert fired == [renew_item.id]


def test_record_with_file_replaces_first(app, renew_item):
    item = app.renewals.record(renew_item.id, NEW_DATE, "new", "b1")
    assert item.files == ["new", "terms"]
    assert app.trays.open_for_files(["old"]) == []
    (ev,) = _events(app, item.id)
    assert ev.data["old_drive_id"] == "old" and ev.data["new_drive_id"] == "new"
    assert ev.data["old_name"] == "passport-old.pdf"
    assert ev.data["old_path"] == f"{BANKS}/passport-old.pdf"
    assert ev.data["marks"] == {
        "starred": False,
        "important": False,
        "group": None,
        "link_name": None,
    }
    assert app.marks.marks_for(["old", "new"]) == {"old": [], "new": []}


def test_marks_follow_new_file(app, renew_item_important):
    app.renewals.record(renew_item_important.id, NEW_DATE, "new", "b1")
    assert app.marks.marks_for(["old", "new"]) == {"old": [], "new": ["starred", "important"]}
    assert _important_group(app, "new") == ["Docs", "ID"]
    assert _important_group(app, "old") is None
    (ev,) = _events(app, renew_item_important.id)
    assert ev.data["marks"] == {
        "starred": True,
        "important": True,
        "group": ["Docs", "ID"],
        "link_name": None,
    }


def test_marks_state(app, renew_item_important):
    assert app.marks.marks_state("old") == MarkState(True, True, ["Docs", "ID"], None)
    assert app.marks.marks_state("new") == MarkState(False, False, None, None)


def test_tags_and_collections_stay(app, renew_item):
    app.tags.add("old", ["passport"])
    box = app.collections.create("Papers")
    app.collections.add_members(box.id, ["old"])
    app.renewals.record(renew_item.id, NEW_DATE, "new", "b1")
    assert app.repo.get("old") is not None
    assert [c.id for c in app.collections.for_file("old")] == [box.id]
    assert app.collections.for_file("new") == []
    assert "passport" in app.tags.for_file("old")
    assert app.tags.for_file("new") == []


def test_renew_refuses_same_file(app, renew_item):
    with pytest.raises(InvalidRequest):
        app.renewals.record(renew_item.id, NEW_DATE, "old", "b1")
    assert app.trays.get(renew_item.id).date == OLD_DATE
    assert _events(app, renew_item.id) == []


def test_renew_refuses_file_on_other_open_item(app, renew_item):
    app.trays.create("renew", ["new"], {"expires": "2030-01-01"}, None)
    with pytest.raises(InvalidRequest):
        app.renewals.record(renew_item.id, NEW_DATE, "new", "b1")
    assert app.trays.get(renew_item.id).files == ["old", "terms"]


def test_renew_refuses_a_tray_without_renew_and_a_done_item(app, renew_item):
    other = app.trays.create("to-pay", ["new"], {}, None)
    with pytest.raises(InvalidRequest):
        app.renewals.record(other.id, NEW_DATE, None, "b1")
    app.trays.done(renew_item.id, {})
    with pytest.raises(InvalidRequest):
        app.renewals.record(renew_item.id, NEW_DATE, None, "b1")


def test_undo_batch_restores_files_date_marks(app, renew_item_important):
    item_id = renew_item_important.id
    app.renewals.record(item_id, NEW_DATE, "new", "b1")
    assert app.renewals.undo_batch("b1") == 1
    item = app.trays.get(item_id)
    assert item.files == ["old", "terms"]
    assert item.date == OLD_DATE
    assert app.marks.marks_for(["old", "new"]) == {"old": ["starred", "important"], "new": []}
    assert _important_group(app, "old") == ["Docs", "ID"]
    first, undo = _events(app, item_id)  # the renewal stays in the history
    assert first.data["new_drive_id"] == "new"
    assert undo.data == {"undo": True, "batch_id": "b1"}
    # a second undo of the same batch finds nothing left to do
    assert app.renewals.undo_batch("b1") == 0


def test_undo_batch_leaves_other_batches(app, renew_item):
    app.renewals.record(renew_item.id, NEW_DATE, None, "b1")
    assert app.renewals.undo_batch("b2") == 0
    assert app.trays.get(renew_item.id).date == NEW_DATE


def test_undo_keeps_later_field_edits(app, renew_item):
    app.renewals.record(renew_item.id, NEW_DATE, "new", "b1")
    app.trays.update(renew_item.id, {"lead_days": 200}, None)
    app.renewals.undo_batch("b1")
    item = app.trays.get(renew_item.id)
    assert item.fields["lead_days"] == 200
    assert item.date == OLD_DATE
    assert item.files == ["old", "terms"]


def test_undo_keeps_a_date_changed_since(app, renew_item):
    app.renewals.record(renew_item.id, NEW_DATE, None, "b1")
    app.trays.update(renew_item.id, {"expires": "2038-01-01"}, None)
    app.renewals.undo_batch("b1")
    assert app.trays.get(renew_item.id).date == date(2038, 1, 1)


def test_activity_undo_undoes_the_renewal_and_resyncs(app, renew_item_important, monkeypatch):
    app.renewals.record(renew_item_important.id, NEW_DATE, "new", "b1")
    monkeypatch.setattr(
        app.executor, "undo", lambda b: SimpleNamespace(failed=None, error=None, index_error=None)
    )
    synced: list[object] = []
    real = app.collections.changed
    monkeypatch.setattr(app.collections, "changed", lambda *a, **k: synced.append(1) or real())
    outcome = app.activity.undo("b1")
    assert outcome.follow_up_error is None
    assert app.trays.get(renew_item_important.id).files == ["old", "terms"]
    assert app.marks.marks_for(["old"]) == {"old": ["starred", "important"]}
    assert synced


def test_the_link_name_stays_with_the_old_file(app, renew_item):
    important = app.collections.builtin("important").id
    app.collections.set_group_path(important, ["old"], ["Docs"], link_names={"old": "Passport"})
    app.renewals.record(renew_item.id, NEW_DATE, "new", "b1")
    assert app.marks.marks_state("new") == MarkState(False, True, ["Docs"], None)
    app.renewals.undo_batch("b1")
    assert app.marks.marks_state("old") == MarkState(False, True, ["Docs"], "Passport")


def test_renew_refuses_file_already_on_item(app, renew_item):
    with pytest.raises(InvalidRequest, match="This file is already on the item"):
        app.renewals.record(renew_item.id, NEW_DATE, "terms", "b1")
    assert app.trays.get(renew_item.id).files == ["old", "terms"]
    assert _events(app, renew_item.id) == []


def test_undo_keeps_a_star_the_new_file_had(app, renew_item_important):
    app.marks.star(["new"])
    app.renewals.record(renew_item_important.id, NEW_DATE, "new", "b1")
    (ev,) = _events(app, renew_item_important.id)
    assert ev.data["new_marks"] == {
        "starred": True,
        "important": False,
        "group": None,
        "link_name": None,
    }
    app.renewals.undo_batch("b1")
    assert app.marks.marks_state("new") == MarkState(True, False, None, None)
    assert app.marks.marks_state("old") == MarkState(True, True, ["Docs", "ID"], None)


def test_undo_puts_the_new_file_back_in_its_own_group(app, renew_item_important):
    app.marks.mark_important(["new"], "Travel")
    app.renewals.record(renew_item_important.id, NEW_DATE, "new", "b1")
    assert _important_group(app, "new") == ["Docs", "ID"]
    app.renewals.undo_batch("b1")
    assert app.marks.marks_state("new") == MarkState(False, True, ["Travel"], None)
    assert app.marks.marks_state("old") == MarkState(True, True, ["Docs", "ID"], None)


def test_undo_puts_an_ungrouped_new_file_back_ungrouped(app, renew_item_important):
    app.marks.mark_important(["new"], None)
    app.renewals.record(renew_item_important.id, NEW_DATE, "new", "b1")
    app.renewals.undo_batch("b1")
    assert app.marks.marks_state("new") == MarkState(False, True, None, None)
