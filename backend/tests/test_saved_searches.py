"""Saved searches: /api/saved-searches (list with counts, save, replace, rename, delete)."""

from dam.api.routers.saved_searches import counted
from dam.index.scanner import scan
from test_api import LOCAL_ORIGIN, make_client


def _tagged(app, fake_archive):
    for name in ("a", "b", "c"):
        fake_archive.add(f"10. Bills/{name}.pdf", content=name.encode(), drive_id=name)
    scan(app.paths, app.repo)
    for drive_id in ("a", "b"):
        app.tags.add(drive_id, ["bills"])
    app.tags.add("c", ["kela"])


def _post(c, **body):
    return c.post("/api/saved-searches", json=body, headers=LOCAL_ORIGIN)


def test_save_list_and_count(app, fake_archive):
    _tagged(app, fake_archive)
    with make_client(app) as c:
        made = _post(c, name="  Bills   to check ", query="tag:bills")
        assert made.status_code == 200
        assert made.json() == {
            "id": made.json()["id"],
            "name": "Bills to check",
            "query": "tag:bills",
            "tag_mode": "all",
        }
        _post(c, name="Either", query="tag:bills tag:kela", tag_mode="any")
        _post(c, name="both", query="tag:bills tag:kela")
        rows = c.get("/api/saved-searches").json()
        assert [(r["name"], r["count"], r["more"], r["error"]) for r in rows] == [
            ("Bills to check", 2, False, None),
            ("both", 0, False, None),
            ("Either", 3, False, None),
        ]


def test_names_sort_with_numbers_in_order(app):
    for name in ("Year 10", "year 2", "Alpha"):
        app.saved_searches.save(name, "tag:x")
    assert [s.name for s in app.saved_searches.list()] == ["Alpha", "year 2", "Year 10"]


def test_a_name_in_use_is_409_unless_replaced(app, fake_archive):
    _tagged(app, fake_archive)
    with make_client(app) as c:
        first = _post(c, name="Bills", query="tag:bills").json()
        taken = _post(c, name="bills", query="tag:kela")
        assert taken.status_code == 409 and "exists" in taken.json()["error"]
        again = _post(c, name="BILLS", query="tag:kela", tag_mode="any", replace=True).json()
        assert again == {"id": first["id"], "name": "BILLS", "query": "tag:kela", "tag_mode": "any"}
        assert [r["name"] for r in c.get("/api/saved-searches").json()] == ["BILLS"]


def test_rename(app):
    with make_client(app) as c:
        one = _post(c, name="One", query="tag:a").json()
        _post(c, name="Two", query="tag:b")
        done = c.patch(
            f"/api/saved-searches/{one['id']}", json={"name": "Uno"}, headers=LOCAL_ORIGIN
        )
        assert (
            done.status_code == 200
            and done.json()["name"] == "Uno"
            and done.json()["query"] == "tag:a"
        )
        # a change of case only is the same search, not a clash with itself
        same = c.patch(
            f"/api/saved-searches/{one['id']}", json={"name": "UNO"}, headers=LOCAL_ORIGIN
        )
        assert same.status_code == 200
        clash = c.patch(
            f"/api/saved-searches/{one['id']}", json={"name": "two"}, headers=LOCAL_ORIGIN
        )
        assert clash.status_code == 409
        gone = c.patch("/api/saved-searches/999", json={"name": "X"}, headers=LOCAL_ORIGIN)
        assert gone.status_code == 404


def test_delete(app):
    with make_client(app) as c:
        one = _post(c, name="One", query="tag:a").json()
        done = c.delete(f"/api/saved-searches/{one['id']}", headers=LOCAL_ORIGIN)
        assert done.status_code == 200 and done.json() == {"deleted": one["id"]}
        assert c.get("/api/saved-searches").json() == []
        assert c.delete(f"/api/saved-searches/{one['id']}", headers=LOCAL_ORIGIN).status_code == 404


def test_an_empty_or_too_long_name_or_query_is_422(app):
    with make_client(app) as c:
        assert _post(c, name="   ", query="tag:a").status_code == 422
        assert _post(c, name="x" * 201, query="tag:a").status_code == 422
        assert _post(c, name="Empty", query="  ").status_code == 422
        assert _post(c, name="Long", query="a" * 2001).status_code == 422
        assert _post(c, name="Mode", query="tag:a", tag_mode="some").status_code == 422
        assert c.get("/api/saved-searches").json() == []


def test_a_query_refused_now_lists_without_a_count(app):
    with make_client(app) as c:
        _post(c, name="Bad date", query="date:2026-13")
        [row] = c.get("/api/saved-searches").json()
        assert row["count"] is None and row["more"] is False
        assert "not a real date" in row["error"]


def test_the_count_stops_at_500():
    assert counted(3) == {"count": 3, "more": False}
    assert counted(500) == {"count": 500, "more": False}
    assert counted(501) == {"count": 500, "more": True}
