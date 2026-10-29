"""Layering guard: no module reaches into another dam module's private names."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "dam"


def _private(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def test_no_module_imports_a_private_name_from_another_dam_module():
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = node.module or ""
            if node.level == 0 and module != "dam" and not module.startswith("dam."):
                continue
            offenders += [
                f"{path.relative_to(SRC)}:{node.lineno} imports {a.name}"
                for a in node.names
                if _private(a.name)
            ]
    assert not offenders, "import a public name instead:\n" + "\n".join(offenders)


def test_lower_layers_do_not_import_the_rules_package():
    offenders = []
    for layer in ("db", "index", "core"):
        for path in sorted((SRC / layer).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    names = [node.module or ""] + [f"{node.module}.{a.name}" for a in node.names]
                elif isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                else:
                    continue
                if any(n == "dam.rules" or n.startswith("dam.rules.") for n in names):
                    offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert not offenders, "dam.db, dam.index and dam.core must not import dam.rules:\n" + "\n".join(
        offenders
    )


# The packages and modules above the engine: the interfaces, the services and the feature
# packages built on them. dam.core, dam.db, dam.index and dam.ops sit below all of them.
HIGHER = (
    "ai",
    "api",
    "app",
    "archive_folders",
    "cli",
    "collections",
    "demo",
    "layouts",
    "maintenance",
    "notes",
    "profiles",
    "query",
    "relabel",
    "reminders",
    "rules",
    "search",
    "serve",
    "services",
    "settings_write",
    "setup",
    "special_folders",
    "snapshots",
    "trays",
)


def _imported(node: ast.Import | ast.ImportFrom, path: Path) -> list[str]:
    """The dotted modules an import statement names (relative imports resolved)."""
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    module = node.module or ""
    if node.level:
        package = list(path.relative_to(SRC.parent).with_suffix("").parts)[: -node.level]
        module = ".".join(package + ([module] if module else []))
    return [module] + [f"{module}.{a.name}" for a in node.names]


def test_engine_layers_do_not_import_higher_layers():
    offenders = []
    for layer in ("core", "db", "index", "ops"):
        for path in sorted((SRC / layer).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):  # function-local imports too
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                hits = {
                    name
                    for name in _imported(node, path)
                    for high in HIGHER
                    if name == f"dam.{high}" or name.startswith(f"dam.{high}.")
                }
                offenders += [f"{path.relative_to(SRC)}:{node.lineno} imports {h}" for h in hits]
    assert not offenders, (
        "dam.core, dam.db, dam.index and dam.ops must not import higher layers:\n"
        + "\n".join(sorted(offenders))
    )
