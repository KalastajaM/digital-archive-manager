"""Naming senders from their Y-tunnus: the name read next to each ID, the owner's confirmed
names, and the From (sender) they fill on the files that carry the ID."""

import pytest
from sqlalchemy import text

from dam import countries
from dam.config import Person, Settings
from dam.core.paths import ArchivePaths
from dam.errors import InvalidRequest
from dam.extract.base import ExtractedText, ExtractorRegistry
from dam.index.content import ContentIndexer
from dam.index.repo import FileRepo
from dam.index.repo.model import FileRecord
from dam.services.assignments import AssignmentService
from dam.services.senders import SenderNames

YT = ("fi.ytunnus", "0112038-9")
OTHER = ("fi.ytunnus", "0201256-6")


def _setup(fake_archive, engine):
    paths = ArchivePaths(fake_archive.root, Settings(archive_root=fake_archive.root))
    repo = FileRepo(engine, inbox=paths.inbox)
    indexer = ContentIndexer(paths, repo, engine, ExtractorRegistry(), 60, barcode_trays=lambda: ())
    people = lambda: [Person(name="Anna", match=["Anna"])]  # noqa: E731
    return repo, indexer, SenderNames(engine, repo), AssignmentService(engine, repo, people)


def _file(repo, drive_id, body, sha=None):
    repo.upsert(FileRecord(drive_id=drive_id, path=f"10. Bills/{drive_id}.pdf", size=1, mtime=1.0))
    repo.save_content(drive_id, sha or f"sha-{drive_id}", ExtractedText(body, "test"), "indexed")


def _row(names, value="0112038-9"):
    return next(r for r in names.list() if r.value == value)


def test_the_pass_keeps_the_name_read_next_to_each_id(fake_archive, engine):
    repo, indexer, names, _ = _setup(fake_archive, engine)
    _file(repo, "a", "Vesilaitos Oy, Y-tunnus 0112038-9")
    _file(repo, "b", "VESILAITOS OY\nY-tunnus 0112038-9")
    _file(repo, "c", "Vesilaitos Oy Y-tunnus 0112038-9 / Lasku")
    _file(repo, "d", "Y-tunnus 0201256-6")  # on one file only: not listed
    indexer.run_identifiers_once()
    rows = names.list()
    assert [(r.kind, r.value, r.files, r.suggested, r.name) for r in rows] == [
        ("fi.ytunnus", "0112038-9", 3, "Vesilaitos Oy", None)
    ]


def test_most_files_first_and_ids_without_a_name_too(fake_archive, engine):
    repo, indexer, names, _ = _setup(fake_archive, engine)
    for i in range(3):
        _file(repo, f"x{i}", "Y-tunnus 0201256-6")
    for i in range(2):
        _file(repo, f"y{i}", "Elisa Oyj, 0112038-9")
    indexer.run_identifiers_once()
    assert [(r.value, r.files, r.suggested) for r in names.list()] == [
        ("0201256-6", 3, None),
        ("0112038-9", 2, "Elisa Oyj"),
    ]


def test_confirming_a_name_fills_from_on_every_file_with_the_id(fake_archive, engine):
    repo, indexer, names, assign = _setup(fake_archive, engine)
    for d in ("a", "b", "c"):
        _file(repo, d, "Vesilaitos Oy, Y-tunnus 0112038-9")
    indexer.run_identifiers_once()
    assign.set(["b"], sender="Water Board")  # the owner's word stays
    assign.set(["c"], person="Anna")
    changed = names.confirm(*YT, " Vesilaitos  Oy ")
    assert changed == 1
    got = assign.get(["a", "b", "c"])
    assert (got["a"].sender, got["a"].set_by) == ("Vesilaitos Oy", "filing")
    assert (got["b"].sender, got["b"].set_by) == ("Water Board", "owner")
    # the owner set the person only: their row is left as it is
    assert (got["c"].sender, got["c"].person, got["c"].set_by) == (None, "Anna", "owner")
    row = _row(names)
    assert (row.name, row.filled) == ("Vesilaitos Oy", 1)


def test_a_person_from_a_filing_stays_when_the_sender_is_filled(fake_archive, engine):
    repo, indexer, names, assign = _setup(fake_archive, engine)
    _file(repo, "a", "Vesilaitos Oy, Y-tunnus 0112038-9")
    indexer.run_identifiers_once()
    assign.record_filing("a", "Anna")
    names.confirm(*YT, "Vesilaitos Oy")
    got = assign.get(["a"])["a"]
    assert (got.sender, got.person, got.set_by) == ("Vesilaitos Oy", "Anna", "filing")
    names.clear(*YT)
    got = assign.get(["a"])["a"]
    assert (got.sender, got.person, got.set_by) == (None, "Anna", "filing")


def test_changing_the_name_changes_the_senders_it_set(fake_archive, engine):
    repo, indexer, names, assign = _setup(fake_archive, engine)
    _file(repo, "a", "Vesilaitos Oy, Y-tunnus 0112038-9")
    indexer.run_identifiers_once()
    names.confirm(*YT, "Vesilaitos Oy")
    assert names.confirm(*YT, "Helsingin Vesi") == 1
    assert assign.get(["a"])["a"].sender == "Helsingin Vesi"


def test_clearing_a_name_takes_back_its_senders_only(fake_archive, engine):
    repo, indexer, names, assign = _setup(fake_archive, engine)
    for d in ("a", "b"):
        _file(repo, d, "Vesilaitos Oy, Y-tunnus 0112038-9")
    indexer.run_identifiers_once()
    names.confirm(*YT, "Vesilaitos Oy")
    assign.set(["b"], sender="Vesilaitos Oy")  # the owner said so too: theirs now
    assert names.clear(*YT) == 1
    got = assign.get(["a", "b"])
    assert "a" not in got
    assert (got["b"].sender, got["b"].set_by) == ("Vesilaitos Oy", "owner")
    assert _row(names).name is None


def test_two_named_ids_that_disagree_set_no_sender(fake_archive, engine):
    repo, indexer, names, assign = _setup(fake_archive, engine)
    _file(repo, "a", "Perintä Oy 0112038-9, for Elisa Oyj 0201256-6")
    _file(repo, "b", "Perintä Oy 0112038-9")
    _file(repo, "c", "Elisa Oyj 0201256-6")
    indexer.run_identifiers_once()
    names.confirm(*YT, "Perintä Oy")
    assert assign.get(["a"])["a"].sender == "Perintä Oy"
    names.confirm(*OTHER, "Elisa Oyj")
    got = assign.get(["a", "b", "c"])
    assert "a" not in got  # which one sent it? not for dam to guess
    assert got["b"].sender == "Perintä Oy" and got["c"].sender == "Elisa Oyj"
    names.clear(*OTHER)
    assert assign.get(["a"])["a"].sender == "Perintä Oy"


def test_two_ids_with_the_same_name_agree(fake_archive, engine):
    repo, indexer, names, assign = _setup(fake_archive, engine)
    _file(repo, "a", "Elisa Oyj 0112038-9 0201256-6")
    indexer.run_identifiers_once()
    names.confirm(*YT, "Elisa Oyj")
    names.confirm(*OTHER, "elisa oyj")
    assert assign.get(["a"])["a"].sender == "Elisa Oyj"
    names.clear(*YT)
    assert assign.get(["a"])["a"].sender == "Elisa Oyj"  # the other ID still names it


def test_a_file_read_later_gets_the_named_sender(fake_archive, engine):
    repo, indexer, names, assign = _setup(fake_archive, engine)
    _file(repo, "a", "Vesilaitos Oy, Y-tunnus 0112038-9")
    indexer.run_identifiers_once()
    names.confirm(*YT, "Vesilaitos Oy")
    _file(repo, "b", "Lasku. Y-tunnus 0112038-9")
    indexer.run_identifiers_once()
    assert assign.get(["b"])["b"].sender == "Vesilaitos Oy"


def test_new_content_without_the_id_loses_the_named_sender(fake_archive, engine):
    repo, indexer, names, assign = _setup(fake_archive, engine)
    _file(repo, "a", "Vesilaitos Oy, Y-tunnus 0112038-9")
    indexer.run_identifiers_once()
    names.confirm(*YT, "Vesilaitos Oy")
    _file(repo, "a", "Something else entirely", sha="sha-new")
    indexer.run_identifiers_once()
    assert "a" not in assign.get(["a"])


def test_missing_and_parked_files_are_left_alone(fake_archive, engine):
    repo, indexer, names, assign = _setup(fake_archive, engine)
    for d in ("a", "b"):
        _file(repo, d, "Vesilaitos Oy, Y-tunnus 0112038-9")
    indexer.run_identifiers_once()
    with engine.begin() as conn:
        conn.execute(text("UPDATE files SET missing = 1 WHERE drive_id = 'b'"))
    assert names.confirm(*YT, "Vesilaitos Oy") == 1
    assert "b" not in assign.get(["b"])
    assert _row(names).files == 1  # live files only; listed while it has a name


def test_a_bad_name_or_kind_is_refused(fake_archive, engine):
    repo, indexer, names, _ = _setup(fake_archive, engine)

    with pytest.raises(InvalidRequest):
        names.confirm(*YT, "   ")
    with pytest.raises(InvalidRequest):
        names.confirm("core.domain", "a.fi", "A")  # no names for domains
    with pytest.raises(InvalidRequest):
        names.confirm("fi.ytunnus", "0112038-8", "A")  # not a valid Y-tunnus


def test_signature_moves_on_so_stored_ids_are_read_again_for_names():
    assert "fi:2" in countries.signature()


def test_migration_0046_adds_the_name_column_and_table(tmp_path, new_engine):
    from alembic import command
    from alembic.config import Config

    from dam.db.engine import MIGRATIONS_DIR, migrate, write_tx

    engine = new_engine(tmp_path / "dam.sqlite")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with write_tx(engine) as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0043")
        connection.execute(
            text("INSERT INTO file_identifiers VALUES ('a', 'fi.ytunnus', '0112038-9', 'sha')")
        )
    assert migrate(engine) == []
    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(identifier_names)"))]
        row = conn.execute(text("SELECT value, name FROM file_identifiers")).one()
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0046"
    assert cols == ["kind", "value", "name", "set_by", "set_at"]
    assert tuple(row) == ("0112038-9", None)


def test_clearing_takes_back_from_files_that_no_longer_carry_the_id(fake_archive, engine):
    repo, indexer, names, assign = _setup(fake_archive, engine)
    for d in ("a", "b"):
        _file(repo, d, "Vesilaitos Oy, Y-tunnus 0112038-9")
    indexer.run_identifiers_once()
    names.confirm(*YT, "Vesilaitos Oy")
    with engine.begin() as conn:
        conn.execute(text("UPDATE files SET missing = 1 WHERE drive_id = 'b'"))
    assert names.clear(*YT) == 2
    assert assign.get(["a", "b"]) == {}


def test_new_text_takes_the_named_sender_back_at_once(fake_archive, engine):
    repo, indexer, names, assign = _setup(fake_archive, engine)
    _file(repo, "a", "Vesilaitos Oy, Y-tunnus 0112038-9")
    indexer.run_identifiers_once()
    names.confirm(*YT, "Vesilaitos Oy")
    _file(repo, "a", "", sha="sha-new")  # no text: the identifiers pass never reads it
    assert "a" not in assign.get(["a"])


def test_a_case_only_correction_is_saved(fake_archive, engine):
    repo, indexer, names, assign = _setup(fake_archive, engine)
    _file(repo, "a", "ELISA OYJ 0112038-9")
    indexer.run_identifiers_once()
    names.confirm(*YT, "ELISA OYJ")
    assert names.confirm(*YT, "Elisa Oyj") == 1
    assert _row(names).name == "Elisa Oyj"
    assert assign.get(["a"])["a"].sender == "Elisa Oyj"


def test_a_from_the_owner_cleared_stays_cleared(fake_archive, engine):
    repo, indexer, names, assign = _setup(fake_archive, engine)
    _file(repo, "a", "Vesilaitos Oy, Y-tunnus 0112038-9")
    indexer.run_identifiers_once()
    names.confirm(*YT, "Vesilaitos Oy")
    assign.set(["a"], sender=None)
    names.confirm(*YT, "Helsingin Vesi")
    _file(repo, "a", "Vesilaitos Oy, Y-tunnus 0112038-9", sha="sha-2")
    indexer.run_identifiers_once()
    got = assign.get(["a"])["a"]
    assert (got.sender, got.person, got.set_by) == (None, None, "owner")


def test_names_of_a_country_that_is_off_fill_nothing(fake_archive, engine):
    from dam import packs

    repo, indexer, names, assign = _setup(fake_archive, engine)
    _file(repo, "a", "Vesilaitos Oy, Y-tunnus 0112038-9")
    indexer.run_identifiers_once()
    names.confirm(*YT, "Vesilaitos Oy")
    packs.activate(packs.build([], ["en"]))
    _file(repo, "b", "Y-tunnus 0112038-9")
    indexer.run_identifiers_once()
    assert "b" not in assign.get(["b"])


def test_a_failing_name_finder_keeps_the_identifiers(fake_archive, engine, monkeypatch):
    import dataclasses

    repo, indexer, _, _ = _setup(fake_archive, engine)

    def boom(text, value):
        raise ValueError("no")

    def broken(pack):
        specs = tuple(dataclasses.replace(s, name=boom) if s.name else s for s in pack.identifiers)
        return dataclasses.replace(pack, identifiers=specs)

    monkeypatch.setattr(countries, "ALL", tuple(broken(p) for p in countries.ALL))
    _file(repo, "a", "Vesilaitos Oy, Y-tunnus 0112038-9")
    indexer.run_identifiers_once()
    assert ("fi.ytunnus", "0112038-9") in repo.identifiers_for("a")
