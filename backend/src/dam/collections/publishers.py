"""Publishers: things that turn collections into something else (e.g. the Ongoing links).

A publisher brings its output in line with the collections on ``sync()`` (applying
goes through the normal operation layer) and can preview a sync for some collections
as if they were changed (``preview_for``). Every registered publisher is synced after
each collection change (``PublisherRegistry.sync_all``, wired by ``App``). Export is not
a publisher (it is on demand).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from dam.errors import NotFound

if TYPE_CHECKING:
    from dam.ops.model import ResolvedOp

log = logging.getLogger(__name__)


class Publisher(Protocol):
    id: str

    def sync(self, dry_run: bool = False, label: str | None = None) -> object:
        """Bring the published output in line with the collections; returns a result.
        ``label``: what the user did that made this sync necessary, for Activity."""
        ...

    def preview_for(
        self,
        collection_ids: list[int],
        *,
        state: str | None = None,
        publish: bool | None = None,
        name: str | None = None,
    ) -> list[ResolvedOp]:
        """What a sync of these collections would do, as if they were in ``state``,
        published on/off or called ``name``. Reads only."""
        ...


class PublisherRegistry:
    def __init__(self) -> None:
        self._publishers: dict[str, Publisher] = {}

    def register(self, publisher: Publisher) -> None:
        self._publishers[publisher.id] = publisher

    def get(self, publisher_id: str) -> Publisher:
        try:
            return self._publishers[publisher_id]
        except KeyError:
            raise NotFound(f"unknown publisher {publisher_id!r}") from None

    def all(self) -> list[Publisher]:
        return list(self._publishers.values())

    def sync_all(self, label: str | None = None) -> dict[str, object]:
        """Sync every publisher, in registration order: publisher id -> its result
        (None when it raised; logged, and the others still run). ``label`` is passed
        on only when given."""
        results: dict[str, object] = {}
        for publisher in self.all():
            try:
                results[publisher.id] = publisher.sync(label=label) if label else publisher.sync()
            except Exception:
                log.exception("publisher %s: sync failed", publisher.id)
                results[publisher.id] = None
        return results
