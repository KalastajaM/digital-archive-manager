"""Snapshots as the API and the UI see them: list, take, export, import, restore, show
the folder.

A restore closes the archive and opens it again around the swap; that is the host's job
(``Host.close_and_reopen`` in ``dam serve``). Without a host (the API used on its own) a
restore is refused with a message. ``snapshot_current`` has no default: the caller must
have asked whether to take a snapshot of the current state first.
"""

import sys
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

from dam import snapshots
from dam.config import AppPaths
from dam.services.errors import Conflict, NotFound
from dam.services.launch import LaunchService, Runner, run_open

_LOCK = threading.Lock()  # one snapshot, import or restore at a time in this process


@runtime_checkable
class Reopener(Protocol):
    """What ``dam serve`` offers: close this archive, run ``change``, open it again."""

    def close_and_reopen[T](self, change: Callable[[], T]) -> T: ...


class SnapshotService:
    def __init__(
        self,
        paths: AppPaths,
        folders: snapshots.Folders,
        reopener: Reopener | None = None,
        pending: Callable[[], bool] = lambda: False,
        runner: Runner = run_open,
        platform: str = sys.platform,
    ) -> None:
        self.paths = paths
        self.folders = folders
        self.reopener = reopener
        self.pending = pending
        self.runner = runner
        self.platform = platform

    def _info(self, name: str) -> dict:
        return vars(snapshots.read_info(self.paths, name, self.folders.archive_root))

    def overview(self) -> dict:
        found = snapshots.list_snapshots(self.paths, self.folders.archive_root)
        return {
            "folder": str(snapshots.snapshots_dir(self.paths)),
            "snapshots": [vars(s) for s in found],
            "can_restore": self.reopener is not None,
        }

    def create(self) -> dict:
        with _LOCK:
            made = snapshots.create_snapshot(self.paths)
        return self._info(made.name)

    def file(self, name: str) -> Path:
        """The zip to export (download) as it is."""
        return snapshots.path_of(self.paths, name)

    def import_file(self, source: Path) -> dict:
        with _LOCK:
            added = snapshots.import_snapshot(self.paths, source)
        return self._info(added.name)

    def restore(self, name: str, snapshot_current: bool, other_folder_ok: bool = False) -> dict:
        """Restore snapshot ``name``; with ``snapshot_current`` a snapshot of the current
        state is taken first (and a failure there stops the restore)."""
        if self.reopener is None:
            raise Conflict("This window cannot restore a snapshot. Start dam with `dam serve`.")
        if self.pending():
            raise Conflict(
                "An operation was interrupted and is not finished. Run `dam recover` "
                "before restoring, so its record is not lost."
            )
        with _LOCK:
            snapshots.path_of(self.paths, name)  # 404 before anything else
            folder = snapshots.snapshots_dir(self.paths)
            with tempfile.TemporaryDirectory(dir=folder, prefix=".restoring-") as tmp:
                staged = snapshots.stage(self.paths, name, self.folders, other_folder_ok, Path(tmp))
                safety = None
                if snapshot_current:
                    safety = snapshots.create_snapshot(self.paths, snapshots.BEFORE_RESTORE)
                replaced = self.reopener.close_and_reopen(
                    lambda: snapshots.apply_restore(self.paths, staged)
                )
        return {
            "restored": name,
            "safety_snapshot": vars(safety) if safety else None,
            "replaced_folder": str(replaced),
            "kept_folders": staged.kept_folders,
        }

    def reveal(self) -> None:
        """Show the snapshots folder in the file manager."""
        folder = snapshots.snapshots_dir(self.paths)
        folder.mkdir(parents=True, exist_ok=True)
        if not folder.is_dir():
            raise NotFound(f"{folder} is not there.")
        launcher = LaunchService(None, self.runner, self.platform)  # type: ignore[arg-type]
        status = self.runner(launcher.command(False, folder.resolve()))
        if status != 0:
            raise Conflict(f"Could not open the folder (the system opener exited {status})")
