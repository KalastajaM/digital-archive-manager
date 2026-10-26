"""The verified copy used to move a file between archive folders on different disks."""

import os
from pathlib import Path

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
