"""Inbox: tray guesses, open trays, payee prefill and the no-duplicate rule on filing."""

import pytest
import yaml

from dam.extract.base import ExtractedText
from dam.index.scanner import scan
from dam.rules.fields import DetectedFields
from dam.services.errors import InvalidRequest
from dam.services.inbox import FileRequest, prefill_of

INBOX = "##. Organize"
BANKS = "10. Financial/Banks"
NORTHPOWER_BILL = (
    "Northpower Oy lasku\nEräpäivä 15.11.2026\nYhteensä 84,20 €\n"
    "IBAN FI21 1234 5600 0007 85\nViitenumero RF18 5390 0754 7034"
)


def add_scan(app, fake_archive, name, drive_id, text):
    fake_archive.add(f"{INBOX}/{name}", content=drive_id.encode(), drive_id=drive_id)
    scan(app.paths, app.repo)
    app.repo.save_content(drive_id, None, ExtractedText(text, "test"), "indexed")


def add_rule(app, **then):
    (app.rules_dir / "50-northpower.yaml").write_text(
        yaml.safe_dump(
            [{"id": "northpower", "when": {"text_contains": ["northpower"]}, "then": then}]
        ),
        encoding="utf-8",
    )
    assert app.reload_rules() == []


def test_prefill_of_gives_payee_when_given():
    assert prefill_of(DetectedFields(), payee="Northpower Oy") == {"payee": "Northpower Oy"}
    assert prefill_of(DetectedFields()) == {}
    assert prefill_of(DetectedFields(), payee="") == {}


def test_inbox_entry_prefill_has_payee_from_a_rule(app, fake_archive):
    add_rule(app, folder=BANKS, payee="Northpower Oy")
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    [entry] = app.inbox.list()
    assert entry.prefill["payee"] == "Northpower Oy"
    assert entry.prefill["total"] == "84.20"


def test_filing_into_to_pay_fills_payee_from_the_rule(app, fake_archive):
    add_rule(app, folder=BANKS, payee="Northpower Oy")
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    app.inbox.file_it([FileRequest("id-a", "a.pdf", BANKS, tray="to-pay")])
    [item] = app.trays.list("to-pay")
    assert item.fields["payee"] == "Northpower Oy"


def test_inbox_entry_tray_guess_and_open_trays(app, fake_archive):
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    add_scan(app, fake_archive, "b.pdf", "id-b", "just a letter")
    entries = {e.record.drive_id: e for e in app.inbox.list()}
    assert entries["id-a"].tray_guess == "to-pay" and entries["id-a"].open_trays == []
    assert entries["id-b"].tray_guess is None
    item = app.trays.create("to-pay", ["id-a"], {}, None)
    entries = {e.record.drive_id: e for e in app.inbox.list()}
    assert entries["id-a"].open_trays == ["to-pay"]
    app.trays.done(item.id, {})
    entries = {e.record.drive_id: e for e in app.inbox.list()}
    assert entries["id-a"].open_trays == []


def test_rule_tray_overrides_the_heuristic(app, fake_archive):
    add_rule(app, folder=BANKS, tray="to-read")
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    [entry] = app.inbox.list()
    assert entry.tray_guess == "to-read"


def test_filing_into_a_tray_the_file_is_already_in_is_refused(app, fake_archive):
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    app.trays.create("to-pay", ["id-a"], {}, None)
    req = FileRequest("id-a", "a.pdf", BANKS, tray="to-pay")
    with pytest.raises(InvalidRequest, match="already in To pay"):
        app.inbox.preview([req])
    with pytest.raises(InvalidRequest, match="already in To pay"):
        app.inbox.file_it([req])
    assert app.repo.get("id-a").path == f"{INBOX}/a.pdf"  # nothing moved
    assert len(app.trays.list("to-pay")) == 1
    # another tray, or no tray, is fine
    app.inbox.preview([FileRequest("id-a", "a.pdf", BANKS, tray="to-read")])
    app.inbox.preview([FileRequest("id-a", "a.pdf", BANKS)])


def test_a_done_item_does_not_block_filing_into_its_tray(app, fake_archive):
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    item = app.trays.create("to-pay", ["id-a"], {}, None)
    app.trays.done(item.id, {})
    outcome = app.inbox.file_it([FileRequest("id-a", "a.pdf", BANKS, tray="to-pay")])
    assert len(outcome.items) == 1


# --- a stale index: filing checks the disk, not only the index ----------------------


def assert_filing_refused(app, fake_archive, reqs, match):
    from sqlalchemy import select

    from dam.db.tables import operations

    for call in (app.inbox.preview, app.inbox.file_it):
        with pytest.raises(InvalidRequest, match=match):
            call(reqs)
    with pytest.raises(InvalidRequest, match=match):
        app.inbox.file_it(reqs, dry_run=True)
    with app.engine.connect() as conn:
        assert list(conn.execute(select(operations))) == []
    assert not (fake_archive.root / BANKS / "a.pdf").exists()
    assert not (fake_archive.root / BANKS / "ok.pdf").exists()  # the valid one stayed too
    assert (fake_archive.root / INBOX / "ok.pdf").exists()
    assert app.tags.for_file("id-a") == [] and app.trays.list("to-pay") == []


def stale_reqs():
    return [
        FileRequest("id-ok", "ok.pdf", BANKS),
        FileRequest("id-a", "a.pdf", BANKS, tags=["t"], tray="to-pay"),
    ]


def test_filing_a_file_replaced_by_another_file_is_refused(app, fake_archive):
    import os

    fake_archive.add(f"{INBOX}/ok.pdf", drive_id="id-ok")
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    os.remove(fake_archive.root / INBOX / "a.pdf")
    fake_archive.add(f"{INBOX}/a.pdf", b"someone else", drive_id="id-new")  # no scan
    assert_filing_refused(app, fake_archive, stale_reqs(), "no longer the file 'id-a'")
    assert (fake_archive.root / INBOX / "a.pdf").read_bytes() == b"someone else"
    # a rename in place is checked the same way
    with pytest.raises(InvalidRequest, match="no longer the file 'id-a'"):
        app.inbox.file_it([FileRequest("id-a", "b.pdf", INBOX)])
    assert (fake_archive.root / INBOX / "a.pdf").exists()


def test_filing_a_file_replaced_by_a_folder_is_refused(app, fake_archive):
    import os

    import xattr

    from dam.index.driveid import DRIVE_ID_XATTR

    fake_archive.add(f"{INBOX}/ok.pdf", drive_id="id-ok")
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    os.remove(fake_archive.root / INBOX / "a.pdf")
    (fake_archive.root / INBOX / "a.pdf").mkdir()  # no scan: the index still says a file
    assert_filing_refused(app, fake_archive, stale_reqs(), "no longer the file 'id-a'")
    # even a folder that carries the requested Drive id is not a file
    xattr.setxattr(fake_archive.root / INBOX / "a.pdf", DRIVE_ID_XATTR, b"id-a")
    assert_filing_refused(app, fake_archive, stale_reqs(), "not a file on disk")
    assert (fake_archive.root / INBOX / "a.pdf").is_dir()


def test_filing_an_inbox_file_without_a_drive_id_works(app, fake_archive):
    fake_archive.add(f"{INBOX}/new.pdf", b"not uploaded yet", drive_id=None)
    scan(app.paths, app.repo)
    [entry] = app.inbox.list()
    drive_id = entry.record.drive_id
    assert drive_id.startswith("local:")
    req = FileRequest(drive_id, "Filed.pdf", BANKS, tags=["t"])
    assert [op.dst for op in app.inbox.preview([req])] == [f"{BANKS}/Filed.pdf"]
    outcome = app.inbox.file_it([req])
    assert outcome.batch.failed is None and outcome.batch.error is None
    assert (fake_archive.root / BANKS / "Filed.pdf").read_bytes() == b"not uploaded yet"
    assert app.tags.for_file(drive_id) == ["t"]


def test_filing_a_local_file_replaced_by_one_with_a_drive_id_is_refused(app, fake_archive):
    import os

    fake_archive.add(f"{INBOX}/new.pdf", b"mine", drive_id=None)
    scan(app.paths, app.repo)
    drive_id = app.repo.by_path(f"{INBOX}/new.pdf").drive_id
    os.remove(fake_archive.root / INBOX / "new.pdf")
    fake_archive.add(f"{INBOX}/new.pdf", b"mine", drive_id="id-real")  # no scan
    for call in (app.inbox.preview, app.inbox.file_it):
        with pytest.raises(InvalidRequest, match="now has Drive id 'id-real'"):
            call([FileRequest(drive_id, "new.pdf", BANKS)])
    assert (fake_archive.root / INBOX / "new.pdf").exists()
    assert not (fake_archive.root / BANKS / "new.pdf").exists()


def add_filed(app, fake_archive, rel, drive_id, text):
    fake_archive.add(rel, content=drive_id.encode(), drive_id=drive_id)
    scan(app.paths, app.repo)
    app.repo.save_content(drive_id, None, ExtractedText(text, "test"), "indexed")


def test_folder_learned_from_similar_filed_files(app, fake_archive):
    add_filed(app, fake_archive, "50. Health/Näkymä/a.pdf", "f1", "Näkymä Oy lasku")
    add_filed(app, fake_archive, "50. Health/Näkymä/b.pdf", "f2", "Näkymä vastaanotto")
    add_filed(app, fake_archive, "10. Financial/Banks/c.pdf", "f3", "Northbank tiliote")
    add_scan(app, fake_archive, "Naekymae hinnasto.pdf", "id-a", "Näkymä hinnasto 2027")
    add_scan(app, fake_archive, "x.pdf", "id-b", "Completely unrelated stuff")
    entries = {e.record.drive_id: e for e in app.inbox.list()}
    assert entries["id-a"].suggestion.folder == "50. Health/Näkymä"
    assert entries["id-a"].suggestion.folder_source == "similar files"
    assert entries["id-b"].suggestion.folder is None


def test_rules_beat_similar_files_and_special_folders_do_not_vote(app, fake_archive):
    add_rule(app, folder=BANKS)
    add_filed(app, fake_archive, "50. Health/H/a.pdf", "f1", "Northpower northpower")
    add_filed(app, fake_archive, "50. Health/H/b.pdf", "f2", "Northpower northpower")
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    [entry] = app.inbox.list()
    assert entry.suggestion.folder == BANKS
    assert entry.suggestion.folder_source == "rule:northpower"


def test_similar_files_in_special_folders_are_ignored(app, fake_archive):
    add_filed(app, fake_archive, "##. To Delete/a.pdf", "f1", "Zorbax Zorbax")
    add_filed(app, fake_archive, "##. To Delete/b.pdf", "f2", "Zorbax Zorbax")
    add_scan(app, fake_archive, "a.pdf", "id-a", "Zorbax letter")
    [entry] = app.inbox.list()
    assert entry.suggestion.folder is None


def test_a_single_similar_file_is_not_enough(app, fake_archive):
    add_filed(app, fake_archive, "50. Health/H/a.pdf", "f1", "Zorbax Zorbax")
    add_scan(app, fake_archive, "a.pdf", "id-a", "Zorbax letter")
    [entry] = app.inbox.list()
    assert entry.suggestion.folder is None


def test_suggested_name_repairs_mojibake(app, fake_archive):
    add_scan(app, fake_archive, "NÃ¤kymÃ¤ TyÃ¶elÃ¤mÃ¤palvelut (5).pdf", "id-a", "x")
    [entry] = app.inbox.list()
    assert "Näkymä_Työelämäpalvelut" in entry.suggestion.name
    assert "Ã" not in entry.suggestion.name


def test_filing_into_another_tray_moves_the_files_open_item(app, fake_archive):
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    item = app.trays.create("to-pay", ["id-a"], {}, None)
    outcome = app.inbox.file_it(
        [FileRequest("id-a", "a.pdf", BANKS, tray="follow-up", tray_fields={"waiting_for": "Bob"})]
    )
    assert outcome.items == [item.id]
    assert app.trays.list("to-pay") == []
    [moved] = app.trays.list("follow-up")
    assert moved.id == item.id and moved.fields["waiting_for"] == "Bob"
    # undoing the filing puts the item back where it was
    app.activity.undo(outcome.batch.batch_id)
    assert [i.id for i in app.trays.list("to-pay")] == [item.id]
    assert app.trays.list("follow-up") == []
