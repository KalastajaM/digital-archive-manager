"""The filing code table: short codes that route a document (tray, folder, tags...)."""

import re
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from dam.codes.configfile import write_config_file
from dam.collections.service import check_collection_name
from dam.core.foldernames import FolderNameError, check_folder_name
from dam.core.text import fold
from dam.rules.engine import TemplateError, check_template
from dam.rules.model import read_yaml
from dam.services.errors import InvalidRequest

_CODE_RE = re.compile(r"^[A-Za-z0-9]{1,4}$")
LABEL_MAX = 24  # fits a sticker and a chip

CONFUSABLE_GROUPS = ("0OØDQ", "1IL7", "5S", "2Z", "8B", "UV", "6G")
_GROUP_OF = {c: i for i, group in enumerate(CONFUSABLE_GROUPS) for c in group}


class FilingCode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    label: str = Field(default="", max_length=LABEL_MAX)
    tray: str | None = None
    folder: str | None = None
    name: str | None = None
    tags: list[str] = Field(default_factory=list)
    collections: list[str] = Field(default_factory=list)
    as_suggested: bool = False
    inbox_folder: str | None = None

    @field_validator("code")
    @classmethod
    def _check_code(cls, v: str) -> str:
        if not _CODE_RE.match(v):
            raise ValueError("a code is 1 to 4 letters or digits")
        return v.upper()

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, v: list[str]) -> list[str]:
        # imported here: dam.services.inbox imports this module (through codes.apply)
        from dam.services.inbox import normalise_tags

        return normalise_tags(v)

    @field_validator("collections")
    @classmethod
    def _check_collections(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for name in v:
            try:
                name = check_collection_name(name)
            except InvalidRequest as e:
                raise ValueError(str(e)) from e
            if name not in out:
                out.append(name)
        return out

    @field_validator("folder", "name")
    @classmethod
    def _check_template(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                check_template(v)
            except TemplateError as e:
                raise ValueError(str(e)) from e
        return v

    @field_validator("inbox_folder")
    @classmethod
    def _check_inbox(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                return check_folder_name(v)  # stored cleaned (NFC, trimmed)
            except FolderNameError as e:
                raise ValueError(str(e)) from e
        return v


@dataclass
class CodeProblem:
    code: str
    message: str


def format_validation(e: ValidationError) -> str:
    parts = []
    for err in e.errors():
        where = ".".join(str(p) for p in err["loc"]) or "code"
        parts.append(f"{where}: {err['msg'].removeprefix('Value error, ')}")
    return "; ".join(parts)


def table_problem(
    fc: FilingCode, tray_ids: Collection[str], seen_codes: set[str], seen_inbox: set[str]
) -> str | None:
    """Why ``fc`` cannot join the table (repeated code, unknown tray, repeated inbox
    folder), else None and it is recorded in ``seen_codes``/``seen_inbox``. The one
    check behind both loading the file and saving a new table."""
    if fc.code in seen_codes:
        return f"the code {fc.code} is used twice"
    if fc.tray is not None and fc.tray not in tray_ids:
        return f"unknown tray {fc.tray!r}"
    if fc.inbox_folder is not None:
        key = fold(fc.inbox_folder)
        if key in seen_inbox:
            return f"inbox folder {fc.inbox_folder!r} is used twice"
        seen_inbox.add(key)
    seen_codes.add(fc.code)
    return None


def check_table(codes: list[FilingCode], tray_ids: Collection[str]) -> list[CodeProblem]:
    """The problems of a whole table (as ``load_codes`` would report them)."""
    seen_codes: set[str] = set()
    seen_inbox: set[str] = set()
    out = []
    for fc in codes:
        message = table_problem(fc, tray_ids, seen_codes, seen_inbox)
        if message:
            out.append(CodeProblem(fc.code, message))
    return out


def load_codes(path: Path, tray_ids: Collection[str]) -> tuple[list[FilingCode], list[CodeProblem]]:
    """Read the code table. Invalid, repeated or tray-less entries are reported and left out."""
    if not path.exists():
        return [], []
    try:
        _, data = read_yaml(path)
    except ValueError as e:
        return [], [CodeProblem("", str(e))]
    if data is None:
        return [], []
    if not isinstance(data, list):
        return [], [CodeProblem("", "the file must be a list of codes")]
    codes: list[FilingCode] = []
    problems: list[CodeProblem] = []
    seen_codes: set[str] = set()
    seen_inbox: set[str] = set()
    for i, item in enumerate(data, start=1):
        label = str(item.get("code", "")) if isinstance(item, dict) else ""
        label = label or f"#{i}"
        try:
            if not isinstance(item, dict):
                raise ValueError("each entry must be a mapping")
            fc = FilingCode.model_validate(item)
        except ValidationError as e:
            problems.append(CodeProblem(label, format_validation(e)))
            continue
        except ValueError as e:
            problems.append(CodeProblem(label, str(e)))
            continue
        message = table_problem(fc, tray_ids, seen_codes, seen_inbox)
        if message:
            problems.append(CodeProblem(fc.code, message))
            continue
        codes.append(fc)
    return codes, problems


def save_codes(path: Path, codes: list[FilingCode]) -> None:
    """Write the table. The file it replaces is kept as ``.bak-<time>``; the new file is
    read back and the original restored if it does not match (no file before: an empty
    table)."""
    dumped = [c.model_dump(exclude_defaults=True, mode="json") for c in codes]
    for d, c in zip(dumped, codes, strict=True):
        d["code"] = c.code
    text = yaml.safe_dump(dumped, allow_unicode=True, sort_keys=False)
    trays = {c.tray for c in codes if c.tray is not None}

    def verify() -> bool:
        back, problems = load_codes(path, trays)
        return not problems and back == codes

    write_config_file(path, text, verify)


def confusable_with(code: str, others: Collection[str]) -> list[str]:
    """Existing codes one confusable substitution away from ``code``."""
    mine = code.upper()
    found: list[str] = []
    for other in others:
        theirs = other.upper()
        if len(theirs) != len(mine):
            continue
        diff = [(a, b) for a, b in zip(mine, theirs, strict=True) if a != b]
        if len(diff) == 1:
            a, b = diff[0]
            if a in _GROUP_OF and _GROUP_OF.get(b) == _GROUP_OF[a]:
                found.append(other)
    return found
