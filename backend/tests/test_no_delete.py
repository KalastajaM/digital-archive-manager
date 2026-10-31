import ast
from collections import Counter
from pathlib import Path

import pytest

from dam.ops.model import GuardError
from dam.ops.primitives import unlink_symlink

SRC = Path(__file__).parents[1] / "src" / "dam"
DELETE_NAMES = {"remove", "unlink", "rmdir", "rmtree", "removedirs", "send2trash"}
# Renames can overwrite (os.rename replaces an existing file), so all of them live in
# ops/primitives.py, which wraps them in exclusive / same-entry checks.
RENAME_NAMES = {"rename", "renames"}
# (file, enclosing function, call) -> the exact number of uses allowed there. A name
# used on ``os``/``shutil`` is reported as ``os.<name>``; on anything else (a Path) as
# ``Path.<name>``. Phase 2 Task 8 adds ``remove_empty_dir`` (an empty folder directly
# inside Ongoing, after deleting its ``.DS_Store`` files).
ALLOWED = Counter(
    {
        ("ops/primitives.py", "unlink_symlink", "Path.unlink"): 1,
        ("ops/primitives.py", "remove_empty_dir", "os.unlink"): 1,
        ("ops/primitives.py", "remove_empty_dir", "os.rmdir"): 1,
        # the same removal by path where dir_fd does not exist (Windows): empty folders only
        ("ops/primitives.py", "_remove_empty_dir_by_path", "os.rmdir"): 1,
        ("collections/export.py", "prune_exports", "shutil.rmtree"): 1,
        # dam's own page-1 picture cache (cache/page1), stale files only; never the archive
        ("extract/picture.py", "prune_page1_pictures", "Path.unlink"): 1,
        # dam's own automatic snapshot zips (<data dir>/snapshots, before-* kinds only, all
        # but the newest few; never manual, before-restore or imported ones, never the
        # archive); owner's request 2026-10-31
        ("snapshots.py", "prune_automatic", "Path.unlink"): 1,
        # dam's own rule picture crop (config/rules/areas, an app-made file, never an archive
        # file) after it was copied into To Delete across disks and the copy verified by
        # content hash; owner's statement 2026-10-24: the rule is for archive files
        ("ops/primitives.py", "remove_moved_picture", "Path.unlink"): 1,
        # Task 12: the reminder LaunchAgent plist, exact path only (outside the archive)
        ("reminders/launchd.py", "uninstall", "Path.unlink"): 1,
        ("ops/primitives.py", "rename_excl", "os.rename"): 1,
        ("ops/primitives.py", "rename_case_only", "os.rename"): 1,
    }
)


def _hits(tree: ast.AST) -> list[tuple[str, str, int]]:
    """Return (enclosing function, offending name, line) for every delete-like use."""
    hits: list[tuple[str, str, int]] = []

    def visit(node: ast.AST, func: str) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            func = node.name
        if isinstance(node, ast.Attribute):
            owner = node.value.id if isinstance(node.value, ast.Name) else None
            if node.attr in DELETE_NAMES | RENAME_NAMES:
                where = owner if owner in ("os", "shutil") else "Path"
                hits.append((func, f"{where}.{node.attr}", node.lineno))
            elif owner == "shutil" and node.attr == "move":
                hits.append((func, "shutil.move", node.lineno))
            elif owner == "os" and node.attr == "replace":
                hits.append((func, "os.replace", node.lineno))
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id in DELETE_NAMES | RENAME_NAMES | {
                "move",
                "replace",
            }:
                hits.append((func, f.id, node.lineno))
            # Path.replace(target) takes one argument; str.replace(old, new) takes two.
            if (
                isinstance(f, ast.Attribute)
                and f.attr == "replace"
                and len(node.args) + len(node.keywords) == 1
            ):
                hits.append((func, "Path.replace", node.lineno))
            if (
                isinstance(f, ast.Name)
                and f.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in DELETE_NAMES | RENAME_NAMES | {"move", "replace"}
            ):
                hits.append((func, f"getattr:{node.args[1].value}", node.lineno))
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if (
                    alias.name in DELETE_NAMES | RENAME_NAMES | {"move", "replace"}
                    or node.module == "send2trash"
                ):
                    hits.append((func, f"import {alias.name}", node.lineno))
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "send2trash":
                    hits.append((func, "import send2trash", node.lineno))
        for child in ast.iter_child_nodes(node):
            visit(child, func)

    visit(tree, "<module>")
    return hits


def test_no_delete_calls_in_source():
    sources = sorted(SRC.rglob("*.py"))
    assert sources, "no source files found"
    allowed_seen: Counter = Counter()
    violations = []
    for path in sources:
        rel = path.relative_to(SRC).as_posix()
        for func, name, line in _hits(
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        ):
            if (rel, func, name) in ALLOWED:
                allowed_seen[(rel, func, name)] += 1
            else:
                violations.append(f"{rel}:{line} {name} in {func}")
    assert violations == []
    # the scan really sees every permitted use, each exactly as often as allowed
    assert allowed_seen == ALLOWED


@pytest.mark.parametrize(
    "snippet",
    [
        "os.remove(p)",
        "os.unlink(p)",
        "p.unlink()",
        "p.rmdir()",
        "shutil.rmtree(p)",
        "shutil.move(a, b)",
        "os.replace(a, b)",
        "p.replace(q)",
        "send2trash(p)",
        "f = os.remove",
        "getattr(p, 'unlink')()",
        "from os import remove",
        "from shutil import move",
        "os.rename(a, b)",
        "p.rename(q)",
        "os.renames(a, b)",
        "from os import rename",
        "os.rmdir(p)",
        "os.removedirs(p)",
        "Path(p).rmdir()",
        "from os import rmdir",
    ],
)
def test_scanner_flags_delete_like_code(snippet):
    assert _hits(ast.parse(snippet))


@pytest.mark.parametrize(
    ("snippet", "name"),
    [
        ("os.rmdir(p)", "os.rmdir"),
        ("p.rmdir()", "Path.rmdir"),
        ("os.unlink(p)", "os.unlink"),
        ("p.unlink()", "Path.unlink"),
        ("os.removedirs(p)", "os.removedirs"),
        ("shutil.rmtree(p)", "shutil.rmtree"),
    ],
)
def test_scanner_names_the_owner(snippet, name):
    assert [h[1] for h in _hits(ast.parse(snippet))] == [name]


def test_scanner_ignores_str_replace():
    assert _hits(ast.parse("s.replace('a', 'b')")) == []


def test_unlink_symlink_refuses_regular_file(fake_archive):
    f = fake_archive.add("##. Ongoing/real.pdf")
    with pytest.raises(GuardError):
        unlink_symlink(f, fake_archive.root / "##. Ongoing")
    assert f.exists()


def test_unlink_symlink_refuses_outside_ongoing(fake_archive):
    fake_archive.add("10. Financial/Banks/a.pdf")
    link = fake_archive.link("10. Financial/link.pdf", "10. Financial/Banks/a.pdf")
    with pytest.raises(GuardError):
        unlink_symlink(link, fake_archive.root / "##. Ongoing")
    assert link.is_symlink()


def test_unlink_symlink_refuses_link_via_symlinked_parent(fake_archive):
    fake_archive.add("10. Financial/Banks/a.pdf")
    fake_archive.link("10. Financial/Banks/l.pdf", "10. Financial/Banks/a.pdf")
    # ##. Ongoing/banks -> 10. Financial/Banks; the real link lives outside Ongoing.
    fake_archive.link("##. Ongoing/banks", "10. Financial/Banks")
    via = fake_archive.root / "##. Ongoing/banks/l.pdf"
    with pytest.raises(GuardError):
        unlink_symlink(via, fake_archive.root / "##. Ongoing")
    assert (fake_archive.root / "10. Financial/Banks/l.pdf").is_symlink()


def test_unlink_symlink_removes_only_the_link(fake_archive):
    target = fake_archive.add("10. Financial/Banks/a.pdf")
    link = fake_archive.link("##. Ongoing/a.pdf", "10. Financial/Banks/a.pdf")
    unlink_symlink(link, fake_archive.root / "##. Ongoing")
    assert not link.is_symlink()
    assert target.exists()
