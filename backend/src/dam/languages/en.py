"""English: label words, stopwords and document-kind words."""

from dam.languages.model import LanguagePack

ENGLISH = LanguagePack(
    code="en",
    name="English",
    due_labels=("due date", r"\bdue\b"),
    total_strong=("total",),
    stopwords=tuple(
        """
        a an the and or but nor so if then than that this these those there here of
        in on at to for from by with without about into onto over under after before
        between during is are was were be been being am do does did done have has
        had having will would shall should can could may might must not no yes i me
        my mine we us our ours you your yours he him his she her hers it its they
        them their theirs what which who whom whose when where why how all any some
        each every both few more most other such only own same too very just also as
        up down out off again once please tell show find give get got know much many
        lot lots one ones
        """.split()
    ),
    kind_words=tuple(
        """
        scan scanned document documents image images invoice receipt letter page
        pages copy final draft print this that with from your have been will
        attachment screenshot
        """.split()
    ),
)
