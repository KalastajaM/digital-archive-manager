"""Lock shared by every writer of the file index and the archive folder."""

import threading
from collections.abc import Iterator
from contextlib import contextmanager

# The scanner and the operation executor both change the index, and the executor also
# renames files on disk. Without a common lock, a scan can read a directory between the
# executor's rename and its index update (inserting a second row for the moved file), or
# apply directory data it gathered before an op moved a file (reverting that op's index
# update). The executor holds it for one whole operation (act through index update),
# except while a copy across disks reads and writes the file (see ``COPYING``); the
# scanner holds it for one directory (gather plus apply), never a whole scan. It is
# re-entrant so nested index work on the same thread cannot deadlock.
INDEX_LOCK = threading.RLock()


class _Copying:
    """The temporary files (``.dam-copy-*``, by name: each name is unique) a copy across
    disks is writing right now, without ``INDEX_LOCK``. A scan leaves them out, so a copy
    in progress gets no index row (and is not listed as left over); once it is renamed
    into place, or has failed and stays, it is an ordinary file again."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._names: set[str] = set()

    @contextmanager
    def writing(self, name: str) -> Iterator[None]:
        """Around the whole copy: entered before the file is created."""
        with self._lock:
            self._names.add(name)
        try:
            yield
        finally:
            with self._lock:
                self._names.discard(name)

    def __contains__(self, name: str) -> bool:
        with self._lock:
            return name in self._names


COPYING = _Copying()
