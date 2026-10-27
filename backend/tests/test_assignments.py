"""From (sender) and For (person): the service, the API, the filing record, the replay
against marked documents and the effect on {person}."""

import pytest
from sqlalchemy import text

from dam.config import Person
from dam.errors import InvalidRequest, NotFound
from dam.extract.base import ExtractedText
from dam.extract.layout import Line, Page1Layout
from dam.index.scanner import scan
from dam.rules.model import Rule
from dam.rules.replay import NOT_READ, replay
from dam.services.assignments import UNSET
from test_api import LOCAL_ORIGIN, make_client, post

INBOX = "##. Organize"
PEOPLE = [
    Person(name="Michiel", match=["Michiel Visser"]),
    Person(name="Tiina", match=["Tiina Visser"]),
]
ZONE = (0.06, 0.10, 0.52, 0.30)
HEADER = (0.05, 0.02, 0.45, 0.14)


def add(app, fake_archive, rel, drive_id, text="x", page1=None):
    fake_archive.add(rel, content=drive_id.encode(), drive_id=drive_id)
    scan(app.paths, app.repo)
    app.repo.save_content(
        drive_id, f"sha-{drive_id}", ExtractedText(text, "test", False, page1), "indexed"
    )


@pytest.fixture
def three(app, fake_archive):
    app.settings.people = PEOPLE
    app.settings.address_zone = ZONE
    for n in "abc":
        add(app, fake_archive, f"{INBOX}/{n}.pdf", n)
    return app.assignments


# --- the service -----------------------------------------------------------------------


def test_set_sender_and_person_on_many(three):
    done = three.set(["a", "b"], sender="Pohjola", person="tiina")
    assert {(a.drive_id, a.sender, a.person, a.set_by) for a in done} == {
        ("a", "Pohjola", "Tiina", "owner"),  # the person as the list spells it
        ("b", "Pohjola", "Tiina", "owner"),
    }
    assert three.person_of("a") == "Tiina" and three.person_of("c") is None
    assert three.persons() == {"a": "Tiina", "b": "Tiina"}
    assert three.with_sender("POHJOLA") == ["a", "b"] or sorted(three.with_sender("POHJOLA")) == [
        "a",
        "b",
    ]


def test_an_omitted_field_stays_and_null_clears(three):
    three.set(["a"], sender="Pohjola", person="Tiina")
    three.set(["a"], person=None)  # sender left out: unchanged
    got = three.get(["a"])["a"]
    assert (got.sender, got.person) == ("Pohjola", None)
    three.set(["a"], sender="Verohallinto")  # person left out: still none
    assert three.get(["a"])["a"].sender == "Verohallinto"
    three.set(["a"], sender=None)  # both empty: the row goes
    assert three.get(["a"]) == {}
    with three.engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM file_assignments")).scalar() == 0


def test_a_sender_keeps_the_spelling_already_in_use(three):
    three.set(["a"], sender="Pohjola")
    three.set(["b"], sender="  pohjola  ")
    assert three.get(["b"])["b"].sender == "Pohjola"
    three.set(["c"], sender="Verohallinto")
    assert three.senders() == [("Pohjola", 2), ("Verohallinto", 1)]


@pytest.mark.parametrize(
    "kwargs, error",
    [
        ({"person": "Nobody"}, InvalidRequest),
        ({"sender": "  "}, InvalidRequest),
        ({"sender": "x" * 200}, InvalidRequest),
        ({}, InvalidRequest),
    ],
)
def test_bad_input_writes_nothing(three, kwargs, error):
    with pytest.raises(error):
        three.set(["a", "b"], **kwargs)
    assert three.get(["a", "b"]) == {}


def test_unknown_files_are_refused_before_anything_is_written(three):
    with pytest.raises(NotFound):
        three.set(["a", "nope"], sender="Pohjola")
    assert three.get(["a"]) == {}
    with pytest.raises(InvalidRequest):
        three.set([], sender="x")


def test_the_filing_never_overwrites_the_owner(three):
    assert three.record_filing("a", "Tiina") is True
    got = three.get(["a"])["a"]
    assert (got.person, got.set_by) == ("Tiina", "filing")
    three.set(["a"], person="Michiel")
    assert three.record_filing("a", "Tiina") is False
    assert three.person_of("a") == "Michiel"
    # a filing keeps the sender the file has
    three.set(["b"], sender="Pohjola")
    three.set(["b"], sender=None)
    three.set(["c"], sender="Pohjola")
    assert three.record_filing("c", "Tiina") is False  # the owner set something for c


def test_unset_marker_is_not_none():
    assert UNSET is not None


# --- the API -----------------------------------------------------------------------------


def test_api_put_get_and_senders(app, three):
    with make_client(app) as c:
        r = c.put(
            "/api/assignments",
            json={"drive_ids": ["a", "b"], "sender": "Pohjola", "person": "Tiina"},
            headers=LOCAL_ORIGIN,
        )
        assert r.status_code == 200, r.text
        assert sorted((x["drive_id"], x["sender"], x["person"], x["set_by"]) for x in r.json()) == [
            ("a", "Pohjola", "Tiina", "owner"),
            ("b", "Pohjola", "Tiina", "owner"),
        ]
        got = c.get("/api/assignments", params=[("drive_id", "a"), ("drive_id", "c")]).json()
        assert [x["drive_id"] for x in got] == ["a"]
        # omitted = unchanged, null = clear
        only_person = c.put(
            "/api/assignments",
            json={"drive_ids": ["a"], "person": None},
            headers=LOCAL_ORIGIN,
        ).json()
        assert only_person[0]["sender"] == "Pohjola" and only_person[0]["person"] is None
        assert c.get("/api/senders").json() == [{"sender": "Pohjola", "count": 2}]
        cleared = c.put(
            "/api/assignments", json={"drive_ids": ["a", "b"], "sender": None}, headers=LOCAL_ORIGIN
        )
        assert cleared.status_code == 200
        assert [x["drive_id"] for x in cleared.json()] == ["b"]  # a has nothing left
        assert c.get("/api/senders").json() == []


def test_api_refusals(app, three):
    with make_client(app) as c:

        def put(body):
            return c.put("/api/assignments", json=body, headers=LOCAL_ORIGIN)

        assert put({"drive_ids": ["a"], "person": "Nobody"}).status_code == 400
        assert put({"drive_ids": ["a"], "sender": ""}).status_code == 400
        assert put({"drive_ids": ["nope"], "sender": "X"}).status_code == 404
        assert put({"drive_ids": ["a"]}).status_code == 400
        assert put({"drive_ids": [], "sender": "X"}).status_code in (400, 422)
    assert three.get(["a"]) == {}


def test_inbox_entries_and_file_detail_carry_the_assignment(app, three):
    three.set(["a"], sender="Pohjola", person="Tiina")
    with make_client(app) as c:
        entries = {e["record"]["drive_id"]: e for e in c.get("/api/inbox").json()}
        assert entries["a"]["assignment"]["sender"] == "Pohjola"
        assert entries["a"]["assignment"]["person"] == "Tiina"
        assert entries["a"]["assignment"]["set_by"] == "owner"
        assert entries["b"]["assignment"] is None
        assert c.get("/api/files/a").json()["assignment"]["person"] == "Tiina"
        assert c.get("/api/files/b").json()["assignment"] is None


# --- the assigned person wins ---------------------------------------------------------------


def person_rule():
    return Rule.model_validate(
        {
            "id": "mail",
            "when": {"text_contains": ["kela"], "folder_is": INBOX},
            "then": {"folder": "Mail/{person}"},
        }
    )


def test_an_assignment_beats_the_address_area_in_the_inbox(app, fake_archive):
    app.settings.people = PEOPLE
    app.settings.address_zone = ZONE
    for r in list(app.rules):
        app.delete_rule(r.id)
    app.save_rule(person_rule())
    page = Page1Layout([Line("Tiina Visser", (0.08, 0.15, 0.33, 0.17))], "text-layer")
    add(app, fake_archive, f"{INBOX}/a.pdf", "a", "kela", page)
    with make_client(app) as c:
        s = c.get("/api/inbox").json()[0]["suggestion"]
        assert (s["folder"], s["person"], s["person_source"]) == (
            "Mail/Tiina",
            "Tiina",
            "address area",
        )
        c.put(
            "/api/assignments",
            json={"drive_ids": ["a"], "person": "Michiel"},
            headers=LOCAL_ORIGIN,
        )
        s = c.get("/api/inbox").json()[0]["suggestion"]
    assert (s["folder"], s["person"], s["person_source"]) == ("Mail/Michiel", "Michiel", "assigned")
    assert s["people_found"] == ["Tiina"]


def test_an_assigned_person_makes_an_unread_page_enough(app, fake_archive):
    app.settings.people = PEOPLE
    for r in list(app.rules):
        app.delete_rule(r.id)
    app.save_rule(person_rule())
    add(app, fake_archive, f"{INBOX}/a.pdf", "a", "kela")  # page 1 not read
    app.assignments.set(["a"], person="Tiina")
    entry = app.inbox.list()[0]
    assert entry.suggestion.folder == "Mail/Tiina" and not entry.suggestion.waiting_for_page1


# --- recording from a filing -----------------------------------------------------------------


def test_filing_with_a_person_folder_the_owner_kept_records_the_person(app, fake_archive):
    app.settings.people = PEOPLE
    app.settings.address_zone = ZONE
    for r in list(app.rules):
        app.delete_rule(r.id)
    app.save_rule(person_rule())
    fake_archive.add("Mail/Tiina/old.txt", content=b"old", drive_id="old")
    page = Page1Layout([Line("Tiina Visser", (0.08, 0.15, 0.33, 0.17))], "text-layer")
    add(app, fake_archive, f"{INBOX}/a.pdf", "a", "kela", page)
    add(app, fake_archive, f"{INBOX}/b.pdf", "b", "kela", page)
    with make_client(app) as c:
        body = {"requests": [{"drive_id": "a", "name": "a.pdf", "folder": "Mail/Tiina"}]}
        assert post(c, "/api/inbox/file", body).status_code == 200
    got = app.assignments.get(["a"])["a"]
    assert (got.person, got.set_by, got.sender) == ("Tiina", "filing", None)
    # not kept (another folder): nothing recorded
    fake_archive.add("Other/old.txt", content=b"old", drive_id="old2")
    app.scan()
    with make_client(app) as c:
        body = {"requests": [{"drive_id": "b", "name": "b.pdf", "folder": "Other"}]}
        assert post(c, "/api/inbox/file", body).status_code == 200
    assert app.assignments.get(["b"]) == {}


def test_the_owners_assignment_is_not_overwritten_by_a_filing(app, fake_archive):
    app.settings.people = PEOPLE
    app.settings.address_zone = ZONE
    for r in list(app.rules):
        app.delete_rule(r.id)
    app.save_rule(person_rule())
    fake_archive.add("Mail/Michiel/old.txt", content=b"old", drive_id="old")
    add(app, fake_archive, f"{INBOX}/a.pdf", "a", "kela")
    app.assignments.set(["a"], person="Michiel")
    with make_client(app) as c:
        body = {"requests": [{"drive_id": "a", "name": "a.pdf", "folder": "Mail/Michiel"}]}
        assert post(c, "/api/inbox/file", body).status_code == 200
    assert app.assignments.get(["a"])["a"].set_by == "owner"


# --- the replay against the marked documents -----------------------------------------------------


def sender_rule(word="pohjola"):
    return Rule.model_validate(
        {
            "id": "pohjola",
            "sender": "Pohjola",
            "when": {"zones": [{"box": list(HEADER), "text_contains": [word]}], "folder_is": INBOX},
            "then": {"folder": "Insurance/Pohjola"},
        }
    )


def test_replay_compares_the_rule_with_the_documents_marked_as_its_sender(app, fake_archive):
    header = Page1Layout([Line("Pohjola Vakuutus", (0.08, 0.04, 0.30, 0.07))], "text-layer")
    elsewhere = Page1Layout([Line("Pohjola maksu", (0.08, 0.60, 0.30, 0.63))], "text-layer")
    add(app, fake_archive, "Insurance/Pohjola/a.pdf", "a", "pohjola", header)  # found
    add(app, fake_archive, f"{INBOX}/b.pdf", "b", "pohjola", header)  # found, in the inbox
    add(app, fake_archive, "20. Home/c.pdf", "c", "pohjola", elsewhere)  # missed
    add(app, fake_archive, "20. Home/d.pdf", "d", "pohjola")  # page 1 not read
    add(app, fake_archive, "20. Home/e.pdf", "e", "pohjola", header)  # not marked
    app.assignments.set(["a", "b", "c", "d"], sender="Pohjola")
    queued = []
    r = replay(
        app.engine,
        sender_rule(),
        [sender_rule()],
        app.settings.special_folders,
        layouts_for=app.repo.layouts_for,
        want_layouts=queued.extend,
        sender_ids=app.assignments.with_sender,
    )
    m = r.marked
    assert (m.total, m.found) == (4, 2)
    assert [(x.path, x.drive_id) for x in m.missed] == [("20. Home/c.pdf", "c")]
    assert [(n.path, n.reason) for n in m.not_checked] == [("20. Home/d.pdf", NOT_READ)]
    assert "d" in queued


def test_replay_marked_only_for_a_rule_with_a_sender(app, fake_archive):
    add(app, fake_archive, "20. Home/a.pdf", "a", "pohjola")
    app.assignments.set(["a"], sender="Pohjola")
    plain = Rule.model_validate({"id": "p", "when": {"text_contains": ["pohjola"]}})
    r = replay(
        app.engine,
        plain,
        [plain],
        app.settings.special_folders,
        sender_ids=app.assignments.with_sender,
    )
    assert r.marked is None
    nothing = sender_rule().model_copy(update={"sender": "Nobody"})
    r = replay(
        app.engine,
        nothing,
        [nothing],
        app.settings.special_folders,
        sender_ids=app.assignments.with_sender,
    )
    assert (r.marked.total, r.marked.found, r.marked.missed) == (0, 0, [])


def test_replay_api_has_marked_and_the_rule_keeps_its_sender(app, fake_archive):
    header = Page1Layout([Line("Pohjola Vakuutus", (0.08, 0.04, 0.30, 0.07))], "text-layer")
    add(app, fake_archive, "Insurance/Pohjola/a.pdf", "a", "pohjola", header)
    app.assignments.set(["a"], sender="Pohjola")
    body = {
        "id": "pohjola",
        "sender": "Pohjola",
        "when": {"zones": [{"box": list(HEADER), "text_contains": ["pohjola"]}]},
        "then": {"folder": "Insurance/Pohjola"},
    }
    with make_client(app) as c:
        for r in list(app.rules):
            app.delete_rule(r.id)
        out = post(c, "/api/rules/replay", {"rule": body}).json()
        assert out["marked"] == {"total": 1, "found": 1, "missed": [], "not_checked": []}
        plain = post(c, "/api/rules/replay", {"rule": {**body, "sender": None}}).json()
        assert plain["marked"] is None
        saved = c.put("/api/rules/pohjola", json=body, headers=LOCAL_ORIGIN).json()
        assert saved["rules"][0]["sender"] == "Pohjola"
        blank = c.put("/api/rules/x", json={**body, "id": "x", "sender": " "}, headers=LOCAL_ORIGIN)
        assert blank.status_code == 400


def test_replay_uses_assigned_persons_for_person_templates(app, fake_archive):
    app.settings.people = PEOPLE
    add(app, fake_archive, "Mail/Tiina/20250110_Kela.pdf", "a", "kela")  # no layout at all
    app.assignments.set(["a"], person="Tiina")
    rule = Rule.model_validate(
        {
            "id": "mail",
            "when": {"text_contains": ["kela"]},
            "then": {"folder": "Mail/{person}", "name": "{doc_date:%Y%m%d}_Kela"},
        }
    )
    r = replay(
        app.engine,
        rule,
        [rule],
        app.settings.special_folders,
        layouts_for=app.repo.layouts_for,
        people=PEOPLE,
        address_zone=ZONE,
        assigned_persons=app.assignments.persons,
    )
    assert (r.matched, r.same, r.not_checked) == (1, 1, [])


def test_migration_0029_adds_the_table(engine):
    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(file_assignments)"))]
    assert cols == ["drive_id", "sender", "person", "set_by", "set_at"]
