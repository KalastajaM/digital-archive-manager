"""The first-run setup controller behind the ``/api/setup`` routes."""

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from dam import layouts, setup
from dam.config import DEFAULTS_DIR, AppPaths, SpecialFolders
from dam.errors import Conflict, InvalidRequest
from dam.ops.model import GuardError, OpKind, ResolvedOp
from dam.services.layout import LayoutOutcome, layout_label, spec_from_input

log = logging.getLogger(__name__)


class SetupMode:
    """What the setup routes call. ``on_configured()`` is called (once, after the
    settings are written) to switch the server to the normal app; it returns whether
    that worked (False: the user has to restart ``dam serve``)."""

    def __init__(
        self,
        app_paths: AppPaths,
        on_configured: Callable[[], bool] | None = None,
        home: Path | None = None,
        on_layout: Callable[[layouts.Spec], LayoutOutcome] | None = None,
        defaults_dir: Path = DEFAULTS_DIR,
        guard: Callable[[Path], str | None] | None = None,
    ) -> None:
        self.app_paths = app_paths
        self.on_configured = on_configured
        self.on_layout = on_layout  # makes the layout's folders once the app is running
        self.defaults_dir = defaults_dir
        self.home = home
        self.guard = guard  # the other archives' folders are off limits (profiles)
        self._lock = threading.Lock()
        self._done = False

    def candidates(self) -> dict:
        return {
            "candidates": [
                {"provider": c.provider, "label": c.label, "path": str(c.path)}
                for c in setup.detect_candidates(self.home)
            ],
            "special_folders": setup.special_folders(),
            "layouts": [
                {
                    "id": t.id,
                    "title": t.title,
                    "description": t.description,
                    "folders": [{"key": r.key, "name": r.name} for r in t.folders],
                }
                for t in layouts.load_templates(self.defaults_dir)
            ],
        }

    def validate(self, raw: str) -> dict:
        check = setup.check_archive_path(raw, self.app_paths, self.home, self.guard)
        return {
            "ok": check.ok,
            "path": str(check.path) if check.path else None,
            "message": check.message,
            "exists": check.exists,
            "can_create": check.can_create,
            "subfolders": setup.list_subfolders(check.path) if check.ok and check.path else [],
            "empty": check.ok and setup.is_empty_folder(check.path),
            "item_count": len(setup.visible_entries(check.path)) if check.ok else 0,
        }

    def _spec(self, body: dict) -> layouts.Spec:
        """The layout the user chose (``body`` is the validated LayoutIn as a dict)."""
        special = SpecialFolders(**body["special"]) if body.get("special") else SpecialFolders()
        rows = [(r.get("key"), r["name"]) for r in body["folders"]]
        return spec_from_input(
            layouts.load_templates(self.defaults_dir),
            body.get("template"),
            bool(body.get("numbered", True)),
            rows,
            special,
        )

    def _folders(self, spec: layouts.Spec) -> list[layouts.Folder]:
        try:
            return layouts.build_folders(spec)
        except layouts.LayoutError as e:
            raise InvalidRequest(str(e)) from None

    def layout_preview(self, raw: str, body: dict) -> dict:
        """The folders a new archive at ``raw`` would get (which exist already: none
        for a folder that is empty or not made yet). Changes nothing."""
        check = setup.check_archive_path(raw, self.app_paths, self.home, self.guard)
        if not check.ok and not check.can_create:
            raise InvalidRequest(check.message or "That folder cannot be used.")
        spec = self._spec(body)
        folders = self._folders(spec)
        have = layouts.existing_names(check.path if check.ok else None)
        rows = [
            {
                "path": f.path,
                "role": f.role,
                "title": f.title,
                "exists": layouts.nfc(f.path).casefold() in have,
            }
            for f in folders
        ]
        missing = [r["path"] for r in rows if not r["exists"]]
        template = layouts.find_template(
            spec.template_id, layouts.load_templates(self.defaults_dir)
        )
        rules = layouts.layout_rules(template, folders)
        return {
            "folders": rows,
            "to_create": len(missing),
            "label": layout_label(len(missing)),
            "ops": [
                ResolvedOp(OpKind.MKDIR, None, name, None, "create missing folder")
                for name in missing
            ],
            "rule_ids": [str(r.get("id")) for r in rules],
            "rules_seedable": layouts.seedable(self.app_paths, self.defaults_dir),
        }

    def apply(self, raw: str, create: bool, layout: dict | None = None) -> dict:
        with self._lock:
            if self._done or setup.is_configured(self.app_paths):
                raise Conflict("The archive folder is already set up.")
            check = setup.check_archive_path(raw, self.app_paths, self.home, self.guard)
            if create and check.can_create:
                setup.create_archive_folder(check)
                check = setup.check_archive_path(raw, self.app_paths, self.home, self.guard)
            if not check.ok or check.path is None:
                raise InvalidRequest(check.message or "That folder cannot be used.")
            spec = self._spec(layout) if layout is not None else None
            folders = self._folders(spec) if spec is not None else []
            if spec is not None:
                template = layouts.find_template(
                    spec.template_id, layouts.load_templates(self.defaults_dir)
                )
                # the chosen special folder names go into the settings before the app
                # starts, so everything (guards, inbox, publishers) uses them
                setup.write_layout_settings(
                    self.app_paths, spec.special, layouts.ai_exclude_folders(template, folders)
                )
            setup.write_archive_root(self.app_paths, check.path)
            self._done = True
            switched = False
            if self.on_configured is not None:
                try:
                    switched = bool(self.on_configured())
                except Exception:
                    log.exception("could not switch to the normal app after setup")
            made = self._make_layout(spec, switched) if spec is not None else None
            return {
                "archive_root": str(check.path),
                "restart_needed": not switched,
                # after the layout was made, so they show as found
                "special_folders": setup.special_folder_status(check.path),
                "layout": made,
            }

    def _make_layout(self, spec: layouts.Spec, switched: bool) -> dict:
        """Make the layout's folders through the running app (previewed, journaled,
        undoable). A failure here does not undo the saved folder: it is reported."""
        if not switched or self.on_layout is None:
            return {
                "error": "dam has to be restarted before the folders can be made."
                " After restarting, choose Set up folders in Browse."
            }
        try:
            outcome = self.on_layout(spec)
        except (InvalidRequest, GuardError) as e:
            return {"error": str(e)}
        except Exception:
            log.exception("could not make the layout after setup")
            return {"error": "The folders could not be made. See the log for details."}
        return {
            "batch": outcome.batch,
            "created": outcome.created,
            "rules_written": outcome.rules_written,
            "rule_ids": outcome.rule_ids,
            "rules_error": outcome.rules_error,
        }
