import os

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from dam.app import App
from dam.cli.main import app as cli
from dam.db.tables import files, operations
from dam.ops.executor import Executor
from dam.ops.model import BatchResult
from dam.services.browse import BrowseService
from dam.services.inbox import FileItResult, InboxService

INBOX = "##. Organize"
BANKS = "10. Financial/Banks"
QUAR = "##. To Delete"
runner = CliRunner()


@pytest.fixture
def run(app_paths):
    def _run(*args, input=None, data_dir=True):
        prefix = ["--data-dir", str(app_paths.data_dir)] if data_dir else []
        return runner.invoke(cli, [*prefix, *map(str, args)], input=input)

    return _run


def journal(app) -> list:
    with app.engine.connect() as conn:
        return list(conn.execute(select(operations).order_by(operations.c.id)).mappings())


def paths_in_db(app) -> set[str]:
    with app.engine.connect() as conn:
        return set(conn.execute(select(files.c.path)).scalars())


def test_scan_then_inbox(run, fake_archive):
    fake_archive.add(f"{INBOX}/File_000.pdf", drive_id="id-1")
    assert run("inbox").stdout.strip() == "inbox is empty"
    r = run("scan")
    assert r.exit_code == 0 and "added" in r.stdout
    r = run("inbox")
    assert r.exit_code == 0
    assert "SUGGESTED NAME" in r.stdout and "File_000.pdf" in r.stdout


def test_file_dry_run_changes_nothing(run, app, fake_archive):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-1")
    run("scan")
    r = run("file", "id-1", "--folder", BANKS, "--name", "b.pdf", "--tag", "x", "--dry-run")
    assert r.exit_code == 0, r.output
    assert f"{BANKS}/b.pdf" in r.stdout and "tags: x" in r.stdout and "dry run" in r.stdout
    assert (fake_archive.root / INBOX / "a.pdf").exists()
    assert journal(app) == [] and app.tags.for_file("id-1") == []
    assert f"{INBOX}/a.pdf" in paths_in_db(app)


def test_file_declined_changes_nothing(run, app, fake_archive):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-1")
    run("scan")
    r = run("file", "id-1", "--folder", BANKS, "--name", "b.pdf", "--tag", "x", input="n\n")
    assert r.exit_code == 1, r.output
    assert f"{BANKS}/b.pdf" in r.stdout and "aborted" in r.stderr
    assert (fake_archive.root / INBOX / "a.pdf").exists()
    assert journal(app) == [] and app.tags.for_file("id-1") == []


def test_file_confirmed_with_y_applies(run, app, fake_archive):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-1")
    run("scan")
    r = run("file", "id-1", "--folder", BANKS, "--name", "b.pdf", input="y\n")
    assert r.exit_code == 0, r.output
    assert (fake_archive.root / BANKS / "b.pdf").exists()


def test_file_and_undo(run, app, fake_archive):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-1")
    run("scan")
    r = run("file", f"{INBOX}/a.pdf", "--folder", BANKS, "--name", "b.pdf", "--tag", "x", "--yes")
    assert r.exit_code == 0, r.output
    assert (fake_archive.root / BANKS / "b.pdf").exists()
    assert app.repo.get("id-1").path == f"{BANKS}/b.pdf"
    assert app.tags.for_file("id-1") == ["x"]
    [summary] = app.activity.recent()
    assert summary.origin == "cli"
    assert run("activity").stdout.count(summary.batch_id) == 1
    r = run("undo", summary.batch_id, input="n\n")
    assert r.exit_code == 1
    assert f"{BANKS}/b.pdf" in r.stdout  # the prompt shows the ops
    assert (fake_archive.root / BANKS / "b.pdf").exists()
    r = run("undo", summary.batch_id, "--yes")
    assert r.exit_code == 0, r.output
    assert (fake_archive.root / INBOX / "a.pdf").exists()
    assert app.repo.get("id-1").path == f"{INBOX}/a.pdf"
    assert app.tags.for_file("id-1") == ["x"]  # tags stay after undo
    newest, original = app.activity.recent()
    assert newest.is_undo and newest.origin == "undo" and original.undone
    assert r.stdout.count(newest.batch_id) == 1


def test_undo_unknown_batch_exits_1_before_asking(run):
    r = run("undo", "nope")
    assert r.exit_code == 1 and "error:" in r.stderr and "Undo batch" not in r.stdout


def test_file_noop_with_tags(run, app, fake_archive):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-1")
    run("scan")
    r = run("file", "id-1", "--folder", INBOX, "--name", "a.pdf", "--tag", "t", "--yes")
    assert r.exit_code == 0, r.output
    assert "no file changes" in r.stdout and "tags: t" in r.stdout
    assert "batch" not in r.stdout
    assert app.tags.for_file("id-1") == ["t"]


def test_file_by_absolute_path_and_default_name(run, fake_archive):
    path = fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-1")
    run("scan")
    r = run("file", path, "--folder", BANKS, "--yes")
    assert r.exit_code == 0, r.output
    assert not path.exists()
    assert len(list((fake_archive.root / BANKS).glob("*.pdf"))) == 1


def test_relative_path_is_archive_relative_not_cwd(run, app, fake_archive, tmp_path, monkeypatch):
    fake_archive.add(f"{INBOX}/a.pdf", content=b"archive", drive_id="id-1")
    run("scan")
    cwd = tmp_path / "elsewhere"
    (cwd / INBOX).mkdir(parents=True)
    decoy = cwd / INBOX / "a.pdf"
    decoy.write_bytes(b"decoy")
    monkeypatch.chdir(cwd)
    r = run("file", f"{INBOX}/a.pdf", "--folder", BANKS, "--name", "b.pdf", "--yes")
    assert r.exit_code == 0, r.output
    assert (fake_archive.root / BANKS / "b.pdf").read_bytes() == b"archive"
    assert decoy.read_bytes() == b"decoy"


def test_file_on_missing_or_parked_record_exits_1(run, app, fake_archive):
    fake_archive.add(f"{INBOX}/gone.pdf", drive_id="id-g")
    fake_archive.add(f"{INBOX}/parked.pdf", drive_id="id-p")
    run("scan")
    (fake_archive.root / INBOX / "gone.pdf").unlink()
    run("scan")
    app.repo.park(f"{INBOX}/parked.pdf")
    for arg in ("id-g", "id-p", f"{INBOX}/gone.pdf"):
        r = run("file", arg, "--folder", BANKS, "--name", "x.pdf")
        assert r.exit_code == 1 and r.stderr.startswith("error:"), arg
        assert "Traceback" not in r.output


def test_search_output(run, app, fake_archive):
    fake_archive.add(f"{BANKS}/statement.txt", content=b"quarterly zebra report", drive_id="id-1")
    run("scan")
    assert run("index").exit_code == 0
    r = run("search", "zebra", "--folder", "10. Financial")
    assert r.exit_code == 0 and f"{BANKS}/statement.txt" in r.stdout and "[zebra]" in r.stdout
    assert run("search", "nonexistentword").stdout.strip() == "no matches"


def stuck_row(app, state="planned"):
    with app.engine.begin() as conn:
        conn.execute(
            operations.insert().values(
                batch_id="b1", seq=0, kind="rename", src=f"{INBOX}/a.pdf", dst="z.pdf",
                state=state, origin="cli", created=1.0,
            )
        )  # fmt: skip


def test_pending_warning_goes_to_stderr_and_recover_settles(run, app, fake_archive):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-1")
    run("scan")
    stuck_row(app)
    r = run("inbox")
    assert "dam recover" in r.stderr and "dam recover" not in r.stdout
    r = run("recover")
    assert r.exit_code == 0 and "dam recover" not in r.output
    assert "a.pdf" in r.stdout
    assert [row["state"] for row in journal(app)] == ["failed"]
    assert app.activity.pending() == []
    assert run("recover").stdout.strip() == "nothing to recover"


def test_recover_prints_index_errors_and_exits_4(run, monkeypatch):
    from dam.ops.undo import RecoveryResult

    monkeypatch.setattr(
        Executor, "recover", lambda self: RecoveryResult(entries=[], index_errors=["disk full"])
    )
    r = run("recover")
    assert r.exit_code == 4 and "disk full" in r.stderr


def test_quarantine_dry_run_no_and_yes(run, app, fake_archive):
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="id-1")
    fake_archive.add(f"{BANKS}/b.pdf", drive_id="id-2")
    run("scan")
    before = paths_in_db(app)
    r = run("quarantine", f"{BANKS}/a.pdf", "--dry-run")
    assert r.exit_code == 0 and "quarantine" in r.stdout
    assert journal(app) == [] and paths_in_db(app) == before
    r = run("quarantine", f"{BANKS}/a.pdf", input="n\n")
    assert r.exit_code == 1
    assert (fake_archive.root / BANKS / "a.pdf").exists()
    assert journal(app) == [] and paths_in_db(app) == before
    r = run("quarantine", f"{BANKS}/a.pdf", "id-2", "--yes")
    assert r.exit_code == 0, r.output
    assert (fake_archive.root / QUAR / BANKS / "a.pdf").exists()
    assert (fake_archive.root / QUAR / BANKS / "b.pdf").exists()
    assert app.repo.get("id-1").path == f"{QUAR}/{BANKS}/a.pdf"
    rows = journal(app)
    assert {x["origin"] for x in rows} == {"cli"} and len({x["batch_id"] for x in rows}) == 1
    assert [x["kind"] for x in rows].count("quarantine") == 2


def test_quarantine_preview_problem_exits_4_without_confirmation(run, fake_archive, monkeypatch):
    fake_archive.add(f"{BANKS}/a.pdf", drive_id="id-1")
    run("scan")
    monkeypatch.setattr(
        BrowseService,
        "quarantine",
        lambda self, ids, origin, dry_run=False: BatchResult("b", dry_run, error="blocked"),
    )
    r = run("quarantine", f"{BANKS}/a.pdf")  # no input: a prompt would abort with exit 1
    assert r.exit_code == 4 and "blocked" in r.stderr and "Quarantine" not in r.stdout


def test_user_errors_exit_1_without_traceback(run, fake_archive):
    r = run("file", "nope", "--folder", BANKS, "--name", "x.pdf")
    assert r.exit_code == 1 and r.stderr.startswith("error:") and "Traceback" not in r.output
    r = run("file", "../outside.pdf", "--folder", BANKS, "--name", "x.pdf")
    assert r.exit_code == 1 and r.stderr.startswith("error:")
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-1")
    run("scan")
    r = run("file", "id-1", "--folder", "../out", "--name", "x.pdf")
    assert r.exit_code == 1 and r.stderr.startswith("error:")
    r = run("file", "id-1", "--folder", BANKS, "--name", "a/b.pdf")
    assert r.exit_code == 1 and r.stderr.startswith("error:")


def test_unexpected_error_exits_3_and_logs_traceback(run, app_paths, fake_archive, monkeypatch):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-1")
    run("scan")

    def boom(self, reqs, origin="ui"):
        raise RuntimeError("kaput")

    monkeypatch.setattr(InboxService, "preview", boom)
    r = run("file", "id-1", "--folder", BANKS, "--name", "b.pdf", "--yes")
    log = app_paths.logs_dir / "dam.log"
    assert r.exit_code == 3
    assert "internal error: RuntimeError: kaput" in r.stderr and str(log) in r.stderr
    assert "Traceback" not in r.output
    text = log.read_text(encoding="utf-8")
    assert "Traceback" in text and "RuntimeError: kaput" in text


def test_app_create_failure_exits_3(run, monkeypatch):
    def broken(data_dir=None, require_archive=True):
        raise OSError("no disk")

    monkeypatch.setattr(App, "create", staticmethod(broken))
    r = run("scan")
    assert r.exit_code == 3 and "internal error: OSError: no disk" in r.stderr
    assert "Traceback" not in r.output


def batch_with(**kw):
    return lambda self, plan, dry_run=False, check=None: BatchResult("b1", dry_run, **kw)


@pytest.mark.parametrize("field", ["error", "index_error"])
def test_batch_string_problems_exit_4(run, fake_archive, monkeypatch, field):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-1")
    run("scan")
    monkeypatch.setattr(Executor, "apply", batch_with(**{field: "boom"}))
    r = run("file", "id-1", "--folder", BANKS, "--name", "b.pdf", "--yes")
    assert r.exit_code == 4 and "boom" in r.stderr and "batch b1" in r.stdout


def test_batch_failed_exits_4(run, app, fake_archive, monkeypatch):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-1")
    run("scan")
    [rop] = app.inbox.preview([_req()])
    monkeypatch.setattr(Executor, "apply", batch_with(failed=rop, error="x"))
    r = run("file", "id-1", "--folder", BANKS, "--name", "b.pdf", "--yes")
    assert r.exit_code == 4 and "failed: move" in r.stderr


def _req():
    from dam.services.inbox import FileRequest

    return FileRequest("id-1", "b.pdf", BANKS)


def test_tag_error_exits_4_and_says_files_were_filed(run, app, fake_archive, monkeypatch):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-1")
    run("scan")
    monkeypatch.setattr(
        InboxService,
        "file_it",
        lambda self, reqs, dry_run=False, origin="ui": FileItResult(
            BatchResult("b1", False), tag_error="RuntimeError: db locked", untagged=["id-1"]
        ),
    )
    r = run("file", "id-1", "--folder", BANKS, "--name", "b.pdf", "--tag", "t", "--yes")
    assert r.exit_code == 4
    assert "tagging failed" in r.stderr and "db locked" in r.stderr and "id-1" in r.stderr
    assert "scan" not in r.stderr


def test_data_dir_falls_back_to_env(run, app_paths, monkeypatch, fake_archive):
    monkeypatch.setenv("DAM_DATA_DIR", str(app_paths.data_dir))
    fake_archive.add(f"{INBOX}/File_000.pdf", drive_id="id-1")
    assert run("scan", data_dir=False).exit_code == 0
    assert "File_000.pdf" in run("inbox", data_dir=False).stdout


@pytest.mark.parametrize("command", ["scan", "serve"])
def test_unavailable_archive_exits_1_with_clear_message(
    run, fake_archive, tmp_path, command, monkeypatch
):
    from dam import serve as dam_serve

    monkeypatch.setattr(dam_serve, "serve", lambda *a, **k: pytest.fail("must not serve"))
    os.rename(fake_archive.root, tmp_path / "archive-away")
    r = run(command, "--no-open") if command == "serve" else run(command)
    assert r.exit_code == 1
    assert "error:" in r.stderr and str(fake_archive.root) in r.stderr
    assert "Google Drive" in r.stderr and "Traceback" not in r.output


def test_undo_cleanup_error_exits_4(run, app, fake_archive, monkeypatch):
    from dam.trays.service import TrayService

    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-1")
    run("scan")
    assert run("file", "id-1", "--folder", BANKS, "--name", "b.pdf", "--yes").exit_code == 0
    [summary] = app.activity.recent()

    def boom(self, batch_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(TrayService, "remove_created_by", boom)
    r = run("undo", summary.batch_id, "--yes")
    assert r.exit_code == 4, r.output
    assert "RuntimeError: db down" in r.stderr
    assert (fake_archive.root / INBOX / "a.pdf").exists()


# -- Phase 2: remind, trays, collections, ongoing -------------------------------------

from dam.reminders import launchd, notify  # noqa: E402


class FakeMac:
    id = "mac"
    sent: list = []

    @classmethod
    def from_settings(cls, settings):
        return cls()

    def send(self, dues, note=None):
        FakeMac.sent.append([d.title for d in dues])


@pytest.fixture
def fake_mac(monkeypatch):
    FakeMac.sent = []
    monkeypatch.setitem(notify.NOTIFIERS, "mac", FakeMac)
    return FakeMac.sent


@pytest.fixture
def a_bill(app, fake_archive):
    fake_archive.add(f"{BANKS}/20261020_Northpower_bill.pdf", drive_id="b-1")
    app.scan()
    return app.trays.create("to-pay", ["b-1"], {"due_date": "2026-11-03"}, title=None)


def test_remind_now_sends_once(run, a_bill, fake_mac):
    r = run("remind", "--now", "2026-11-03T09:00")
    assert r.exit_code == 0, r.output
    assert fake_mac == [["Northpower bill"]]
    assert "Northpower bill" in r.stdout and "2026-11-03" in r.stdout
    r = run("remind", "--now", "2026-11-03T10:00")
    assert r.exit_code == 0 and fake_mac == [["Northpower bill"]]
    assert "nothing due" in r.stdout


def test_remind_dry_run_sends_and_marks_nothing(run, a_bill, fake_mac):
    r = run("remind", "--now", "2026-11-03T09:00", "--dry-run")
    assert r.exit_code == 0, r.output
    assert "Northpower bill" in r.stdout and "dry run" in r.stdout
    assert fake_mac == []
    assert run("remind", "--now", "2026-11-03T09:00").exit_code == 0
    assert fake_mac == [["Northpower bill"]]


def test_remind_channel_error_exits_4(run, a_bill, monkeypatch):
    class Broken:
        id = "mac"

        @classmethod
        def from_settings(cls, settings):
            return cls()

        def send(self, dues, note=None):
            raise notify.NotifyError("osascript failed")

    monkeypatch.setitem(notify.NOTIFIERS, "mac", Broken)
    r = run("remind", "--now", "2026-11-03T09:00")
    assert r.exit_code == 4 and "mac: osascript failed" in r.stderr


def test_remind_works_without_the_archive(run, a_bill, fake_mac, fake_archive, tmp_path):
    os.rename(fake_archive.root, tmp_path / "away")
    try:
        r = run("remind", "--now", "2026-11-03T09:00")
    finally:
        os.rename(tmp_path / "away", fake_archive.root)
    assert r.exit_code == 0, r.output
    assert fake_mac == [["Northpower bill"]]


def reminder_marks(app) -> int:
    from dam.db.tables import reminders_sent

    with app.engine.connect() as conn:
        return len(conn.execute(select(reminders_sent)).all())


def test_remind_test_notification_sends_one_and_marks_nothing(run, app, a_bill, fake_mac):
    r = run("remind", "--test-notification", "--now", "2026-11-03T09:00")
    assert r.exit_code == 0, r.output
    assert fake_mac == [["dam test notification"]]
    assert "mac: sent" in r.stdout
    assert reminder_marks(app) == 0
    # the real reminder is still due afterwards
    assert run("remind", "--now", "2026-11-03T09:00").exit_code == 0
    assert fake_mac[-1] == ["Northpower bill"]


def test_remind_test_notification_dry_run_sends_nothing(run, app, fake_mac):
    r = run("remind", "--test-notification", "--dry-run")
    assert r.exit_code == 0, r.output
    assert fake_mac == [] and "dam test notification" in r.stdout and "mac" in r.stdout
    assert "dry run" in r.stdout and reminder_marks(app) == 0


def test_remind_test_notification_reports_each_channel(run, app, monkeypatch):
    class Broken:
        id = "mac"

        @classmethod
        def from_settings(cls, settings):
            return cls()

        def send(self, dues, note=None):
            raise notify.NotifyError("osascript failed (exit 1)")

    monkeypatch.setitem(notify.NOTIFIERS, "mac", Broken)
    r = run("remind", "--test-notification")
    assert r.exit_code == 4 and "mac: osascript failed (exit 1)" in r.stderr


@pytest.mark.parametrize(
    "args",
    [["--now", "yesterday"], ["--install", "--uninstall"], ["--test-notification", "--install"]],
)
def test_remind_usage_errors_exit_2(run, args):
    assert run("remind", *args).exit_code == 2


@pytest.fixture
def home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return launchd.subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(launchd.subprocess, "run", fake_run)
    monkeypatch.setattr(launchd.os, "getuid", lambda: 501)
    return home, calls


def test_remind_install_declined_writes_nothing(run, home):
    _, calls = home
    r = run("remind", "--install", input="n\n")
    assert r.exit_code == 1 and "aborted" in r.stderr
    assert str(launchd.plist_path()) in r.stdout and "nl.dam.remind" in r.stdout
    assert not launchd.plist_path().exists() and calls == []


def test_remind_install_and_uninstall(run, home, app_paths):
    _, calls = home
    r = run("remind", "--install", "--yes")
    assert r.exit_code == 0, r.output
    path = launchd.plist_path()
    assert path.is_file() and str(app_paths.data_dir.resolve()) in path.read_text(encoding="utf-8")
    assert any(c[1] == "bootstrap" for c in calls)
    r = run("remind", "--install", "--yes")  # same content: fine
    assert r.exit_code == 0, r.output
    r = run("remind", "--uninstall", input="y\n")
    assert r.exit_code == 0, r.output
    assert not path.exists()
    r = run("remind", "--uninstall", "--yes")
    assert r.exit_code == 0 and "not installed" in r.stdout


def test_remind_install_conflict_needs_force(run, home):
    path = launchd.plist_path()
    path.parent.mkdir(parents=True)
    path.write_text("something else", encoding="utf-8")
    r = run("remind", "--install", "--yes")
    assert r.exit_code == 1 and "--force" in r.stderr
    assert path.read_text(encoding="utf-8") == "something else"
    assert run("remind", "--install", "--yes", "--force").exit_code == 0
    assert "nl.dam.remind" in path.read_text(encoding="utf-8")


def test_set_email_password_needs_email_settings(run):
    r = run("remind", "--set-email-password", input="pw\npw\n")
    assert r.exit_code == 1 and "reminders.email" in r.stderr


def test_set_email_password_stores_in_keychain(run, app_paths, monkeypatch):
    import yaml

    settings = app_paths.config_dir / "settings.yaml"
    raw = yaml.safe_load(settings.read_text(encoding="utf-8"))
    raw["reminders"] = {
        "email": {"to": "me@example.com", "smtp_host": "smtp.example.com", "smtp_user": "me"}
    }
    settings.write_text(yaml.safe_dump(raw), encoding="utf-8")
    stored = []
    monkeypatch.setattr(notify, "store_keychain_password", lambda u, p: stored.append((u, p)))
    r = run("remind", "--set-email-password", input="s3cret-pw\ns3cret-pw\n")
    assert r.exit_code == 0, r.output
    assert stored == [("me", "s3cret-pw")]
    assert "s3cret-pw" not in r.output


def test_trays_command(run, app, a_bill, fake_archive):
    fake_archive.add(f"{BANKS}/r.pdf", drive_id="r-1")
    app.scan()
    app.trays.create("to-read", ["r-1"], {}, title=None)
    r = run("trays")
    assert r.exit_code == 0, r.output
    assert "To pay" in r.stdout and "Northpower bill" in r.stdout and "2026-11-03" in r.stdout
    assert "To read" in r.stdout and "r" in r.stdout
    r = run("trays", "--tray", "to-read")
    assert "Northpower bill" not in r.stdout and "To read" in r.stdout
    assert "Northpower bill" not in run("trays", "--done").stdout
    app.trays.done(a_bill.id, {})
    assert "Northpower bill" in run("trays", "--done").stdout
    assert run("trays", "--tray", "nope").exit_code == 1


def test_trays_command_shows_titles_as_plain_text(run, app, a_bill):
    from sqlalchemy import update

    from dam.db.tables import items

    with app.engine.begin() as conn:  # a title as stored by an older version, say
        conn.execute(
            update(items)
            .where(items.c.id == a_bill.id)
            .values(title="Evil\u202e\x1b[31mbill\nnext")
        )
    r = run("trays")
    assert r.exit_code == 0, r.output
    assert "Evil[31mbill next" in r.stdout
    assert "\u202e" not in r.stdout and "\x1b" not in r.stdout


def test_ongoing_sync_help_says_it_waits_for_the_app(run):
    r = run("ongoing", "sync", "--help")
    assert "Refused while the app has the archive open" in r.stdout


def test_collections_command(run, app, a_bill):
    c = app.collections.create("Sauna")
    app.collections.add_members(c.id, ["b-1"])
    old = app.collections.create("Old")
    app.collections.close(old.id)
    r = run("collections")
    assert r.exit_code == 0, r.output
    assert "Sauna" in r.stdout and "Old" not in r.stdout
    r = run("collections", "--closed")
    assert "Old" in r.stdout and "Sauna" not in r.stdout


def test_collections_command_shows_the_tree(run, app):
    houses = app.collections.create("Houses")
    sauna = app.collections.create("Sauna", parent_id=houses.id)
    app.collections.create("Deck", parent_id=sauna.id)
    app.collections.create("Attic", parent_id=houses.id)
    app.collections.create("Zebra")
    r = run("collections")
    assert r.exit_code == 0, r.output
    header, *lines = r.stdout.splitlines()
    start, end = header.index("NAME"), header.index("MEMBERS")
    assert [x[start:end].rstrip() for x in lines] == [
        "Houses",
        "  Sauna",
        "    Deck",
        "  Attic",
        "Zebra",
    ]
    app.collections.close(app.collections.by_name("Deck").id)
    r = run("collections", "--closed")
    assert "Houses › Sauna › Deck" in r.stdout  # its parents are not listed: the full path


def test_ongoing_sync_and_entries(run, app, a_bill, fake_archive):
    c = app.collections.create("Sauna")
    app.collections.add_members(c.id, ["b-1"])  # synced right away
    link = fake_archive.root / "##. Ongoing" / "Sauna" / "20261020_Northpower_bill.pdf"
    link.unlink()  # the user removed the link: the next sync repairs it
    r = run("ongoing", "sync", "--dry-run")
    assert r.exit_code == 0, r.output
    assert "symlink" in r.stdout and "dry run" in r.stdout
    assert not os.path.lexists(link)
    r = run("ongoing", "sync")
    assert r.exit_code == 0, r.output
    assert link.is_symlink()
    assert "no file changes" in run("ongoing", "sync").stdout
    fake_archive.link("##. Ongoing/Mine", f"{BANKS}/20261020_Northpower_bill.pdf")
    app.scan()
    r = run("ongoing", "entries")
    assert r.exit_code == 0, r.output
    assert "Sauna" in r.stdout and "managed" in r.stdout and "Mine" in r.stdout


# -- one writer at a time: commands that change the archive hold its lock ---------------

WRITERS = [
    ("scan",),
    ("index",),
    ("errors", "--retry"),
    ("errors", "--retry-unsupported"),
    ("file", "id-1", "--folder", BANKS, "--yes"),
    ("quarantine", "id-1", "--yes"),
    ("move", "id-1", "--folder", BANKS, "--yes"),
    ("undo", "nope", "--yes"),
    ("init", "--yes"),
    ("star", "id-1"),
    ("unstar", "id-1"),
    ("important", "id-1"),
    ("unimportant", "id-1"),
    ("ongoing", "sync"),
    ("ai", "--on"),
    ("ai", "--off"),
]
READERS = [
    ("inbox",),
    ("search", "x"),
    ("activity",),
    ("errors",),
    ("file", "id-1", "--folder", BANKS, "--dry-run"),
    ("quarantine", "id-1", "--dry-run"),
    ("move", "id-1", "--folder", BANKS, "--dry-run"),
    ("ongoing", "sync", "--dry-run"),
    ("ongoing", "entries"),
    ("remind", "--dry-run"),
    ("ai", "--status"),
    ("ai", "--log"),
    ("trays",),
    ("collections",),
    ("starred",),
    ("important", "--list"),
    ("openapi",),
]


@pytest.fixture
def held_by_app(app_paths):
    from dam.profiles import ServeLock

    lock = ServeLock(app_paths.data_dir)
    lock.acquire()
    lock.publish(8766)
    yield lock
    lock.release()


@pytest.mark.parametrize("args", WRITERS, ids=" ".join)
def test_a_writer_is_refused_while_the_app_has_the_archive(run, fake_archive, held_by_app, args):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-1")
    r = run(*args)
    assert r.exit_code == 1, r.output
    assert "open in the app on port 8766" in r.stderr and "close the app" in r.stderr


def test_add_and_recover_are_refused_while_the_app_has_the_archive(
    run, app_paths, held_by_app, tmp_path
):
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.4")
    r = run("add", outside, "--yes")
    assert r.exit_code == 1 and "open in the app on port 8766" in r.stderr
    r = run("recover")
    assert r.exit_code == 1 and "Run recovery" in r.stderr and "8766" in r.stderr


@pytest.mark.parametrize("args", READERS, ids=" ".join)
def test_a_reader_still_works_while_the_app_has_the_archive(
    run, app, fake_archive, held_by_app, args
):
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-1")
    app.scan()
    r = run(*args)
    assert r.exit_code == 0, r.output
    assert "open in the app" not in r.output


def test_a_writer_is_refused_while_another_command_changes_the_archive(run, app_paths):
    from dam.profiles import ServeLock

    lock = ServeLock(app_paths.data_dir)
    lock.acquire(command="dam scan")
    try:
        r = run("star", "x")
        assert r.exit_code == 1
        assert "A dam command (dam scan) is changing this archive right now" in r.stderr
        assert "Wait for it to finish" in r.stderr
        r = run("serve", "--no-open")
        assert r.exit_code == 1 and "A dam command (dam scan)" in r.stderr
        assert run("inbox").exit_code == 0
    finally:
        lock.release()


def test_no_recover_warning_while_another_process_has_the_archive(
    run, app, fake_archive, held_by_app
):
    """Its pending rows may be changes under way there, and `dam recover` is refused."""
    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-1")
    app.scan()
    stuck_row(app)
    r = run("inbox")
    assert r.exit_code == 0 and "dam recover" not in r.output


def test_a_writer_holds_the_lock_and_names_itself(run, app_paths, monkeypatch):
    import json

    from dam.app import App

    seen = []
    real = App.scan

    def spying(self, subtree=""):
        seen.append(json.loads((app_paths.data_dir / "serve.json").read_text(encoding="utf-8")))
        return real(self, subtree)

    monkeypatch.setattr(App, "scan", spying)
    assert run("scan").exit_code == 0
    assert seen[0]["kind"] == "cli" and seen[0]["command"] == "dam scan"
    assert run("scan").exit_code == 0  # released when the command ended


def test_init_with_a_layout_takes_the_lock_once(run, app_paths, tmp_path):
    """``init`` holds the lock and opens a session inside it: the same process never
    refuses itself."""
    folder = tmp_path / "fresh"
    folder.mkdir()
    r = run("init", "--archive", folder, "--layout", "minimal", "--yes")
    assert r.exit_code == 0, r.output
    assert "Undo it with" in r.stdout


HOLD_LOCK = """
import sys
from pathlib import Path
from dam.profiles import ServeLock
lock = ServeLock(Path(sys.argv[1]))
lock.acquire(command="dam file")
sys.stdout.write("held\\n")
sys.stdout.flush()
sys.stdin.read()  # hold it until the parent closes stdin
"""


def test_a_writer_waits_for_a_command_in_another_process(run, app_paths, fake_archive):
    import subprocess
    import sys

    fake_archive.add(f"{INBOX}/a.pdf", drive_id="id-1")
    other = subprocess.Popen(
        [sys.executable, "-c", HOLD_LOCK, str(app_paths.data_dir)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    try:
        assert other.stdout is not None and other.stdout.readline().strip() == b"held"
        r = run("scan")
        assert r.exit_code == 1 and "A dam command (dam file)" in r.stderr
        assert "added" not in r.stdout
    finally:
        assert other.stdin is not None
        other.stdin.close()
        other.wait(30)
        assert other.stdout is not None
        other.stdout.close()
    assert other.returncode == 0
    r = run("scan")
    assert r.exit_code == 0 and "added" in r.stdout, r.output
