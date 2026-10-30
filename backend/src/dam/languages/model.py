"""What a language pack holds. Packs are data: they are reached through ``dam.languages``,
never imported one by one."""

from dataclasses import dataclass


@dataclass(frozen=True)
class LanguagePack:
    code: str  # ISO 639-1
    name: str  # "Finnish"
    # label words as regex fragments on folded text (no diacritics, case-folded), in the
    # order they are tried: a longer label that starts like a shorter one comes first
    due_labels: tuple[str, ...] = ()
    total_strong: tuple[str, ...] = ()
    total_weak: tuple[str, ...] = ()
    stopwords: tuple[str, ...] = ()  # left out of questions to the archive
    # words that say what kind of document it is or how it was made, not who it is from
    kind_words: tuple[str, ...] = ()
    # the 12 months, each as the folded forms written in dates ("15 oktober 2026")
    months: tuple[tuple[str, ...], ...] = ()
    # the language writes month names with a capital (English): a lower-case "may" or
    # "march" is then a word, not a month
    months_capitalized: bool = False
