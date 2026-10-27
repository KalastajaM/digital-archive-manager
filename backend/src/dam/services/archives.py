"""The archives (profiles) as the API and the UI see them: list, add, switch, rename,
recolour, forget, show in the file manager.

One service belongs to one running API, which serves one profile (``current_id``).
Switching to another profile is the host's job (``dam serve`` closes this profile's
background work and opens the other one in the same process); without a host (the API
used on its own) switching is refused with a message. Forgetting only edits the
registry: no folder is ever deleted.
"""

import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from dam import demo, setup
from dam.config import AppPaths
from dam.core.paths import fold_name
from dam.errors import Conflict, InvalidRequest, NotFound
from dam.profiles import MAIN_ID, MAIN_NAME, PALETTE, Locked, Profile, ProfileStore, ServeLock
from dam.services.launch import LaunchService, Runner, run_open

log = logging.getLogger(__name__)


class Switcher(Protocol):
    """What ``dam serve`` offers: open another profile in the running process, or open
    this one afresh (its archive folders changed)."""

    def switch(self, key: str) -> Profile: ...

    def reopen(self) -> None: ...


@dataclass(frozen=True)
class SwitchOutcome:
    profile: Profile
    restart_needed: bool = False


class ArchiveService:
    def __init__(
        self,
        store: ProfileStore,
        current_id: str,
        switcher: Switcher | None = None,
        paths: AppPaths | None = None,
        runner: Runner = run_open,
        platform: str = sys.platform,
        home: Path | None = None,
        build_demo: Callable[[Path, Path], None] = demo.build_into,
    ) -> None:
        self.store = store
        self.current_id = current_id
        self.switcher = switcher
        self.paths = paths  # the current profile's data folder (for the folder checks)
        self.runner = runner
        self.platform = platform
        self.home = home
        self.build_demo = build_demo

    # -- reading ------------------------------------------------------------------------

    def current(self) -> Profile:
        """The profile this server runs (a placeholder when the registry no longer lists
        it, e.g. forgotten from another terminal)."""
        profiles = self.store.load()
        for p in profiles:
            if p.id == self.current_id:
                return p
        data_dir = self.paths.data_dir if self.paths else self.store.base
        return Profile(self.current_id, MAIN_NAME, PALETTE[0][1], data_dir, True)

    def describe(self, p: Profile) -> dict:
        elsewhere = None
        if p.id != self.current_id:
            elsewhere = ServeLock.holder(p.data_dir)
        root = p.archive_root
        return {
            "id": p.id,
            "name": p.name,
            "color": p.color,
            "data_dir": str(p.data_dir),
            "archive_root": root,
            "extra_folders": [
                {"label": label, "path": str(path), "attached": attached}
                for label, path, attached in setup.current_extra_folder_entries(p.paths)
            ],
            "configured": root is not None,
            "current": p.id == self.current_id,
            "in_use_elsewhere": elsewhere is not None,
            "port": elsewhere.get("port") if elsewhere else None,
        }

    def summary(self) -> dict:
        """The profile in use (for ``/api/status``) and how many there are."""
        profiles = self.store.load()
        cur = next((p for p in profiles if p.id == self.current_id), None) or self.current()
        return {
            "archive": {"id": cur.id, "name": cur.name, "color": cur.color},
            "profiles_count": len(profiles),
        }

    def overview(self) -> dict:
        return {
            "archives": [self.describe(p) for p in self.store.load()],
            "current": self.current_id,
            "can_switch": self.switcher is not None,
        }

    # -- changing -----------------------------------------------------------------------

    def _demo_folder(self, raw: str) -> Path:
        """The folder for a demo archive: new or empty, and clear of every other archive
        (checked before anything is registered)."""
        paths = self.paths or AppPaths(self.store.base)
        check = setup.check_archive_path(raw, paths, self.home, self.store.root_guard(None))
        if check.path is None or not (check.ok or check.can_create):
            raise InvalidRequest(check.message or "That folder cannot be used.")
        if check.ok and not setup.is_empty_folder(check.path):
            raise InvalidRequest("That folder is not empty. Pick a new or empty folder.")
        return check.path

    def add(self, name: str, color: str | None = None, demo_folder: str | None = None) -> dict:
        """Register a new archive (its data folder is made; not switched to). With
        ``demo_folder``: also build the fictional demo archive there."""
        self.store.check_new_name(name)
        folder = self._demo_folder(demo_folder) if demo_folder else None
        profile = self.store.add(name, color)
        if folder is not None:
            try:
                if not folder.exists():
                    folder.mkdir(parents=False)
                self.build_demo(folder, profile.data_dir)
            except BaseException:
                # leave no half-made entry in the list; the folders are not touched
                self.store.forget(profile.id)
                raise
        return self.describe(self.store.find(profile.id))

    def switch(self, key: str) -> SwitchOutcome:
        target = self.store.find(key)
        if target.id == self.current_id:
            return SwitchOutcome(target)
        if self.switcher is None:
            raise Conflict(
                "This window cannot switch archives. Start dam with --archive "
                f"'{target.name}' to open it."
            )
        try:
            return SwitchOutcome(self.switcher.switch(target.id))
        except Locked as e:
            raise Conflict(f"'{target.name}': {e}") from None

    def reopen(self) -> bool:
        """Open this archive afresh in the running server, so an added, detached or
        attached archive folder takes effect. False when it could not (no server, or the
        reopen failed and was rolled back): ``dam serve`` must be restarted."""
        if self.switcher is None:
            return False
        try:
            self.switcher.reopen()
        except Exception:
            log.exception("could not reopen the archive after its folders changed")
            return False
        return True

    def update(self, key: str, name: str | None = None, color: str | None = None) -> dict:
        target = self.store.find(key)
        if name is not None:
            target = self.store.set_name(target.id, name)
        if color is not None:
            target = self.store.recolor(target.id, color)
        return self.describe(self.store.find(target.id))

    def forget(self, key: str, switch_to: str | None = None) -> dict:
        """Remove the entry from the list; returns where its folders are (they stay).
        Forgetting the archive in use needs ``switch_to``: another archive to open."""
        target = self.store.find(key)
        info = self.describe(target)
        if target.id == self.current_id:
            if len(self.store.load()) == 1:
                raise Conflict(
                    f"'{target.name}' is your only archive, so it cannot be forgotten. "
                    "Add another archive first."
                )
            if switch_to is None:
                raise Conflict(
                    f"'{target.name}' is the archive in use. Choose which archive to open "
                    "instead, then forget this one."
                )
            heir = self.store.find(switch_to)
            if heir.id == target.id:
                raise InvalidRequest("Choose a different archive to open.")
            self.switch(heir.id)  # raises if it cannot: the entry is then kept
        self.store.forget(target.id)
        return {
            "forgotten": info,
            "data_dir": info["data_dir"],
            "archive_root": info["archive_root"],
        }

    def reveal(self, key: str, what: str, label: str | None = None) -> None:
        """Show the profile's data folder, archive folder or one of its extra archive
        folders (``what="extra"`` with its ``label``) in the file manager. The folder
        comes from the registry and the settings, never from the client."""
        p = self.store.find(key)
        if what not in ("data", "archive", "extra"):
            raise InvalidRequest("what must be 'data', 'archive' or 'extra'")
        if what == "extra":
            if not label:
                raise InvalidRequest("Say which extra folder (its label).")
            found = [
                path
                for name, path, _ in setup.current_extra_folder_entries(p.paths)
                if fold_name(name) == fold_name(label)
            ]
            if not found:
                raise NotFound(f"This archive has no extra folder '{label}'.")
            raw = str(found[0])
        else:
            raw = p.archive_root if what == "archive" else str(p.data_dir)
        if not raw:
            raise NotFound("This archive has no archive folder yet.")
        folder = Path(raw).expanduser()
        if not folder.is_dir():
            raise NotFound(f"{folder} is not there.")
        launcher = LaunchService(None, self.runner, self.platform)  # type: ignore[arg-type]
        status = self.runner(launcher.command(False, folder.resolve()))
        if status != 0:
            raise Conflict(f"Could not open the folder (the system opener exited {status})")


def solo(paths: AppPaths) -> ArchiveService:
    """The service for an API used on its own: the data folder is the one archive "Main"
    and nothing can be switched."""
    return ArchiveService(ProfileStore(paths.data_dir), MAIN_ID, None, paths)
