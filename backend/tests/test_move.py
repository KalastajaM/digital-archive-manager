"""General file move between archive folders: plan, preview, apply, undo, refusals."""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from typer.testing import CliRunner

from dam.api import create_api
from dam.cli.main import app as cli
from dam.core.fs import readlink
from dam.db.tables import operations
from dam.ops.model import OpKind
from dam.ops.planner import COLLISION_NOTE
from dam.services.errors import InvalidRequest, NotFound

INBOX = "##. Organize"
ONG = "##. Ongoing"
IMP = "##. Important"
QUAR = "##. To Delete"
BANKS = "10. Financial/Banks"
TAXES = "10. Financial/Taxes"
BASE = "http://127.0.0.1:8765"
LOCAL_ORIGIN = {"Origin": BASE}


def journal(app) -> list:
    with app.engine.connect() as conn:
        return list(conn.execute(select(operations).order_by(operations.c.id)).mappings())


@pytest.fixture
def two_files(app, fake_archive):
    fake_archive.add(f"{BANKS}/a.pdf", b"a", drive_id="id-a")
    fake_archive.add(f"{BANKS}/b.pdf", b"b", drive_id="id-b")
    app.scan()


# --- plan, preview, apply, undo ------------------------------------------------------


def test_move_plan_is_one_move_per_file_keeping_its_name(app, two_files):
    plan = app.browse.move_plan(["id-a", "id-b"], TAXES)
    assert plan.origin == "ui"
    assert [(op.kind, op.src, op.dst) for op in plan.ops] == [
        (OpKind.MOVE, f"{BANKS}/a.pdf", TAXES),
        (OpKind.MOVE, f"{BANKS}/b.pdf", TAXES),
    ]
    assert all(op.name is None for op in plan.ops)


def test_move_and_its_undo(app, fake_archive, two_files):
    preview = app.browse.move_preview(["id-a", "id-b"], TAXES)
    assert [(op.kind, op.dst) for op in preview] == [
        (OpKind.MKDIR, TAXES),  # the new folder is shown
        (OpKind.MOVE, f"{TAXES}/a.pdf"),
        (OpKind.MOVE, f"{TAXES}/b.pdf"),
    ]
    assert journal(app) == []  # a preview journals nothing
    assert (fake_archive.root / BANKS / "a.pdf").exists()

    result = app.browse.move(["id-a", "id-b"], TAXES, origin="cli")
    assert result.failed is None and result.error is None and result.index_error is None
    assert [op.dst for op in result.done] == [TAXES, f"{TAXES}/a.pdf", f"{TAXES}/b.pdf"]
    assert result.unchanged == []
    assert (fake_archive.root / TAXES / "a.pdf").read_bytes() == b"a"
    assert not (fake_archive.root / BANKS / "a.pdf").exists()
    assert app.repo.get("id-a").path == f"{TAXES}/a.pdf"
    rows = journal(app)
    assert {r["batch_id"] for r in rows} == {result.batch_id}
    assert {r["origin"] for r in rows} == {"cli"}
    assert app.activity.get(result.batch_id).undoable

    outcome = app.activity.undo(result.batch_id)
    assert outcome.batch.failed is None and outcome.batch.error is None
    assert outcome.follow_up_error is None
    assert (fake_archive.root / BANKS / "a.pdf").read_bytes() == b"a"
    assert (fake_archive.root / BANKS / "b.pdf").exists()
    assert not (fake_archive.root / TAXES / "a.pdf").exists()
    assert app.repo.get("id-a").path == f"{BANKS}/a.pdf"
    assert app.activity.get(result.batch_id).undone


def test_move_dry_run_changes_nothing(app, fake_archive, two_files):
    result = app.browse.move(["id-a"], TAXES, dry_run=True)
    assert result.dry_run and [op.kind for op in result.done] == [OpKind.MKDIR, OpKind.MOVE]
    assert journal(app) == [] and (fake_archive.root / BANKS / "a.pdf").exists()


def test_move_collision_is_renamed_with_note(app, fake_archive, two_files):
    fake_archive.add(f"{INBOX}/a.pdf", b"other", drive_id="id-other")
    app.scan()
    [op] = app.browse.move_preview(["id-a"], INBOX)
    assert (op.kind, op.src, op.dst) == (OpKind.MOVE, f"{BANKS}/a.pdf", f"{INBOX}/a_2.pdf")
    assert op.note == COLLISION_NOTE
    result = app.browse.move(["id-a"], INBOX)
    assert [(r.dst, r.note) for r in result.done] == [(f"{INBOX}/a_2.pdf", COLLISION_NOTE)]
    assert (fake_archive.root / INBOX / "a.pdf").read_bytes() == b"other"  # untouched
    assert (fake_archive.root / INBOX / "a_2.pdf").read_bytes() == b"a"


def test_two_files_with_one_name_into_one_folder(app, fake_archive, two_files):
    fake_archive.add(f"{INBOX}/a.pdf", b"inbox a", drive_id="id-ia")
    app.scan()
    ops = app.browse.move_preview(["id-a", "id-ia"], TAXES)
    assert [(op.dst, op.note) for op in ops if op.kind is OpKind.MOVE] == [
        (f"{TAXES}/a.pdf", None),
        (f"{TAXES}/a_2.pdf", COLLISION_NOTE),
    ]


@pytest.mark.parametrize("folder", [INBOX, IMP, f"{IMP}/Passports"])
def test_moving_into_organize_and_important_is_allowed(app, fake_archive, two_files, folder):
    result = app.browse.move(["id-a"], folder)
    assert result.failed is None and result.error is None
    assert (fake_archive.root / folder / "a.pdf").exists()
    assert app.repo.get("id-a").path == f"{folder}/a.pdf"


def test_moving_out_of_organize_and_important_is_allowed(app, fake_archive):
    fake_archive.add(f"{INBOX}/in.pdf", drive_id="id-in")
    fake_archive.add(f"{IMP}/imp.pdf", drive_id="id-imp")
    app.scan()
    result = app.browse.move(["id-in", "id-imp"], BANKS)
    assert result.failed is None and result.error is None
    assert app.repo.get("id-in").path == f"{BANKS}/in.pdf"
    assert app.repo.get("id-imp").path == f"{BANKS}/imp.pdf"


def test_a_file_already_in_the_folder_gets_no_op_and_is_unchanged(app, fake_archive, two_files):
    fake_archive.add(f"{INBOX}/c.pdf", drive_id="id-c")
    app.scan()
    plan = app.browse.move_plan(["id-a", "id-c"], BANKS)
    assert [op.src for op in plan.ops] == [f"{INBOX}/c.pdf"]
    # another spelling of the same folder (APFS: case-insensitive) is the same folder
    assert app.browse.move_preview(["id-a"], "10. financial/banks") == []
    result = app.browse.move(["id-a", "id-c"], BANKS)
    assert result.unchanged == ["id-a"]
    assert [op.dst for op in result.done] == [f"{BANKS}/c.pdf"]
    nothing = app.browse.move(["id-a"], BANKS)
    assert nothing.done == [] and nothing.unchanged == ["id-a"] and nothing.failed is None
    assert (fake_archive.root / BANKS / "a.pdf").exists()


# --- refusals ------------------------------------------------------------------------


def assert_refused(app, fake_archive, ids, folder, match):
    before = sorted(str(p.relative_to(fake_archive.root)) for p in fake_archive.root.rglob("*"))
    for call in (app.browse.move_plan, app.browse.move_preview, app.browse.move):
        with pytest.raises(InvalidRequest, match=match):
            call(ids, folder)
    after = sorted(str(p.relative_to(fake_archive.root)) for p in fake_archive.root.rglob("*"))
    assert after == before and journal(app) == []


def test_a_folder_cannot_be_moved(app, fake_archive, two_files):
    folder_id = app.repo.by_path(BANKS).drive_id
    assert_refused(app, fake_archive, [folder_id], INBOX, "folders cannot be moved yet")


def test_a_link_cannot_be_moved(app, fake_archive, two_files):
    fake_archive.link("Home/a-link.pdf", f"{BANKS}/a.pdf")
    app.scan()
    link = app.repo.by_path("Home/a-link.pdf")
    assert link is not None and link.is_link
    assert_refused(app, fake_archive, [link.drive_id], INBOX, "links cannot be moved")


@pytest.mark.parametrize("area", [ONG, QUAR])
def test_a_source_in_ongoing_or_to_delete_is_refused(app, fake_archive, area):
    fake_archive.add(f"{area}/Sauna/x.pdf", drive_id="id-x")
    fake_archive.add(f"{BANKS}/ok.pdf", drive_id="id-ok")
    app.scan()
    assert_refused(app, fake_archive, ["id-ok", "id-x"], INBOX, area)


@pytest.mark.parametrize(
    "folder", [QUAR, f"{QUAR}/{BANKS}", ONG, f"{ONG}/Sauna", "##. ongoing/sauna", "##. TO DELETE"]
)
def test_a_destination_in_to_delete_or_ongoing_is_refused(app, fake_archive, two_files, folder):
    assert_refused(app, fake_archive, ["id-a"], folder, "cannot be moved into")


@pytest.mark.parametrize("folder", ["../outside", "/etc", f"{BANKS}/../../..", "a\0b"])
def test_a_destination_that_is_not_an_archive_rel_is_refused(app, fake_archive, two_files, folder):
    assert_refused(app, fake_archive, ["id-a"], folder, "not a folder in the archive")


def test_a_duplicated_id_is_refused(app, fake_archive, two_files):
    assert_refused(app, fake_archive, ["id-a", "id-b", "id-a"], TAXES, "more than once")


def test_no_files_is_refused(app, fake_archive, two_files):
    assert_refused(app, fake_archive, [], TAXES, "No files")


def test_an_unknown_or_missing_file_is_not_found(app, fake_archive, two_files):
    with pytest.raises(NotFound):
        app.browse.move_plan(["nope"], TAXES)
    os.remove(fake_archive.root / BANKS / "b.pdf")
    app.scan()
    with pytest.raises(NotFound):
        app.browse.move_preview(["id-a", "id-b"], TAXES)
    assert journal(app) == []


def test_the_executor_guards_still_apply(app, fake_archive, two_files):
    # a new top-level folder and the archive root are refused by the executor's guards
    from dam.ops.model import GuardError

    with pytest.raises(GuardError):
        app.browse.move_preview(["id-a"], "99. New top level")
    with pytest.raises(GuardError):
        app.browse.move_preview(["id-a"], "")
    with pytest.raises(GuardError):  # a file is not a folder
        app.browse.move_preview(["id-a"], f"{BANKS}/b.pdf")
    assert journal(app) == []


def test_a_symlinked_folder_in_the_destination_path_is_refused(app, fake_archive, two_files):
    from dam.ops.model import GuardError

    fake_archive.link("10. Financial/Linked", BANKS)
    fake_archive.link("10. Financial/ToOngoing", ONG)
    app.scan()
    for folder in ("10. Financial/Linked", "10. Financial/Linked/Sub", "10. Financial/ToOngoing"):
        with pytest.raises(GuardError, match="not a folder"):
            app.browse.move_preview(["id-a"], folder)
        with pytest.raises(GuardError, match="not a folder"):
            app.browse.move(["id-a"], folder)
    assert journal(app) == [] and (fake_archive.root / BANKS / "a.pdf").exists()


# --- a stale index: the disk is checked, not only the index -------------------------


def assert_stale_refused(app, fake_archive, match):
    for call in (app.browse.move_preview, app.browse.move):
        with pytest.raises(InvalidRequest, match=match):
            call(["id-b", "id-a"], TAXES)
    with pytest.raises(InvalidRequest, match=match):
        app.browse.move(["id-a"], TAXES, dry_run=True)
    assert journal(app) == []
    assert not (fake_archive.root / TAXES).exists()  # nothing moved, no folder made
    assert (fake_archive.root / BANKS / "b.pdf").exists()  # the valid file stayed too


def test_a_file_replaced_by_a_folder_since_the_scan_is_refused(app, fake_archive, two_files):
    os.remove(fake_archive.root / BANKS / "a.pdf")
    (fake_archive.root / BANKS / "a.pdf").mkdir()  # no scan: the index still says a file
    assert_stale_refused(app, fake_archive, "no longer the file 'id-a'")
    assert (fake_archive.root / BANKS / "a.pdf").is_dir()


def test_a_folder_carrying_the_same_drive_id_is_still_refused(app, fake_archive, two_files):
    import xattr

    from dam.index.driveid import DRIVE_ID_XATTR

    os.remove(fake_archive.root / BANKS / "a.pdf")
    (fake_archive.root / BANKS / "a.pdf").mkdir()
    xattr.setxattr(fake_archive.root / BANKS / "a.pdf", DRIVE_ID_XATTR, b"id-a")
    assert_stale_refused(app, fake_archive, "not a file on disk")


def test_a_file_replaced_by_another_file_since_the_scan_is_refused(app, fake_archive, two_files):
    os.remove(fake_archive.root / BANKS / "a.pdf")
    fake_archive.add(f"{BANKS}/a.pdf", b"someone else", drive_id="id-new")  # no scan
    assert_stale_refused(app, fake_archive, "no longer the file 'id-a'")
    assert (fake_archive.root / BANKS / "a.pdf").read_bytes() == b"someone else"


def test_a_swap_after_a_separate_preview_is_caught_by_move(app, fake_archive, two_files):
    # The check runs inside apply, on the resolved ops it then runs, so a file swapped
    # after a separate preview is still caught.
    app.browse.move_preview(["id-a"], TAXES)
    os.remove(fake_archive.root / BANKS / "a.pdf")
    fake_archive.add(f"{BANKS}/a.pdf", b"swapped", drive_id="id-new")
    with pytest.raises(InvalidRequest):
        app.browse.move(["id-a"], TAXES)
    assert journal(app) == [] and not (fake_archive.root / TAXES).exists()


def test_an_invalid_origin_is_refused(app, two_files):
    with pytest.raises(InvalidRequest):
        app.browse.move_plan(["id-a"], TAXES, origin="undo")


# --- Ongoing -------------------------------------------------------------------------


def test_a_moved_members_ongoing_link_follows_after_the_next_sync(app, fake_archive, two_files):
    c = app.collections.create("Sauna")
    app.collections.add_members(c.id, ["id-a", "id-b"])  # syncs Ongoing
    link = fake_archive.root / ONG / "Sauna" / "a.pdf"
    assert readlink(link) == str(fake_archive.root.resolve() / BANKS / "a.pdf")
    result = app.browse.move(["id-a"], TAXES)
    assert result.failed is None and result.error is None
    # members are tracked by drive id: the next scan (the watcher's) plus sync repoints it
    app.scan()
    app.sync_publishers()
    assert readlink(link) == str(fake_archive.root.resolve() / TAXES / "a.pdf")
    assert link.exists()
    assert sorted(os.listdir(fake_archive.root / ONG / "Sauna")) == ["a.pdf", "b.pdf"]


# --- API -----------------------------------------------------------------------------


@pytest.fixture
def client(app):
    with TestClient(create_api(app, None), base_url=BASE) as c:
        yield c


def post(client, url, body):
    return client.post(url, json=body, headers=LOCAL_ORIGIN)


def test_api_move_preview_and_move(client, app, fake_archive, two_files):
    r = post(client, "/api/browse/move/preview", {"drive_ids": ["id-a"], "folder": TAXES})
    assert r.status_code == 200, r.text
    assert [(o["kind"], o["dst"]) for o in r.json()] == [
        ("mkdir", TAXES),
        ("move", f"{TAXES}/a.pdf"),
    ]
    assert journal(app) == []
    r = post(client, "/api/browse/move", {"drive_ids": ["id-a", "id-b"], "folder": BANKS})
    assert r.status_code == 200 and r.json()["done"] == []
    assert r.json()["unchanged"] == ["id-a", "id-b"]
    r = post(client, "/api/browse/move", {"drive_ids": ["id-a"], "folder": TAXES})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["done"][-1]["dst"] == f"{TAXES}/a.pdf" and body["failed"] is None
    assert body["unchanged"] == []
    assert (fake_archive.root / TAXES / "a.pdf").exists()
    r = post(client, f"/api/activity/{body['batch_id']}/undo", {})
    assert r.status_code == 200, r.text
    assert (fake_archive.root / BANKS / "a.pdf").exists()


def test_api_move_refusals_are_400(client, app, fake_archive, two_files):
    for folder in (QUAR, ONG, "../x"):
        for url in ("/api/browse/move/preview", "/api/browse/move"):
            r = post(client, url, {"drive_ids": ["id-a"], "folder": folder})
            assert r.status_code == 400 and r.json()["error"], (url, folder, r.text)
    fake_archive.add(f"{ONG}/Sauna/x.pdf", drive_id="id-ong")
    fake_archive.add(f"{QUAR}/old.pdf", drive_id="id-quar")
    app.scan()
    folder_id = app.repo.by_path(BANKS).drive_id
    for drive_id in ("id-ong", "id-quar", folder_id):
        for url in ("/api/browse/move/preview", "/api/browse/move"):
            r = post(client, url, {"drive_ids": [drive_id], "folder": INBOX})
            assert r.status_code == 400 and r.json()["error"], (url, drive_id, r.text)
    r = post(client, "/api/browse/move", {"drive_ids": ["nope"], "folder": TAXES})
    assert r.status_code == 404
    r = post(client, "/api/browse/move", {"drive_ids": ["id-a"], "folder": TAXES, "x": 1})
    assert r.status_code == 422  # unknown fields are refused, as for every request body
    assert journal(app) == []


# --- CLI -----------------------------------------------------------------------------

runner = CliRunner()


@pytest.fixture
def run(app_paths):
    def _run(*args, input=None):
        return runner.invoke(cli, ["--data-dir", str(app_paths.data_dir), *args], input=input)

    return _run


def test_cli_move_dry_run_prints_the_plan(run, app, fake_archive, two_files):
    r = run("move", f"{BANKS}/a.pdf", "id-b", "--folder", TAXES, "--dry-run")
    assert r.exit_code == 0, r.output
    assert "mkdir" in r.stdout and f"{BANKS}/a.pdf -> {TAXES}/a.pdf" in r.stdout
    assert f"{BANKS}/b.pdf -> {TAXES}/b.pdf" in r.stdout
    assert "dry run: nothing was changed" in r.stdout
    assert journal(app) == [] and (fake_archive.root / BANKS / "a.pdf").exists()


def test_cli_move_asks_first_and_applies_with_yes(run, app, fake_archive, two_files):
    r = run("move", "id-a", "--folder", TAXES, input="n\n")
    assert r.exit_code == 1 and "aborted" in r.stderr
    assert journal(app) == [] and (fake_archive.root / BANKS / "a.pdf").exists()
    r = run("move", "id-a", "--folder", TAXES, input="y\n")
    assert r.exit_code == 0, r.output
    assert (fake_archive.root / TAXES / "a.pdf").exists()
    r = run("move", "id-b", "--folder", TAXES, "--yes")
    assert r.exit_code == 0, r.output
    assert "batch" in r.stdout
    assert app.repo.get("id-b").path == f"{TAXES}/b.pdf"
    assert {x["origin"] for x in journal(app)} == {"cli"}


def test_cli_move_collision_note_and_unchanged(run, app, fake_archive, two_files):
    fake_archive.add(f"{TAXES}/a.pdf", b"other", drive_id="id-t")
    run("scan")
    r = run("move", "id-a", "id-t", "--folder", TAXES, "--dry-run")
    assert r.exit_code == 0, r.output
    assert f"{TAXES}/a_2.pdf  ({COLLISION_NOTE})" in r.stdout
    assert f"already in {TAXES}: {TAXES}/a.pdf" in r.stdout
    r = run("move", "id-t", "--folder", "10. Financial//Taxes/.", "--dry-run")
    assert r.exit_code == 0, r.output
    assert f"already in {TAXES}: {TAXES}/a.pdf" in r.stdout  # the canonical rel


def test_cli_move_refusals_exit_1(run, app, fake_archive, two_files):
    r = run("move", "id-a", "--folder", QUAR, "--yes")
    assert r.exit_code == 1 and r.stderr.startswith("error:") and "Traceback" not in r.output
    r = run("move", "nope", "--folder", TAXES, "--yes")
    assert r.exit_code == 1 and r.stderr.startswith("error:")
    r = run("move", "id-a", "--folder", "99. New", "--yes")  # a guard refusal
    assert r.exit_code == 1 and r.stderr.startswith("error:")
    r = run("move", "id-a")  # --folder is required: a usage error
    assert r.exit_code == 2
    assert journal(app) == []


# --- files without a Drive id (``local:`` ids) ---------------------------------------


def local_id(app, rel):
    rec = app.repo.by_path(rel)
    assert rec.drive_id.startswith("local:")
    return rec.drive_id


def test_moving_a_file_without_a_drive_id_works(app, fake_archive):
    fake_archive.add(f"{BANKS}/new.pdf", b"not uploaded yet", drive_id=None)
    app.scan()
    drive_id = local_id(app, f"{BANKS}/new.pdf")
    assert [op.dst for op in app.browse.move_preview([drive_id], TAXES)][-1] == f"{TAXES}/new.pdf"
    result = app.browse.move([drive_id], TAXES)
    assert result.failed is None and result.error is None, result.error
    assert (fake_archive.root / TAXES / "new.pdf").read_bytes() == b"not uploaded yet"
    assert app.repo.get(drive_id).path == f"{TAXES}/new.pdf"


def test_a_local_file_replaced_by_one_with_a_drive_id_is_refused(app, fake_archive):
    fake_archive.add(f"{BANKS}/new.pdf", b"mine", drive_id=None)
    app.scan()
    drive_id = local_id(app, f"{BANKS}/new.pdf")
    os.remove(fake_archive.root / BANKS / "new.pdf")
    fake_archive.add(f"{BANKS}/new.pdf", b"mine", drive_id="id-real")  # no scan
    for call in (app.browse.move_preview, app.browse.move):
        with pytest.raises(InvalidRequest, match="now has Drive id 'id-real'"):
            call([drive_id], TAXES)
    assert journal(app) == [] and not (fake_archive.root / TAXES).exists()


def test_a_local_file_whose_size_changed_is_refused(app, fake_archive):
    fake_archive.add(f"{BANKS}/new.pdf", b"mine", drive_id=None)
    app.scan()
    drive_id = local_id(app, f"{BANKS}/new.pdf")
    (fake_archive.root / BANKS / "new.pdf").write_bytes(b"something longer")  # no scan
    with pytest.raises(InvalidRequest, match="has changed since the last scan"):
        app.browse.move([drive_id], TAXES)
    assert journal(app) == [] and not (fake_archive.root / TAXES).exists()


def test_a_local_file_replaced_by_a_folder_is_refused(app, fake_archive):
    fake_archive.add(f"{BANKS}/new.pdf", b"mine", drive_id=None)
    app.scan()
    drive_id = local_id(app, f"{BANKS}/new.pdf")
    os.remove(fake_archive.root / BANKS / "new.pdf")
    (fake_archive.root / BANKS / "new.pdf").mkdir()
    with pytest.raises(InvalidRequest, match="not a file on disk"):
        app.browse.move([drive_id], TAXES)
    assert journal(app) == []
