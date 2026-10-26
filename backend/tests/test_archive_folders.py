"""Adding, detaching and attaching extra archive folders: overlap and label rules, the
settings writes, the database-only forget, and the reserved top-level names."""

import unicodedata

import pytest
import yaml

from conftest import FakeArchive
from dam import setup
from dam.archive_folders import (
    add_folder,
    attach_folder,
    check_folder,
    check_label,
    detach_folder,
)
from dam.config import AppPaths, load_settings
from dam.core.paths import ArchivePaths
from dam.index.repo import FileRecord, TagRepo
from dam.ops.guards import check_not_label
from dam.ops.model import GuardError, Op, OpKind, Plan
from dam.profiles import ProfileStore
from dam.services.errors import InvalidRequest


def paths_of(app_paths: AppPaths) -> tuple[ArchivePaths, object]:
    settings = load_settings(app_paths)
    return ArchivePaths(settings.archive_root, settings), settings


def settings_bytes(app_paths: AppPaths) -> bytes:
    return (app_paths.config_dir / "settings.yaml").read_bytes()


def test_the_same_folder_as_main(app_paths, fake_archive):
    paths, _ = paths_of(app_paths)
    assert check_folder(fake_archive.root, paths, None, None) == (
        "That folder is already part of this archive ('the main folder')."
    )


def test_inside_main(app_paths, fake_archive):
    paths, _ = paths_of(app_paths)
    assert check_folder(fake_archive.root / "10. Financial", paths, None, None) == (
        "That folder is inside 'the main folder', which is already part of this archive."
    )


def test_around_main(app_paths, fake_archive):
    paths, _ = paths_of(app_paths)
    assert check_folder(fake_archive.root.parent, paths, None, None) == (
        "That folder contains 'the main folder', which is already part of this archive."
    )


def test_overlap_with_another_extra(app_paths, extra_folder):
    paths, _ = paths_of(app_paths)
    assert check_folder(extra_folder.root, paths, None, None) == (
        "That folder is already part of this archive ('Old years')."
    )
    assert check_folder(extra_folder.root / "2009", paths, None, None) == (
        "That folder is inside 'Old years', which is already part of this archive."
    )
    assert check_folder(extra_folder.root.parent, paths, None, None) == (
        "That folder contains 'Old years', which is already part of this archive."
    )


def test_a_symlink_to_the_main_folder(app_paths, fake_archive, tmp_path):
    link = tmp_path / "link"
    try:
        link.symlink_to(fake_archive.root, target_is_directory=True)
    except OSError:
        pytest.skip("no symlinks here")
    paths, _ = paths_of(app_paths)
    assert "already part of this archive ('the main folder')" in check_folder(
        link, paths, None, None
    )


def test_the_same_folder_in_nfd_spelling(app_paths, tmp_path):
    root = tmp_path / unicodedata.normalize("NFC", "Arkisto é")
    FakeArchive(root)
    settings_file = app_paths.config_dir / "settings.yaml"
    data = yaml.safe_load(settings_file.read_text(encoding="utf-8"))
    data["archive_root"] = str(root)
    settings_file.write_text(yaml.safe_dump(data), encoding="utf-8")
    paths, _ = paths_of(app_paths)
    nfd = tmp_path / unicodedata.normalize("NFD", "Arkisto é")
    same_folder = nfd.exists()  # a normalisation-insensitive file system (macOS)
    message = check_folder(nfd, paths, None, None)
    assert (message is not None) == same_folder


def test_inside_another_profiles_extra_folder(tmp_path):
    base = tmp_path / "base"
    a_archive, other_extra = tmp_path / "A", tmp_path / "disk" / "Other"
    for folder in (a_archive, other_extra / "sub"):
        folder.mkdir(parents=True)
    paths = AppPaths(base)
    paths.ensure()
    (paths.config_dir / "settings.yaml").write_text(
        yaml.safe_dump({"archive_root": str(a_archive)}), encoding="utf-8"
    )
    store = ProfileStore(base)
    a = store.load(persist=True)[0]
    b = store.add("Test")
    mine = tmp_path / "B"
    mine.mkdir()
    setup.write_archive_root(AppPaths(b.data_dir), mine)
    b_file = AppPaths(b.data_dir).config_dir / "settings.yaml"
    data = yaml.safe_load(b_file.read_text(encoding="utf-8"))
    data["extra_folders"] = [{"label": "Other", "path": str(other_extra)}]
    b_file.write_text(yaml.safe_dump(data), encoding="utf-8")
    settings = load_settings(AppPaths(a.data_dir))
    a_paths = ArchivePaths(a_archive, settings)
    inside = check_folder(other_extra / "sub", a_paths, store, a.id)
    assert "inside an extra archive folder of 'Test'" in inside
    assert "already an extra archive folder of 'Test'" in check_folder(
        other_extra, a_paths, store, a.id
    )
    assert "contains an extra archive folder of 'Test'" in check_folder(
        other_extra.parent, a_paths, store, a.id
    )
    elsewhere = tmp_path / "free"
    elsewhere.mkdir()
    assert check_folder(elsewhere, a_paths, store, a.id) is None


def test_an_unreadable_folder_is_refused(app_paths, tmp_path):
    paths, _ = paths_of(app_paths)
    assert "cannot be read" in check_folder(tmp_path / "nowhere", paths, None, None)


@pytest.mark.parametrize(
    "label", ["", "   ", "##. Stuff", "a/b", "Old YEARS", "old years", "10. financial"]
)
def test_label_rules_refuse(app_paths, extra_folder, label):
    paths, settings = paths_of(app_paths)
    assert check_label(label, paths, settings)


def test_a_clash_with_a_main_top_level_entry_names_it(app_paths, extra_folder, fake_archive):
    (fake_archive.root / "Elder Stuff").mkdir()
    paths, settings = paths_of(app_paths)
    assert "main folder" in check_label("ELDER stuff", paths, settings)
    assert check_label("Fresh", paths, settings) is None


def test_the_label_of_a_detached_entry_counts_as_taken(app_paths, extra_folder, app):
    detach_folder(app_paths, app.repo, "Old years", forget=False, dry_run=False)
    paths, settings = paths_of(app_paths)
    assert paths.extra_labels == ()
    assert "already" in check_label("old years", paths, settings)


def test_add_writes_the_settings_and_changes_nothing_on_disk(app_paths, fake_archive, tmp_path):
    new = tmp_path / "disk2" / "Archive"
    new.mkdir(parents=True)
    (new / "a.txt").write_text("x", encoding="utf-8")
    before = sorted(p.name for p in fake_archive.root.rglob("*"))
    change = add_folder(
        app_paths, " Archive 2016 ", new, dry_run=False, store=None, current_id=None
    )
    assert (change.label, change.path, change.files, change.reopen) == (
        "Archive 2016",
        str(new),
        0,
        True,
    )
    settings = load_settings(app_paths)
    assert [(e.label, e.path, e.attached) for e in settings.extra_folders] == [
        ("Archive 2016", new, True)
    ]
    assert sorted(p.name for p in fake_archive.root.rglob("*")) == before
    assert [p.name for p in new.iterdir()] == ["a.txt"]


def test_add_refuses_with_the_message(app_paths, fake_archive):
    with pytest.raises(InvalidRequest, match="already part of this archive"):
        add_folder(app_paths, "Same", fake_archive.root, dry_run=False, store=None, current_id=None)


def test_dry_run_writes_nothing(app_paths, extra_folder, app, tmp_path):
    new = tmp_path / "disk2"
    new.mkdir()
    before = settings_bytes(app_paths)
    added = add_folder(app_paths, "New", new, dry_run=True, store=None, current_id=None)
    detached = detach_folder(app_paths, app.repo, "Old years", forget=False, dry_run=True)
    assert not added.reopen and not detached.reopen
    assert settings_bytes(app_paths) == before


def _index_extra(app, extra, rel: str, drive_id: str) -> str:
    path = extra.add(rel, b"x", drive_id=drive_id)
    st = path.stat()
    indexed = f"Old years/{rel}"
    app.repo.upsert(
        FileRecord(
            drive_id=drive_id, path=indexed, size=st.st_size, mtime=st.st_mtime, last_seen=1.0
        )
    )
    return indexed


def test_detach_marks_rows_missing_and_attach_restores(app_paths, extra_folder, app):
    rel = _index_extra(app, extra_folder, "2009/a.pdf", "x1")
    TagRepo(app.engine).add("x1", ["taxes"])
    # a dry run reports the count and changes nothing
    preview = detach_folder(app_paths, app.repo, "Old years", forget=False, dry_run=True)
    assert preview.files == 1 and not app.repo.get("x1").missing

    change = detach_folder(app_paths, app.repo, "Old years", forget=False, dry_run=False)
    assert (change.label, change.files, change.reopen) == ("Old years", 1, True)
    entry = load_settings(app_paths).extra_folders[0]
    assert (entry.label, entry.path, entry.attached) == ("Old years", extra_folder.root, False)
    record = app.repo.get("x1")
    assert record.missing and record.path == rel
    assert TagRepo(app.engine).for_file("x1") == ["taxes"]

    back = attach_folder(app_paths, "old YEARS", dry_run=False, store=None, current_id=None)
    assert back.reopen
    assert load_settings(app_paths).extra_folders[0].attached
    # the scanner (a later step) sees the rows again; the identity and the tag stayed
    app.repo.touch_seen(["x1"], 1.0)
    record = app.repo.get("x1")
    assert record.drive_id == "x1" and not record.missing
    assert TagRepo(app.engine).for_file("x1") == ["taxes"]


def test_attach_checks_the_overlap_again(app_paths, extra_folder, app, fake_archive):
    detach_folder(app_paths, app.repo, "Old years", forget=False, dry_run=False)
    data = yaml.safe_load((app_paths.config_dir / "settings.yaml").read_text(encoding="utf-8"))
    data["extra_folders"][0]["path"] = str(fake_archive.root / "10. Financial")
    (app_paths.config_dir / "settings.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(InvalidRequest, match="inside 'the main folder'"):
        attach_folder(app_paths, "Old years", dry_run=False, store=None, current_id=None)
    assert not load_settings(app_paths).extra_folders[0].attached


def test_forget_removes_rows_only(app_paths, extra_folder, app):
    _index_extra(app, extra_folder, "2009/a.pdf", "x1")
    _index_extra(app, extra_folder, "2010/b.pdf", "x2")
    TagRepo(app.engine).add("x1", ["taxes"])
    on_disk = sorted(p.name for p in extra_folder.root.rglob("*"))
    preview = detach_folder(app_paths, app.repo, "Old years", forget=True, dry_run=True)
    assert preview.files == 2 and app.repo.get("x1") is not None
    change = detach_folder(app_paths, app.repo, "Old years", forget=True, dry_run=False)
    assert change.files == 2
    assert app.repo.get("x1") is None and app.repo.get("x2") is None
    assert TagRepo(app.engine).for_file("x1") == []
    assert sorted(p.name for p in extra_folder.root.rglob("*")) == on_disk
    assert not load_settings(app_paths).extra_folders[0].attached
    # forgetting a folder that is already detached still works, and reopens nothing
    _index_extra(app, extra_folder, "2011/c.pdf", "x3")
    again = detach_folder(app_paths, app.repo, "Old years", forget=True, dry_run=False)
    assert again.files == 1 and not again.reopen


def test_check_not_label_covers_top_level_main_entries_only(app_paths, extra_folder):
    paths, _ = paths_of(app_paths)
    with pytest.raises(GuardError, match="'OLD YEARS' is the name of an archive folder"):
        check_not_label(paths, "OLD YEARS")
    check_not_label(paths, "Old years/2009")
    check_not_label(paths, "10. Financial/old years")


def test_new_folder_named_like_label_refused(extra_folder, app, fake_archive):
    plan = Plan([Op(OpKind.MKDIR, None, "OLD YEARS")], origin="ui", new_folders=True)
    with pytest.raises(GuardError) as e:
        app.executor.preview(plan)
    assert str(e.value) == "'OLD YEARS' is the name of an archive folder. Choose another name."
    assert not (fake_archive.root / "OLD YEARS").exists()


def test_rename_of_a_top_level_entry_to_a_label_name_refused(extra_folder, app, fake_archive):
    (fake_archive.root / "Foo").mkdir()
    app.scan()
    refused = Plan([Op(OpKind.RENAME, "Foo", "old years", allow_top_level=True)], origin="ui")
    with pytest.raises(GuardError, match="name of an archive folder"):
        app.executor.preview(refused)
    allowed = Plan([Op(OpKind.RENAME, "Foo", "Bar", allow_top_level=True)], origin="ui")
    app.executor.preview(allowed)


def test_label_stays_reserved_while_detached(app_paths, extra_folder):
    from dam.app import App

    f = app_paths.config_dir / "settings.yaml"
    data = yaml.safe_load(f.read_text(encoding="utf-8"))
    data["extra_folders"][0]["attached"] = False
    f.write_text(yaml.safe_dump(data), encoding="utf-8")
    application = App.create(app_paths.data_dir)
    try:
        assert application.paths.extra_labels == ()
        plan = Plan([Op(OpKind.MKDIR, None, "OLD YEARS")], origin="ui", new_folders=True)
        with pytest.raises(GuardError, match="is the name of an archive folder"):
            application.executor.preview(plan)
    finally:
        application.close()


def test_attach_refused_when_a_main_entry_took_the_label(
    app_paths, extra_folder, app, fake_archive
):
    detach_folder(app_paths, app.repo, "Old years", forget=False, dry_run=False)
    (fake_archive.root / "old YEARS").mkdir()
    with pytest.raises(InvalidRequest, match="already the name of a folder in the main folder"):
        attach_folder(app_paths, "Old years", dry_run=False, store=None, current_id=None)
    assert not load_settings(app_paths).extra_folders[0].attached


def test_detach_dry_run_count_matches_the_real_one(app_paths, extra_folder, app):
    from dam.index.repo import FileRecord

    _index_extra(app, extra_folder, "2009/a.pdf", "x1")
    path = extra_folder.add("2010/b.pdf", b"x", drive_id="x2")
    app.repo.upsert(  # a row that was never seen (NULL last_seen)
        FileRecord(drive_id="x2", path="Old years/2010/b.pdf", size=1, mtime=path.stat().st_mtime)
    )
    preview = detach_folder(app_paths, app.repo, "Old years", forget=False, dry_run=True)
    real = detach_folder(app_paths, app.repo, "Old years", forget=False, dry_run=False)
    assert preview.files == real.files == 2
