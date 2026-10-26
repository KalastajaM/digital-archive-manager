"""File identity (dam.ops.identity): per-platform birth time, comparison rules, large
Windows file indexes, and migration 0024 with rows written by an older version."""

import os
import stat
import sys
import types
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from dam.db.engine import MIGRATIONS_DIR, make_engine, migrate, write_tx
from dam.ops import identity
from dam.ops.identity import Identity, same, same_object
from dam.ops.model import GuardError
from dam.ops.primitives import remove_empty_dir
from fsswap import recreate_dir, recreate_link


def fake_stat(mode=stat.S_IFDIR, ino=5, dev=7, ctime_ns=1000, **extra):
    return types.SimpleNamespace(
        st_mode=mode, st_ino=ino, st_dev=dev, st_ctime_ns=ctime_ns, **extra
    )


# -- birth, per platform ----------------------------------------------------------------


def test_macos_and_windows_use_the_birth_time_of_stat():
    st = fake_stat(st_birthtime=1_700_000_000.5)
    assert identity.of_stat(st) == Identity(7, 5, "b:1700000000500000000")
    st = fake_stat(st_birthtime_ns=1_700_000_000_123_456_789)
    assert identity.of_stat(st).birth == "b:1700000000123456789"


def test_linux_uses_statx_birth_for_folders_and_links(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(identity, "_statx_birth_ns", lambda path, fd: 42)
    assert identity.of_stat(fake_stat(), path="/x").birth == "b:42"
    assert identity.of_stat(fake_stat(stat.S_IFLNK), path="/x").birth == "b:42"
    assert identity.of_stat(fake_stat(), fd=3).birth == "b:42"


def test_linux_without_statx_links_fall_back_to_ctime_folders_to_nothing(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(identity, "_statx_birth_ns", lambda path, fd: None)
    assert identity.of_stat(fake_stat(stat.S_IFLNK), path="/x").birth == "c:1000"
    # a folder's ctime moves whenever an entry comes or goes: never used
    assert identity.of_stat(fake_stat(), path="/x").birth is None


def test_other_platforms_without_birth_time_know_only_dev_and_ino(monkeypatch):
    monkeypatch.setattr(sys, "platform", "freebsd14")
    assert identity.of_stat(fake_stat(stat.S_IFLNK), path="/x") == Identity(7, 5, None)


# -- comparison -----------------------------------------------------------------------


def test_same_needs_equal_dev_ino_and_equal_known_birth():
    rec = Identity(1, 2, "b:10")
    assert same(rec, Identity(1, 2, "b:10"))
    assert not same(rec, Identity(1, 2, "b:11"))  # inode reused, newly created
    assert not same(rec, Identity(1, 3, "b:10"))
    assert not same(rec, Identity(2, 2, "b:10"))
    assert not same(rec, Identity(1, 2, None))  # cannot be verified: never a match
    assert not same(rec, Identity(1, 2, "c:10"))  # a different kind of value
    assert not same(None, Identity(1, 2, "b:10"))


def test_same_object_ignores_the_birth():
    rec = Identity(1, 2, "b:10")
    assert same_object(rec, Identity(1, 2, "b:11"))  # Drive re-wrote it: same inode
    assert same_object(rec, Identity(1, 2, None))
    assert same_object((1, 2), Identity(1, 2, "c:5"))
    assert not same_object(rec, Identity(1, 3, "b:10"))
    assert not same_object(rec, Identity(2, 2, "b:10"))
    assert not same_object(None, Identity(1, 2, "b:10"))


def test_a_record_without_birth_is_compared_on_dev_and_ino():
    old = Identity(1, 2, None)  # a row from before migration 0024
    assert same(old, Identity(1, 2, "b:99"))
    assert not same(old, Identity(1, 3, "b:99"))
    assert same((1, 2), Identity(1, 2, "b:99"))  # a plain pair is such a record


def test_columns_round_trip_a_huge_windows_file_index():
    big = Identity(2**32 + 5, 2**64 - 1, "b:1")
    cols = big.columns()
    assert all(isinstance(v, str) for v in cols.values())
    assert identity.from_columns(cols["st_dev"], cols["st_ino"], cols["st_birth"]) == big
    assert identity.from_columns("1", "2", None) == Identity(1, 2, None)


def test_huge_identity_is_stored_in_the_database(engine):
    from dam.db.tables import collections, ongoing_entries

    big = Identity(1, 2**64 + 3, "b:123")
    with engine.begin() as conn:
        cid = conn.execute(
            collections.insert().values(name="A", name_fold="a", created=1.0)
        ).inserted_primary_key[0]
        conn.execute(
            ongoing_entries.insert().values(
                collection_id=cid, rel="##. Ongoing/A", kind="folder", created=1.0, **big.columns()
            )
        )
        row = conn.execute(ongoing_entries.select()).one()
    assert identity.from_columns(row.st_dev, row.st_ino, row.st_birth) == big


# -- on the real disk -----------------------------------------------------------------


def test_a_folder_deleted_and_recreated_is_a_different_identity(tmp_path: Path):
    d = tmp_path / "a"
    d.mkdir()
    old = identity.of_path(d)
    recreate_dir(d)
    assert not same(old, identity.of_path(d))


def test_a_link_deleted_and_recreated_is_a_different_identity(tmp_path: Path):
    link = tmp_path / "l"
    os.symlink(tmp_path, link)
    old = identity.of_path(link)
    recreate_link(link, tmp_path)
    assert not same(old, identity.of_path(link))


def test_a_folder_filled_and_emptied_is_still_the_same_identity(tmp_path: Path):
    d = tmp_path / "a"
    d.mkdir()
    old = identity.of_path(d)
    (d / "f").write_text("x", encoding="utf-8")
    os.unlink(d / "f")
    assert same(old, identity.of_path(d))


def test_remove_empty_dir_checks_the_fd_identity(tmp_path: Path):
    root = tmp_path / "root"
    (root / "a").mkdir(parents=True)
    old = identity.of_path(root / "a")
    recreate_dir(root / "a")
    with pytest.raises(GuardError, match="identity changed"):
        remove_empty_dir(root / "a", root, old)
    remove_empty_dir(root / "a", root, identity.of_path(root / "a"))
    assert not (root / "a").exists()


def test_remove_empty_dir_accepts_a_folder_whose_birth_changed(tmp_path: Path):
    root = tmp_path / "root"
    (root / "a").mkdir(parents=True)
    now = identity.of_path(root / "a")
    old = Identity(now.dev, now.ino, "b:1")  # as recorded; Drive has re-written it since
    remove_empty_dir(root / "a", root, old)
    assert not (root / "a").exists()


def test_remove_empty_dir_still_refuses_a_non_empty_folder_with_changed_birth(tmp_path: Path):
    root = tmp_path / "root"
    (root / "a").mkdir(parents=True)
    (root / "a" / "f").write_text("x", encoding="utf-8")
    now = identity.of_path(root / "a")
    with pytest.raises(GuardError):
        remove_empty_dir(root / "a", root, Identity(now.dev, now.ino, "b:1"))
    assert (root / "a" / "f").exists()


# -- migration 0024 -------------------------------------------------------------------


def test_migration_0024_keeps_existing_rows(tmp_path: Path):
    engine = make_engine(tmp_path / "old.sqlite")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with write_tx(engine) as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "0023")
    with write_tx(engine) as conn:
        conn.execute(
            text(
                "INSERT INTO collections (id, name, name_fold, created) VALUES (900, 'A', 'a', 1.0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO ongoing_entries (collection_id, rel, kind, link_value, st_dev,"
                " st_ino, created) VALUES (900, '##. Ongoing/A', 'folder', NULL, 16777221,"
                " 9223372036854775807, 2.0),"
                " (900, '##. Ongoing/A/x.pdf', 'link', '../x.pdf', 1, 2, 3.0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO made_folders (batch_id, rel, st_dev, st_ino, created)"
                " VALUES ('b', '10. Finance', '16777221', '4503599627370497', 4.0)"
            )
        )
    migrate(engine)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT rel, kind, link_value, st_dev, st_ino, st_birth, created, typeof(st_ino)"
                " FROM ongoing_entries ORDER BY id"
            )
        ).all()
        made = conn.execute(text("SELECT rel, st_dev, st_ino, st_birth FROM made_folders")).all()
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version == "0036"
    assert [tuple(r) for r in rows] == [
        ("##. Ongoing/A", "folder", None, "16777221", "9223372036854775807", None, 2.0, "text"),
        ("##. Ongoing/A/x.pdf", "link", "../x.pdf", "1", "2", None, 3.0, "text"),
    ]
    assert [tuple(r) for r in made] == [("10. Finance", "16777221", "4503599627370497", None)]
    # an old row has no birth: compared on dev and ino only
    old = identity.from_columns("16777221", "9223372036854775807", None)
    assert same(old, Identity(16777221, 9223372036854775807, "b:5"))
    engine.dispose()
