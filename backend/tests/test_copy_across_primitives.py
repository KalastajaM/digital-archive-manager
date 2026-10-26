"""The verified copy used to move a file between archive folders on different disks."""

import errno
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from dam.ops import primitives
from dam.ops.model import OpFailed
from dam.ops.primitives import TEMP_COPY_PREFIX, copy_across, copy_file, file_sha256


def _source(tmp_path: Path, data: bytes = b"letter") -> Path:
    src = tmp_path / "a" / "x.pdf"
    src.parent.mkdir(parents=True)
    src.write_bytes(data)
    os.utime(src, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
    return src


def _target(tmp_path: Path) -> Path:
    folder = tmp_path / "b"
    folder.mkdir()
    return folder / "x.pdf"


def _temps(folder: Path) -> list[str]:
    return [p.name for p in folder.iterdir() if p.name.startswith(TEMP_COPY_PREFIX)]


def test_copy_across_copies_and_keeps_mtime(tmp_path):
    src, dst = _source(tmp_path), _target(tmp_path)
    copy_across(src, dst, file_sha256(src))
    assert dst.read_bytes() == b"letter"
    assert dst.stat().st_mtime_ns == src.stat().st_mtime_ns
    assert src.exists()
    assert _temps(dst.parent) == []


def test_copy_across_no_size_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(primitives, "MAX_COPY_BYTES", 1)
    src, dst = _source(tmp_path, b"0123456789"), _target(tmp_path)
    copy_across(src, dst, file_sha256(src))
    assert dst.read_bytes() == b"0123456789"


def test_copy_across_hash_mismatch_refuses(tmp_path):
    src, dst = _source(tmp_path), _target(tmp_path)
    with pytest.raises(OpFailed):
        copy_across(src, dst, "0" * 64)
    assert not dst.exists()
    assert src.read_bytes() == b"letter"


def test_final_name_taken_keeps_temp(tmp_path):
    src, dst = _source(tmp_path), _target(tmp_path)
    dst.write_bytes(b"someone else's")
    with pytest.raises(OpFailed) as e:
        copy_across(src, dst, file_sha256(src))
    assert TEMP_COPY_PREFIX in str(e.value)
    assert dst.read_bytes() == b"someone else's"
    assert len(_temps(dst.parent)) == 1


def test_copy_file_stop_between_chunks(tmp_path):
    src, dst = _source(tmp_path, b"x" * (3 * 1024 * 1024)), _target(tmp_path)
    with pytest.raises(OpFailed) as e:
        copy_file(src, dst, limit=None, stop=lambda: True)
    assert dst.name in str(e.value)
    assert dst.exists()  # the partial file stays: dam never deletes
    assert src.stat().st_size == 3 * 1024 * 1024


def test_hashing_stops_between_chunks(tmp_path):
    src = _source(tmp_path, b"x" * (3 * 1024 * 1024))
    with pytest.raises(OpFailed):
        file_sha256(src, stop=lambda: True)


def test_copy_file_reports_bytes_within_a_file(tmp_path, monkeypatch):
    monkeypatch.setattr(primitives, "_COPY_CHUNK", 4)
    src, dst = _source(tmp_path, b"0123456789"), _target(tmp_path)
    seen = []
    copy_across(src, dst, file_sha256(src), on_bytes=seen.append)
    assert seen == [4, 8, 10]


def test_has_room_keeps_the_margin(tmp_path, monkeypatch):
    free = primitives._COPY_FREE_MARGIN + 100
    monkeypatch.setattr(
        primitives.shutil, "disk_usage", lambda p: SimpleNamespace(total=0, used=0, free=free)
    )
    assert primitives.has_room(tmp_path, 100)
    assert not primitives.has_room(tmp_path, 101)


def test_temp_copy_name_length():
    room = primitives.NAME_MAX_BYTES - primitives.TEMP_COPY_EXTRA
    assert len(primitives.temp_copy_name("x.pdf")) == len("x.pdf") + primitives.TEMP_COPY_EXTRA
    assert primitives.temp_copy_too_long("a" * room) == 0
    assert primitives.temp_copy_too_long("a" * (room + 3)) == 3
    assert primitives.temp_copy_too_long("ä" * room) == room  # two bytes each in UTF-8


# --- rename_excl: the system's no-overwrite rename, else check then rename ---------------


@pytest.mark.skipif(sys.platform != "linux", reason="renameat2 is a Linux call")
def test_linux_uses_renameat2(tmp_path):
    assert primitives._renameat2 is not None
    (tmp_path / "a").write_bytes(b"a")
    (tmp_path / "b").write_bytes(b"b")
    with pytest.raises(FileExistsError):
        primitives.rename_excl(tmp_path / "a", tmp_path / "b")
    assert (tmp_path / "b").read_bytes() == b"b"
    primitives.rename_excl(tmp_path / "a", tmp_path / "c")
    assert (tmp_path / "c").read_bytes() == b"a"


def _no_exclusive_rename(monkeypatch, err: int):
    """A system call that answers -1 with ``err`` (as renameat2 on a file system without
    RENAME_NOREPLACE: EINVAL)."""
    monkeypatch.setattr(primitives, "_renamex_np", None)
    monkeypatch.setattr(primitives, "_renameat2", lambda *args: -1)
    monkeypatch.setattr(primitives.ctypes, "get_errno", lambda: err)


@pytest.mark.parametrize("err", [errno.EINVAL, errno.ENOSYS, errno.ENOTSUP])
def test_unsupported_exclusive_rename_falls_back(tmp_path, monkeypatch, err):
    _no_exclusive_rename(monkeypatch, err)
    (tmp_path / "a").write_bytes(b"a")
    (tmp_path / "b").write_bytes(b"b")
    with pytest.raises(FileExistsError):
        primitives.rename_excl(tmp_path / "a", tmp_path / "b")
    primitives.rename_excl(tmp_path / "a", tmp_path / "c")
    assert (tmp_path / "c").read_bytes() == b"a"


def test_exclusive_rename_errors_are_raised(tmp_path, monkeypatch):
    _no_exclusive_rename(monkeypatch, errno.EIO)
    (tmp_path / "a").write_bytes(b"a")
    with pytest.raises(OSError) as e:
        primitives.rename_excl(tmp_path / "a", tmp_path / "c")
    assert e.value.errno == errno.EIO
    assert (tmp_path / "a").exists() and not (tmp_path / "c").exists()


def test_exclusive_rename_reports_a_taken_name(tmp_path, monkeypatch):
    _no_exclusive_rename(monkeypatch, errno.EEXIST)
    (tmp_path / "a").write_bytes(b"a")
    with pytest.raises(FileExistsError):
        primitives.rename_excl(tmp_path / "a", tmp_path / "c")
