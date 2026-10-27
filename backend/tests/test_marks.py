"""★ Ongoing and ! Important (stars, Task 1): the built-in collections, marks on file
records, quarantine protection, the routes and the CLI."""

import re
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event, insert, select, text
from sqlalchemy.exc import IntegrityError
from typer.testing import CliRunner

from dam.api import create_api
from dam.cli.main import app as cli
from dam.collections.marks import MarkService
from dam.collections.publishers import PublisherRegistry
from dam.collections.service import CollectionService, check_collection_name
from dam.config import SpecialFolders
from dam.db.engine import MIGRATIONS_DIR, migrate, write_tx
from dam.db.tables import collections, files, notes, operations
from dam.errors import InvalidRequest, NotFound
from dam.index.repo import FileRepo
from dam.ops.model import OpKind, Plan

INBOX = "##. Organize"
BANKS = "10. Financial/Banks"
QUAR = "##. To Delete"
BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}
IMPORTANT_REFUSAL = "This file is marked Important; unmark it first"
IMPORTANT_FOLDER_REFUSAL = "This file is in a folder marked Important; unmark it first"
runner = CliRunner()


# --- fixtures ------------------------------------------------------------------------


def _file_row(drive_id: str, path: str, is_dir: bool = False) -> dict:
    return {
        "drive_id": drive_id,
        "path": path,
        "path_nfc": path,
        "name": path.rsplit("/", 1)[-1],
        "is_dir": is_dir,
    }


@pytest.fixture
def svc(engine):
    class Fake:
        id = "ongoing"

        def plan(self, cols):
            return Plan(ops=[], origin="workflow")

    reg = PublisherRegistry()
    reg.register(Fake())
    calls: list[int] = []
    s = CollectionService(
        engine,
        FileRepo(engine, INBOX),
        reg,
        SpecialFolders(),
        on_change=lambda: calls.append(1),
    )
    s.calls = calls
    with write_tx(engine) as conn:
        for i in range(1, 6):
            conn.execute(insert(files).values(**_file_row(f"f{i}", f"{BANKS}/f{i}.pdf")))
    return s


@pytest.fixture
def marks(svc):
    return MarkService(svc)


@contextmanager
def counted(engine):
    """Every SQL query (not BEGIN/COMMIT) run on ``engine`` in the block, in order."""
    seen: list[str] = []

    def hook(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith(("SELECT", "INSERT", "UPDATE", "DELETE")):
            seen.append(statement)

    event.listen(engine, "before_cursor_execute", hook)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", hook)


def mark_queries(statements: list[str]) -> list[str]:
    """The statements that read the marks (``marks_for``)."""
    return [
        s
        for s in statements
        if re.search(r"SELECT collection_members\.drive_id, collections\.kind", s)
    ]


# --- migration -----------------------------------------------------------------------


def _at(new_engine, tmp_path: Path, revision: str):
    engine = new_engine(tmp_path / "old.sqlite")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with write_tx(engine) as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, revision)
    return engine


def test_migration_0017_creates_the_built_ins(engine):
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0037"
        rows = conn.execute(
            select(collections.c.name, collections.c.kind, collections.c.publish)
            .where(collections.c.kind.is_not(None))
            .order_by(collections.c.kind)
        ).all()
    # publish {}: the Ongoing publisher leaves them alone until Task 2 publishes them
    assert [tuple(r) for r in rows] == [("Important", "important", {}), ("Ongoing", "starred", {})]


def test_database_stamped_by_mains_short_lived_0017_heals(tmp_path: Path, new_engine):
    # main's file_fields shipped as 0017 for a while; such a database is stamped 0017
    # with file_fields but without collections.kind
    engine = _at(new_engine, tmp_path, "0016")
    with write_tx(engine) as conn:
        conn.execute(
            text(
                "CREATE TABLE file_fields (drive_id TEXT PRIMARY KEY, fields TEXT NOT NULL,"
                " updated FLOAT NOT NULL)"
            )
        )
        conn.execute(text("INSERT INTO file_fields VALUES ('d1', '{}', 1.0)"))
        conn.execute(text("UPDATE alembic_version SET version_num = '0017'"))
    migrate(engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0037"
        kinds = (
            conn.execute(text("SELECT kind FROM collections WHERE kind IS NOT NULL ORDER BY kind"))
            .scalars()
            .all()
        )
        assert kinds == ["important", "starred"]
        assert conn.execute(text("SELECT drive_id FROM file_fields")).scalars().all() == ["d1"]


def test_kind_is_unique_where_set(engine):
    with pytest.raises(IntegrityError):
        with write_tx(engine) as conn:
            conn.execute(
                insert(collections).values(
                    name="Other", name_fold="other", created=1.0, kind="starred"
                )
            )
    with write_tx(engine) as conn:  # NULL kinds do not clash
        for n in ("A", "B"):
            conn.execute(insert(collections).values(name=n, name_fold=n.lower(), created=1.0))


def test_migration_0017_renames_a_clash_from_0016(tmp_path: Path, new_engine):
    engine = _at(new_engine, tmp_path, "0016")
    with write_tx(engine) as conn:
        for cid, name in ((1, "Ongoing"), (2, "important"), (3, "important (collection)")):
            conn.execute(
                text(
                    "INSERT INTO collections(id, name, name_fold, state, created, publish)"
                    " VALUES (:id, :n, :f, 'open', 1.0, '{\"ongoing\": true}')"
                ),
                {"id": cid, "n": name, "f": name.casefold()},
            )
        conn.execute(text("INSERT INTO collection_members VALUES (1, 'd1', 1.0, NULL, NULL)"))
        conn.execute(
            text(
                "INSERT INTO notes(target_kind, target_id, text, updated)"
                " VALUES ('collection', '2', 'my note', 1.0)"
            )
        )
    migrate(engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0037"
        rows = {
            r.id: (r.name, r.name_fold, r.kind, r.publish)
            for r in conn.execute(select(collections)).all()
        }
        member = conn.execute(text("SELECT collection_id, drive_id FROM collection_members")).one()
        note_rows = dict(
            conn.execute(
                select(notes.c.target_id, notes.c.text).where(notes.c.target_kind == "collection")
            ).all()
        )
    assert rows[1] == ("Ongoing (collection)", "ongoing (collection)", None, {"ongoing": True})
    assert rows[2] == (
        "important (collection 2)",
        "important (collection 2)",
        None,
        {"ongoing": True},
    )
    assert rows[3][:3] == ("important (collection)", "important (collection)", None)
    kinds = {v[2]: v[0] for v in rows.values() if v[2]}
    assert kinds == {"starred": "Ongoing", "important": "Important"}
    assert tuple(member) == (1, "d1")  # the members stay with the renamed collection
    # the rename is recorded in the collection's note (a new one, or above the user's)
    assert "Ongoing" in note_rows["1"] and "renamed" in note_rows["1"]
    assert note_rows["2"].endswith("my note") and "renamed" in note_rows["2"]
    assert "3" not in note_rows
    engine.dispose()


# --- built-in rules ------------------------------------------------------------------


def test_builtin_lookup(svc):
    star = svc.builtin("starred")
    imp = svc.builtin("important")
    assert (star.name, star.kind) == ("Ongoing", "starred")
    assert (imp.name, imp.kind) == ("Important", "important")
    with pytest.raises(InvalidRequest):
        svc.builtin("other")


def test_builtins_refuse_changes(svc):
    star = svc.builtin("starred")
    imp = svc.builtin("important")
    other = svc.create("Sauna")
    for c in (star, imp):
        with pytest.raises(InvalidRequest, match="built in"):
            svc.set_name(c.id, "New name")
        with pytest.raises(InvalidRequest, match="built in"):
            svc.close(c.id)
        with pytest.raises(InvalidRequest, match="built in"):
            svc.reopen(c.id)
        with pytest.raises(InvalidRequest, match="built in"):
            svc.set_parent(c.id, other.id)
        with pytest.raises(InvalidRequest, match="built in"):
            svc.set_parent(c.id, None)
        with pytest.raises(InvalidRequest, match="built in"):
            svc.set_parent(other.id, c.id)  # no children
        with pytest.raises(InvalidRequest, match="built in"):
            svc.create("Child", parent_id=c.id)
        with pytest.raises(InvalidRequest, match="built in"):
            svc.set_publish(c.id, "ongoing", False)
        with pytest.raises(InvalidRequest, match="built in"):
            svc.get_or_create(c.name.upper())
    with pytest.raises(InvalidRequest, match="no groups"):
        svc.create_group(star.id, "Work")
    group = svc.create_group(imp.id, "Houses")  # Important may have groups
    assert svc.get(imp.id).groups[0].id == group.id
    assert svc.get(star.id).state == "open" and svc.get(star.id).name == "Ongoing"
    assert svc.get(other.id).parent_id is None


STAR_REFUSAL = "'Ongoing' is built in: use the ★ Starred mark instead"
IMPORTANT_NAME_REFUSAL = "'Important' is built in: use the ! Important mark instead"


def test_reserved_names_are_refused(svc):
    with pytest.raises(InvalidRequest, match=STAR_REFUSAL):
        check_collection_name(" ongoing ")
    with pytest.raises(InvalidRequest, match=IMPORTANT_NAME_REFUSAL):
        check_collection_name("IMPORTANT")
    assert check_collection_name("Important stuff") == "Important stuff"
    with pytest.raises(InvalidRequest, match=STAR_REFUSAL):
        svc.create("ongoing")
    with pytest.raises(InvalidRequest, match=IMPORTANT_NAME_REFUSAL):
        svc.create("IMPORTANT")
    with pytest.raises(InvalidRequest, match=IMPORTANT_NAME_REFUSAL):
        svc.get_or_create("important")
    c = svc.create("Sauna")
    with pytest.raises(InvalidRequest, match=IMPORTANT_NAME_REFUSAL):
        svc.set_name(c.id, "Important")


def test_builtins_are_hidden_from_lists(svc):
    svc.create("Sauna")
    assert [c.name for c in svc.list()] == ["Sauna"]
    assert [c.name for c in svc.list(None)] == ["Sauna"]
    assert {c.name for c in svc.list(None, include_builtin=True)} == {
        "Sauna",
        "Ongoing",
        "Important",
    }
    star = svc.builtin("starred")
    svc.add_members(star.id, ["f1"])
    assert svc.for_file("f1") == []
    assert [c.kind for c in svc.for_file("f1", include_builtin=True)] == ["starred"]


# --- MarkService ---------------------------------------------------------------------


def test_star_toggles(marks, svc):
    marks.star(["f1", "f2"])
    assert marks.marks_for(["f1", "f2", "f3"]) == {
        "f1": ["starred"],
        "f2": ["starred"],
        "f3": [],
    }
    marks.star(["f1"])  # already starred: no-op
    assert [m.drive_id for m in svc.builtin("starred").members] == ["f1", "f2"]
    marks.unstar(["f1"])
    assert marks.marks_for(["f1", "f2"]) == {"f1": [], "f2": ["starred"]}
    marks.unstar(["f1"])  # not starred: no-op
    with pytest.raises(NotFound):
        marks.star(["nope"])


def test_mark_important_with_a_group_path(marks, svc):
    marks.mark_important(["f1"], "Houses/Hillside")
    marks.mark_important(["f2"], " Houses / Hillside ")  # the same groups again
    marks.mark_important(["f3"], None)
    imp = svc.builtin("important")
    groups = {g.id: g for g in imp.groups}
    assert len(groups) == 2
    by_id = {m.drive_id: m.group_id for m in imp.members}
    hillside = groups[by_id["f1"]]
    assert hillside.name == "Hillside" and groups[hillside.parent_id].name == "Houses"
    assert by_id["f2"] == hillside.id and by_id["f3"] is None
    # one group per file: another path moves it
    marks.mark_important(["f1"], "Passports")
    imp = svc.builtin("important")
    names = {g.id: g.name for g in imp.groups}
    assert names[{m.drive_id: m.group_id for m in imp.members}["f1"]] == "Passports"
    # without a path, a file keeps its group
    marks.mark_important(["f1"], None)
    imp = svc.builtin("important")
    assert names[{m.drive_id: m.group_id for m in imp.members}["f1"]] == "Passports"
    marks.star(["f1"])
    assert marks.marks_for(["f1"]) == {"f1": ["starred", "important"]}
    marks.unmark_important(["f1", "f2"])
    assert marks.marks_for(["f1", "f2", "f3"]) == {
        "f1": ["starred"],
        "f2": [],
        "f3": ["important"],
    }
    with pytest.raises(InvalidRequest):
        marks.mark_important(["f4"], "Houses//x")


def test_marks_change_notifies_once(marks, svc):
    before = len(svc.calls)
    marks.star(["f1", "f2"])
    marks.mark_important(["f3"], "A/B/C")
    marks.unstar(["f1", "f2"])
    assert len(svc.calls) == before + 3


def test_marks_for_is_one_query(marks, svc, engine):
    marks.star(["f1"])
    marks.mark_important(["f2"], None)
    many = [f"f{i}" for i in range(1, 6)] + [f"x{i}" for i in range(2000)]
    for ids in (["f1"], many):
        with counted(engine) as seen:
            out = marks.marks_for(ids)
        assert len(seen) == 1, seen
        assert out["f1"] == ["starred"] and out.get("f2", ["important"]) == ["important"]
    with counted(engine) as seen:
        assert marks.marks_for([]) == {}
    assert seen == []


# --- quarantine ----------------------------------------------------------------------


def test_quarantine_refuses_an_important_file(app, fake_archive):
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="a")
    fake_archive.add(f"{BANKS}/b.pdf", drive_id="b")
    fake_archive.add("20. Home/Deeds/deed.pdf", drive_id="deed")
    app.scan()
    app.marks.mark_important(["b", "deed"], None)
    for ids in (["b"], ["a", "b"]):
        for dry_run in (True, False):
            with pytest.raises(InvalidRequest, match=IMPORTANT_REFUSAL):
                app.browse.quarantine(ids, origin="ui", dry_run=dry_run)
    # a folder holding an Important file is refused too
    folder = app.repo.by_path("20. Home/Deeds").drive_id
    with pytest.raises(InvalidRequest, match=IMPORTANT_REFUSAL):
        app.browse.quarantine([folder], origin="ui")
    assert (fake_archive.root / BANKS / "a.pdf").exists()
    assert (fake_archive.root / "20. Home/Deeds/deed.pdf").exists()
    with app.engine.connect() as conn:  # nothing moved (the publisher's links aside)
        assert {r.kind for r in conn.execute(select(operations)).all()} <= {"symlink"}
    app.marks.unmark_important(["b"])
    result = app.browse.quarantine(["a", "b"], origin="ui")
    assert result.error is None and len(result.done) >= 2
    assert (fake_archive.root / QUAR / BANKS / "b.pdf").exists()


# --- API -----------------------------------------------------------------------------


@pytest.fixture
def client(app):
    with TestClient(create_api(app), base_url=BASE) as c:
        yield c


def send(client, method, url, body=None):
    return client.request(method, url, json=body if body is not None else {}, headers=LOCAL_ORIGIN)


@pytest.fixture
def tree(app, fake_archive):
    fake_archive.add(f"{INBOX}/in1.pdf", drive_id="in1")
    fake_archive.add(f"{INBOX}/in2.pdf", drive_id="in2")
    for i in range(1, 6):
        fake_archive.add(f"{BANKS}/s{i}.txt", content=b"zebra statement", drive_id=f"s{i}")
    app.scan()
    app.index()


def test_mark_routes(client, app, tree):
    r = send(client, "POST", "/api/marks/star", {"drive_ids": ["s1", "s2"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"collection", "batch", "problems", "ongoing_status"}
    assert body["collection"]["kind"] == "starred"
    assert [m["drive_id"] for m in body["collection"]["members"]] == ["s1", "s2"]
    assert all(m["marks"] == ["starred"] for m in body["collection"]["members"])
    r = send(
        client, "POST", "/api/marks/important", {"drive_ids": ["s2"], "group": "Houses/Hillside"}
    )
    assert r.status_code == 200, r.text
    imp = r.json()["collection"]
    assert imp["kind"] == "important"
    assert [g["name"] for g in imp["groups"]] == ["Houses", "Hillside"]
    assert imp["members"][0]["marks"] == ["starred", "important"]
    assert send(client, "POST", "/api/marks/unstar", {"drive_ids": ["s1"]}).status_code == 200
    assert send(client, "POST", "/api/marks/unimportant", {"drive_ids": ["s2"]}).status_code == 200
    assert app.marks.marks_for(["s1", "s2"]) == {"s1": [], "s2": ["starred"]}
    assert send(client, "POST", "/api/marks/star", {"drive_ids": ["nope"]}).status_code == 404
    assert send(client, "POST", "/api/marks/other", {"drive_ids": ["s1"]}).status_code == 404
    r = send(client, "POST", "/api/marks/star", {"drive_ids": ["s1"], "group": "X"})
    assert r.status_code == 400  # ★ has no groups


def test_collection_routes_hide_and_protect_the_builtins(client, app, tree):
    star = app.collections.builtin("starred")
    assert client.get("/api/collections").json() == []
    rows = client.get("/api/collections", params={"builtin": True, "state": "all"}).json()
    assert {(c["name"], c["kind"]) for c in rows} == {
        ("Ongoing", "starred"),
        ("Important", "important"),
    }
    assert send(client, "PATCH", f"/api/collections/{star.id}", {"name": "X"}).status_code == 400
    assert send(client, "POST", f"/api/collections/{star.id}/close").status_code == 400
    r = send(client, "POST", "/api/collections", {"name": "Ongoing"})
    assert r.status_code == 400 and STAR_REFUSAL in r.text
    # the previews refuse what their apply refuses
    for url, body in (
        (f"/api/collections/{star.id}/rename/preview", {"name": "X"}),
        (f"/api/collections/{star.id}/reopen/preview", {}),
        (f"/api/collections/{star.id}/publish/preview", {"publisher": "ongoing", "on": False}),
        (f"/api/collections/{star.id}/close/preview", {}),
    ):
        r = send(client, "POST", url, body)
        assert r.status_code == 400 and "built in" in r.text, (url, r.text)
    sauna = send(client, "POST", "/api/collections", {"name": "Sauna"}).json()
    r = send(
        client, "POST", f"/api/collections/{sauna['id']}/rename/preview", {"name": "important"}
    )
    assert r.status_code == 400 and IMPORTANT_NAME_REFUSAL in r.text
    r = send(client, "POST", f"/api/collections/{sauna['id']}/rename/preview", {"name": "Spa"})
    assert r.status_code == 200, r.text


def test_quarantine_route_and_cli_refuse_important(client, app, tree, app_paths, fake_archive):
    app.marks.mark_important(["s2"], None)
    r = send(client, "POST", "/api/quarantine", {"drive_ids": ["s1", "s2"], "dry_run": True})
    assert r.status_code == 400 and IMPORTANT_REFUSAL in r.text
    r = runner.invoke(
        cli, ["--data-dir", str(app_paths.data_dir), "quarantine", "s1", "s2", "--yes"]
    )
    assert r.exit_code == 1 and IMPORTANT_REFUSAL in r.stderr
    assert (fake_archive.root / BANKS / "s1.txt").exists()


@pytest.mark.parametrize("area", [QUAR, "##. Ongoing"])
def test_inbox_filing_refuses_the_quarantine_and_ongoing(
    client, app, tree, app_paths, fake_archive, area
):
    """Final review #1: an Important inbox file could be filed into ``##. To Delete``.
    Filing (API preview, API file, ``dam file``) refuses a destination at or under the
    quarantine or Ongoing with Browse's message, marked or not."""
    app.marks.mark_important(["in1"], None)
    refusal = f"Files cannot be moved into {area}"
    for folder in (area, f"{area}/Old"):
        req = {"drive_id": "in1", "name": "in1.pdf", "folder": folder}
        r = send(client, "POST", "/api/inbox/preview", [req])
        assert r.status_code == 400 and refusal in r.text, r.text
        for dry_run in (True, False):
            r = send(client, "POST", "/api/inbox/file", {"requests": [req], "dry_run": dry_run})
            assert r.status_code == 400 and refusal in r.text, r.text
        # an unmarked file is refused the same way (the area is never a filing target)
        r = send(client, "POST", "/api/inbox/preview", [{**req, "drive_id": "in2"}])
        assert r.status_code == 400 and refusal in r.text, r.text
    r = runner.invoke(
        cli,
        [
            "--data-dir",
            str(app_paths.data_dir),
            "file",
            "in1",
            "--folder",
            f"{area}/Old",
            "--name",
            "in1.pdf",
            "--yes",
        ],
    )
    assert r.exit_code == 1 and refusal in r.stderr, r.output + r.stderr
    assert (fake_archive.root / INBOX / "in1.pdf").exists()
    assert not (fake_archive.root / area / "Old").exists()
    assert app.repo.get("in1").path == f"{INBOX}/in1.pdf"
    with app.engine.connect() as conn:  # only the mark's own link was journaled
        kinds = {r.kind for r in conn.execute(select(operations)).all()}
    assert kinds <= {"symlink"}, kinds


def test_an_important_file_is_never_moved_into_the_quarantine(client, app, tree):
    """Belt and braces for #1: Browse move / Edit details refuse the quarantine too."""
    app.marks.mark_important(["s2"], None)
    r = send(client, "POST", "/api/browse/move", {"drive_ids": ["s2"], "folder": f"{QUAR}/x"})
    assert r.status_code == 400 and f"Files cannot be moved into {QUAR}" in r.text, r.text
    r = send(
        client,
        "POST",
        "/api/browse/rename/preview",
        {"drive_id": "s2", "name": "s2.txt", "folder": QUAR},
    )
    assert r.status_code == 400 and f"Files cannot be moved into {QUAR}" in r.text, r.text


def test_quarantine_refuses_a_file_under_a_folder_marked_important(client, app, tree, fake_archive):
    """Final review #3 (ruling): protection follows a folder mark down to its files."""
    banks = app.repo.by_path(BANKS)
    assert banks is not None and banks.is_dir
    app.marks.mark_important([banks.drive_id], None)
    r = send(client, "POST", "/api/quarantine", {"drive_ids": ["s1"], "dry_run": True})
    assert r.status_code == 400 and IMPORTANT_FOLDER_REFUSAL in r.text, r.text
    assert f"{BANKS}/s1.txt" in r.text
    # the marked folder itself, and its parent, are refused as before
    r = send(client, "POST", "/api/quarantine", {"drive_ids": [banks.drive_id], "dry_run": True})
    assert r.status_code == 400 and IMPORTANT_REFUSAL in r.text, r.text
    fin = app.repo.by_path("10. Financial")
    r = send(client, "POST", "/api/quarantine", {"drive_ids": [fin.drive_id], "dry_run": True})
    assert r.status_code == 400 and IMPORTANT_REFUSAL in r.text, r.text
    # a sibling tree is untouched by the mark
    r = send(client, "POST", "/api/quarantine", {"drive_ids": ["in2"], "dry_run": True})
    assert r.status_code == 200, r.text
    app.marks.unmark_important([banks.drive_id])
    r = send(client, "POST", "/api/quarantine", {"drive_ids": ["s1"], "dry_run": True})
    assert r.status_code == 200, r.text


def _all_file_responses(client, app) -> dict[str, list[str]]:
    """Every response carrying file records: the marks of s1 (or in1) in each."""
    item = app.trays.create(app.tray_defs[0].id, ["s1", "s2"], {}, "Bill")
    out: dict[str, list[str]] = {}
    browse = client.get("/api/browse", params={"path": BANKS}).json()
    out["browse"] = next(e["marks"] for e in browse if e["drive_id"] == "s1")
    flat = client.get("/api/browse/files", params={"path": BANKS}).json()
    out["files"] = next(e["marks"] for e in flat["rows"] if e["drive_id"] == "s1")
    hits = client.get("/api/search", params={"q": "zebra"}).json()
    out["search"] = next(h["marks"] for h in hits if h["drive_id"] == "s1")
    out["detail"] = client.get("/api/files/s1").json()["record"]["marks"]
    inbox = client.get("/api/inbox").json()
    out["inbox"] = next(e["record"]["marks"] for e in inbox if e["record"]["drive_id"] == "in1")
    star = app.collections.builtin("starred")
    members = client.get(f"/api/collections/{star.id}").json()["members"]
    out["members"] = next(m["marks"] for m in members if m["drive_id"] == "s1")
    links = client.get("/api/files/s1/links").json()
    assert links["collections"] == []  # the built-ins are not listed as collections
    rows = client.get(f"/api/items/{item.id}/files").json()
    out["item_files"] = next(f["marks"] for f in rows if f["drive_id"] == "s1")
    tray_rows = client.get(f"/api/trays/{item.tray_id}/items").json()
    out["tray_first_file"] = next(t["first_file"]["marks"] for t in tray_rows if t["id"] == item.id)
    today = client.get("/api/today").json()
    for row in today["found"]:
        assert "marks" in row
    return out


def test_every_file_record_carries_marks(client, app, tree):
    app.marks.star(["s1", "in1"])
    app.marks.mark_important(["s1"], None)
    out = _all_file_responses(client, app)
    assert {k: v for k, v in out.items() if k != "inbox"} == {
        k: ["starred", "important"] for k in out if k != "inbox"
    }
    assert out["inbox"] == ["starred"]
    assert (
        send(client, "POST", "/api/marks/unstar", {"drive_ids": ["s1", "in1"]}).status_code == 200
    )
    assert send(client, "POST", "/api/marks/unimportant", {"drive_ids": ["s1"]}).status_code == 200
    assert client.get("/api/files/s1").json()["record"]["marks"] == []


@pytest.mark.parametrize(
    "url,params",
    [
        ("/api/browse", {"path": BANKS}),
        ("/api/browse/files", {"path": BANKS}),
        ("/api/search", {"q": "zebra"}),
        ("/api/files/s1", {}),
        ("/api/inbox", {}),
        ("/api/today", {}),
        ("/api/collections", {"builtin": True}),
        ("STAR", {}),
    ],
)
def test_marks_are_one_query_per_response(client, app, tree, url, params):
    app.marks.star([f"s{i}" for i in range(1, 6)] + ["in1", "in2"])
    if url == "STAR":
        url = f"/api/collections/{app.collections.builtin('starred').id}"
    with counted(app.engine) as seen:
        r = client.get(url, params=params)
    assert r.status_code == 200, r.text
    # Today lists no inbox file found for a tray here: no file rows, no marks query
    assert len(mark_queries(seen)) == (0 if url == "/api/today" else 1), mark_queries(seen)


def test_tray_and_item_files_marks_are_one_query(client, app, tree):
    tray = app.tray_defs[0].id
    items = [app.trays.create(tray, [f"s{i}"], {}, f"Item {i}") for i in range(1, 4)]
    app.marks.star(["s1", "s2", "s3"])
    with counted(app.engine) as seen:
        rows = client.get(f"/api/trays/{tray}/items").json()
    assert len(mark_queries(seen)) == 1
    assert all(r["first_file"]["marks"] == ["starred"] for r in rows)
    with counted(app.engine) as seen:
        files_ = client.get(f"/api/items/{items[0].id}/files").json()
    assert len(mark_queries(seen)) == 1
    assert files_[0]["marks"] == ["starred"]


# --- CLI -----------------------------------------------------------------------------


@pytest.fixture
def run(app_paths):
    def _run(*args, input=None):
        return runner.invoke(cli, ["--data-dir", str(app_paths.data_dir), *map(str, args)])

    return _run


def test_cli_marks(run, app, fake_archive):
    fake_archive.add(f"{BANKS}/plan.xlsx", drive_id="p1")
    fake_archive.add(f"{BANKS}/deed.pdf", drive_id="d1")
    run("scan")
    r = run("star", f"{BANKS}/plan.xlsx")
    assert r.exit_code == 0, r.output
    r = run("starred")
    assert r.exit_code == 0 and f"{BANKS}/plan.xlsx" in r.stdout
    r = run("important", "d1", "--group", "Houses/Hillside")
    assert r.exit_code == 0, r.output
    r = run("important", "--list")
    assert r.exit_code == 0 and "Houses › Hillside" in r.stdout and f"{BANKS}/deed.pdf" in r.stdout
    assert app.marks.marks_for(["p1", "d1"]) == {"p1": ["starred"], "d1": ["important"]}
    r = run("collections")
    assert "Ongoing" not in r.stdout and "Important" not in r.stdout
    assert run("unstar", "p1").exit_code == 0
    assert run("unimportant", f"{BANKS}/deed.pdf").exit_code == 0
    assert app.marks.marks_for(["p1", "d1"]) == {"p1": [], "d1": []}
    r = run("starred")
    assert r.exit_code == 0 and "no starred files" in r.stdout
    r = run("important", "--list")
    assert "no important files" in r.stdout
    r = run("important")
    assert r.exit_code == 1 and "error:" in r.stderr
    r = run("star", "nope")
    assert r.exit_code == 1


def test_convert_never_fills_a_builtin(app, fake_archive):
    fake_archive.add(f"{BANKS}/plan.xlsx", drive_id="p1")
    fake_archive.link("##. Ongoing/plan.xlsx", f"{BANKS}/plan.xlsx")
    app.scan()
    with pytest.raises(InvalidRequest, match=STAR_REFUSAL):
        app.convert.preview("##. Ongoing/plan.xlsx", "Ongoing", None)
    with pytest.raises(InvalidRequest, match=IMPORTANT_NAME_REFUSAL):
        app.convert.preview("##. Ongoing/plan.xlsx", "important", None)
    assert app.marks.marks_for(["p1"]) == {"p1": []}


def test_filing_never_fills_a_builtin(client, app, fake_archive):
    fake_archive.add(f"{INBOX}/scan.pdf", drive_id="in1")
    app.scan()
    req = {"drive_id": "in1", "name": "deed.pdf", "folder": BANKS, "collections": ["important"]}
    r = send(client, "POST", "/api/inbox/preview", [req])
    assert r.status_code == 400 and IMPORTANT_NAME_REFUSAL in r.text
    for dry_run in (True, False):
        r = send(client, "POST", "/api/inbox/file", {"requests": [req], "dry_run": dry_run})
        assert r.status_code == 400 and IMPORTANT_NAME_REFUSAL in r.text
    r = send(
        client,
        "POST",
        "/api/inbox/file",
        {"requests": [{**req, "collections": ["Sauna", "Ongoing"]}]},
    )
    assert r.status_code == 400 and STAR_REFUSAL in r.text
    assert (fake_archive.root / INBOX / "scan.pdf").exists()
    assert app.repo.get("in1").path == f"{INBOX}/scan.pdf"
    with app.engine.connect() as conn:
        assert conn.execute(select(operations)).all() == []
    assert app.collections.by_name("Sauna") is None
    assert app.marks.marks_for(["in1"]) == {"in1": []}


def test_only_important_adds_wait_for_a_running_quarantine(app, fake_archive, monkeypatch):
    """The Important marks are read and the batch runs under ``important_lock``:
    marking a file Important while a quarantine runs waits until the batch is done,
    while a star or an add to an ordinary collection goes ahead at once."""
    import threading

    fake_archive.add(f"{BANKS}/a.pdf", drive_id="a")
    fake_archive.add(f"{BANKS}/b.pdf", drive_id="b")
    app.scan()
    sauna = app.collections.create("Sauna")
    real_apply = app.executor.apply
    waiting: list[threading.Thread] = []

    def start(target, *args) -> threading.Thread:
        t = threading.Thread(target=target, args=args)
        t.start()
        return t

    def apply(plan, dry_run=False, check=None):
        if waiting or not any(op.kind is OpKind.QUARANTINE for op in plan.ops):
            return real_apply(plan, dry_run=dry_run, check=check)  # e.g. an Ongoing sync
        for t in (
            start(app.marks.star, ["b"]),
            start(app.collections.add_members, sauna.id, ["b"]),
            start(app.collections.set_member_group, sauna.id, ["a"], None),
        ):
            t.join(5)
            assert not t.is_alive()  # not held up by the quarantine
        t = start(app.marks.mark_important, ["a"], None)
        t.join(0.3)
        assert t.is_alive()  # blocked on important_lock while the batch runs
        waiting.append(t)
        return real_apply(plan, dry_run=dry_run, check=check)

    monkeypatch.setattr(app.executor, "apply", apply)
    result = app.browse.quarantine(["a"], origin="ui")
    waiting[0].join(5)
    assert not waiting[0].is_alive()
    assert result.error is None and result.done
    assert app.marks.marks_for(["a", "b"]) == {"a": ["important"], "b": ["starred"]}
    assert {m.drive_id for m in app.collections.get(sauna.id).members} == {"a", "b"}
