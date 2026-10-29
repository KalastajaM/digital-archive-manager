"""Finnish: label words (folded: no diacritics), stopwords and document-kind words."""

from dam.languages.model import LanguagePack

FINNISH = LanguagePack(
    code="fi",
    name="Finnish",
    due_labels=("erapaiva", "erapvm", "maksettava"),
    total_strong=("yhteensa", "maksettava", "loppusumma", "kokonaissumma"),
    total_weak=("summa",),
    stopwords=tuple(
        """
        ja tai mutta sekä vai eli kuin kun jos niin että jotta koska vaikka myös
        vain jo nyt sitten siis ei en et emme ette eivät olla olen olet on olemme
        olette ovat oli olin olit olimme olitte olivat ollut olleet onko onkos ole
        minä sinä hän me te he minun sinun hänen meidän teidän heidän minua sinua
        häntä meitä teitä heitä minulla sinulla hänellä meillä teillä heillä se ne
        sen niiden sitä niitä siitä niistä siihen niihin sillä niillä tämä tuo nämä
        nuo tämän tuon tätä tuota tässä tuossa täällä siellä mikä mitkä mitä minkä
        missä mistä mihin millä milloin miten miksi kuka ketkä kenen kenelle kuinka
        paljonko montako mikäli joka jotka jonka joita jossa josta johon jolla
        kanssa ilman yli alle ennen jälkeen aikana välillä
        """.split()
    ),
    kind_words=tuple(
        """
        lasku kuitti kirje oikea sivu liite
        """.split()
    ),
)
