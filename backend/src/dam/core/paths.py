"""Archive-relative path handling and guards."""

import os
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from dam.config import Settings
from dam.core.fs import listable, resolve


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


def not_connected_message(folder: ArchiveFolder) -> str:
    """What the owner reads when ``folder`` (an extra folder) is needed but unplugged."""
    return f"'{folder.label}' is not connected ({folder.root}). Connect it and try again."


class ArchivePaths:
    def __init__(self, root: Path, settings: Settings) -> None:
        self.root = resolve(root)
        self.settings = settings
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

    def is_connected(self, label: str) -> bool:
        return listable(next(f for f in self.folders if f.label == label).root)

    def disconnected_labels(self) -> tuple[str, ...]:
        return tuple(f.label for f in self.folders[1:] if not listable(f.root))

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
