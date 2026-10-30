"""The identifiers pass: business IDs, IBANs and domains read from the stored text of each
file (never the file itself), kept per content, redone when content or packs change."""

from sqlalchemy import text

from dam import countries
from dam.config import Settings
from dam.core.paths import ArchivePaths
from dam.extract.base import ExtractedText, ExtractorRegistry
from dam.index.content import ContentIndexer
from dam.index.repo import FileRepo
from dam.index.repo.model import FileRecord

BILL = "Vesilaitos Oy, Y-tunnus 0112038-9, www.vesilaitos.fi. Tilinumero FI21 1234 5600 0007 85"


def _setup(fake_archive, engine):
    paths = ArchivePaths(fake_archive.root, Settings(archive_root=fake_archive.root))
    repo = FileRepo(engine, inbox=paths.inbox)
    indexer = ContentIndexer(paths, repo, engine, ExtractorRegistry(), 60, barcode_trays=lambda: ())
    return repo, indexer


def _file(repo, drive_id, body, sha="a" * 64, path=None):
    repo.upsert(
        FileRecord(drive_id=drive_id, path=path or f"10. Bills/{drive_id}.pdf", size=1, mtime=1.0)
    )
    repo.save_content(drive_id, sha, ExtractedText(body, "test"), "indexed")


def test_a_file_gets_its_identifiers_once(fake_archive, engine):
    repo, indexer = _setup(fake_archive, engine)
    _file(repo, "f1", BILL)
    assert indexer.run_identifiers_once() == 1
    assert repo.identifiers_for("f1") == [
        ("core.iban", "FI2112345600000785"),
        ("core.domain", "vesilaitos.fi"),
        ("fi.ytunnus", "0112038-9"),
    ]
    assert indexer.run_identifiers_once() == 0
    assert repo.files_with_identifier("fi.ytunnus", "0112038-9") == ["f1"]


def test_a_file_without_identifiers_is_read_once_too(fake_archive, engine):
    repo, indexer = _setup(fake_archive, engine)
    _file(repo, "f1", "Just a note")
    assert indexer.run_identifiers_once() == 1
    assert repo.identifiers_for("f1") == [] and indexer.run_identifiers_once() == 0
    assert repo.identifier_progress(countries.signature()) == (1, 1)


def test_new_content_is_read_again(fake_archive, engine):
    repo, indexer = _setup(fake_archive, engine)
    _file(repo, "f1", BILL)
    indexer.run_identifiers_once()
    _file(repo, "f1", "Now from www.other.fi", sha="b" * 64)
    assert indexer.run_identifiers_once() == 1
    assert repo.identifiers_for("f1") == [("core.domain", "other.fi")]


def test_a_save_for_old_content_is_refused(fake_archive, engine):
    repo, _ = _setup(fake_archive, engine)
    _file(repo, "f1", BILL)
    assert not repo.save_identifiers(
        "f1", "c" * 64, countries.signature(), [("fi.ytunnus", "0112038-9")]
    )
    assert repo.identifiers_for("f1") == []


def test_another_pack_version_reads_everything_again(fake_archive, engine):
    repo, indexer = _setup(fake_archive, engine)
    _file(repo, "f1", BILL)
    indexer.run_identifiers_once()
    assert repo.identifier_progress("core:1 fi:3") == (0, 1)
    assert len(repo.next_for_identifiers(10, "core:1 fi:3")) == 1


def test_rekey_keeps_and_purge_removes_them(fake_archive, engine):
    repo, indexer = _setup(fake_archive, engine)
    _file(repo, "tmp-1", BILL, path="10. Bills/bill.pdf")
    indexer.run_identifiers_once()
    repo.rekey("tmp-1", "real-1")
    assert ("fi.ytunnus", "0112038-9") in repo.identifiers_for("real-1")
    repo.park("10. Bills/bill.pdf")
    repo.purge_parked()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM file_identifiers")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM file_identifier_reads")).scalar() == 0


def test_a_huge_text_is_handled(fake_archive, engine):
    repo, indexer = _setup(fake_archive, engine)
    _file(repo, "f1", ("Rivi ilman tunnuksia 12,00 € " * 200_000) + BILL)
    assert indexer.run_identifiers_once() == 1
    assert ("fi.ytunnus", "0112038-9") in repo.identifiers_for("f1")


def test_the_step_runs_the_pass(fake_archive, engine):
    repo, indexer = _setup(fake_archive, engine)
    _file(repo, "f1", BILL)
    indexer.step()
    assert repo.identifiers_for("f1") != []


def test_new_text_for_the_same_content_is_read_again(fake_archive, engine):
    """OCR or an extractor can give other text for the same bytes."""
    repo, indexer = _setup(fake_archive, engine)
    _file(repo, "f1", BILL)
    indexer.run_identifiers_once()
    _file(repo, "f1", "Now from www.other.fi")  # same sha256, other text
    assert indexer.run_identifiers_once() == 1
    assert repo.identifiers_for("f1") == [("core.domain", "other.fi")]


def test_the_progress_count_is_kept_until_the_next_write(fake_archive, engine, monkeypatch):
    repo, indexer = _setup(fake_archive, engine)
    _file(repo, "f1", BILL)
    calls = []
    real = repo._identifier_progress
    monkeypatch.setattr(repo, "_identifier_progress", lambda sig: calls.append(sig) or real(sig))
    sig = countries.signature()
    assert repo.identifier_progress(sig) == (0, 1)
    assert repo.identifier_progress(sig) == (0, 1) and len(calls) == 1  # kept
    indexer.run_identifiers_once()
    assert repo.identifier_progress(sig) == (1, 1) and len(calls) == 2  # a write: counted again


def test_a_step_loads_a_limited_amount_of_text(fake_archive, engine):
    repo, _ = _setup(fake_archive, engine)
    for n in range(3):
        _file(repo, f"f{n}", "x" * 1_000_000, sha=str(n) * 64)
    sig = countries.signature()
    assert len(repo.next_for_identifiers(10, sig, max_chars=1_500_000)) == 1
    assert len(repo.next_for_identifiers(10, sig, max_chars=2_500_000)) == 2
    # one text larger than the cap is still read, alone
    assert len(repo.next_for_identifiers(10, sig, max_chars=10)) == 1


def test_counts_for_many_identifiers_in_one_go(fake_archive, engine):
    repo, indexer = _setup(fake_archive, engine)
    _file(repo, "f1", BILL, sha="1" * 64)
    _file(repo, "f2", "Y-tunnus 0112038-9", sha="2" * 64)
    indexer.run_identifiers_once()
    got = repo.identifier_counts(
        [
            ("fi.ytunnus", "0112038-9"),
            ("core.domain", "vesilaitos.fi"),
            ("core.domain", "nowhere.fi"),
        ]
    )
    assert got == {("fi.ytunnus", "0112038-9"): 2, ("core.domain", "vesilaitos.fi"): 1}
    assert repo.identifier_counts([]) == {}
