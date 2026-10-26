"""Changing an extra folder's label rewrites every stored path under it."""

import pytest
import yaml
from sqlalchemy import select, text

from dam import relabel
from dam.app import App
from dam.config import load_settings
from dam.core.yamledit import YamlEditError
from dam.db.engine import make_engine
from dam.db.tables import made_folders, operations
from dam.ops.model import OpFailed
from dam.snapshots import list_snapshots

RULES = """\
# rules for the old disk
- id: car  # keep this comment
  when: {text_contains: ["auto"], folder_is: "##. Organize"}
  then:
    folder: Old years/{doc_date:%Y}   # by year
- id: tmpl
  then: {folder: "{payee}/x"}
"""


@pytest.fixture
def archive(app_paths, extra_folder, fake_archive):
    """An archive with an extra folder holding indexed, tagged files, a journaled move
    inside it, a rule file and settings that name it. The app is closed again (a relabel
    runs with the archive closed)."""
    extra_folder.add("2009/a.pdf", b"a", drive_id="x1")
    extra_folder.add("2009/b.pdf", b"b", drive_id="x2")
    settings = app_paths.config_dir / "settings.yaml"
    data = yaml.safe_load(settings.read_text(encoding="utf-8"))
    data["protected_paths"] = ["##. Important", "Old years/2009/keep"]
    data["ai"] = {"exclude_folders": ["Old years/private", "Health"]}
    settings.write_text("# my settings\n" + yaml.safe_dump(data), encoding="utf-8")
    (app_paths.config_dir / "rules").mkdir(exist_ok=True)
    (app_paths.config_dir / "rules" / "mine.yaml").write_text(RULES, encoding="utf-8")
    app = App.create(app_paths.data_dir)
    try:
        app.scan()
        app.tags.add("x1", ["car"])
        moved = app.browse.move(["x2"], "Old years/2010", origin="ui")
        assert moved.failed is None
    finally:
        app.close()
    return moved.batch_id


@pytest.fixture
def engine(app_paths):
    eng = make_engine(app_paths.db_path)
    yield eng
    eng.dispose()


def _apply(app_paths, engine, old="Old years", new="Archive disk"):
    plan = relabel.plan(app_paths, engine, old, new)
    relabel.apply(app_paths, engine, plan)
    return plan


def test_rewrites_index_journal_settings_rules(app_paths, engine, archive):
    plan = relabel.plan(app_paths, engine, "Old years", "Archive disk")
    assert plan.counts["files"] >= 4  # the folder's own row, 2009, 2010 and the files
    assert plan.counts["operations"] >= 2
    assert sorted(f.path.name for f in plan.files) == ["mine.yaml", "settings.yaml"]
    relabel.apply(app_paths, engine, plan)
    with engine.connect() as conn:
        paths = set(conn.execute(text("SELECT path FROM files")).scalars())
        fts = set(conn.execute(text("SELECT path FROM file_fts")).scalars())
        journal = conn.execute(select(operations.c.src, operations.c.dst)).all()
    assert "Archive disk/2009/a.pdf" in paths and "Archive disk" in paths
    assert not any(p.startswith("Old years") for p in paths | fts)
    assert any(dst == "Archive disk/2010/b.pdf" for _, dst in journal)
    settings = load_settings(app_paths)
    assert [e.label for e in settings.extra_folders] == ["Archive disk"]
    assert settings.protected_paths == ["##. Important", "Archive disk/2009/keep"]
    assert settings.ai.exclude_folders == ["Archive disk/private", "Health"]
    raw = (app_paths.config_dir / "settings.yaml").read_text(encoding="utf-8")
    assert raw.startswith("# my settings\n")
    rules = (app_paths.config_dir / "rules" / "mine.yaml").read_text(encoding="utf-8")
    assert rules == RULES.replace("Old years/{doc_date", "Archive disk/{doc_date")
    assert [s.kind for s in list_snapshots(app_paths)] == ["before-relabel"]


def test_old_batch_still_undoable(app_paths, engine, archive, extra_folder):
    _apply(app_paths, engine)
    app = App.create(app_paths.data_dir)
    try:
        assert app.executor.undo(archive).failed is None
        assert app.repo.get("x2").path == "Archive disk/2009/b.pdf"
        assert app.tags.for_file("x1") == ["car"]
        assert app.repo.get("x1").path == "Archive disk/2009/a.pdf"
    finally:
        app.close()
    assert (extra_folder.root / "2009" / "b.pdf").exists()


def test_case_only_change(app_paths, engine, archive):
    _apply(app_paths, engine, new="old years")
    with engine.connect() as conn:
        assert "old years/2009/a.pdf" in set(conn.execute(text("SELECT path FROM files")).scalars())


def test_made_folders_rewritten(app_paths, engine, archive):
    with engine.begin() as conn:
        conn.execute(
            made_folders.insert().values(
                batch_id="b", rel="Old years/new", st_dev=1, st_ino=2, st_birth=None, created=1.0
            )
        )
    _apply(app_paths, engine)
    with engine.connect() as conn:
        assert conn.execute(select(made_folders.c.rel)).scalar_one() == "Archive disk/new"


def test_settings_failure_rolls_db_back(app_paths, engine, archive, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(relabel, "write_config_file", broken)
    plan = relabel.plan(app_paths, engine, "Old years", "Archive disk")
    with pytest.raises(OSError):
        relabel.apply(app_paths, engine, plan)
    with engine.connect() as conn:
        paths = set(conn.execute(text("SELECT path FROM files")).scalars())
    assert "Old years/2009/a.pdf" in paths and not any(p.startswith("Archive") for p in paths)
    assert load_settings(app_paths).extra_folders[0].label == "Old years"
    rules = (app_paths.config_dir / "rules" / "mine.yaml").read_text(encoding="utf-8")
    assert rules == RULES


def test_rule_file_that_cannot_be_edited_refuses_before_anything(app_paths, engine, archive):
    (app_paths.config_dir / "rules" / "folded.yaml").write_text(
        "- id: f\n  then:\n    folder: >\n      Old years/x\n", encoding="utf-8"
    )
    with pytest.raises(YamlEditError) as e:
        relabel.plan(app_paths, engine, "Old years", "Archive disk")
    assert "folded.yaml" in str(e.value) and "line 3" in str(e.value)


def test_refused_when_planned_row(app_paths, engine, archive):
    with engine.begin() as conn:
        conn.execute(operations.update().values(state="planned"))
    with pytest.raises(OpFailed) as e:
        relabel.plan(app_paths, engine, "Old years", "Archive disk")
    assert "dam recover" in str(e.value)


def test_hidden_main_entry_warned(app_paths, engine, archive, fake_archive):
    fake_archive.add("Old years/x.pdf", b"x", drive_id=None)
    plan = relabel.plan(app_paths, engine, "Old years", "Archive disk")
    assert plan.warnings == [
        "The main folder has an entry named 'Old years'. It was hidden behind the label and"
        " is indexed after the change."
    ]


def test_settings_write_untouched_keys(app_paths, engine, archive):
    """The other settings keys come back exactly as they were."""
    before = load_settings(app_paths)
    _apply(app_paths, engine)
    after = load_settings(app_paths)
    assert after.archive_root == before.archive_root
    assert after.special_folders == before.special_folders
