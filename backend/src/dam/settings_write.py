"""Write top-level keys of the archive's ``settings.yaml`` and keep everything else (the
comments, the other keys) as it is."""

import json
import re
from collections.abc import Callable
from pathlib import Path

import yaml

from dam.codes.configfile import write_config_file
from dam.config import AppPaths, Settings, load_settings

_TOP_LEVEL = re.compile(r"^(?P<key>[A-Za-z_][\w-]*)[ \t]*:")


def _flow(value: object) -> str:
    """A scalar or a list of scalars on one line (JSON is valid YAML flow)."""
    return json.dumps(value, ensure_ascii=False)


def _lines_for(key: str, value: object) -> list[str]:
    """``key: value`` as YAML lines: scalars and lists of scalars on the key's line, a
    list of mappings (whose values are scalars or lists of scalars) as a block."""
    if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
        lines = [f"{key}:"]
        for item in value:
            for n, (name, inner) in enumerate(item.items()):
                lines.append(f"{'  - ' if n == 0 else '    '}{name}: {_flow(inner)}")
        return lines
    return [f"{key}: {_flow(value)}"]


def with_keys(text: str, updates: dict[str, object]) -> str:
    """``text`` (a settings file, ``\\n`` newlines) with each top-level key of ``updates``
    set to its value. A key that is there is replaced in place (its block of indented
    lines, or unindented list items, goes); a new one is added at the end. Comments and the
    other keys stay."""
    lines = text.split("\n")
    for key, value in updates.items():
        new = _lines_for(key, value)
        start = next(
            (
                i
                for i, line in enumerate(lines)
                if (m := _TOP_LEVEL.match(line)) and m.group("key") == key
            ),
            None,
        )
        if start is None:
            while lines and not lines[-1].strip():
                lines.pop()
            lines.extend(new)
            lines.append("")
            continue
        end = start + 1
        while end < len(lines) and (
            not lines[end].strip()
            or lines[end][:1] in " \t"
            or lines[end].startswith("-")
            or lines[end].startswith("#")
        ):
            end += 1
        # blank lines and comments after the value belong to what follows
        while end > start + 1 and (not lines[end - 1].strip() or lines[end - 1].startswith("#")):
            end -= 1
        lines[start:end] = new
    return "\n".join(lines)


def write_keys(
    app_paths: AppPaths, updates: dict[str, object], verify: Callable[[Settings], bool]
) -> Path:
    """Set top-level keys in ``<data dir>/config/settings.yaml``. The file it replaces is
    kept as ``.bak-<time>``; the new one is read back through ``load_settings`` and
    ``verify`` must accept it, else the old content is restored and ``OSError`` is raised
    (as well as for a failed write)."""
    app_paths.ensure()
    path = app_paths.config_dir / "settings.yaml"
    original = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    text = with_keys(original, updates)

    def check() -> bool:
        try:
            return verify(load_settings(app_paths))
        except (ValueError, yaml.YAMLError, OSError):
            return False

    write_config_file(path, text, check)
    return path
