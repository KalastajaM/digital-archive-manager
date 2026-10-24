"""Where the time of a rule test goes, step by step (seconds, plus a few counts).

Filled in while a replay runs and written to dam's log when it ends: numbers only, no
paths, names or words."""

from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass
class Timings:
    sql: float = 0.0  # the list of documents and the text of each chunk
    fold: float = 0.0  # folding text (case and accents) for the word tests
    layouts: float = 0.0  # loading page-1 layouts (query and JSON parsing)
    zones: float = 0.0  # words in an area: the lines of page 1 inside the box
    picture_load: float = 0.0  # decoding page-1 pictures
    ncc: float = 0.0  # matching a picture area (the correlation)
    plan: float = 0.0  # ordering the documents (the sender, the folder, the picture ranking)
    rows: int = 0  # documents looked at
    text_chars: int = 0  # characters of text folded
    layouts_loaded: int = 0
    pictures_loaded: int = 0
    pictures_matched: int = 0

    def summary(self, total: float) -> str:
        """One line for the log: ``total`` is the wall time of the whole run."""
        timed = [f.name for f in fields(self) if isinstance(getattr(self, f.name), float)]
        other = total - sum(getattr(self, n) for n in timed)
        steps = " ".join(f"{n}={getattr(self, n):.2f}s" for n in timed)
        counts = " ".join(
            f"{f.name}={getattr(self, f.name)}" for f in fields(self) if f.name not in timed
        )
        return f"rule test: total={total:.2f}s {steps} other={max(0.0, other):.2f}s {counts}"
