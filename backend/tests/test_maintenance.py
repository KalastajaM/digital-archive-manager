"""Maintenance: the duplicate check (size grouping, hashing only candidates, stored hashes),
replacing or removing duplicates in one undoable batch, what the removed copies hand over to
the kept one, and the small lists. Fake archives only."""

import os
import threading
import time
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from dam.api import create_api
from dam.db.tables import files, operations
from dam.maintenance import duplicates
from dam.maintenance.checks import suggest_name
from dam.ops.model import GuardError, OpKind
from dam.ops.primitives import TEMP_COPY_PREFIX
from dam.services.errors import InvalidRequest
from dam.trays.model import load_trays

INBOX = "##. Organize"
ONG = "##. Ongoing"
IMP = "##. Important"
QUAR = "##. To Delete"
BANKS = "10. Financial/Banks"
HOME = "20. Home"
DEFAULTS = Path(__file__).resolve().parents[2] / "defaults" / "trays"
BASE = "http://127.0.0.1:8765"


def run(app, kind, days=None, wait=15):
    job = app.maintenance.start(kind, days)
    job.join(wait)
    view = job.view()
    assert view.state in ("done", "stopped"), (view.state, view.error)
    return view


def run_job(app, kind, wait=15):
    job = app.maintenance.start(kind)
    job.join(wait)
    return job


def dup_result(app):
    return run(app, "duplicates").result


def hashed_paths(monkeypatch):
    """Record every file the duplicate check opens for hashing."""
    seen: list[str] = []
    real = duplicates.hash_file

    def spy(path, stopped):
        seen.append(path.name)
        return real(path, stopped)

    monkeypatch.setattr(duplicates, "hash_file", spy)
    return seen


@pytest.fixture
def pair(app, fake_archive):
    """The same content twice (one in a numbered folder, one in the inbox) and a third
    file of the same size with other content."""
    fake_archive.add(f"{BANKS}/20230101_bill.pdf", b"same-content", drive_id="id-keep")
    fake_archive.add(f"{INBOX}/scan.pdf", b"same-content", drive_id="id-dup")
    fake_archive.add(f"{HOME}/other.pdf", b"other-bytes!", drive_id="id-other")
    fake_archive.add(f"{HOME}/small.txt", b"x", drive_id="id-small")
    app.scan()
    return fake_archive


# --- size grouping and hashing ---


def test_estimate_counts_only_files_that_share_a_size(app, pair):
    est = app.maintenance.estimate()
    assert (est.files, est.candidates, est.known) == (4, 3, 0)
    assert (est.to_read_files, est.to_read_bytes) == (3, 36)


def test_only_candidates_are_hashed_and_the_hash_is_stored(app, pair, monkeypatch):
    seen = hashed_paths(monkeypatch)
    result = dup_result(app)
    assert sorted(seen) == ["20230101_bill.pdf", "other.pdf", "scan.pdf"]  # not small.txt
    [group] = result.groups
    assert {f.drive_id for f in group.files} == {"id-keep", "id-dup"}
    assert app.repo.get("id-keep").sha256 == group.sha256
    assert app.repo.get("id-small").sha256 is None  # never read
    est = app.maintenance.estimate()
    assert (est.known, est.to_read_files, est.to_read_bytes) == (3, 0, 0)


def test_a_stored_hash_is_not_read_again(app, pair, monkeypatch):
    dup_result(app)
    seen = hashed_paths(monkeypatch)
    result = dup_result(app)
    assert seen == []
    assert (result.reused, result.read_files) == (3, 0)
    assert len(result.groups) == 1


def test_a_changed_file_loses_its_hash_and_is_read_again(app, pair, monkeypatch):
    dup_result(app)
    path = pair.root / INBOX / "scan.pdf"
    path.write_bytes(b"changed-data")  # same size, other content
    os.utime(path, (time.time() + 5, time.time() + 5))
    app.scan()
    assert app.repo.get("id-dup").sha256 is None  # the scanner forgot it
    seen = hashed_paths(monkeypatch)
    result = dup_result(app)
    assert seen == ["scan.pdf"]
    assert result.groups == []


def test_links_to_delete_and_the_apps_folders_are_skipped(app, fake_archive, monkeypatch):
    fake_archive.add(f"{BANKS}/a.pdf", b"content-1", drive_id="id-a")
    fake_archive.add(f"{QUAR}/{BANKS}/a.pdf", b"content-1", drive_id="id-q")
    fake_archive.link(f"{ONG}/a.pdf", f"{BANKS}/a.pdf")
    fake_archive.link(f"{HOME}/a-link.pdf", f"{BANKS}/a.pdf")
    app.scan()
    seen = hashed_paths(monkeypatch)
    est = app.maintenance.estimate()
    assert (est.files, est.candidates) == (1, 0)
    assert dup_result(app).groups == []
    assert seen == []


def test_empty_files_are_not_duplicates(app, fake_archive):
    fake_archive.add(f"{BANKS}/e1.txt", b"", drive_id="id-e1")
    fake_archive.add(f"{HOME}/e2.txt", b"", drive_id="id-e2")
    app.scan()
    assert app.maintenance.estimate().candidates == 0


# --- keep suggestion ---


def test_keep_prefers_a_numbered_folder_over_the_inbox_then_the_oldest(app, fake_archive):
    old, new = time.time() - 9000, time.time() - 100
    fake_archive.add(f"{INBOX}/in.pdf", b"abcdef", drive_id="id-in")
    for rel, did, when in ((f"{HOME}/new.pdf", "id-new", new), (f"{BANKS}/old.pdf", "id-old", old)):
        path = fake_archive.add(rel, b"abcdef", drive_id=did)
        os.utime(path, (when, when))
    app.scan()
    [group] = dup_result(app).groups
    assert group.keep == "id-old"  # numbered, and older than the other numbered one
    assert [f.drive_id for f in group.files][0] == "id-old"
    assert {f.place for f in group.files} == {"numbered", "inbox"}


def test_keep_prefers_a_copy_that_cannot_be_removed(app, fake_archive):
    fake_archive.add(f"{BANKS}/a.pdf", b"abcdef", drive_id="id-a")
    fake_archive.add(f"{INBOX}/b.pdf", b"abcdef", drive_id="id-b")
    app.scan()
    app.marks.mark_important(["id-b"])
    [group] = dup_result(app).groups
    assert group.keep == "id-b"
    locked = {f.drive_id: (f.locked, f.why) for f in group.files}
    assert locked["id-b"] == ("important", "It is marked Important, so it stays")
    assert locked["id-a"] == (None, None)


# --- the same name, other content ---


def test_same_name_with_other_content_is_listed_but_copies_are_not(app, fake_archive):
    fake_archive.add(f"{BANKS}/Statement.pdf", b"version one", drive_id="id-1")
    fake_archive.add(
        f"{HOME}/statement.PDF".replace("PDF", "pdf"), b"version 2!!!!", drive_id="id-2"
    )
    fake_archive.add(f"{HOME}/same.pdf", b"copy-copy", drive_id="id-3")
    fake_archive.add(f"{BANKS}/same.pdf", b"copy-copy", drive_id="id-4")
    app.scan()
    result = dup_result(app)
    assert [g.name.casefold() for g in result.name_groups] == ["statement.pdf"]
    assert {f.drive_id for f in result.name_groups[0].files} == {"id-1", "id-2"}
    assert len(result.groups) == 1  # same.pdf is an exact pair, not a version pair


def test_equal_sizes_with_different_hashes_are_versions(app, fake_archive):
    fake_archive.add(f"{BANKS}/v.pdf", b"aaaa", drive_id="id-1")
    fake_archive.add(f"{HOME}/v.pdf", b"bbbb", drive_id="id-2")
    app.scan()
    result = dup_result(app)
    assert result.groups == []
    assert len(result.name_groups) == 1


# --- replace with a link / move to To Delete ---


def resolve(app, action="link", carry=True, dry=False, keep="id-keep", remove=("id-dup",)):
    return app.maintenance.resolve([(keep, list(remove))], action, carry_over=carry, dry_run=dry)


def journal(app, batch_id):
    with app.engine.connect() as conn:
        return list(
            conn.execute(select(operations).where(operations.c.batch_id == batch_id)).mappings()
        )


def test_replace_with_a_link_is_one_batch_and_one_undo(app, pair):
    dup_result(app)
    dry = resolve(app, dry=True)
    assert [(o.kind, o.src, o.dst) for o in dry.done if o.kind is not OpKind.MKDIR] == [
        (OpKind.QUARANTINE, f"{INBOX}/scan.pdf", f"{QUAR}/{INBOX}/scan.pdf"),
        (OpKind.SYMLINK, f"{BANKS}/20230101_bill.pdf", f"{INBOX}/scan.pdf"),
    ]
    assert (pair.root / INBOX / "scan.pdf").is_file()  # a dry run changes nothing
    assert not (pair.root / INBOX / "scan.pdf").is_symlink()

    result = resolve(app)
    assert result.failed is None and result.error is None
    link = pair.root / INBOX / "scan.pdf"
    assert link.is_symlink() and link.read_bytes() == b"same-content"
    assert (pair.root / QUAR / INBOX / "scan.pdf").read_bytes() == b"same-content"
    assert (pair.root / BANKS / "20230101_bill.pdf").is_file()
    rows = journal(app, result.batch_id)
    assert [r["kind"] for r in rows if r["kind"] != "mkdir"] == ["quarantine", "symlink"]
    assert {r["label"] for r in rows} == {"Replaced 1 duplicate with a link to the kept copy"}
    assert app.repo.by_path(f"{INBOX}/scan.pdf").is_link  # indexed right away

    outcome = app.activity.undo(result.batch_id)
    assert outcome.batch.failed is None and outcome.batch.error is None
    back = pair.root / INBOX / "scan.pdf"
    assert back.is_file() and not back.is_symlink() and back.read_bytes() == b"same-content"
    assert not (pair.root / QUAR / INBOX / "scan.pdf").exists()
    assert app.repo.get("id-dup").path == f"{INBOX}/scan.pdf"
    assert app.activity.get(result.batch_id).undone


def test_move_to_to_delete_without_a_link_and_its_undo(app, pair):
    dup_result(app)
    result = resolve(app, action="quarantine")
    assert not (pair.root / INBOX / "scan.pdf").exists()
    assert (pair.root / QUAR / INBOX / "scan.pdf").is_file()
    assert {r["label"] for r in journal(app, result.batch_id)} == {"Moved 1 duplicate to To Delete"}
    app.activity.undo(result.batch_id)
    assert (pair.root / INBOX / "scan.pdf").is_file()


def test_several_groups_in_one_batch(app, fake_archive):
    for n in (1, 2):
        fake_archive.add(f"{BANKS}/k{n}.pdf", b"content-%d" % n, drive_id=f"k{n}")
        fake_archive.add(f"{HOME}/d{n}.pdf", b"content-%d" % n, drive_id=f"d{n}")
    app.scan()
    dup_result(app)
    result = app.maintenance.resolve([("k1", ["d1"]), ("k2", ["d2"])], "link")
    assert len([r for r in journal(app, result.batch_id) if r["kind"] != "mkdir"]) == 4
    assert (fake_archive.root / HOME / "d1.pdf").is_symlink()
    app.activity.undo(result.batch_id)
    assert not (fake_archive.root / HOME / "d1.pdf").is_symlink()
    assert not (fake_archive.root / HOME / "d2.pdf").is_symlink()


def test_one_copy_to_to_delete_and_another_replaced_with_a_link_in_one_batch(app, pair):
    pair.add(f"{HOME}/third.pdf", b"same-content", drive_id="id-third")
    app.scan()
    dup_result(app)
    result = app.maintenance.resolve(
        [("id-keep", ["id-dup", "id-third"])], "quarantine", links=["id-third"]
    )
    assert result.error is None and result.failed is None
    assert not (pair.root / INBOX / "scan.pdf").exists()  # moved, no link
    assert (pair.root / HOME / "third.pdf").is_symlink()  # moved and linked
    assert {r["label"] for r in journal(app, result.batch_id)} == {
        "Moved 1 duplicate to To Delete and replaced 1 with a link"
    }
    app.activity.undo(result.batch_id)
    assert (pair.root / INBOX / "scan.pdf").is_file()
    third = pair.root / HOME / "third.pdf"
    assert third.is_file() and not third.is_symlink()
    with pytest.raises(InvalidRequest, match="not one of the copies to remove"):
        app.maintenance.resolve([("id-keep", ["id-dup"])], "quarantine", links=["id-third"])


def test_a_taken_name_in_to_delete_gets_a_number_and_undo_still_restores(app, pair):
    pair.add(f"{QUAR}/{INBOX}/scan.pdf", b"older-thing", drive_id="id-old-q")
    app.scan()
    dup_result(app)
    result = resolve(app)
    assert (pair.root / QUAR / INBOX / "scan_2.pdf").read_bytes() == b"same-content"
    app.activity.undo(result.batch_id)
    assert (pair.root / INBOX / "scan.pdf").read_bytes() == b"same-content"
    assert not (pair.root / INBOX / "scan.pdf").is_symlink()


def test_refuses_important_and_locked_copies(app, pair):
    dup_result(app)
    app.marks.mark_important(["id-dup"])
    with pytest.raises(InvalidRequest, match="marked Important"):
        resolve(app)
    app.marks.unmark_important(["id-dup"])
    app.locks.lock("id-dup")
    with pytest.raises(InvalidRequest, match="locked"):
        resolve(app)
    assert (pair.root / INBOX / "scan.pdf").is_file()
    assert not (pair.root / QUAR / INBOX).exists()


def test_refuses_files_not_known_to_be_the_same(app, pair):
    # nothing has been hashed yet
    with pytest.raises(InvalidRequest, match="not known to be the same"):
        resolve(app)
    dup_result(app)
    with pytest.raises(InvalidRequest, match="not known to be the same"):
        resolve(app, remove=("id-other",))


def test_versions_of_one_name_can_be_resolved_once_asked_for(app, fake_archive):
    fake_archive.add(f"{BANKS}/CV.pdf", b"version-one", drive_id="id-v1")
    fake_archive.add(f"{HOME}/cv.PDF", b"version-two-longer", drive_id="id-v2")
    fake_archive.add(f"{HOME}/other.pdf", b"version-one", drive_id="id-other")
    app.scan()
    [group] = dup_result(app).name_groups
    assert {f.drive_id for f in group.files} == {"id-v1", "id-v2"}
    with pytest.raises(InvalidRequest, match="not known to be the same"):
        app.maintenance.resolve([("id-v1", ["id-v2"])], "link")
    result = app.maintenance.resolve([("id-v1", ["id-v2"], "name")], "link")
    linked = fake_archive.root / HOME / "cv.PDF"
    assert linked.is_symlink() and linked.read_bytes() == b"version-one"
    assert (fake_archive.root / QUAR / HOME / "cv.PDF").read_bytes() == b"version-two-longer"
    app.activity.undo(result.batch_id)
    assert not linked.is_symlink() and linked.read_bytes() == b"version-two-longer"
    # the name is what makes them versions: another name is refused
    with pytest.raises(InvalidRequest, match="does not have the name"):
        app.maintenance.resolve([("id-v1", ["id-other"], "name")], "quarantine")


def test_refuses_a_file_changed_since_the_scan(app, pair):
    dup_result(app)
    path = pair.root / INBOX / "scan.pdf"
    path.write_bytes(b"different-ish")
    with pytest.raises(InvalidRequest, match="changed since the last scan"):
        resolve(app)


def test_refuses_the_same_file_twice_and_a_kept_file_that_is_removed(app, pair):
    dup_result(app)
    with pytest.raises(InvalidRequest, match="more than once"):
        resolve(app, remove=("id-keep",))
    with pytest.raises(InvalidRequest, match="more than once"):
        app.maintenance.resolve([("id-keep", ["id-dup"]), ("id-dup", ["id-keep"])], "link")


def test_link_needs_the_symlink_privilege(app, pair, monkeypatch):
    dup_result(app)
    monkeypatch.setattr("dam.maintenance.service.can_make_links", lambda: False)
    with pytest.raises(InvalidRequest, match="Developer Mode"):
        resolve(app)
    assert resolve(app, action="quarantine", dry=True).done  # moving needs no link


def test_the_group_listing_drops_what_was_replaced(app, pair):
    job = app.maintenance.start("duplicates")
    job.join(15)
    assert len(app.maintenance.result_of(job)[1].groups) == 1
    resolve(app)
    assert app.maintenance.result_of(job)[1].groups == []


# --- carry over ---


@pytest.fixture
def rich(app, pair):
    """The removed copy has tags, collections, a star, a note, a checklist, a tray item and
    From/For; the kept one has a few of its own."""
    app.tray_defs, _ = load_trays(DEFAULTS)
    app.tags.add("id-dup", ["tax", "2023"])
    app.tags.add("id-keep", ["2023"])
    taxes = app.collections.create("Tax 2023")
    app.collections.add_members(taxes.id, ["id-dup"])
    app.marks.star(["id-dup"])
    app.notes.set("file", "id-dup", "paid in June")
    app.notes.set("file", "id-keep", "original")
    app.notes.add_check("file", "id-dup", "call the bank")
    app.notes.add_check("file", "id-keep", "Call the bank")  # the same, other case
    app.notes.add_check("file", "id-dup", "file the form")
    item = app.trays.create_quick("to-read", ["id-dup"]).created[0]
    app.people = None
    app.assignments.set(["id-dup"], sender="Pohjola")
    app.assignments.set(["id-keep"], sender="Existing sender")
    dup_result(app)
    return item


def test_carry_over_is_listed_in_the_preview_and_added_after(app, pair, rich):
    dry = resolve(app, dry=True)
    [c] = dry.carry_over
    assert c.drive_id == "id-keep"
    assert c.tags == ["tax"]  # "2023" is already there
    assert sorted(c.collections) == ["Starred", "Tax 2023"]
    assert c.notes == ["paid in June"]
    assert c.checklist == ["file the form"]  # "call the bank" is there already
    assert len(c.items) == 1 and c.items[0].startswith("To read")
    assert c.sender is None  # the kept copy has one: never overwritten
    assert app.tags.for_file("id-keep") == ["2023"]  # a dry run adds nothing

    result = resolve(app)
    assert result.carry_errors == []
    assert sorted(app.tags.for_file("id-keep")) == ["2023", "tax"]
    names = {
        col.name
        for col in app.collections.list(include_builtin=True)
        if "id-keep" in [m.drive_id for m in col.members]
    }
    assert names == {"Tax 2023", "Ongoing"}
    assert app.notes.get("file", "id-keep") == "original\n\npaid in June"  # appended
    assert [c.text for c in app.notes.checklist("file", "id-keep")] == [
        "Call the bank",
        "file the form",
    ]
    assert "id-keep" in app.trays.for_file("id-dup")[0].files
    assert app.assignments.get(["id-keep"])["id-keep"].sender == "Existing sender"


def test_carry_over_fills_empty_from_and_keeps_the_note_when_the_keeper_has_none(app, pair):
    app.notes.set("file", "id-dup", "only here")
    app.assignments.set(["id-dup"], sender="Pohjola")
    dup_result(app)
    result = resolve(app)
    assert app.notes.get("file", "id-keep") == "only here"
    assert app.assignments.get(["id-keep"])["id-keep"].sender == "Pohjola"
    assert result.carry_over[0].sender == "Pohjola"


def test_undo_takes_back_the_collection_and_note_the_batch_added(app, pair, rich):
    result = resolve(app)
    app.activity.undo(result.batch_id)
    in_tax = [m.drive_id for m in app.collections.by_name("Tax 2023").members]
    assert in_tax == ["id-dup"]  # the keeper's membership went with the undo
    assert app.notes.get("file", "id-keep") == "original\n\npaid in June"  # an append stays


def test_no_carry_over_when_not_asked(app, pair, rich):
    result = resolve(app, carry=False)
    assert result.carry_over == []
    assert app.tags.for_file("id-keep") == ["2023"]


# --- cancel ---


def test_a_job_can_be_stopped_with_what_it_has(app, fake_archive, monkeypatch):
    for n in range(6):
        fake_archive.add(f"{BANKS}/f{n}.pdf", b"same-size", drive_id=f"a{n}")
    app.scan()
    started = threading.Event()
    real = duplicates.hash_file

    def slow(path, stopped):
        started.set()
        time.sleep(0.2)
        return real(path, stopped)

    monkeypatch.setattr(duplicates, "hash_file", slow)
    job = app.maintenance.start("duplicates")
    assert started.wait(5)
    job.stop()
    job.join(10)
    view = job.view()
    assert view.state == "stopped"
    assert view.result.complete is False
    assert view.done < 6


def test_progress_is_reported(app, pair):
    view = run(app, "duplicates")
    assert (view.done, view.total, view.bytes_done) == (3, 3, 36)


# --- the other checks ---


def test_empty_folders(app, fake_archive):
    fake_archive.add(f"{BANKS}/keeps-this-folder.txt", b"k", drive_id="id-k")
    (fake_archive.root / HOME / "Old").mkdir(parents=True)
    (fake_archive.root / HOME / "Old" / ".DS_Store").write_bytes(b"x")
    (fake_archive.root / HOME / "Full").mkdir()
    fake_archive.add(f"{HOME}/Full/a.txt", b"a", drive_id="id-a")
    (fake_archive.root / "30. Top").mkdir()  # top level: never offered
    (fake_archive.root / QUAR / "Gone").mkdir()  # inside the app's folder
    app.scan()
    result = run(app, "empty_folders").result
    assert [f.path for f in result.items] == [f"{HOME}/Old"]
    assert result.total == 1
    rec = app.repo.by_path(f"{HOME}/Old")
    assert result.items[0].drive_id == rec.drive_id
    # Mark for deletion is the existing quarantine of a folder
    batch = app.browse.quarantine([rec.drive_id], origin="ui")
    assert (fake_archive.root / QUAR / HOME / "Old").is_dir()
    assert batch.error is None


def test_a_listed_folder_drops_out_once_it_is_marked_for_deletion(app, fake_archive):
    fake_archive.add(f"{BANKS}/keeps-this-folder.txt", b"k", drive_id="id-k")
    (fake_archive.root / HOME / "Old").mkdir(parents=True)
    app.scan()
    job = app.maintenance.start("empty_folders")
    job.join(10)
    [folder] = app.maintenance.result_of(job)[1].items
    app.browse.quarantine([folder.drive_id], origin="ui")
    result = app.maintenance.result_of(job)[1]
    assert (result.items, result.total) == ([], 0)


def test_the_default_folders_are_not_listed_when_empty(app, fake_archive):
    fake_archive.add(f"{BANKS}/keeps-this-folder.txt", b"k", drive_id="id-k")
    (fake_archive.root / INBOX / "To pay").mkdir(parents=True)  # a filing code's folder
    (fake_archive.root / INBOX / "to read").mkdir()  # the same, in other case
    (fake_archive.root / INBOX / "Scans").mkdir()  # the owner's own: listed
    (fake_archive.root / QUAR).mkdir(exist_ok=True)
    app.scan()
    assert [f.path for f in run(app, "empty_folders").result.items] == [f"{INBOX}/Scans"]


def test_a_folder_with_something_not_yet_indexed_is_not_empty(app, fake_archive):
    fake_archive.add(f"{BANKS}/keeps-this-folder.txt", b"k", drive_id="id-k")
    (fake_archive.root / HOME / "Old").mkdir(parents=True)
    app.scan()
    (fake_archive.root / HOME / "Old" / "new.txt").write_bytes(b"new")  # not scanned yet
    assert run(app, "empty_folders").result.items == []


def test_broken_links_elsewhere_are_listed_and_quarantined(app, fake_archive):
    fake_archive.add(f"{BANKS}/a.pdf", b"a", drive_id="id-a")
    fake_archive.link(f"{HOME}/good.pdf", f"{BANKS}/a.pdf")
    (fake_archive.root / HOME).mkdir(exist_ok=True)
    (fake_archive.root / HOME / "dead.pdf").symlink_to(fake_archive.root / "gone" / "x.pdf")
    app.scan()
    result = run(app, "broken_links").result
    [link] = result.items
    assert (link.path, link.inside) == (f"{HOME}/dead.pdf", None)
    assert link.target is not None and link.target.endswith("gone/x.pdf")
    with pytest.raises(InvalidRequest, match="not in"):
        app.maintenance.remove_links([link.drive_id])  # only the publish roots
    batch = app.browse.quarantine([link.drive_id], origin="ui")
    assert batch.error is None and batch.failed is None
    assert os.path.lexists(fake_archive.root / QUAR / HOME / "dead.pdf")
    assert not os.path.lexists(fake_archive.root / HOME / "dead.pdf")
    app.activity.undo(batch.batch_id)
    assert (fake_archive.root / HOME / "dead.pdf").is_symlink()


def test_a_broken_link_in_ongoing_is_removed_and_journaled(app, fake_archive):
    (fake_archive.root / ONG / "Sauna").mkdir()
    dead = fake_archive.root / ONG / "Sauna" / "dead.pdf"
    dead.symlink_to(fake_archive.root / "gone" / "x.pdf")
    app.scan()
    [link] = run(app, "broken_links").result.items
    assert link.inside == ONG
    dry = app.maintenance.remove_links([link.drive_id], dry_run=True)
    assert [o.kind for o in dry.done] == [OpKind.UNLINK_SYMLINK]
    assert os.path.lexists(dead)
    result = app.maintenance.remove_links([link.drive_id])
    assert result.error is None and not os.path.lexists(dead)
    assert [r["kind"] for r in journal(app, result.batch_id)] == ["unlink_symlink"]
    # Undo would make a link to nothing: the operation layer refuses that (the target
    # must exist), so it says so and changes nothing
    with pytest.raises(GuardError):
        app.activity.undo(result.batch_id)
    assert not os.path.lexists(dead)


def test_collection_and_tray_entries_pointing_nowhere(app, fake_archive):
    app.tray_defs, _ = load_trays(DEFAULTS)
    fake_archive.add(f"{BANKS}/a.pdf", b"a", drive_id="id-a")
    fake_archive.add(f"{BANKS}/b.pdf", b"b", drive_id="id-b")
    fake_archive.add(f"{BANKS}/c.pdf", b"c", drive_id="id-c")
    app.scan()
    col = app.collections.create("Trip")
    app.collections.add_members(col.id, ["id-a", "id-b", "id-c"])
    app.trays.create_quick("to-read", ["id-a"])
    app.browse.quarantine(["id-a"], origin="ui")  # in To Delete
    (fake_archive.root / BANKS / "b.pdf").write_bytes(b"x")  # stays: present
    (fake_archive.root / BANKS / "c.pdf").rename(fake_archive.root / "elsewhere.tmp")
    app.scan()
    result = run(app, "references").result
    rows = {(r.kind, r.drive_id): (r.reason, r.owner_name) for r in result.items}
    assert rows[("collection", "id-a")][0] == "in To Delete"
    assert rows[("collection", "id-c")][0] == "missing"
    assert ("collection", "id-b") not in rows
    [tray_row] = [r for r in result.items if r.kind == "tray"]
    assert tray_row.owner_id == "to-read" and tray_row.reason == "in To Delete"
    assert tray_row.owner_name.startswith("To read")
    assert tray_row.item_id is not None


def test_a_missing_entry_shows_where_the_file_was_last_seen(app, fake_archive):
    fake_archive.add(f"{BANKS}/c.pdf", b"c", drive_id="id-c")
    fake_archive.add(f"{BANKS}/d.pdf", b"d", drive_id="id-d")
    app.scan()
    col = app.collections.create("Trip")
    app.collections.add_members(col.id, ["id-c", "id-d"])
    (fake_archive.root / BANKS / "c.pdf").rename(fake_archive.root / "elsewhere.tmp")
    app.browse.quarantine(["id-d"], origin="ui")
    app.scan()
    with app.engine.begin() as conn:  # the index forgot it; the journal still knows
        conn.execute(files.delete().where(files.c.drive_id == "id-d"))
    paths = {r.drive_id: (r.reason, r.path) for r in run(app, "references").result.items}
    assert paths["id-c"] == ("missing", f"{BANKS}/c.pdf")
    assert paths["id-d"] == ("missing", f"{QUAR}/{BANKS}/d.pdf")


def test_names_that_do_not_follow_the_convention(app, fake_archive):
    old = time.mktime((2021, 3, 4, 12, 0, 0, 0, 0, -1))
    path = fake_archive.add(f"{BANKS}/statement march.pdf", b"a", drive_id="id-a")
    os.utime(path, (old, old))
    fake_archive.add(f"{BANKS}/20230105-bill.pdf", b"b", drive_id="id-b")
    fake_archive.add(f"{BANKS}/20230105_ok.pdf", b"c", drive_id="id-c")
    fake_archive.add(f"{INBOX}/not-numbered.pdf", b"d", drive_id="id-d")
    fake_archive.add(f"{BANKS}/.hidden", b"e", drive_id="id-e")
    app.scan()
    result = run(app, "names").result
    assert {r.path: r.suggestion for r in result.items} == {
        f"{BANKS}/statement march.pdf": "20210304_statement march.pdf",
        f"{BANKS}/20230105-bill.pdf": "20230105_bill.pdf",
    }
    # the rename is the existing previewed rename
    [op] = app.browse.rename_file_preview("id-b", "20230105_bill.pdf", BANKS)
    assert (op.kind, op.dst) == (OpKind.RENAME, f"{BANKS}/20230105_bill.pdf")


def test_suggest_name():
    assert suggest_name("bill.pdf", None, None) is None
    assert suggest_name("bill.pdf", date(2022, 2, 3), None) == "20220203_bill.pdf"
    assert suggest_name("20230105 bill.pdf", date(2022, 2, 3), 0) == "20230105_bill.pdf"
    assert suggest_name("20230105_ok.pdf", None, None) is None


def test_waiting_in_to_delete(app, fake_archive):
    fake_archive.add(f"{BANKS}/old.pdf", b"o" * 10, drive_id="id-old")
    fake_archive.add(f"{BANKS}/new.pdf", b"n" * 20, drive_id="id-new")
    app.scan()
    app.browse.quarantine(["id-old"], origin="ui")
    app.browse.quarantine(["id-new"], origin="ui")
    long_ago = time.time() - 40 * 86400
    with app.engine.begin() as conn:  # the first was marked 40 days ago
        conn.execute(
            operations.update()
            .where(operations.c.dst == f"{QUAR}/{BANKS}/old.pdf")
            .values(finished=long_ago)
        )
    result = run(app, "waiting", days=30).result
    assert [(f.path, f.days, f.approximate) for f in result.items] == [
        (f"{QUAR}/{BANKS}/old.pdf", 40, False)
    ]
    assert (result.total, result.total_size) == (1, 10)
    assert (result.in_to_delete, result.in_to_delete_size) == (2, 30)
    assert run(app, "waiting", days=0).result.total == 2
    assert run(app, "waiting", days=50).result.items == []


def test_a_file_put_in_to_delete_by_hand_is_dated_from_the_disk(app, fake_archive):
    path = fake_archive.add(f"{QUAR}/stray.pdf", b"s", drive_id="id-s")
    app.scan()
    result = run(app, "waiting", days=0, wait=10).result
    [f] = result.items
    assert f.approximate is True
    assert path.exists()


# --- API ---


@pytest.fixture
def client(app):
    with TestClient(create_api(app, None), base_url=BASE) as c:
        yield c


H = {"Origin": BASE}


def poll(client, job_id):
    for _ in range(100):
        body = client.get(f"/api/maintenance/jobs/{job_id}", headers=H).json()
        if body["state"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_api_reset_forgets_a_kind_or_all(client, app, fake_archive):
    fake_archive.add(f"{BANKS}/a.txt", b"a", drive_id="id-a")
    app.scan()
    for kind in ("names", "empty_folders"):
        poll(
            client,
            client.post("/api/maintenance/jobs", json={"kind": kind}, headers=H).json()["job_id"],
        )
    gone = client.delete("/api/maintenance/jobs", params={"kind": "names"}, headers=H)
    assert gone.json() == {"forgotten": 1}
    assert client.get("/api/maintenance/jobs/latest/names", headers=H).json() is None
    assert client.get("/api/maintenance/jobs/latest/empty_folders", headers=H).json() is not None
    assert client.delete("/api/maintenance/jobs", headers=H).json() == {"forgotten": 1}
    assert client.get("/api/maintenance/jobs/latest/empty_folders", headers=H).json() is None
    bad = client.delete("/api/maintenance/jobs", params={"kind": "nope"}, headers=H)
    assert bad.status_code in (400, 422)


def test_api_duplicates_flow(client, app, pair):
    est = client.get("/api/maintenance/duplicates/estimate", headers=H).json()
    assert est["to_read_files"] == 3
    started = client.post("/api/maintenance/jobs", json={"kind": "duplicates"}, headers=H)
    assert started.status_code == 200 and started.json()["duplicates"] is None
    body = poll(client, started.json()["job_id"])
    assert body["state"] == "done" and body["kind"] == "duplicates"
    [group] = body["duplicates"]["groups"]
    assert group["keep"] == "id-keep"
    latest = client.get("/api/maintenance/jobs/latest/duplicates", headers=H).json()
    assert latest["job_id"] == started.json()["job_id"]
    assert client.get("/api/maintenance/jobs/latest/names", headers=H).json() is None

    choice = {"groups": [{"keep": "id-keep", "others": ["id-dup"]}], "action": "link"}
    dry = client.post(
        "/api/maintenance/duplicates/resolve", json={**choice, "dry_run": True}, headers=H
    )
    assert dry.status_code == 200
    assert [o["kind"] for o in dry.json()["done"] if o["kind"] != "mkdir"] == [
        "quarantine",
        "symlink",
    ]
    done = client.post("/api/maintenance/duplicates/resolve", json=choice, headers=H)
    assert done.json()["error"] is None
    assert (pair.root / INBOX / "scan.pdf").is_symlink()
    undo = client.post(f"/api/activity/{done.json()['batch_id']}/undo", json={}, headers=H)
    assert undo.status_code == 200
    assert (pair.root / INBOX / "scan.pdf").is_file()


def test_api_refusals_and_stop(client, app, pair):
    app.marks.mark_important(["id-dup"])
    started = client.post("/api/maintenance/jobs", json={"kind": "duplicates"}, headers=H).json()
    poll(client, started["job_id"])
    r = client.post(
        "/api/maintenance/duplicates/resolve",
        json={"groups": [{"keep": "id-keep", "others": ["id-dup"]}], "action": "quarantine"},
        headers=H,
    )
    assert r.status_code == 400 and "marked Important" in r.json()["error"]
    stopped = client.post(f"/api/maintenance/jobs/{started['job_id']}/stop", json={}, headers=H)
    assert stopped.status_code == 200
    assert client.get("/api/maintenance/jobs/nope", headers=H).status_code == 404
    assert (
        client.post("/api/maintenance/jobs", json={"kind": "bogus"}, headers=H).status_code == 422
    )


def test_files_table_untouched_by_a_check_except_hashes(app, pair):
    before = {r.drive_id: (r.path, r.size) for r in app.repo.regular_files()}
    dup_result(app)
    assert {r.drive_id: (r.path, r.size) for r in app.repo.regular_files()} == before
    with app.engine.connect() as conn:
        assert conn.execute(select(operations)).first() is None  # no journal rows
        assert conn.execute(select(files.c.sha256).where(files.c.sha256.is_not(None))).first()


# --- extra archive folders that are not there ----------------------------------------------


def test_broken_link_reason_offline(extra_folder, app, fake_archive, tmp_path):
    target = extra_folder.add("2009/x.pdf", b"x", drive_id="x1")
    (fake_archive.root / HOME).mkdir(exist_ok=True)
    (fake_archive.root / HOME / "x.pdf").symlink_to(target)
    (fake_archive.root / HOME / "dead.pdf").symlink_to(fake_archive.root / "gone" / "y.pdf")
    app.scan()
    assert [i.path for i in run(app, "broken_links").result.items] == [f"{HOME}/dead.pdf"]
    os.rename(extra_folder.root, tmp_path / "unplugged")
    app.scan()
    result = run(app, "broken_links").result
    assert [(i.path, i.reason) for i in result.items] == [
        (f"{HOME}/dead.pdf", "broken"),
        (f"{HOME}/x.pdf", "folder_not_connected"),
    ]
    assert result.total == 2


def test_broken_link_reason_detached(extra_folder, app, app_paths, fake_archive):
    from dam.app import App
    from dam.archive_folders import detach_folder

    target = extra_folder.add("2009/x.pdf", b"x", drive_id="x1")
    (fake_archive.root / HOME).mkdir(exist_ok=True)
    (fake_archive.root / HOME / "x.pdf").symlink_to(target)
    app.scan()
    detach_folder(app_paths, app.repo, "Old years", forget=False, dry_run=False)
    os.rename(extra_folder.root, extra_folder.root.with_name("moved away"))  # gone too
    again = App.create(app_paths.data_dir)
    try:
        again.scan()
        [link] = run(again, "broken_links").result.items
        assert (link.path, link.reason) == (f"{HOME}/x.pdf", "folder_detached")
    finally:
        again.close()


def test_remove_links_refuses_a_link_into_an_unplugged_folder(
    extra_folder, app, fake_archive, tmp_path
):
    target = extra_folder.add("2009/x.pdf", b"x", drive_id="x1")
    (fake_archive.root / ONG / "Sauna").mkdir()
    link = fake_archive.root / ONG / "Sauna" / "x.pdf"
    link.symlink_to(target)
    app.scan()
    os.rename(extra_folder.root, tmp_path / "unplugged")
    app.scan()
    [found] = run(app, "broken_links").result.items
    assert found.reason == "folder_not_connected"
    with pytest.raises(InvalidRequest, match="'Old years' is not connected"):
        app.maintenance.remove_links([found.drive_id], dry_run=True)
    assert os.path.lexists(link)


def test_label_clash_check(extra_folder, app, fake_archive):
    assert run(app, "label_clashes").result.items == []
    fake_archive.add("old YEARS/a.pdf", b"a")
    app.scan()
    result = run(app, "label_clashes").result
    assert (result.items, result.total) == (["Old years"], 1)
    with TestClient(create_api(app, None), base_url=BASE) as c:
        job = c.post("/api/maintenance/jobs", json={"kind": "label_clashes"}, headers=H)
        assert job.status_code == 200, job.text
        body = poll(c, job.json()["job_id"])
    assert body["label_clashes"] == {"items": ["Old years"], "total": 1}


# --- ignoring results ---


def test_an_ignored_duplicate_group_stays_out_until_a_new_copy_joins(app, pair):
    [group] = run(app, "duplicates").result.groups
    app.maintenance.ignored.add(
        "duplicates", group.sha256, "20230101_bill.pdf", ["id-keep", "id-dup"]
    )
    result = app.maintenance.result_of(run_job(app, "duplicates"))[1]
    assert (result.groups, result.groups_total) == ([], 0)
    pair.add(f"{HOME}/third copy.pdf", b"same-content", drive_id="id-third")
    app.scan()
    [back] = app.maintenance.result_of(run_job(app, "duplicates"))[1].groups
    assert {f.drive_id for f in back.files} == {"id-keep", "id-dup", "id-third"}


def test_ignored_versions_folders_and_entries_are_left_out(app, fake_archive):
    fake_archive.add(f"{BANKS}/Statement.pdf", b"one", drive_id="id-v1")
    fake_archive.add(f"{HOME}/statement.pdf", b"two", drive_id="id-v2")
    (fake_archive.root / HOME / "Old").mkdir()
    (fake_archive.root / HOME / "Older").mkdir()
    app.scan()
    old = app.repo.by_path(f"{HOME}/Old")
    ignored = app.maintenance.ignored
    ignored.add("versions", "STATEMENT.pdf", "Statement.pdf", ["id-v1", "id-v2"])  # folded
    ignored.add("empty_folders", old.drive_id, f"{HOME}/Old")
    dups = app.maintenance.result_of(run_job(app, "duplicates"))[1]
    assert (dups.name_groups, dups.name_groups_total) == ([], 0)
    folders = app.maintenance.result_of(run_job(app, "empty_folders"))[1]
    assert [f.path for f in folders.items] == [f"{HOME}/Older"] and folders.total == 1
    [entry] = ignored.list()[1:]  # newest first
    assert ignored.unignore(entry.id) and not ignored.unignore(entry.id)
    assert app.maintenance.result_of(run_job(app, "duplicates"))[1].name_groups_total == 1


def test_an_ignored_reference_is_keyed_by_owner_item_and_file(app, fake_archive):
    fake_archive.add(f"{BANKS}/c.pdf", b"c", drive_id="id-c")
    app.scan()
    col = app.collections.create("Trip")
    app.collections.add_members(col.id, ["id-c"])
    (fake_archive.root / BANKS / "c.pdf").rename(fake_archive.root / "elsewhere.tmp")
    app.scan()
    app.maintenance.ignored.add("references", f"collection-{col.id}--id-c", "c.pdf")
    result = app.maintenance.result_of(run_job(app, "references"))[1]
    assert (result.items, result.total) == ([], 0)


def test_api_ignore_list_and_stop_ignoring(client, app, fake_archive):
    body = {"kind": "names", "key": "id-x", "label": "10. Financial/x.pdf"}
    added = client.post("/api/maintenance/ignored", json=body, headers=H)
    assert added.status_code == 200 and added.json()["label"] == "10. Financial/x.pdf"
    listed = client.get("/api/maintenance/ignored", headers=H).json()
    assert [(i["kind"], i["key"]) for i in listed] == [("names", "id-x")]
    group = {"kind": "duplicates", "key": "abc", "label": "a.pdf"}
    assert client.post("/api/maintenance/ignored", json=group, headers=H).status_code == 400
    bad = {**body, "kind": "waiting"}
    assert client.post("/api/maintenance/ignored", json=bad, headers=H).status_code in (400, 422)
    gone = client.delete(f"/api/maintenance/ignored/{added.json()['id']}", headers=H)
    assert gone.status_code == 200
    assert client.get("/api/maintenance/ignored", headers=H).json() == []
    assert (
        client.delete(f"/api/maintenance/ignored/{added.json()['id']}", headers=H).status_code
        == 404
    )


def test_unfinished_copies_check(extra_folder, app, fake_archive):
    assert run(app, "unfinished_copies").result.items == []
    left = extra_folder.add(f"2010/{TEMP_COPY_PREFIX}abcd1234-a.pdf", b"half")
    fake_archive.add(f"10. Financial/{TEMP_COPY_PREFIX}0011aabb-b.pdf", b"partial")
    fake_archive.add("10. Financial/dam-copy-not-ours.pdf", b"x")  # no leading dot
    app.scan()
    result = run(app, "unfinished_copies").result
    assert [(i.path, i.size) for i in result.items] == [
        (f"10. Financial/{TEMP_COPY_PREFIX}0011aabb-b.pdf", 7),
        (f"Old years/2010/{TEMP_COPY_PREFIX}abcd1234-a.pdf", 4),
    ]
    assert (result.total, result.total_size) == (2, 11)
    with TestClient(create_api(app, None), base_url=BASE) as c:
        job = c.post("/api/maintenance/jobs", json={"kind": "unfinished_copies"}, headers=H)
        assert job.status_code == 200, job.text
        job_id = job.json()["job_id"]
        assert poll(c, job_id)["unfinished_copies"]["total"] == 2
        os.rename(left, left.with_name("kept.pdf"))  # the owner dealt with it
        app.scan()
        body = c.get(f"/api/maintenance/jobs/{job_id}").json()
    assert body["unfinished_copies"]["total"] == 1
    assert body["unfinished_copies"]["total_size"] == 7
