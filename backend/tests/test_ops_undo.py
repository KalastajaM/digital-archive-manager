import dataclasses
import os
from pathlib import Path

import pytest
from sqlalchemy import insert, select

from conftest import needs_dir_fd
from dam.config import Settings
from dam.core.fs import readlink
from dam.core.paths import ArchivePaths
from dam.db.tables import files, operations
from dam.index.driveid import read_drive_id
from dam.index.repo import FileRepo
from dam.ops import primitives
from dam.ops.executor import Executor, JournalEntry
from dam.ops.model import GuardError, Op, OpFailed, OpKind, Plan
from dam.ops.planner import Planner
from dam.ops.undo import _check_restores_origin

K = OpKind


@pytest.fixture
def paths(fake_archive) -> ArchivePaths:
    return ArchivePaths(fake_archive.root, Settings(archive_root=fake_archive.root))


@pytest.fixture
def executor(paths, engine) -> Executor:
    return Executor(paths, engine, FileRepo(engine, inbox="##. Organize"))


def journal(engine, batch_id: str | None = None) -> list[dict]:
    q = select(operations).order_by(operations.c.id)
    if batch_id is not None:
        q = q.where(operations.c.batch_id == batch_id)
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(q).mappings().all()]


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
                st = p.stat()
                out[rel] = ("file", p.read_bytes(), read_drive_id(p), st.st_mtime)
    return out


def db_paths(engine) -> dict[str, str]:
    with engine.connect() as conn:
        rows = conn.execute(select(files.c.drive_id, files.c.path, files.c.name, files.c.ext))
        return {r.drive_id: (r.path, r.name, r.ext) for r in rows}


def index(engine, *entries: tuple[str, str]) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(files),
            [
                {
                    "drive_id": d,
                    "path": p,
                    "path_nfc": p,
                    "name": Path(p).name,
                    "ext": Path(p).suffix.lstrip(".").lower(),
                    "is_dir": False,
                }
                for d, p in entries
            ],
        )


def plan(*ops: Op) -> Plan:
    return Plan(ops=list(ops), origin="cli")


# --- brief tests -------------------------------------------------------------


def test_undo_restores_exact_state(fake_archive, executor, engine):
    fake_archive.add("##. Organize/File_000.pdf", content=b"one", drive_id="id-1")
    fake_archive.add("##. Organize/b.pdf", content=b"two", drive_id="id-2")
    index(engine, ("id-1", "##. Organize/File_000.pdf"), ("id-2", "##. Organize/b.pdf"))
    before, db_before = tree(fake_archive.root), db_paths(engine)

    done = executor.apply(
        plan(
            Op(K.RENAME, "##. Organize/File_000.pdf", "20261013_Taxcard.pdf"),
            Op(K.MOVE, "##. Organize/b.pdf", "10. Financial/Banks"),
        )
    )
    assert done.failed is None
    assert tree(fake_archive.root) != before

    result = executor.undo(done.batch_id)
    assert result.failed is None and result.error is None
    assert tree(fake_archive.root) == before
    assert db_paths(engine) == db_before

    originals = journal(engine, done.batch_id)
    assert [r["state"] for r in originals] == ["undone", "undone"]
    undo_rows = journal(engine, result.batch_id)
    assert [r["undo_of"] for r in undo_rows] == [done.batch_id, done.batch_id]
    assert all(r["state"] == "done" and r["origin"] == "undo" for r in undo_rows)
    # reverse order: the move is reverted first
    assert [(r["src"], r["dst"]) for r in undo_rows] == [
        ("10. Financial/Banks/b.pdf", "##. Organize/b.pdf"),
        ("##. Organize/20261013_Taxcard.pdf", "##. Organize/File_000.pdf"),
    ]


def test_undo_quarantine(fake_archive, executor, engine):
    fake_archive.add("10. Financial/Banks/old.pdf", content=b"old", drive_id="id-q")
    index(engine, ("id-q", "10. Financial/Banks/old.pdf"))
    before, db_before = tree(fake_archive.root), db_paths(engine)
    done = executor.apply(plan(Op(K.QUARANTINE, "10. Financial/Banks/old.pdf", None)))
    assert done.failed is None
    assert (fake_archive.root / "##. To Delete/10. Financial/Banks/old.pdf").exists()

    result = executor.undo(done.batch_id)
    assert result.failed is None, result.error
    after = tree(fake_archive.root)
    # the quarantine sub-folders created by the quarantine stay (folders are never removed)
    created = {k for k in after if k.startswith("##. To Delete/")}
    assert created == {"##. To Delete/10. Financial", "##. To Delete/10. Financial/Banks"}
    assert {k: v for k, v in after.items() if k not in created} == before
    assert read_drive_id(fake_archive.root / "10. Financial/Banks/old.pdf") == "id-q"
    assert db_paths(engine) == db_before
    originals = journal(engine, done.batch_id)
    assert [(r["kind"], r["state"]) for r in originals] == [
        ("mkdir", "undone"),
        ("mkdir", "undone"),
        ("quarantine", "undone"),
    ]
    undo_rows = journal(engine, result.batch_id)
    assert [(r["kind"], r["state"], r["undo_of"]) for r in undo_rows] == [
        ("move", "done", done.batch_id)
    ]


def test_undo_refuses_if_changed(fake_archive, executor, engine):
    fake_archive.add("##. Organize/a.pdf", content=b"a", drive_id="id-a")
    fake_archive.add("##. Organize/b.pdf", content=b"b", drive_id="id-b")
    done = executor.apply(
        plan(
            Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks"),
            Op(K.MOVE, "##. Organize/b.pdf", "10. Financial/Banks"),
        )
    )
    with open(fake_archive.root / "10. Financial/Banks/a.pdf", "ab") as f:
        f.write(b"more")
    snapshot = tree(fake_archive.root)
    with pytest.raises(OpFailed, match="cannot be undone"):
        executor.undo(done.batch_id)
    assert tree(fake_archive.root) == snapshot  # nothing moved, not even b.pdf
    assert [r["state"] for r in journal(engine)] == ["done", "done"]


def test_undo_refuses_if_origin_occupied(fake_archive, executor, engine):
    fake_archive.add("##. Organize/a.pdf", content=b"a", drive_id="id-a")
    fake_archive.add("##. Organize/b.pdf", content=b"b", drive_id="id-b")
    done = executor.apply(
        plan(
            Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks"),
            Op(K.MOVE, "##. Organize/b.pdf", "10. Financial/Banks"),
        )
    )
    fake_archive.add("##. Organize/a.pdf", content=b"newcomer", drive_id="id-new")
    snapshot = tree(fake_archive.root)
    with pytest.raises(GuardError, match="occupied"):
        executor.undo(done.batch_id)
    assert tree(fake_archive.root) == snapshot
    assert not (fake_archive.root / "##. Organize/a_2.pdf").exists()
    assert [r["state"] for r in journal(engine)] == ["done", "done"]


def test_undo_twice_refused(fake_archive, executor, engine):
    fake_archive.add("##. Organize/a.pdf")
    done = executor.apply(plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks")))
    executor.undo(done.batch_id)
    snapshot, rows = tree(fake_archive.root), journal(engine)
    with pytest.raises(OpFailed, match="nothing to undo"):
        executor.undo(done.batch_id)
    assert tree(fake_archive.root) == snapshot
    assert journal(engine) == rows


def test_recover_after_crash_before_act(fake_archive, paths, engine, monkeypatch):
    fake_archive.add("##. Organize/a.pdf", drive_id="id-a")
    index(engine, ("id-a", "##. Organize/a.pdf"))
    calls = []

    def crash_once(src, dst):
        calls.append(1)
        raise SystemExit("simulated crash")

    monkeypatch.setattr(primitives, "rename_excl", crash_once)
    with pytest.raises(SystemExit):
        Executor(paths, engine, FileRepo(engine, inbox="##. Organize")).apply(
            plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks"))
        )
    monkeypatch.undo()

    fresh = Executor(paths, engine, FileRepo(engine, inbox="##. Organize"))
    pending = fresh.pending()
    assert [(e.state, e.src) for e in pending] == [("planned", "##. Organize/a.pdf")]
    assert isinstance(pending[0], JournalEntry)
    snapshot = tree(fake_archive.root)
    entries = fresh.recover().entries
    assert [(e.state, e.error) for e in entries] == [("failed", "interrupted before execution")]
    assert tree(fake_archive.root) == snapshot  # recover only reads the disk
    assert (fake_archive.root / "##. Organize/a.pdf").exists()
    assert journal(engine)[0]["state"] == "failed"
    assert db_paths(engine)["id-a"][0] == "##. Organize/a.pdf"
    assert fresh.pending() == []


def test_recover_after_crash_after_act(fake_archive, paths, engine, monkeypatch):
    fake_archive.add("##. Organize/a.pdf", drive_id="id-a")
    index(engine, ("id-a", "##. Organize/a.pdf"))

    def crash(self, rop, snap):
        raise SystemExit("simulated crash")

    monkeypatch.setattr(Executor, "_verify", crash)
    with pytest.raises(SystemExit):
        Executor(paths, engine, FileRepo(engine, inbox="##. Organize")).apply(
            plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks"))
        )
    monkeypatch.undo()

    fresh = Executor(paths, engine, FileRepo(engine, inbox="##. Organize"))
    snapshot = tree(fake_archive.root)
    entries = fresh.recover().entries
    assert [(e.state, e.dst) for e in entries] == [("done", "10. Financial/Banks/a.pdf")]
    assert tree(fake_archive.root) == snapshot
    assert journal(engine)[0]["state"] == "done"
    assert db_paths(engine)["id-a"] == ("10. Financial/Banks/a.pdf", "a.pdf", "pdf")
    # a recovered batch can be undone like any other
    assert fresh.undo(entries[0].batch_id).failed is None
    assert (fake_archive.root / "##. Organize/a.pdf").exists()


# --- undo details -------------------------------------------------------------


def test_undo_leaves_created_folders(fake_archive, executor, engine):
    fake_archive.add("##. Organize/a.pdf")
    done = executor.apply(plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks/2026")))
    assert [r["kind"] for r in journal(engine)] == ["mkdir", "move"]
    result = executor.undo(done.batch_id)
    assert result.failed is None
    assert [r.kind for r in result.done] == [K.MOVE]
    assert (fake_archive.root / "##. Organize/a.pdf").exists()
    assert (fake_archive.root / "10. Financial/Banks/2026").is_dir()  # left in place
    assert [r["state"] for r in journal(engine, done.batch_id)] == ["undone", "undone"]


def test_undo_rename_chain(fake_archive, executor):
    fake_archive.add("##. Organize/a.pdf", content=b"A")
    before = tree(fake_archive.root)
    done = executor.apply(
        plan(
            Op(K.RENAME, "##. Organize/a.pdf", "b.pdf"),
            Op(K.RENAME, "##. Organize/b.pdf", "c.pdf"),
        )
    )
    assert [r.dst for r in done.done] == ["##. Organize/b.pdf", "##. Organize/c.pdf"]
    result = executor.undo(done.batch_id)
    assert result.failed is None, result.error
    assert [(r.src, r.dst) for r in result.done] == [
        ("##. Organize/c.pdf", "##. Organize/b.pdf"),
        ("##. Organize/b.pdf", "##. Organize/a.pdf"),
    ]
    assert tree(fake_archive.root) == before


def test_undo_restores_suffixed_entries(fake_archive, executor):
    fake_archive.add("##. Organize/a.pdf", content=b"A")
    fake_archive.add("##. Organize/c.pdf", content=b"C")
    before = tree(fake_archive.root)
    done = executor.apply(
        plan(
            Op(K.RENAME, "##. Organize/a.pdf", "b.pdf"),
            Op(K.RENAME, "##. Organize/c.pdf", "a.pdf"),
        )
    )
    assert done.done[-1].dst == "##. Organize/a_2.pdf"  # vacated names stay taken
    result = executor.undo(done.batch_id)
    assert result.failed is None, result.error
    assert tree(fake_archive.root) == before


def test_undo_move_with_name(fake_archive, executor):
    fake_archive.add("##. Organize/File_000.pdf", content=b"new")
    fake_archive.add("10. Financial/Banks/Taxcard.pdf", content=b"orig")
    before = tree(fake_archive.root)
    done = executor.apply(
        plan(Op(K.MOVE, "##. Organize/File_000.pdf", "10. Financial/Banks", name="Taxcard.pdf"))
    )
    assert done.done[-1].dst == "10. Financial/Banks/Taxcard_2.pdf"
    result = executor.undo(done.batch_id)
    assert result.failed is None, result.error
    assert tree(fake_archive.root) == before


def test_undo_case_only_rename(fake_archive, executor):
    fake_archive.add("##. Organize/File.pdf", drive_id="id-c")
    done = executor.apply(plan(Op(K.RENAME, "##. Organize/File.pdf", "file.pdf")))
    result = executor.undo(done.batch_id)
    assert result.failed is None, result.error
    assert os.listdir(fake_archive.root / "##. Organize") == ["File.pdf"]


def test_undo_restores_into_protected(fake_archive, executor):
    fake_archive.add("##. Important/passport.pdf", drive_id="id-p")
    before = tree(fake_archive.root)
    done = executor.apply(plan(Op(K.MOVE, "##. Important/passport.pdf", "10. Financial/Banks")))
    assert done.failed is None
    result = executor.undo(done.batch_id)
    assert result.failed is None, result.error
    assert tree(fake_archive.root) == before


def test_undo_refuses_if_drive_id_changed(fake_archive, executor, engine):
    import xattr

    from dam.index.driveid import DRIVE_ID_XATTR

    fake_archive.add("##. Organize/a.pdf", drive_id="id-a")
    done = executor.apply(plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks")))
    moved = fake_archive.root / "10. Financial/Banks/a.pdf"
    st = moved.stat()
    xattr.setxattr(moved, DRIVE_ID_XATTR, b"someone-else")
    os.utime(moved, ns=(st.st_atime_ns, st.st_mtime_ns))
    snapshot, rows = tree(fake_archive.root), journal(engine)
    with pytest.raises(OpFailed, match="cannot be undone"):
        executor.undo(done.batch_id)
    assert tree(fake_archive.root) == snapshot
    assert journal(engine) == rows


def test_undo_refuses_if_moved_entry_missing(fake_archive, executor):
    fake_archive.add("##. Organize/a.pdf")
    done = executor.apply(plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks")))
    primitives.rename_excl(
        fake_archive.root / "10. Financial/Banks/a.pdf", fake_archive.root / "10. Financial/x.pdf"
    )
    with pytest.raises(OpFailed, match="cannot be undone"):
        executor.undo(done.batch_id)
    assert not (fake_archive.root / "##. Organize/a.pdf").exists()


def test_undo_partly_failed_batch_reverts_done_rows_only(
    fake_archive, executor, engine, monkeypatch
):
    fake_archive.add("##. Organize/a.pdf")
    fake_archive.add("##. Organize/b.pdf")
    real = primitives.rename_excl
    calls = []

    def fail_second(src, dst):
        calls.append(1)
        if len(calls) == 2:
            raise PermissionError(13, "denied", str(src))
        real(src, dst)

    monkeypatch.setattr(primitives, "rename_excl", fail_second)
    done = executor.apply(
        plan(
            Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks"),
            Op(K.MOVE, "##. Organize/b.pdf", "10. Financial/Banks"),
        )
    )
    monkeypatch.undo()
    assert [r["state"] for r in journal(engine)] == ["done", "failed"]
    result = executor.undo(done.batch_id)
    assert result.failed is None
    assert [(r.src, r.dst) for r in result.done] == [
        ("10. Financial/Banks/a.pdf", "##. Organize/a.pdf")
    ]
    assert [r["state"] for r in journal(engine, done.batch_id)] == ["undone", "failed"]


def test_undo_failing_partway_marks_only_reverted(fake_archive, executor, engine, monkeypatch):
    fake_archive.add("##. Organize/a.pdf")
    fake_archive.add("##. Organize/b.pdf")
    done = executor.apply(
        plan(
            Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks"),
            Op(K.MOVE, "##. Organize/b.pdf", "10. Financial/Banks"),
        )
    )
    real, calls = primitives.rename_excl, []

    def fail_second(src, dst):
        calls.append(1)
        if len(calls) == 2:
            raise PermissionError(13, "denied", str(src))
        real(src, dst)

    monkeypatch.setattr(primitives, "rename_excl", fail_second)
    result = executor.undo(done.batch_id)
    assert result.failed is not None and "denied" in result.error
    # reverse order: b.pdf was reverted, a.pdf was not
    assert (fake_archive.root / "##. Organize/b.pdf").exists()
    assert (fake_archive.root / "10. Financial/Banks/a.pdf").exists()
    assert [r["state"] for r in journal(engine, done.batch_id)] == ["done", "undone"]
    assert [r["state"] for r in journal(engine, result.batch_id)] == ["done", "failed"]

    monkeypatch.undo()
    retry = executor.undo(done.batch_id)  # the rest can still be undone
    assert retry.failed is None
    assert (fake_archive.root / "##. Organize/a.pdf").exists()
    assert [r["state"] for r in journal(engine, done.batch_id)] == ["undone", "undone"]


def test_undo_unverified_row(fake_archive, executor, engine, monkeypatch):
    fake_archive.add("##. Organize/a.pdf", drive_id="id-a")

    def bad_verify(self, rop, snap):
        raise OpFailed("verification failed")

    monkeypatch.setattr(Executor, "_verify", bad_verify)
    done = executor.apply(plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks")))
    monkeypatch.undo()
    assert journal(engine)[0]["state"] == "unverified"
    result = executor.undo(done.batch_id)
    assert result.failed is None, result.error
    assert (fake_archive.root / "##. Organize/a.pdf").exists()
    assert journal(engine, done.batch_id)[0]["state"] == "undone"


def test_undo_refuses_batch_with_planned_rows(fake_archive, executor, engine, monkeypatch):
    fake_archive.add("##. Organize/a.pdf")

    def crash(src, dst):
        raise SystemExit("simulated crash")

    monkeypatch.setattr(primitives, "rename_excl", crash)
    with pytest.raises(SystemExit):
        executor.apply(plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks")))
    monkeypatch.undo()
    batch_id = journal(engine)[0]["batch_id"]
    with pytest.raises(OpFailed, match="recover"):
        executor.undo(batch_id)


def test_undo_unknown_batch(executor):
    with pytest.raises(OpFailed, match="could not be found"):
        executor.undo("nope")


def test_undo_symlink(fake_archive, executor, engine):
    fake_archive.add("10. Financial/Banks/a.pdf")
    before = tree(fake_archive.root)
    done = executor.apply(plan(Op(K.SYMLINK, "10. Financial/Banks/a.pdf", "##. Ongoing/a.pdf")))
    assert (fake_archive.root / "##. Ongoing/a.pdf").is_symlink()
    result = executor.undo(done.batch_id)
    assert result.failed is None, result.error
    assert [r.kind for r in result.done] == [K.UNLINK_SYMLINK]
    assert tree(fake_archive.root) == before
    assert journal(engine, done.batch_id)[0]["state"] == "undone"


def test_undo_symlink_outside_ongoing_removes_the_link_the_app_made(fake_archive, executor, engine):
    # the owner's approved exception: undo may remove a link the app made, anywhere
    fake_archive.add("10. Financial/Banks/a.pdf")
    before = tree(fake_archive.root)
    done = executor.apply(plan(Op(K.SYMLINK, "10. Financial/Banks/a.pdf", "10. Financial/a.pdf")))
    assert (fake_archive.root / "10. Financial/a.pdf").is_symlink()
    result = executor.undo(done.batch_id)
    assert result.failed is None, result.error
    assert [r.kind for r in result.done] == [K.UNLINK_SYMLINK]
    assert tree(fake_archive.root) == before
    assert (fake_archive.root / "10. Financial/Banks/a.pdf").exists()  # the original stays
    assert journal(engine, done.batch_id)[0]["state"] == "undone"


def test_undo_symlink_outside_ongoing_never_removes_a_regular_file(fake_archive, executor):
    fake_archive.add("10. Financial/Banks/a.pdf")
    done = executor.apply(plan(Op(K.SYMLINK, "10. Financial/Banks/a.pdf", "10. Financial/a.pdf")))
    link = fake_archive.root / "10. Financial/a.pdf"
    primitives.unlink_symlink(link, fake_archive.root)  # the user replaced it by a real file
    link.write_bytes(b"mine")
    with pytest.raises(OpFailed, match="cannot be undone"):
        executor.undo(done.batch_id)
    assert link.read_bytes() == b"mine"


def test_undo_symlink_outside_ongoing_never_removes_a_folder(fake_archive, executor):
    fake_archive.add("10. Financial/Banks/a.pdf")
    done = executor.apply(plan(Op(K.SYMLINK, "10. Financial/Banks/a.pdf", "10. Financial/a.pdf")))
    link = fake_archive.root / "10. Financial/a.pdf"
    primitives.unlink_symlink(link, fake_archive.root)
    link.mkdir()
    with pytest.raises(OpFailed, match="cannot be undone"):
        executor.undo(done.batch_id)
    assert link.is_dir()


def test_undo_symlink_outside_ongoing_leaves_a_link_pointing_elsewhere(fake_archive, executor):
    fake_archive.add("10. Financial/Banks/a.pdf")
    fake_archive.add("10. Financial/Banks/b.pdf")
    done = executor.apply(plan(Op(K.SYMLINK, "10. Financial/Banks/a.pdf", "10. Financial/a.pdf")))
    link = fake_archive.root / "10. Financial/a.pdf"
    primitives.unlink_symlink(link, fake_archive.root)
    link.symlink_to(fake_archive.root / "10. Financial/Banks/b.pdf")  # not the app's link
    with pytest.raises(OpFailed, match="cannot be undone"):
        executor.undo(done.batch_id)
    assert link.is_symlink()


def test_undo_symlink_outside_ongoing_refuses_a_link_the_app_did_not_make(fake_archive, executor):
    # a user's own link: nothing in the journal made it, and a plan cannot ask to remove it
    fake_archive.add("10. Financial/Banks/a.pdf")
    fake_archive.link("10. Financial/mine.pdf", "10. Financial/Banks/a.pdf")
    with pytest.raises(GuardError, match="can be removed"):
        executor.apply(plan(Op(K.UNLINK_SYMLINK, "10. Financial/mine.pdf", None)))
    with pytest.raises(GuardError, match="can be removed"):
        # not even with the flags only an undo may set
        executor.apply(
            plan(
                Op(
                    K.UNLINK_SYMLINK,
                    "10. Financial/mine.pdf",
                    "10. Financial/Banks/a.pdf",
                    exact=True,
                )
            )
        )
    assert (fake_archive.root / "10. Financial/mine.pdf").is_symlink()


def test_undo_symlink_refuses_if_link_repointed(fake_archive, executor):
    fake_archive.add("10. Financial/Banks/a.pdf")
    fake_archive.add("10. Financial/Banks/b.pdf")
    done = executor.apply(plan(Op(K.SYMLINK, "10. Financial/Banks/a.pdf", "##. Ongoing/a.pdf")))
    link = fake_archive.root / "##. Ongoing/a.pdf"
    primitives.unlink_symlink(link, fake_archive.root / "##. Ongoing")
    link.symlink_to(fake_archive.root / "10. Financial/Banks/b.pdf")
    with pytest.raises(OpFailed, match="cannot be undone"):
        executor.undo(done.batch_id)
    assert link.is_symlink()


def test_undo_unlink_symlink_inside_archive(fake_archive, executor, engine):
    fake_archive.add("10. Financial/Banks/a.pdf")
    fake_archive.link("##. Ongoing/a.pdf", "10. Financial/Banks/a.pdf")
    before = tree(fake_archive.root)
    done = executor.apply(plan(Op(K.UNLINK_SYMLINK, "##. Ongoing/a.pdf", None)))
    assert not os.path.lexists(fake_archive.root / "##. Ongoing/a.pdf")
    result = executor.undo(done.batch_id)
    assert result.failed is None, result.error
    assert tree(fake_archive.root) == before
    assert journal(engine, done.batch_id)[0]["state"] == "undone"


def test_undo_unlink_symlink_outside_target(fake_archive, executor, engine, tmp_path):
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("x", encoding="utf-8")
    link = fake_archive.root / "##. Ongoing/ext.txt"
    link.symlink_to(outside)
    done = executor.apply(plan(Op(K.UNLINK_SYMLINK, "##. Ongoing/ext.txt", None)))
    assert journal(engine)[0]["dst"] == "abs:" + str(outside)
    result = executor.undo(done.batch_id)
    assert result.failed is None, result.error
    assert readlink(link) == str(outside)
    assert outside.read_text(encoding="utf-8") == "x"
    assert journal(engine, done.batch_id)[0]["state"] == "undone"


def test_undo_unlink_symlink_refuses_if_link_path_occupied(fake_archive, executor):
    fake_archive.add("10. Financial/Banks/a.pdf")
    fake_archive.link("##. Ongoing/a.pdf", "10. Financial/Banks/a.pdf")
    done = executor.apply(plan(Op(K.UNLINK_SYMLINK, "##. Ongoing/a.pdf", None)))
    fake_archive.add("##. Ongoing/a.pdf", content=b"real file")
    with pytest.raises(GuardError, match="occupied"):
        executor.undo(done.batch_id)
    assert (fake_archive.root / "##. Ongoing/a.pdf").read_bytes() == b"real file"


def test_abs_link_target_needs_exact(fake_archive, paths, tmp_path):
    with pytest.raises(GuardError):
        Planner(paths).resolve(
            plan(Op(K.SYMLINK, f"abs:{tmp_path}", "##. Ongoing/x")), restore=True
        )


def _forged_restores(tmp_path):
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("x", encoding="utf-8")
    return [
        Op(K.SYMLINK, f"abs:{outside}", "10. Financial/hosts", exact=True),
        Op(K.MOVE, "##. To Delete/Old Stuff", "", allow_top_level=True, exact=True),
    ]


@pytest.mark.parametrize("which", [0, 1], ids=["abs-symlink", "move-into-root"])
def test_origin_undo_refused_by_apply_and_preview(fake_archive, executor, engine, tmp_path, which):
    fake_archive.add("##. To Delete/Old Stuff/a.pdf")
    op = _forged_restores(tmp_path)[which]
    snapshot = tree(fake_archive.root)
    with pytest.raises(GuardError, match="reserved"):
        executor.preview(Plan([op], origin="undo"))
    with pytest.raises(GuardError, match="reserved"):
        executor.apply(Plan([op], origin="undo"))
    with pytest.raises(GuardError, match="reserved"):
        executor.apply(Plan([op], origin="undo"), dry_run=True)
    assert tree(fake_archive.root) == snapshot
    assert journal(engine) == []


def test_inverse_must_restore_journaled_source(executor, paths):
    row = JournalEntry(
        id=1, batch_id="b", seq=0, kind="move", src="10. Financial/a.pdf",
        dst="##. Organize/a.pdf", drive_id=None, size=None, mtime=None, is_file=True,
        state="done", error=None, origin="cli", undo_of=None, created=0.0, finished=None,
    )  # fmt: skip
    with pytest.raises(OpFailed, match="does not restore"):
        _check_restores_origin(executor, Op(K.MOVE, "##. Organize/a.pdf", "10. Financial",
                                            name="b.pdf"), row)  # fmt: skip
    top = dataclasses.replace(row, src="a.pdf")
    _check_restores_origin(executor, Op(K.MOVE, "x/a.pdf", "", name="a.pdf"), top)
    with pytest.raises(OpFailed, match="does not restore"):
        _check_restores_origin(executor, Op(K.MOVE, "x/a.pdf", "", name="a.pdf"), row)


def test_journal_records_is_file(fake_archive, executor, engine):
    fake_archive.add("##. Organize/a.pdf")
    executor.apply(plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks/2026")))
    assert [(r["kind"], r["is_file"]) for r in journal(engine)] == [
        ("mkdir", None),
        ("move", True),
    ]


def test_undo_refuses_if_folder_replaced_file(fake_archive, executor, engine):
    fake_archive.add("##. Organize/a.pdf", drive_id=None)
    done = executor.apply(plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks")))
    moved = fake_archive.root / "10. Financial/Banks/a.pdf"
    primitives.rename_excl(moved, fake_archive.root / "10. Financial/x.pdf")
    moved.mkdir()
    snapshot, rows = tree(fake_archive.root), journal(engine)
    with pytest.raises(OpFailed, match="cannot be undone"):
        executor.undo(done.batch_id)
    assert tree(fake_archive.root) == snapshot
    assert journal(engine) == rows


def test_exact_refuses_instead_of_suffixing(fake_archive, executor):
    fake_archive.add("##. Organize/a.pdf")
    fake_archive.add("10. Financial/Banks/a.pdf")
    with pytest.raises(GuardError, match="occupied"):
        executor.preview(plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks", exact=True)))


def test_undo_of_undo_refused(fake_archive, executor, engine):
    fake_archive.add("##. Organize/a.pdf")
    done = executor.apply(plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks")))
    undo = executor.undo(done.batch_id)
    snapshot, rows = tree(fake_archive.root), journal(engine)
    with pytest.raises(OpFailed, match="cannot be undone again"):
        executor.undo(undo.batch_id)
    assert tree(fake_archive.root) == snapshot
    assert journal(engine) == rows


def test_abs_link_target_needs_undo_origin(fake_archive, executor, engine, tmp_path):
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("x", encoding="utf-8")
    op = Op(K.SYMLINK, f"abs:{outside}", "10. Financial/hosts", exact=True)
    with pytest.raises(GuardError):
        executor.apply(Plan([op], origin="cli"))
    assert not os.path.lexists(fake_archive.root / "10. Financial/hosts")
    assert journal(engine) == []


def test_undo_quarantine_of_top_level_folder(fake_archive, executor, engine):
    fake_archive.add("Old Stuff/a.pdf", content=b"A")
    before = tree(fake_archive.root)
    done = executor.apply(plan(Op(K.QUARANTINE, "Old Stuff", None, allow_top_level=True)))
    assert done.failed is None, done.error
    assert (fake_archive.root / "##. To Delete/Old Stuff/a.pdf").exists()
    result = executor.undo(done.batch_id)
    assert result.failed is None, result.error
    assert tree(fake_archive.root) == before
    assert [r["state"] for r in journal(engine, done.batch_id)] == ["undone"]


@pytest.mark.parametrize("origin", ["cli", "ui", "workflow"])
def test_move_into_root_refused_outside_undo(fake_archive, executor, engine, origin):
    fake_archive.add("##. To Delete/Old Stuff/a.pdf")
    op = Op(K.MOVE, "##. To Delete/Old Stuff", "", allow_top_level=True, exact=True)
    with pytest.raises(GuardError, match="archive folder"):
        executor.apply(Plan([op], origin=origin))
    assert not (fake_archive.root / "Old Stuff").exists()
    assert journal(engine) == []


def test_undo_unverified_inverse_marks_original_and_retry_finishes(
    fake_archive, executor, engine, monkeypatch
):
    fake_archive.add("##. Organize/a.pdf")
    fake_archive.add("##. Organize/b.pdf")
    done = executor.apply(
        plan(
            Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks"),
            Op(K.MOVE, "##. Organize/b.pdf", "10. Financial/Banks"),
        )
    )

    def bad_verify(self, rop, snap):
        raise OpFailed("verification failed")

    monkeypatch.setattr(Executor, "_verify", bad_verify)
    first = executor.undo(done.batch_id)
    monkeypatch.undo()
    assert first.failed is not None
    assert [r["state"] for r in journal(engine, first.batch_id)] == ["unverified"]
    # the inverse of row 2 (b.pdf) acted: its original is undone, row 1 is not
    assert [r["state"] for r in journal(engine, done.batch_id)] == ["done", "undone"]
    retry = executor.undo(done.batch_id)
    assert retry.failed is None, retry.error
    assert (fake_archive.root / "##. Organize/a.pdf").exists()
    assert (fake_archive.root / "##. Organize/b.pdf").exists()
    assert [r["state"] for r in journal(engine, done.batch_id)] == ["undone", "undone"]


# --- recovery details ------------------------------------------------------------


def _crash_in_act(executor, monkeypatch, op: Op, attr: str = "rename_excl") -> str:
    def crash(*a, **k):
        raise SystemExit("simulated crash")

    monkeypatch.setattr(primitives, attr, crash)
    with pytest.raises(SystemExit):
        executor.apply(plan(op))
    monkeypatch.undo()
    return journal(executor.engine)[-1]["batch_id"]


def test_recover_needs_manual_check(fake_archive, executor, engine, monkeypatch):
    fake_archive.add("##. Organize/a.pdf", drive_id="id-a")
    index(engine, ("id-a", "##. Organize/a.pdf"))
    _crash_in_act(executor, monkeypatch, Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks"))
    fake_archive.add("10. Financial/Banks/a.pdf")  # both ends now present
    snapshot, db_before = tree(fake_archive.root), db_paths(engine)
    entries = executor.recover().entries
    assert tree(fake_archive.root) == snapshot
    assert db_paths(engine) == db_before
    assert [(e.state, e.error) for e in entries] == [("failed", "needs manual check")]


def test_recover_done_requires_same_drive_id(fake_archive, executor, engine, monkeypatch):
    fake_archive.add("##. Organize/a.pdf", drive_id="id-a")
    _crash_in_act(executor, monkeypatch, Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks"))
    # src vanished and some *other* entry sits at dst
    primitives.rename_excl(
        fake_archive.root / "##. Organize/a.pdf", fake_archive.root / "10. Financial/x.pdf"
    )
    fake_archive.add("10. Financial/Banks/a.pdf", drive_id="id-other")
    entries = executor.recover().entries
    assert [(e.state, e.error) for e in entries] == [("failed", "needs manual check")]


def test_recover_mkdir_and_symlink(fake_archive, executor, engine, monkeypatch):
    _crash_in_act(executor, monkeypatch, Op(K.MKDIR, None, "10. Financial/New"), "make_dir")
    fake_archive.add("10. Financial/Banks/a.pdf")
    _crash_in_act(
        executor,
        monkeypatch,
        Op(K.SYMLINK, "10. Financial/Banks/a.pdf", "##. Ongoing/a.pdf"),
        "make_symlink",
    )
    # the symlink actually got created before the crash
    (fake_archive.root / "##. Ongoing/a.pdf").symlink_to(
        fake_archive.root / "10. Financial/Banks/a.pdf"
    )
    entries = executor.recover().entries
    assert [(e.kind, e.state, e.error) for e in entries] == [
        ("mkdir", "failed", "interrupted before execution"),
        ("symlink", "done", None),
    ]


def test_recover_unlink_symlink(fake_archive, executor, monkeypatch):
    fake_archive.add("10. Financial/Banks/a.pdf")
    fake_archive.link("##. Ongoing/a.pdf", "10. Financial/Banks/a.pdf")
    _crash_in_act(
        executor, monkeypatch, Op(K.UNLINK_SYMLINK, "##. Ongoing/a.pdf", None), "unlink_symlink"
    )
    assert [(e.state, e.error) for e in executor.recover().entries] == [
        ("failed", "interrupted before execution")
    ]


def test_recover_case_only_rename_after_act(fake_archive, executor, engine, monkeypatch):
    fake_archive.add("##. Organize/File.pdf", drive_id="id-c")

    def crash(self, rop, snap):
        raise SystemExit("simulated crash")

    monkeypatch.setattr(Executor, "_verify", crash)
    with pytest.raises(SystemExit):
        executor.apply(plan(Op(K.RENAME, "##. Organize/File.pdf", "file.pdf")))
    monkeypatch.undo()
    assert [(e.state, e.error) for e in executor.recover().entries] == [("done", None)]


def test_recover_undo_row_marks_original_undone(fake_archive, executor, engine, monkeypatch):
    fake_archive.add("##. Organize/a.pdf")
    done = executor.apply(plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks")))

    def crash(self, rop, snap):
        raise SystemExit("simulated crash")

    monkeypatch.setattr(Executor, "_verify", crash)
    with pytest.raises(SystemExit):
        executor.undo(done.batch_id)
    monkeypatch.undo()
    assert journal(engine, done.batch_id)[0]["state"] == "done"
    entries = executor.recover().entries
    assert [(e.state, e.undo_of) for e in entries] == [("done", done.batch_id)]
    assert journal(engine, done.batch_id)[0]["state"] == "undone"


def test_undo_file_then_its_folder(fake_archive, executor, engine):
    fake_archive.add("##. Organize/Trip/a.pdf", content=b"A", drive_id="id-a")
    index(engine, ("id-a", "##. Organize/Trip/a.pdf"))
    before, db_before = tree(fake_archive.root), db_paths(engine)
    done = executor.apply(
        plan(
            Op(K.RENAME, "##. Organize/Trip/a.pdf", "b.pdf"),
            Op(K.MOVE, "##. Organize/Trip", "10. Financial"),
        )
    )
    assert done.failed is None
    assert db_paths(engine)["id-a"][0] == "10. Financial/Trip/b.pdf"
    result = executor.undo(done.batch_id)
    assert result.failed is None, result.error
    assert tree(fake_archive.root) == before
    assert db_paths(engine) == db_before


def test_undo_file_then_its_folder_detects_change(fake_archive, executor):
    fake_archive.add("##. Organize/Trip/a.pdf", content=b"A")
    done = executor.apply(
        plan(
            Op(K.RENAME, "##. Organize/Trip/a.pdf", "b.pdf"),
            Op(K.MOVE, "##. Organize/Trip", "10. Financial"),
        )
    )
    with open(fake_archive.root / "10. Financial/Trip/b.pdf", "ab") as f:
        f.write(b"edited")
    snapshot = tree(fake_archive.root)
    with pytest.raises(OpFailed, match="cannot be undone"):
        executor.undo(done.batch_id)
    assert tree(fake_archive.root) == snapshot


def test_recover_size_check_without_drive_id(fake_archive, executor, monkeypatch):
    fake_archive.add("##. Organize/a.pdf", content=b"abc", drive_id=None)
    _crash_in_act(executor, monkeypatch, Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks"))
    # src vanished; a different-sized file sits at dst
    primitives.rename_excl(
        fake_archive.root / "##. Organize/a.pdf", fake_archive.root / "10. Financial/x.pdf"
    )
    fake_archive.add("10. Financial/Banks/a.pdf", content=b"other content", drive_id=None)
    entries = executor.recover().entries
    assert [(e.state, e.error) for e in entries] == [("failed", "needs manual check")]


def test_recover_size_match_without_drive_id(fake_archive, executor, monkeypatch):
    fake_archive.add("##. Organize/a.pdf", content=b"abc", drive_id=None)

    def crash(self, rop, snap):
        raise SystemExit("simulated crash")

    monkeypatch.setattr(Executor, "_verify", crash)
    with pytest.raises(SystemExit):
        executor.apply(plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks")))
    monkeypatch.undo()
    assert [(e.state, e.error) for e in executor.recover().entries] == [("done", None)]


def test_recover_collects_index_errors_and_continues(fake_archive, executor, engine, monkeypatch):
    fake_archive.add("##. Organize/a.pdf", drive_id="id-a")
    fake_archive.add("##. Organize/b.pdf", drive_id="id-b")
    index(
        engine,
        ("id-a", "##. Organize/a.pdf"),
        ("id-b", "##. Organize/b.pdf"),
        ("stale", "10. Financial/Banks/a.pdf"),  # UNIQUE conflict for a.pdf's new path
    )

    def crash(self, rop, snap):
        raise SystemExit("simulated crash")

    monkeypatch.setattr(Executor, "_verify", crash)
    for name in ("a.pdf", "b.pdf"):
        with pytest.raises(SystemExit):
            executor.apply(plan(Op(K.MOVE, f"##. Organize/{name}", "10. Financial/Banks")))
    monkeypatch.undo()
    result = executor.recover()
    assert [e.state for e in result.entries] == ["done", "done"]
    assert len(result.index_errors) == 1 and "10. Financial/Banks/a.pdf" in result.index_errors[0]
    assert db_paths(engine)["id-b"][0] == "10. Financial/Banks/b.pdf"  # second row still ran
    assert [r["state"] for r in journal(engine)] == ["done", "done"]


def test_recover_folder_replaced_file_needs_manual_check(fake_archive, executor, monkeypatch):
    fake_archive.add("##. Organize/a.pdf", drive_id=None)
    _crash_in_act(executor, monkeypatch, Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks"))
    primitives.rename_excl(
        fake_archive.root / "##. Organize/a.pdf", fake_archive.root / "10. Financial/x.pdf"
    )
    (fake_archive.root / "10. Financial/Banks/a.pdf").mkdir()  # a folder, not the file
    entries = executor.recover().entries
    assert [(e.state, e.error) for e in entries] == [("failed", "needs manual check")]


# --- quarantine root created on demand (final review item 1) -------------------


def test_quarantine_creates_missing_quarantine_root_and_undo_restores(
    fake_archive, executor, engine
):
    (fake_archive.root / "##. To Delete").rmdir()
    fake_archive.add("10. Financial/Banks/old.pdf", content=b"old", drive_id="id-q")
    index(engine, ("id-q", "10. Financial/Banks/old.pdf"))
    resolved = executor.preview(plan(Op(K.QUARANTINE, "10. Financial/Banks/old.pdf", None)))
    assert [(r.kind, r.dst) for r in resolved] == [
        (K.MKDIR, "##. To Delete"),
        (K.MKDIR, "##. To Delete/10. Financial"),
        (K.MKDIR, "##. To Delete/10. Financial/Banks"),
        (K.QUARANTINE, "##. To Delete/10. Financial/Banks/old.pdf"),
    ]
    done = executor.apply(plan(Op(K.QUARANTINE, "10. Financial/Banks/old.pdf", None)))
    assert done.failed is None, done.error
    assert (fake_archive.root / "##. To Delete/10. Financial/Banks/old.pdf").exists()

    result = executor.undo(done.batch_id)
    assert result.failed is None, result.error
    assert read_drive_id(fake_archive.root / "10. Financial/Banks/old.pdf") == "id-q"
    assert (fake_archive.root / "##. To Delete/10. Financial/Banks").is_dir()  # folders stay


@pytest.mark.parametrize(
    "op",
    [
        Op(K.MKDIR, None, "##. To Delete"),
        Op(K.MKDIR, None, "99. New"),
        Op(K.MOVE, "##. Organize/a.pdf", "##. To Delete"),
        Op(K.MOVE, "##. Organize/a.pdf", "99. New/sub"),
    ],
    ids=["mkdir-quarantine", "mkdir-other", "move-into-quarantine", "move-new-top"],
)
def test_only_quarantine_op_may_create_top_level_folder(fake_archive, executor, engine, op):
    (fake_archive.root / "##. To Delete").rmdir()
    fake_archive.add("##. Organize/a.pdf")
    with pytest.raises(GuardError, match="top-level"):
        executor.apply(plan(op))
    assert not (fake_archive.root / "##. To Delete").exists()
    assert not (fake_archive.root / "99. New").exists()
    assert journal(engine) == []


# --- identity via drive id (final review item 5) --------------------------------


def _move_one(fake_archive, executor, drive_id):
    fake_archive.add("##. Organize/a.pdf", content=b"abc", drive_id=drive_id)
    done = executor.apply(plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks")))
    assert done.failed is None
    return done, fake_archive.root / "10. Financial/Banks/a.pdf"


def test_undo_allows_mtime_only_change_with_same_drive_id(fake_archive, executor):
    done, moved = _move_one(fake_archive, executor, "id-a")
    os.utime(moved, (1_000_000, 1_000_000))  # Drive touched the mtime
    result = executor.undo(done.batch_id)
    assert result.failed is None and result.error is None
    assert read_drive_id(fake_archive.root / "##. Organize/a.pdf") == "id-a"


def test_undo_refuses_size_change_with_same_drive_id(fake_archive, executor):
    done, moved = _move_one(fake_archive, executor, "id-a")
    moved.write_bytes(b"abcd")
    with pytest.raises(OpFailed, match="cannot be undone"):
        executor.undo(done.batch_id)


def test_undo_refuses_mtime_change_without_drive_id(fake_archive, executor):
    done, moved = _move_one(fake_archive, executor, None)
    os.utime(moved, (1_000_000, 1_000_000))
    with pytest.raises(OpFailed, match="cannot be undone"):
        executor.undo(done.batch_id)


def _crash_after_act(fake_archive, paths, engine, monkeypatch, drive_id):
    fake_archive.add("##. Organize/a.pdf", content=b"abc", drive_id=drive_id)

    def crash(self, rop, snap):
        raise SystemExit("simulated crash")

    monkeypatch.setattr(Executor, "_verify", crash)
    with pytest.raises(SystemExit):
        Executor(paths, engine, FileRepo(engine, inbox="##. Organize")).apply(
            plan(Op(K.MOVE, "##. Organize/a.pdf", "10. Financial/Banks"))
        )
    monkeypatch.undo()
    return Executor(paths, engine, FileRepo(engine, inbox="##. Organize"))


def test_recover_with_drive_id_ignores_mtime(fake_archive, paths, engine, monkeypatch):
    fresh = _crash_after_act(fake_archive, paths, engine, monkeypatch, "id-a")
    os.utime(fake_archive.root / "10. Financial/Banks/a.pdf", (1_000_000, 1_000_000))
    assert [e.state for e in fresh.recover().entries] == ["done"]


def test_recover_with_drive_id_checks_size(fake_archive, paths, engine, monkeypatch):
    fresh = _crash_after_act(fake_archive, paths, engine, monkeypatch, "id-a")
    (fake_archive.root / "10. Financial/Banks/a.pdf").write_bytes(b"abcd")
    assert [(e.state, e.error) for e in fresh.recover().entries] == [
        ("failed", "needs manual check")
    ]


# --- REMOVE_EMPTY_DIR (Phase 2 Task 8) --------------------------------------------


@needs_dir_fd
def test_undo_remove_empty_dir_recreates_folder(fake_archive, executor, engine):
    folder = fake_archive.root / "##. Ongoing/Tax 2026"
    folder.mkdir()
    (folder / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1" + b"\x00" * 24)
    done = executor.apply(Plan([Op(K.REMOVE_EMPTY_DIR, "##. Ongoing/Tax 2026", None)], "ui"))
    assert done.failed is None, done.error
    assert not os.path.lexists(folder)
    result = executor.undo(done.batch_id)
    assert result.failed is None, result.error
    assert [(r.kind, r.dst) for r in result.done] == [(K.MKDIR, "##. Ongoing/Tax 2026")]
    assert folder.is_dir() and not folder.is_symlink()
    assert os.listdir(folder) == []  # .DS_Store is never restored
    assert journal(engine, done.batch_id)[0]["state"] == "undone"
    (inv,) = journal(engine, result.batch_id)
    assert (inv["kind"], inv["state"], inv["undo_of"]) == (K.MKDIR, "done", done.batch_id)


def test_undo_remove_empty_dir_refuses_if_occupied(fake_archive, executor, engine):
    folder = fake_archive.root / "##. Ongoing/Tax"
    folder.mkdir()
    done = executor.apply(Plan([Op(K.REMOVE_EMPTY_DIR, "##. Ongoing/Tax", None)], "ui"))
    folder.mkdir()  # someone made it again
    with pytest.raises(GuardError, match="occupied"):
        executor.undo(done.batch_id)
    folder.rmdir()
    fake_archive.add("##. Ongoing/TAX", content=b"a file now")  # case variant, a file
    with pytest.raises(GuardError, match="occupied"):
        executor.undo(done.batch_id)
    assert (fake_archive.root / "##. Ongoing/TAX").read_bytes() == b"a file now"
    assert journal(engine, done.batch_id)[0]["state"] == "done"


def test_undo_unlinks_then_remove_restores_links(fake_archive, executor):
    fake_archive.add("10. Financial/Banks/a.pdf")
    fake_archive.link("##. Ongoing/Tax/a.pdf", "10. Financial/Banks/a.pdf")
    before = tree(fake_archive.root)
    done = executor.apply(
        Plan(
            [
                Op(K.UNLINK_SYMLINK, "##. Ongoing/Tax/a.pdf", None),
                Op(K.REMOVE_EMPTY_DIR, "##. Ongoing/Tax", None),
            ],
            "cli",
        )
    )
    assert done.failed is None, done.error
    result = executor.undo(done.batch_id)
    assert result.failed is None, result.error
    assert [r.kind for r in result.done] == [K.MKDIR, K.SYMLINK]
    assert tree(fake_archive.root) == before


def test_exact_mkdir_refuses_existing_folder(fake_archive, paths):
    with pytest.raises(GuardError, match="occupied"):
        Planner(paths).resolve(Plan([Op(K.MKDIR, None, "10. Financial/Banks", exact=True)], "cli"))


def test_recover_remove_empty_dir(fake_archive, executor, monkeypatch):
    for name in ("Gone", "Stays"):
        (fake_archive.root / "##. Ongoing" / name).mkdir()
    op = Op(K.REMOVE_EMPTY_DIR, "##. Ongoing/Gone", None)
    _crash_in_act(executor, monkeypatch, op, "remove_empty_dir")
    (fake_archive.root / "##. Ongoing/Gone").rmdir()  # it did happen before the crash
    _crash_in_act(
        executor, monkeypatch, Op(K.REMOVE_EMPTY_DIR, "##. Ongoing/Stays", None), "remove_empty_dir"
    )
    assert [(e.src, e.state, e.error) for e in executor.recover().entries] == [
        ("##. Ongoing/Gone", "done", None),
        ("##. Ongoing/Stays", "failed", "interrupted before execution"),
    ]


def test_undo_refuses_automatic_ongoing_syncs(fake_archive, executor, engine):
    fake_archive.add("10. Financial/Banks/a.pdf")
    fake_archive.link("##. Ongoing/Tax/a.pdf", "10. Financial/Banks/a.pdf")
    done = executor.apply(Plan([Op(K.UNLINK_SYMLINK, "##. Ongoing/Tax/a.pdf", None)], "workflow"))
    assert done.failed is None
    with pytest.raises(OpFailed, match="automatic Ongoing update"):
        executor.undo(done.batch_id)
    assert not (fake_archive.root / "##. Ongoing/Tax/a.pdf").is_symlink()
    assert [r["state"] for r in journal(engine, done.batch_id)] == ["done"]


def test_undo_waits_for_folder(extra_folder, app):
    src = extra_folder.add("2009/a.pdf", b"a", drive_id="x1")
    app.scan()
    result = app.browse.move(["x1"], "Old years/2010", origin="ui")
    assert result.failed is None and result.error is None
    root = extra_folder.root.resolve()
    gone = root.with_name("away")
    os.rename(root, gone)
    message = f"'Old years' is not connected ({root}). Connect it and try again."
    with pytest.raises(GuardError) as e:
        app.executor.preview_undo(result.batch_id)
    assert str(e.value) == message
    with pytest.raises(GuardError) as e:
        app.executor.undo(result.batch_id)
    assert str(e.value) == message
    assert (gone / "2010" / "a.pdf").read_bytes() == b"a"
    os.rename(gone, root)  # plugged in again: the undo goes through
    undone = app.executor.undo(result.batch_id)
    assert undone.failed is None and undone.error is None
    assert src.read_bytes() == b"a"
