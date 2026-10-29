"""The part of detection that is not tied to a country: always on."""

import re

from dam.checks import IBAN_LENGTHS, valid_iban, valid_rf
from dam.countries.model import CountryPack, IdentifierSpec, ReferenceSpec

_RF = re.compile(r"(?<![A-Za-z0-9])RF\d{2}[0-9A-Z ]{1,21}", re.ASCII)


def find_rf(text: str) -> list[tuple[int, str]]:
    """RF creditor references (ISO 11649), the longest valid run of each match."""
    found: list[tuple[int, str]] = []
    for m in _RF.finditer(text):
        tokens = m[0].split()  # "RF18", "5000", "1", ...
        for k in range(len(tokens), 0, -1):
            compact = "".join(tokens[:k])
            if valid_rf(compact):
                found.append((m.start(), compact))
                break
    return found


# a country code and check digits, then what may follow; a lookahead, so a run that is no
# IBAN does not hide one that starts inside it
_IBAN = re.compile(r"(?<![A-Za-z0-9])(?=([A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}))", re.ASCII)


def _iban_end(text: str, start: int, length: int) -> int:
    """Where an IBAN of ``length`` characters (spaces between them) starting at ``start``
    ends in ``text``."""
    pos, seen = start, 0
    while seen < length:
        if text[pos] != " ":
            seen += 1
        pos += 1
    return pos


def find_ibans(text: str) -> list[tuple[int, str]]:
    """Valid IBANs of SEPA countries, in text order: each its country's length, with no
    letter or digit right after it."""
    out: list[tuple[int, str]] = []
    for m in _IBAN.finditer(text):
        compact = m[1].replace(" ", "")
        length = IBAN_LENGTHS.get(compact[:2])
        if length is None or len(compact) < length or not valid_iban(compact[:length]):
            continue
        end = _iban_end(text, m.start(), length)
        if end < len(text) and text[end].isalnum():
            continue
        out.append((m.start(), compact[:length]))
    return out


def _once(values) -> list[str]:
    return list(dict.fromkeys(values))


_WWW = re.compile(r"(?i)\bwww\.([a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,})\b")
_MAIL = re.compile(r"(?i)\b[a-z0-9._%+-]+@([a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,})\b")
# mail services anyone can use: an address there names a person, not an organisation
FREE_MAIL = frozenset(
    "gmail.com googlemail.com outlook.com hotmail.com live.com msn.com icloud.com me.com "
    "yahoo.com aol.com proton.me protonmail.com gmx.com gmx.net mail.com".split()
)


def find_domains(text: str) -> list[str]:
    hits = sorted([(m.start(), m[1]) for p in (_WWW, _MAIL) for m in p.finditer(text)])
    return _once(d.lower() for _, d in hits if d.lower() not in FREE_MAIL)


CORE = CountryPack(
    code="core",
    name="Core",
    references=(ReferenceSpec("core.rf", find_rf),),
    identifiers=(
        IdentifierSpec("core.iban", "IBAN", lambda t: _once(v for _, v in find_ibans(t)), False),
        IdentifierSpec("core.domain", "Web or mail domain", find_domains, True),
    ),
)
