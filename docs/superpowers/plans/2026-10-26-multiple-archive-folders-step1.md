# Multiple archive folders, step 1: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let one archive span a main folder plus labelled extra folders on other disks or cloud services, without cross-disk moves.

**Architecture:** `ArchivePaths` becomes the only place that maps archive-relative paths to disk: a path whose first component is an attached label lives in that extra folder, everything else in the main folder. The scanner, watcher, To Delete handling and operation guards learn about folders through that class. An offline folder is skipped completely, so nothing under it is ever marked missing.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy Core on SQLite, watchdog, pytest; React + TypeScript, Vite, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-26-multiple-archive-folders-design.md`

## Global Constraints

- All safety rules in `CONTRIBUTING.md` apply. `backend/tests/test_no_delete.py` is not touched. Only `dam/ops` writes to the archive.
- Text IO always passes `encoding="utf-8"` (`tests/test_encoding.py` fails otherwise).
- `pathlib` only, no shell commands. Backend CI runs on macOS, Windows and Ubuntu.
- Tests use temporary fake archives only: the main folder from the `fake_archive` fixture plus extra folders made under `tmp_path`.
- No database migration is expected. If one turns out to be needed, name it `00NN_<topic>.py` with the next free number.
- Every user-visible change gets a `CHANGELOG.md` entry under `## [Unreleased]`.
- After API changes run `npm run gen:api` in `frontend/` and commit `src/api/schema.d.ts`.
- Published text (docs, changelog, commit messages): no em or en dashes as punctuation, no AI-tell phrasing. Commits use `feat:`/`fix:`/`test:`/`docs:` prefixes, say why, and end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Label comparisons are always NFC plus casefold (`core.paths._fold`).
- Exact user-facing messages (copy them verbatim):
  - overlap: `That folder is already part of this archive ('{label}').`, `That folder is inside '{label}', which is already part of this archive.`, `That folder contains '{label}', which is already part of this archive.` (the main folder's label in these messages is `the main folder`)
  - offline op: `'{label}' is not connected ({path}). Connect it and try again.`
  - reserved name: `'{name}' is the name of an archive folder. Choose another name.`

## Decisions this plan adds to the spec

- **Relabel is deferred to step 2.** Paths with the label prefix also live in rule and tray YAML files under the config folder, not only in the database tables, so a safe relabel needs its own design. In step 1 the label is fixed when the folder is added.
- **Detached folders stay in `settings.yaml`** with `attached: false`, so Maintenance can say a link points into a detached folder and Settings can offer **Attach again** with the same label.

## Review Focus

- A mount point that exists but lists nothing (external disk folder with the disk unplugged, iCloud not signed in) while the index has rows under that label must count as offline, not as "all files deleted". Test in Task 4.
- A folder that disconnects during the walk must leave every row under its label untouched. Test in Task 4.
- The same folder reached by another spelling (a symlink to the main folder, NFD vs NFC, different case on macOS) must be refused as overlapping. Test in Task 3.
- `label_of` must match whole path components: a main-folder folder `Old years 2` is not under the label `Old years`. Test in Task 1.
- A top-level folder in the main folder that differs from a label only in case or normalisation (`old years`, NFD `Old years`) is a clash. dam refuses to create one, and the scanner reports one made outside dam. Tests in Tasks 3 and 4.

---

### Task 1: Settings key and multi-folder `ArchivePaths`

**Files:**
- Modify: `backend/src/dam/config.py` (`Settings`, `load_settings`)
- Modify: `backend/src/dam/core/paths.py`
- Test: `backend/tests/test_paths.py`, `backend/tests/test_config.py`
- Test helper: `backend/tests/conftest.py` (fixture `extra_folder`)

**Interfaces:**
- Produces, in `config.py`: `class ExtraFolder(BaseModel): label: str; path: Path; attached: bool = True`, and `Settings.extra_folders: list[ExtraFolder] = []` (paths `expanduser()`ed in `load_settings` like `archive_root`).
- Produces, in `core/paths.py`:
  - `@dataclass(frozen=True) class ArchiveFolder: label: str; root: Path` (`label == ""` is the main folder)
  - `ArchivePaths.root: Path` stays the main folder.
  - `ArchivePaths.folders: tuple[ArchiveFolder, ...]`: main first, then attached extras in settings order, roots resolved.
  - `ArchivePaths.extra_labels: tuple[str, ...]`
  - `ArchivePaths.label_of(rel: str) -> str`: the extra label `rel` lies at or under, else `""`.
  - `ArchivePaths.folder_of(rel: str) -> ArchiveFolder`
  - `ArchivePaths.join(rel: str) -> Path`: maps the label to its root and joins the rest, with no containment check. It replaces `paths.root / rel`.
  - `ArchivePaths.is_connected(label: str) -> bool`: `listable(folder.root)`.
  - `ArchivePaths.disconnected_labels() -> tuple[str, ...]`: attached extras that are not connected.
  - `rel()` tries every folder's root. `abs()` maps through `join()` and keeps its escape checks per folder.
- Produces, in `tests/conftest.py`: fixture `extra_folder(tmp_path, app_paths) -> FakeArchive`. It makes `tmp_path / "disk" / "Archive 2000-2015"` and writes `extra_folders: [{label: "Old years", path: ...}]` into the test settings file.

- [ ] **Step 1: Write the failing tests** in `test_paths.py`:

```python
def test_extra_folder_paths_map_to_their_root(tmp_path):
    main, extra = tmp_path / "main", tmp_path / "disk" / "old"
    main.mkdir(); extra.mkdir(parents=True)
    s = Settings(archive_root=main, extra_folders=[ExtraFolder(label="Old years", path=extra)])
    p = ArchivePaths(main, s)
    assert p.abs("Old years/2009/a.pdf") == resolve(extra) / "2009" / "a.pdf"
    assert p.rel(extra / "2009" / "a.pdf") == "Old years/2009/a.pdf"
    assert p.rel(extra) == "Old years"
    assert p.abs("Taxes/a.pdf") == resolve(main) / "Taxes" / "a.pdf"

def test_label_of_matches_whole_components(tmp_path): ...
    # "Old years 2/x" -> "", "old years/x" -> "Old years", NFD "Old years/x" -> "Old years"

def test_escape_from_extra_folder_refused(tmp_path): ...
    # abs("Old years/../x") and abs("Old years/" + "..") raise OutsideArchiveError

def test_detached_folder_is_not_mapped(tmp_path): ...
    # attached=False: abs("Old years/a") resolves under main, extra_labels == ()

def test_disconnected_labels(tmp_path): ...
    # extra root renamed away -> disconnected_labels() == ("Old years",)
```

And in `test_config.py`: `extra_folders` round-trips from YAML, and `~` in `path` is expanded.

- [ ] **Step 2: Run** `cd backend && uv run pytest tests/test_paths.py tests/test_config.py -q`. Expected: FAIL (`ExtraFolder` not defined).
- [ ] **Step 3: Implement** the interfaces above. `label_of` folds both sides with `_fold` and compares `PurePosixPath(...).parts[0]`.
- [ ] **Step 4: Run** the same command. Expected: PASS. Then run the whole suite (`uv run pytest -q -W error`). Expected: PASS, since nothing uses extras yet.
- [ ] **Step 5: Commit** `feat: map archive paths across a main folder and labelled extra folders`.

### Task 2: Route every disk lookup through `ArchivePaths`

**Files:**
- Modify: `backend/src/dam/ops/planner.py:103,112,185,439` (`self.paths.root / x` becomes `self.paths.join(x)`)
- Modify: `backend/src/dam/ops/executor.py:167` (made-folder and undo-link containment root becomes `self.paths.folder_of(rel).root`)
- Modify: `backend/src/dam/services/launch.py:102,122,160,190`, `backend/src/dam/services/links.py:59`, `backend/src/dam/ai/service.py:257`
- Keep on the main folder, and add a comment saying why: `app.py:338` (`archive_available`), `collections/export.py:117`, `serve.py:129`
- Test: `backend/tests/test_launch.py`, `backend/tests/test_links.py`, `backend/tests/test_move.py`

**Interfaces:**
- Consumes: `ArchivePaths.join`, `folder_of`, `is_connected` (Task 1).
- Produces: `services.launch` raises `Conflict` with the offline-op message when the file's folder is not connected (used by Task 8's UI).

- [ ] **Step 1: Write the failing tests:**
  - `test_reveal_file_in_extra_folder`: Reveal/open of `Old years/2009/a.pdf` targets the path under the extra root.
  - `test_open_file_in_disconnected_folder_says_so`: the extra root renamed away gives `Conflict` with `'Old years' is not connected (`.
  - `test_link_drop_from_extra_folder`: dropping a file from the extra folder onto a main-folder folder makes a link whose target is the file's absolute path under the extra root.
  - `test_move_within_extra_folder`: moving `Old years/2009/a.pdf` to `Old years/2010/` plans and applies one rename, and undo restores it.
- [ ] **Step 2: Run** `uv run pytest tests/test_launch.py tests/test_links.py tests/test_move.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the replacements listed under Files.
- [ ] **Step 4: Run** the same tests, then the full suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat: open, link and move files inside extra archive folders`.

### Task 3: Adding, detaching and attaching folders (backend rules)

**Files:**
- Create: `backend/src/dam/archive_folders.py`
- Modify: `backend/src/dam/profiles.py` (`root_conflict`, `root_problems`), `backend/src/dam/setup.py` (new `current_extra_folders`)
- Modify: `backend/src/dam/ops/guards.py` (reserved top-level names)
- Test: `backend/tests/test_archive_folders.py` (new), `backend/tests/test_profiles.py`

**Interfaces:**
- Consumes: `profiles.related`, `foldernames.check_folder_name`, `settings_write.write_keys`, `ArchivePaths` (Task 1), `FileRepo.mark_missing`, `FileRepo._delete_rows`.
- Produces, in `archive_folders.py`:
  - `check_label(label: str, paths: ArchivePaths, settings: Settings) -> str | None`: the rules from the spec "Adding an extra folder" step 2. Labels of detached entries count as taken too.
  - `check_folder(candidate: Path, paths: ArchivePaths, store: ProfileStore | None, current_id: str | None) -> str | None`: overlap against own folders (exact messages in Global Constraints), then `profiles.root_conflict` for other profiles and data folders, then "can be listed now".
  - `add_folder(app_paths, label: str, path: Path, dry_run: bool) -> FolderChange`
  - `detach_folder(app_paths, repo, label: str, forget: bool, dry_run: bool) -> FolderChange`: sets `attached: false`, then `repo.mark_missing(math.inf, subtree=label)`. With `forget`, the rows under the label are removed through a new `FileRepo.forget_subtree(rel: str) -> int` that reuses `_delete_rows`. These are database rows only.
  - `attach_folder(app_paths, label: str, dry_run: bool) -> FolderChange`: runs `check_folder` again, then sets `attached: true`.
  - `@dataclass class FolderChange: label: str; path: str; files: int; reopen: bool` (`files` is the number of rows affected by a detach or forget).
- Produces, in `setup.py`: `current_extra_folders(app_paths: AppPaths) -> list[Path]` (attached ones, read raw like `current_archive_root`). `root_conflict` checks the candidate against every other profile's main folder and its extras.
- Produces, in `guards.py`: `check_not_label(paths, rel)`, which raises `GuardError` with the reserved-name message when a new or renamed top-level main-folder entry folds to an attached label. It is called wherever the planner creates or renames a top-level entry (mkdir, move, rename).

- [ ] **Step 1: Write the failing tests** in `test_archive_folders.py`:
  - each overlap case: the same folder as main, inside main, around main, the same as another extra, a symlink to the main folder (Review Focus), the same folder in NFD spelling (Review Focus), and inside another profile's extra folder (via `test_profiles.py`'s store helpers)
  - label rules: empty, `##. x`, `a/b`, a duplicate in other case, a clash with an existing main top-level `old years` (Review Focus), and the label of a detached entry
  - `test_detach_marks_rows_missing_and_attach_restores`: scan, tag a file, detach (rows missing, tag row kept), attach and scan (same `drive_id`, tag still there, `missing` false)
  - `test_forget_removes_rows_only`: the file on disk is still there afterwards
  - `test_new_folder_named_like_label_refused`: New folder `OLD YEARS` at the main top level raises `GuardError` with the reserved-name message
  - `test_dry_run_writes_nothing`: the settings file bytes are unchanged
- [ ] **Step 2: Run** `uv run pytest tests/test_archive_folders.py tests/test_profiles.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the interfaces above. Write settings with `write_keys(app_paths, {"extra_folders": [...]}, verify)`, where `verify` checks the reloaded list.
- [ ] **Step 4: Run** the same tests, then the full suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat: add, detach and attach extra archive folders with overlap and label checks`.

### Task 4: Scanner per folder

**Files:**
- Modify: `backend/src/dam/index/scanner.py` (`ScanReport`, `_disk_spelling`, `_scan`)
- Test: `backend/tests/test_scanner.py`

**Interfaces:**
- Consumes: `ArchivePaths.folders`, `folder_of`, `extra_labels` (Task 1).
- Produces: `ScanReport.offline: list[str]` (labels skipped because they are not connected) and `ScanReport.clashes: list[str]` (main top-level names that fold to a label). `aborted` keeps meaning "the main folder is not available".

Full scan (`subtree == ""`): walk the main folder as today, but skip top-level entries that fold to an attached label (record them in `clashes`). Then, for each attached extra, run the existing subtree walk with `start = folder.root`. Skip an extra, appending its label to both `offline` and `skipped`, when it is not listable, or when it lists nothing while `repo.list_dir(label)` has rows. Before `mark_missing`, check each walked extra is still listable; if one is not, append its label to `offline` and `skipped`. A subtree scan under an offline label aborts, as today's "start folder cannot be read" path does. `_disk_spelling` starts at `paths.folder_of(rel).root` and skips the label component.

- [ ] **Step 1: Write the failing tests:**
  - `test_full_scan_indexes_extra_folder`: `Old years` gets a folder row, and its files get rows under `Old years/...`
  - `test_offline_extra_marks_nothing_missing`: scan, rename the extra root away, scan. `report.offline == ["Old years"]`, no row under the label is missing, and main-folder deletions are still marked missing.
  - `test_empty_mount_counts_as_offline` (Review Focus): an extra root that exists but is empty, with indexed rows, behaves as above
  - `test_extra_gone_during_walk_marks_nothing` (Review Focus): monkeypatch `listable` to return False for the extra root on its second call
  - `test_reconnect_unmarks`: back on disk, the next scan gives `missing` false with the same `drive_id`s
  - `test_clash_reported_and_not_indexed` (Review Focus): a main top-level folder `old years` made on disk outside dam lands in `report.clashes`, and its files are not indexed
- [ ] **Step 2: Run** `uv run pytest tests/test_scanner.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** as described above.
- [ ] **Step 4: Run** the same tests, then the full suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat: scan each archive folder on its own so an unplugged disk never looks deleted`.

### Task 5: Watcher per folder

**Files:**
- Modify: `backend/src/dam/index/watcher.py`
- Test: `backend/tests/test_watcher.py`

**Interfaces:**
- Consumes: `ArchivePaths.folders`, `is_connected` (Task 1), `scan(paths, repo, subtree)` (Task 4).
- Produces: `Watcher.refresh_watches() -> list[str]`, which returns the labels that just reconnected. It holds one watchdog `ObservedWatch` per connected folder (`observer.schedule` / `observer.unschedule`), drops the watch of a folder that went away, and adds one for a folder that came back. `start()` calls it. `_reconcile_loop` calls it before each scan, and for each reconnected label runs `scan(paths, repo, subtree=label)` and `_call_on_change()`. `_aborted` logs the offline labels from the report as well.

- [ ] **Step 1: Write the failing tests:** `test_refresh_watches_follows_connect_and_disconnect` (rename the extra root away and back, then assert the returned labels and the scheduled watch paths), and `test_change_in_extra_folder_is_noted` (`_note` on a path under the extra root queues `Old years/...`).
- [ ] **Step 2: Run** `uv run pytest tests/test_watcher.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** as described above.
- [ ] **Step 4: Run** the same tests, then the full suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat: watch every connected archive folder and rescan one that comes back`.

### Task 6: To Delete in every folder, and operations refused while a folder is offline

**Files:**
- Modify: `backend/src/dam/core/paths.py` (quarantine helpers)
- Modify every caller of `paths.quarantine` / `special.quarantine` that tests membership or builds a path: `ops/planner.py:358,405,498`, `ops/guards.py:118,128,188,202`, `services/browse.py:162,309,527,569,581`, `services/today.py:161,176`, `maintenance/checks.py:197,227,232,439`, `api/deps.py:44`, `ai/tasks/ask_archive.py:216`, `rules/replay.py:445`, `rules/engine.py:499`
- Modify: `backend/src/dam/ops/guards.py` (new `check_connected`), `ops/planner.py` and `ops/undo.py` (call it)
- Test: `backend/tests/test_folder_to_delete.py` (new), `backend/tests/test_restore.py`, `backend/tests/test_ops_undo.py`, `backend/tests/test_move.py`

**Interfaces:**
- Produces, in `core/paths.py`:
  - `ArchivePaths.quarantine_for(rel: str) -> str`: `"Old years/##. To Delete"` for a rel under `Old years`, else `self.quarantine`
  - `ArchivePaths.quarantines -> tuple[str, ...]`: main first, then one per attached extra
  - `ArchivePaths.is_quarantined(rel: str, strict: bool = False) -> bool`: `is_under` against any of them
- Quarantine destination: `join(quarantine_for(src), <src without its label>)`, so `Old years/2009/a.pdf` goes to `Old years/##. To Delete/2009/a.pdf`. Restore `original` strips that prefix and puts the label back. Restore `inbox` is a cross-folder move, so in step 1 it is refused with `DIFFERENT_DISKS` when the two folders are on different volumes (`primitives.same_disk`).
- Produces, in `guards.py`: `check_connected(paths: ArchivePaths, *rels: str) -> None`, which raises `GuardError` with the offline-op message for the first rel whose folder is not connected. The planner calls it for every op's src and dst. Undo calls it for every op it reverses.
- Cross-disk moves keep today's `OpFailed(DIFFERENT_DISKS)`, raised from the dry run: the planner checks `primitives.same_disk` on the two folders' roots when src and dst labels differ.

- [ ] **Step 1: Write the failing tests:**
  - `test_quarantine_in_extra_folder_stays_on_its_disk`: the path is as above, the folder is created on demand, and the batch is journaled
  - `test_restore_original_in_extra_folder`
  - `test_to_delete_waiting_lists_all_folders`: `waiting_in_to_delete` returns entries from both To Delete folders
  - `test_move_refused_while_folder_offline`: the dry run raises the offline-op message, and nothing changes on disk
  - `test_undo_waits_for_folder`: undo of a batch under `Old years` while it is offline raises the same message
  - `test_cross_disk_move_refused_in_dry_run`: patch `primitives.same_disk` to return False, and the dry run reports `DIFFERENT_DISKS`
- [ ] **Step 2: Run** `uv run pytest tests/test_folder_to_delete.py tests/test_restore.py tests/test_ops_undo.py tests/test_move.py -q`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** the helpers, then replace each call site under Files. Grep `quarantine` across `backend/src/dam` afterwards: every remaining use of the plain `paths.quarantine` must mean the main folder on purpose.
- [ ] **Step 4: Run** the same tests, then the full suite. Expected: PASS, with `test_no_delete.py` unchanged and passing.
- [ ] **Step 5: Commit** `feat: give each archive folder its own To Delete and refuse changes to an unplugged folder`.

### Task 7: Publisher, Maintenance and search

**Files:**
- Modify: `backend/src/dam/maintenance/checks.py` (`BrokenLink`, `broken_links`, new `label_clashes` check), `backend/src/dam/maintenance/service.py` (register it)
- Modify: `backend/src/dam/collections/ongoing.py` (only if the sync test below fails)
- Modify: `backend/src/dam/query.py` (`IS_VALUES`), `backend/src/dam/search.py` (`SearchContext`, `_add_is`)
- Modify: `frontend/src/searchFilters.ts` (`IS_VALUES` and help text), `frontend/src/screens/Maintenance.tsx` (link reason, clash card)
- Test: `backend/tests/test_maintenance.py`, `backend/tests/test_ongoing.py`, `backend/tests/test_search_filters.py`, `frontend/src/searchFilters.test.ts`, `frontend/src/screens/Maintenance.test.tsx`

**Interfaces:**
- Produces: `BrokenLink.reason: Literal["broken", "folder_not_connected", "folder_detached"]`. A link whose target lies in an offline extra is listed with `folder_not_connected`. A link whose target lies under a detached entry's path is listed with `folder_detached`. Maintenance shows `Folder not connected` / `Folder detached` instead of `Missing`.
- Produces: `label_clashes(ctx, repo, paths, engine) -> LabelClashes` (`items: list[str]`, `total: int`), with the card text `A folder in the main folder has the same name as the archive folder '{label}'. Rename it or the archive folder.`
- Produces: `SearchContext.disconnected: tuple[str, ...]`, filled from `paths.disconnected_labels()` by the caller. `is:disconnected` adds `_under_any(w, list(ctx.disconnected))`, or a false condition when the tuple is empty. Help text: `disconnected (files in an archive folder that is not connected now)`.

- [ ] **Step 1: Write the failing tests:**
  - `test_ongoing_sync_plans_nothing_for_offline_folder`: a collection member in `Old years` is published, the extra root is renamed away, and `sync(dry_run=True)` returns no operations
  - `test_broken_link_reason_offline` and `test_broken_link_reason_detached`
  - `test_label_clash_check`
  - `test_is_disconnected` and `test_not_is_disconnected`, plus `in:"Old years" is:disconnected` combined
  - frontend: `IS_VALUES` contains `"disconnected"`, and Maintenance renders `Folder not connected` for that reason
- [ ] **Step 2: Run** `uv run pytest tests/test_maintenance.py tests/test_ongoing.py tests/test_search_filters.py -q` and `cd frontend && npm test -- --run searchFilters Maintenance`. Expected: FAIL.
- [ ] **Step 3: Implement** as described above.
- [ ] **Step 4: Run** the same tests, then both full suites. Expected: PASS.
- [ ] **Step 5: Commit** `feat: Maintenance and search know about unplugged and detached archive folders`.

### Task 8: API and app reopen

**Files:**
- Create: `backend/src/dam/api/routers/folders.py`, registered in `api/main.py`
- Modify: `backend/src/dam/api/schemas.py` (`FileRecordOut` and collection member out models get `folder: str | None`, `connected: bool`, plus new folder models), `backend/src/dam/api/marks.py` (fill them)
- Modify: `backend/src/dam/serve.py` (new `reopen()`), `backend/src/dam/services/archives.py` (`Switcher` protocol gets `reopen`)
- Modify: `frontend/src/api/schema.d.ts` (regenerated)
- Test: `backend/tests/test_api_folders.py` (new), `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `archive_folders.add_folder/detach_folder/attach_folder/check_*` (Task 3), `ArchivePaths.label_of`, `disconnected_labels` (Task 1).
- Produces, endpoints:
  - `GET /api/archive-folders`, returning `ArchiveFoldersOut { folders: [ArchiveFolderOut { label: str | null, path: str, attached: bool, connected: bool, files: int }] }` (main first, `label: null`)
  - `POST /api/archive-folders` with `{label, path, dry_run}`, returning `FolderChangeOut { label, path, files, restart_needed: bool }`
  - `POST /api/archive-folders/{label}/detach` with `{forget: bool, dry_run}`, returning `FolderChangeOut`
  - `POST /api/archive-folders/{label}/attach` with `{dry_run}`, returning `FolderChangeOut`
  - Check failures answer 400 with the message from Task 3.
- Produces: `Server.reopen() -> None`, which opens a fresh `App` for the current profile, swaps it in and restarts background work like `switch()`. It reuses the held `ServeLock` instead of acquiring a new one, and rolls back the same way on failure. When the server cannot reopen (no `Server`, as in the CLI), endpoints return `restart_needed: true`.
- Produces: in `api/marks.py`, one helper `_place(app, rows)` computes `disconnected_labels()` once per response and sets `folder = label_of(path) or None` and `connected = folder not in disconnected` on every record dict. `with_marks`, `with_record_marks` and `collections_out` call it.

- [ ] **Step 1: Write the failing tests:** an add round trip (GET shows the folder, a Browse root listing includes `Old years` with `folder == "Old years"`, `connected == true`), each 400 refusal, detach then attach, `dry_run` writing nothing, and a search result for a file in an offline folder carrying `connected == false`.
- [ ] **Step 2: Run** `uv run pytest tests/test_api_folders.py tests/test_api.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the endpoints, `reopen()` and `_place`. Then run `cd frontend && npm run gen:api`.
- [ ] **Step 4: Run** the backend suite, then `cd frontend && npm run build`. Expected: PASS, with the regenerated schema type-checking.
- [ ] **Step 5: Commit** `feat: API for archive folders, with folder and connected on every file record`.

### Task 9: Frontend: Settings card, Browse and file view

**Files:**
- Create: `frontend/src/components/ArchiveFoldersSettings.tsx` (+ `.test.tsx`)
- Modify: `frontend/src/screens/Settings.tsx` (section `{ id: "folders", label: "Archive folders", scope: "archive" }`, before Indexing)
- Modify: `frontend/src/components/FolderBrowser.tsx`, `frontend/src/screens/FilePanel.tsx` / `Viewer.tsx`
- Test: `frontend/src/screens/Settings.test.tsx`, `frontend/src/components/FolderBrowser.test.tsx`, `frontend/src/screens/Viewer.test.tsx`

**Interfaces:**
- Consumes: the endpoints and record fields from Task 8.
- The card lists the main folder (`Main folder`, path, no actions), then each extra with label, path and a status of `Connected`, `Not connected` or `Detached`. Each extra has **Detach** (confirm dialog: `Detach '{label}'? Its {files} files leave the archive until you attach it again. Nothing on the disk changes.`, with a checkbox `Also forget their tags, notes and collection places`) or **Attach again**. **Add folder** asks for the label and path, shows the dry-run result (the file count after scanning comes later, so the dialog says `dam will index it in the background.`), then applies. When the response has `restart_needed`, it shows the existing restart notice.
- Browse: a root row with `folder !== null` uses a drive icon. When `connected` is false it shows `Not connected`, and opening it shows `'{label}' is not connected. Connect the disk or sign in to the cloud drive, and it comes back by itself.`
- File view: when `connected` is false, the preview area shows the same sentence, and the open and reveal actions are disabled.

- [ ] **Step 1: Write the failing tests** for each behaviour above, using the existing mocked API client.
- [ ] **Step 2: Run** `cd frontend && npm test -- --run ArchiveFoldersSettings Settings FolderBrowser Viewer`. Expected: FAIL.
- [ ] **Step 3: Implement** as described above, following the existing settings sections and icon set.
- [ ] **Step 4: Run** `npm test -- --run && npm run build`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: Settings card for archive folders and not-connected states in Browse and the file view`.

### Task 10: Docs, changelog and the full check

**Files:**
- Modify: `CHANGELOG.md`, `docs/guide.md` (new section "Several archive folders"), `docs/reference.md` (settings key `extra_folders`, the four endpoints, `is:disconnected`, "Safety model in detail": To Delete per folder, "Cloud drives": per folder)
- Modify: `docs/superpowers/specs/2026-10-26-multiple-archive-folders-design.md` (status line: step 1 built)

- [ ] **Step 1: Write** the entries. The changelog under `### Added` reads, in plain words: one archive can now span several folders, an unplugged disk keeps its files in the index, and each folder has its own To Delete.
- [ ] **Step 2: Run the full check:** `cd backend && uv run ruff check . && uv run pytest -q -W error`, then `cd frontend && npm test -- --run && npm run build`. Expected: all pass.
- [ ] **Step 3: Try it on a demo archive** (never a real one): `uv run python -m dam.demo /tmp/dam-demo`, add a second temp folder as an extra folder in Settings, rename it away, and confirm Browse shows `Not connected` and `is:disconnected` finds its files. Take screenshots with no personal documents.
- [ ] **Step 4: Commit** `docs: guide and reference for several archive folders`.
