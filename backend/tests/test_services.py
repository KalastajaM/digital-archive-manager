import os
from pathlib import Path

import pytest
import yaml
from sqlalchemy import func, select

from conftest import posix_permissions
from dam.app import App
from dam.db.tables import collection_members, files, notes, operations
from dam.extract.base import ExtractedText
from dam.index.scanner import scan
from dam.ops.executor import Executor
from dam.ops.model import BatchResult, GuardError, OpKind
from dam.services.errors import InvalidRequest
from dam.services.inbox import FileRequest

INBOX = "##. Organize"
BANKS = "10. Financial/Banks"


def batches(app: App) -> set[str]:
    with app.engine.connect() as conn:
        return set(conn.execute(select(operations.c.batch_id)).scalars())


def test_app_create_wires_settings(app, fake_archive):
    assert app.paths.root == fake_archive.root.resolve()
    assert app.settings.archive_root == fake_archive.root
    assert app.repo.inbox == INBOX
    assert app.executor.throttle_ms == app.settings.ops_throttle_ms
    assert app.content.reads_per_minute == app.settings.indexer_reads_per_minute
    assert app.rule_errors == []


def test_reload_rules_refreshes_rules_and_errors(app):
    rules_dir = app.app_paths.config_dir / "rules"
    (rules_dir / "50-bad.yaml").write_text("- id: ''\n", encoding="utf-8")
    (rules_dir / "60-bank.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "id": "bank",
                    "when": {"text_contains": ["iban"]},
                    "then": {"folder": BANKS, "tags": ["bank"]},
                }
            ]
        ),
        encoding="utf-8",
    )
    errors = app.reload_rules()
    assert [e.file for e in errors] == ["50-bad.yaml"]
    assert app.rule_errors == errors
    assert "bank" in [r.id for r in app.rules]


def test_inbox_lists_only_inbox_files(app, fake_archive):
    old = fake_archive.add(f"{INBOX}/old.pdf")
    new = fake_archive.add(f"{INBOX}/new.pdf")
    os.utime(old, (1_000_000, 1_000_000))
    os.utime(new, (2_000_000, 2_000_000))
    fake_archive.add(f"{INBOX}/Photos/p.jpg")
    fake_archive.add(f"{BANKS}/elsewhere.pdf")
    fake_archive.link(f"{INBOX}/link.pdf", f"{BANKS}/elsewhere.pdf")
    scan(app.paths, app.repo)
    entries = app.inbox.list()
    assert [e.record.name for e in entries] == ["new.pdf", "old.pdf"]
    assert all(e.suggestion.name for e in entries)


def test_inbox_entry_text_excerpt_and_suggestion_use_text(app, fake_archive):
    fake_archive.add(f"{INBOX}/scan.pdf", drive_id="id-t")
    scan(app.paths, app.repo)
    app.repo.save_content("id-t", None, ExtractedText("x" * 600 + " 13.10.2026", "test"), "indexed")
    assert app.repo.text_for("id-t").startswith("x")
    assert app.repo.text_for("nope") == ""
    [entry] = app.inbox.list()
    assert entry.text_excerpt == "x" * 500
    assert app.inbox.suggestion("id-t").doc_date.isoformat() == "2026-10-13"
    with pytest.raises(KeyError):
        app.inbox.suggestion("nope")


def test_file_it_renames_moves_tags(app, fake_archive):
    fake_archive.add(f"{INBOX}/File_000.pdf", drive_id="id-1")
    scan(app.paths, app.repo)
    req = FileRequest("id-1", "20261013_Statement.pdf", BANKS, tags=["bank", "2026"])
    plan = app.inbox.build_plan([req])
    assert [(op.kind, op.name) for op in plan.ops] == [(OpKind.MOVE, "20261013_Statement.pdf")]
    assert plan.origin == "ui"
    result = app.inbox.file_it([req], origin="cli").batch
    assert result.failed is None and result.error is None and result.index_error is None
    target = fake_archive.root / BANKS / "20261013_Statement.pdf"
    assert target.exists()
    assert not (fake_archive.root / INBOX / "File_000.pdf").exists()
    assert app.repo.get("id-1").path == f"{BANKS}/20261013_Statement.pdf"
    assert app.tags.for_file("id-1") == ["2026", "bank"]
    assert batches(app) == {result.batch_id}
    assert app.inbox.list() == []


def test_build_plan_rename_only_and_noop(app, fake_archive):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-a")
    fake_archive.add(f"{INBOX}/b.pdf", drive_id="id-b")
    scan(app.paths, app.repo)
    plan = app.inbox.build_plan(
        [FileRequest("id-a", "c.pdf", INBOX), FileRequest("id-b", "b.pdf", INBOX)], origin="cli"
    )
    assert [(op.kind, op.src, op.dst) for op in plan.ops] == [
        (OpKind.RENAME, f"{INBOX}/a.pdf", "c.pdf")
    ]
    assert plan.origin == "cli"


def test_build_plan_validation(app, fake_archive):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-a")
    scan(app.paths, app.repo)
    with pytest.raises(KeyError):
        app.inbox.build_plan([FileRequest("nope", "a.pdf", BANKS)])
    for bad in ("", "x/y.pdf"):
        with pytest.raises(ValueError):
            app.inbox.build_plan([FileRequest("id-a", bad, BANKS)])
    # ".DS_\u017ftore" (long s) casefolds to ".ds_store"; NFD of ASCII is itself
    for bad in (".DS_Store", ".ds_store", ".DS_STORE", ".DS_\u017ftore"):
        with pytest.raises(InvalidRequest, match="DS_Store"):
            app.inbox.build_plan([FileRequest("id-a", bad, "##. Ongoing/Tax")])
    assert (fake_archive.root / INBOX / "a.pdf").exists()
    for bad in ("/abs", "../out"):
        with pytest.raises(ValueError):
            app.inbox.build_plan([FileRequest("id-a", "a.pdf", bad)])
    for origin in ("undo", "web"):
        with pytest.raises(ValueError):
            app.inbox.build_plan([FileRequest("id-a", "a.pdf", BANKS)], origin=origin)


def test_preview_and_dry_run_change_nothing(app, fake_archive):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-a")
    scan(app.paths, app.repo)
    reqs = [FileRequest("id-a", "b.pdf", BANKS, tags=["t"])]
    assert [r.dst for r in app.inbox.preview(reqs)] == [f"{BANKS}/b.pdf"]
    outcome = app.inbox.file_it(reqs, dry_run=True)
    result = outcome.batch
    assert outcome.tag_error is None and outcome.untagged == []
    assert result.dry_run and [r.dst for r in result.done] == [f"{BANKS}/b.pdf"]
    assert (fake_archive.root / INBOX / "a.pdf").exists()
    assert app.tags.for_file("id-a") == []
    assert batches(app) == set()


def test_file_it_batch_two_files_same_name(app, fake_archive):
    fake_archive.add(f"{INBOX}/a.pdf", content=b"a", drive_id="id-a")
    fake_archive.add(f"{INBOX}/b.pdf", content=b"b", drive_id="id-b")
    scan(app.paths, app.repo)
    reqs = [FileRequest("id-a", "same.pdf", BANKS), FileRequest("id-b", "same.pdf", BANKS)]
    result = app.inbox.file_it(reqs).batch
    assert result.failed is None and result.error is None
    assert (fake_archive.root / BANKS / "same.pdf").read_bytes() == b"a"
    assert (fake_archive.root / BANKS / "same_2.pdf").read_bytes() == b"b"


def test_file_it_failure_tags_only_done(app, fake_archive, monkeypatch):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-a")
    fake_archive.add(f"{INBOX}/b.pdf", drive_id="id-b")
    scan(app.paths, app.repo)
    reqs = [
        FileRequest("id-a", "a.pdf", BANKS, tags=["ta"]),
        FileRequest("id-b", "b.pdf", BANKS, tags=["tb"]),
    ]
    app.executor.throttle_ms = 0
    resolved = app.inbox.preview(reqs)
    # Something appears at the 2nd op's destination after preview: never overwrite.
    fake_archive.add(f"{BANKS}/b.pdf", content=b"blocker")
    monkeypatch.setattr(Executor, "preview", lambda self, plan: resolved)
    result = app.inbox.file_it(reqs).batch
    assert result.failed is not None and result.failed.src == f"{INBOX}/b.pdf"
    assert app.tags.for_file("id-a") == ["ta"]
    assert app.tags.for_file("id-b") == []


def test_folders_excludes_quarantine_and_inbox(app, fake_archive):
    fake_archive.add(f"{INBOX}/Photos/p.jpg")
    fake_archive.add("##. To Delete/10. Financial/x.pdf")
    fake_archive.add("20. Home/ä/x.pdf")
    scan(app.paths, app.repo)
    folders = app.browse.folders()
    assert "##. Ongoing" in folders
    assert "10. Financial" in folders and BANKS in folders
    assert "20. Home/ä" in folders
    assert not any(f.startswith(("##. Organize", "##. To Delete")) for f in folders)
    assert folders == sorted(folders, key=lambda s: s.casefold())


def test_list_dir_dirs_first(app, fake_archive):
    fake_archive.add("10. Financial/a.pdf", drive_id="id-a")
    fake_archive.add("10. Financial/Z/b.pdf")
    scan(app.paths, app.repo)
    entries = app.browse.list_dir("10. Financial")
    assert [(e.name, e.is_dir) for e in entries] == [("Banks", True), ("Z", True), ("a.pdf", False)]
    assert entries[2].drive_id == "id-a" and entries[2].path == "10. Financial/a.pdf"
    assert entries[2].size == 1


def test_quarantine_via_browse(app, fake_archive):
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="id-q")
    scan(app.paths, app.repo)
    dry = app.browse.quarantine(["id-q"], origin="ui", dry_run=True)
    assert dry.dry_run and (fake_archive.root / BANKS / "a.pdf").exists()
    result = app.browse.quarantine(["id-q"], origin="ui")
    assert result.failed is None and result.error is None
    assert (fake_archive.root / "##. To Delete" / BANKS / "a.pdf").exists()
    assert result.done[-1].kind is OpKind.QUARANTINE
    with pytest.raises(KeyError):
        app.browse.quarantine(["nope"], origin="ui")
    with pytest.raises(ValueError):
        app.browse.quarantine(["id-q"], origin="undo")


def test_activity_undo_roundtrip(app, fake_archive):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-a")
    scan(app.paths, app.repo)
    result = app.inbox.file_it([FileRequest("id-a", "b.pdf", BANKS)]).batch
    [summary] = app.activity.recent()
    assert summary.batch_id == result.batch_id
    assert summary.origin == "ui" and not summary.undone and not summary.is_undo
    assert [op.kind for op in summary.ops] == [OpKind.MOVE]
    undo = app.activity.undo(result.batch_id).batch
    assert undo.failed is None and undo.error is None
    assert (fake_archive.root / INBOX / "a.pdf").exists()
    assert not (fake_archive.root / BANKS / "b.pdf").exists()
    newest, original = app.activity.recent()
    assert newest.batch_id == undo.batch_id and newest.is_undo
    assert original.batch_id == result.batch_id and original.undone
    assert len(app.activity.recent(limit=1)) == 1
    assert app.activity.pending() == []
    recovered = app.activity.recover()
    assert recovered.entries == [] and recovered.index_errors == []


def test_app_create_default_data_dir_from_env(app_paths, monkeypatch):
    monkeypatch.setenv("DAM_DATA_DIR", str(app_paths.data_dir))
    app = App.create()
    try:
        assert app.app_paths.data_dir == Path(app_paths.data_dir)
    finally:
        app.close()


@pytest.mark.parametrize("folder", [f"{BANKS}/", "10. financial/banks", f"./{BANKS}"])
def test_same_folder_spellings_are_not_moves(app, fake_archive, folder):
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="id-a")
    fake_archive.add(f"{BANKS}/b.pdf", drive_id="id-b")
    scan(app.paths, app.repo)
    plan = app.inbox.build_plan(
        [FileRequest("id-a", "a.pdf", folder), FileRequest("id-b", "c.pdf", folder)]
    )
    assert [(op.kind, op.src, op.dst) for op in plan.ops] == [
        (OpKind.RENAME, f"{BANKS}/b.pdf", "c.pdf")
    ]


def test_case_only_folder_difference_still_tags_done_files(app, fake_archive, monkeypatch):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-a")
    scan(app.paths, app.repo)
    real = Executor.apply

    def apply_with_disk_case(self, plan, dry_run=False, check=None):
        result = real(self, plan, dry_run, check)
        for r in result.done:
            r.src = r.src.upper()  # a disk spelling that differs only by case
        return result

    monkeypatch.setattr(Executor, "apply", apply_with_disk_case)
    app.inbox.file_it([FileRequest("id-a", "a.pdf", BANKS, tags=["t"])])
    assert app.tags.for_file("id-a") == ["t"]


def test_file_it_tag_failure_is_per_file_and_keeps_batch_id(app, fake_archive, monkeypatch):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-a")
    fake_archive.add(f"{INBOX}/b.pdf", drive_id="id-b")
    scan(app.paths, app.repo)
    real = app.tags.add

    def flaky(drive_id, names):
        if drive_id == "id-a":
            raise RuntimeError("db locked")
        real(drive_id, names)

    monkeypatch.setattr(app.tags, "add", flaky)
    reqs = [
        FileRequest("id-a", "a.pdf", BANKS, tags=["t"]),
        FileRequest("id-b", "b.pdf", BANKS, tags=["u"]),
    ]
    outcome = app.inbox.file_it(reqs)
    assert outcome.batch.batch_id in batches(app)
    assert outcome.batch.index_error is None and outcome.batch.failed is None
    assert "db locked" in outcome.tag_error
    assert outcome.untagged == ["id-a"]
    assert app.tags.for_file("id-b") == ["u"]  # the other file was still tagged
    assert (fake_archive.root / BANKS / "a.pdf").exists()


def test_tags_are_normalised(app, fake_archive, monkeypatch):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-a")
    scan(app.paths, app.repo)
    reqs = [FileRequest("id-a", "a.pdf", BANKS, tags=[" bank ", "", "  ", "Bank", "bank", "x"])]
    calls = []
    real = app.tags.add
    monkeypatch.setattr(app.tags, "add", lambda d, names: (calls.append(names), real(d, names)))
    app.inbox.file_it(reqs)
    assert calls == [["bank", "Bank", "x"]]  # in order, deduped, case kept
    assert app.tags.for_file("id-a") == ["Bank", "bank", "x"]


def test_tags_in_collision_case(app, fake_archive):
    fake_archive.add(f"{INBOX}/a.pdf", content=b"a", drive_id="id-a")
    fake_archive.add(f"{INBOX}/b.pdf", content=b"b", drive_id="id-b")
    scan(app.paths, app.repo)
    reqs = [
        FileRequest("id-a", "same.pdf", BANKS, tags=["ta"]),
        FileRequest("id-b", "same.pdf", BANKS, tags=["tb"]),
    ]
    app.inbox.file_it(reqs)
    assert (fake_archive.root / BANKS / "same_2.pdf").read_bytes() == b"b"
    assert app.tags.for_file("id-a") == ["ta"]
    assert app.tags.for_file("id-b") == ["tb"]


def test_noop_tagging_through_file_it(app, fake_archive):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-a")
    scan(app.paths, app.repo)
    result = app.inbox.file_it([FileRequest("id-a", "a.pdf", INBOX, tags=["t"])]).batch
    assert result.done == [] and result.failed is None
    assert app.tags.for_file("id-a") == ["t"]


def test_origin_cli_is_journaled(app, fake_archive):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-a")
    scan(app.paths, app.repo)
    result = app.inbox.file_it([FileRequest("id-a", "a.pdf", BANKS)], origin="cli").batch
    with app.engine.connect() as conn:
        origins = set(
            conn.execute(
                select(operations.c.origin).where(operations.c.batch_id == result.batch_id)
            ).scalars()
        )
    assert origins == {"cli"}


def test_inbox_list_excludes_missing_and_parked(app, fake_archive):
    fake_archive.add(f"{INBOX}/keep.pdf", drive_id="id-k")
    gone = fake_archive.add(f"{INBOX}/gone.pdf", drive_id="id-g")
    fake_archive.add(f"{INBOX}/parked.pdf", drive_id="id-p")
    scan(app.paths, app.repo)
    gone.unlink()
    scan(app.paths, app.repo)
    app.repo.park(f"{INBOX}/parked.pdf")
    assert app.repo.get("id-g").missing and app.repo.get("id-p").parked_at is not None
    assert [e.record.name for e in app.inbox.list()] == ["keep.pdf"]


def test_app_scan_and_index(app, fake_archive):
    for i in range(3):
        fake_archive.add(f"{BANKS}/f{i}.txt", content=b"hello", drive_id=f"id-{i}")
    report = app.scan()
    assert report.added >= 3
    assert app.scan(BANKS).added == 0
    assert app.index(limit=2) == 2
    assert app.index() >= 1
    assert app.index() == 0


def test_service_errors_are_typed(app, fake_archive):
    from dam.services.errors import InvalidRequest, NotFound

    with pytest.raises(NotFound):
        app.inbox.suggestion("nope")
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-a")
    scan(app.paths, app.repo)
    with pytest.raises(InvalidRequest):
        app.inbox.build_plan(
            [FileRequest("id-a", "x.pdf", BANKS), FileRequest("id-a", "y.pdf", BANKS)]
        )
    with pytest.raises(InvalidRequest):
        app.browse.quarantine([], origin="web")
    with pytest.raises(NotFound):
        app.activity.get("nope")


def test_browse_resolve(app, fake_archive, tmp_path, monkeypatch):
    from dam.core.paths import OutsideArchiveError
    from dam.services.errors import NotFound

    path = fake_archive.add(f"{BANKS}/a.pdf", drive_id="id-a")
    fake_archive.add(f"{BANKS}/gone.pdf", drive_id="id-g")
    scan(app.paths, app.repo)
    (fake_archive.root / BANKS / "gone.pdf").unlink()
    scan(app.paths, app.repo)
    assert app.browse.resolve("id-a").drive_id == "id-a"
    assert app.browse.resolve(str(path)).drive_id == "id-a"
    assert app.browse.resolve(f"{BANKS}/a.pdf").drive_id == "id-a"
    for bad in ("nope", f"{BANKS}/gone.pdf", "id-g"):
        with pytest.raises(NotFound):
            app.browse.resolve(bad)
    with pytest.raises(OutsideArchiveError):
        app.browse.resolve("../x")
    # relative paths are archive-relative, never cwd-relative
    other = tmp_path / "cwd"
    (other / "10. Financial" / "Banks").mkdir(parents=True)
    (other / BANKS / "a.pdf").write_bytes(b"x")
    monkeypatch.chdir(other)
    assert app.browse.resolve(f"{BANKS}/a.pdf").drive_id == "id-a"


def test_index_terminates_when_files_keep_failing(app, fake_archive, monkeypatch):
    for i in range(3):
        fake_archive.add(f"{BANKS}/f{i}.txt", drive_id=f"id-{i}")
    app.scan()
    calls = []

    def always_busy(limit=20, now=None):
        calls.append(limit)
        return limit  # a pathological indexer that never runs out of work

    monkeypatch.setattr(app.content, "run_once", always_busy)
    with app.engine.connect() as conn:
        rows = conn.execute(select(func.count()).select_from(files)).scalar_one()
    assert app.index() == rows  # hard cap: the number of rows


def test_index_does_not_repick_cloud_pending_files(app, fake_archive, monkeypatch):
    import time

    fake_archive.add(f"{BANKS}/f.txt", drive_id="id-1")
    app.scan()

    def defer(rec, path, now):
        app.repo.set_index_state(rec.drive_id, "cloud_pending", retry_at=time.time() + 3600)

    monkeypatch.setattr(app.content, "_process", defer)
    assert app.index() == 1
    assert app.index() == 0


def test_quarantine_via_browse_when_quarantine_folder_absent(app, fake_archive):
    (fake_archive.root / "##. To Delete").rmdir()
    fake_archive.add(f"{BANKS}/q.pdf", drive_id="id-q")
    app.scan()
    result = app.browse.quarantine(["id-q"], origin="ui")
    assert result.failed is None and result.error is None
    assert (fake_archive.root / "##. To Delete" / BANKS / "q.pdf").exists()


@pytest.mark.parametrize("kind", ["absent", "file"])
def test_app_create_refuses_unavailable_archive_root(tmp_path, kind):
    from dam.config import AppPaths
    from dam.services.errors import ArchiveUnavailable, InvalidRequest

    root = tmp_path / "no-archive"
    if kind == "file":
        root.write_text("not a folder", encoding="utf-8")
    paths = AppPaths(tmp_path / "data")
    paths.ensure()
    (paths.config_dir / "settings.yaml").write_text(
        yaml.safe_dump({"archive_root": str(root)}), encoding="utf-8"
    )
    with pytest.raises(ArchiveUnavailable) as exc:
        App.create(paths.data_dir)
    assert isinstance(exc.value, InvalidRequest)
    message = str(exc.value)
    assert str(root) in message and "Google Drive" in message and "settings.yaml" in message


@posix_permissions
@pytest.mark.skipif(getattr(os, "geteuid", lambda: -1)() == 0, reason="root can list mode-000 dirs")
def test_archive_available_false_when_not_listable(app, fake_archive):
    assert app.archive_available is True
    os.chmod(fake_archive.root, 0o000)
    try:
        assert app.archive_available is False
    finally:
        os.chmod(fake_archive.root, 0o755)


# --- Phase 2: filing into trays, collections and notes --------------------------------

NORTHPOWER_BILL = (
    "Northpower Oy lasku\nEräpäivä 15.11.2026\nYhteensä 84,20 €\n"
    "IBAN FI21 1234 5600 0007 85\nViitenumero RF18 5390 0754 7034"
)
OTHER_BILL = "Lasku\nEräpäivä 01.12.2026\nYhteensä 12,00 €"


def add_scan(app, fake_archive, name, drive_id, text):
    fake_archive.add(f"{INBOX}/{name}", content=drive_id.encode(), drive_id=drive_id)
    scan(app.paths, app.repo)
    app.repo.save_content(drive_id, None, ExtractedText(text, "test"), "indexed")


def test_inbox_entry_prefill_has_found_fields_only(app, fake_archive):
    add_scan(app, fake_archive, "a.pdf", "id-a", OTHER_BILL)
    [entry] = app.inbox.list()
    assert entry.prefill == {"due_date": "2026-12-01", "total": "12.00"}


def test_file_into_to_pay_creates_item_with_fields(app, fake_archive):
    add_scan(app, fake_archive, "File_000.pdf", "id-1", NORTHPOWER_BILL)
    req = FileRequest("id-1", "20261001_Northpower_Sahko.pdf", BANKS, tray="to-pay")
    outcome = app.inbox.file_it([req])
    assert outcome.batch.failed is None and outcome.follow_up_error is None
    [item] = app.trays.list("to-pay")
    assert outcome.items == [item.id]
    assert item.title == "Northpower Sahko"
    assert item.files == ["id-1"]
    assert item.created_by_batch == outcome.batch.batch_id
    assert {k: str(v) for k, v in item.fields.items()} == {
        "due_date": "2026-11-15",
        "amount": "84.20",
        "iban": "FI2112345600000785",
        "reference": "RF18539007547034",
    }
    assert item.missing_required == []


def test_explicit_tray_fields_win_and_blank_clears_prefill(app, fake_archive):
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    req = FileRequest(
        "id-a", "a.pdf", BANKS, tray="to-pay", tray_fields={"amount": "90,00", "iban": ""}
    )
    app.inbox.file_it([req])
    [item] = app.trays.list("to-pay")
    assert str(item.fields["amount"]) == "90.00"
    assert "iban" not in item.fields
    assert str(item.fields["due_date"]) == "2026-11-15"


def test_batch_into_tray_one_item_per_file_prefilled_per_file(app, fake_archive):
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    add_scan(app, fake_archive, "b.pdf", "id-b", OTHER_BILL)
    add_scan(app, fake_archive, "c.pdf", "id-c", "no fields here")
    reqs = [
        FileRequest("id-a", "20261001_Northpower.pdf", BANKS, tray="to-pay"),
        FileRequest("id-b", "20261002_Other.pdf", BANKS, tray="to-pay"),
        FileRequest("id-c", "20261003_Blank.pdf", BANKS, tray="to-pay"),
    ]
    outcome = app.inbox.file_it(reqs)
    assert len(outcome.items) == 3
    by_file = {i.files[0]: i for i in app.trays.list("to-pay")}
    assert len(by_file) == 3
    assert str(by_file["id-a"].fields["amount"]) == "84.20"
    assert str(by_file["id-b"].fields["amount"]) == "12.00"
    assert str(by_file["id-b"].fields["due_date"]) == "2026-12-01"
    assert by_file["id-c"].fields == {} and by_file["id-c"].missing_required == ["due_date"]


def test_failed_file_gets_no_item(app, fake_archive, monkeypatch):
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    add_scan(app, fake_archive, "b.pdf", "id-b", OTHER_BILL)
    reqs = [
        FileRequest("id-a", "a.pdf", BANKS, tray="to-pay", collections=["Sauna"], note="n"),
        FileRequest("id-b", "b.pdf", BANKS, tray="to-pay", collections=["Sauna"], note="n"),
    ]
    app.executor.throttle_ms = 0
    resolved = app.inbox.preview(reqs)
    fake_archive.add(f"{BANKS}/b.pdf", content=b"blocker")  # stale preview: 2nd op fails
    monkeypatch.setattr(Executor, "preview", lambda self, plan: resolved)
    outcome = app.inbox.file_it(reqs)
    assert outcome.batch.failed is not None and outcome.batch.failed.src == f"{INBOX}/b.pdf"
    [item] = app.trays.list("to-pay")
    assert item.files == ["id-a"] and outcome.items == [item.id]
    assert [m.drive_id for m in app.collections.by_name("sauna").members] == ["id-a"]
    assert app.notes.get("item", str(item.id)) == "n"
    assert app.notes.get("file", "id-a") == "" and app.notes.get("file", "id-b") == ""


def test_undo_removes_created_items_memberships_note(app, fake_archive):
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    existing = app.collections.create("Sauna")
    req = FileRequest(
        "id-a", "b.pdf", BANKS, tray="to-pay", collections=["sauna", "Remont"], note=" paid? "
    )
    outcome = app.inbox.file_it([req])
    assert outcome.follow_up_error is None
    [item_id] = outcome.items
    assert app.notes.get("item", str(item_id)) == "paid?"
    assert app.notes.get("file", "id-a") == ""
    assert [c.name for c in app.collections.for_file("id-a")] == ["Remont", "Sauna"]
    assert app.collections.by_name("Sauna").id == existing.id  # reused, case-insensitively
    undo = app.activity.undo(outcome.batch.batch_id)
    assert undo.batch.failed is None and undo.batch.error is None
    assert undo.follow_up_error is None
    assert app.trays.list("to-pay") == []
    assert app.collections.for_file("id-a") == []
    assert app.notes.get("item", str(item_id)) == ""
    # collections themselves stay (see CollectionService.remove_created_by)
    assert {c.name for c in app.collections.list()} == {"Remont", "Sauna"}


def test_failed_undo_keeps_follow_ups(app, fake_archive, monkeypatch):
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    outcome = app.inbox.file_it([FileRequest("id-a", "b.pdf", BANKS, tray="to-pay", note="x")])
    batch_id = outcome.batch.batch_id
    [item_id] = outcome.items
    # refused before anything moved
    fake_archive.add(f"{INBOX}/a.pdf", content=b"occupies the origin")
    with pytest.raises(GuardError):
        app.activity.undo(batch_id)
    # stopped partway
    partial = BatchResult(batch_id="u", dry_run=False, error="OSError: gone")
    monkeypatch.setattr(app.executor, "undo", lambda b: partial)
    undo = app.activity.undo(batch_id)
    assert undo.batch is partial and undo.follow_up_error is None
    assert len(app.trays.list("to-pay")) == 1
    assert app.notes.get("item", str(item_id)) == "x"


def test_dry_run_creates_nothing(app, fake_archive):
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    req = FileRequest("id-a", "b.pdf", BANKS, tray="to-pay", collections=["Sauna"], note="n")
    outcome = app.inbox.file_it([req], dry_run=True)
    assert outcome.items == [] and outcome.follow_up_error is None
    assert app.trays.list("to-pay") == []
    assert app.collections.list() == []
    assert app.notes.get("file", "id-a") == ""
    assert app.notes.get("item", "1") == ""


INVALID_FOLLOW_UPS = [
    {"tray": "nope"},
    {"tray": "to-pay", "tray_fields": {"colour": "red"}},
    {"tray": "to-pay", "tray_fields": {"due_date": "15.11.2026"}},
    {"tray": "to-pay", "tray_fields": {"amount": "lots"}},
    {"tray_fields": {"due_date": "2026-11-15"}},
    {"collections": ["a/b"]},
    {"collections": [""]},
    {"note": "x" * 10_001},
]


def test_preview_refuses_an_invalid_amount_and_journals_nothing(app, fake_archive):
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    req = FileRequest("id-a", "a.pdf", BANKS, tray="to-pay", tray_fields={"amount": "abc"})
    with pytest.raises(InvalidRequest, match="amount"):
        app.inbox.preview([req])
    with app.engine.connect() as conn:
        assert conn.execute(select(operations.c.id)).first() is None
    assert (fake_archive.root / INBOX / "a.pdf").exists()


@pytest.mark.parametrize("extra", INVALID_FOLLOW_UPS)
def test_preview_validates_follow_ups_like_file_it(app, fake_archive, extra):
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    with pytest.raises(InvalidRequest):
        app.inbox.preview([FileRequest("id-a", "b.pdf", BANKS, **extra)])
    assert batches(app) == set()
    assert app.collections.list() == []


@pytest.mark.parametrize("extra", INVALID_FOLLOW_UPS)
def test_invalid_follow_up_is_invalid_request_before_any_move(app, fake_archive, extra):
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    add_scan(app, fake_archive, "b.pdf", "id-b", NORTHPOWER_BILL)
    reqs = [FileRequest("id-a", "a.pdf", BANKS), FileRequest("id-b", "b.pdf", BANKS, **extra)]
    with pytest.raises(InvalidRequest):
        app.inbox.file_it(reqs)
    assert (fake_archive.root / INBOX / "a.pdf").exists()
    assert (fake_archive.root / INBOX / "b.pdf").exists()
    assert batches(app) == set()
    assert app.collections.list() == []


def test_unknown_tray_is_invalid_request_before_any_move(app, fake_archive):
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    with pytest.raises(InvalidRequest, match="nope"):
        app.inbox.file_it([FileRequest("id-a", "b.pdf", BANKS, tray="nope")])
    assert (fake_archive.root / INBOX / "a.pdf").exists()
    assert batches(app) == set()


def test_collection_created_by_name_when_new(app, fake_archive):
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    outcome = app.inbox.file_it([FileRequest("id-a", "b.pdf", BANKS, collections=[" Sauna "])])
    assert outcome.follow_up_error is None and outcome.items == []
    coll = app.collections.by_name("Sauna")
    assert coll is not None and coll.name == "Sauna"
    assert [m.drive_id for m in coll.members] == ["id-a"]


def test_noop_filing_creates_follow_ups_without_batch(app, fake_archive):
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    outcome = app.inbox.file_it(
        [FileRequest("id-a", "a.pdf", INBOX, tray="to-pay", collections=["Sauna"], note="n")]
    )
    assert outcome.batch.done == []
    # the only journal rows are the Ongoing sync publishing the new collection
    with app.engine.connect() as conn:
        assert set(conn.execute(select(operations.c.origin)).scalars()) == {"workflow"}
    [item] = app.trays.list("to-pay")
    assert item.created_by_batch is None
    assert app.collections.for_file("id-a")[0].name == "Sauna"
    assert app.notes.get("item", str(item.id)) == "n"


def test_follow_up_failure_is_reported_and_files_stay_filed(app, fake_archive, monkeypatch):
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(app.trays, "create", boom)
    outcome = app.inbox.file_it(
        [FileRequest("id-a", "b.pdf", BANKS, tray="to-pay", collections=["Sauna"], note="n")]
    )
    assert outcome.batch.failed is None
    assert outcome.follow_up_error == "RuntimeError: db down"
    assert outcome.items == []
    assert (fake_archive.root / BANKS / "b.pdf").exists()
    # the memberships still ran; the note (meant for the item) is skipped, not moved
    assert app.collections.for_file("id-a")[0].name == "Sauna"
    assert app.notes.get("file", "id-a") == ""


def test_app_wires_trays_collections_notes(app):
    assert [t.id for t in app.tray_defs] == ["to-pay", "to-action", "to-read", "follow-up"]
    assert app.tray_errors == []
    assert app.publishers.all() == [app.ongoing]
    trays_dir = app.app_paths.config_dir / "trays"
    (trays_dir / "99-bad.yaml").write_text("id: ''\n", encoding="utf-8")
    app.reload_rules()
    assert [e.file for e in app.tray_errors] == ["99-bad.yaml"]
    assert [t.id for t in app.tray_defs] == ["to-pay", "to-action", "to-read", "follow-up"]


def test_note_without_tray_goes_on_the_file(app, fake_archive):
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    outcome = app.inbox.file_it([FileRequest("id-a", "b.pdf", BANKS, note=" see Northpower ")])
    assert outcome.follow_up_error is None
    assert app.notes.get("file", "id-a") == "see Northpower"
    undo = app.activity.undo(outcome.batch.batch_id)
    assert undo.follow_up_error is None
    assert app.notes.get("file", "id-a") == ""


def test_filing_note_never_overwrites_an_existing_note(app, fake_archive):
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    app.notes.set("file", "id-a", "mine")
    outcome = app.inbox.file_it([FileRequest("id-a", "b.pdf", BANKS, note="filing note")])
    assert outcome.batch.failed is None
    assert outcome.follow_up_error == "note not added: b.pdf already has a note"
    assert app.notes.get("file", "id-a") == "mine"
    app.activity.undo(outcome.batch.batch_id)
    assert app.notes.get("file", "id-a") == "mine"


def test_noop_and_failed_batch_follow_ups_have_no_batch(app, fake_archive, monkeypatch):
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    add_scan(app, fake_archive, "b.pdf", "id-b", OTHER_BILL)
    reqs = [
        FileRequest("id-a", "a.pdf", INBOX, tray="to-pay", collections=["Sauna"], note="n"),
        FileRequest("id-b", "b.pdf", BANKS, tray="to-pay"),
    ]
    app.executor.throttle_ms = 0
    resolved = app.inbox.preview(reqs)
    fake_archive.add(f"{BANKS}/b.pdf", content=b"blocker")  # the only op fails
    monkeypatch.setattr(Executor, "preview", lambda self, plan: resolved)
    outcome = app.inbox.file_it(reqs)
    assert outcome.batch.failed is not None and outcome.batch.done == []
    [item] = app.trays.list("to-pay")
    assert item.files == ["id-a"] and item.created_by_batch is None
    with app.engine.connect() as conn:
        owners = set(conn.execute(select(collection_members.c.created_by_batch)).scalars())
        note_owners = set(conn.execute(select(notes.c.created_by_batch)).scalars())
    assert owners == {None} and note_owners == {None}


def test_undo_keeps_earlier_membership_and_other_batches_items(app, fake_archive):
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    add_scan(app, fake_archive, "b.pdf", "id-b", OTHER_BILL)
    sauna = app.collections.create("Sauna")
    app.collections.add_members(sauna.id, ["id-a"])  # the user's own membership
    first = app.inbox.file_it([FileRequest("id-b", "b.pdf", BANKS, tray="to-pay")])
    second = app.inbox.file_it(
        [FileRequest("id-a", "a.pdf", BANKS, tray="to-pay", collections=["Sauna"])]
    )
    assert second.follow_up_error is None
    undo = app.activity.undo(second.batch.batch_id)
    assert undo.follow_up_error is None
    assert [m.drive_id for m in app.collections.get(sauna.id).members] == ["id-a"]
    assert [i.id for i in app.trays.list("to-pay")] == first.items


def test_unparseable_prefill_does_not_block_filing(app, fake_archive):
    add_scan(
        app,
        fake_archive,
        "a.pdf",
        "id-a",
        "Lasku\nEräpäivä 01.12.2026\nYhteensä 1000000000000,00 €",
    )
    assert app.inbox.list()[0].prefill["total"] == "1000000000000.00"
    outcome = app.inbox.file_it([FileRequest("id-a", "b.pdf", BANKS, tray="to-pay")])
    assert outcome.batch.failed is None and outcome.follow_up_error is None
    [item] = app.trays.list("to-pay")
    assert "amount" not in item.fields and str(item.fields["due_date"]) == "2026-12-01"


def test_undo_reports_follow_up_cleanup_error(app, fake_archive, monkeypatch):
    add_scan(app, fake_archive, "a.pdf", "id-a", NORTHPOWER_BILL)
    outcome = app.inbox.file_it([FileRequest("id-a", "b.pdf", BANKS, tray="to-pay", note="n")])

    def boom(batch_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(app.trays, "remove_created_by", boom)
    undo = app.activity.undo(outcome.batch.batch_id)
    assert undo.batch.failed is None and undo.batch.error is None
    assert undo.follow_up_error == "RuntimeError: db down"
    assert (fake_archive.root / INBOX / "a.pdf").exists()
    assert app.notes.get("item", str(outcome.items[0])) == ""  # the others still ran


def test_reload_rules_returns_tray_errors_and_survives_refresh_failure(app, monkeypatch):
    (app.app_paths.config_dir / "trays" / "99-bad.yaml").write_text("id: ''\n", encoding="utf-8")
    (app.app_paths.config_dir / "rules" / "50-bad.yaml").write_text("- id: ''\n", encoding="utf-8")

    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(app.trays, "refresh_dates", boom)
    errors = app.reload_rules()
    assert [e.file for e in errors] == ["50-bad.yaml", "99-bad.yaml"]


def test_batch_summary_undoable(app, fake_archive):
    import dataclasses

    from dam.services.activity import ActivityService

    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-a")
    scan(app.paths, app.repo)
    result = app.inbox.file_it([FileRequest("id-a", "b.pdf", BANKS)]).batch
    summary = app.activity.get(result.batch_id)
    assert summary.undoable is True
    interrupted = [dataclasses.replace(summary.ops[0], state="planned")]
    assert ActivityService._summary(result.batch_id, interrupted).undoable is False
    workflow = [dataclasses.replace(summary.ops[0], origin="workflow")]
    assert ActivityService._summary(result.batch_id, workflow).undoable is False
    undo = app.activity.undo(result.batch_id).batch
    assert app.activity.get(result.batch_id).undoable is False  # already undone
    assert app.activity.get(undo.batch_id).undoable is False  # an undo
