"""The inbox list reads its files' rows in a few queries, not a few per file, and keeps
the "similar files" folder search until the index changes; the suggestion itself is
worked out afresh on every list, so a rule edit, new text or a page-1 read shows at once."""

from contextlib import contextmanager

import yaml
from sqlalchemy import event

from dam.config import Person
from dam.db.generation import WriteGeneration
from dam.extract.base import ExtractedText
from dam.extract.layout import Line, Page1Layout
from dam.index.scanner import scan
from dam.rules.model import Rule
from dam.rules.similar import SOURCE as SIMILAR

INBOX = "##. Organize"
ACME = "20. Companies/Acme"
BOLT = "20. Companies/Boltworks"
BILL = (
    "Northpower Oy lasku\nEräpäivä 15.11.2026\nYhteensä 84,20 €\n"
    "IBAN FI21 1234 5600 0007 85\nViitenumero RF18 5390 0754 7034"
)
PEOPLE = [Person(name="Tiina", match=["Tiina Visser"])]
ZONE = (0.06, 0.10, 0.52, 0.30)


def add(app, fake_archive, rel, drive_id, text="x", page1=None):
    fake_archive.add(rel, content=drive_id.encode(), drive_id=drive_id)
    scan(app.paths, app.repo)
    app.repo.save_content(
        drive_id, f"sha-{drive_id}", ExtractedText(text, "test", False, page1), "indexed"
    )


@contextmanager
def statements(app):
    """The SQL statements run inside the block."""
    seen: list[str] = []

    def note(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    event.listen(app.engine, "before_cursor_execute", note)
    try:
        yield seen
    finally:
        event.remove(app.engine, "before_cursor_execute", note)


def fts(seen: list[str]) -> int:
    return sum(1 for s in seen if "MATCH" in s and "file_fts" in s)


def by_id(app):
    return {e.record.drive_id: e for e in app.inbox.list()}


def filed_acme(app, fake_archive, n=2):
    for i in range(n):
        add(app, fake_archive, f"{ACME}/old{i}.pdf", f"acme-{i}", "Acmetools Oy invoice")


# --- same answers as the one-file paths --------------------------------------------------------


def test_list_gives_what_the_one_file_paths_give(app, fake_archive):
    (app.rules_dir / "50-northpower.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "id": "northpower",
                    "when": {"text_contains": ["northpower"]},
                    "then": {"folder": "10. Financial/Banks", "payee": "Northpower Oy"},
                }
            ]
        ),
        encoding="utf-8",
    )
    assert app.reload_rules() == []
    app.settings.people = PEOPLE
    app.settings.address_zone = ZONE
    filed_acme(app, fake_archive)
    page = Page1Layout([Line("Tiina Visser", (0.08, 0.15, 0.33, 0.17))], "text-layer")
    add(app, fake_archive, f"{INBOX}/bill.pdf", "bill", BILL, page)
    add(app, fake_archive, f"{INBOX}/acme.pdf", "acme", "Acmetools Oy order")
    add(app, fake_archive, f"{INBOX}/plain.pdf", "plain", "nothing here")
    add(app, fake_archive, f"{INBOX}/edited.pdf", "edited", BILL)
    app.scan_fields.put("edited", [{"kind": "total", "label": None, "value": "1,00"}])
    app.assignments.set(["plain"], person="Tiina")
    app.repo.save_barcode("plain", "sha-plain", "barcode-that-does-not-parse")

    entries = by_id(app)
    assert set(entries) == {"bill", "acme", "plain", "edited"}
    assert entries["bill"].prefill["payee"] == "Northpower Oy"
    assert entries["acme"].suggestion.folder == ACME
    assert entries["edited"].fields_edited and entries["edited"].prefill == {"total": "1.00"}
    assert entries["plain"].suggestion.person == "Tiina"
    for drive_id, entry in entries.items():
        assert entry.suggestion == app.inbox.suggestion(drive_id), drive_id
        assert entry.prefill == app.inbox.prefill_for(drive_id), drive_id
        assert entry.text_excerpt == app.repo.text_for(drive_id)[:500]
        if not entry.fields_edited:
            assert entry.fields == app.inbox.detected_fields(drive_id), drive_id


def test_list_queries_do_not_grow_with_the_files(app, fake_archive):
    filed_acme(app, fake_archive)
    for i in range(3):
        add(app, fake_archive, f"{INBOX}/a{i}.pdf", f"a{i}", BILL)
    app.inbox.list()  # fills the similar-files cache
    with statements(app) as few:
        app.inbox.list()
    for i in range(3, 15):
        add(app, fake_archive, f"{INBOX}/a{i}.pdf", f"a{i}", BILL)
    app.inbox.list()
    with statements(app) as many:
        assert len(app.inbox.list()) == 15
    assert len(many) == len(few)
    assert fts(many) == 0


# --- the similar-files cache -------------------------------------------------------------------


def test_similar_folder_is_searched_once_until_the_index_changes(app, fake_archive):
    filed_acme(app, fake_archive)
    add(app, fake_archive, f"{INBOX}/acme.pdf", "acme", "Acmetools Oy order")
    with statements(app) as first:
        assert by_id(app)["acme"].suggestion.folder == ACME
    assert fts(first) == 1
    with statements(app) as again:
        by_id(app)
    assert fts(again) == 0
    # a write that has nothing to do with the files or their words keeps it
    app.scan_fields.put("acme", [{"kind": "total", "label": None, "value": "1,00"}])
    app.repo.save_layout("acme", "sha-acme", Page1Layout([], "text-layer"))
    with statements(app) as unrelated:
        by_id(app)
    assert fts(unrelated) == 0


def test_similar_folder_follows_the_index(app, fake_archive):
    add(app, fake_archive, f"{ACME}/old0.pdf", "acme-0", "Acmetools Oy invoice")
    add(app, fake_archive, f"{INBOX}/acme.pdf", "acme", "Acmetools Oy order")
    assert by_id(app)["acme"].suggestion.folder is None  # one match is not enough
    add(app, fake_archive, f"{ACME}/old1.pdf", "acme-1", "Acmetools Oy invoice")
    found = by_id(app)["acme"].suggestion
    assert (found.folder, found.folder_source) == (ACME, SIMILAR)
    # the filed files move: the suggestion follows them
    for i in range(2):
        app.repo.update_path(f"{ACME}/old{i}.pdf", f"{BOLT}/old{i}.pdf")
    assert by_id(app)["acme"].suggestion.folder == BOLT


def test_new_text_gives_a_new_similar_folder(app, fake_archive):
    filed_acme(app, fake_archive)
    for i in range(2):
        add(app, fake_archive, f"{BOLT}/b{i}.pdf", f"bolt-{i}", "Boltworks Ab kuitti")
    add(app, fake_archive, f"{INBOX}/scan.pdf", "scan", "Acmetools Oy order")
    assert by_id(app)["scan"].suggestion.folder == ACME
    app.repo.save_content("scan", "sha-scan-2", ExtractedText("Boltworks Ab", "test"), "indexed")
    assert by_id(app)["scan"].suggestion.folder == BOLT


def test_a_rule_edit_shows_at_once(app, fake_archive):
    filed_acme(app, fake_archive)
    add(app, fake_archive, f"{INBOX}/acme.pdf", "acme", "Acmetools Oy order")
    assert by_id(app)["acme"].suggestion.folder == ACME
    rule = {"id": "acme", "when": {"text_contains": ["acmetools"]}, "then": {"folder": "Tools"}}
    app.save_rule(Rule.model_validate(rule))
    found = by_id(app)["acme"].suggestion
    assert (found.folder, found.folder_source) == ("Tools", "rule:acme")
    app.delete_rule("acme")
    assert by_id(app)["acme"].suggestion.folder == ACME


def test_a_page1_read_shows_at_once(app, fake_archive):
    app.settings.people = PEOPLE
    app.settings.address_zone = ZONE
    for r in list(app.rules):
        app.delete_rule(r.id)
    rule = {"id": "mail", "when": {"text_contains": ["kela"]}, "then": {"folder": "Mail/{person}"}}
    app.save_rule(Rule.model_validate(rule))
    add(app, fake_archive, f"{INBOX}/a.pdf", "a", "kela")
    assert by_id(app)["a"].suggestion.waiting_for_page1
    page = Page1Layout([Line("Tiina Visser", (0.08, 0.15, 0.33, 0.17))], "text-layer")
    assert app.repo.save_layout("a", "sha-a", page)
    found = by_id(app)["a"].suggestion
    assert found.folder == "Mail/Tiina" and not found.waiting_for_page1


# --- the write generation ----------------------------------------------------------------------


def test_write_generation_moves_on_writes_to_its_tables_only(app, fake_archive):
    gen = WriteGeneration(app.engine, ("files", "file_fts"))
    add(app, fake_archive, f"{INBOX}/a.pdf", "a", "x")
    before = gen.value
    app.repo.save_layout("a", "sha-a", Page1Layout([], "text-layer"))
    app.repo.text_for("a")
    assert gen.value == before
    app.repo.save_content("a", "sha-a2", ExtractedText("y", "test"), "indexed")
    assert gen.value > before
