"""Starting an archive from scratch: the layout of top-level folders, and "New folder".

Both are *user-initiated* workflows. They are the only place a top-level folder is ever
made: they build a ``Plan(new_folders=True)`` (see ``dam.ops.model.Plan``), which the
planner accepts only when it holds nothing but folder creations with valid names, outside
the app's own folders. Everything goes through the executor: previewed, journaled and
undoable (undo removes only the folders that are still empty). Filing suggestions, rules
and syncs never build such a plan, so they still cannot create a top-level folder.
"""

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from dam import layouts
from dam.config import DEFAULTS_DIR, AppPaths, SpecialFolders
from dam.core.foldernames import FolderNameError, check_folder_name
from dam.core.paths import ArchivePaths
from dam.ops.executor import Executor
from dam.ops.guards import canonical, fold_parts, is_under, join
from dam.ops.model import BatchResult, GuardError, Op, OpKind, Plan, ResolvedOp
from dam.services import check_origin
from dam.services.errors import InvalidRequest

log = logging.getLogger(__name__)


@dataclass
class FolderPreview:
    path: str
    role: str  # inbox | ongoing | important | quarantine | layout
    title: str
    exists: bool  # already in the archive: left as it is


@dataclass
class LayoutPreview:
    folders: list[FolderPreview]
    to_create: int
    label: str
    ops: list[ResolvedOp]
    rule_ids: list[str]  # the example rules that would be written
    rules_seedable: bool  # False: the archive has rules of its own, which stay as they are


@dataclass
class LayoutOutcome:
    batch: BatchResult
    rules_written: bool = False
    rules_error: str | None = None
    created: int = 0
    rule_ids: list[str] = field(default_factory=list)


def layout_label(count: int) -> str:
    return f"Created the archive layout ({count} folder{'' if count == 1 else 's'})"


def spec_from_input(
    templates: list[layouts.Template],
    template_id: str | None,
    numbered: bool,
    rows: list[tuple[str | None, str]],
    special: SpecialFolders,
) -> layouts.Spec:
    """The ``Spec`` for what the user chose; the template only ties rows to its rules."""
    template = layouts.find_template(template_id, templates)
    if template_id is not None and template is None:
        raise InvalidRequest(f"Unknown layout {template_id!r}.")
    known = {r.key for r in template.folders} if template else set()
    seen: set[str] = set()
    out = []
    for key, name in rows:
        if key is not None and (key not in known or key in seen):
            key = None  # a key the template does not have (or has twice): just a name
        if key is not None:
            seen.add(key)
        out.append(layouts.Row(key, name))
    return layouts.Spec(template_id, tuple(out), numbered, special)


class LayoutService:
    def __init__(
        self,
        paths: ArchivePaths,
        executor: Executor,
        app_paths: AppPaths,
        reload_rules: Callable[[], object] | None = None,
        defaults_dir: Callable[[], Path] = lambda: DEFAULTS_DIR,
        rescan: Callable[[str], object] | None = None,
    ) -> None:
        self.paths = paths
        self.executor = executor
        self.app_paths = app_paths
        self.reload_rules = reload_rules
        self._defaults = defaults_dir
        self.rescan = rescan  # lists a new folder in the index at once (else the watcher does)

    @property
    def defaults_dir(self) -> Path:
        return self._defaults()

    # -- the layout -------------------------------------------------------------

    @property
    def special(self) -> SpecialFolders:
        return self.paths.settings.special_folders

    def templates(self) -> list[layouts.Template]:
        return layouts.load_templates(self.defaults_dir)

    def spec(
        self, template_id: str | None, numbered: bool, rows: list[tuple[str | None, str]]
    ) -> layouts.Spec:
        """The special folders are the configured ones (change them in settings.yaml)."""
        return spec_from_input(self.templates(), template_id, numbered, rows, self.special)

    def _folders(self, spec: layouts.Spec) -> list[layouts.Folder]:
        try:
            return layouts.build_folders(spec)
        except layouts.LayoutError as e:
            raise InvalidRequest(str(e)) from None

    def _plan(self, folders: list[layouts.Folder], origin: str) -> Plan:
        ops = [Op(OpKind.MKDIR, None, f.path) for f in folders]
        return Plan(ops, origin=origin, new_folders=True)

    def preview(self, spec: layouts.Spec, origin: str = "ui") -> LayoutPreview:
        """Every folder of the layout and which of them would be made. Nothing is
        changed or journaled."""
        check_origin(origin)
        folders = self._folders(spec)
        resolved = self.executor.preview(self._plan(folders, origin))
        made = {fold_parts(op.dst) for op in resolved if op.kind is OpKind.MKDIR}
        rows = [
            FolderPreview(f.path, f.role, f.title, fold_parts(f.path) not in made) for f in folders
        ]
        template = layouts.find_template(spec.template_id, self.templates())
        rules = layouts.layout_rules(template, folders)
        return LayoutPreview(
            rows,
            len(made),
            layout_label(len(made)),
            resolved,
            [str(r.get("id")) for r in rules],
            layouts.seedable(self.app_paths, self.defaults_dir),
        )

    def apply(self, spec: layouts.Spec, origin: str = "ui") -> LayoutOutcome:
        """Make the missing folders as one journaled batch, then (only if the archive
        has no rules of its own) write example rules for them."""
        check_origin(origin)
        folders = self._folders(spec)
        plan = self._plan(folders, origin)
        count = sum(1 for op in self.executor.preview(plan) if op.kind is OpKind.MKDIR)
        if count == 0:
            raise InvalidRequest("Every one of these folders exists already. Nothing to create.")
        plan.label = layout_label(count)
        batch = self.executor.apply(plan)
        outcome = LayoutOutcome(batch, created=len(batch.done))
        if batch.failed is not None or batch.error is not None:
            return outcome
        template = layouts.find_template(spec.template_id, self.templates())
        rules = layouts.layout_rules(template, folders)
        try:
            outcome.rules_written = layouts.write_layout_rules(
                self.app_paths, rules, self.defaults_dir
            )
            if outcome.rules_written:
                outcome.rule_ids = [str(r.get("id")) for r in rules]
                if self.reload_rules is not None:
                    self.reload_rules()
        except OSError as e:
            outcome.rules_error = (
                f"The folders were made, but the example rules were not saved ({e})"
            )
        return outcome

    # -- New folder -------------------------------------------------------------

    def _new_folder_plan(self, parent: str, name: str, origin: str) -> Plan:
        check_origin(origin)
        special = self.special
        names = (special.inbox, special.ongoing, special.important, special.quarantine)
        try:
            clean = check_folder_name(name, names)
            folder = canonical(parent, self.paths)
        except FolderNameError as e:
            raise InvalidRequest(str(e)) from None
        except GuardError:
            raise InvalidRequest(f"{parent!r} is not a folder in the archive.") from None
        if folder:
            disk = self.paths.abs(folder)
            if disk.is_symlink() or not disk.is_dir():
                raise InvalidRequest(f"{folder!r} is not a folder in the archive.")
        for area in names:
            if is_under(folder, area):
                raise InvalidRequest(f"Folders are not made inside {area}.")
        target = join(folder, clean)
        if any(fold_parts(e.name) == fold_parts(clean) for e in self._entries(folder)):
            raise InvalidRequest(f"There is already a folder or file called {clean!r} here.")
        where = f"in {folder}" if folder else "at the top of the archive"
        return Plan(
            [Op(OpKind.MKDIR, None, target)],
            origin=origin,
            label=f"Created the folder {clean} {where}",
            new_folders=True,
        )

    def _entries(self, folder: str) -> list[os.DirEntry]:
        try:
            return list(os.scandir(self.paths.abs(folder)))
        except OSError:
            return []

    def new_folder_preview(self, parent: str, name: str, origin: str = "ui") -> list[ResolvedOp]:
        """The folder that would be made (``[]`` is never returned: an existing name is
        refused). Nothing is changed or journaled."""
        return self.executor.preview(self._new_folder_plan(parent, name, origin))

    def new_folder(self, parent: str, name: str, origin: str = "ui") -> BatchResult:
        """Make one folder, at the top of the archive (``parent`` empty) or inside
        ``parent``, as one journaled batch that undo can reverse while it is empty."""
        batch = self.executor.apply(self._new_folder_plan(parent, name, origin))
        if batch.done and self.rescan is not None:
            try:
                self.rescan(batch.done[0].dst)
            except Exception:  # made all the same; the watcher's next scan lists it
                log.warning("indexing the new folder failed", exc_info=True)
        return batch
