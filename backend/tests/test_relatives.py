"""Relatives: the scoring service, the Not related marks, the API, the one-step tag of
several files and the links to one file in several folders (one batch, one Undo)."""

import os
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, text, update

from dam.api import create_api
from dam.config import Person
from dam.db.tables import file_tags, files, item_files, items, related_dismissed, tags
from dam.errors import NotFound
from dam.services import relatives as rel
from dam.services.relatives import RelativesService

BANKS = "10. Financial/Banks"
HOME = "20. Home"
TAXES = "13. Taxes"
INBOX = "##. Organize"
QUAR = "##. To Delete"
BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}


@pytest.fixture
def archive(app, fake_archive):
    """Me in Taxes; sib next to it; others elsewhere."""
    fake_archive.add(f"{TAXES}/me.pdf", b"me", drive_id="me")
    fake_archive.add(f"{TAXES}/sib.pdf", b"sib", drive_id="sib")
    fake_archive.add(f"{HOME}/far.pdf", b"far", drive_id="far")
    fake_archive.add(f"{BANKS}/bank.pdf", b"bank", drive_id="bank")
    app.scan()
    return fake_archive


def ids(result):
    return [r.drive_id for r in result.relatives]


def by_id(result):
    return {r.drive_id: r for r in result.relatives}


def kinds(r):
    return {(link.kind, link.value) for link in r.links}


def add_item(app, drive_ids, fields):
    with app.engine.begin() as conn:
        item_id = conn.execute(
            insert(items).values(tray_id="bills", title="t", fields=fields, created=1.0)
        ).inserted_primary_key[0]
        for d in drive_ids:
            conn.execute(insert(item_files).values(item_id=item_id, drive_id=d))
    return item_id


def set_date(app, drive_id, day):
    with app.engine.begin() as conn:
        conn.execute(update(files).where(files.c.drive_id == drive_id).values(doc_date=day))


# --- each kind of link ----------------------------------------------------------------


def test_nothing_in_common_is_no_relative(app, archive):
    got = app.relatives.of("far")
    assert got.relatives == [] and got.common == [] and got.total == 0 and got.hidden == 0


def test_same_folder(app, archive):
    got = app.relatives.of("me")
    assert ids(got) == ["sib"]
    r = got.relatives[0]
    assert kinds(r) == {("folder", TAXES)}
    assert r.score == 2 and r.folder == TAXES and r.name == "sib.pdf" and not r.in_inbox


def test_shared_tag_counts_each_tag(app, archive):
    app.tags.add("me", ["Tax", "2025", "Kela"])
    app.tags.add("far", ["Tax", "2025"])
    app.tags.add("bank", ["kela"])  # another tag: no link
    r = by_id(app.relatives.of("me"))["far"]
    assert kinds(r) == {("tag", "Tax"), ("tag", "2025")}
    assert r.score == 4
    assert "bank" not in by_id(app.relatives.of("me"))


def test_same_sender_and_person(app, archive):
    app.assignments.set(["me", "far", "bank"], sender="Verohallinto")
    app.assignments.set(["me"], person=None)
    got = by_id(app.relatives.of("me"))
    assert kinds(got["far"]) == {("sender", "Verohallinto")}
    assert got["far"].score == 3
    # the sender is matched up to case and accents, never guessed from a name
    app.assignments.set(["bank"], sender="VEROHALLINTO")
    assert "bank" in by_id(app.relatives.of("me"))


def test_same_person(app, archive):
    app.settings.people = [Person(name="Tiina", match=["Tiina Visser"])]
    app.assignments.set(["me", "far"], person="Tiina")
    r = by_id(app.relatives.of("me"))["far"]
    assert kinds(r) == {("person", "Tiina")} and r.score == 1


def test_same_collection_but_not_the_built_in_ones(app, archive):
    c = app.collections.create("Tax return")
    app.collections.add_members(c.id, ["me", "far"])
    with app.engine.begin() as conn:  # the built-in collections are marks, not groups of files
        star = conn.execute(text("SELECT id FROM collections WHERE kind = 'starred'")).scalar_one()
    app.collections.add_members(star, ["me", "bank"])
    got = by_id(app.relatives.of("me"))
    assert kinds(got["far"]) == {("collection", "Tax return")} and got["far"].score == 3
    assert "bank" not in got


def test_same_reference_and_iban_from_tray_items(app, archive):
    add_item(app, ["me"], {"reference": "1 2345 6", "iban": "FI21 1234 5600 0007 85"})
    add_item(app, ["far"], {"reference": "123456", "iban": "FI2112345600000785"})
    add_item(app, ["bank"], {"reference": "999", "iban": "FI2112345600000785"})
    got = by_id(app.relatives.of("me"))
    assert kinds(got["far"]) == {("reference", "1 2345 6"), ("iban", "FI2112345600000785")}
    assert got["far"].score == 7
    assert kinds(got["bank"]) == {("iban", "FI2112345600000785")} and got["bank"].score == 2


# --- booster, damping, dismissed ------------------------------------------------------


def test_same_month_only_adds_to_a_relative(app, archive):
    set_date(app, "me", date(2025, 9, 30))
    set_date(app, "far", date(2025, 9, 1))
    set_date(app, "sib", date(2025, 9, 15))
    set_date(app, "bank", date(2024, 9, 15))
    got = by_id(app.relatives.of("me"))
    assert "far" not in got  # the same month alone is not a link
    assert got["sib"].same_month and got["sib"].score == 3  # folder 2 + month 1
    app.tags.add("me", ["T"])
    app.tags.add("bank", ["T"])
    assert not by_id(app.relatives.of("me"))["bank"].same_month  # another year


def test_both_dates_are_needed_for_the_booster(app, archive):
    set_date(app, "me", date(2025, 9, 30))
    assert not by_id(app.relatives.of("me"))["sib"].same_month


def test_common_values_count_half_and_then_nothing(app, archive):
    app.tags.add("me", ["Everything"])
    app.tags.add("far", ["Everything"])
    app.tags.add("bank", ["Everything"])
    svc = RelativesService(app.engine, app.repo, app.paths, common_limit=2)
    # 3 files have it: more than 2 -> half weight
    assert by_id(svc.of("me"))["far"].score == 1
    svc = RelativesService(app.engine, app.repo, app.paths, common_limit=0)
    # more than 5 x 0 files -> no weight, so no link: far is no relative at all
    assert "far" not in by_id(svc.of("me"))
    assert rel.damping(200) == 1 and rel.damping(201) == 0.5 and rel.damping(1001) == 0


def test_the_default_limit_is_a_constant(app):
    assert rel.COMMON_LIMIT == 200 and app.relatives.common_limit == 200


def test_not_related_wins_whatever_is_shared(app, archive):
    app.tags.add("me", ["T"])
    app.tags.add("sib", ["T"])
    assert "sib" in ids(app.relatives.of("me"))
    app.relatives.dismiss("sib", "me")
    got = app.relatives.of("me")
    assert "sib" not in ids(got) and got.hidden == 1
    assert "me" not in ids(app.relatives.of("sib"))  # both ways
    assert [d.drive_id for d in app.relatives.dismissed("me")] == ["sib"]
    app.relatives.dismiss("me", "sib")  # twice is fine
    with app.engine.connect() as conn:
        assert conn.execute(select(related_dismissed)).all()[0][:2] == ("me", "sib")  # sorted
        assert len(conn.execute(select(related_dismissed)).all()) == 1
    app.relatives.restore("me", "sib")
    assert "sib" in ids(app.relatives.of("me")) and app.relatives.of("me").hidden == 0


def test_dismiss_refuses_itself_and_unknown_files(app, archive):
    with pytest.raises(Exception, match="itself"):
        app.relatives.dismiss("me", "me")
    with pytest.raises(NotFound):
        app.relatives.dismiss("me", "nope")


# --- what is listed -------------------------------------------------------------------


def test_missing_parked_folders_and_to_delete_are_left_out(app, archive):
    archive.add(f"{TAXES}/gone.pdf", b"g", drive_id="gone")
    archive.add(f"{TAXES}/parked.pdf", b"p", drive_id="parked")
    (archive.root / TAXES / "sub").mkdir()
    archive.add(f"{QUAR}/{TAXES}/deleted.pdf", b"d", drive_id="deleted")
    app.scan()
    app.tags.add("me", ["T"])
    app.tags.add("deleted", ["T"])
    with app.engine.begin() as conn:
        conn.execute(update(files).where(files.c.drive_id == "gone").values(missing=True))
        conn.execute(update(files).where(files.c.drive_id == "parked").values(parked_at=1.0))
    assert ids(app.relatives.of("me")) == ["sib"]  # not the folder "sub", not "deleted"


def test_a_link_stands_for_its_target_and_is_counted_once(app, archive):
    archive.link(f"{TAXES}/link-to-far.pdf", f"{HOME}/far.pdf")
    app.scan()
    app.tags.add("me", ["T"])
    app.tags.add("far", ["T"])
    got = app.relatives.of("me")
    assert ids(got).count("far") == 1 and "link-to-far.pdf" not in [r.name for r in got.relatives]
    # asking about the link is asking about its target
    link = app.repo.by_path(f"{TAXES}/link-to-far.pdf")
    assert link.is_link
    again = app.relatives.of(link.drive_id)
    assert again.drive_id == "far" and "me" in ids(again)


def test_a_link_to_nothing_has_no_relatives(app, archive):
    archive.link(f"{TAXES}/dangling.pdf", f"{HOME}/not-there.pdf")
    app.scan()
    link = app.repo.by_path(f"{TAXES}/dangling.pdf")
    assert app.relatives.of(link.drive_id).relatives == []


def test_unknown_file_is_not_found(app, archive):
    with pytest.raises(NotFound):
        app.relatives.of("nope")


def test_ranking_is_by_score_then_name(app, archive):
    archive.add(f"{TAXES}/aaa.pdf", b"a", drive_id="aaa")
    app.scan()
    app.tags.add("me", ["T", "U"])
    app.tags.add("far", ["T", "U"])  # 4
    app.tags.add("bank", ["T"])  # 2
    app.tags.add("sib", ["T"])  # folder 2 + tag 2 = 4
    got = app.relatives.of("me")
    assert [(r.name, r.score) for r in got.relatives] == [
        ("far.pdf", 4),
        ("sib.pdf", 4),
        ("aaa.pdf", 2),
        ("bank.pdf", 2),
    ]
    assert ids(app.relatives.of("me")) == ids(got)  # stable
    assert ids(app.relatives.of("me", limit=2)) == ["far", "sib"]
    assert app.relatives.of("me", limit=2).total == 4


def test_common_values_count_the_relatives_that_share_them(app, archive):
    app.tags.add("me", ["T"])
    app.tags.add("far", ["T"])
    app.tags.add("sib", ["T"])
    got = app.relatives.of("me")
    counts = {(c.kind, c.value): c.count for c in got.common}
    assert counts == {("tag", "T"): 2, ("folder", TAXES): 1}
    assert got.common[0].count == 2


def test_inbox_relatives_are_flagged(app, archive):
    archive.add(f"{INBOX}/scan.pdf", b"s", drive_id="scan")
    app.scan()
    app.assignments.set(["me", "scan"], sender="Verohallinto")
    r = by_id(app.relatives.of("me"))["scan"]
    assert r.in_inbox and r.folder == INBOX


def test_sharing_the_inbox_or_the_root_is_no_folder_link(app, archive):
    archive.add(f"{INBOX}/a.pdf", b"a", drive_id="a")
    archive.add(f"{INBOX}/b.pdf", b"b", drive_id="b")
    archive.add("top1.pdf", b"t1", drive_id="top1")
    archive.add("top2.pdf", b"t2", drive_id="top2")
    app.scan()
    assert ids(app.relatives.of("a")) == []
    assert ids(app.relatives.of("top1")) == []


# --- the API --------------------------------------------------------------------------


@pytest.fixture
def client(app):
    with TestClient(create_api(app, None), base_url=BASE) as c:
        yield c


def post(client, url, body):
    return client.post(url, json=body, headers=LOCAL_ORIGIN)


def test_api_shape(client, app, archive):
    app.tags.add("me", ["T"])
    app.tags.add("sib", ["T"])
    set_date(app, "me", date(2025, 9, 1))
    set_date(app, "sib", date(2025, 9, 2))
    body = client.get("/api/files/me/relatives").json()
    assert set(body) == {"drive_id", "relatives", "common", "total", "hidden"}
    row = body["relatives"][0]
    assert set(row) == {
        "drive_id", "path", "name", "ext", "folder", "score", "links", "same_month", "in_inbox",
    }  # fmt: skip
    assert row["drive_id"] == "sib" and row["same_month"] is True and row["score"] == 5
    assert {(x["kind"], x["value"], x["weight"]) for x in row["links"]} == {
        ("tag", "T", 2.0),
        ("folder", TAXES, 2.0),
    }
    assert client.get("/api/files/me/relatives?limit=1").json()["total"] == 1
    assert client.get("/api/files/me/relatives?limit=0").status_code == 422
    assert client.get("/api/files/me/relatives?limit=201").status_code == 422


def test_api_unknown_file_is_404(client, archive):
    assert client.get("/api/files/nope/relatives").status_code == 404
    assert post(client, "/api/files/nope/relatives/dismiss", {"drive_id": "me"}).status_code == 404
    assert post(client, "/api/files/me/relatives/dismiss", {"drive_id": "nope"}).status_code == 404


def test_api_dismiss_and_restore_round_trip(client, app, archive):
    app.tags.add("me", ["T"])
    app.tags.add("far", ["T"])
    marked = post(client, "/api/files/me/relatives/dismiss", {"drive_id": "far"}).json()
    assert [d["drive_id"] for d in marked["dismissed"]] == ["far"]
    body = client.get("/api/files/me/relatives").json()
    assert "far" not in [r["drive_id"] for r in body["relatives"]] and body["hidden"] == 1
    assert (
        client.get("/api/files/me/relatives/dismissed").json()["dismissed"][0]["name"] == "far.pdf"
    )
    assert post(client, "/api/files/far/relatives/restore", {"drive_id": "me"}).json() == {
        "dismissed": []
    }
    assert "far" in [
        r["drive_id"] for r in client.get("/api/files/me/relatives").json()["relatives"]
    ]


def test_api_rejects_unknown_fields(client, archive):
    assert (
        post(client, "/api/files/me/relatives/dismiss", {"drive_id": "far", "x": 1}).status_code
        == 422
    )


# --- tagging several files as one step ------------------------------------------------


def tag_names(app, drive_id):
    return app.tags.for_file(drive_id)


def test_tag_apply_is_one_undo_step(client, app, archive):
    app.tags.add("sib", ["Tax"])
    r = post(client, "/api/tags/apply", {"drive_ids": ["me", "sib", "far"], "tag": "tax"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["message"] == "Tagged 3 files 'tax'"
    # the tag as it is spelled already; files that had it are not part of the undo
    assert tag_names(app, "me") == ["Tax"] and tag_names(app, "far") == ["Tax"]
    assert body["undo"]["detach"] == [{"name": "Tax", "drive_ids": ["me", "far"]}]
    assert body["undo"]["drop"] == []
    assert post(client, "/api/tags/undo", body["undo"]).status_code == 200
    assert tag_names(app, "me") == [] and tag_names(app, "far") == []
    assert tag_names(app, "sib") == ["Tax"]  # it had it before


def test_tag_apply_a_new_tag_is_dropped_by_undo(client, app, archive):
    body = post(
        client, "/api/tags/apply", {"drive_ids": ["me", "far"], "tag": "  New  tag "}
    ).json()
    assert tag_names(app, "me") == ["New tag"] and body["undo"]["drop"] == ["New tag"]
    post(client, "/api/tags/undo", body["undo"])
    with app.engine.connect() as conn:
        assert conn.execute(select(tags)).all() == []
        assert conn.execute(select(file_tags)).all() == []


def test_tag_apply_refuses_unknown_blank_and_to_delete(client, app, archive):
    archive.add(f"{QUAR}/old.pdf", b"o", drive_id="old")
    app.scan()
    assert (
        post(client, "/api/tags/apply", {"drive_ids": ["me", "nope"], "tag": "x"}).status_code
        == 404
    )
    assert post(client, "/api/tags/apply", {"drive_ids": ["me"], "tag": "  "}).status_code == 422
    assert post(client, "/api/tags/apply", {"drive_ids": [], "tag": "x"}).status_code == 422
    assert (
        post(client, "/api/tags/apply", {"drive_ids": ["me", "old"], "tag": "x"}).status_code == 400
    )
    assert tag_names(app, "me") == []


# --- a link to one file in several folders: one batch -------------------------------


def test_link_there_makes_one_batch_and_undoes_as_one_step(app, archive):
    preview = app.browse.link_there_preview("me", [HOME, BANKS])
    assert [(o.src, o.dst) for o in preview] == [
        (f"{TAXES}/me.pdf", f"{HOME}/me.pdf"),
        (f"{TAXES}/me.pdf", f"{BANKS}/me.pdf"),
    ]
    assert not os.path.lexists(archive.root / HOME / "me.pdf")  # a preview changes nothing
    result = app.browse.link_there("me", [HOME, BANKS])
    assert result.failed is None and result.error is None and len(result.done) == 2
    for folder in (HOME, BANKS):
        link = archive.root / folder / "me.pdf"
        assert link.is_symlink() and link.read_bytes() == b"me"
        assert app.repo.by_path(f"{folder}/me.pdf").is_link  # indexed right away
    assert (archive.root / TAXES / "me.pdf").read_bytes() == b"me"  # the file stays
    with app.engine.connect() as conn:
        from dam.db.tables import operations

        rows = (
            conn.execute(select(operations).where(operations.c.batch_id == result.batch_id))
            .mappings()
            .all()
        )
    assert len(rows) == 2 and {r["label"] for r in rows} == {"Linked me.pdf in 2 folders"}
    assert app.activity.get(result.batch_id).undoable
    outcome = app.activity.undo(result.batch_id)
    assert outcome.batch.failed is None and outcome.batch.error is None
    assert not os.path.lexists(archive.root / HOME / "me.pdf")
    assert not os.path.lexists(archive.root / BANKS / "me.pdf")
    assert (archive.root / TAXES / "me.pdf").read_bytes() == b"me"
    assert app.activity.get(result.batch_id).undone


def test_link_there_skips_the_files_own_folder_and_repeated_folders(app, archive):
    result = app.browse.link_there("me", [TAXES, HOME, HOME + "/", HOME.upper()])
    assert [o.dst for o in result.done] == [f"{HOME}/me.pdf"]
    assert result.unchanged == ["me"]
    nothing = app.browse.link_there("me", [TAXES])
    assert nothing.done == []


def test_link_there_refuses_what_a_single_link_refuses(app, archive):
    from dam.errors import InvalidRequest

    with pytest.raises(InvalidRequest, match="No folders"):
        app.browse.link_there("me", [])
    with pytest.raises(InvalidRequest):
        app.browse.link_there("me", [HOME, "##. To Delete"])  # one bad folder: nothing is made
    assert not os.path.lexists(archive.root / HOME / "me.pdf")
    with pytest.raises(NotFound):
        app.browse.link_there("nope", [HOME])


def test_link_there_api(client, app, archive):
    pre = post(
        client, "/api/browse/link-there/preview", {"drive_id": "me", "folders": [HOME, BANKS]}
    )
    assert pre.status_code == 200 and len(pre.json()) == 2
    done = post(client, "/api/browse/link-there", {"drive_id": "me", "folders": [HOME, BANKS]})
    assert done.status_code == 200 and len(done.json()["done"]) == 2
    undo = post(client, f"/api/activity/{done.json()['batch_id']}/undo", {})
    assert undo.status_code == 200, undo.text
    assert not os.path.lexists(archive.root / HOME / "me.pdf")


# --- the migration --------------------------------------------------------------------


def test_migration_0041_creates_the_table_on_an_older_database(tmp_path, new_engine):
    from alembic import command
    from alembic.config import Config

    from dam.db.engine import MIGRATIONS_DIR, migrate, write_tx

    engine = new_engine(tmp_path / "dam.sqlite")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with write_tx(engine) as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0040")
    with engine.connect() as conn:
        assert "related_dismissed" not in {
            r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
    assert migrate(engine) == []
    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(related_dismissed)"))]
        pk = [r[1] for r in conn.execute(text("PRAGMA table_info(related_dismissed)")) if r[5]]
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0050"
    assert cols == ["drive_a", "drive_b", "created"] and pk == ["drive_a", "drive_b"]


def _folder_id(app, path):
    with app.engine.connect() as conn:
        return conn.execute(
            select(files.c.drive_id).where(files.c.path == path, files.c.is_dir.is_(True))
        ).scalar_one()


def test_same_collection_through_a_member_folder(app, archive):
    """A collection can hold a folder: every file inside it (at any depth) is a member, as
    the file panel's collection chips say, so it is a collection link both ways."""
    archive.add(f"{HOME}/Sauna/deep/plan.pdf", b"plan", drive_id="plan")
    app.scan()
    c = app.collections.create("Sauna build")
    app.collections.add_members(c.id, [_folder_id(app, HOME), "bank"])
    # "far" and "plan" are in the collection through 20. Home; "bank" directly
    got = by_id(app.relatives.of("bank"))
    assert kinds(got["far"]) == {("collection", "Sauna build")}
    assert kinds(got["plan"]) == {("collection", "Sauna build")}
    got = by_id(app.relatives.of("plan"))
    assert kinds(got["bank"]) == {("collection", "Sauna build")}
    assert ("collection", "Sauna build") in kinds(got["far"])
    assert "me" not in got  # outside the member folder


def _identifiers(app, found: dict[str, list[tuple[str, str]]]) -> None:
    from dam import countries
    from dam.extract.base import ExtractedText

    for drive_id, values in found.items():
        app.repo.save_content(drive_id, f"sha-{drive_id}", ExtractedText("x", "t"), "indexed")
        app.repo.save_identifiers(drive_id, f"sha-{drive_id}", countries.signature(), values)


def test_the_same_business_id(app, archive):
    _identifiers(
        app,
        {
            "me": [("fi.ytunnus", "0112038-9"), ("core.domain", "kela.fi")],
            "far": [("fi.ytunnus", "0112038-9")],
            "bank": [("core.domain", "kela.fi")],
        },
    )
    got = by_id(app.relatives.of("me"))
    assert kinds(got["far"]) == {("business_id", "0112038-9")}
    assert got["far"].score == 3
    assert "bank" not in got  # a domain alone links nothing


def test_no_business_id_link_when_its_country_is_off(app, archive):
    from dam import packs

    _identifiers(app, {"me": [("fi.ytunnus", "0112038-9")], "far": [("fi.ytunnus", "0112038-9")]})
    packs.activate(packs.build([], ["en"]))
    assert "far" not in by_id(app.relatives.of("me"))


def test_your_own_business_id_links_nothing(app, archive):
    from dam import packs

    _identifiers(app, {"me": [("fi.ytunnus", "0112038-9")], "far": [("fi.ytunnus", "0112038-9")]})
    packs.activate(packs.build(["fi"], ["en"], own_ids=["0112038-9"]))
    assert "far" not in by_id(app.relatives.of("me"))
