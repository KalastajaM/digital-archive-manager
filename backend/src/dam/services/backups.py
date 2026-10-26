"""Backups as the API and the UI see them: list, make one, restore one, show the folder.

A restore closes the archive and opens it again around the swap; that is the host's job
(``Host.reopen`` in ``dam serve``). Without a host (the API used on its own) a restore is
refused with a message. ``backup_current`` has no default: the caller must have asked
whether to back up the current state first.
"""

import sys
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

from dam import backups
from dam.config import AppPaths
from dam.services.errors import Conflict, NotFound
from dam.services.launch import LaunchService, Runner, run_open

_LOCK = threading.Lock()  # one backup or restore at a time in this process


@runtime_checkable
class Reopener(Protocol):
    """What ``dam serve`` offers: close this archive, run ``change``, open it again."""

    def reopen[T](self, change: Callable[[], T]) -> T: ...


class BackupService:
    def __init__(
        self,
        paths: AppPaths,
        archive_root: Path | None,
        reopener: Reopener | None = None,
        pending: Callable[[], bool] = lambda: False,
        runner: Runner = run_open,
        platform: str = sys.platform,
    ) -> None:
        self.paths = paths
        self.archive_root = archive_root
        self.reopener = reopener
        self.pending = pending
        self.runner = runner
        self.platform = platform

    def overview(self) -> dict:
        return {
            "folder": str(backups.backups_dir(self.paths)),
            "backups": [vars(b) for b in backups.list_backups(self.paths, self.archive_root)],
            "can_restore": self.reopener is not None,
        }

    def create(self) -> dict:
        with _LOCK:
            info = backups.create_backup(self.paths)
        return vars(backups.read_info(self.paths, info.name, self.archive_root))

    def restore(self, name: str, backup_current: bool) -> dict:
        """Restore backup ``name``; with ``backup_current`` a backup of the current state
        is made first (and a failure there stops the restore)."""
        if self.reopener is None:
            raise Conflict("This window cannot restore a backup. Start dam with `dam serve`.")
        if self.pending():
            raise Conflict(
                "An operation was interrupted and is not finished. Run `dam recover` "
                "before restoring, so its record is not lost."
            )
        with _LOCK:
            backups.read_info(self.paths, name)  # 404 before anything else
            folder = backups.backups_dir(self.paths)
            with tempfile.TemporaryDirectory(dir=folder, prefix=".restoring-") as tmp:
                staged = backups.stage(self.paths, name, self.archive_root, Path(tmp))
                safety = None
                if backup_current:
                    safety = backups.create_backup(self.paths, backups.BEFORE_RESTORE)
                replaced = self.reopener.reopen(lambda: backups.apply_restore(self.paths, staged))
        return {
            "restored": name,
            "safety_backup": vars(safety) if safety else None,
            "replaced_folder": str(replaced),
        }

    def reveal(self) -> None:
        """Show the backups folder in the file manager."""
        folder = backups.backups_dir(self.paths)
        folder.mkdir(parents=True, exist_ok=True)
        if not folder.is_dir():
            raise NotFound(f"{folder} is not there.")
        launcher = LaunchService(None, self.runner, self.platform)  # type: ignore[arg-type]
        status = self.runner(launcher.command(False, folder.resolve()))
        if status != 0:
            raise Conflict(f"Could not open the folder (the system opener exited {status})")
