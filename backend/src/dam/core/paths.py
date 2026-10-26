"""Archive-relative path handling and guards."""

import os
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from dam.config import Settings
from dam.core.fs import listable, lists_nothing, resolve


class OutsideArchiveError(ValueError):
    """A path lies outside the archive root."""


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _not_plain(part: str) -> bool:
    """A component that is not one plain name on this platform: on Windows a backslash
    separates folders (so ``..\\x`` is an escape) and ``:`` makes a drive or stream."""
    return os.name == "nt" and ("\\" in part or ":" in part)


def _fold(s: str) -> str:
    return nfc(s).casefold()


@dataclass(frozen=True)
class ArchiveFolder:
    """One folder of the archive: ``label == ""`` is the main folder, any other label
    is the first path component its content appears under."""

    label: str
    root: Path


def folder_connected(folder: ArchiveFolder, has_rows: Callable[[str], bool] | None) -> bool:
    """The one definition of a connected folder: its root can be listed, and an extra
    folder does not list nothing while the index has rows under its label (a cloud drive
    signed out leaves an empty mount point). ``has_rows`` (label -> the index has live
    rows under it) None: listable is enough."""
    if not listable(folder.root):
        return False
    if not folder.label or has_rows is None:
        return True
    return not (lists_nothing(folder.root) and has_rows(folder.label))


def not_connected_message(folder: ArchiveFolder) -> str:
    """What the owner reads when ``folder`` (an extra folder) is needed but unplugged."""
    return f"'{folder.label}' is not connected ({folder.root}). Connect it and try again."


class ArchivePaths:
    # how long a connectivity answer serves file lists and search (``cached``), so a
    # slow network mount is not listed for every response; a change always asks afresh
    connected_ttl_s = 2.0

    def __init__(
        self, root: Path, settings: Settings, has_rows: Callable[[str], bool] | None = None
    ) -> None:
        self.root = resolve(root)
        self.settings = settings
        # label -> the index has live rows under it (``FileRepo.has_live_under``, wired by
        # ``App``); used by ``is_connected``
        self.has_rows = has_rows
        self._connected: dict[str, tuple[float, bool]] = {}  # label -> (monotonic, answer)
        self.folders: tuple[ArchiveFolder, ...] = (
            ArchiveFolder("", self.root),
            *(
                ArchiveFolder(extra.label, resolve(extra.path))
                for extra in settings.extra_folders
                if extra.attached
            ),
        )

    @property
    def extra_labels(self) -> tuple[str, ...]:
        return tuple(f.label for f in self.folders[1:])

    def main_rel_ok(self, inner: str) -> bool:
        """``inner`` (a path in the main folder) does not start with a component that
        folds to an archive folder's label, attached or detached: such an entry is left
        out of the archive, as its rel would name that folder's files."""
        parts = PurePosixPath(inner).parts
        if not parts:
            return True
        first = _fold(parts[0])
        return all(_fold(extra.label) != first for extra in self.settings.extra_folders)

    def label_of(self, rel: str) -> str:
        """The extra folder's label ``rel`` lies at or under, else ``""``."""
        parts = PurePosixPath(rel).parts
        if not parts:
            return ""
        first = _fold(parts[0])
        for f in self.folders[1:]:
            if _fold(f.label) == first:
                return f.label
        return ""

    def folder_of(self, rel: str) -> ArchiveFolder:
        label = self.label_of(rel)
        return next(f for f in self.folders if f.label == label)

    def join(self, rel: str) -> Path:
        """Where ``rel`` lies on disk: the extra label maps to its root. No containment
        check (see ``abs``)."""
        folder = self.folder_of(rel)
        parts = PurePosixPath(rel).parts
        return folder.root.joinpath(*(parts[1:] if folder.label else parts))

    def is_connected(self, label: str, cached: bool = False) -> bool:
        """Whether the folder ``label`` is connected (``folder_connected``). ``cached``
        accepts an answer up to ``connected_ttl_s`` old: only for what is shown, never
        before changing the archive."""
        now = time.monotonic()
        last = self._connected.get(label)
        if cached and last is not None and now - last[0] <= self.connected_ttl_s:
            return last[1]
        folder = next(f for f in self.folders if f.label == label)
        connected = folder_connected(folder, self.has_rows)
        self._connected[label] = (now, connected)
        return connected

    def disconnected_labels(self, cached: bool = False) -> tuple[str, ...]:
        return tuple(f.label for f in self.folders[1:] if not self.is_connected(f.label, cached))

    @property
    def inbox(self) -> str:
        return self.settings.special_folders.inbox

    @property
    def ongoing(self) -> str:
        return self.settings.special_folders.ongoing

    @property
    def important(self) -> str:
        return self.settings.special_folders.important

    @property
    def quarantine(self) -> str:
        return self.settings.special_folders.quarantine

    def quarantine_for(self, rel: str) -> str:
        """The ``##. To Delete`` that ``rel`` goes into: its own folder's (a rename never
        crosses disks), so ``Old years/##. To Delete`` for a path under ``Old years``."""
        label = self.label_of(rel)
        return f"{label}/{self.quarantine}" if label else self.quarantine

    @property
    def quarantines(self) -> tuple[str, ...]:
        """Every folder's ``##. To Delete``: the main folder's first, then one per
        attached extra folder."""
        return (self.quarantine, *(f"{label}/{self.quarantine}" for label in self.extra_labels))

    def is_quarantined(self, rel: str, strict: bool = False) -> bool:
        """``rel`` is one of the ``##. To Delete`` folders or inside one (``strict``:
        inside only)."""
        parts = PurePosixPath(_fold(rel)).parts
        for q in self.quarantines:
            qp = PurePosixPath(_fold(q)).parts
            if parts[: len(qp)] == qp and not (strict and len(parts) == len(qp)):
                return True
        return False

    @property
    def publish_roots(self) -> tuple[str, str]:
        """The two folders the publisher owns entries in (``##. Ongoing`` and
        ``##. Important``): the only places the app ever removes anything, and only
        its own links and empty folders there."""
        return (self.ongoing, self.important)

    def in_publish_root(self, rel: str) -> str | None:
        """The publish root ``rel`` lies strictly inside (never the root itself), or
        None."""
        parts = PurePosixPath(_fold(rel)).parts
        for root in self.publish_roots:
            rp = PurePosixPath(_fold(root)).parts
            if len(parts) > len(rp) and parts[: len(rp)] == rp:
                return root
        return None

    def _locate(self, p: Path) -> Path:
        """Resolve the parent (not the item itself) so symlinks stay links."""
        p = Path(p)
        try:
            if p.name in ("", ".", ".."):
                return resolve(p)
            return resolve(p.parent) / p.name
        except (RuntimeError, OSError):
            raise OutsideArchiveError(f"cannot resolve {p}") from None

    def rel(self, p: Path) -> str:
        located = self._locate(p)
        for folder in self.folders:
            try:
                r = located.relative_to(folder.root)
            except ValueError:
                continue
            inner = "" if r == Path(".") else r.as_posix()
            if not folder.label:
                if not self.main_rel_ok(inner):
                    break
                return inner
            return f"{folder.label}/{inner}" if inner else folder.label
        raise OutsideArchiveError(f"{p} is outside the archive")

    def abs(self, rel: str) -> Path:
        parts = PurePosixPath(rel).parts
        if (
            PurePosixPath(rel).is_absolute()
            or ".." in parts
            or any(_not_plain(part) for part in parts)
            or (os.name == "nt" and (PureWindowsPath(rel).drive or PureWindowsPath(rel).root))
        ):
            raise OutsideArchiveError(f"{rel!r} is outside the archive")
        result = self.join(rel)
        try:
            self._locate(result).relative_to(self.folder_of(rel).root)
        except ValueError:
            raise OutsideArchiveError(f"{rel!r} is outside the archive") from None
        return result

    def is_inside(self, p: Path) -> bool:
        try:
            self.rel(p)
        except OutsideArchiveError:
            return False
        return True

    def is_root(self, rel: str) -> bool:
        return rel == ""

    def is_top_level(self, rel: str) -> bool:
        return len(PurePosixPath(rel).parts) == 1

    def is_protected(self, rel: str) -> bool:
        parts = PurePosixPath(_fold(rel)).parts
        for prot in self.settings.protected_paths:
            pp = PurePosixPath(_fold(prot)).parts
            if parts[: len(pp)] == pp:
                return True
        return False
