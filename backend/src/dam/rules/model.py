"""Rule schema and loading from YAML files.

A rules file is a YAML *list of rules*::

    - id: apteekki-receipts
      when: {text_contains: ["apteekki"], filename_matches: "(?i)apteek", folder_is: "##. Organize"}
      then: {folder: "11. Bills & Receipts/{doc_date:%Y}", name: "{doc_date:%Y%m%d}_Apteekki",
             tags: ["receipt"]}
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import regex
import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationError,
    field_validator,
    model_validator,
)

from dam.core.text import fold
from dam.rules.picture import DEFAULT_MIN_SCORE, check_image_path

COLLECTION_NAME_MAX = 120  # as the collections' own limit (``dam.collections.service``)


MatchMode = Literal["word_start", "whole_word", "anywhere"]


@dataclass(frozen=True)
class TermTest:
    """A test for a folded ``term`` against folded text, by ``mode``; call it with the
    text. A word boundary is the start or end of the text or any character that is not a
    letter or a digit (Unicode-aware; hyphen, slash, dot and space are boundaries, digits
    are not). ``anywhere``: the term is somewhere in the text. ``word_start``: it begins
    at a boundary and may continue (Finnish endings: kela, Kelan; vakuutus,
    vakuutuskirja; not Henkivakuutus). ``whole_word``: it is bounded on both sides. A
    boundary is only required at an end of the term that is a letter or digit itself.
    (A dataclass, not a closure, so that two equal rules compare equal.)"""

    term: str
    mode: MatchMode
    _pattern: "re.Pattern[str] | None" = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.mode != "anywhere":
            before = r"(?<![^\W_])" if self.term[:1].isalnum() else ""
            after = r"(?![^\W_])" if self.mode == "whole_word" and self.term[-1:].isalnum() else ""
            object.__setattr__(self, "_pattern", re.compile(before + re.escape(self.term) + after))

    def __call__(self, text: str) -> bool:
        if self._pattern is None:
            return self.term in text
        return self._pattern.search(text) is not None


class Zone(BaseModel):
    """An area of page 1 that must hold something: ``box`` is ``(x0, y0, x1, y1)`` as
    fractions of the page, origin top left. Exactly one of ``text_contains`` (words: a line
    of page 1 in the box has one of them; a line lies in the box when at least half of it is
    inside the box grown by a small margin, ``dam.extract.layout.ZONE_MARGIN``, 2 % across and
    0.6 % down; the lines listed for a drawn box use no margin) or ``image``
    (a picture area: ``areas/<name>.png``, a grayscale crop of the area kept in the rules'
    ``areas`` folder, ``dam.rules.picture``; it matches when its best score on page 1 is at
    least ``min_score``, ``DEFAULT_MIN_SCORE`` when that is not given)."""

    model_config = ConfigDict(extra="forbid")

    box: tuple[float, float, float, float]
    text_contains: list[str] | None = None
    image: str | None = None
    min_score: float | None = None
    # How the words match the text of a line: "word_start" (the word begins a word, any
    # ending: Kela, Kelan; not Henkivakuutus for vakuutus), "whole_word" or "anywhere".
    # The default for a key that is ABSENT is "anywhere" on purpose: rule files written
    # before this key existed matched anywhere in the line and must keep doing so. The
    # app's draft and the rule sheet set "word_start" explicitly for new areas. YAML
    # leaves out "anywhere", so word_start and whole_word are what gets written.
    match: MatchMode = "anywhere"

    @field_validator("match", mode="before")
    @classmethod
    def _null_match_is_the_default(cls, value):
        return "anywhere" if value is None else value

    @field_validator("box")
    @classmethod
    def _a_real_box(cls, box: tuple[float, float, float, float]):
        x0, y0, x1, y1 = box
        if not all(0 <= v <= 1 for v in box):
            raise ValueError("box values must be between 0 and 1")
        if not (x0 < x1 and y0 < y1):
            raise ValueError("box must have x0 < x1 and y0 < y1")
        return box

    @model_validator(mode="after")
    def _words_or_picture(self) -> "Zone":
        if self.image is not None:
            if self.text_contains is not None:
                raise ValueError("an area has words (text_contains) or a picture (image), not both")
            check_image_path(self.image)
            if self.match != "anywhere":
                raise ValueError("match is for an area with words (text_contains)")
            if self.min_score is not None and not 0 < self.min_score <= 1:
                raise ValueError("min_score must be above 0 and at most 1")
            return self
        if self.min_score is not None:
            raise ValueError("min_score is for a picture area (image)")
        if not self.text_contains:
            raise ValueError("an area needs at least one word in text_contains")
        if any(not t.strip() for t in self.text_contains):
            raise ValueError("text_contains entries must not be blank")
        return self

    @property
    def is_picture(self) -> bool:
        return self.image is not None

    @property
    def threshold(self) -> float:
        """The score a picture area needs."""
        return self.min_score if self.min_score is not None else DEFAULT_MIN_SCORE


class When(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text_contains: list[str] = Field(default_factory=list)
    filename_matches: str | None = None
    folder_is: str | None = None
    # areas of page 1: every one must match (within an area, any one of its words)
    zones: list[Zone] = Field(default_factory=list)
    # the document is for this person (the owner's assignment, else the one found in the
    # address area of page 1), compared like rule words
    person: str | None = None

    @field_validator("text_contains")
    @classmethod
    def _no_blank_terms(cls, terms: list[str]) -> list[str]:
        if any(not t.strip() for t in terms):
            raise ValueError("text_contains entries must not be blank")
        return terms

    @field_validator("person")
    @classmethod
    def _no_blank_person(cls, person: str | None) -> str | None:
        if person is not None and not person.strip():
            raise ValueError("person must not be blank")
        return person

    @field_validator("filename_matches")
    @classmethod
    def _valid_regex(cls, pattern: str | None) -> str | None:
        if pattern is not None:
            try:
                regex.compile(pattern)
            except regex.error as e:
                raise ValueError(f"invalid regex: {e}") from e
        return pattern


class Then(BaseModel):
    model_config = ConfigDict(extra="forbid")

    folder: str | None = None
    name: str | None = None
    tags: list[str] = Field(default_factory=list)
    # the tray the document is guessed to belong in (a tray id; beats the To pay
    # heuristic) and the payee for the To pay tray's ``payee`` prefill
    tray: str | None = None
    payee: str | None = None
    # collections the Inbox form is prefilled to "Also add to collection" with (like
    # ``tags``); a name that does not exist yet is created when the document is filed
    collections: list[str] = Field(default_factory=list)

    @field_validator("collections")
    @classmethod
    def _clean_collections(cls, names: list[str]) -> list[str]:
        out: dict[str, str] = {}
        for raw in names:
            name = raw.strip()
            if not name:
                raise ValueError("collections entries must not be blank")
            if len(name) > COLLECTION_NAME_MAX:
                raise ValueError(f"a collection name is at most {COLLECTION_NAME_MAX} characters")
            out.setdefault(name.casefold(), name)
        return list(out.values())

    @field_validator("folder", "name", "tray", "payee")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    when: When = Field(default_factory=When)
    then: Then = Field(default_factory=Then)
    # when this rule matched, people are looked for in this area of page 1 instead of in
    # the archive's address zone (x0, y0, x1, y1), for this rule's folder and name only
    person_zone: tuple[float, float, float, float] | None = None
    # the sender (a name from the owner's list of senders) this rule identifies: the
    # replay compares the documents the owner marked as from it with what the rule matches
    sender: str | None = None

    _folded_terms: list[str] = PrivateAttr(default_factory=list)
    # the folded words of each zone, in order ([] for a zone without words)
    _folded_zones: list[list[str]] = PrivateAttr(default_factory=list)
    # one test per word of each zone, by the zone's match mode (same order as the words)
    _zone_tests: list[list[TermTest]] = PrivateAttr(default_factory=list)
    _regex: "regex.Pattern[str] | None" = PrivateAttr(default=None)

    @field_validator("sender")
    @classmethod
    def _no_blank_sender(cls, sender: str | None) -> str | None:
        if sender is not None and not sender.strip():
            raise ValueError("sender must not be blank")
        return sender.strip() if sender is not None else None

    @field_validator("person_zone")
    @classmethod
    def _a_real_person_zone(cls, box):
        if box is not None:
            x0, y0, x1, y1 = box
            if not all(0 <= v <= 1 for v in box) or not (x0 < x1 and y0 < y1):
                raise ValueError("person_zone must be x0, y0, x1, y1 between 0 and 1")
        return box

    @field_validator("when", "then", mode="before")
    @classmethod
    def _null_means_empty(cls, value):
        return {} if value is None else value

    def model_post_init(self, __context) -> None:
        self._folded_terms = [fold(t) for t in self.when.text_contains]
        self._folded_zones = [[fold(t) for t in z.text_contains or []] for z in self.when.zones]
        self._zone_tests = [
            [TermTest(fold(t), z.match) for t in z.text_contains or []] for z in self.when.zones
        ]
        pattern = self.when.filename_matches
        self._regex = regex.compile(pattern) if pattern is not None else None


@dataclass
class RuleError:
    file: str
    message: str


def _format_validation(e: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc']) or 'rule'}: {err['msg']}" for err in e.errors()
    )


LEARNED_FILE = "learned.yaml"  # rules made in the app; read before every other file
# rule ids the API cannot take: they are fixed routes under ``/api/rules``
RESERVED_IDS = frozenset({"state", "replay", "explain", "draft-zone", "area-picture", "areas"})

MAX_CONFIG_BYTES = 256 * 1024
TOO_DEEP_MESSAGE = "file skipped: too deeply nested or too large to load"


def read_yaml(path: Path) -> tuple[yaml.Node | None, object]:
    """Read one YAML config file: ``(node, data)``. Raise ``ValueError`` on any problem.

    Files over ``MAX_CONFIG_BYTES`` are refused unread; nesting too deep to construct
    (``RecursionError``) is reported like any other bad file.
    """
    try:
        if path.stat().st_size > MAX_CONFIG_BYTES:
            raise ValueError(f"file skipped: too large (over {MAX_CONFIG_BYTES // 1024} KB)")
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(f"cannot read file: {e}") from e
    loader = yaml.SafeLoader(text)
    try:
        node = loader.get_single_node()
        data = loader.construct_document(node) if node is not None else None
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f"line {mark.line + 1}: " if mark else ""
        problem = getattr(e, "problem", None) or str(e)
        raise ValueError(f"{where}invalid YAML: {problem}") from e
    except (RecursionError, MemoryError) as e:
        raise ValueError(TOO_DEEP_MESSAGE) from e
    finally:
        loader.dispose()
    return node, data


def load_rule_file(path: Path) -> list[Rule]:
    """Parse one rules file; raise ``ValueError`` with a readable message on any problem."""
    node, data = read_yaml(path)
    if not isinstance(data, list):
        raise ValueError("top level must be a list of rules")
    problems: list[str] = []
    rules: list[Rule] = []
    for i, item in enumerate(data):
        line = node.value[i].start_mark.line + 1
        if not isinstance(item, dict):
            problems.append(f"line {line}: a rule must be a mapping")
            continue
        try:
            rules.append(Rule.model_validate(item))
        except ValidationError as e:
            problems.append(f"line {line}: {_format_validation(e)}")
    if problems:
        raise ValueError("file skipped, no rule loaded from it: " + "; ".join(problems))
    return rules


def rule_files(rules_dir: Path) -> list[Path]:
    """The rule files in load order: ``learned.yaml`` first, then the rest by name."""
    if not Path(rules_dir).is_dir():
        return []
    return sorted(
        (
            p
            for p in Path(rules_dir).iterdir()
            if p.suffix.lower() in (".yaml", ".yml") and p.is_file()
        ),
        key=lambda p: (p.name != LEARNED_FILE, p.name),
    )


def load_rules(rules_dir: Path) -> tuple[list[Rule], list[RuleError]]:
    """Load ``*.yaml``/``*.yml``: ``learned.yaml`` first, then the others in name order.
    A bad file is reported and skipped."""
    rules: list[Rule] = []
    errors: list[RuleError] = []
    files = rule_files(rules_dir)
    owner: dict[str, str] = {}
    for path in files:
        try:
            loaded = load_rule_file(path)
            local: dict[str, str] = {}
            for r in loaded:
                first = owner.get(r.id) or local.get(r.id)
                if first:
                    raise ValueError(
                        f"file skipped: duplicate id {r.id!r} (first defined in {first})"
                    )
                local[r.id] = path.name
        except ValueError as e:
            errors.append(RuleError(file=path.name, message=str(e)))
            continue
        except (RecursionError, MemoryError):  # e.g. validating absurdly nested data
            errors.append(RuleError(file=path.name, message=TOO_DEEP_MESSAGE))
            continue
        owner.update(local)
        rules.extend(loaded)
    return rules, errors
