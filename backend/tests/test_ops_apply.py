import os
import unicodedata
from pathlib import Path

import pytest
from sqlalchemy import insert, select, text

from conftest import needs_dir_fd
from dam.config import Settings
from dam.core.fs import readlink
from dam.core.paths import ArchivePaths
from dam.db.tables import files, operations
from dam.index.driveid import read_drive_id
from dam.index.repo import FileRepo
from dam.ops import identity, primitives
from dam.ops.executor import Executor
from dam.ops.model import GuardError, Op, OpKind, Plan
from fsswap import recreate_dir

K = OpKind


@pytest.fixture
def paths(fake_archive) -> ArchivePaths:
    return ArchivePaths(fake_archive.root, Settings(archive_root=fake_archive.root))


@pytest.fixture
def executor(paths, engine) -> Executor:
    return Executor(paths, engine, FileRepo(engine, inbox="##. Organize"))


def journal(engine) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(select(operations).order_by(operations.c.id)).mappings().all()
    return [dict(r) for r in rows]


def tree(root: Path) -> dict[str, object]:
    out: dict[str, object] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for n in dirnames + filenames:
            p = Path(dirpath) / n
            rel = p.relative_to(root).as_posix()
            if p.is_symlink():
                out[rel] = ("link", readlink(p))
            elif p.is_dir():
                out[rel] = ("dir",)
            else:
                out[rel] = ("file", p.read_bytes(), read_drive_id(p))
    return out


def plan(*ops: Op) -> Plan:
    return Plan(ops=list(ops), origin="cli")


def test_rename_in_place(fake_archive, executor, engine):
    fake_archive.add("##. Organize/File_000.pdf", drive_id="id-1")
    result = executor.apply(plan(Op(K.RENAME, "##. Organize/File_000.pdf", "20261013_Taxcard.pdf")))
    assert result.failed is None and result.error is None
    assert not (fake_archive.root / "##. Organize/File_000.pdf").exists()
    new = fake_archive.root / "##. Organize/20261013_Taxcard.pdf"
    assert read_drive_id(new) == "id-1"
    rows = journal(engine)
    assert len(rows) == 1
    row = rows[0]
    assert row["state"] == "done"
    assert row["kind"] == K.RENAME
    assert row["src"] == "##. Organize/File_000.pdf"
    assert row["dst"] == "##. Organize/20261013_Taxcard.pdf"
    assert row["drive_id"] == "id-1"
    assert row["size"] == 1
    assert row["origin"] == "cli"
    assert row["batch_id"] == result.batch_id
    assert row["seq"] == 0
    assert row["created"] is not None and row["finished"] is not None


def test_move_to_existing_folder(fake_archive, executor):
    fake_archive.add("##. Organize/a.pdf", drive_id="id-a")
    result = executor.apply(plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks")))
    assert result.failed is None
    moved = fake_archive.root / "10. Financial/Banks/a.pdf"
    assert moved.exists()
    assert read_drive_id(moved) == "id-a"
    assert [r.dst for r in result.done] == ["10. Financial/Banks/a.pdf"]


def test_collision_gets_suffix(fake_archive, executor):
    fake_archive.add("##. Organize/a.pdf", content=b"new")
    existing = fake_archive.add("10. Financial/Banks/a.pdf", content=b"original")
    result = executor.apply(plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks")))
    assert result.failed is None
    assert result.done[-1].dst.endswith("_2.pdf")
    assert result.done[-1].note == "renamed to avoid collision"
    assert existing.read_bytes() == b"original"
    assert (fake_archive.root / "10. Financial/Banks/a_2.pdf").read_bytes() == b"new"


def test_missing_folder_creates_mkdir(fake_archive, executor):
    fake_archive.add("##. Organize/a.pdf")
    resolved = executor.preview(
        plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks/2026/Q4"))
    )
    assert [(r.kind, r.src, r.dst) for r in resolved] == [
        (K.MKDIR, None, "10. Financial/Banks/2026"),
        (K.MKDIR, None, "10. Financial/Banks/2026/Q4"),
        (K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks/2026/Q4/a.pdf"),
    ]
    result = executor.apply(plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks/2026/Q4")))
    assert result.failed is None
    assert (fake_archive.root / "10. Financial/Banks/2026/Q4/a.pdf").exists()


def test_new_top_level_folder_refused(fake_archive, executor, engine):
    fake_archive.add("##. Organize/a.pdf")
    with pytest.raises(GuardError):
        executor.apply(plan(Op(K.MOVE, "##. Organize/a.pdf", "99. New")))
    assert not (fake_archive.root / "99. New").exists()
    assert journal(engine) == []


def test_new_top_level_folder_allowed_with_flag(fake_archive, executor):
    fake_archive.add("##. Organize/a.pdf")
    op = Op(K.MOVE, "##. Organize/a.pdf", "99. New", allow_top_level=True)
    assert executor.apply(plan(op)).failed is None
    assert (fake_archive.root / "99. New/a.pdf").exists()


def test_quarantine_mirrors_path(fake_archive, executor):
    fake_archive.add("10. Financial/Banks/a.pdf", drive_id="id-q")
    result = executor.apply(plan(Op(K.QUARANTINE, "10. Financial/Banks/a.pdf", None)))
    assert result.failed is None
    target = fake_archive.root / "##. To Delete/10. Financial/Banks/a.pdf"
    assert target.exists()
    assert read_drive_id(target) == "id-q"
    assert not (fake_archive.root / "10. Financial/Banks/a.pdf").exists()
    assert [r.kind for r in result.done] == [K.MKDIR, K.MKDIR, K.QUARANTINE]


def test_quarantine_collision_gets_suffix(fake_archive, executor):
    fake_archive.add("10. Financial/Banks/a.pdf", content=b"second")
    old = fake_archive.add("##. To Delete/10. Financial/Banks/a.pdf", content=b"first")
    result = executor.apply(plan(Op(K.QUARANTINE, "10. Financial/Banks/a.pdf", None)))
    assert result.done[-1].dst == "##. To Delete/10. Financial/Banks/a_2.pdf"
    assert old.read_bytes() == b"first"


def test_quarantine_protected_refused(fake_archive, executor):
    f = fake_archive.add("##. Important/x.pdf")
    with pytest.raises(GuardError):
        executor.apply(plan(Op(K.QUARANTINE, "##. Important/x.pdf", None)))
    assert f.exists()


def test_quarantine_protected_case_variant_refused(fake_archive, executor):
    fake_archive.add("##. Important/x.pdf")
    with pytest.raises(GuardError):
        executor.preview(plan(Op(K.QUARANTINE, "##. important/x.pdf", None)))


def test_quarantine_folder_containing_protected_refused(fake_archive, paths, engine):
    paths.settings.protected_paths = ["10. Financial/Banks/Keep"]
    fake_archive.add("10. Financial/Banks/Keep/x.pdf")
    ex = Executor(paths, engine, FileRepo(engine, inbox="##. Organize"))
    with pytest.raises(GuardError):
        ex.preview(plan(Op(K.QUARANTINE, "10. Financial/Banks", None)))


def test_quarantine_already_quarantined_refused(fake_archive, executor):
    fake_archive.add("##. To Delete/a.pdf")
    with pytest.raises(GuardError):
        executor.preview(plan(Op(K.QUARANTINE, "##. To Delete/a.pdf", None)))


def test_move_protected_into_quarantine_refused(fake_archive, executor):
    fake_archive.add("##. Important/x.pdf")
    with pytest.raises(GuardError):
        executor.preview(plan(Op(K.MOVE, "##. Important/x.pdf", "##. To Delete")))


def test_move_into_protected_allowed(fake_archive, executor):
    fake_archive.add("##. Organize/a.pdf")
    assert executor.apply(plan(Op(K.MOVE, "##. Organize/a.pdf", "##. Important"))).failed is None
    assert (fake_archive.root / "##. Important/a.pdf").exists()


@pytest.mark.parametrize(
    "op",
    [
        Op(K.MOVE, "../evil", "10. Financial"),
        Op(K.MOVE, "/etc/passwd", "10. Financial"),
        Op(K.MOVE, "##. Organize/a.pdf", "../outside"),
        Op(K.RENAME, "##. Organize/a.pdf", "../a.pdf"),
        Op(K.RENAME, "##. Organize/a.pdf", "sub/a.pdf"),
        Op(K.QUARANTINE, "../evil", None),
        Op(K.SYMLINK, "../evil", "##. Ongoing/l"),
    ],
)
def test_outside_root_refused(fake_archive, executor, op):
    fake_archive.add("##. Organize/a.pdf")
    with pytest.raises(GuardError):
        executor.apply(plan(op))


def test_outside_root_via_symlinked_dir_refused(fake_archive, executor, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.pdf").write_bytes(b"s")
    (fake_archive.root / "10. Financial/escape").symlink_to(outside)
    with pytest.raises(GuardError):
        executor.preview(plan(Op(K.MOVE, "10. Financial/escape/secret.pdf", "10. Financial/Banks")))


def test_symlinked_dir_inside_archive_not_followed(fake_archive, executor):
    fake_archive.add("10. Financial/Banks/a.pdf")
    fake_archive.add("##. Organize/b.pdf")
    fake_archive.link("##. Ongoing/banks", "10. Financial/Banks")
    with pytest.raises(GuardError):
        executor.preview(plan(Op(K.MOVE, "##. Ongoing/banks/a.pdf", "##. Organize")))
    with pytest.raises(GuardError):
        executor.preview(plan(Op(K.MOVE, "##. Organize/b.pdf", "##. Ongoing/banks")))


@pytest.mark.parametrize(
    "op",
    [
        Op(K.MOVE, "", "10. Financial"),
        Op(K.MOVE, "10. Financial", "##. Organize"),
        Op(K.RENAME, "10. Financial", "11. Money"),
        Op(K.QUARANTINE, "10. Financial", None),
        Op(K.MOVE, "##. Organize/a.pdf", ""),
        Op(K.MKDIR, None, ""),
        Op(K.MOVE, "##. Organize/a.pdf", "", allow_top_level=True),
        Op(K.SYMLINK, "##. Organize/a.pdf", "", allow_top_level=True),
        Op(K.MKDIR, None, "", allow_top_level=True),
    ],
)
def test_root_and_top_level_refused(fake_archive, executor, op):
    fake_archive.add("##. Organize/a.pdf")
    with pytest.raises(GuardError):
        executor.preview(plan(op))


def test_move_dir_into_itself_refused(fake_archive, executor):
    fake_archive.add("10. Financial/Banks/a.pdf")
    with pytest.raises(GuardError):
        executor.preview(plan(Op(K.MOVE, "10. Financial/Banks", "10. Financial/Banks/sub")))


def test_dry_run_changes_nothing(fake_archive, executor, engine):
    fake_archive.add("##. Organize/a.pdf")
    fake_archive.add("10. Financial/Banks/a.pdf")
    before_tree, before_journal = tree(fake_archive.root), journal(engine)
    p = plan(
        Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks/2026"),
        Op(K.QUARANTINE, "10. Financial/Banks/a.pdf", None),
    )
    result = executor.apply(p, dry_run=True)
    assert result.dry_run
    assert result.failed is None
    assert [r.kind for r in result.done] == [K.MKDIR, K.MOVE, K.MKDIR, K.MKDIR, K.QUARANTINE]
    assert tree(fake_archive.root) == before_tree
    assert journal(engine) == before_journal


def test_src_vanished_between_preview_and_apply(fake_archive, executor, engine, monkeypatch):
    a = fake_archive.add("##. Organize/a.pdf")
    fake_archive.add("##. Organize/b.pdf")
    p = plan(
        Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks"),
        Op(K.MOVE, "##. Organize/b.pdf", "10. Financial/Banks"),
    )
    resolved = executor.preview(p)
    os.remove(a)
    monkeypatch.setattr(Executor, "preview", lambda self, plan: resolved)
    result = executor.apply(p)
    assert result.done == []
    assert result.failed is not None and result.failed.src == "##. Organize/a.pdf"
    assert "no longer there" in result.error
    rows = journal(engine)
    assert [r["state"] for r in rows] == ["failed"]
    assert "no longer there" in rows[0]["error"]
    assert (fake_archive.root / "##. Organize/b.pdf").exists()
    assert not (fake_archive.root / "10. Financial/Banks/b.pdf").exists()


def test_src_replaced_between_preview_and_apply(fake_archive, executor, monkeypatch):
    fake_archive.add("##. Organize/a.pdf", drive_id="id-old")
    p = plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks"))
    resolved = executor.preview(p)
    fake_archive.add("##. Organize/a.pdf", drive_id="id-other")
    monkeypatch.setattr(Executor, "preview", lambda self, plan: resolved)
    result = executor.apply(p)
    assert result.failed is not None
    assert (fake_archive.root / "##. Organize/a.pdf").exists()


def test_moving_symlink_keeps_target(fake_archive, executor):
    target = fake_archive.add("10. Financial/Banks/a.pdf", content=b"payload", drive_id="id-t")
    link = fake_archive.link("##. Ongoing/a.pdf", "10. Financial/Banks/a.pdf")
    link_target = readlink(link)
    (fake_archive.root / "##. Ongoing/Taxes").mkdir()
    result = executor.apply(plan(Op(K.MOVE, "##. Ongoing/a.pdf", "##. Ongoing/Taxes")))
    assert result.failed is None
    moved = fake_archive.root / "##. Ongoing/Taxes/a.pdf"
    assert moved.is_symlink()
    assert readlink(moved) == link_target
    assert moved.read_bytes() == b"payload"
    assert target.read_bytes() == b"payload"
    assert read_drive_id(target) == "id-t"


def test_batch_stops_on_first_failure(fake_archive, executor, engine, monkeypatch):
    for n in ("a", "b", "c"):
        fake_archive.add(f"##. Organize/{n}.pdf")
    p = plan(*(Op(K.MOVE, f"##. Organize/{n}.pdf", "10. Financial/Banks") for n in "abc"))
    resolved = executor.preview(p)
    # Something appears at the 2nd op's destination after preview: never overwrite.
    blocker = fake_archive.add("10. Financial/Banks/b.pdf", content=b"blocker")
    monkeypatch.setattr(Executor, "preview", lambda self, plan: resolved)
    result = executor.apply(p)
    assert [r.src for r in result.done] == ["##. Organize/a.pdf"]
    assert result.failed is not None and result.failed.src == "##. Organize/b.pdf"
    assert "already exists" in result.error
    assert blocker.read_bytes() == b"blocker"
    assert (fake_archive.root / "##. Organize/b.pdf").exists()
    assert (fake_archive.root / "##. Organize/c.pdf").exists()
    assert [(r["src"], r["state"]) for r in journal(engine)] == [
        ("##. Organize/a.pdf", "done"),
        ("##. Organize/b.pdf", "failed"),
    ]


def test_journal_rows_committed_per_op(fake_archive, executor, engine, monkeypatch):
    fake_archive.add("##. Organize/a.pdf")

    def crash(src, dst):
        raise SystemExit("simulated crash")

    monkeypatch.setattr(primitives, "rename_excl", crash)
    with pytest.raises(SystemExit):
        executor.apply(plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks")))
    rows = journal(engine)
    assert [r["state"] for r in rows] == ["planned"]
    assert (fake_archive.root / "##. Organize/a.pdf").exists()


def test_case_only_rename(fake_archive, executor):
    fake_archive.add("##. Organize/File.pdf", drive_id="id-c")
    result = executor.apply(plan(Op(K.RENAME, "##. Organize/File.pdf", "file.pdf")))
    assert result.failed is None, result.error
    assert result.done[0].dst == "##. Organize/file.pdf"
    assert result.done[0].note is None
    names = os.listdir(fake_archive.root / "##. Organize")
    assert names == ["file.pdf"]
    assert read_drive_id(fake_archive.root / "##. Organize/file.pdf") == "id-c"


def test_rename_then_move_without_collision(fake_archive, executor):
    fake_archive.add("##. Organize/scan.pdf", content=b"mine")
    result = executor.apply(
        plan(
            Op(K.RENAME, "##. Organize/scan.pdf", "20261013_Tax.pdf"),
            Op(K.MOVE, "##. Organize/20261013_Tax.pdf", "10. Financial/Banks"),
        )
    )
    assert result.failed is None, result.error
    assert (fake_archive.root / "10. Financial/Banks/20261013_Tax.pdf").read_bytes() == b"mine"


def test_reference_to_collided_name_that_still_exists_is_ambiguous(fake_archive, executor):
    # Op 2 could mean the renamed file (now X_2) or the other file still called X.
    fake_archive.add("##. Organize/scan.pdf", content=b"mine")
    fake_archive.add("##. Organize/20261013_Tax.pdf", content=b"other")
    with pytest.raises(GuardError, match="ambiguous"):
        executor.preview(
            plan(
                Op(K.RENAME, "##. Organize/scan.pdf", "20261013_Tax.pdf"),
                Op(K.MOVE, "##. Organize/20261013_Tax.pdf", "10. Financial/Banks"),
            )
        )


def test_quarantine_of_collided_original_is_ambiguous(fake_archive, executor, engine):
    fake_archive.add("##. Organize/a.pdf", content=b"new")
    fake_archive.add("10. Financial/Banks/a.pdf", content=b"old")
    before = tree(fake_archive.root)
    with pytest.raises(GuardError, match="ambiguous"):
        executor.apply(
            plan(
                Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks"),
                Op(K.QUARANTINE, "10. Financial/Banks/a.pdf", None),
            )
        )
    assert tree(fake_archive.root) == before
    assert journal(engine) == []


def test_reference_to_vacated_collided_name_is_redirected_with_note(fake_archive, executor):
    fake_archive.add("##. Organize/X.pdf", content=b"other")
    fake_archive.add("##. Organize/scan.pdf", content=b"mine")
    result = executor.apply(
        plan(
            Op(K.MOVE, "##. Organize/X.pdf", "10. Financial/Banks"),  # vacates X.pdf
            Op(K.RENAME, "##. Organize/scan.pdf", "X.pdf"),  # conservative: gets X_2
            Op(K.MOVE, "##. Organize/X.pdf", "10. Financial"),  # means the renamed file
        )
    )
    assert result.failed is None, result.error
    last = result.done[-1]
    assert (last.src, last.dst) == ("##. Organize/X_2.pdf", "10. Financial/X_2.pdf")
    assert last.note and "redirected" in last.note
    assert (fake_archive.root / "10. Financial/X_2.pdf").read_bytes() == b"mine"
    assert (fake_archive.root / "10. Financial/Banks/X.pdf").read_bytes() == b"other"


def test_quarantine_of_entry_moved_out_of_protected_refused(fake_archive, executor, engine):
    fake_archive.add("##. Important/x.pdf")
    with pytest.raises(GuardError, match="protected"):
        executor.apply(
            plan(
                Op(K.MOVE, "##. Important/x.pdf", "10. Financial"),
                Op(K.QUARANTINE, "10. Financial/x.pdf", None),
            )
        )
    assert (fake_archive.root / "##. Important/x.pdf").exists()
    assert journal(engine) == []


def test_quarantine_of_folder_holding_protected_origin_refused(fake_archive, executor):
    fake_archive.add("##. Important/x.pdf")
    with pytest.raises(GuardError, match="protected"):
        executor.preview(
            plan(
                Op(K.MOVE, "##. Important/x.pdf", "10. Financial/Banks"),
                Op(K.MOVE, "10. Financial/Banks", "##. To Delete"),
            )
        )


def test_verify_failure_after_act_is_unverified(fake_archive, executor, engine, monkeypatch):
    fake_archive.add("##. Organize/a.pdf", content=b"abc")
    fake_archive.add("##. Organize/b.pdf")
    real = primitives.rename_excl

    def rename_then_grow(src, dst):
        real(src, dst)
        with open(dst, "ab") as f:  # size changes between act and verify
            f.write(b"more")

    monkeypatch.setattr(primitives, "rename_excl", rename_then_grow)
    result = executor.apply(
        plan(
            Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks"),
            Op(K.MOVE, "##. Organize/b.pdf", "10. Financial/Banks"),
        )
    )
    assert result.done == []
    assert result.failed is not None and result.failed.src == "##. Organize/a.pdf"
    assert "Could not confirm" in result.error
    rows = journal(engine)
    assert [r["state"] for r in rows] == ["unverified"]
    assert "Could not confirm" in rows[0]["error"]
    assert (fake_archive.root / "10. Financial/Banks/a.pdf").exists()
    assert (fake_archive.root / "##. Organize/b.pdf").exists()


def test_index_error_keeps_done_and_stops(fake_archive, executor, engine):
    fake_archive.add("##. Organize/a.pdf", drive_id="id-a")
    fake_archive.add("##. Organize/b.pdf")
    with engine.begin() as conn:
        conn.execute(
            insert(files),
            [
                {
                    "drive_id": "id-a",
                    "path": "##. Organize/a.pdf",
                    "path_nfc": "##. Organize/a.pdf",
                    "name": "a.pdf",
                    "is_dir": False,
                },
                # stale row already claiming the destination path -> UNIQUE conflict
                {
                    "drive_id": "stale",
                    "path": "10. Financial/Banks/a.pdf",
                    "path_nfc": "10. Financial/Banks/a.pdf",
                    "name": "a.pdf",
                    "is_dir": False,
                },
            ],
        )
    result = executor.apply(
        plan(
            Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks"),
            Op(K.MOVE, "##. Organize/b.pdf", "10. Financial/Banks"),
        )
    )
    assert result.failed is None
    assert result.index_error and "10. Financial/Banks/a.pdf" in result.index_error
    assert [r.src for r in result.done] == ["##. Organize/a.pdf"]
    assert [r["state"] for r in journal(engine)] == ["done"]
    assert (fake_archive.root / "10. Financial/Banks/a.pdf").exists()
    assert (fake_archive.root / "##. Organize/b.pdf").exists()


def test_paths_take_on_disk_spelling(fake_archive, executor, engine):
    fake_archive.add("##. Organize/Scan.pdf")
    (fake_archive.root / "10. Financial/Banks/Northbank").mkdir()
    result = executor.apply(
        plan(Op(K.MOVE, "##. organize/scan.PDF", "10. financial/banks/northbank/2026"))
    )
    assert result.failed is None, result.error
    assert [(r.kind, r.src, r.dst) for r in result.done] == [
        (K.MKDIR, None, "10. Financial/Banks/Northbank/2026"),
        (K.MOVE, "##. Organize/Scan.pdf", "10. Financial/Banks/Northbank/2026/Scan.pdf"),
    ]
    assert [r["dst"] for r in journal(engine)] == [
        "10. Financial/Banks/Northbank/2026",
        "10. Financial/Banks/Northbank/2026/Scan.pdf",
    ]
    assert os.listdir(fake_archive.root / "10. Financial/Banks/Northbank/2026") == ["Scan.pdf"]


def test_mkdir_journal_row(fake_archive, executor, engine):
    result = executor.apply(plan(Op(K.MKDIR, None, "10. Financial/Banks/2027")))
    assert result.failed is None, result.error
    (row,) = journal(engine)
    assert (row["kind"], row["src"], row["dst"], row["state"]) == (
        K.MKDIR,
        None,
        "10. Financial/Banks/2027",
        "done",
    )
    assert (fake_archive.root / "10. Financial/Banks/2027").is_dir()


def test_mkdir_existing_folder_is_noop(fake_archive, executor, engine):
    assert executor.apply(plan(Op(K.MKDIR, None, "10. Financial/Banks"))).done == []
    assert journal(engine) == []


def test_case_only_rename_of_directory(fake_archive, executor):
    fake_archive.add("10. Financial/Banks/Trip/a.pdf")
    result = executor.apply(plan(Op(K.RENAME, "10. Financial/Banks/Trip", "TRIP")))
    assert result.failed is None, result.error
    assert result.done[0].dst == "10. Financial/Banks/TRIP"
    assert "TRIP" in os.listdir(fake_archive.root / "10. Financial/Banks")
    assert (fake_archive.root / "10. Financial/Banks/TRIP/a.pdf").exists()


def test_rename_case_only_refuses_different_entry_or_hard_link(tmp_path):
    (tmp_path / "a").write_bytes(b"a")
    (tmp_path / "b").write_bytes(b"b")
    with pytest.raises(FileExistsError):
        primitives.rename_case_only(tmp_path / "a", tmp_path / "b")
    assert (tmp_path / "b").read_bytes() == b"b"
    if not (tmp_path / "A").exists():  # a case-sensitive filesystem (Linux): "A" is not "a"
        return
    os.link(tmp_path / "a", tmp_path / "hard")
    with pytest.raises(FileExistsError):
        primitives.rename_case_only(tmp_path / "a", tmp_path / "A")


def test_unlink_symlink_journals_link_target(fake_archive, executor, engine):
    fake_archive.add("10. Financial/Banks/a.pdf")
    link = fake_archive.link("##. Ongoing/a.pdf", "10. Financial/Banks/a.pdf")
    target = readlink(link)
    result = executor.apply(plan(Op(K.UNLINK_SYMLINK, "##. Ongoing/a.pdf", None)))
    assert result.failed is None, result.error
    assert os.path.isabs(target)  # fixture links are absolute; journal keeps it relative
    (row,) = journal(engine)
    assert (row["src"], row["dst"]) == ("##. Ongoing/a.pdf", "10. Financial/Banks/a.pdf")


def test_unlink_symlink_journals_outside_target_as_abs(fake_archive, executor, engine, tmp_path):
    outside = tmp_path / "elsewhere.pdf"
    outside.write_bytes(b"x")
    (fake_archive.root / "##. Ongoing/ext.pdf").symlink_to(outside)
    result = executor.apply(plan(Op(K.UNLINK_SYMLINK, "##. Ongoing/ext.pdf", None)))
    assert result.failed is None, result.error
    (row,) = journal(engine)
    assert row["dst"] == "abs:" + os.path.normpath(str(outside))
    assert outside.exists()


def test_move_with_name_collision_one_op(fake_archive, executor, engine):
    fake_archive.add("##. Organize/File_000.pdf", content=b"new", drive_id="id-new")
    original = fake_archive.add("10. Financial/Banks/20261013_Taxcard.pdf", content=b"orig")
    op = Op(K.MOVE, "##. Organize/File_000.pdf", "10. Financial/Banks", name="20261013_Taxcard.pdf")
    result = executor.apply(plan(op))
    assert result.failed is None, result.error
    landed = fake_archive.root / "10. Financial/Banks/20261013_Taxcard_2.pdf"
    assert landed.read_bytes() == b"new"
    assert read_drive_id(landed) == "id-new"
    assert original.read_bytes() == b"orig"
    assert not (fake_archive.root / "##. Organize/File_000.pdf").exists()
    (row,) = journal(engine)
    assert (row["kind"], row["src"], row["dst"], row["state"]) == (
        K.MOVE,
        "##. Organize/File_000.pdf",
        "10. Financial/Banks/20261013_Taxcard_2.pdf",
        "done",
    )
    assert result.done[0].note == "renamed to avoid collision"


def test_move_with_name_no_collision(fake_archive, executor, engine):
    fake_archive.add("##. Organize/File_000.pdf", content=b"new")
    op = Op(K.MOVE, "##. Organize/File_000.pdf", "10. Financial/Banks", name="20261013_Tax.pdf")
    result = executor.apply(plan(op))
    assert result.failed is None, result.error
    assert [r.dst for r in result.done] == ["10. Financial/Banks/20261013_Tax.pdf"]
    assert (fake_archive.root / "10. Financial/Banks/20261013_Tax.pdf").read_bytes() == b"new"
    assert len(journal(engine)) == 1


def test_move_with_name_case_only_in_same_folder(fake_archive, executor):
    fake_archive.add("##. Organize/File.pdf")
    op = Op(K.MOVE, "##. Organize/File.pdf", "##. Organize", name="file.pdf")
    result = executor.apply(plan(op))
    assert result.failed is None, result.error
    assert os.listdir(fake_archive.root / "##. Organize") == ["file.pdf"]


@pytest.mark.parametrize("bad", ["a/b.pdf", "", ".", "..", "x\0.pdf"])
def test_move_with_invalid_name_refused(fake_archive, executor, bad):
    fake_archive.add("##. Organize/a.pdf")
    with pytest.raises(GuardError):
        executor.preview(plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial", name=bad)))
    assert (fake_archive.root / "##. Organize/a.pdf").exists()


@pytest.mark.parametrize(
    "op",
    [
        Op(K.RENAME, "##. Organize/a.pdf", "b.pdf", name="c.pdf"),
        Op(K.QUARANTINE, "##. Organize/a.pdf", None, name="c.pdf"),
        Op(K.MKDIR, None, "10. Financial/x", name="c.pdf"),
        Op(K.SYMLINK, "##. Organize/a.pdf", "##. Ongoing/l.pdf", name="c.pdf"),
        Op(K.UNLINK_SYMLINK, "##. Ongoing/l.pdf", None, name="c.pdf"),
    ],
)
def test_name_on_non_move_refused(fake_archive, executor, op):
    fake_archive.add("##. Organize/a.pdf")
    with pytest.raises(GuardError, match="name"):
        executor.preview(plan(op))


def test_quarantine_never_follows_redirect(fake_archive, executor, engine):
    fake_archive.add("##. Organize/X.pdf", content=b"other")
    fake_archive.add("##. Organize/scan.pdf", content=b"mine")
    before = tree(fake_archive.root)
    with pytest.raises(GuardError, match="ambiguous"):
        executor.apply(
            plan(
                Op(K.MOVE, "##. Organize/X.pdf", "10. Financial/Banks"),  # vacates X.pdf
                Op(K.RENAME, "##. Organize/scan.pdf", "X.pdf"),  # gets X_2
                Op(K.QUARANTINE, "##. Organize/X.pdf", None),  # would redirect: refused
            )
        )
    assert tree(fake_archive.root) == before
    assert journal(engine) == []


def test_snapshot_oserror_fails_op_and_stops(fake_archive, executor, engine, monkeypatch):
    fake_archive.add("##. Organize/a.pdf")
    fake_archive.add("##. Organize/b.pdf")
    p = plan(
        Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks"),
        Op(K.MOVE, "##. Organize/b.pdf", "10. Financial/Banks"),
    )

    def unreadable(path):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr("dam.ops.executor.read_drive_id", unreadable)
    result = executor.apply(p)
    assert result.done == []
    assert result.failed is not None and result.failed.src == "##. Organize/a.pdf"
    assert "cannot read source" in result.error
    assert [r["state"] for r in journal(engine)] == ["failed"]
    assert (fake_archive.root / "##. Organize/a.pdf").exists()
    assert (fake_archive.root / "##. Organize/b.pdf").exists()


@pytest.mark.parametrize("bad", ["##. Organize/a\0.pdf", "\0"])
def test_nul_in_path_refused(fake_archive, executor, bad):
    fake_archive.add("##. Organize/a.pdf")
    with pytest.raises(GuardError):
        executor.preview(plan(Op(K.MOVE, bad, "10. Financial")))
    with pytest.raises(GuardError):
        executor.preview(plan(Op(K.MOVE, "##. Organize/a.pdf", bad)))


def test_preview_sees_earlier_ops(fake_archive, executor):
    fake_archive.add("##. Organize/x/a.pdf")
    fake_archive.add("##. Organize/b/a.pdf")
    resolved = executor.preview(
        plan(
            Op(K.MOVE, "##. Organize/x/a.pdf", "10. Financial/Banks/new"),
            Op(K.MOVE, "##. Organize/b/a.pdf", "10. Financial/Banks/new"),
        )
    )
    assert [(r.kind, r.dst) for r in resolved] == [
        (K.MKDIR, "10. Financial/Banks/new"),
        (K.MOVE, "10. Financial/Banks/new/a.pdf"),
        (K.MOVE, "10. Financial/Banks/new/a_2.pdf"),
    ]


def test_preview_missing_source_fails(fake_archive, executor):
    with pytest.raises(GuardError):
        executor.preview(plan(Op(K.MOVE, "##. Organize/nope.pdf", "10. Financial/Banks")))


def test_move_directory_updates_descendants(fake_archive, executor, engine):
    fake_archive.add("##. Organize/Trip/a.pdf", drive_id="id-a")
    with engine.begin() as conn:
        conn.execute(
            insert(files),
            [
                {
                    "drive_id": "id-dir",
                    "path": "##. Organize/Trip",
                    "path_nfc": "##. Organize/Trip",
                    "name": "Trip",
                    "is_dir": True,
                },
                {
                    "drive_id": "id-a",
                    "path": "##. Organize/Trip/a.pdf",
                    "path_nfc": "##. Organize/Trip/a.pdf",
                    "name": "a.pdf",
                    "ext": "pdf",
                    "is_dir": False,
                },
            ],
        )
    result = executor.apply(plan(Op(K.MOVE, "##. Organize/Trip", "10. Financial")))
    assert result.failed is None, result.error
    assert (fake_archive.root / "10. Financial/Trip/a.pdf").exists()
    with engine.connect() as conn:
        rows = dict(conn.execute(select(files.c.drive_id, files.c.path)).all())
    assert rows == {"id-dir": "10. Financial/Trip", "id-a": "10. Financial/Trip/a.pdf"}


def test_symlink_and_unlink_symlink_ops(fake_archive, executor, engine):
    target = fake_archive.add("10. Financial/Banks/a.pdf", content=b"t", drive_id="id-t")
    result = executor.apply(
        plan(Op(K.SYMLINK, "10. Financial/Banks/a.pdf", "##. Ongoing/Tax/a.pdf"))
    )
    assert result.failed is None, result.error
    link = fake_archive.root / "##. Ongoing/Tax/a.pdf"
    assert link.is_symlink() and link.read_bytes() == b"t"
    assert [r.kind for r in result.done] == [K.MKDIR, K.SYMLINK]
    assert result.done[-1].drive_id == "id-t"
    result = executor.apply(plan(Op(K.UNLINK_SYMLINK, "##. Ongoing/Tax/a.pdf", None)))
    assert result.failed is None, result.error
    assert not os.path.lexists(link)
    assert target.read_bytes() == b"t"
    assert [r["state"] for r in journal(engine)] == ["done", "done", "done"]


def test_unlink_symlink_op_refuses_regular_file(fake_archive, executor):
    f = fake_archive.add("##. Ongoing/real.pdf")
    with pytest.raises(GuardError):
        executor.apply(plan(Op(K.UNLINK_SYMLINK, "##. Ongoing/real.pdf", None)))
    assert f.exists()


def test_unlink_symlink_op_refuses_outside_ongoing(fake_archive, executor):
    fake_archive.add("10. Financial/Banks/a.pdf")
    link = fake_archive.link("10. Financial/l.pdf", "10. Financial/Banks/a.pdf")
    with pytest.raises(GuardError):
        executor.apply(plan(Op(K.UNLINK_SYMLINK, "10. Financial/l.pdf", None)))
    assert link.is_symlink()


def test_throttle_sleeps_between_ops_only(fake_archive, paths, engine, monkeypatch):
    for n in "abc":
        fake_archive.add(f"##. Organize/{n}.pdf")
    sleeps: list[float] = []
    monkeypatch.setattr("dam.ops.executor.time.sleep", sleeps.append)
    ex = Executor(paths, engine, FileRepo(engine, inbox="##. Organize"), throttle_ms=250)
    p = plan(*(Op(K.MOVE, f"##. Organize/{n}.pdf", "10. Financial/Banks") for n in "abc"))
    assert ex.apply(p).failed is None
    assert sleeps == [0.25, 0.25]


def test_update_path_prefix_boundary_and_fts(engine):
    nfd = unicodedata.normalize("NFD", "Kyynärpää.pdf")
    with engine.begin() as conn:
        conn.execute(
            insert(files),
            [
                {"drive_id": "d1", "path": "a/b", "path_nfc": "a/b", "name": "b", "is_dir": True},
                {
                    "drive_id": "d2",
                    "path": f"a/b/{nfd}",
                    "path_nfc": unicodedata.normalize("NFC", f"a/b/{nfd}"),
                    "name": nfd,
                    "ext": "pdf",
                    "is_dir": False,
                },
                {
                    "drive_id": "d3",
                    "path": "a/bc/x.pdf",
                    "path_nfc": "a/bc/x.pdf",
                    "name": "x.pdf",
                    "ext": "pdf",
                    "is_dir": False,
                },
            ],
        )
        conn.execute(
            text("INSERT INTO file_fts(drive_id, name, path, text) VALUES (:d, :n, :p, 't')"),
            [
                {"d": "d2", "n": nfd, "p": f"a/b/{nfd}"},
                {"d": "d3", "n": "x.pdf", "p": "a/bc/x.pdf"},
            ],
        )
    repo = FileRepo(engine, inbox="##. Organize")
    repo.update_path("a/b", "z/B")
    repo.update_path("not/in/db", "z/q")  # unknown rows: no-op
    with engine.connect() as conn:
        rows = {r.drive_id: r for r in conn.execute(select(files)).all()}
        fts = dict(conn.execute(text("SELECT drive_id, path FROM file_fts")).all())
        fts_names = dict(conn.execute(text("SELECT drive_id, name FROM file_fts")).all())
    assert rows["d1"].path == "z/B" and rows["d1"].name == "B"
    assert rows["d2"].path == f"z/B/{nfd}"
    assert rows["d2"].path_nfc == unicodedata.normalize("NFC", f"z/B/{nfd}")
    assert rows["d3"].path == "a/bc/x.pdf"
    assert fts["d2"] == unicodedata.normalize("NFC", f"z/B/{nfd}")
    assert fts_names["d2"] == unicodedata.normalize("NFC", nfd)
    assert fts["d3"] == "a/bc/x.pdf"


def test_rename_updates_name_and_ext(engine):
    with engine.begin() as conn:
        conn.execute(
            insert(files),
            [
                {
                    "drive_id": "d1",
                    "path": "a/x.PDF",
                    "path_nfc": "a/x.PDF",
                    "name": "x.PDF",
                    "ext": "pdf",
                    "is_dir": False,
                }
            ],
        )
    FileRepo(engine, inbox="##. Organize").update_path("a/x.PDF", "a/20261013_y.Jpg")
    with engine.connect() as conn:
        row = conn.execute(select(files)).one()
    assert (row.path, row.name, row.ext) == ("a/20261013_y.Jpg", "20261013_y.Jpg", "jpg")


def test_exclusive_rename_never_overwrites_even_without_precheck(
    fake_archive, executor, monkeypatch
):
    # Simulate a race: destination appears after the pre-check passed.
    fake_archive.add("##. Organize/a.pdf", content=b"mine")
    p = plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks"))
    resolved = executor.preview(p)
    blocker = fake_archive.add("10. Financial/Banks/a.pdf", content=b"blocker")
    monkeypatch.setattr(Executor, "preview", lambda self, plan: resolved)
    monkeypatch.setattr(Executor, "_precheck", lambda self, rop: None)
    result = executor.apply(p)
    assert result.failed is not None
    assert blocker.read_bytes() == b"blocker"
    assert (fake_archive.root / "##. Organize/a.pdf").read_bytes() == b"mine"


def test_rename_excl_fallback_when_unsupported(tmp_path, monkeypatch):
    monkeypatch.setattr(primitives, "_renamex_np", None)
    (tmp_path / "a").write_bytes(b"a")
    (tmp_path / "b").write_bytes(b"b")
    with pytest.raises(FileExistsError):
        primitives.rename_excl(tmp_path / "a", tmp_path / "b")
    assert (tmp_path / "b").read_bytes() == b"b"
    primitives.rename_excl(tmp_path / "a", tmp_path / "c")
    assert (tmp_path / "c").read_bytes() == b"a"


# --- REMOVE_EMPTY_DIR (Phase 2 Task 8) --------------------------------------------

ONG = "##. Ongoing"
FINDER = b"\x00\x00\x00\x01Bud1" + b"\x00" * 24  # Finder's .DS_Store header


def _finder_ds(folder: Path) -> Path:
    ds = folder / ".DS_Store"
    ds.write_bytes(FINDER)
    return ds


def _ui(*ops: Op) -> Plan:
    return Plan(ops=list(ops), origin="ui")


def test_remove_empty_dir_removes_empty_app_folder(fake_archive, executor, engine):
    (fake_archive.root / ONG / "Tax 2026").mkdir()
    result = executor.apply(_ui(Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Tax 2026", None)))
    assert result.failed is None, result.error
    assert not os.path.lexists(fake_archive.root / ONG / "Tax 2026")
    assert (fake_archive.root / ONG).is_dir()
    (row,) = journal(engine)
    assert (row["kind"], row["src"], row["dst"], row["state"], row["is_file"]) == (
        K.REMOVE_EMPTY_DIR,
        f"{ONG}/Tax 2026",
        f"{ONG}/Tax 2026",
        "done",
        False,
    )


@needs_dir_fd
def test_remove_empty_dir_deletes_ds_store_only(fake_archive, executor):
    folder = fake_archive.root / ONG / "Tax"
    folder.mkdir()
    ds = _finder_ds(folder)
    assert os.lstat(ds).st_nlink == 1 and read_drive_id(ds) is None
    result = executor.apply(Plan([Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Tax", None)], "workflow"))
    assert result.failed is None, result.error
    assert not os.path.lexists(folder)


@pytest.mark.parametrize("other", ["a.pdf", ".ds_store", "DS_Store", ".DS_Store.bak"])
def test_remove_empty_dir_refuses_other_entry(fake_archive, executor, engine, other):
    folder = fake_archive.root / ONG / "Tax"
    folder.mkdir()
    _finder_ds(folder)
    keep = fake_archive.add(f"{ONG}/Tax/{other}", content=b"keep") if other != ".ds_store" else None
    if keep is None:  # a case variant cannot sit next to .DS_Store on APFS: alone then
        (folder / ".DS_Store").unlink()
        keep = fake_archive.add(f"{ONG}/Tax/{other}", content=b"keep")
    with pytest.raises(GuardError, match="not empty"):
        executor.preview(_ui(Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Tax", None)))
    assert keep.read_bytes() == b"keep" and folder.is_dir()
    assert journal(engine) == []


def test_remove_empty_dir_refuses_subfolder(fake_archive, executor):
    (fake_archive.root / ONG / "Tax" / "sub").mkdir(parents=True)
    with pytest.raises(GuardError, match="not empty"):
        executor.preview(_ui(Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Tax", None)))
    assert (fake_archive.root / ONG / "Tax" / "sub").is_dir()


@pytest.mark.parametrize(
    "src",
    [
        ONG,  # the Ongoing folder itself
        "10. Financial/Banks",  # outside Ongoing
        "10. Financial/Banks/Empty",
        "",  # root
        f"{ONG}/..",
    ],
)
def test_remove_empty_dir_refuses_paths(fake_archive, executor, engine, src):
    (fake_archive.root / ONG / "a" / "b").mkdir(parents=True)
    (fake_archive.root / "10. Financial/Banks/Empty").mkdir()
    before = tree(fake_archive.root)
    with pytest.raises(GuardError):
        executor.apply(_ui(Op(K.REMOVE_EMPTY_DIR, src, None)))
    assert tree(fake_archive.root) == before
    assert journal(engine) == []


def test_remove_empty_dir_case_variant_of_ongoing_accepted(fake_archive, executor):
    (fake_archive.root / ONG / "Tax").mkdir()
    result = executor.apply(_ui(Op(K.REMOVE_EMPTY_DIR, "##. ONGOING/Tax", None)))
    assert result.failed is None, result.error
    assert not os.path.lexists(fake_archive.root / ONG / "Tax")


def test_remove_empty_dir_refuses_symlink_and_file(fake_archive, executor):
    (fake_archive.root / "10. Financial/Banks/Empty").mkdir()
    link = fake_archive.link(f"{ONG}/Tax", "10. Financial/Banks/Empty")
    f = fake_archive.add(f"{ONG}/note.pdf")
    for rel in (f"{ONG}/Tax", f"{ONG}/note.pdf", f"{ONG}/missing"):
        with pytest.raises(GuardError):
            executor.apply(_ui(Op(K.REMOVE_EMPTY_DIR, rel, None)))
    assert link.is_symlink() and (fake_archive.root / "10. Financial/Banks/Empty").is_dir()
    assert f.exists()


@pytest.mark.parametrize(
    "op",
    [
        Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Tax", "x"),
        Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Tax", None, name="x"),
        Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Tax", None, exact=True),
        Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Tax", None, allow_top_level=True),
        Op(K.REMOVE_EMPTY_DIR, None, None),
    ],
)
def test_remove_empty_dir_refuses_extra_fields(fake_archive, executor, op):
    (fake_archive.root / ONG / "Tax").mkdir()
    with pytest.raises(GuardError):
        executor.apply(_ui(op))
    assert (fake_archive.root / ONG / "Tax").is_dir()


@pytest.mark.parametrize("kind", ["dir", "link"])
def test_remove_empty_dir_refuses_ds_store_that_is_not_a_file(fake_archive, executor, kind):
    folder = fake_archive.root / ONG / "Tax"
    folder.mkdir()
    target = fake_archive.add("10. Financial/Banks/t.pdf", content=b"t")
    if kind == "dir":
        (folder / ".DS_Store").mkdir()
    else:
        (folder / ".DS_Store").symlink_to(target)
    with pytest.raises(GuardError):
        executor.preview(_ui(Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Tax", None)))
    # the primitive refuses on its own, too
    with pytest.raises(GuardError):
        primitives.remove_empty_dir(folder, fake_archive.root / ONG)
    assert os.path.lexists(folder / ".DS_Store") and folder.is_dir()
    assert target.read_bytes() == b"t"


def test_remove_empty_dir_after_unlinking_its_links_in_same_batch(fake_archive, executor):
    fake_archive.add("10. Financial/Banks/a.pdf")
    fake_archive.link(f"{ONG}/Tax/a.pdf", "10. Financial/Banks/a.pdf")
    p = _ui(
        Op(K.UNLINK_SYMLINK, f"{ONG}/Tax/a.pdf", None), Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Tax", None)
    )
    result = executor.apply(p)
    assert result.failed is None, result.error
    assert [r.kind for r in result.done] == [K.UNLINK_SYMLINK, K.REMOVE_EMPTY_DIR]
    assert not os.path.lexists(fake_archive.root / ONG / "Tax")
    assert (fake_archive.root / "10. Financial/Banks/a.pdf").exists()


def test_remove_empty_dir_refuses_entry_added_earlier_in_batch(fake_archive, executor, engine):
    (fake_archive.root / ONG / "Tax").mkdir()
    fake_archive.add("10. Financial/Banks/a.pdf")
    p = _ui(
        Op(K.SYMLINK, "10. Financial/Banks/a.pdf", f"{ONG}/Tax/a.pdf"),
        Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Tax", None),
    )
    with pytest.raises(GuardError, match="not empty"):
        executor.preview(p)
    p = _ui(
        Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Tax", None),
        Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Tax", None),
    )
    with pytest.raises(GuardError):  # already removed in the simulation
        executor.preview(p)
    assert journal(engine) == []


def test_remove_empty_dir_primitive_rechecks_at_act_time(fake_archive):
    ongoing = fake_archive.root / ONG
    folder = ongoing / "Tax"
    folder.mkdir()
    keep = fake_archive.add(f"{ONG}/Tax/a.pdf", content=b"keep")
    (folder / ".DS_Store").write_bytes(b"f")
    with pytest.raises(GuardError, match="not empty"):
        primitives.remove_empty_dir(folder, ongoing)
    assert keep.read_bytes() == b"keep"
    assert (folder / ".DS_Store").exists()  # nothing removed when anything else is present
    nested = folder / "sub"
    nested.mkdir()
    keep.unlink()
    (folder / ".DS_Store").unlink()
    with pytest.raises(GuardError, match="not empty"):
        primitives.remove_empty_dir(folder, ongoing)  # holds the subfolder
    with pytest.raises(GuardError):
        primitives.remove_empty_dir(ongoing, ongoing)  # Ongoing itself
    (fake_archive.root / "10. Financial/Banks/E").mkdir()
    with pytest.raises(GuardError):
        primitives.remove_empty_dir(fake_archive.root / "10. Financial/Banks/E", ongoing)
    assert nested.is_dir() and (fake_archive.root / "10. Financial/Banks/E").is_dir()


def test_remove_empty_dir_primitive_refuses_via_symlinked_parent(fake_archive):
    (fake_archive.root / "10. Financial/Banks/E").mkdir()
    fake_archive.link(f"{ONG}/banks", "10. Financial/Banks")
    via = fake_archive.root / ONG / "banks" / "E"  # really 10. Financial/Banks/E
    with pytest.raises(GuardError):
        primitives.remove_empty_dir(via, fake_archive.root / ONG)
    assert (fake_archive.root / "10. Financial/Banks/E").is_dir()


def test_remove_empty_dir_filled_between_preview_and_apply(fake_archive, executor, engine):
    folder = fake_archive.root / ONG / "Tax"
    folder.mkdir()
    real_preview = executor.preview

    def preview_then_fill(p):
        resolved = real_preview(p)
        (folder / "late.pdf").write_bytes(b"late")
        return resolved

    executor.preview = preview_then_fill
    result = executor.apply(_ui(Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Tax", None)))
    assert result.failed is not None and "not empty" in result.error
    assert (folder / "late.pdf").read_bytes() == b"late"
    assert [r["state"] for r in journal(engine)] == ["failed"]


def test_remove_empty_dir_rmdir_enotempty_is_guard_error(fake_archive, monkeypatch):
    import errno

    folder = fake_archive.root / ONG / "Tax"
    folder.mkdir()

    def racing_rmdir(p, **kw):
        raise OSError(errno.ENOTEMPTY, "Directory not empty", str(p))

    monkeypatch.setattr(primitives.os, "rmdir", racing_rmdir)
    with pytest.raises(GuardError, match="not empty"):
        primitives.remove_empty_dir(folder, fake_archive.root / ONG)


# --- REMOVE_EMPTY_DIR fix round 1: only genuine Finder .DS_Store files ---------------


def _precious(fake_archive, rel="10. Financial/Banks/tax-return.pdf", drive_id="auto"):
    return fake_archive.add(rel, content=b"PRECIOUS", drive_id=drive_id)


def _survives(fake_archive) -> bool:
    return any(
        p.read_bytes() == b"PRECIOUS"
        for p in fake_archive.root.rglob("*")
        if p.is_file() and not p.is_symlink()
    )


def test_probe_move_named_ds_store_then_remove_refused(fake_archive, executor, engine):
    (fake_archive.root / ONG / "Tax").mkdir()
    doc = _precious(fake_archive)
    p = _ui(
        Op(K.MOVE, "10. Financial/Banks/tax-return.pdf", f"{ONG}/Tax", name=".DS_Store"),
        Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Tax", None),
    )
    with pytest.raises(GuardError, match="DS_Store"):
        executor.apply(p)
    assert doc.read_bytes() == b"PRECIOUS" and journal(engine) == []


def test_cross_batch_move_named_ds_store_refused(fake_archive, executor, engine):
    (fake_archive.root / ONG / "Tax").mkdir()
    doc = _precious(fake_archive, drive_id=None)
    with pytest.raises(GuardError):
        executor.apply(
            _ui(Op(K.MOVE, "10. Financial/Banks/tax-return.pdf", f"{ONG}/Tax", name=".DS_Store"))
        )
    result = executor.apply(Plan([Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Tax", None)], "workflow"))
    assert result.failed is None, result.error  # the folder really was empty
    assert doc.read_bytes() == b"PRECIOUS"


@pytest.mark.parametrize(
    "op",
    [
        Op(K.RENAME, "10. Financial/Banks/tax-return.pdf", ".DS_Store"),
        Op(K.RENAME, "10. Financial/Banks/tax-return.pdf", ".ds_store"),
        Op(K.MOVE, "10. Financial/Banks/tax-return.pdf", f"{ONG}/Tax", name=".DS_STORE"),
        Op(K.SYMLINK, "10. Financial/Banks/tax-return.pdf", f"{ONG}/Tax/.DS_Store"),
        Op(K.SYMLINK, "10. Financial/Banks/tax-return.pdf", f"{ONG}/.ds_Store"),
    ],
)
def test_guard_refuses_ds_store_names(fake_archive, executor, engine, op):
    (fake_archive.root / ONG / "Tax").mkdir()
    doc = _precious(fake_archive)
    with pytest.raises(GuardError, match="DS_Store"):
        executor.apply(_ui(op))
    assert doc.read_bytes() == b"PRECIOUS" and journal(engine) == []


def test_guard_refuses_moving_a_file_named_ds_store(fake_archive, executor):
    ds = fake_archive.add("10. Financial/Banks/.DS_Store", content=FINDER, drive_id=None)
    (fake_archive.root / ONG / "Tax").mkdir()
    with pytest.raises(GuardError, match="DS_Store"):
        executor.apply(_ui(Op(K.MOVE, "10. Financial/Banks/.DS_Store", f"{ONG}/Tax")))
    assert ds.exists()


def test_planner_refuses_ds_store_put_there_earlier_in_batch(
    fake_archive, executor, engine, monkeypatch
):
    """Layer (b) on its own: with the name guard switched off, the planner still
    refuses a .DS_Store that an earlier op of the batch put into the folder."""
    monkeypatch.setattr("dam.ops.guards.is_ds_store_name", lambda name: False)
    (fake_archive.root / ONG / "Tax").mkdir()
    doc = _precious(fake_archive, drive_id=None)
    for first in (
        Op(K.MOVE, "10. Financial/Banks/tax-return.pdf", f"{ONG}/Tax", name=".DS_Store"),
        Op(K.SYMLINK, "10. Financial/Banks/tax-return.pdf", f"{ONG}/Tax/.DS_Store"),
    ):
        with pytest.raises(GuardError, match="not empty"):
            executor.preview(_ui(first, Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Tax", None)))
    assert doc.read_bytes() == b"PRECIOUS" and journal(engine) == []


def test_primitive_refuses_impostor_after_guard_and_planner(fake_archive, executor, monkeypatch):
    """Layer (c) on its own: a document that reached the name .DS_Store (here in an
    earlier batch, with the name guard off) is never deleted by the primitive."""
    monkeypatch.setattr("dam.ops.guards.is_ds_store_name", lambda name: False)
    folder = fake_archive.root / ONG / "Tax"
    folder.mkdir()
    _precious(fake_archive)
    moved = executor.apply(
        _ui(Op(K.MOVE, "10. Financial/Banks/tax-return.pdf", f"{ONG}/Tax", name=".DS_Store"))
    )
    assert moved.failed is None, moved.error
    result = executor.apply(Plan([Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Tax", None)], "workflow"))
    assert result.failed is not None
    assert (folder / ".DS_Store").read_bytes() == b"PRECIOUS"


def _impostor(fake_archive, folder: Path, kind: str) -> tuple[Path, bytes]:
    ds = folder / ".DS_Store"
    if kind == "hardlink":
        doc = _precious(fake_archive, drive_id=None)
        doc.write_bytes(FINDER + b"PRECIOUS")  # even with the magic header
        os.link(doc, ds)
    elif kind == "no-magic":
        ds.write_bytes(b"PRECIOUS")
    elif kind == "drive-id":
        fake_archive.add(f"{ONG}/Tax/.DS_Store", content=FINDER + b"PRECIOUS", drive_id="id-x")
    elif kind == "symlink":
        doc = _precious(fake_archive, drive_id=None)
        doc.write_bytes(FINDER + b"PRECIOUS")
        ds.symlink_to(doc)
    elif kind == "short":
        ds.write_bytes(FINDER[:5])
    return ds, os.lstat(ds).st_ino


@pytest.mark.parametrize("kind", ["hardlink", "no-magic", "drive-id", "symlink", "short"])
def test_primitive_refuses_non_finder_ds_store(fake_archive, executor, engine, kind):
    folder = fake_archive.root / ONG / "Tax"
    folder.mkdir()
    ds, ino = _impostor(fake_archive, folder, kind)
    before = tree(fake_archive.root)
    with pytest.raises(GuardError):
        primitives.remove_empty_dir(folder, fake_archive.root / ONG)
    try:  # the preview refuses a symlink already; the others reach the primitive
        result = executor.apply(_ui(Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Tax", None)))
        assert result.failed is not None and kind != "symlink"
    except GuardError:
        assert kind == "symlink"
    assert tree(fake_archive.root) == before
    assert os.lstat(ds).st_ino == ino


@needs_dir_fd
def test_genuine_finder_ds_store_removed(fake_archive):
    folder = fake_archive.root / ONG / "Tax"
    folder.mkdir()
    _finder_ds(folder)
    primitives.remove_empty_dir(folder, fake_archive.root / ONG)
    assert not os.path.lexists(folder)


def _outside_with_finder_ds(fake_archive) -> Path:
    other = fake_archive.root / "10. Financial/Banks/Empty"
    other.mkdir()
    _finder_ds(other)
    return other


def test_folder_swapped_for_symlink_between_plan_and_act(fake_archive, executor, monkeypatch):
    folder = fake_archive.root / ONG / "Tax"
    folder.mkdir()
    other = _outside_with_finder_ds(fake_archive)
    real = Executor._precheck

    def precheck_then_swap(self, rop):
        real(self, rop)
        folder.rmdir()
        folder.symlink_to(other)

    monkeypatch.setattr(Executor, "_precheck", precheck_then_swap)
    result = executor.apply(_ui(Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Tax", None)))
    assert result.failed is not None
    assert folder.is_symlink() and (other / ".DS_Store").read_bytes() == FINDER


@needs_dir_fd
def test_folder_swapped_for_symlink_inside_primitive(fake_archive, monkeypatch):
    folder = fake_archive.root / ONG / "Tax"
    folder.mkdir()
    other = _outside_with_finder_ds(fake_archive)
    real = os.listdir

    def swap(p):
        if isinstance(p, int):  # the primitive lists through its folder fd
            folder.rmdir()
            folder.symlink_to(other)
        return real(p)

    monkeypatch.setattr(primitives.os, "listdir", swap)
    with pytest.raises(GuardError):
        primitives.remove_empty_dir(folder, fake_archive.root / ONG)
    assert folder.is_symlink() and other.is_dir()
    assert (other / ".DS_Store").read_bytes() == FINDER


def test_ongoing_swapped_for_symlink_refused(fake_archive, executor, monkeypatch):
    (fake_archive.root / ONG / "Tax").mkdir()
    victim = fake_archive.root / "10. Financial/Tax"
    victim.mkdir()
    _finder_ds(victim)
    real = primitives.remove_empty_dir

    def swap(path, ongoing, identity=None):
        primitives.rename_excl(fake_archive.root / ONG, fake_archive.root / "moved-ongoing")
        (fake_archive.root / ONG).symlink_to(fake_archive.root / "10. Financial")
        return real(path, ongoing, identity=identity)

    monkeypatch.setattr(primitives, "remove_empty_dir", swap)
    result = executor.apply(_ui(Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Tax", None)))
    assert result.failed is not None
    assert victim.is_dir() and (victim / ".DS_Store").read_bytes() == FINDER
    assert (fake_archive.root / "moved-ongoing/Tax").is_dir()


def test_ongoing_symlink_refused_by_primitive(fake_archive, tmp_path):
    real = tmp_path / "real-ongoing"
    (real / "Tax").mkdir(parents=True)
    link = tmp_path / "ongoing-link"
    link.symlink_to(real)
    with pytest.raises(GuardError):
        primitives.remove_empty_dir(link / "Tax", link)
    assert (real / "Tax").is_dir()


def test_primitive_needs_lexical_parent(fake_archive):
    folder = fake_archive.root / ONG / "Tax"
    folder.mkdir()
    alias = fake_archive.root / "10. Financial/ong-alias"
    alias.symlink_to(fake_archive.root / ONG)  # resolves to Ongoing, lexically elsewhere
    with pytest.raises(GuardError):
        primitives.remove_empty_dir(alias / "Tax", fake_archive.root / ONG)
    assert folder.is_dir()


def test_remove_empty_dir_never_follows_redirect(fake_archive, paths, monkeypatch):
    """Like QUARANTINE, a removal never follows a collision redirect. (Today any later
    reference to the collided name is refused as ambiguous first, so the redirect is
    forced here.)"""
    from dam.ops.planner import Planner

    (fake_archive.root / ONG / "Tax_2").mkdir()
    monkeypatch.setattr(
        Planner, "_alias", lambda self, src: (f"{ONG}/Tax_2", "redirected from 'Tax'")
    )
    with pytest.raises(GuardError, match="ambiguous"):
        Planner(paths).resolve(_ui(Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Tax", None)))
    assert (fake_archive.root / ONG / "Tax_2").is_dir()


# --- REMOVE_EMPTY_DIR at any depth inside Ongoing (mac redesign, Task 8) ----------------


@needs_dir_fd
def test_remove_empty_dir_removes_a_nested_app_folder(fake_archive, executor, engine):
    (fake_archive.root / ONG / "Sauna" / "2025" / "Q1").mkdir(parents=True)
    _finder_ds(fake_archive.root / ONG / "Sauna" / "2025" / "Q1")
    result = executor.apply(_ui(Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Sauna/2025/Q1", None)))
    assert result.failed is None, result.error
    assert not os.path.lexists(fake_archive.root / ONG / "Sauna" / "2025" / "Q1")
    assert (fake_archive.root / ONG / "Sauna" / "2025").is_dir()
    (row,) = journal(engine)
    assert (row["kind"], row["src"], row["state"]) == (
        K.REMOVE_EMPTY_DIR,
        f"{ONG}/Sauna/2025/Q1",
        "done",
    )


def test_remove_empty_dir_nested_after_unlinking_in_same_batch(fake_archive, executor):
    fake_archive.add("10. Financial/Banks/a.pdf")
    fake_archive.link(f"{ONG}/Sauna/2025/a.pdf", "10. Financial/Banks/a.pdf")
    p = _ui(
        Op(K.UNLINK_SYMLINK, f"{ONG}/Sauna/2025/a.pdf", None),
        Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Sauna/2025", None),
        Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Sauna", None),
    )
    result = executor.apply(p)
    assert result.failed is None, result.error
    assert not os.path.lexists(fake_archive.root / ONG / "Sauna")
    assert (fake_archive.root / "10. Financial/Banks/a.pdf").exists()


def test_remove_empty_dir_nested_refuses_a_parent_before_its_child(fake_archive, executor):
    (fake_archive.root / ONG / "Sauna" / "2025").mkdir(parents=True)
    with pytest.raises(GuardError, match="not empty"):
        executor.preview(_ui(Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Sauna", None)))
    assert (fake_archive.root / ONG / "Sauna" / "2025").is_dir()


def test_remove_empty_dir_nested_refuses_symlinked_intermediate(fake_archive, executor, engine):
    (fake_archive.root / "10. Financial/Banks/E").mkdir()
    fake_archive.link(f"{ONG}/Sauna/banks", "10. Financial/Banks")
    via = f"{ONG}/Sauna/banks/E"  # really 10. Financial/Banks/E
    with pytest.raises(GuardError):
        executor.apply(_ui(Op(K.REMOVE_EMPTY_DIR, via, None)))
    with pytest.raises(GuardError):
        primitives.remove_empty_dir(fake_archive.root / via, fake_archive.root / ONG)
    assert (fake_archive.root / "10. Financial/Banks/E").is_dir()
    assert (fake_archive.root / ONG / "Sauna" / "banks").is_symlink()
    assert journal(engine) == []


def test_remove_empty_dir_primitive_nested(fake_archive):
    ongoing = fake_archive.root / ONG
    nested = ongoing / "Sauna" / "2025" / "Q1"
    nested.mkdir(parents=True)
    keep = fake_archive.add(f"{ONG}/Sauna/2025/Q1/a.pdf", content=b"keep")
    with pytest.raises(GuardError, match="not empty"):
        primitives.remove_empty_dir(nested, ongoing)
    assert keep.read_bytes() == b"keep"
    with pytest.raises(GuardError, match="not empty"):
        primitives.remove_empty_dir(nested.parent, ongoing)
    keep.unlink()
    primitives.remove_empty_dir(nested, ongoing)
    assert not os.path.lexists(nested) and nested.parent.is_dir()


@pytest.mark.parametrize(
    "path",
    [
        "{ongoing}",  # Ongoing itself
        "{ongoing}/.",
        "{ongoing}/Sauna/..",
        "{ongoing}/Sauna/../Sauna",
        "{root}/10. Financial/Banks/E",  # outside Ongoing
        "{root}/10. Financial/Banks/E/F",
        "{root}/##. Ongoing-other/E",  # a sibling whose name starts like Ongoing
    ],
)
def test_remove_empty_dir_primitive_refuses_ongoing_itself_and_outside(fake_archive, path):
    ongoing = fake_archive.root / ONG
    (ongoing / "Sauna").mkdir()
    (fake_archive.root / "10. Financial/Banks/E/F").mkdir(parents=True)
    (fake_archive.root / "##. Ongoing-other/E").mkdir(parents=True)
    before = tree(fake_archive.root)
    p = Path(path.format(ongoing=ongoing, root=fake_archive.root))
    with pytest.raises(GuardError):
        primitives.remove_empty_dir(p, ongoing)
    assert tree(fake_archive.root) == before


def test_remove_empty_dir_primitive_refuses_when_ongoing_is_a_link(fake_archive, tmp_path):
    other = tmp_path / "other"
    (other / "E").mkdir(parents=True)
    link = fake_archive.root / "ong-link"
    link.symlink_to(other)
    with pytest.raises(GuardError):
        primitives.remove_empty_dir(link / "E", link)
    assert (other / "E").is_dir()


@needs_dir_fd
def test_remove_empty_dir_refuses_a_folder_with_another_identity(fake_archive, executor, engine):
    folder = fake_archive.root / ONG / "Tax"
    folder.mkdir()
    ident = identity.of_path(folder)
    real_preview = executor.preview

    def preview_then_swap(p):
        resolved = real_preview(p)
        recreate_dir(folder)  # the user's own empty folder, same name, between plan and act
        return resolved

    executor.preview = preview_then_swap
    op = Op(K.REMOVE_EMPTY_DIR, f"{ONG}/Tax", None, identity=ident)
    result = executor.apply(_ui(op))
    assert result.failed is not None and "identity" in result.error
    assert folder.is_dir()
    assert [r["state"] for r in journal(engine)] == ["failed"]
    # the primitive refuses on its own, before touching anything
    _finder_ds(folder)
    with pytest.raises(GuardError, match="identity"):
        primitives.remove_empty_dir(folder, fake_archive.root / ONG, ident)
    assert (folder / ".DS_Store").exists()
    # the right identity (or none) removes it
    primitives.remove_empty_dir(folder, fake_archive.root / ONG, identity=identity.of_path(folder))
    assert not os.path.lexists(folder)


@pytest.mark.parametrize("kind", [K.MKDIR, K.SYMLINK, K.UNLINK_SYMLINK, K.MOVE])
def test_identity_is_for_remove_empty_dir_only(fake_archive, executor, kind):
    (fake_archive.root / ONG / "Tax").mkdir()
    fake_archive.add("10. Financial/Banks/a.pdf")
    src = f"{ONG}/Tax" if kind is K.UNLINK_SYMLINK else "10. Financial/Banks/a.pdf"
    op = Op(kind, None if kind is K.MKDIR else src, f"{ONG}/New", identity=(1, 2))
    with pytest.raises(GuardError, match="identity"):
        executor.preview(_ui(op))


def test_a_deep_mkdir_chain_resolves_quickly(paths, executor):
    """The planner's simulation walks every earlier event for every op (cubic in
    the batch); ``fold_parts`` is memoised so a 30-deep chain of folders with a
    link in each (an Ongoing tree) still resolves well under a second."""
    import time

    from dam.ops.planner import Planner

    (paths.root / "##. Ongoing").mkdir(exist_ok=True)
    ops, rel = [], "##. Ongoing"
    for i in range(30):
        rel = f"{rel}/d{i}"
        ops.append(Op(OpKind.MKDIR, None, rel, exact=True))
        ops.append(Op(OpKind.SYMLINK, "##. Organize", f"{rel}/link{i}", exact=True))
    start = time.perf_counter()
    resolved = Planner(paths).resolve(Plan(ops, "workflow"))
    took = time.perf_counter() - start
    assert len(resolved) == 60 and resolved[-1].dst.endswith("/d29/link29")
    assert took < 2.0, f"{took:.2f}s for a 30-deep chain"
