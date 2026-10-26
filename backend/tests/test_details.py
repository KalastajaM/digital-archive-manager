"""Pick-one suggestions and "Edit details…" (stars spec §7): per-field suggestion
sources, the suggestions of any file, a file's tags written directly, and a rename
(with or without a move) through preview → apply → undo."""

import os

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select

from dam.api import create_api
from dam.db.tables import operations
from dam.extract.base import ExtractedText
from dam.index.repo import FileRecord
from dam.ops.model import OpKind
from dam.ops.planner import COLLISION_NOTE
from dam.rules.engine import suggest
from dam.rules.model import Rule
from dam.services.errors import InvalidRequest, NotFound

INBOX = "##. Organize"
ONG = "##. Ongoing"
QUAR = "##. To Delete"
BANKS = "10. Financial/Banks"
BILLS = "10. Financial/Bills"
BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}


def rule(id: str, when: dict, **then) -> Rule:
    return Rule.model_validate({"id": id, "when": when, "then": then})


def journal(app) -> list:
    with app.engine.connect() as conn:
        return list(conn.execute(select(operations).order_by(operations.c.id)).mappings())


# --- per-field sources -----------------------------------------------------------


def test_each_field_names_the_rule_it_came_from():
    rules = [
        rule("northpower", {"text_contains": ["northpower"]}, folder=BILLS, tags=["bill"]),
        rule(
            "named",
            {"text_contains": ["northpower"]},
            name="{doc_date:%Y%m%d}_Northpower",
            tags=["bill", "power"],
        ),
    ]
    s = suggest(FileRecord(drive_id="x", path=f"{INBOX}/scan.pdf"), "Northpower 1.10.2026", rules)
    assert s.name == "20261001_Northpower.pdf" and s.name_source == "rule:named"
    assert s.folder == BILLS and s.folder_source == "rule:northpower"
    assert s.tags == ["bill", "power"]
    assert s.tag_sources == {"bill": "rule:northpower", "power": "rule:named"}


def test_a_name_made_from_the_scan_says_scan():
    s = suggest(FileRecord(drive_id="x", path=f"{INBOX}/scan.pdf"), "1.10.2026", [])
    assert s.name == "20261001_scan.pdf" and s.name_source == "scan"
    assert s.folder is None and s.folder_source is None and s.tag_sources == {}


# --- the app: suggestions, tags, rename ------------------------------------------


@pytest.fixture
def filed(app, fake_archive):
    """A filed bill (outside the inbox) that the Northpower rule matches, and a second file."""
    fake_archive.add(f"{BANKS}/scan.pdf", b"a", drive_id="id-a")
    fake_archive.add(f"{BANKS}/other.pdf", b"b", drive_id="id-b")
    app.scan()
    app.repo.save_content(
        "id-a", None, ExtractedText("Northpower Oy lasku 1.10.2026", "test"), "indexed"
    )
    (app.rules_dir / "50-northpower.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "id": "northpower",
                    "when": {"text_contains": ["northpower"]},
                    "then": {
                        "folder": BILLS,
                        "name": "{doc_date:%Y%m%d}_Northpower",
                        "tags": ["bill"],
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    assert app.reload_rules() == []


@pytest.fixture
def client(app):
    with TestClient(create_api(app, None), base_url=BASE) as c:
        yield c


def post(client, url, body):
    return client.post(url, json=body, headers=LOCAL_ORIGIN)


def test_suggestions_for_a_file_already_filed(client, filed):
    r = client.get("/api/files/id-a/suggestions")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "20261001_Northpower.pdf" and body["name_source"] == "rule:northpower"
    assert body["folder"] == BILLS and body["folder_source"] == "rule:northpower"
    assert body["tags"] == ["bill"] and body["tag_sources"] == {"bill": "rule:northpower"}
    assert "rule:northpower" in body["sources"]


def test_a_file_with_nothing_to_suggest_gets_no_values(client, fake_archive, app):
    fake_archive.add(f"{BANKS}/20260105_Vuokra.pdf", b"v", drive_id="id-v")
    app.scan()
    body = client.get("/api/files/id-v/suggestions").json()
    # its name already follows the convention: nothing differs, so nothing is suggested
    assert body["name"] is None and body["name_source"] is None
    assert body["folder"] is None and body["tags"] == [] and body["tag_sources"] == {}


def test_suggestions_of_an_unknown_file_are_404(client, filed):
    assert client.get("/api/files/nope/suggestions").status_code == 404


def test_inbox_entries_carry_the_field_sources(client, fake_archive, app, filed):
    fake_archive.add(f"{INBOX}/scan2.pdf", b"c", drive_id="id-c")
    app.scan()
    app.repo.save_content("id-c", None, ExtractedText("Northpower 2.10.2026", "test"), "indexed")
    [entry] = client.get("/api/inbox").json()
    s = entry["suggestion"]
    assert s["name_source"] == "rule:northpower" and s["folder_source"] == "rule:northpower"
    assert s["tag_sources"] == {"bill": "rule:northpower"}


def test_tags_are_written_directly_and_exactly(client, app, filed):
    app.tags.add("id-a", ["old", "keep"])
    r = client.put(
        "/api/files/id-a/tags", json={"tags": [" keep", "new", "new", ""]}, headers=LOCAL_ORIGIN
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"tags": ["keep", "new"]}
    assert app.tags.for_file("id-a") == ["keep", "new"]
    assert client.get("/api/files/id-a").json()["tags"] == ["keep", "new"]
    assert app.tags.for_file("id-b") == []  # another file's tags are untouched
    r = client.put("/api/files/id-a/tags", json={"tags": []}, headers=LOCAL_ORIGIN)
    assert r.json() == {"tags": []} and app.tags.for_file("id-a") == []
    assert journal(app) == []  # tags are not a file operation


def test_tags_of_an_unknown_file_are_404_and_bad_bodies_422(client, filed):
    assert (
        client.put("/api/files/nope/tags", json={"tags": ["a"]}, headers=LOCAL_ORIGIN).status_code
        == 404
    )
    r = client.put("/api/files/id-a/tags", json={"tags": ["a"], "x": 1}, headers=LOCAL_ORIGIN)
    assert r.status_code == 422


def test_tags_need_the_local_origin(client, filed):
    r = client.put(
        "/api/files/id-a/tags", json={"tags": ["a"]}, headers={"Origin": "http://evil.example"}
    )
    assert r.status_code == 403


def test_a_rename_in_its_folder_is_one_rename(app, fake_archive, filed):
    ops = app.browse.rename_file_preview("id-a", "Northpower.pdf", BANKS)
    assert [(op.kind, op.src, op.dst) for op in ops] == [
        (OpKind.RENAME, f"{BANKS}/scan.pdf", f"{BANKS}/Northpower.pdf")
    ]
    assert journal(app) == [] and (fake_archive.root / BANKS / "scan.pdf").exists()


def test_a_rename_and_move_is_one_move_with_its_new_name(app, fake_archive, filed):
    ops = app.browse.rename_file_preview("id-a", "Northpower.pdf", BILLS)
    assert [(op.kind, op.dst) for op in ops] == [
        (OpKind.MKDIR, BILLS),
        (OpKind.MOVE, f"{BILLS}/Northpower.pdf"),
    ]
    result = app.browse.rename_file("id-a", "Northpower.pdf", BILLS)
    assert result.failed is None and result.error is None
    assert (fake_archive.root / BILLS / "Northpower.pdf").read_bytes() == b"a"
    assert app.repo.get("id-a").path == f"{BILLS}/Northpower.pdf"
    assert app.activity.get(result.batch_id).undoable
    outcome = app.activity.undo(result.batch_id)
    assert outcome.batch.error is None
    assert (fake_archive.root / BANKS / "scan.pdf").read_bytes() == b"a"
    assert app.repo.get("id-a").path == f"{BANKS}/scan.pdf"


def test_a_rename_that_changes_nothing_is_unchanged(app, filed):
    result = app.browse.rename_file("id-a", "scan.pdf", BANKS)
    assert result.done == [] and result.unchanged == ["id-a"]
    assert app.browse.rename_file_preview("id-a", "scan.pdf", BANKS) == []


def test_a_rename_onto_a_taken_name_gets_a_suffix(app, filed):
    [op] = app.browse.rename_file_preview("id-a", "other.pdf", BANKS)
    assert op.dst == f"{BANKS}/other_2.pdf" and op.note == COLLISION_NOTE


@pytest.mark.parametrize(
    "name",
    ["", "a/b.pdf", ".DS_Store", " lead.pdf", "trail.pdf ", "x" * 252 + ".pdf", "ä" * 126 + ".pdf"],
)
def test_an_invalid_name_is_refused(app, filed, name):
    with pytest.raises(InvalidRequest):
        app.browse.rename_file_preview("id-a", name, BANKS)


def test_rename_area_rules_are_the_moves(app, fake_archive, filed):
    for folder in (QUAR, ONG):
        with pytest.raises(InvalidRequest):
            app.browse.rename_file_preview("id-a", "x.pdf", folder)
    fake_archive.add(f"{ONG}/Sauna/x.pdf", drive_id="id-ong")
    app.scan()
    with pytest.raises(InvalidRequest):
        app.browse.rename_file_preview("id-ong", "y.pdf", f"{ONG}/Sauna")
    with pytest.raises(InvalidRequest):
        app.browse.rename_file_preview(app.repo.by_path(BANKS).drive_id, "y", "10. Financial")
    with pytest.raises(NotFound):
        app.browse.rename_file_preview("nope", "y.pdf", BANKS)


def test_a_file_replaced_since_the_scan_is_refused(app, fake_archive, filed):
    os.remove(fake_archive.root / BANKS / "scan.pdf")
    fake_archive.add(f"{BANKS}/scan.pdf", b"someone else", drive_id="id-new")  # no scan
    with pytest.raises(InvalidRequest, match="no longer the file 'id-a'"):
        app.browse.rename_file_preview("id-a", "Northpower.pdf", BANKS)
    with pytest.raises(InvalidRequest, match="no longer the file 'id-a'"):
        app.browse.rename_file("id-a", "Northpower.pdf", BANKS)
    assert journal(app) == []
    assert (fake_archive.root / BANKS / "scan.pdf").read_bytes() == b"someone else"


def test_api_rename_preview_rename_and_undo(client, app, fake_archive, filed):
    body = {"drive_id": "id-a", "name": "Northpower.pdf", "folder": BANKS}
    r = post(client, "/api/browse/rename/preview", body)
    assert r.status_code == 200, r.text
    assert [(o["kind"], o["dst"]) for o in r.json()] == [("rename", f"{BANKS}/Northpower.pdf")]
    assert journal(app) == []
    r = post(client, "/api/browse/rename", body)
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["done"][0]["dst"] == f"{BANKS}/Northpower.pdf" and result["unchanged"] == []
    assert (fake_archive.root / BANKS / "Northpower.pdf").exists()
    r = post(client, f"/api/activity/{result['batch_id']}/undo", {})
    assert r.status_code == 200, r.text
    assert (fake_archive.root / BANKS / "scan.pdf").exists()


def test_api_rename_refusals(client, filed):
    for url in ("/api/browse/rename/preview", "/api/browse/rename"):
        r = post(client, url, {"drive_id": "id-a", "name": "a/b", "folder": BANKS})
        assert r.status_code == 400 and r.json()["error"]
        r = post(client, url, {"drive_id": "id-a", "name": "CON.pdf", "folder": BANKS})
        assert r.status_code == 400 and "reserved name on Windows" in r.json()["error"]
        r = post(client, url, {"drive_id": "id-a", "name": "a?.pdf", "folder": BANKS})
        assert r.status_code == 400 and "cannot contain" in r.json()["error"]
        r = post(client, url, {"drive_id": "id-a", "name": "x.pdf", "folder": QUAR})
        assert r.status_code == 400
        assert (
            post(client, url, {"drive_id": "nope", "name": "x.pdf", "folder": BANKS}).status_code
            == 404
        )
        r = post(client, url, {"drive_id": "id-a", "name": "x.pdf", "folder": BANKS, "x": 1})
        assert r.status_code == 422


def test_a_name_of_exactly_255_bytes_is_allowed(app, filed):
    name = "x" * 251 + ".pdf"
    [op] = app.browse.rename_file_preview("id-a", name, BANKS)
    assert op.dst == f"{BANKS}/{name}"


def test_a_file_inside_important_can_be_renamed(app, fake_archive):
    # protected paths are protected against quarantine and removal, not frozen
    fake_archive.add("##. Important/Houses/deed.pdf", b"d", drive_id="id-deed")
    app.scan()
    result = app.browse.rename_file("id-deed", "Deed 2026.pdf", "##. Important/Houses")
    assert result.error is None and result.failed is None
    assert [op.kind for op in result.done] == [OpKind.RENAME]
    assert (fake_archive.root / "##. Important/Houses/Deed 2026.pdf").read_bytes() == b"d"
    app.activity.undo(result.batch_id)
    assert (fake_archive.root / "##. Important/Houses/deed.pdf").exists()
