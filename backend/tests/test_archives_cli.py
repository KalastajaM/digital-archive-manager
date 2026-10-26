"""``dam --archive`` and ``dam archives ...``."""

import hashlib
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import dam.serve as serve_mod
from conftest import FakeArchive
from dam import setup
from dam.cli.main import app as cli
from dam.config import AppPaths
from dam.profiles import ProfileStore, ServeLock

runner = CliRunner()
INBOX = "##. Organize"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def base(app_paths) -> Path:
    return app_paths.data_dir  # Main: an old-style data folder with its archive set


@pytest.fixture
def run(base):
    def _run(*args, input=None, env=None):
        return runner.invoke(cli, ["--data-dir", str(base), *map(str, args)], input=input, env=env)

    return _run


def test_archives_list_adopts_an_old_data_folder_as_main(run, base, fake_archive):
    before = {p: sha(p) for p in base.rglob("*") if p.is_file()}
    r = run("archives", "list")
    assert r.exit_code == 0, r.output
    assert "Main" in r.stdout and "main" in r.stdout and str(fake_archive.root) in r.stdout
    after = {p: sha(p) for p in base.rglob("*") if p.is_file()}
    assert set(after) - set(before) == {base / "archives.yaml"}
    assert {p: h for p, h in after.items() if p in before} == before
    # nothing about the old layout changes how it is used
    assert run("scan").exit_code == 0


def test_add_switch_and_work_on_each_archive_separately(run, base, fake_archive, tmp_path):
    fake_archive.add(f"{INBOX}/main-only.pdf", drive_id="m-1")
    assert run("scan").exit_code == 0
    main_db, main_settings = sha(base / "dam.sqlite"), sha(base / "config" / "settings.yaml")

    test_archive = FakeArchive(tmp_path / "test-archive")
    test_archive.add(f"{INBOX}/test-only.pdf", drive_id="t-1")
    r = run("archives", "add", "Test", "--folder", test_archive.root, "--yes", "--layout", "none")
    assert r.exit_code == 0, r.output
    assert "Added 'Test'" in r.stdout
    # Main stays the archive in use
    assert "main-only.pdf" in run("inbox").stdout
    r = run("archives", "list")
    assert r.stdout.index("*") < r.stdout.index("Main")

    # --archive picks the other one; its index is its own
    assert run("--archive", "Test", "scan").exit_code == 0
    inbox = run("--archive", "test", "inbox").stdout
    assert "test-only.pdf" in inbox and "main-only.pdf" not in inbox
    assert (base / "archives" / "test" / "dam.sqlite").is_file()
    # ... and Main's files are byte-identical
    assert (sha(base / "dam.sqlite"), sha(base / "config" / "settings.yaml")) == (
        main_db,
        main_settings,
    )

    # DAM_ARCHIVE does the same
    assert "test-only.pdf" in run("inbox", env={"DAM_ARCHIVE": "Test"}).stdout

    # switching changes the default
    r = run("archives", "switch", "test")
    assert r.exit_code == 0 and "now the archive in use" in r.stdout
    assert "test-only.pdf" in run("inbox").stdout
    assert "main-only.pdf" in run("--archive", "main", "inbox").stdout

    # where / rename / color / forget
    r = run("archives", "where", "Test")
    assert str(base / "archives" / "test") in r.stdout and str(test_archive.root) in r.stdout
    assert run("archives", "rename", "Test", "Playground").exit_code == 0
    assert "Playground" in run("archives", "list").stdout
    assert run("archives", "color", "playground", "#abcdef").exit_code == 0
    assert "#abcdef" in yaml.safe_dump(
        yaml.safe_load((base / "archives.yaml").read_text(encoding="utf-8"))
    )


def test_forget_deletes_nothing_and_prints_the_paths(run, base, fake_archive, tmp_path):
    test_archive = FakeArchive(tmp_path / "test-archive")
    test_archive.add(f"{INBOX}/t.pdf", drive_id="t-1")
    assert (
        run(
            "archives", "add", "Test", "--folder", test_archive.root, "-y", "--layout", "none"
        ).exit_code
        == 0
    )
    r = run("archives", "forget", "main")  # the archive in use
    assert r.exit_code == 1 and "in use" in r.stderr
    assert run("archives", "switch", "test").exit_code == 0
    r = run("archives", "forget", "main", "--switch-to", "test")
    assert r.exit_code == 0, r.output
    assert "Nothing was deleted" in r.stdout
    assert str(base) in r.stdout and str(fake_archive.root) in r.stdout
    assert (base / "dam.sqlite").exists() or (base / "config" / "settings.yaml").exists()
    assert fake_archive.root.is_dir()
    # the last one cannot be forgotten
    r = run("archives", "forget", "test")
    assert r.exit_code == 1 and "only archive" in r.stderr
    assert (test_archive.root / INBOX / "t.pdf").is_file()
    assert run("archives", "forget", "nope").exit_code == 1


def test_an_unknown_archive_is_an_error(run):
    r = run("--archive", "ghost", "inbox")
    assert r.exit_code == 1 and "no archive called 'ghost'" in r.stderr.lower()


def test_add_refuses_an_existing_name_and_an_overlapping_folder(run, base, fake_archive, tmp_path):
    other = FakeArchive(tmp_path / "other")
    assert (
        run("archives", "add", "Test", "--folder", other.root, "-y", "--layout", "none").exit_code
        == 0
    )
    r = run("archives", "add", "test", "--folder", other.root, "-y")
    assert r.exit_code == 1 and "already an archive" in r.stderr
    # B cannot take A's folder, a folder inside it, or one that holds it
    inside = tmp_path / "other" / "deeper"
    inside.mkdir()
    for folder in (fake_archive.root, fake_archive.root / "sub", other.root, inside, tmp_path):
        r = run("archives", "add", "Third", "--folder", folder, "-y", "--layout", "none")
        assert r.exit_code == 1, (folder, r.output)
        assert "archive folder" in r.stderr or "data folder" in r.stderr or "home" in r.stderr
    assert (
        not (base / "archives" / "third" / "config" / "settings.yaml")
        .read_text(encoding="utf-8")
        .count('archive_root: "')
        if (base / "archives" / "third").exists()
        else True
    )
    # init on the other archive is guarded the same way
    r = run("--archive", "test", "init", "--archive", fake_archive.root, "--yes")
    assert r.exit_code == 1 and "already the archive folder of 'Main'" in r.stderr
    assert setup.current_archive_root(AppPaths(base / "archives" / "test")) == str(other.root)


def test_a_demo_archive_from_the_command_line(run, base, tmp_path):
    folder = tmp_path / "demo"
    r = run("archives", "add", "Demo", "--demo", "--folder", folder)
    assert r.exit_code == 0, r.output
    assert (folder / INBOX).is_dir() and list((folder / INBOX).glob("*.pdf"))
    assert run("archives", "add", "Demo2", "--demo").exit_code == 1  # needs --folder
    r = run("archives", "add", "Demo3", "--demo", "--folder", folder)  # now another's folder
    assert r.exit_code == 1 and "already the archive folder of 'Demo'" in r.stderr
    full = tmp_path / "full"
    full.mkdir()
    (full / "x.txt").write_text("x", encoding="utf-8")
    r = run("archives", "add", "Demo4", "--demo", "--folder", full)
    assert r.exit_code == 1 and "not empty" in r.stderr
    assert [p.id for p in ProfileStore(base).load()] == ["main", "demo"]  # no half-made entries


def test_serve_opens_the_chosen_archive_and_refuses_one_served_elsewhere(
    run, base, fake_archive, tmp_path, monkeypatch
):
    other = FakeArchive(tmp_path / "other")
    assert (
        run("archives", "add", "Test", "--folder", other.root, "-y", "--layout", "none").exit_code
        == 0
    )
    served = []
    monkeypatch.setattr(
        serve_mod,
        "serve",
        lambda a, api, port, open_browser, host=None: served.append(a.app_paths.data_dir),
    )
    assert run("serve", "--no-open").exit_code == 0
    assert run("--archive", "Test", "serve", "--no-open", "--port", "9301").exit_code == 0
    assert served == [base, base / "archives" / "test"]
    # a second process on the same archive is refused, and says where the first is
    held = ServeLock(base / "archives" / "test")
    held.acquire(9301)
    try:
        r = run("--archive", "Test", "serve", "--no-open", "--port", "9302")
        assert r.exit_code == 1 and "9301" in r.stderr and "another dam window" in r.stderr
        # the other archive is free to run side by side
        assert run("serve", "--no-open", "--port", "9302").exit_code == 0
        listing = run("archives", "list").stdout
        assert "another window (port 9301)" in listing
    finally:
        held.release()
    assert len(served) == 3


def test_archives_list_names_a_command_that_holds_an_archive(run, base, fake_archive, tmp_path):
    other = FakeArchive(tmp_path / "other")
    assert (
        run("archives", "add", "Test", "--folder", other.root, "-y", "--layout", "none").exit_code
        == 0
    )
    held = ServeLock(base / "archives" / "test")
    held.acquire(command="dam scan")
    try:
        line = next(x for x in run("archives", "list").stdout.splitlines() if "Test" in x)
        assert "in use by a dam command (dam scan)" in line and "window" not in line
    finally:
        held.release()


def test_the_reminder_job_is_per_archive(run, base, tmp_path, monkeypatch):
    import dam.cli.main as cli_main

    other = FakeArchive(tmp_path / "other")
    assert (
        run("archives", "add", "Test", "--folder", other.root, "-y", "--layout", "none").exit_code
        == 0
    )
    monkeypatch.setattr(cli_main, "_platform", lambda: "linux")
    r = run("--archive", "Test", "remind", "--install")
    assert r.exit_code == 1
    assert f'--data-dir "{base}" --archive test remind' in r.stderr
    r = run("--archive", "main", "remind", "--install")
    assert "--archive main remind" in r.stderr  # named once there are several archives


def test_a_single_archive_keeps_the_old_reminder_command(run, base, monkeypatch):
    import dam.cli.main as cli_main

    monkeypatch.setattr(cli_main, "_platform", lambda: "linux")
    r = run("remind", "--install")
    assert f'--data-dir "{base}" remind' in r.stderr and "--archive" not in r.stderr
