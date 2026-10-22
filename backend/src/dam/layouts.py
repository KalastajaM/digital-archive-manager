"""Starter layouts for a new archive: the top-level folders, the special folders, and
example rules that point at them.

A layout is a data file (``defaults/layouts/*.yaml``; add your own next to the shipped
ones). Nothing here touches the disk except to read: creating the folders goes through
``dam.services.layout`` and the journaled operation layer, and writing the rules and
settings through ``write_layout_rules`` / ``dam.setup.write_layout_settings``.
"""

import logging
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dam.config import DEFAULTS_DIR, AppPaths, SpecialFolders
from dam.core.foldernames import FolderNameError, check_folder_name
from dam.core.paths import nfc
from dam.rules.model import MAX_CONFIG_BYTES

log = logging.getLogger(__name__)

FIRST_NUMBER = 10  # "10. Finance", "11. Bills & Receipts", ...
MAX_FOLDERS = 100
RULES_FILE = "00-examples.yaml"  # the rules file the app seeds (and a layout may replace)
SPECIAL_ROLES = ("inbox", "ongoing", "important", "quarantine")
_KEY_REF = re.compile(r"<([a-z][a-z0-9_]*)>")


class LayoutError(ValueError):
    """A layout (or the names in it) cannot be used; the message is shown to the user."""


class _FolderFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=255)


class _LayoutFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    title: str = Field(min_length=1)
    description: str = ""
    order: int = 100
    folders: list[_FolderFile] = Field(default_factory=list, max_length=MAX_FOLDERS)
    rules: list[dict] = Field(default_factory=list)
    ai_exclude: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class Row:
    """One editable top-level folder: ``key`` ties it to a template's rules (None for a
    row the user added)."""

    key: str | None
    name: str


@dataclass(frozen=True)
class Template:
    id: str
    title: str
    description: str
    order: int
    folders: tuple[Row, ...]
    rules: tuple[dict, ...] = ()
    ai_exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class Spec:
    """What the user chose: the rows (as edited), the numbering and the special names."""

    template_id: str | None
    rows: tuple[Row, ...]
    numbered: bool
    special: SpecialFolders = field(default_factory=SpecialFolders)


@dataclass(frozen=True)
class Folder:
    """A folder the layout wants: ``role`` is a special role or "layout"."""

    path: str
    role: str
    key: str | None
    title: str  # the plain name without its number


def load_templates(defaults_dir: Path = DEFAULTS_DIR) -> list[Template]:
    """The layouts in ``<defaults>/layouts`` ordered by ``order`` then id. A file that
    cannot be read or is invalid is logged and skipped."""
    out: list[Template] = []
    folder = defaults_dir / "layouts"
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.yaml")):
        try:
            if path.stat().st_size > MAX_CONFIG_BYTES:
                raise ValueError("file too large")
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            parsed = _LayoutFile.model_validate(raw)
        except (OSError, ValueError, yaml.YAMLError, ValidationError) as e:
            log.warning("layout file %s skipped: %s", path, str(e).splitlines()[0] if str(e) else e)
            continue
        out.append(
            Template(
                parsed.id,
                parsed.title,
                parsed.description,
                parsed.order,
                tuple(Row(f.key, f.name) for f in parsed.folders),
                tuple(parsed.rules),
                tuple(parsed.ai_exclude),
            )
        )
    return sorted(out, key=lambda t: (t.order, t.id))


def find_template(template_id: str | None, templates: Iterable[Template]) -> Template | None:
    return next((t for t in templates if t.id == template_id), None)


def numbered_name(index: int, name: str) -> str:
    return f"{FIRST_NUMBER + index}. {name}"


def special_names(special: SpecialFolders) -> tuple[str, ...]:
    return tuple(getattr(special, role) for role in SPECIAL_ROLES)


def build_folders(spec: Spec) -> list[Folder]:
    """Every folder the layout wants, in order: the special folders first, then the rows
    (numbered when asked). Every name is checked; a duplicate (case-insensitive) or a
    bad name is a ``LayoutError`` that names the offender."""
    if len(spec.rows) > MAX_FOLDERS:
        raise LayoutError(f"A layout can have at most {MAX_FOLDERS} folders.")
    names = special_names(spec.special)
    out: list[Folder] = []
    for role in SPECIAL_ROLES:
        name = getattr(spec.special, role)
        out.append(Folder(_checked(name, names), role, None, name))
    plain: list[tuple[Row, str]] = []
    for row in spec.rows:
        title = _checked(row.name, names)
        if title.startswith("##."):
            raise LayoutError(f"{title!r}: names starting with ## are for the special folders.")
        plain.append((row, title))
    for i, (row, title) in enumerate(plain):
        out.append(
            Folder(numbered_name(i, title) if spec.numbered else title, "layout", row.key, title)
        )
    seen: dict[str, str] = {}
    for f in out:
        folded = nfc(f.path).casefold()
        if folded in seen:
            raise LayoutError(f"Two folders would be called {f.path!r}. Give each its own name.")
        seen[folded] = f.path
    return out


def _checked(name: str, special: tuple[str, ...]) -> str:
    try:
        return check_folder_name(name, special)
    except FolderNameError as e:
        raise LayoutError(f"{name!r}: {e}") from None


def existing_names(root: Path | None) -> set[str]:
    """Folded names of the entries directly in ``root`` (empty when it does not exist)."""
    if root is None:
        return set()
    try:
        return {nfc(n).casefold() for n in os.listdir(root)}
    except OSError:
        return set()


# -- rules ----------------------------------------------------------------------------


def _resolve_refs(value, names: dict[str, str]):
    """``value`` with every ``<key>`` replaced by that folder's final name; None when a
    key has no folder (the user removed it)."""
    if isinstance(value, str):
        missing = False

        def sub(m: re.Match) -> str:
            nonlocal missing
            if m[1] in names:
                return names[m[1]]
            missing = True
            return m[0]

        text = _KEY_REF.sub(sub, value)
        return None if missing else text
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            r = _resolve_refs(v, names)
            if r is None:
                return None
            out[k] = r
        return out
    if isinstance(value, list):
        items = [_resolve_refs(v, names) for v in value]
        return None if any(i is None for i in items) else items
    return value


def layout_rules(template: Template | None, folders: list[Folder]) -> list[dict]:
    """The template's example rules aimed at the final folder names; a rule that points
    at a folder the user removed is left out."""
    if template is None:
        return []
    names = {f.key: f.path for f in folders if f.key}
    names["inbox"] = next(f.path for f in folders if f.role == "inbox")
    rules = []
    for rule in template.rules:
        resolved = _resolve_refs(rule, names)
        if resolved is not None:
            rules.append(resolved)
    return rules


def ai_exclude_folders(template: Template | None, folders: list[Folder]) -> list[str]:
    if template is None:
        return []
    by_key = {f.key: f.path for f in folders if f.key}
    return [by_key[k] for k in template.ai_exclude if k in by_key]


_RULES_HEADER = """\
# EXAMPLE RULES for the folders of your new archive. Edit, copy or delete them.
#
# Rules file: a YAML list of rules. Files in this folder load in name order;
# for folder and name the first matching rule wins, tags from all matches are merged.
#
# when: all given conditions must match (each is optional)
#   text_contains:    any of these words in the document text (case/diacritics-insensitive)
#   filename_matches: regex searched in the file name (add (?i) yourself if wanted)
#   folder_is:        folder the file currently sits in
# then:
#   folder / name:    templates using {doc_date:%Y%m%d}, {year} and {stem}
#                     (name is the stem only; the extension is added automatically)
#   tags:             tags to suggest
#
# The Finland bank examples at the end are optional: remove the # to use them.

"""


def _finland_examples(defaults_dir: Path) -> str:
    """The shipped example rules (Finland), commented out, from the first rule on."""
    try:
        lines = (defaults_dir / "rules" / RULES_FILE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    start = next((i for i, line in enumerate(lines) if line.startswith("- id:")), None)
    if start is None:
        return ""
    while start > 0 and lines[start - 1].startswith("#"):
        start -= 1  # the comment lines that belong to the first rule
    body = [line if line.startswith("#") else f"# {line}".rstrip() for line in lines[start:]]
    return (
        "\n# --- Optional: Finland examples (they point at folders of the older "
        "numbered layout; change the folder names to yours) ---\n" + "\n".join(body) + "\n"
    )


def rules_text(rules: list[dict], defaults_dir: Path = DEFAULTS_DIR) -> str:
    body = (
        yaml.safe_dump(rules, sort_keys=False, allow_unicode=True, width=100) if rules else "[]\n"
    )
    return _RULES_HEADER + body + _finland_examples(defaults_dir)


def seedable(app_paths: AppPaths, defaults_dir: Path = DEFAULTS_DIR) -> bool:
    """True when the rules folder holds no rules of the user's: nothing, or only the
    shipped ``00-examples.yaml`` exactly as shipped. Anything else is left alone."""
    rules_dir = app_paths.config_dir / "rules"
    try:
        files = [p for p in rules_dir.iterdir() if p.suffix.lower() in (".yaml", ".yml")]
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if not files:
        return True
    if [p.name for p in files] != [RULES_FILE]:
        return False
    try:
        shipped = (defaults_dir / "rules" / RULES_FILE).read_bytes()
        return files[0].read_bytes() == shipped
    except OSError:
        return False


def write_layout_rules(
    app_paths: AppPaths, rules: list[dict], defaults_dir: Path = DEFAULTS_DIR
) -> bool:
    """Replace the never-edited example rules with ones for the new layout. Only when
    ``seedable`` (the user has no rules of their own); returns whether it wrote."""
    if not seedable(app_paths, defaults_dir):
        return False
    target = app_paths.config_dir / "rules" / RULES_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    text = rules_text(rules, defaults_dir)
    with open(target, "w", encoding="utf-8", newline="\n") as f:  # in place: no rename
        f.write(text)
    return True
