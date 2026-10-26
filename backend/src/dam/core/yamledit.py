"""Change single values in a YAML file the owner wrote, character for character.

The file is composed (``yaml.compose``), which gives every scalar its exact start and
end in the text. Only those characters are replaced, so comments, order, quoting and
layout stay as they were. A value that cannot be replaced that way (folded or literal
block, a plain scalar spread over lines, an alias shared by two places) is refused
with its line, so the owner edits it by hand.
"""

import json
from collections import Counter
from collections.abc import Callable, Iterator

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

Path = tuple[str | int, ...]
# what a plain (unquoted) value may not start with: YAML indicators
_INDICATORS = tuple("-?:,[]{}#&*!|>'\"%@`")


class YamlEditError(ValueError):
    """A value the edit cannot change safely; the message starts with ``line N:``."""


def _walk(node: Node, path: Path) -> Iterator[tuple[Path, Node]]:
    yield path, node
    if isinstance(node, MappingNode):
        for key, value in node.value:
            name = key.value if isinstance(key, ScalarNode) else str(key.value)
            yield from _walk(value, (*path, name))
    elif isinstance(node, SequenceNode):
        for i, item in enumerate(node.value):
            yield from _walk(item, (*path, i))


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)  # a valid double-quoted YAML scalar


def _written(value: str, style: str | None) -> str:
    """``value`` as YAML text in the quoting ``style`` it replaces. A plain value stays
    plain when it can (checked again on the whole file by ``replace_values``)."""
    if style == "'":
        return "'" + value.replace("'", "''") + "'"
    plain = (
        style is None
        and value
        and value == value.strip()
        and not value.startswith(_INDICATORS)
        and ": " not in value
        and " #" not in value
        and "\n" not in value
    )
    return value if plain else _quoted(value)


def _render(text: str, edits: list[tuple[int, int, str, int]]) -> str:
    for start, end, value, _ in sorted(edits, reverse=True):
        text = text[:start] + value + text[end:]
    return text


def _value_at(root: Node | None, path: Path) -> object:
    for p, node in _walk(root, ()) if root is not None else ():
        if p == path:
            return node.value if isinstance(node, ScalarNode) else None
    return None


def replace_values(
    text: str, change: Callable[[Path, str], str | None]
) -> tuple[str, list[int]]:
    """``text`` with each string scalar that ``change(path, value)`` answers with a new
    value replaced in place; ``path`` holds the mapping keys and list indices down to the
    value. Returns the new text and the (1-based) lines changed. ``YamlEditError`` when
    a value to change is folded, literal, spread over lines or an alias."""
    root = yaml.compose(text)
    if root is None:
        return text, []
    nodes = list(_walk(root, ()))
    uses = Counter(id(node) for _, node in nodes)
    edits: list[tuple[int, int, str, int]] = []
    wanted: list[tuple[Path, str]] = []
    for path, node in nodes:
        if not isinstance(node, ScalarNode) or node.tag != "tag:yaml.org,2002:str":
            continue
        new = change(path, node.value)
        if new is None or new == node.value:
            continue
        line = node.start_mark.line + 1
        if uses[id(node)] > 1:
            raise YamlEditError(f"line {line}: the value is an alias used in two places")
        if node.style not in (None, "'", '"') or node.end_mark.line != node.start_mark.line:
            raise YamlEditError(f"line {line}: the value is written over several lines")
        if any(e[0] == node.start_mark.index for e in edits):
            continue
        edits.append((node.start_mark.index, node.end_mark.index, _written(new, node.style), line))
        wanted.append((path, new))
    result = _render(text, edits)
    # a plain value that reads back as something else (in a flow mapping a "," or "}"
    # ends it, for example) is written quoted instead
    try:
        check = yaml.compose(result)
    except yaml.YAMLError:
        check = None
    for i, (path, new) in enumerate(wanted):
        if check is None or _value_at(check, path) != new:
            start, end, _, line = edits[i]
            edits[i] = (start, end, _quoted(new), line)
    if check is None or any(_value_at(check, p) != v for p, v in wanted):
        result = _render(text, edits)
    return result, sorted({line for *_, line in edits})
