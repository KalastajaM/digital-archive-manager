"""Archives (profiles): the registry, adopting an existing install, add / switch / rename /
forget, the isolation rules, the per-profile server lock and reminder agent."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from dam import setup
from dam.config import AppPaths
from dam.profiles import (
    MAIN_ID,
    Locked,
    ProfileStore,
    ServeLock,
    related,
    root_conflict,
    slugify,
)
from dam.reminders import launchd
from dam.services.errors import Conflict, InvalidRequest, NotFound


def mk(*parts: Path | str) -> Path:
    p = Path(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p


def snapshot(folder: Path) -> dict[str, str]:
    """Every file under ``folder`` -> its hash (the folder itself is not followed into
    other profiles' folders)."""
    out = {}
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            out[str(path.relative_to(folder))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


@pytest.fixture
def base(tmp_path) -> Path:
    return tmp_path / "base"


def old_install(base: Path) -> Path:
    """A data folder as every install before profiles has it."""
    paths = AppPaths(base)
    paths.ensure()
    (paths.config_dir / "settings.yaml").write_text(
        yaml.safe_dump({"archive_root": str(base.parent / "the-archive")}), encoding="utf-8"
    )
    paths.db_path.write_bytes(b"not really a database")
    return base


# -- the registry ------------------------------------------------------------------------


def test_a_fresh_base_is_main_and_writes_nothing(base):
    store = ProfileStore(base)
    [main] = store.load(persist=True)
    assert (main.id, main.name, main.data_dir, main.active) == (MAIN_ID, "Main", base, True)
    assert not base.exists()  # nothing to adopt: nothing written


def test_an_existing_single_archive_layout_is_adopted_as_main_unchanged(base):
    old_install(base)
    before = snapshot(base)
    store = ProfileStore(base)
    [main] = store.load(persist=True)
    assert main.data_dir == base and main.name == "Main" and main.active
    after = snapshot(base)
    assert set(after) - set(before) == {"archives.yaml"}  # only the registry is new
    assert {k: v for k, v in after.items() if k != "archives.yaml"} == before
    # a second load reads the file, with the same result
    assert ProfileStore(base).load() == [main]
    registry = yaml.safe_load((base / "archives.yaml").read_text(encoding="utf-8"))
    assert registry["archives"][0]["data_dir"] == str(base)
    assert not (base / "archives").exists()  # nothing moved


def test_a_database_alone_counts_as_a_single_archive_layout(base):
    mk(base)
    (base / "dam.sqlite").write_bytes(b"x")
    ProfileStore(base).load(persist=True)
    assert (base / "archives.yaml").is_file()


def test_add_makes_the_data_folder_and_does_not_switch(base):
    old_install(base)
    store = ProfileStore(base)
    test = store.add("Test archive")
    assert test.id == "test-archive" and test.data_dir == base / "archives" / "test-archive"
    assert (test.data_dir / "config" / "settings.yaml").is_file()
    assert setup.current_archive_root(AppPaths(test.data_dir)) is None  # not set up yet
    assert [p.id for p in store.load()] == [MAIN_ID, "test-archive"]
    assert store.active().id == MAIN_ID
    assert test.color != store.load()[0].color


def test_names_are_unique_and_ids_never_reuse_a_folder(base):
    store = ProfileStore(base)
    store.add("Test")
    with pytest.raises(Conflict):
        store.add("test")
    with pytest.raises(Conflict):
        store.add("Main")
    store.forget("Test")  # the folder stays ...
    again = store.add("Test")  # ... so the new one gets a different id and folder
    assert again.id == "test-2"
    assert (base / "archives" / "test").is_dir()


@pytest.mark.parametrize("name", ["", "   ", "x" * 41, "bad\x00name", "a\nb\x07"])
def test_bad_names_are_refused(base, name):
    with pytest.raises(InvalidRequest):
        ProfileStore(base).add(name)


def test_bad_colours_are_refused(base):
    with pytest.raises(InvalidRequest):
        ProfileStore(base).add("T", "red")


def test_slugify():
    assert slugify("Éva's test!") == "eva-s-test"
    assert slugify("???") == "archive"


def test_switch_rename_recolor_find(base):
    store = ProfileStore(base)
    store.add("Test")
    assert store.set_active("test").id == "test"
    assert store.active().id == "test"
    assert [p.active for p in store.load()] == [False, True]
    assert store.set_name("TEST", "Playground").name == "Playground"
    assert store.find("playground").id == "test"  # by name, any case
    assert store.find("test").name == "Playground"  # by id
    store.recolor("test", "#112233")
    assert store.find("test").color == "#112233"
    with pytest.raises(NotFound):
        store.find("nope")
    with pytest.raises(Conflict):
        store.set_name("test", "main")


def test_a_broken_registry_is_reported_and_left_alone(base):
    mk(base)
    (base / "archives.yaml").write_text("archives: [1, 2", encoding="utf-8")
    with pytest.raises(InvalidRequest, match="archives.yaml"):
        ProfileStore(base).load()
    assert (base / "archives.yaml").read_text(encoding="utf-8") == "archives: [1, 2"


def test_forget_never_deletes_and_follows_the_rules(base, tmp_path):
    old_install(base)
    store = ProfileStore(base)
    test = store.add("Test")
    archive = mk(tmp_path / "test-archive-folder")
    (archive / "doc.pdf").write_bytes(b"precious")
    setup.write_archive_root(AppPaths(test.data_dir), archive)
    before = (snapshot(base), snapshot(archive))
    # the archive in use needs another one to open
    with pytest.raises(Conflict, match="in use"):
        store.forget("main")
    gone = store.forget("test")
    assert gone.data_dir == test.data_dir and gone.archive_root == str(archive)
    assert [p.id for p in store.load()] == [MAIN_ID]
    assert test.data_dir.is_dir() and (archive / "doc.pdf").read_bytes() == b"precious"
    after_base = snapshot(base)
    # only the registry changed
    assert {k for k in after_base if after_base[k] != before[0].get(k)} <= {"archives.yaml"}
    assert snapshot(archive) == before[1]
    # the last one cannot be forgotten
    with pytest.raises(Conflict, match="only archive"):
        store.forget("main")


def test_forgetting_the_active_one_with_a_new_choice(base):
    store = ProfileStore(base)
    store.add("Test")
    gone = store.forget("main", switch_to="test")
    assert gone.id == "main"
    [only] = store.load()
    assert only.id == "test" and only.active
    assert only.data_dir.is_dir()
    assert base.is_dir()  # Main's folder is not touched either


# -- isolation -----------------------------------------------------------------------------


def two_archives(base: Path, tmp_path: Path):
    old_install(base)
    store = ProfileStore(base)
    a = store.load(persist=True)[0]
    b = store.add("Test")
    root_a, root_b = mk(tmp_path / "A-archive"), mk(tmp_path / "B-archive")
    (root_a / "a.pdf").write_bytes(b"a")
    setup.write_archive_root(AppPaths(a.data_dir), root_a)
    setup.write_archive_root(AppPaths(b.data_dir), root_b)
    return store, a, b, root_a, root_b


def test_writes_for_b_leave_a_byte_identical(base, tmp_path):
    store, a, b, root_a, root_b = two_archives(base, tmp_path)

    # A's whole data folder except B's nested folder and the registry, and A's archive
    def a_files() -> dict[str, str]:
        files = snapshot(a.data_dir)
        return {k: v for k, v in files.items() if not k.startswith("archives")}

    before = (a_files(), snapshot(root_a))
    # everything setup writes for B: the archive folder, the layout names, AI exclusions
    from dam.config import SpecialFolders

    new_root = mk(tmp_path / "B-new-archive")
    setup.write_archive_root(AppPaths(b.data_dir), new_root)
    setup.write_layout_settings(AppPaths(b.data_dir), SpecialFolders(inbox="Inbox"), ["Private"])
    (AppPaths(b.data_dir).config_dir / "rules").mkdir(exist_ok=True)
    (b.data_dir / "ai-state.json").write_text('{"enabled": false}', encoding="utf-8")
    store.set_name("test", "Renamed")
    store.recolor("test", "#010203")
    assert a_files() == before[0]  # A's settings, rules, database: byte-identical
    assert snapshot(root_a) == before[1]
    assert not (a.data_dir / "ai-state.json").exists()


def test_roots_may_not_be_the_same_nested_or_inside_a_data_folder(base, tmp_path):
    store, a, b, root_a, root_b = two_archives(base, tmp_path)
    profiles = store.load()
    for bad in (root_a, root_a / "sub", tmp_path):
        assert root_conflict(bad, profiles, base, b.id), bad
    messages = {
        "same": root_conflict(root_a, profiles, base, b.id),
        "inside": root_conflict(root_a / "sub", profiles, base, b.id),
        "around": root_conflict(tmp_path, profiles, base, b.id),
    }
    assert "already the archive folder of 'Main'" in messages["same"]
    assert "inside the archive folder of 'Main'" in messages["inside"]
    # tmp_path contains both the base and the roots; whichever rule fires, it is refused
    assert messages["around"]
    # a data folder, or a folder inside one, is never an archive
    assert root_conflict(b.data_dir, profiles, base, b.id)
    assert root_conflict(a.data_dir / "cache", profiles, base, a.id)
    # an unrelated folder is fine, for either archive
    other = mk(tmp_path / "elsewhere")
    assert root_conflict(other, profiles, base, b.id) is None
    # the archive's own folder is fine for itself
    assert root_conflict(root_b, profiles, base, b.id) is None


def test_the_check_is_case_insensitive_where_the_file_system_is(tmp_path):
    folder = mk(tmp_path / "Docs")
    upper = Path(str(folder).replace("Docs", "DOCS"))
    insensitive = upper.exists()
    assert (related(folder, upper) == "same") == insensitive
    if not insensitive:  # a case-sensitive file system: two different folders
        assert related(folder, upper) is None


def test_a_symlink_to_another_archive_is_seen_through(base, tmp_path):
    store, a, b, root_a, root_b = two_archives(base, tmp_path)
    link = tmp_path / "link"
    try:
        link.symlink_to(root_a, target_is_directory=True)
    except OSError:
        pytest.skip("no symlinks here")
    assert root_conflict(link, store.load(), base, b.id)
    assert root_conflict(link / "deeper", store.load(), base, b.id)


def test_check_archive_path_uses_the_guard(base, tmp_path):
    store, a, b, root_a, root_b = two_archives(base, tmp_path)
    paths = AppPaths(b.data_dir)
    guard = store.root_guard(b.id)
    check = setup.check_archive_path(str(root_a), paths, guard=guard)
    assert not check.ok and "already the archive folder of 'Main'" in check.message
    nested = mk(root_a / "sub")
    assert not setup.check_archive_path(str(nested), paths, guard=guard).ok
    assert setup.check_archive_path(str(root_b), paths, guard=guard).ok
    assert setup.check_archive_path(str(root_a), paths).ok  # no guard: no rule


def test_roots_may_not_touch_another_archives_extra_folders(base, tmp_path):
    store, a, b, root_a, root_b = two_archives(base, tmp_path)
    extra = mk(tmp_path / "disk" / "Old years")
    settings = AppPaths(a.data_dir).config_dir / "settings.yaml"
    data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    data["extra_folders"] = [
        {"label": "Old years", "path": str(extra)},
        {"label": "Gone", "path": str(mk(tmp_path / "disk" / "Gone")), "attached": False},
    ]
    settings.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert setup.current_extra_folders(AppPaths(a.data_dir)) == [extra]
    profiles = store.load()
    assert "already an extra archive folder of 'Main'" in root_conflict(extra, profiles, base, b.id)
    assert "inside an extra archive folder of 'Main'" in root_conflict(
        extra / "sub", profiles, base, b.id
    )
    assert "contains an extra archive folder of 'Main'" in root_conflict(
        extra.parent, profiles, base, b.id
    )
    assert root_conflict(extra, profiles, base, a.id) is None  # its own: not this rule
    assert root_conflict(tmp_path / "disk" / "Gone", profiles, base, b.id) is None
    assert store.root_problems() == {}


def test_root_problems_flags_an_extra_folder_inside_another_archive(base, tmp_path):
    store, a, b, root_a, root_b = two_archives(base, tmp_path)
    settings = AppPaths(b.data_dir).config_dir / "settings.yaml"
    data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    data["extra_folders"] = [{"label": "Oops", "path": str(root_a / "a-sub")}]
    settings.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert set(store.root_problems()) == {"main", "test"}  # the overlap is mutual


def test_root_problems_flags_a_hand_edited_overlap(base, tmp_path):
    store, a, b, root_a, root_b = two_archives(base, tmp_path)
    assert store.root_problems() == {}
    settings = AppPaths(b.data_dir).config_dir / "settings.yaml"
    settings.write_text(yaml.safe_dump({"archive_root": str(root_a)}), encoding="utf-8")
    problems = store.root_problems()
    assert set(problems) == {"main", "test"}


# -- one server per profile --------------------------------------------------------------


HOLD_LOCK = """
import sys
from pathlib import Path
from dam.profiles import ServeLock
lock = ServeLock(Path(sys.argv[1]))
lock.acquire(command="dam scan")
sys.stdout.write("held\\n")
sys.stdout.flush()
sys.stdin.read()  # hold it until the parent closes stdin
"""


def test_serve_lock_refuses_another_process_until_it_exits(tmp_path):
    """The lock is the OS's: a second process is refused while the first lives, and the
    folder is free again once it has exited (no stale lock file to clean up)."""
    data = mk(tmp_path / "data")
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLD_LOCK, str(data)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == b"held"
        assert ServeLock.holder(data) == {"port": None, "command": "dam scan"}
        mine = ServeLock(data)
        with pytest.raises(Locked) as caught:
            mine.acquire(8766)
        assert caught.value.command == "dam scan"
        assert "A dam command (dam scan) is changing this archive" in str(caught.value)
    finally:
        assert holder.stdin is not None
        holder.stdin.close()
        holder.wait(30)
        assert holder.stdout is not None
        holder.stdout.close()
    assert holder.returncode == 0
    assert ServeLock.holder(data) is None
    mine.acquire(8766)  # the lock file is still there, but nobody holds it
    assert mine.held
    mine.release()


def test_serve_json_says_who_holds_the_lock(tmp_path):
    import json

    data = mk(tmp_path / "data")
    lock = ServeLock(data)
    lock.acquire(command="dam file")
    info = json.loads((data / "serve.json").read_text(encoding="utf-8"))
    assert info["kind"] == "cli" and info["command"] == "dam file" and info["port"] is None
    lock.release()
    lock.acquire()
    lock.publish(8766)
    info = json.loads((data / "serve.json").read_text(encoding="utf-8"))
    assert info["kind"] == "serve" and info["port"] == 8766 and "command" not in info
    lock.release()


def test_serve_lock_is_exclusive_per_profile(tmp_path):
    one, two = mk(tmp_path / "one"), mk(tmp_path / "two")
    first = ServeLock(one)
    first.acquire(8766)
    other = ServeLock(one)
    with pytest.raises(Locked) as caught:
        other.acquire(8767)
    assert caught.value.port == 8766 and "8766" in str(caught.value)
    assert ServeLock.holder(one) == {"port": 8766, "command": None}
    assert ServeLock.holder(two) is None  # another profile is free
    second = ServeLock(two)
    second.acquire(8767)
    first.release()
    assert ServeLock.holder(one) is None  # released: free again
    other.acquire(8768)
    other.release()
    second.release()


# -- the reminder agent --------------------------------------------------------------------


def test_main_keeps_its_launchagent_label_and_others_get_their_own():
    assert launchd.label_for("main") == "nl.dam.remind" == launchd.LABEL
    assert launchd.label_for(None) == launchd.LABEL
    assert launchd.label_for("test") == "nl.dam.remind.test"
    assert launchd.plist_path().name == "nl.dam.remind.plist"
    assert launchd.plist_path("nl.dam.remind.test").name == "nl.dam.remind.test.plist"
    with pytest.raises(launchd.LaunchdError):
        launchd.plist_path("../evil")


def test_plist_for_a_profile_names_the_archive(tmp_path):
    import plistlib

    data = tmp_path / "base" / "archives" / "test"
    text = launchd.plist(
        ["/venv/bin/dam"], data, 7, "nl.dam.remind.test", (tmp_path / "base", "test")
    )
    parsed = plistlib.loads(text.encode())
    assert parsed["Label"] == "nl.dam.remind.test"
    assert parsed["ProgramArguments"] == [
        "/venv/bin/dam",
        "--data-dir",
        str((tmp_path / "base").resolve()),
        "--archive",
        "test",
        "remind",
    ]
    assert parsed["StandardOutPath"].startswith(str(data.resolve()))
    # the older form (one archive) is unchanged
    old = plistlib.loads(launchd.plist(["/venv/bin/dam"], tmp_path / "d", 8).encode())
    assert old["Label"] == "nl.dam.remind"
    assert "--archive" not in old["ProgramArguments"]


def test_installing_and_removing_one_profiles_agent_leaves_the_others(tmp_path, monkeypatch):
    calls = []

    class Done:
        returncode, stderr = 0, ""

    monkeypatch.setattr(launchd, "_launchctl", lambda *a: calls.append(a) or Done())
    base = tmp_path / "base"
    main_path = launchd.install(["/venv/bin/dam"], base, 8)
    test_path = launchd.install(
        ["/venv/bin/dam"],
        base / "archives" / "test",
        9,
        label=launchd.label_for("test"),
        archive=(base, "test"),
    )
    assert main_path != test_path and main_path.is_file() and test_path.is_file()
    main_text = main_path.read_text(encoding="utf-8")
    assert launchd.uninstall(label=launchd.label_for("test")) is True
    assert not test_path.exists()
    assert main_path.read_text(encoding="utf-8") == main_text  # Main's agent was not touched
    assert launchd.pins_archive() is False and launchd.pins_archive("nl.dam.remind.test") is None
    # a profile's uninstall refuses Main's file
    with pytest.raises(launchd.LaunchdError):
        launchd.uninstall(main_path, label=launchd.label_for("test"))
    assert os.path.exists(main_path)
