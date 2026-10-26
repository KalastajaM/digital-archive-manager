"""Smaller reliability fixes: name spelling on case-sensitive volumes, a journal write
that fails after the change, directory fsyncs, Windows-safe target names."""

import unicodedata
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from dam.config import Settings
from dam.core.paths import ArchivePaths
from dam.db.tables import operations
from dam.index.repo import FileRepo
from dam.ops import primitives
from dam.ops.executor import Executor
from dam.ops.guards import validate
from dam.ops.model import ABS_TARGET, GuardError, Op, OpKind, Plan
from dam.ops.planner import _Sim


@pytest.fixture
def paths(fake_archive) -> ArchivePaths:
    return ArchivePaths(fake_archive.root, Settings(archive_root=fake_archive.root))


def _listing(monkeypatch, folder: Path, names: list[str]) -> None:
    """Make ``folder.iterdir()`` list ``names`` in this order (any filesystem)."""
    real = Path.iterdir

    def fake(self):
        if self == folder:
            return iter([folder / n for n in names])
        return real(self)

    monkeypatch.setattr(Path, "iterdir", fake)


def test_exact_spelling_wins_on_a_case_sensitive_volume(fake_archive, paths, monkeypatch):
    # Both names exist on ext4 or case-sensitive APFS; on a case-insensitive disk the
    # second add writes the same file, which is fine for a spelling lookup.
    fake_archive.add("A/Report.pdf")
    fake_archive.add("A/report.pdf")
    _listing(monkeypatch, fake_archive.root / "A", ["report.pdf", "Report.pdf"])
    sim = _Sim(paths)
    assert sim.spell("A/Report.pdf") == "A/Report.pdf"
    assert sim.spell("A/report.pdf") == "A/report.pdf"
    _listing(monkeypatch, fake_archive.root / "A", ["Report.pdf", "report.pdf"])
    assert sim.spell("A/report.pdf") == "A/report.pdf"
    assert sim.spell("A/REPORT.pdf") == "A/Report.pdf"  # no exact one: first folded match


def test_same_normal_form_wins_over_other_case(fake_archive, paths, monkeypatch):
    nfd = unicodedata.normalize("NFD", "Kuitti_ä.pdf")
    fake_archive.add("A/KUITTI_Ä.pdf")
    fake_archive.add("A/" + nfd)
    _listing(monkeypatch, fake_archive.root / "A", ["KUITTI_Ä.pdf", nfd])
    sim = _Sim(paths)
    assert sim.spell("A/Kuitti_ä.pdf") == "A/" + nfd


# --- the journal cannot record a change that was made ------------------------------


def test_change_made_but_not_recorded_stops_and_says_so(fake_archive, paths, engine, monkeypatch):
    fake_archive.add("##. Organize/a.pdf", drive_id="id-a")
    fake_archive.add("##. Organize/b.pdf", drive_id="id-b")
    ex = Executor(paths, engine, FileRepo(engine, inbox="##. Organize"))
    real = ex._journal_finish

    def finish(op_id, state, *args, **kwargs):
        if state == "done":
            raise OperationalError("UPDATE operations", {}, Exception("database is locked"))
        return real(op_id, state, *args, **kwargs)

    monkeypatch.setattr(ex, "_journal_finish", finish)
    result = ex.apply(
        Plan(
            ops=[
                Op(OpKind.RENAME, "##. Organize/a.pdf", "a2.pdf"),
                Op(OpKind.RENAME, "##. Organize/b.pdf", "b2.pdf"),
            ],
            origin="cli",
        )
    )
    assert (fake_archive.root / "##. Organize/a2.pdf").exists()  # the first change happened
    assert (fake_archive.root / "##. Organize/b.pdf").exists()  # and the batch stopped there
    assert result.done == [] and result.failed is not None
    assert result.failed.src == "##. Organize/a.pdf"
    assert "was made" in result.error and "Run recovery" in result.error
    assert "database is locked" in result.error
    with engine.connect() as conn:
        states = [r.state for r in conn.execute(select(operations.c.state))]
    assert states == ["planned"]
    monkeypatch.undo()
    recovered = ex.recover()
    assert [e.state for e in recovered.entries] == ["done"]


# --- folders are synced after a rename or a new folder -----------------------------


@pytest.fixture
def synced(monkeypatch) -> list[Path]:
    calls: list[Path] = []
    monkeypatch.setattr(primitives, "sync_dir", lambda folder: calls.append(Path(folder)))
    return calls


def test_rename_syncs_both_folders(tmp_path, synced):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a/f.pdf").write_bytes(b"x")
    primitives.rename_excl(tmp_path / "a/f.pdf", tmp_path / "b/f.pdf")
    assert synced == [tmp_path / "b", tmp_path / "a"]
    synced.clear()
    primitives.rename_excl(tmp_path / "b/f.pdf", tmp_path / "b/g.pdf")
    assert synced == [tmp_path / "b"]


def test_failed_rename_syncs_nothing(tmp_path, synced):
    (tmp_path / "f.pdf").write_bytes(b"x")
    (tmp_path / "g.pdf").write_bytes(b"y")
    with pytest.raises(FileExistsError):
        primitives.rename_excl(tmp_path / "f.pdf", tmp_path / "g.pdf")
    assert synced == []


def test_new_folder_and_placed_copy_sync_their_folder(tmp_path, synced):
    primitives.make_dir(tmp_path / "new")
    assert synced == [tmp_path]
    synced.clear()
    (tmp_path / "src.pdf").write_bytes(b"data")
    primitives.copy_across(tmp_path / "src.pdf", tmp_path / "new/src.pdf")
    assert synced == [tmp_path / "new"]


def test_case_only_rename_syncs_its_folder(tmp_path, synced):
    (tmp_path / "f.pdf").write_bytes(b"x")
    if not (tmp_path / "F.pdf").exists():
        pytest.skip("case-sensitive file system")
    primitives.rename_case_only(tmp_path / "f.pdf", tmp_path / "F.pdf")
    assert synced == [tmp_path]


def test_sync_dir_is_best_effort(tmp_path, monkeypatch):
    primitives.sync_dir(tmp_path)  # a real folder: no error
    primitives.sync_dir(tmp_path / "missing")  # cannot be opened: ignored
    opened = []
    monkeypatch.setattr(primitives, "_is_windows", lambda: True)
    monkeypatch.setattr(primitives.os, "open", lambda *a, **k: opened.append(a))
    primitives.sync_dir(tmp_path)
    assert opened == []  # Windows: skipped


def test_copy_asks_for_a_full_flush_on_macos(tmp_path, monkeypatch):
    asked: list[int] = []

    class FakeFcntl:
        F_FULLFSYNC = 51

        @staticmethod
        def fcntl(fd, cmd):
            asked.append(cmd)

    fsynced: list[int] = []
    monkeypatch.setattr(primitives.sys, "platform", "darwin")
    monkeypatch.setattr(primitives, "fcntl", FakeFcntl)
    monkeypatch.setattr(primitives.os, "fsync", lambda fd: fsynced.append(fd))
    (tmp_path / "src.pdf").write_bytes(b"data")
    primitives.copy_file(tmp_path / "src.pdf", tmp_path / "dst.pdf")
    assert asked == [51] and fsynced == []

    class Refusing(FakeFcntl):
        @staticmethod
        def fcntl(fd, cmd):
            raise OSError("not supported")

    monkeypatch.setattr(primitives, "fcntl", Refusing)
    primitives.copy_file(tmp_path / "src.pdf", tmp_path / "dst2.pdf")
    assert len(fsynced) == 1  # falls back to fsync


# --- new names must also work on Windows and cloud drives --------------------------

BAD_NAMES = [
    "CON.pdf",
    "aux",
    "Lpt1.txt",
    "report.",
    "report ",
    "a:b.pdf",
    'a"b.pdf',
    "a?.pdf",
    "a|b.pdf",
    "a<b>.pdf",
    "a*.pdf",
    "tab\there.pdf",
]


@pytest.mark.parametrize("name", BAD_NAMES)
def test_new_names_windows_refuses_are_refused(paths, name):
    src = "10. Financial/Banks/a.pdf"
    for op in (
        Op(OpKind.RENAME, src, name),
        Op(OpKind.MOVE, src, "10. Financial", name=name),
        Op(OpKind.COPY, src, "10. Financial", name=name),
        Op(OpKind.COPY, ABS_TARGET + str(Path.cwd() / "x.pdf"), "##. Organize", name=name),
    ):
        with pytest.raises(GuardError) as e:
            validate(op, paths)
        assert "Windows" in str(e.value) or "cannot" in str(e.value)


def test_plain_names_still_pass(paths):
    src = "10. Financial/Banks/a.pdf"
    validate(Op(OpKind.RENAME, src, "COM10 report.pdf"), paths)
    validate(Op(OpKind.MOVE, src, "10. Financial", name="Console.pdf"), paths)


@pytest.mark.parametrize("name", ["CON.pdf", "a:b.pdf", "report."])
def test_existing_names_are_left_alone(paths, name):
    # a file that already has such a name still moves and copies under it
    src = f"10. Financial/Banks/{name}"
    validate(Op(OpKind.MOVE, src, "10. Financial"), paths)
    validate(Op(OpKind.MOVE, src, "10. Financial", name=name), paths)
    validate(Op(OpKind.COPY, src, "10. Financial"), paths)
    validate(Op(OpKind.RENAME, src, "fine.pdf"), paths)


def test_undo_may_give_back_an_old_name(paths):
    validate(
        Op(OpKind.RENAME, "10. Financial/Banks/fine.pdf", "CON.pdf", exact=True),
        paths,
        restore=True,
    )


# --- settings files: the backup is on the disk before the file is rewritten ---------


def _record_syncs(monkeypatch, module) -> list[str]:
    synced: list[str] = []
    real = module.to_disk

    def record(f):
        real(f)
        synced.append(Path(f.name).name)

    monkeypatch.setattr(module, "to_disk", record)
    return synced


def test_config_file_backup_is_synced_before_the_rewrite(tmp_path, monkeypatch):
    from dam.codes import configfile

    synced = _record_syncs(monkeypatch, configfile)
    path = tmp_path / "codes.yaml"
    path.write_text("old: 1\n", encoding="utf-8")
    configfile.write_config_file(path, "new: 2\n", verify=lambda: True)
    assert len(synced) == 2
    assert synced[0].startswith("codes.yaml.bak-") and synced[1] == "codes.yaml"
    assert path.read_text(encoding="utf-8") == "new: 2\n"


def test_settings_backup_is_synced_before_the_rewrite(app_paths, monkeypatch):
    from dam import setup

    synced = _record_syncs(monkeypatch, setup)
    setup.write_ai_exclude_folders(app_paths, ["Private"])
    assert len(synced) == 2
    assert synced[0].startswith("settings.yaml.bak-") and synced[1] == "settings.yaml"


def test_rules_state_keeps_a_backup_and_falls_back_to_it(tmp_path, monkeypatch):
    from dam.rules import state as rules_state

    synced = _record_syncs(monkeypatch, rules_state)
    rules_state.save_state(tmp_path, rules_state.RulesState(offer=False))
    assert synced == ["rules-state.json"]  # nothing to back up yet
    synced.clear()
    rules_state.save_state(tmp_path, rules_state.RulesState(offer=True, declined=[["kela"]]))
    assert synced == ["rules-state.json.bak", "rules-state.json"]
    assert rules_state.load_state(tmp_path) == rules_state.RulesState(True, [["kela"]])
    # a crash part way through the write: the backup is used
    (tmp_path / "rules-state.json").write_text('{"offer": tr', encoding="utf-8")
    assert rules_state.load_state(tmp_path) == rules_state.RulesState(offer=False)
    # and a broken file never replaces the good backup
    rules_state.save_state(tmp_path, rules_state.RulesState(offer=True))
    backup = (tmp_path / "rules-state.json.bak").read_text(encoding="utf-8")
    assert '"offer": false' in backup
