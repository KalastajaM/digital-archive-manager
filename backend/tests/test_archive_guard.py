"""The runtime guard in ``archive_guard``: archive writes from outside dam/ops fail."""

import os
import sys
from pathlib import Path

import pytest

import archive_guard


def run_as(module: str, source: str, **names) -> None:
    """Run ``source`` as if it were code in ``src/dam/<module>`` (the guard looks at the
    file name of each frame; no product file is changed)."""
    filename = os.path.join(archive_guard.SRC, *module.split("/"))
    exec(compile(source, filename, "exec"), {"__name__": "probe", **names})


@pytest.fixture
def caught():
    """The violations the guard recorded, cleared so the test's teardown passes."""
    yield archive_guard.state.violations
    archive_guard.state.violations.clear()


def expect_violation(caught, module: str, source: str, event: str, **names) -> None:
    with pytest.raises(AssertionError, match="archive write outside dam/ops") as info:
        run_as(module, source, **names)
    assert event in str(info.value)
    assert f"dam/{module}:" in str(info.value)
    assert caught


def test_open_for_writing_from_a_non_ops_module(fake_archive, caught):
    target = fake_archive.root / "new.txt"
    expect_violation(
        caught,
        "services/probe.py",
        "with open(p, 'w', encoding='utf-8') as f: f.write('x')",
        "open",
        p=target,
    )
    assert not target.exists()


def test_append_and_write_bytes_are_writes_too(fake_archive, caught):
    existing = fake_archive.add("a.pdf")
    expect_violation(caught, "services/probe.py", "open(p, 'ab').close()", "open", p=existing)
    expect_violation(caught, "services/probe.py", "p.write_bytes(b'y')", "open", p=existing)
    assert existing.read_bytes() == b"x"


def test_aliased_shutil_move(fake_archive, caught):
    src = fake_archive.add("a.pdf")
    expect_violation(
        caught,
        "api/probe.py",
        "import shutil as sh\nsh.move(a, b)",
        "shutil.move",
        a=src,
        b=src.with_name("b.pdf"),
    )
    assert src.exists()


def test_getattr_os_remove(fake_archive, caught):
    src = fake_archive.add("a.pdf")
    expect_violation(
        caught, "index/probe.py", "import os\ngetattr(os, 'remove')(p)", "os.remove", p=src
    )
    assert src.exists()


def test_subprocess_mv(fake_archive, caught):
    src = fake_archive.add("a.pdf")
    expect_violation(
        caught,
        "extract/probe.py",
        "import subprocess\nsubprocess.run(['mv', str(a), str(b)])",
        "subprocess.Popen",
        a=src,
        b=fake_archive.root / "b.pdf",
    )
    assert src.exists()  # refused before the process starts


def test_a_swallowed_violation_is_still_recorded(fake_archive, caught):
    run_as(
        "services/probe.py",
        "try:\n    (root / 'x').mkdir()\nexcept Exception:\n    pass",
        root=fake_archive.root,
    )
    assert any("os.mkdir" in v for v in caught)


def test_ops_writes_are_allowed(fake_archive, caught):
    src = fake_archive.add("a.pdf")
    run_as(
        "ops/probe.py",
        "import os, shutil\n"
        "(root / 'new.txt').write_text('x', encoding='utf-8')\n"
        "os.rename(src, root / 'b.pdf')\n"
        "shutil.copyfile(root / 'b.pdf', root / 'c.pdf')\n"
        "(root / 'Folder').mkdir()",
        root=fake_archive.root,
        src=src,
    )
    assert (fake_archive.root / "c.pdf").exists()
    assert not caught


def test_a_non_ops_helper_called_by_ops_is_allowed(fake_archive, caught):
    helper: dict = {}
    run_as(
        "services/probe.py",
        "def write(p):\n    p.write_bytes(b'y')\nout['write'] = write",
        out=helper,
    )
    run_as("ops/probe.py", "write(p)", write=helper["write"], p=fake_archive.root / "n")
    assert not caught


def test_reads_and_writes_elsewhere_are_not_flagged(fake_archive, tmp_path, caught):
    src = fake_archive.add("a.pdf")
    run_as(
        "services/probe.py",
        "import os, shutil\n"
        "src.read_bytes()\n"
        "os.listdir(root)\n"
        "os.stat(src)\n"
        "shutil.copyfile(src, outside / 'copy.pdf')\n"
        "(outside / 'cache.txt').write_text('x', encoding='utf-8')",
        root=fake_archive.root,
        src=src,
        outside=tmp_path,
    )
    assert (tmp_path / "copy.pdf").read_bytes() == b"x"
    assert not caught


@pytest.mark.skipif(sys.platform == "win32", reason="no cat on Windows")
def test_a_reading_command_is_not_flagged(fake_archive, caught):
    import subprocess

    src = fake_archive.add("a.pdf")
    run_as(
        "extract/probe.py",
        "out = subprocess.run(['cat', str(p)], capture_output=True).stdout",
        subprocess=subprocess,
        p=src,
    )
    assert not caught


def test_the_tests_themselves_may_build_archives(fake_archive, caught):
    (fake_archive.root / "Folder").mkdir()
    (fake_archive.root / "Folder" / "a.txt").write_text("x", encoding="utf-8")
    os.rename(fake_archive.root / "Folder", fake_archive.root / "Other")
    assert not caught


@pytest.mark.archive_write_allowed("dam/services/probe.py:<module>", reason="the marker")
def test_the_marker_allows_one_place(fake_archive, caught):
    run_as("services/probe.py", "(root / 'x').mkdir()", root=fake_archive.root)
    assert not caught
    with pytest.raises(AssertionError):
        run_as("api/probe.py", "(root / 'y').mkdir()", root=fake_archive.root)


def test_only_registered_roots_are_watched(tmp_path: Path, caught):
    plain = tmp_path / "archive-not-registered"
    plain.mkdir()
    run_as("services/probe.py", "(p / 'x').mkdir()", p=plain)
    assert not caught
