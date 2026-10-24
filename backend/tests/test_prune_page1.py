"""prune_page1_pictures: removes only stale files of dam's own page-1 cache folder."""

import ast
import logging
import threading

import pytest

from dam.extract.base import ExtractedText
from dam.extract.picture import PICTURE_DIR, picture_name, prune_page1_pictures
from test_no_delete import ALLOWED, _hits

SHA = "ab" * 32
OTHER = "cd" * 32


def _folder(cache):
    folder = cache / PICTURE_DIR
    folder.mkdir(parents=True)
    return folder


def _put(folder, name):
    p = folder / name
    p.write_bytes(b"jpg")
    return p


def test_removes_stale_keeps_current(tmp_path):
    folder = _folder(tmp_path)
    current = _put(folder, picture_name("id-a", SHA))
    changed = _put(folder, picture_name("id-b", OTHER))  # the file has other content now
    unknown = _put(folder, picture_name("id-gone", SHA))
    local = _put(folder, picture_name("local:1-2", SHA))  # sanitised id stays matched
    keys = [("id-a", SHA), ("id-b", SHA), ("local:1-2", SHA)]
    assert prune_page1_pictures(tmp_path, keys) == sorted([changed.name, unknown.name])
    assert current.exists() and local.exists()
    assert not changed.exists() and not unknown.exists()


def test_ignores_names_that_do_not_match_the_pattern(tmp_path):
    folder = _folder(tmp_path)
    keep = [
        _put(folder, "notes.txt"),
        _put(folder, "id-a-abab.jpg"),  # short prefix
        _put(folder, f"id-a-{'AB' * 8}.jpg"),  # upper case hex
        _put(folder, f"id a-{'ab' * 8}.jpg"),  # space
        _put(folder, f"id-a-{'ab' * 8}.png"),
        _put(folder, f".{'ab' * 8}.jpg"),
    ]
    sub = folder / f"id-x-{'ab' * 8}.jpg"
    sub.mkdir()  # a directory with a matching name
    (sub / "inner.jpg").write_bytes(b"x")
    assert prune_page1_pictures(tmp_path, []) == []
    assert all(p.exists() for p in keep) and (sub / "inner.jpg").exists()


def test_ignores_symlinks(tmp_path):
    folder = _folder(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("keep", encoding="utf-8")
    link = folder / picture_name("id-a", SHA)
    try:
        link.symlink_to(victim)
    except OSError:
        pytest.skip("symlinks need privileges here")
    assert prune_page1_pictures(tmp_path, []) == []
    assert link.is_symlink() and victim.read_text(encoding="utf-8") == "keep"


def test_never_touches_anything_outside_the_folder(tmp_path):
    folder = _folder(tmp_path)
    outside = [
        _put(tmp_path, picture_name("id-a", SHA)),  # in cache/, not cache/page1/
        _put(tmp_path.parent, picture_name("id-b", SHA)),
    ]
    nested = folder / "deeper"
    nested.mkdir()
    outside.append(_put(nested, picture_name("id-c", SHA)))
    assert prune_page1_pictures(tmp_path, []) == []
    assert all(p.exists() for p in outside)


def test_a_symlinked_folder_is_left_alone(tmp_path):
    real = tmp_path / "elsewhere"
    real.mkdir()
    stale = _put(real, picture_name("id-a", SHA))
    cache = tmp_path / "cache"
    cache.mkdir()
    try:
        (cache / PICTURE_DIR).symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks need privileges here")
    assert prune_page1_pictures(cache, []) == []
    assert stale.exists()


def test_missing_folder_is_fine(tmp_path):
    assert prune_page1_pictures(tmp_path / "nothing", []) == []


def test_the_allowance_is_that_one_function_only():
    assert [k for k in ALLOWED if "picture.py" in k[0]] == [
        ("extract/picture.py", "prune_page1_pictures", "Path.unlink")
    ]
    # the same call anywhere else is a hit that is not allowed
    hits = _hits(ast.parse("def other(p):\n    p.unlink()\n"))
    assert hits and ("extract/picture.py", hits[0][0], hits[0][1]) not in ALLOWED


def test_first_scan_prunes_the_cache(app, fake_archive, caplog):
    from dam.serve import _initial_scan

    fake_archive.add("##. Ongoing/a.pdf", drive_id="id-a")
    app.scan()
    sha = "ef" * 32
    app.repo.save_content("id-a", sha, ExtractedText("Lasku", "test", False), "indexed")
    folder = _folder(app.app_paths.cache_dir)
    keep = _put(folder, picture_name("id-a", sha))
    stale = _put(folder, picture_name("id-a", OTHER))
    with caplog.at_level(logging.INFO, logger="dam.serve"):
        _initial_scan(app, threading.Event())
    assert keep.exists() and not stale.exists()
