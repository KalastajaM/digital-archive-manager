"""Phase 3 Task 3: the summarize-collection and ask-archive tasks. The provider is
always a fake; nothing reaches the network."""

import time

import pytest
import yaml
from sqlalchemy import select

from dam.ai import guard
from dam.ai.anthropic import wire_schema
from dam.ai.fake import FakeProvider
from dam.ai.tasks import TASKS
from dam.ai.tasks.ask_archive import ask_query, snippet, terms
from dam.db.tables import ai_cache, ai_calls
from dam.errors import Conflict, InvalidRequest, NotFound

BANKS = "10. Financial/Banks"
HOME = "20. Home/Insurance"
INBOX = "##. Organize"
NORTHPOWER = "Northpower Oy sähkölasku. Eräpäivä 15.11.2026. Yhteensä 84,20 €."
POLICY = "Kotivakuutus If Vahinkovakuutus. Vakuutusmaksu 312 € vuodessa."


def calls(app) -> list:
    with app.engine.connect() as conn:
        return list(conn.execute(select(ai_calls).order_by(ai_calls.c.id)).mappings())


@pytest.fixture
def tapp(app, fake_archive):
    """Bills and an insurance policy, a medical letter (excluded ``50. Medical``) that
    mentions the same words, and a work file under a case variant of ``70. Work``."""
    app.ai.provider = FakeProvider()
    fake_archive.add(f"{BANKS}/northpower.txt", NORTHPOWER.encode(), drive_id="b1")
    fake_archive.add(
        f"{BANKS}/northpower2.txt", b"Northpower Oy lasku lokakuu 79,10", drive_id="b2"
    )
    fake_archive.add(f"{HOME}/policy.txt", POLICY.encode(), drive_id="h1")
    fake_archive.add("20. Home/Sauna/notes.txt", b"sauna stove", drive_id="s1")
    fake_archive.add(
        "50. Medical/Lab/northpower.txt", b"Northpower lab results lasku verikoe", drive_id="m1"
    )
    fake_archive.add("70. work/northpower.txt", b"Northpower Oy work contract lasku", drive_id="w1")
    app.scan()
    app.index()
    return app


def collection(app, *, medical: bool = True):
    """A collection "House" with groups Bills (with a nested Paid) and Insurance."""
    c = app.collections.create("House")
    bills = app.collections.create_group(c.id, "Bills")
    paid = app.collections.create_group(c.id, "Paid", bills.id)
    ins = app.collections.create_group(c.id, "Insurance")
    app.collections.set_member_group(c.id, ["b1"], bills.id)
    app.collections.set_member_group(c.id, ["b2"], paid.id)
    app.collections.set_member_group(c.id, ["h1"], ins.id)
    if medical:
        app.collections.add_members(c.id, ["m1", "w1"])
    return app.collections.get(c.id), {"bills": bills, "paid": paid, "ins": ins}


def test_tasks_are_registered():
    assert TASKS["summarize-collection"].model_tier == "small"
    assert TASKS["ask-archive"].model_tier == "large"


# -- exclusions (the rest of test_excluded_everywhere) ------------------------------------


def test_excluded_everywhere(tapp):
    """A file under ``50. Medical`` (or a case variant of ``70. Work``) is never sent
    as a collection member nor as an ask-archive snippet."""
    c, _ = collection(tapp)
    p = tapp.ai.prepare("summarize-collection", {"collection_id": c.id})
    assert p.blocked is None
    assert "m1" not in p.files and "w1" not in p.files
    assert set(p.files) == {"b1", "b2", "h1"}
    assert "verikoe" not in p.payload_text and "contract" not in p.payload_text
    # their names are not sent either; the sheet lists them in the notes
    assert "50. Medical" not in p.payload_text and "70. work" not in p.payload_text
    assert any("northpower.txt" in n and "50. Medical" in n for n in p.notes)
    assert any("70. Work" in n for n in p.notes)
    tapp.ai.run(p.token)
    sent = tapp.ai.provider.calls[-1]["user"]
    assert "verikoe" not in sent and "contract" not in sent

    p = tapp.ai.prepare("ask-archive", {"question": "Northpower lasku"})
    assert p.blocked is None
    assert "m1" not in p.files and "w1" not in p.files
    assert set(p.files) == {"b1", "b2"}
    assert "verikoe" not in p.payload_text and "contract" not in p.payload_text
    tapp.ai.run(p.token)
    sent = tapp.ai.provider.calls[-1]["user"]
    assert "verikoe" not in sent and "contract" not in sent


def test_excluded_non_ascii_case_variant_is_caught_past_sql(tapp, fake_archive):
    """SQLite folds ASCII case only: ``ÄITI`` vs ``äiti`` is caught in Python."""
    tapp.settings.ai.exclude_folders = [*tapp.settings.ai.exclude_folders, "60. ÄITI"]
    fake_archive.add("60. äiti/kirje.txt", b"Northpower lasku aidin kirje", drive_id="a1")
    tapp.scan()
    tapp.index()
    p = tapp.ai.prepare("ask-archive", {"question": "Northpower lasku"})
    assert "a1" not in p.files and "kirje" not in p.payload_text
    c = tapp.collections.create("Mum")
    tapp.collections.add_members(c.id, ["a1", "b1"])
    p = tapp.ai.prepare("summarize-collection", {"collection_id": c.id})
    assert p.files == ["b1"] and any("60. ÄITI" in n for n in p.notes)


def test_excluded_folder_member_skips_everything_under_it(tapp, fake_archive):
    c = tapp.collections.create("Folders")
    medical = tapp.repo.by_path("50. Medical")
    tapp.collections.add_members(c.id, [medical.drive_id, "h1"])
    p = tapp.ai.prepare("summarize-collection", {"collection_id": c.id})
    assert p.files == ["h1"]
    assert "verikoe" not in p.payload_text
    assert any("northpower.txt" in n for n in p.notes)


def test_ask_skips_an_inbox_file_whose_rules_point_at_an_excluded_folder(tapp, fake_archive):
    fake_archive.add(f"{INBOX}/lab.txt", b"Laboratorio Northpower lasku", drive_id="in1")
    tapp.scan()
    tapp.index()
    (tapp.rules_dir / "50-lab.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "id": "lab",
                    "when": {"text_contains": ["laboratorio"]},
                    "then": {"folder": "50. Medical/Lab"},
                }
            ]
        ),
        encoding="utf-8",
    )
    assert tapp.reload_rules() == []
    p = tapp.ai.prepare("ask-archive", {"question": "Northpower lasku"})
    assert "in1" not in p.files and "Laboratorio" not in p.payload_text


def test_all_members_excluded_is_blocked(tapp):
    c = tapp.collections.create("Private")
    tapp.collections.add_members(c.id, ["m1"])
    p = tapp.ai.prepare("summarize-collection", {"collection_id": c.id})
    assert p.blocked == "no member of this collection can be sent"
    assert p.payload_text == "" and p.files == []
    with pytest.raises(InvalidRequest, match="can be sent"):
        tapp.ai.run(p.token)
    assert tapp.ai.provider.calls == []


# -- summarize-collection ---------------------------------------------------------------


def test_collection_payload(tapp):
    c, g = collection(tapp, medical=False)
    tapp.summaries.put("b1", "user", "Northpower's October electricity bill.")
    tapp.collections.set_group_summary(g["ins"].id, "Our home insurance.")
    p = tapp.ai.prepare("summarize-collection", {"collection_id": c.id})
    assert p.model == "claude-haiku-5-5"
    assert guard.DATA_PREAMBLE in p.system and "English" in p.system
    text = p.payload_text
    # everything taken from the archive sits inside delimited blocks
    assert "<collection>" in text and "<groups>" in text and text.count("<member>") == 3
    assert f"{g['paid'].id}: Paid (in {g['bills'].id})" in text
    assert "Our home insurance." in text
    assert "Northpower's October electricity bill." in text
    assert f"folder: {BANKS}" in text and f"group: {g['bills'].id}" in text
    assert NORTHPOWER in text
    assert p.notes == []
    # the schema lists the collection's group ids as string keys
    schema = TASKS["summarize-collection"]
    tapp.ai.run(p.token)
    sent = tapp.ai.provider.calls[-1]
    assert sent["max_tokens"] == 3000
    assert set(sent["schema"]["properties"]["per_group"]["properties"]) == {str(g[k].id) for k in g}
    assert schema.schema["properties"]["per_group"]["type"] == "object"


def test_member_text_is_cut_and_members_capped(tapp, fake_archive):
    long = ("sana " * 400).strip()
    ids = []
    for i in range(42):
        fake_archive.add(f"{BANKS}/many/f{i:02}.txt", long.encode(), drive_id=f"x{i:02}")
        ids.append(f"x{i:02}")
    tapp.scan()
    tapp.index()
    c = tapp.collections.create("Many")
    tapp.collections.add_members(c.id, ids)
    p = tapp.ai.prepare("summarize-collection", {"collection_id": c.id})
    assert len(p.files) == 40
    assert "only the first 40 of 42 members are sent" in p.notes
    body = p.payload_text.split("<member>")[1]
    start = body.split("text start:\n")[1].split("\n</member>")[0]
    assert len(start) <= 800 and start.endswith("…")


def test_collection_post_rejects_unknown_groups_and_trims(tapp):
    c, g = collection(tapp, medical=False)
    bills = str(g["bills"].id)
    tapp.ai.provider.reply = lambda **_kw: {
        "summary": "word " * 300,
        "per_group": {bills: "Two Northpower bills.", "9999": "made up", str(g["ins"].id): " "},
    }
    r = tapp.ai.run(tapp.ai.prepare("summarize-collection", {"collection_id": c.id}).token)
    assert r.data["per_group"] == {bills: "Two Northpower bills."}
    assert r.data["rejected"] == {"per_group.9999": "unknown group"}
    assert len(r.data["summary"]) <= 800 and r.data["summary"].endswith("…")
    assert [c_["outcome"] for c_ in calls(tapp)] == ["ok"]
    # running saved nothing: the user applies it through the summary endpoints
    assert tapp.collections.get(c.id).summary == ""
    assert all(grp.summary == "" for grp in tapp.collections.get(c.id).groups)


def test_collection_extra_keys_are_still_fatal(tapp):
    c, g = collection(tapp, medical=False)
    for bad in (
        {"summary": "x", "per_group": {}, "action": "delete"},
        {"summary": "x", "per_group": {str(g["bills"].id): {"nested": 1}}},
        {"summary": "x"},
    ):
        tapp.ai.provider.reply = lambda **_kw: bad  # noqa: B023
        p = tapp.ai.prepare("summarize-collection", {"collection_id": c.id, "refresh": True})
        with pytest.raises(Conflict, match="did not match"):
            tapp.ai.run(p.token)


def test_collection_cache_key(tapp, fake_archive):
    c, g = collection(tapp, medical=False)
    tapp.ai.run(tapp.ai.prepare("summarize-collection", {"collection_id": c.id}).token)
    assert tapp.ai.prepare("summarize-collection", {"collection_id": c.id}).cached is not None

    def changed(step) -> None:
        step()
        p = tapp.ai.prepare("summarize-collection", {"collection_id": c.id})
        assert p.cached is None
        tapp.ai.run(p.token)
        assert tapp.ai.prepare("summarize-collection", {"collection_id": c.id}).cached

    # a saved file summary, a group summary, the group structure, a member's content,
    # a member's name and the language each shape the prompt
    changed(lambda: tapp.summaries.put("b1", "user", "A bill."))
    changed(lambda: tapp.collections.set_group_summary(g["bills"].id, "Bills."))
    changed(lambda: tapp.collections.set_member_group(c.id, ["h1"], g["bills"].id))
    changed(lambda: tapp.collections.rename_group(g["paid"].id, "Settled"))

    def edit():
        (fake_archive.root / BANKS / "northpower.txt").write_bytes(b"Northpower Oy lasku marraskuu")
        tapp.scan()
        tapp.index()

    changed(edit)

    def rename():
        base = fake_archive.root / BANKS
        (base / "northpower2.txt").rename(base / "northpower-oct.txt")
        tapp.scan()
        tapp.index()

    changed(rename)

    def lang():
        tapp.settings.ai.language = "fi"

    changed(lang)


def test_collection_unknown_and_bad_params(tapp):
    with pytest.raises(NotFound):
        tapp.ai.prepare("summarize-collection", {"collection_id": 999})
    for bad in ({}, {"collection_id": "1"}, {"collection_id": True}):
        with pytest.raises(InvalidRequest):
            tapp.ai.prepare("summarize-collection", bad)


# -- ask-archive: retrieval ---------------------------------------------------------------


def test_query_builder_drops_stopwords_and_ors_prefixes():
    assert terms("What is the Northpower bill for, and mikä on eräpäivä?") == [
        "northpower",
        "bill",
        "eräpäivä",
    ]
    assert ask_query("Northpower bill") == '"northpower"* OR "bill"*'
    # FTS syntax in the question is only ever literal
    # (single characters are dropped: "b"* would match half the archive)
    assert ask_query('NEAR(xy) "quoted" a* -b') == '"near"* OR "xy"* OR "quoted"*'
    assert ask_query("the and of mikä on") == ""
    assert ask_query("") == ""


def test_prefix_query_catches_finnish_inflection(tapp):
    # "vakuutus"* finds the inflected "Vakuutusmaksu"; "paljonko" is a stopword
    p = tapp.ai.prepare("ask-archive", {"question": "Paljonko vakuutus maksaa?"})
    assert p.files == ["h1"]
    assert POLICY in p.payload_text


def test_nothing_matches_makes_no_call(tapp):
    for q in ("zebra quantum", "what is the"):
        p = tapp.ai.prepare("ask-archive", {"question": q})
        assert p.blocked == "Nothing in the archive matches"
        assert p.files == [] and p.payload_text == ""
        with pytest.raises(InvalidRequest, match="Nothing in the archive matches"):
            tapp.ai.run(p.token)
    # only an excluded file matches: the same answer
    p = tapp.ai.prepare("ask-archive", {"question": "verikoe"})
    assert p.blocked == "Nothing in the archive matches"
    assert tapp.ai.provider.calls == []
    assert calls(tapp) == []


def test_question_is_required_and_bounded(tapp):
    too_long = {"question": "x" * 1001}
    for bad in ({}, {"question": ""}, {"question": "   "}, {"question": 3}, too_long):
        with pytest.raises(InvalidRequest):
            tapp.ai.prepare("ask-archive", bad)


def test_top_eight_by_bm25_with_snippets_around_the_match(tapp, fake_archive):
    filler = "täyte " * 600  # 3 600 characters before the match
    for i in range(10):
        body = filler + "Voltex kaukolämpö " + ("Voltex " * i) + "loppu " * 300
        fake_archive.add(f"{BANKS}/voltex{i}.txt", body.encode(), drive_id=f"f{i}")
    tapp.scan()
    tapp.index()
    p = tapp.ai.prepare("ask-archive", {"question": "voltex"})
    assert len(p.files) == 8
    # bm25: the files with the most "Voltex" first
    assert p.files[:3] == ["f9", "f8", "f7"]
    snippets = p.payload_text.split("<source>")[1:]
    assert len(snippets) == 8
    for s in snippets:
        body = s.split("\n</source>")[0].split("\n\n", 1)[1]
        assert len(body) <= 1500
        assert "Voltex" in body and body.startswith("…")


def test_ask_payload_model_and_language(tapp):
    p = tapp.ai.prepare("ask-archive", {"question": "Milloin Northpower lasku erääntyy?"})
    assert p.model == "claude-sonnet-5-5"
    assert guard.DATA_PREAMBLE in p.system
    assert "same language as the question" in p.system
    assert guard.delimited("question", "Milloin Northpower lasku erääntyy?") in p.payload_text
    assert "drive_id: b1" in p.payload_text and f"folder: {BANKS}" in p.payload_text
    tapp.ai.run(p.token)
    assert tapp.ai.provider.calls[-1]["max_tokens"] == 3000
    assert tapp.ai.provider.calls[-1]["model"] == "claude-sonnet-5-5"


# -- ask-archive: the answer --------------------------------------------------------------


def test_citations_are_limited_to_sent_snippets(tapp):
    tapp.ai.provider.reply = lambda **_kw: {
        "answer": "The Northpower bill is due on 15.11.2026.",
        "citations": [
            {"drive_id": "b1", "quote": "Eräpäivä 15.11.2026"},
            {"drive_id": "m1", "quote": "Northpower lab results"},  # excluded: never sent
            {"drive_id": "zz", "quote": "made up"},
            {"drive_id": "h1", "quote": "not retrieved for this question"},
            {"drive_id": "b1", "quote": "Eräpäivä 15.11.2026"},  # a repeat
        ],
    }
    p = tapp.ai.prepare("ask-archive", {"question": "Northpower eräpäivä"})
    assert "h1" not in p.files
    r = tapp.ai.run(p.token)
    assert r.data["answer"] == "The Northpower bill is due on 15.11.2026."
    assert r.data["citations"] == [
        {"drive_id": "b1", "quote": "Eräpäivä 15.11.2026", "name": "northpower.txt"}
    ]
    assert r.data["rejected"] == {"citations": "3 citations of sources that were not sent dropped"}


def test_ask_soft_limits_and_fatal_shapes(tapp):
    tapp.ai.provider.reply = lambda **_kw: {
        "answer": "word " * 1000,
        "citations": [{"drive_id": "b1", "quote": "q" * 400}] * 12,
    }
    r = tapp.ai.run(tapp.ai.prepare("ask-archive", {"question": "Northpower"}).token)
    assert len(r.data["answer"]) <= 2000 and r.data["answer"].endswith("…")
    (cite,) = r.data["citations"]
    assert len(cite["quote"]) <= 300
    for bad in (
        {"answer": "x", "citations": [], "open": "file"},
        {"answer": "x", "citations": [{"drive_id": "b1"}]},
        {"answer": "x", "citations": [{"drive_id": "b1", "quote": "q", "url": "http://x"}]},
    ):
        tapp.ai.provider.reply = lambda **_kw: bad  # noqa: B023
        p = tapp.ai.prepare("ask-archive", {"question": "Northpower", "refresh": True})
        with pytest.raises(Conflict, match="did not match"):
            tapp.ai.run(p.token)


def test_ask_cache_key(tapp, fake_archive):
    p = tapp.ai.prepare("ask-archive", {"question": "Northpower lasku"})
    tapp.ai.run(p.token)
    assert tapp.ai.prepare("ask-archive", {"question": "Northpower lasku"}).cached is not None
    # another question
    assert tapp.ai.prepare("ask-archive", {"question": "Northpower lasku?"}).cached is None
    # another language setting
    tapp.settings.ai.language = "fi"
    assert tapp.ai.prepare("ask-archive", {"question": "Northpower lasku"}).cached is None
    tapp.settings.ai.language = "en"
    assert tapp.ai.prepare("ask-archive", {"question": "Northpower lasku"}).cached is not None
    # a snippet's file changed
    (fake_archive.root / BANKS / "northpower2.txt").write_bytes(
        b"Northpower Oy lasku marraskuu 81,00"
    )
    tapp.scan()
    tapp.index()
    assert tapp.ai.prepare("ask-archive", {"question": "Northpower lasku"}).cached is None


def test_fake_default_reply_fits_the_schemas(tapp):
    c, _ = collection(tapp)
    r = tapp.ai.run(tapp.ai.prepare("summarize-collection", {"collection_id": c.id}).token)
    assert r.data == {"summary": "fake", "per_group": {}, "rejected": {}}
    r = tapp.ai.run(tapp.ai.prepare("ask-archive", {"question": "Northpower"}).token)
    assert r.data == {"answer": "fake", "citations": [], "rejected": {}}


# -- the wire and the validator -------------------------------------------------------------


def test_typed_map_schema():
    schema = {
        "type": "object",
        "properties": {"1": {"type": "string"}},
        "additionalProperties": {"type": "string"},
    }
    assert guard.validate_output({"1": "a", "2": "b"}, schema) is None
    assert guard.validate_output({"2": 3}, schema) is not None
    assert guard.validate_output({"2": {"x": 1}}, schema) is not None
    # structured output wants closed objects: only the listed keys are offered
    wired = wire_schema(schema)
    assert wired["additionalProperties"] is False
    assert wired["properties"] == {"1": {"type": "string"}}


# -- review fixes ----------------------------------------------------------------------------


def test_snippet_is_linear_on_a_huge_text_with_many_hits():
    text = (
        "northpower lasku " * 36_667
    )  # about 440 000 characters, about 37 000 "northpower" starts
    assert len(text) > 440_000
    started = time.perf_counter()
    piece = snippet(text, ["northpower"])
    assert time.perf_counter() - started < 0.5
    assert len(piece) <= 1500 and "northpower" in piece


def test_snippet_only_scans_the_start_of_the_text():
    text = "täyte " * 40_000 + "Voltex"  # the match lies past the 200 000 scanned
    piece = snippet(text, ["voltex"])
    assert piece.startswith("täyte") and "Voltex" not in piece


def test_terms_lower_case_like_the_tokenizer():
    # unicode61 folds with lower(): casefold() would make "strasse", which never matches
    assert terms("Straße ÄITI") == ["straße", "äiti"]
    assert ask_query("Straße") == '"straße"*'


def test_hostile_question_is_only_ever_literal(tapp):
    hostile = (
        'Northpower" OR lasku) NEAR(x y, 2) {name path}: text:* ^foo -bar AND NOT "" '
        "'; DROP TABLE files; -- * ( ) : ^ \" \x00 lasku*"
    )
    p = tapp.ai.prepare("ask-archive", {"question": hostile})
    assert p.blocked is None
    assert set(p.files) == {"b1", "b2"}
    assert guard.delimited("question", hostile.strip()) in p.payload_text
    assert tapp.repo.get("b1") is not None  # the files table is still there


def test_text_hits_rank_ahead_of_name_or_path_hits(tapp, fake_archive):
    # a name full of the term (a strong bm25 on the name) but no match in the text
    fake_archive.add(
        f"{BANKS}/voltex voltex voltex.txt", b"electricity contract terms", drive_id="n1"
    )
    # one match deep inside a long text (a weak bm25)
    fake_archive.add(
        f"{BANKS}/letter.txt",
        ("muuta " * 300 + "Voltex " + "muuta " * 300).encode(),
        drive_id="t1",
    )
    tapp.scan()
    tapp.index()
    p = tapp.ai.prepare("ask-archive", {"question": "voltex"})
    assert p.files == ["t1", "n1"]


def test_empty_additional_properties_stays_closed():
    for closed in ({}, {"description": "anything"}):
        schema = {"type": "object", "properties": {}, "additionalProperties": closed}
        assert guard.validate_output({"action": "delete"}, schema) is not None
        assert guard.validate_output({}, schema) is None
    typed = {"type": "object", "properties": {}, "additionalProperties": {"type": "string"}}
    assert guard.validate_output({"1": "a"}, typed) is None


def test_demo_reply_fills_collection_groups_and_cites_a_sent_source(tapp):
    """``DAM_AI_FAKE=1`` demos: a collection answer with a line for every group and an
    ask answer citing a snippet that was sent; both pass the tasks' checks."""
    from dam.ai.fake import demo_reply

    tapp.ai.provider = FakeProvider(demo_reply, demo=True)
    coll, g = collection(tapp)
    r = tapp.ai.run(tapp.ai.prepare("summarize-collection", {"collection_id": coll.id}).token)
    assert r.data["rejected"] == {}
    assert "House" in r.data["summary"] and "DAM_AI_FAKE=1" in r.data["summary"]
    assert set(r.data["per_group"]) == {str(g["bills"].id), str(g["paid"].id), str(g["ins"].id)}
    assert "Bills" in r.data["per_group"][str(g["bills"].id)]

    p = tapp.ai.prepare("ask-archive", {"question": "Northpower lasku"})
    r = tapp.ai.run(p.token)
    assert r.data["rejected"] == {}
    assert "[1]" in r.data["answer"] and "DAM_AI_FAKE=1" in r.data["answer"]
    assert r.data["citations"], r.data
    first = r.data["citations"][0]
    assert first["drive_id"] in p.files
    assert first["quote"] and first["quote"][:20] in p.payload_text


def test_collection_and_ask_demo_answers_are_never_cached_or_priced(tapp):
    """``DAM_AI_FAKE=1``: like suggest-filing, the collection and ask demo answers cost
    0 (whatever the usage says), are logged as "fake" and are never cached: preparing
    again shows no result "from earlier"."""
    from dam.ai.fake import demo_reply

    tapp.ai.provider = FakeProvider(demo_reply, demo=True, input_tokens=9000, output_tokens=3000)
    coll, _ = collection(tapp)
    for task, params in (
        ("summarize-collection", {"collection_id": coll.id}),
        ("ask-archive", {"question": "Northpower lasku"}),
    ):
        p = tapp.ai.prepare(task, params)
        assert p.cached is None and p.estimate_eur > 0
        r = tapp.ai.run(p.token)
        assert (r.cost_eur, r.cached) == (0.0, False), task
        again = tapp.ai.prepare(task, params)
        assert again.cached is None, task
    with tapp.engine.connect() as conn:
        assert conn.execute(select(ai_cache)).all() == []
    logged = calls(tapp)
    assert [(c["task"], c["outcome"], c["cost_eur"]) for c in logged] == [
        ("summarize-collection", "fake", 0.0),
        ("ask-archive", "fake", 0.0),
    ]
    assert tapp.ai.status()["month_spend_eur"] == 0.0


def test_ask_citations_carry_marks_over_the_api(tapp):
    """stars Task 4: each cited file's ★ / ! marks, as they are now (one query)."""
    from fastapi.testclient import TestClient

    from dam.ai.fake import demo_reply
    from dam.api import create_api
    from test_marks import counted, mark_queries

    tapp.ai.provider = FakeProvider(demo_reply, demo=True)
    p = tapp.ai.prepare("ask-archive", {"question": "Northpower lasku"})
    tapp.marks.star(p.files)
    base = "http://127.0.0.1:8765"
    with TestClient(create_api(tapp), base_url=base) as client:
        with counted(tapp.engine) as seen:
            r = client.post(
                "/api/ai/ask-archive/run", json={"token": p.token}, headers={"Origin": base}
            )
    assert r.status_code == 200, r.text
    cites = r.json()["data"]["citations"]
    assert cites and all(c["marks"] == ["starred"] for c in cites)
    assert len(mark_queries(seen)) == 1
