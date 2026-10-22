"""Find text-mode file I/O that relies on the platform's default encoding (cp1252 on
Windows): ``read_text`` / ``write_text`` / text ``open`` / ``fdopen`` / ``text=True``
subprocess calls without an explicit ``encoding``."""

from __future__ import annotations

import ast
from pathlib import Path


def _has_kw(call: ast.Call, name: str) -> bool:
    return any(k.arg == name for k in call.keywords)


def _mode(call: ast.Call, pos: int) -> str | None:
    if len(call.args) > pos and isinstance(call.args[pos], ast.Constant):
        return str(call.args[pos].value)
    for k in call.keywords:
        if k.arg == "mode" and isinstance(k.value, ast.Constant):
            return str(k.value.value)
    return "r" if len(call.args) <= pos and not _has_kw(call, "mode") else None


def offenders(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _has_kw(node, "encoding"):
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        owner = f.value.id if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) else ""
        bad = False
        if name in ("read_text", "write_text"):
            bad = True
        elif name == "open" and owner in ("", "io", "codecs") and isinstance(f, ast.Name):
            bad = "b" not in (_mode(node, 1) or "b")
        elif (
            name == "open"
            and isinstance(f, ast.Attribute)
            and owner
            not in (
                "os",
                "Image",
                "zf",
                "webbrowser",
                "self",
                "app",
                "Image",
            )
        ):
            bad = "b" not in (_mode(node, 0) or "b") and not isinstance(f.value, ast.Call)
        elif name == "fdopen":
            bad = "b" not in (_mode(node, 1) or "b")
        elif name in ("run", "Popen", "check_output") and owner == "subprocess":
            bad = any(
                k.arg in ("text", "universal_newlines")
                and isinstance(k.value, ast.Constant)
                and k.value.value
                for k in node.keywords
            )
        if bad:
            found.append(node)
    return found


def main() -> None:
    import sys

    fix = "--fix" in sys.argv
    for root in ("src", "tests"):
        for p in sorted(Path(root).rglob("*.py")):
            calls = offenders(p)
            if not calls:
                continue
            if not fix:
                for c in calls:
                    print(f"{p}:{c.lineno}")
                continue
            lines = p.read_text(encoding="utf-8").split("\n")
            for c in sorted(calls, key=lambda c: (c.end_lineno, c.end_col_offset), reverse=True):
                ln = lines[c.end_lineno - 1]
                col = len(ln.encode()[: c.end_col_offset].decode())  # byte -> char offset
                inner = ln[: col - 1]
                has_args = bool(c.args or c.keywords)
                sep = ", " if has_args else ""
                if has_args and inner.rstrip().endswith(","):
                    sep = " "
                lines[c.end_lineno - 1] = inner + f'{sep}encoding="utf-8"' + ln[col - 1 :]
            p.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
