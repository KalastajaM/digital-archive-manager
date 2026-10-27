"""Filing rules: the rules, their tests and offers, and picture areas (dam.api.schemas)."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from dam.api.schemas.base import StrictIn

# -- rules --------------------------------------------------------------------


class AreaOut(BaseModel):
    """An area of page 1 behind a suggestion or in a rule's explanation, for drawing it:
    ``box`` is [x0, y0, x1, y1] as fractions of page 1, origin top left. ``kind``: "text" (a
    rule's words), "image" (a rule's picture) or "address" (where people are looked for;
    ``rule_id`` "" is the archive's own area). ``index`` is the area's place in its rule's
    ``zones``. ``lines`` are the boxes of the lines that matched in it (for an address area,
    the line where the person was found). ``matched`` is whether the rule matched the
    document, ``reason`` why this area or the rule did not, ``wins`` whether the rule gave
    the folder or name, and ``score`` how well a picture matched (0 to 1)."""

    rule_id: str
    index: int
    box: list[float]
    kind: Literal["text", "image", "address"]
    lines: list[list[float]]
    score: float | None = None
    matched: bool = True
    reason: str | None = None
    wins: bool = False


class DraftWordOut(BaseModel):
    word: str
    ticked: bool


class RuleDraftOut(BaseModel):
    id: str
    words: list[DraftWordOut]
    folder: str | None
    name: str | None
    tags: list[str]
    tray: str | None
    payee: str | None


class ZoneIn(StrictIn):
    """An area of page 1: ``box`` is [x0, y0, x1, y1] as fractions of the page, origin top
    left. It has words (``text_contains``) or a picture (``image``, ``areas/<name>.png``
    from ``POST /api/rules/area-picture``): exactly one. ``min_score`` (a picture's, 0 to 1)
    is the score the picture needs; left out, the default (0.85). ``match`` (for words):
    how a word matches, ``word_start`` (begins a word, any ending), ``whole_word`` or
    ``anywhere``. Left out it is ``anywhere`` (how rules written before it matched)."""

    box: list[float] = Field(min_length=4, max_length=4)
    text_contains: list[str] | None = None
    image: str | None = None
    min_score: float | None = None
    match: Literal["word_start", "whole_word", "anywhere"] | None = None


class RuleWhenIn(StrictIn):
    text_contains: list[str] = Field(default_factory=list)
    filename_matches: str | None = None
    folder_is: str | None = None
    # areas of page 1: every one must match, within an area any one of its words
    zones: list[ZoneIn] = Field(default_factory=list)
    person: str | None = None


class RuleThenIn(StrictIn):
    folder: str | None = None
    name: str | None = None
    tags: list[str] = Field(default_factory=list)
    tray: str | None = None
    payee: str | None = None
    collections: list[str] = Field(default_factory=list)


class RuleIn(StrictIn):
    id: str
    when: RuleWhenIn = Field(default_factory=RuleWhenIn)
    then: RuleThenIn = Field(default_factory=RuleThenIn)
    person_zone: list[float] | None = Field(default=None, min_length=4, max_length=4)
    sender: str | None = None


class RuleReplayIn(StrictIn):
    rule: RuleIn
    replaces: str | None = None
    # for a new rule: the learned rule it goes directly above (see ``ZoneDraftOut``)
    place_above: str | None = None
    # continue a replay that stopped at its time budget: the ``next_after`` it gave (an
    # opaque cursor, good for a little while). Only the documents it had not reached are
    # looked at; the counts are for that part.
    after: str | None = None
    # the document the areas were drawn on: the documents in its folder are looked at early
    near_drive_id: str | None = None
    # the document the rule is being made from: left out of every count and list, and
    # judged on its own in ``source`` of the result
    source_drive_id: str | None = None


class RuleReplayJobIn(StrictIn):
    """Start a test of a rule in the background (same placement fields as ``RuleReplayIn``).
    ``sheet`` names the open sheet it is for: starting another test for the same sheet ends
    the first."""

    rule: RuleIn
    sheet: str = Field(min_length=1, max_length=64)
    replaces: str | None = None
    place_above: str | None = None
    near_drive_id: str | None = None
    source_drive_id: str | None = None


class AreasForIn(StrictIn):
    """The rule being tested and the document to draw its areas on."""

    rule: RuleIn
    drive_id: str


class AreasForOut(BaseModel):
    """The rule's areas on this document, as the suggestion has them (``AreaOut``): the
    matched lines of each text area, the best place and score of each picture area, and for
    one that did not match, why. Changes nothing."""

    areas: list[AreaOut]


class RuleMoveIn(StrictIn):
    delta: int


class RuleExplainIn(StrictIn):
    drive_id: str


class RulesStateIn(StrictIn):
    offer: bool | None = None
    clear_declined: bool = False


class RulesDeclineIn(StrictIn):
    words: list[str]


class ZoneOut(BaseModel):
    box: list[float]
    text_contains: list[str] | None
    image: str | None
    min_score: float | None = None
    match: Literal["word_start", "whole_word", "anywhere"] = "anywhere"


class RuleWhenOut(BaseModel):
    text_contains: list[str]
    filename_matches: str | None
    folder_is: str | None
    zones: list[ZoneOut]
    person: str | None


class RuleThenOut(BaseModel):
    folder: str | None
    name: str | None
    tags: list[str]
    tray: str | None
    payee: str | None
    collections: list[str]


class RuleStatsOut(BaseModel):
    suggested: int
    changed: int
    last_used: float | None
    flagged: bool


class RuleSampleOut(BaseModel):
    """A document the rule was last used on (still in the archive): a page to show its
    areas on."""

    drive_id: str
    name: str | None
    ext: str | None


class RuleOut(BaseModel):
    id: str
    file: str
    learned: bool
    when: RuleWhenOut
    then: RuleThenOut
    person_zone: list[float] | None
    sender: str | None
    stats: RuleStatsOut
    sample: RuleSampleOut | None = None


class RuleErrorOut(BaseModel):
    file: str
    message: str


class RulesStateOut(BaseModel):
    offer: bool
    declined: int


class RulesOut(BaseModel):
    rules: list[RuleOut]
    errors: list[RuleErrorOut]
    state: RulesStateOut
    # picture files in config/rules/areas that no loaded rule uses (a deleted rule leaves
    # its pictures)
    unused_pictures: list[str] = []
    # the score a picture area needs when it names none
    default_min_score: float = 0.85


class ReplayHitOut(BaseModel):
    drive_id: str
    path_now: str
    path_rule: str


class ShadowOut(BaseModel):
    drive_id: str
    rule_id: str  # the earlier rule that wins


class PictureScoreOut(BaseModel):
    """How well page 1 of a document matched a rule's picture areas (the lowest score of
    them) and whether the rule matched it."""

    path: str
    drive_id: str
    score: float
    matched: bool
    # for a document the rule did not match: the score its failing area needed (it is only
    # listed when within 0.15 of it)
    needed: float | None = None


class NotCheckedOut(BaseModel):
    """A document the rule could match by its words but whose page 1 could not be looked
    at; ``reason``: "page 1 not read yet", "no OCR engine" or "missing"."""

    path: str
    drive_id: str
    reason: str


class MarkedDocOut(BaseModel):
    path: str
    drive_id: str


class MarkedOut(BaseModel):
    """For a rule with a sender: the documents the owner marked as from that sender.
    ``missed`` are documents whose page 1 was read and the rule does not match (paths);
    ``not_checked`` those that could not be looked at yet (never counted as missed)."""

    total: int
    found: int
    missed: list[MarkedDocOut]
    not_checked: list[NotCheckedOut]


class SourceDocOut(BaseModel):
    """The document the rule is being made from, judged as live filing would (a document in
    the inbox by the rule as written, a filed one without its folder condition, as the test
    does) and left out of every count and list of the test. ``matched`` is null while page 1
    (or its picture) is not read yet, so it cannot be told; ``reason`` says why not, in the
    words of the explanation of a document ("no word found in the area", "the picture in the
    area scores 0.71, needs 0.85")."""

    drive_id: str
    path: str
    matched: bool | None
    reason: str = ""


class ReplayOut(BaseModel):
    matched: int
    same: int
    different: list[ReplayHitOut]
    inbox: int
    shadowed: list[ShadowOut]
    checked: int
    total: int
    truncated: bool
    not_checked: list[NotCheckedOut]
    # how many page-1 reads are queued by this replay (post it again to see them)
    reading: int
    # when ``truncated``: send it as ``after`` to test the rest, from where this stopped (an
    # opaque cursor: the order of the test is remembered for a little while)
    next_after: str | None = None
    # the filed documents gone through, those that could not be checked included
    looked_at: int = 0
    marked: MarkedOut | None = None  # only for a rule with a sender (first call only)
    # only for a rule with picture areas: the lowest scores of its matches and the highest
    # of its near misses (documents where only a picture area failed, within 0.15 of the
    # score it needed), to see how well they are told apart
    scores: list[PictureScoreOut] = []
    # only when the request named a ``source_drive_id`` that is in the index
    source: SourceDocOut | None = None


class ReplayJobOut(BaseModel):
    """A test running in the background. ``state``: "running" (going through the
    documents), "waiting" (all looked at; ``waiting`` of them wait for page 1 to be read and
    are looked at again as it is), "done", "stopped" (by the user, or the sheet was not
    heard from) or "error". ``looked_at`` of ``total`` filed documents are gone through.
    ``result`` is what has been found so far, as a finished test gives it; it is left out
    (null) when nothing changed since the ``version`` the poll said it had."""

    job_id: str
    sheet: str
    state: Literal["running", "waiting", "done", "stopped", "error"]
    version: int
    looked_at: int
    total: int
    waiting: int
    elapsed_s: float
    error: str | None = None
    result: ReplayOut | None = None


class ReadNowOut(BaseModel):
    """How many of a test's documents were queued to have page 1 read now."""

    queued: int


class Page1LineOut(BaseModel):
    text: str
    box: list[float]  # x0, y0, x1, y1 as fractions of page 1, origin top left


class Page1Out(BaseModel):
    """Page 1's lines. ``read`` false: not read yet (a read is queued), or it cannot be
    (``unavailable`` says why: "no OCR engine"; None while it is just waiting)."""

    read: bool
    lines: list[Page1LineOut]
    unavailable: str | None = None


class AreaPictureIn(StrictIn):
    """Cut the picture of ``box`` (fractions of page 1) from the document's page-1 picture.
    With ``save`` (and the rule's id, for the file name) it is also kept in
    ``config/rules/areas`` and the answer names it."""

    drive_id: str
    box: list[float] = Field(min_length=4, max_length=4)
    save: bool = False
    rule_id: str | None = None


class AreaPictureOut(BaseModel):
    """The crop: 8-bit grayscale, its long side at most 300 px; ``png`` is base64.
    ``image`` is the path for a zone's ``image`` once it is saved, else null."""

    width: int
    height: int
    png: str
    image: str | None = None


class Page1BoxIn(StrictIn):
    box: list[float] = Field(min_length=4, max_length=4)


class ZoneDraftIn(StrictIn):
    drive_id: str
    # one box, or several: each is an area of the rule, with one ticked word
    boxes: list[list[float]] = Field(default_factory=list, max_length=8)
    # boxes that become picture areas (the crop is kept as a picture file), after the others
    picture_boxes: list[list[float]] = Field(default_factory=list, max_length=4)
    sender: str | None = None

    @field_validator("boxes", "picture_boxes")
    @classmethod
    def _four_numbers(cls, boxes: list[list[float]]) -> list[list[float]]:
        if any(len(b) != 4 for b in boxes):
            raise ValueError("a box is four numbers: x0, y0, x1, y1")
        return boxes


class ZoneDraftAreaOut(BaseModel):
    """One box of a draft: the page-1 lines in it and its candidate words (one ticked)."""

    box: list[float]
    words: list[DraftWordOut]
    lines: list[str]


class ZoneDraftPictureOut(BaseModel):
    """A picture box of a draft: ``image`` is the saved crop (the zone's ``image``), ``png``
    the same picture in base64 to show."""

    box: list[float]
    image: str
    width: int
    height: int
    png: str


class ZoneDraftOut(RuleDraftOut):
    """The draft boxes drawn on page 1 start from. The rule's ``when`` is ``{folder_is,
    zones: [{box, text_contains: [the ticked word]}, ...]}``; ``zones`` has the candidate
    words and the page-1 lines of each box (``words`` itself is empty). ``place_above``: the
    learned rule that already matches the document; send it back when replaying or saving
    so the new rule is placed directly above it."""

    zones: list[ZoneDraftAreaOut]
    pictures: list[ZoneDraftPictureOut] = []
    folder_is: str | None
    sender: str | None
    place_above: str | None
    # who the document is for (the assignment, else the one person found in the address
    # area) and everyone found in the address area, for the rule sheet's For row
    person: str | None = None
    people_found: list[str] = []


class RuleExplainOut(BaseModel):
    rule_id: str
    matched: bool
    why: str
    wins: list[str]
    zone_lines: list[list[str]] = []  # page-1 lines in each of the rule's zones
    areas: list[AreaOut] = []  # the rule's areas for drawing, matched or not
