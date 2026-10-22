"""Archive-relative path handling and guards."""

import os
import unicodedata
from pathlib import Path, PurePosixPath, PureWindowsPath

from dam.config import Settings
from dam.core.fs import resolve


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


class ArchivePaths:
    def __init__(self, root: Path, settings: Settings) -> None:
        self.root = resolve(root)
        self.settings = settings

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
        try:
            r = self._locate(p).relative_to(self.root)
        except ValueError:
            raise OutsideArchiveError(f"{p} is outside the archive") from None
        return "" if r == Path(".") else r.as_posix()

    def abs(self, rel: str) -> Path:
        parts = PurePosixPath(rel).parts
        if (
            PurePosixPath(rel).is_absolute()
            or ".." in parts
            or any(_not_plain(part) for part in parts)
            or (os.name == "nt" and (PureWindowsPath(rel).drive or PureWindowsPath(rel).root))
        ):
            raise OutsideArchiveError(f"{rel!r} is outside the archive")
        result = self.root.joinpath(*parts)
        if not self.is_inside(result):
            raise OutsideArchiveError(f"{rel!r} is outside the archive")
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
