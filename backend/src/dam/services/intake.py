"""Getting documents in: copy files from anywhere on this computer into the inbox.

The files are *copied* (the originals stay where they are), never over an existing file
(a taken name gets ``_2``), as one journaled COPY batch. Undo moves the copies to the
quarantine folder, like any other file the app takes out of the archive: the app never
deletes. A file over ``MAX_COPY_BYTES`` is refused.
"""

import logging
import re
from collections.abc import Callable
from pathlib import Path

from dam.core.fs import realpath
from dam.core.paths import ArchivePaths, nfc
from dam.ops.executor import Executor
from dam.ops.guards import is_ds_store_name
from dam.ops.model import ABS_TARGET, BatchResult, GuardError, Op, OpKind, Plan, ResolvedOp
from dam.ops.primitives import MAX_COPY_BYTES
from dam.services import check_origin
from dam.services.errors import InvalidRequest, TooLarge

_WINDOWS_BAD = re.compile(r'[\x00-\x1f\x7f<>:"|?*]')
_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)
log = logging.getLogger(__name__)
MAX_FILES = 200
LIMIT_MB = MAX_COPY_BYTES // (1024 * 1024)


def clean_file_name(raw: str) -> str:
    """A file name that is safe in the archive on every platform: only the last path
    component, characters Windows refuses replaced with ``_``, no trailing dot or space,
    a reserved Windows name given a ``_`` in front, at most 255 bytes. ``InvalidRequest``
    for a name with nothing usable in it or one that would be hidden (starts with a dot)."""
    name = nfc(raw).replace("\\", "/").rsplit("/", 1)[-1]
    name = _WINDOWS_BAD.sub("_", name).strip().rstrip(". ")
    if not name:
        raise InvalidRequest("That file has no usable name.")
    if name.startswith(".") or is_ds_store_name(name):
        raise InvalidRequest(f"{name!r} starts with a dot (a hidden file); rename it first.")
    if name.split(".")[0].rstrip().casefold() in _RESERVED:
        name = "_" + name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    elif not stem:
        stem, ext = name, ""
    else:
        ext = "." + ext
    while len((stem + ext).encode("utf-8")) > 255 and stem:
        stem = stem[:-1]
    return (stem + ext).rstrip(". ") or "file"


class IntakeService:
    def __init__(
        self,
        paths: ArchivePaths,
        executor: Executor,
        rescan: Callable[[str], object] | None = None,
    ) -> None:
        self.paths = paths
        self.executor = executor
        self.rescan = rescan  # indexes the inbox right away (else the watcher gets there)

    def _plan(
        self, sources: list[Path], origin: str, names: list[str] | None = None
    ) -> tuple[Plan, list[str]]:
        check_origin(origin)
        if not sources:
            raise InvalidRequest("No files given.")
        if len(sources) > MAX_FILES:
            raise InvalidRequest(f"Add at most {MAX_FILES} files at a time.")
        inbox = self.paths.inbox
        disk = self.paths.abs(inbox)
        if disk.is_symlink() or not disk.is_dir():
            raise InvalidRequest(
                f"The inbox folder {inbox!r} does not exist yet. Create it first:"
                " Browse > New folder, or start from a layout."
            )
        ops, final = [], []
        for i, source in enumerate(sources):
            real = realpath(source)
            if not real.is_file():
                raise InvalidRequest(f"{source.name}: not a file (folders are not copied).")
            if real.stat().st_size > MAX_COPY_BYTES:
                raise TooLarge(f"{source.name} is larger than {LIMIT_MB} MB.")
            name = clean_file_name(names[i] if names else source.name)
            final.append(name)
            ops.append(Op(OpKind.COPY, ABS_TARGET + str(real), inbox, name=name))
        what = final[0] if len(final) == 1 else f"{len(final)} files"
        return Plan(ops, origin=origin, label=f"Added {what} to the inbox"), final

    def preview(self, sources: list[Path], origin: str = "cli") -> list[ResolvedOp]:
        """Where each file would land in the inbox (a taken name gets ``_2``)."""
        try:
            return self.executor.preview(self._plan(sources, origin)[0])
        except GuardError as e:
            raise InvalidRequest(str(e)) from None

    def add_files(
        self, sources: list[Path], origin: str = "cli", names: list[str] | None = None
    ) -> BatchResult:
        """Copy ``sources`` into the inbox as one journaled batch (``names``: the names to
        give them instead of their own, e.g. an upload's file name)."""
        plan, _ = self._plan(sources, origin, names)
        try:
            result = self.executor.apply(plan)
        except GuardError as e:
            raise InvalidRequest(str(e)) from None
        if result.done and self.rescan is not None:
            try:
                self.rescan(self.paths.inbox)
            except Exception:  # the batch is done; the watcher's next scan picks the files up
                log.warning("indexing the new files failed", exc_info=True)
        return result
