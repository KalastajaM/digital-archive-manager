"""Swedish: label words (folded: no diacritics)."""

from dam.languages.model import LanguagePack

SWEDISH = LanguagePack(
    code="sv",
    name="Swedish",
    due_labels=("forfallodag",),
    total_strong=("totalt", "att betala"),
    months=(
        ("januari",),
        ("februari",),
        ("mars",),
        ("april",),
        ("maj",),
        ("juni",),
        ("juli",),
        ("augusti",),
        ("september",),
        ("oktober",),
        ("november",),
        ("december",),
    ),
)
