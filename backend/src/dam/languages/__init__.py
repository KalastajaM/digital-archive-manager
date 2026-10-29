"""Language packs: the words detection needs to read documents in one language (labels
for due dates and totals, stopwords, document-kind words). They are reached only through
``get`` and ``enabled`` and the helpers below."""

import re
from collections.abc import Iterable, Sequence

from dam.languages.en import ENGLISH
from dam.languages.fi import FINNISH
from dam.languages.model import LanguagePack
from dam.languages.sv import SWEDISH

__all__ = [
    "DEFAULT_LANGUAGES",
    "PACKS",
    "LanguagePack",
    "enabled",
    "get",
    "kind_words",
    "label_pattern",
    "stopwords",
]

PACKS: dict[str, LanguagePack] = {p.code: p for p in (FINNISH, ENGLISH, SWEDISH)}
DEFAULT_LANGUAGES: tuple[str, ...] = ("fi", "sv", "en")  # the Finland pack's, then English


def get(code: str) -> LanguagePack:
    try:
        return PACKS[code]
    except KeyError:
        raise ValueError(f"unknown language pack {code!r}") from None


def enabled(codes: Sequence[str] = DEFAULT_LANGUAGES) -> list[LanguagePack]:
    return [get(code) for code in codes]


def label_pattern(fragments: Iterable[str], whole_words: bool = False) -> re.Pattern[str]:
    """The fragments as one alternation, tried in the order given; ``whole_words`` puts
    word boundaries around all of them. No fragments: a pattern that never matches (an
    empty alternation would match everywhere)."""
    body = "|".join(fragments)
    if not body:
        return re.compile(r"(?!)")
    return re.compile(rf"\b(?:{body})\b" if whole_words else body)


def stopwords(codes: Sequence[str] = DEFAULT_LANGUAGES) -> frozenset[str]:
    return frozenset(w for pack in enabled(codes) for w in pack.stopwords)


def kind_words(codes: Sequence[str] = DEFAULT_LANGUAGES) -> frozenset[str]:
    return frozenset(w for pack in enabled(codes) for w in pack.kind_words)
