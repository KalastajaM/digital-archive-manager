"""What reading a filing-code QR sticker gives (no imaging dependencies, so the index
repository can store and load it cheaply)."""

from dataclasses import dataclass
from typing import Literal

Tick = Literal["ticked", "empty", "unclear"]


@dataclass(frozen=True)
class QrRead:
    """A dam sticker found on a page. ``star``/``important``: the tick boxes (None for
    the plain layout, which has none)."""

    code: str
    layout: int
    star: Tick | None = None
    important: Tick | None = None
