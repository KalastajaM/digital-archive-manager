"""Dutch: label words (folded: no diacritics), stopwords and document-kind words.

The label words are not from a source: they are the usual ones on Dutch bills, to be
checked on real ones."""

from dam.languages.model import LanguagePack

DUTCH = LanguagePack(
    code="nl",
    name="Dutch",
    # "te betalen voor" before "betalen voor": the longer one is tried first
    due_labels=("vervaldatum", "uiterste betaaldatum", "te betalen voor", "betalen voor"),
    total_strong=("totaal te betalen", "totaalbedrag", "totaal", "te betalen"),
    total_weak=("bedrag",),
    stopwords=tuple(
        """
        de het een en of maar want dus als dan dat die dit deze daar hier er van in
        op aan te met voor door over naar bij uit om tot onder tegen tussen na zonder
        is zijn was waren ben bent wordt worden werd werden heb hebt heeft hebben had
        hadden kan kunnen kon konden zal zullen zou zouden moet moeten mag mogen wil
        willen niet geen wel ook nog al ja nee ik mij me mijn wij we ons onze jij
        je jou jouw u uw hij hem zij ze haar hun hen wat wie welk welke waar
        wanneer waarom hoe hoeveel alle alles iets niets elk elke ieder iedere veel
        meer meest zo zeer
        """.split()
    ),
    kind_words=tuple(
        """
        factuur nota bon kassabon aanmaning herinnering brief pagina bijlage
        """.split()
    ),
    months=(
        ("januari", "jan"),
        ("februari", "feb"),
        ("maart", "mrt"),
        ("april", "apr"),
        ("mei",),
        ("juni", "jun"),
        ("juli", "jul"),
        ("augustus", "aug"),
        ("september", "sep", "sept"),
        ("oktober", "okt"),
        ("november", "nov"),
        ("december", "dec"),
    ),
)
