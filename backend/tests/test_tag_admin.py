"""Tags: search by tag, the Tags screen's list and changes (each undoable), pins, groups and
the sidebar's pinned and recent tags. Fake archives only."""

import time

import pytest
from sqlalchemy import text

from dam.extract.base import ExtractedText
from test_api import BANKS, LOCAL_ORIGIN, make_client


@pytest.fixture
def client(app, fake_archive):
    for i in (1, 2, 3, 4):
        fake_archive.add(f"{BANKS}/f{i}.pdf", drive_id=f"id-{i}", content=b"%PDF kela letter")
    app.scan()
    app.tags.add("id-1", ["medical", "Kela"])
    app.tags.add("id-2", ["medical"])
    app.tags.add("id-3", ["tax", "Kela"])
    with make_client(app) as c:
        yield c


def post(client, url, body=None):
    r = client.post(url, json=body or {}, headers=LOCAL_ORIGIN)
    return r


def names(client, **params):
    r = client.get("/api/tags/all", params=params)
    assert r.status_code == 200, r.text
    return {t["name"]: t for t in r.json()["tags"]}


def search(client, **params):
    r = client.get("/api/search", params=params)
    assert r.status_code == 200, r.text
    return sorted(h["drive_id"] for h in r.json())


# -- search by tag -------------------------------------------------------------


def test_search_by_one_tag(client):
    assert search(client, tag="medical") == ["id-1", "id-2"]


def test_several_tags_need_all(client):
    r = client.get("/api/search", params=[("tag", "medical"), ("tag", "Kela")])
    assert [h["drive_id"] for h in r.json()] == ["id-1"]


def test_any_needs_at_least_one_tag(client):
    two = [("tag", "medical"), ("tag", "tax")]
    r = client.get("/api/search", params=[*two, ("tag_mode", "any")])
    assert sorted(h["drive_id"] for h in r.json()) == ["id-1", "id-2", "id-3"]
    r = client.get("/api/search", params=two)  # the default is all
    assert r.json() == []
    r = client.get("/api/search", params=[*two, ("tag_mode", "all")])
    assert r.json() == []


def test_any_and_all_with_three_tags(client):
    three = [("tag", "medical"), ("tag", "Kela"), ("tag", "tax")]
    r = client.get("/api/search", params=[*three, ("tag_mode", "any")])
    assert sorted(h["drive_id"] for h in r.json()) == ["id-1", "id-2", "id-3"]
    assert client.get("/api/search", params=three).json() == []
    r = client.get("/api/search", params=[("tag", "medical"), ("tag", "Kela"), ("tag_mode", "all")])
    assert [h["drive_id"] for h in r.json()] == ["id-1"]


def test_any_with_an_unknown_tag_ignores_it(client):
    params = [("tag", "medical"), ("tag", "nope")]
    r = client.get("/api/search", params=[*params, ("tag_mode", "any")])
    assert sorted(h["drive_id"] for h in r.json()) == ["id-1", "id-2"]
    assert client.get("/api/search", params=params).json() == []  # all: nothing can match
    r = client.get("/api/search", params=[("tag", "nope"), ("tag", "x"), ("tag_mode", "any")])
    assert r.json() == []


def test_any_combines_with_words_and_folder(client, app, fake_archive):
    fake_archive.add("Other/g1.pdf", drive_id="id-5", content=b"%PDF kela letter")
    app.scan()
    app.tags.add("id-5", ["tax"])
    for d in ("id-1", "id-3", "id-5"):
        app.repo.save_content(d, None, ExtractedText("decision", "t"), "indexed")
    app.repo.save_content("id-2", None, ExtractedText("other", "t"), "indexed")
    two = [("tag", "medical"), ("tag", "tax"), ("tag_mode", "any")]
    assert search(client, q="decision", tag=["medical", "tax"], tag_mode="any") == [
        "id-1",
        "id-3",
        "id-5",
    ]
    r = client.get("/api/search", params=[("q", "decision"), ("folder", "Other"), *two])
    assert [h["drive_id"] for h in r.json()] == ["id-5"]
    r = client.get("/api/search", params=[("folder", BANKS), *two])
    assert sorted(h["drive_id"] for h in r.json()) == ["id-1", "id-2", "id-3"]


def test_bad_tag_mode_is_refused(client):
    assert client.get("/api/search", params={"tag": "tax", "tag_mode": "some"}).status_code == 422


def test_tag_matches_without_case_or_accents(client, app):
    app.tags.add("id-4", ["Ääni"])
    assert search(client, tag="aani") == ["id-4"]
    assert search(client, tag="KELA") == ["id-1", "id-3"]


def test_tags_combine_with_words(client, app, fake_archive):
    app.tags.add("id-4", ["medical"])
    app.repo.save_content(
        "id-1",
        None,
        ExtractedText("Kela decision", "t"),
        "indexed",
    )
    app.repo.save_content(
        "id-4",
        None,
        ExtractedText("Kela decision", "t"),
        "indexed",
    )
    app.repo.save_content(
        "id-3",
        None,
        ExtractedText("Kela decision", "t"),
        "indexed",
    )
    assert search(client, q="decision") == ["id-1", "id-3", "id-4"]
    assert search(client, q="decision", tag="medical") == ["id-1", "id-4"]


def test_unknown_tag_or_nothing_asked_finds_nothing(client):
    assert search(client, tag="nope") == []
    assert search(client) == []
    assert search(client, tag="  ") == []


def test_tag_search_skips_missing_files(client, app):
    with app.engine.begin() as conn:
        conn.execute(text("UPDATE files SET missing = 1 WHERE drive_id = 'id-2'"))
    assert search(client, tag="medical") == ["id-1"]


def test_tag_search_uses_the_tag_index(app):
    with app.engine.connect() as conn:
        plan = " ".join(
            str(r)
            for r in conn.execute(
                text("EXPLAIN QUERY PLAN SELECT drive_id FROM file_tags WHERE tag_id IN (1)")
            )
        )
    assert "ix_file_tags_tag_id" in plan or "COVERING INDEX" in plan.upper()


# -- the list ------------------------------------------------------------------


def test_listing_has_counts_and_empty_tags(client):
    assert post(client, "/api/tags", {"name": "later"}).status_code == 200
    tags = names(client)
    assert tags["medical"]["files"] == 2 and tags["Kela"]["files"] == 2
    assert tags["later"]["files"] == 0
    assert set(names(client, query="ke")) == {"Kela"}
    assert set(names(client, query="  ")) == set(tags)


def test_create_refuses_a_name_in_use_in_any_case(client):
    assert post(client, "/api/tags", {"name": "KELA"}).status_code == 409
    assert post(client, "/api/tags", {"name": "   "}).status_code == 422


def test_create_undo_removes_it(client):
    out = post(client, "/api/tags", {"name": "later"}).json()
    assert post(client, "/api/tags/undo", out["undo"]).status_code == 200
    assert "later" not in names(client)


# -- rename --------------------------------------------------------------------


def test_rename_updates_every_file_and_undo_restores(client, app):
    out = post(client, "/api/tags/rename", {"name": "medical", "new_name": "health"}).json()
    assert app.tags.for_file("id-1") == ["Kela", "health"]
    assert search(client, tag="health") == ["id-1", "id-2"]
    assert "medical" not in names(client)
    post(client, "/api/tags/undo", out["undo"])
    assert app.tags.for_file("id-2") == ["medical"]
    assert "health" not in names(client)


def test_rename_to_an_existing_name_asks_to_merge(client):
    r = post(client, "/api/tags/rename", {"name": "medical", "new_name": "kela"})
    assert r.status_code == 409 and "merge" in r.json()["error"]


def test_rename_may_only_change_case(client):
    assert (
        post(client, "/api/tags/rename", {"name": "medical", "new_name": "Medical"}).status_code
        == 200
    )
    assert "Medical" in names(client)


def test_rename_missing_tag(client):
    assert post(client, "/api/tags/rename", {"name": "zzz", "new_name": "y"}).status_code == 404


# -- merge ---------------------------------------------------------------------


def test_merge_preview_then_apply_then_undo(client, app):
    body = {"sources": ["tax", "medical"], "into": "Kela"}
    plan = post(client, "/api/tags/merge", {**body, "dry_run": True}).json()
    # Kela is on id-1 and id-3; tax is on id-3, medical on id-1 and id-2: only id-2 gains
    assert plan["gains"] == 1
    assert plan["message"] == "1 file gets 'Kela'; 'tax', 'medical' are removed"
    assert "tax" in names(client)  # a preview changes nothing
    done = post(client, "/api/tags/merge", body).json()
    assert set(names(client)) == {"Kela"}
    assert app.tags.for_file("id-2") == ["Kela"]
    post(client, "/api/tags/undo", done["undo"])
    assert app.tags.for_file("id-2") == ["medical"]
    assert app.tags.for_file("id-3") == ["Kela", "tax"]
    assert names(client)["Kela"]["files"] == 2


def test_merge_needs_another_tag(client):
    assert post(client, "/api/tags/merge", {"sources": ["Kela"], "into": "Kela"}).status_code == 422
    assert post(client, "/api/tags/merge", {"sources": ["zzz"], "into": "Kela"}).status_code == 404


# -- delete --------------------------------------------------------------------


def test_delete_removes_from_every_file_and_undo_brings_back(client, app):
    out = post(client, "/api/tags/delete", {"name": "medical"}).json()
    assert "2 files" in out["message"]
    assert app.tags.for_file("id-1") == ["Kela"]
    assert "medical" not in names(client)
    post(client, "/api/tags/undo", out["undo"])
    assert search(client, tag="medical") == ["id-1", "id-2"]


# -- pins and the sidebar ------------------------------------------------------


def sidebar(client):
    r = client.get("/api/tags/sidebar")
    assert r.status_code == 200
    return [(t["name"], t["pinned"]) for t in r.json()]


def test_sidebar_is_pinned_first_then_most_recent(client, app):
    app.tags.add("id-4", ["fresh"])
    # tags used so far, newest first: fresh, tax, medical, Kela (set below for a stable order)
    with app.engine.begin() as conn:
        for i, n in enumerate(["Kela", "medical", "tax", "fresh"]):
            conn.execute(
                text("UPDATE tags SET last_used_at = :t WHERE name = :n"), {"t": 100 + i, "n": n}
            )
    assert sidebar(client) == [
        ("fresh", False),
        ("tax", False),
        ("medical", False),
        ("Kela", False),
    ]
    post(client, "/api/tags/pin", {"names": ["Kela"], "pinned": True})
    assert sidebar(client) == [("Kela", True), ("fresh", False), ("tax", False), ("medical", False)]
    post(client, "/api/tags/pin", {"names": ["tax"], "pinned": True})
    assert [n for n, _ in sidebar(client)][:2] == ["Kela", "tax"]  # oldest pin first


def test_sidebar_is_at_most_eight(client, app):
    for i in range(12):
        app.tags.add("id-4", [f"t{i:02}"])
    assert len(sidebar(client)) == 8
    post(client, "/api/tags/pin", {"names": [f"t{i:02}" for i in range(10)], "pinned": True})
    assert len(sidebar(client)) == 8 and all(p for _, p in sidebar(client))


def test_unused_tags_are_not_recent_but_a_pinned_one_shows(client):
    post(client, "/api/tags", {"name": "later"})
    assert "later" not in [n for n, _ in sidebar(client)]
    post(client, "/api/tags/pin", {"names": ["later"], "pinned": True})
    assert sidebar(client)[0] == ("later", True)


def test_recent_means_put_on_a_file(app, fake_archive):
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="id-a")
    app.scan()
    app.tags.add("id-a", ["old"])
    app.tags.add("id-a", ["new"])
    time.sleep(0.01)
    app.tags.set_for_file("id-a", ["new", "old"])  # nothing added: the order stays
    assert [t["name"] for t in app.tag_admin.sidebar()] == ["new", "old"]
    time.sleep(0.01)
    app.tags.set_for_file("id-a", ["new"])
    app.tags.set_for_file("id-a", ["new", "old"])  # old is added again: newest
    assert [t["name"] for t in app.tag_admin.sidebar()] == ["old", "new"]


def test_pin_undo(client):
    out = post(client, "/api/tags/pin", {"names": ["Kela"], "pinned": True}).json()
    post(client, "/api/tags/undo", out["undo"])
    assert not names(client)["Kela"]["pinned"]


# -- groups --------------------------------------------------------------------


def test_group_lifecycle(client):
    g = post(client, "/api/tags/groups", {"name": "Health"}).json()
    assert post(client, "/api/tags/groups", {"name": "health"}).status_code == 409
    out = post(
        client, "/api/tags/group", {"names": ["medical", "Kela"], "group_id": g["id"]}
    ).json()
    listing = client.get("/api/tags/all").json()
    assert listing["groups"] == [{"id": g["id"], "name": "Health"}]
    assert names(client)["medical"]["group_id"] == g["id"]
    post(client, "/api/tags/undo", out["undo"])
    assert names(client)["medical"]["group_id"] is None
    post(client, "/api/tags/group", {"names": ["medical"], "group_id": g["id"]})
    assert (
        post(client, f"/api/tags/groups/{g['id']}/rename", {"name": "Care"}).json()["name"]
        == "Care"
    )
    gone = post(client, f"/api/tags/groups/{g['id']}/delete").json()
    assert gone["members"] == ["medical"]
    assert (
        names(client)["medical"]["group_id"] is None
        and client.get("/api/tags/all").json()["groups"] == []
    )
    back = post(
        client, "/api/tags/groups/restore", {"name": gone["name"], "members": gone["members"]}
    ).json()
    assert names(client)["medical"]["group_id"] == back["id"]


def test_a_tag_is_in_one_group_only(client):
    a = post(client, "/api/tags/groups", {"name": "A"}).json()["id"]
    b = post(client, "/api/tags/groups", {"name": "B"}).json()["id"]
    post(client, "/api/tags/group", {"names": ["tax"], "group_id": a})
    post(client, "/api/tags/group", {"names": ["tax"], "group_id": b})
    assert names(client)["tax"]["group_id"] == b


def test_group_errors(client):
    assert post(client, "/api/tags/group", {"names": ["tax"], "group_id": 999}).status_code == 404
    assert post(client, "/api/tags/groups/999/delete").status_code == 404
    assert post(client, "/api/tags/groups/999/rename", {"name": "x"}).status_code == 404
