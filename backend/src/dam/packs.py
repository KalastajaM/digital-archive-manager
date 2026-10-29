"""The packs detection uses now: a ``Profile`` of the enabled country and language packs,
with their label patterns and word sets built once. The App activates the profile its
settings ask for, at start and whenever they change; detection reads ``active()``. One
archive is open per process, so one profile is active at a time."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from dam import countries, languages
from dam.countries import CountryPack
from dam.languages import LanguagePack

DEFAULT_COUNTRIES = countries.DEFAULT_COUNTRIES
DEFAULT_LANGUAGES = languages.DEFAULT_LANGUAGES


@dataclass(frozen=True)
class Profile:
    countries: tuple[CountryPack, ...]  # the core pack first
    languages: tuple[LanguagePack, ...]
    due_labels: re.Pattern[str]
    total_strong: re.Pattern[str]
    total_weak: re.Pattern[str]
    stopwords: frozenset[str]
    kind_words: frozenset[str]
    months: dict[str, int]  # folded month word -> 1..12
    # where the addressee sits on page 1: the first enabled country that has a standard
    address_zone: tuple[float, float, float, float] | None


def build(country_codes: Sequence[str], language_codes: Sequence[str]) -> Profile:
    """``ValueError`` naming an unknown code."""
    cs = tuple(countries.enabled(country_codes))
    ls = tuple(languages.enabled(language_codes))
    months: dict[str, int] = {}
    for pack in ls:
        for number, forms in enumerate(pack.months, start=1):
            for form in forms:
                months.setdefault(form, number)
    return Profile(
        countries=cs,
        languages=ls,
        due_labels=languages.label_pattern(w for p in ls for w in p.due_labels),
        # whole words on folded text, so "subtotal" and "valisumma" are never labels
        total_strong=languages.label_pattern((w for p in ls for w in p.total_strong), True),
        total_weak=languages.label_pattern((w for p in ls for w in p.total_weak), True),
        stopwords=frozenset(w for p in ls for w in p.stopwords),
        kind_words=frozenset(w for p in ls for w in p.kind_words),
        months=months,
        address_zone=next((c.address_zone for c in cs if c.address_zone is not None), None),
    )


def business_id_kinds(profile: Profile) -> list[str]:
    """The identifier kinds that are business IDs (a Y-tunnus, later a btw-id): they name
    one organisation; not IBANs (``names_sender`` false) or web and mail domains (shared
    too widely)."""
    return [
        s.kind
        for p in profile.countries
        for s in p.identifiers
        if s.names_sender and not s.kind.endswith(".domain")
    ]


_active: Profile | None = None


def activate(profile: Profile) -> None:
    global _active
    _active = profile


def active() -> Profile:
    """The activated profile; the default packs until one is activated."""
    global _active
    if _active is None:
        _active = build(DEFAULT_COUNTRIES, DEFAULT_LANGUAGES)
    return _active
