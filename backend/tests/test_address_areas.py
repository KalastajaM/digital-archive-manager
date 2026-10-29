"""The address area of one document (migration 0047): it replaces the archive's area and a
rule's for that document; "none" means nobody is looked for on it."""

from dam.address_areas import NONE, AddressAreas
from dam.config import Person
from dam.extract.layout import Line, Page1Layout
from dam.index.repo import FileRecord
from dam.rules.engine import DOCUMENT_AREA, suggest
from dam.rules.model import Rule
from dam.rules.people import PeopleContext
from test_api import LOCAL_ORIGIN, make_client
from test_people import add, fill, run

INBOX = "##. Organize"
ZONE = (0.06, 0.10, 0.52, 0.30)
LOW = (0.05, 0.75, 0.5, 0.9)
PEOPLE = [Person(name="Tiina", match=["Tiina Visser"])]
PUT = {"headers": LOCAL_ORIGIN}


def rule(**extra):
    return Rule.model_validate(
        {
            "id": "mail",
            "when": {"text_contains": ["kela"], "folder_is": INBOX},
            "then": {"folder": "Mail/{person}"},
            **extra,
        }
    )


def rec():
    return FileRecord(drive_id="a", path=f"{INBOX}/a.pdf", name="a.pdf", ext="pdf")


LOW_LETTER = Page1Layout([Line("Tiina Visser", (0.08, 0.80, 0.33, 0.82))], "text-layer")


def test_the_documents_own_area_wins_over_the_general_one_and_a_rules():
    general = suggest(
        rec(), "kela", [rule()], layout=LOW_LETTER, people=PeopleContext(PEOPLE, ZONE)
    )
    assert general.person is None
    own = suggest(
        rec(), "kela", [rule()], layout=LOW_LETTER, people=PeopleContext(PEOPLE, ZONE, None, LOW)
    )
    assert (own.person, own.person_source, own.folder) == ("Tiina", DOCUMENT_AREA, "Mail/Tiina")
    (area,) = [a for a in own.areas if a.kind == "address"]
    assert area.document and area.rule_id == "" and area.box == LOW
    # over a rule's own area too
    ruled = rule(person_zone=[0.05, 0.1, 0.5, 0.3])
    over = suggest(
        rec(), "kela", [ruled], layout=LOW_LETTER, people=PeopleContext(PEOPLE, ZONE, None, LOW)
    )
    assert over.person_source == DOCUMENT_AREA


def test_none_looks_for_nobody_but_an_assignment_still_counts():
    letter = Page1Layout([Line("Tiina Visser", (0.08, 0.15, 0.33, 0.17))], "text-layer")
    off = suggest(
        rec(), "kela", [rule()], layout=letter, people=PeopleContext(PEOPLE, ZONE, None, NONE)
    )
    assert off.person is None and off.people_found == []
    assert not [a for a in off.areas if a.kind == "address"]
    assigned = suggest(
        rec(), "kela", [rule()], layout=letter, people=PeopleContext(PEOPLE, ZONE, "Tiina", NONE)
    )
    assert (assigned.person, assigned.person_source) == ("Tiina", "assigned")


def test_store_set_none_and_clear(app):
    areas = AddressAreas(app.engine)
    assert areas.of("a") is None
    areas.set("a", LOW)
    assert areas.of("a") == LOW
    areas.set("a", NONE)
    assert areas.of("a") == NONE and areas.all() == {"a": NONE}
    areas.clear("a")
    assert areas.of("a") is None and areas.all() == {}


def test_replay_reads_the_documents_own_area(app, fake_archive):
    fill(app, fake_archive)
    add(app, fake_archive, "Mail/Tiina/20250610_Kela.pdf", "f", "Kela", LOW_LETTER)
    assert "f" in [n.drive_id for n in run(app, rule()).not_checked]
    r = run(app, rule(), document_zones=lambda: {"f": LOW})
    assert "f" not in [n.drive_id for n in r.not_checked]


def test_api_moves_removes_and_restores_a_documents_area(app, fake_archive):
    add(app, fake_archive, f"{INBOX}/kela.pdf", "k", "Kela", LOW_LETTER)
    with make_client(app) as c:
        assert c.get("/api/files/k/address-area").json() == {"state": "general", "box": None}
        moved = c.put("/api/files/k/address-area", json={"box": list(LOW)}, **PUT)
        assert moved.json() == {"state": "document", "box": list(LOW)}
        off = c.put("/api/files/k/address-area", json={"box": None}, **PUT)
        assert off.json() == {"state": "none", "box": None}
        back = c.delete("/api/files/k/address-area", **PUT)
        assert back.json() == {"state": "general", "box": None}
        bad = c.put("/api/files/k/address-area", json={"box": [0.5, 0.5, 0.2, 0.2]}, **PUT)
        assert bad.status_code == 400
        assert c.get("/api/files/nope/address-area").status_code == 404
    assert app.address_areas.of("k") is None
