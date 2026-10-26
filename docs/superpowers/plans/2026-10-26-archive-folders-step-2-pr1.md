# Archive folders step 2, PR 1 (copy across for files, relabel) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move files between archive folders on different disks as a verified copy plus a move of the original to To Delete, run as a background job, and let the owner change an extra folder's label.

**Architecture:** A new op kind `COPY_ACROSS` that the planner emits (only for plans with `Plan.copy_across`) in place of the different-disks refusal, each followed by an ordinary QUARANTINE of the original; the executor copies under a temporary name, verifies, re-points the index row; undo reuses QUARANTINE and MOVE inverses. A copy job runner reuses the maintenance job pattern. Relabel is a database plus config rewrite run with the archive closed.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy core on SQLite, PyYAML; React + TypeScript, TanStack Query, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-26-archive-folders-step-2-design.md` (builds on `2026-10-26-multiple-archive-folders-design.md`).

## Global Constraints

- CONTRIBUTING safety rules: never delete user files; only `dam/ops` writes to the archive; every change previewed, journaled, undoable; `backend/tests/test_no_delete.py` untouched.
- Tests use temporary fake archives only (`fake_archive`, `extra_folder` fixtures); cross-disk is simulated by `monkeypatch.setattr(primitives, "same_disk", lambda a, b: False)`.
- Every text-mode open/read_text/write_text has `encoding="utf-8"`.
- Cross-platform: `pathlib`, no shell commands; `SF_DATALESS` only where `st_flags` exists.
- Temporary copy name: `.dam-copy-<8 hex>-<name>` in the destination folder.
- Copy across has no size cap (`limit=None`), only the free-space check with `_COPY_FREE_MARGIN`.
- Copy jobs do not end when nobody polls; one copy job at a time (second start is 409).
- Before calling done: `uv run ruff check . && uv run pytest -q -W error` in `backend/`, `npm test -- --run && npm run build` in `frontend/`, `npm run gen:api` after API changes.
- Published text (CHANGELOG, docs, commit and PR text): no em or en dashes as punctuation.
- PR #83 (open, touches `core/paths.py`, `index/repo.py`, `archive_folders.py`, `serve.py`, `ArchiveFoldersSettings.tsx`): merge `origin/main` once it lands, before Task 7.

## Review Focus

1. A source edited between preview and act (same size): the re-hash refuses, the batch stops, nothing moves. (Task 4 test `test_source_changed_after_preview_stops`.)
2. A name taken at the destination since the preview: the temporary copy is not renamed over it; op fails, temp file named. (Task 1 test `test_final_name_taken_keeps_temp`.)
3. A copy-across move of several files where one is locked: refused in the dry run with every locked name, nothing copied. (Task 3 test `test_locked_file_refuses_copy_across`.)
4. Relabel where a rule file has a `folder:` value in a flow mapping on one line with other keys: only that value changes. (Task 7 test `test_flow_mapping_value_edited_in_place`.)
5. Undo of a copy-across batch while the destination folder is unplugged: refused with the not-connected message, nothing moves. (Task 5 test `test_undo_waits_for_destination`.)

---

### Task 1: Copy primitives

**Files:**
- Modify: `backend/src/dam/ops/primitives.py` (`copy_file`, `copy_picture`, new `copy_across`, `is_dataless`)
- Modify: `backend/src/dam/ops/executor.py` (callers of `copy_picture`)
- Test: `backend/tests/test_copy_across_primitives.py`

**Interfaces:**
- Produces:
  - `copy_file(src: Path, dst: Path, limit: int | None = MAX_COPY_BYTES, stop: Callable[[], bool] | None = None) -> int`; `limit=None` = no cap; `stop()` true between chunks raises `OpFailed` naming the incomplete `dst`.
  - `copy_verified(src: Path, dst: Path, sha256: str, limit: int | None = MAX_COPY_BYTES, stop=None) -> None` (today's `copy_picture` body; `copy_picture = copy_verified` kept as alias).
  - `TEMP_COPY_PREFIX = ".dam-copy-"`; `copy_across(src: Path, dst: Path, sha256: str, stop=None) -> None`: copy to `dst.parent / f"{TEMP_COPY_PREFIX}{secrets.token_hex(4)}-{dst.name}"` via `copy_verified(limit=None)`, `os.utime(temp, ns=(st.st_atime_ns, st.st_mtime_ns))` from the source, then `rename_excl(temp, dst)`. Any failure raises `OpFailed` whose text names the temp file; nothing is removed.
  - `is_dataless(path: Path) -> bool` (move `_is_dataless` from `collections/export.py` here, import it there).

- [ ] **Step 1: Write failing tests** in `test_copy_across_primitives.py`: `test_copy_across_copies_and_keeps_mtime` (content equal, `dst.stat().st_mtime_ns == src.stat().st_mtime_ns`, source still there, no `.dam-copy-*` left); `test_copy_across_no_size_cap` (monkeypatch `MAX_COPY_BYTES` to 1, copy 10 bytes succeeds); `test_copy_across_hash_mismatch_refuses` (wrong sha256 → `OpFailed`, `dst` absent); `test_final_name_taken_keeps_temp` (create `dst` first → `OpFailed` mentions `.dam-copy-`, `dst` content unchanged, one temp file present); `test_copy_file_stop_between_chunks` (`stop=lambda: True` with a 3 MB file → `OpFailed`, partial temp stays).
- [ ] **Step 2:** `cd backend && uv run pytest tests/test_copy_across_primitives.py -q` → FAIL (import errors).
- [ ] **Step 3:** Implement the interfaces above; update `executor.py` to call `copy_verified`.
- [ ] **Step 4:** Run the test file and `tests/test_picture_quarantine.py` → PASS.
- [ ] **Step 5:** Commit `feat: verified copy primitive for moves across disks`.

### Task 2: Rekey carries everything keyed by drive id

**Files:**
- Modify: `backend/src/dam/index/repo.py` (`FileRepo.rekey`)
- Test: `backend/tests/test_rekey.py`

**Interfaces:**
- Produces: `FileRepo.rekey(old_id: str, new_id: str) -> None` now also updates every table with a file drive id: `notes.target_id` and `checklist_items.target_id` where `target_kind == "file"`, `collection_members`, `member_link_names`, `item_files`, `file_locks`, `file_assignments`, `file_summaries`, `file_fields`, `rule_outcomes`, and any other `drive_id` column found in `db/tables.py` (grep `"drive_id"`; `ai_calls.files` is JSON, leave it).

- [ ] **Step 1:** `test_rekey_keeps_notes_collections_items_locks`: index a file, add a tag, a note, a collection membership, a tray item, a lock (through the services, as existing tests do), `repo.rekey("local:a", "drv-1")`, assert each is found under `drv-1` and nothing under the old id. `test_scanner_rekey_keeps_note`: a file scanned without xattr gets a note; set the Drive xattr helper the fake archive offers (`FakeArchive.add(..., drive_id=...)` writes it; check `conftest.py`), rescan, note still on the file.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Extend `rekey` (same transaction, `PRAGMA defer_foreign_keys = ON` already set).
- [ ] **Step 4:** Run the test and `tests/test_scanner*.py` → PASS.
- [ ] **Step 5:** Commit `fix: keep notes, collections and tray items when a file gets its Drive id`.

### Task 3: Op kind and planner expansion

**Files:**
- Modify: `backend/src/dam/ops/model.py` (`OpKind.COPY_ACROSS`, `Plan.copy_across: bool = False`, `ResolvedOp.size: int | None = None`, `ResolvedOp.cloud_only: bool = False`, docstrings)
- Modify: `backend/src/dam/ops/planner.py` (`_relocate`, `_check_same_disk`, new `_copy_across`, free-space check)
- Modify: `backend/src/dam/ops/primitives.py` (drop `different_disks_message`'s "yet")
- Modify: `backend/src/dam/ops/guards.py` only if `validate` rejects the new kind
- Test: `backend/tests/test_copy_across_plan.py`; update `tests/test_move.py::test_cross_disk_move_refused_in_dry_run`, `tests/test_restore.py::test_restore_to_inbox_from_extra_folder_needs_one_disk`

**Interfaces:**
- Consumes: `primitives.is_dataless` (Task 1).
- Produces: in a plan with `copy_across=True`, a MOVE of a **file** across disks resolves to `[MKDIR…], ResolvedOp(COPY_ACROSS, src, dst, drive_id, note, size=…, cloud_only=…)`, then `ResolvedOp(QUARANTINE, src, <own To Delete path>, drive_id, note="copied to <dst>")`. When `src` is already quarantined (restore), only the COPY_ACROSS, with note `"the original stays in To Delete"`. Without `copy_across` (or for a folder, or under undo `restore=True`), the existing `OpFailed(different_disks_message(a, b))`. New message `different_disks_message`: `"<first> and <second> are on different disks, so this cannot be moved between them here."` Protected source: `GuardError(f"{name} is protected, so it is not copied across disks.")`. Free space: sum of `size` per destination folder root vs `shutil.disk_usage(root).free - _COPY_FREE_MARGIN` → `OpFailed("There is not enough free space on <label or the main folder> for these files (<n> MB needed).")`.
- Simulation: COPY_ACROSS appends `("create", dst, "file")`; the QUARANTINE goes through `_relocate` as today (so `_N` and aliases work).

- [ ] **Step 1:** Tests: `test_file_move_across_disks_plans_copy_and_quarantine` (ops kinds `[mkdir, copy_across, quarantine]`, dsts `Old years/2010`, `Old years/2010/a.pdf`, `##. To Delete/<path>`; note); `test_taken_name_gets_suffix`; `test_restore_across_disks_plans_copy_only`; `test_plain_plan_still_refused` (no `copy_across` → old refusal with new wording); `test_folder_move_across_disks_refused` (restore of a quarantined folder across disks → `OpFailed` different disks); `test_protected_file_refused`; `test_not_enough_space_refused` (monkeypatch `shutil.disk_usage`); `test_locked_file_refuses_copy_across`; `test_same_disk_stays_a_move` (no monkeypatch → plain MOVE). Use `app.executor.preview(Plan([...], origin="ui", copy_across=True))` directly.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. In `_relocate`, for `op.kind is MOVE` call `_check_same_disk` returning `bool` (False = different disks) and branch to `_copy_across(op, folder)` when `self._copy_across_plan and kind == "file"`; set `self._copy_across_plan = plan.copy_across and not restore` in `resolve`. Size from `os.lstat`, `cloud_only` from `is_dataless`.
- [ ] **Step 4:** Run the new file, `test_move.py`, `test_restore.py` (updated wording) → PASS.
- [ ] **Step 5:** Commit `feat: plan moves across disks as a verified copy and a move to To Delete`.

### Task 4: Executor runs COPY_ACROSS

**Files:**
- Modify: `backend/src/dam/ops/executor.py` (`_snapshot`, `_precheck`, `_act`, `_verify`, `_run_op` index step, `_run_resolved(…, should_stop=None, progress=None)`, `apply(…, should_stop=None, progress=None)`)
- Modify: `backend/src/dam/ops/undo.py` (`RELOCATE` stays; add `COPY_ACROSS` to `_check_unchanged`'s hash branch only in Task 5)
- Modify: `backend/src/dam/index/scanner.py` (skip names starting with `TEMP_COPY_PREFIX`)
- Test: `backend/tests/test_copy_across.py`

**Interfaces:**
- Consumes: `primitives.copy_across` (Task 1), `FileRepo.rekey` (Task 2), the resolved ops of Task 3.
- Produces:
  - `Executor.apply(plan, dry_run=False, check=None, should_stop: Callable[[], bool] | None = None, progress: Callable[[ResolvedOp, int, int], None] | None = None)`. `should_stop` is checked before each op, except directly after a COPY_ACROSS whose QUARANTINE follows (the pair finishes). `progress(rop, index, total)` after each op. `BatchResult.stopped: bool = False` set when it stopped early.
  - `Executor.cancel_copies: threading.Event`: set by `App.close`; passed as `stop=` to `copy_across` so a copy in progress ends at a chunk boundary.
  - Index step for COPY_ACROSS: new id = `read_drive_id(copy)` if set, else `f"local:{uuid4()}"` if the old id does not start with `"local:"`, else unchanged; `rekey` when it changes, then `update_path(src, dst)`.
  - Snapshot of COPY_ACROSS: `content_hash = file_sha256(src)`, `drive_id` = source's (journaled for undo).

- [ ] **Step 1:** Tests (cross-disk monkeypatched, Drive ids via `FakeArchive.add(..., drive_id=...)`): `test_file_moves_across_with_tags_and_note` (tag, note, collection follow; original in `##. To Delete/...`; copy content and mtime; journal rows `copy_across` then `quarantine`, both `done`); `test_drive_id_source_gets_local_id`; `test_local_id_kept`; `test_scan_after_move_gives_original_a_new_row` (rescan: copy keeps tags, To Delete original is a separate untagged row); `test_source_changed_after_preview_stops` (preview, rewrite source same size, apply the same resolved plan via `apply(check=…)` → failed, nothing in To Delete); `test_stop_finishes_pair` (two files, `should_stop` true after first op → first file fully moved, second untouched, `result.stopped`); `test_cancel_mid_copy_leaves_temp` (set `cancel_copies` → failed, temp named in error, source in place).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement. Precheck: as a move's (source plain file, drive id, dst free, parent a real folder). Verify: `dst` regular, size and `file_sha256` equal the journaled hash, source still exists.
- [ ] **Step 4:** Run the file and `tests/test_move.py tests/test_executor*.py` → PASS.
- [ ] **Step 5:** Commit `feat: copy files across disks with verification and index re-pointing`.

### Task 5: Undo and recovery of COPY_ACROSS

**Files:**
- Modify: `backend/src/dam/ops/undo.py` (`_inverse`, `_check_unchanged`, `mark_reverted`, `_happened`, recover index step)
- Modify: `backend/src/dam/ops/executor.py` (index step after the inverse QUARANTINE of a copy)
- Modify: `backend/src/dam/ops/model.py` (`ResolvedOp.restore_row: tuple[str, str] | None = None`: `(original path, original drive id)` set on the inverse QUARANTINE by undo)
- Modify: the maintenance check that lists odd names (`backend/src/dam/maintenance/`, the `names` kind): a `.dam-copy-*` file is listed as "an unfinished copy left by a move across disks; remove it when the move is done"
- Test: `backend/tests/test_copy_across_undo.py`, the names check's test file (`test_leftover_temp_copy_listed`)

**Interfaces:**
- Consumes: Tasks 3–4; `FileRepo.forget_rows(ids)` from PR #83 if merged, else a local `_delete_rows` call through a new `FileRepo.forget_rows` with the same signature (reconcile at the merge).
- Produces: inverse of COPY_ACROSS = `Op(QUARANTINE, row.dst, None)`; the planner's resolved op gets `restore_row=(row.src, row.drive_id)` (undo sets it after resolve by matching src). After it completes, the executor: forgets any row at `row.src` or with id `row.drive_id` that is not the moved row, then `update_path(<copy in To Delete>, row.src)` and `rekey(current_id, row.drive_id)`. `_check_unchanged`: COPY_ACROSS like COPY (regular file, size, hash). `mark_reverted`: QUARANTINE whose src equals a COPY_ACROSS row's dst reverts it. Recovery `_happened(COPY_ACROSS)`: dst missing → False; dst regular with journaled size and hash and src present → True (then the index step runs); else None.

- [ ] **Step 1:** Tests: `test_undo_puts_original_back_with_tags` (tags, note on the original path, original Drive id, copy in `Old years/##. To Delete/...`, journal rows `undone`); `test_undo_after_scan_keeps_tagged_row`; `test_undo_of_stopped_batch`; `test_undo_waits_for_destination` (rename the extra root away → not-connected `GuardError`); `test_undo_refused_when_copy_changed`; `test_recover_planned_copy_across` (three states: nothing copied → interrupted; full copy with source → done and index re-pointed; only temp file → needs manual check, files untouched).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the file, `tests/test_undo*.py tests/test_recover*.py tests/test_no_delete.py` → PASS.
- [ ] **Step 5:** Commit `feat: undo and recover moves across disks`.

### Task 6: Copy job, services and API

**Files:**
- Create: `backend/src/dam/ops/jobs.py` (`CopyJobs`)
- Modify: `backend/src/dam/maintenance/jobs.py` (`Job` gets `abandon: bool = True`; `should_stop` honours it)
- Modify: `backend/src/dam/services/browse.py` (`move` and `restore` set `copy_across=True`; a resolved plan with COPY_ACROSS starts a job instead of applying; `check_disk_identity` call accepts COPY_ACROSS as the move kind)
- Modify: `backend/src/dam/app.py` (`self.copy_jobs`, `jobs_running`, `close` sets `executor.cancel_copies` then closes copy jobs)
- Modify: `backend/src/dam/api/schemas.py`, `backend/src/dam/api/routers/browse.py`
- Test: `backend/tests/test_copy_jobs.py`, `backend/tests/test_api_copy_across.py`

**Interfaces:**
- Consumes: `Executor.apply(…, should_stop, progress)` (Task 4).
- Produces:
  - `CopyJobs.start(work: Callable[[JobContext], BatchResult]) -> Job` (kind `"copy_across"`, `abandon=False`; `Conflict("A move across disks is running. Wait for it to finish or stop it.")` when one runs), `get(job_id)`, `latest()`, `running()`, `close()` (stop, join 2 s).
  - `MoveResult` and the restore `BatchResult` gain `job_id: str | None = None`; when set, `done` is empty and the batch runs in the job. Job progress: `done`/`total` = files, `bytes_done`/`bytes_total` from `ResolvedOp.size`, `current` = file name.
  - API: `ResolvedOpOut` adds `size: int | None = None`, `cloud_only: bool = False`; `MoveResultOut`/`BatchResultOut` add `job_id: str | None = None`; new `CopyJobOut` (MaintenanceJobOut's progress fields plus `result: MoveResultOut | None`); routes `GET /api/browse/move/jobs/latest` (null when none), `GET /api/browse/move/jobs/{job_id}` (404 unknown), `POST /api/browse/move/jobs/{job_id}/stop`.
  - A copy job's result text when stopped: `BatchResult.error = f"Stopped: {n} of {total} files moved."`.

- [ ] **Step 1:** Tests: `test_job_not_abandoned` (monkeypatch `ABANDONED_S` to 0, job runs to the end); `test_second_job_conflicts`; `test_move_across_starts_job_and_finishes` (service level, join the job, files moved, result batch id undoable via `app.executor.undo`); `test_move_preview_reports_size_and_cloud_only`; `test_api_move_returns_job_and_polls` (TestClient as in `tests/test_api.py`: POST move → `job_id`, GET until `state == "done"`, POST stop on a finished job is harmless); `test_jobs_running_blocks_detach` (409 from `/api/archive-folders/{label}/detach` while a job runs, using a `should_stop`-blocking work function).
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the two files, `tests/test_api*.py tests/test_browse*.py tests/test_restore.py` → PASS.
- [ ] **Step 5:** Commit `feat: run moves across disks as a background job with progress and Stop`.

### Task 7: Relabel

Merge `origin/main` first (PR #83). Then:

**Files:**
- Create: `backend/src/dam/relabel.py` (plan and apply)
- Create: `backend/src/dam/core/yamledit.py` (value edits in place)
- Modify: `backend/src/dam/archive_folders.py` (`relabel_folder`), `backend/src/dam/api/routers/folders.py`, `backend/src/dam/api/schemas.py`, `backend/src/dam/serve.py` only if `close_and_reopen` needs a hook
- Modify: `backend/src/dam/cli/main.py` (`dam folders relabel OLD NEW [--dry-run]`, if a `folders` command group exists; else skip)
- Test: `backend/tests/test_yamledit.py`, `backend/tests/test_relabel.py`, `backend/tests/test_api_folders.py`

**Interfaces:**
- Produces:
  - `yamledit.replace_values(text: str, change: Callable[[tuple[str | int, ...], str], str | None]) -> tuple[str, list[int]]`: walk `yaml.compose(text)`; for each plain or quoted single-line scalar (style `None`, `'"'`, `"'"`) whose path (keys and list indices) the callback answers with a new value, replace exactly `node.start_mark.index:node.end_mark.index` with the new value in the same quoting style (escape for that style); returns the new text and the changed 1-based lines. Raises `YamlEditError(f"{line}: …")` for a matching folded/literal/multi-line scalar or an alias.
  - `relabel.plan(app_paths: AppPaths, engine: Engine, old: str, new: str) -> RelabelPlan` (dataclass: `old`, `new`, `counts: dict[str, int]` keyed `files`, `operations`, `made_folders`, `maintenance_ignored`; `files_changed: list[FileChange(path: Path, lines: list[int], text: str)]`; `settings_text: str`; `warnings: list[str]`). Matching: first component folds (NFC, casefold) to `old`, then the rest kept; rewritten to `new` + rest. Rule keys `folder`, `folder_is`; tray keys found in `trays/model.py` that hold a folder. Settings keys `extra_folders` (label), `protected_paths`, `ai.exclude_folders` (through `settings_write.with_keys`).
  - `relabel.apply(app_paths, engine, plan) -> None`: snapshot via `snapshots.create_snapshot(..., note=f"Before changing label '{old}' to '{new}'")` (check its signature), DB transaction, settings write, config files (each through `write_config_file` with a verify that reloads and compares), on a failure after the DB step the inverse DB rewrite and `.bak` restore, then raise.
  - `archive_folders.relabel_folder(app_paths, engine, label, new_label, dry_run) -> RelabelChange` using `check_label(new, …)` with the folder's own old label not counting as taken; refuses `planned` journal rows ("An operation was interrupted. Run dam recover first.").
  - `POST /api/archive-folders/{label}/relabel` body `ArchiveFolderRelabelIn {label: str, dry_run: bool = False}` → `RelabelOut {label, new_label, counts, files: [{name, lines}], warnings, restart_needed}`; applied inside `Host.close_and_reopen`; 409 when `jobs_running`.

- [ ] **Step 1:** `test_yamledit.py`: `test_plain_value_replaced_comments_kept`, `test_quoted_value_keeps_quotes`, `test_flow_mapping_value_edited_in_place`, `test_folded_scalar_refused_with_line`, `test_alias_refused`. `test_relabel.py`: `test_rewrites_index_journal_settings_rules` (index rows, FTS search for the new path, an old batch under the label still undoable after relabel, protected path and ai exclude rewritten, rule file comments intact); `test_case_only_change`; `test_detached_folder`; `test_settings_failure_rolls_db_back` (monkeypatch `settings_write.write_keys` to raise → files rows still under old label, rule file unchanged); `test_refused_when_planned_row`; `test_hidden_main_entry_warned`; `test_template_with_placeholder_first_left_alone`. API: `test_relabel_dry_run_and_apply`, `test_relabel_409_while_job_runs`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the three files and `tests/test_archive_folders.py tests/test_snapshots*.py` → PASS.
- [ ] **Step 5:** Commit `feat: change an archive folder's label, rewriting every stored path under it`.

### Task 8: Frontend

**Files:**
- Modify: `frontend/src/api/schema.d.ts` (`npm run gen:api`), `frontend/src/api/client.ts` (`useCopyJob(jobId)` polling every 1 s while running, `useStopCopyJob`, `useLatestCopyJob`, `useRelabelFolder`)
- Modify: `frontend/src/components/PlanPreview.tsx` (summary above the list when any op is `copy_across`: "Copies N files (X MB) to <folder>. The originals go to To Delete in <source>." plus "N are in the cloud only and are downloaded first."; confirm label "Copy and move")
- Create: `frontend/src/components/CopyJobProgress.tsx` (dialog: files, bytes, current name, Stop; closable; small line in Browse while running; toast with Undo at the end)
- Modify: `frontend/src/screens/Browse.tsx` / `frontend/src/components/MoveTo.tsx` / `frontend/src/components/Restore.tsx` (a result with `job_id` opens the progress dialog)
- Modify: `frontend/src/components/ArchiveFoldersSettings.tsx` (Change label: input, dry run summary, apply)
- Test: `frontend/src/components/CopyJobProgress.test.tsx`, `frontend/src/components/PlanPreview.test.tsx`, `frontend/src/components/ArchiveFoldersSettings.test.tsx`

**Interfaces:**
- Consumes: Task 6 and 7 endpoints.

- [ ] **Step 1:** Tests: preview summary text and button label; progress dialog shows `3 of 10 files` and Stop posts to `/stop`; a finished job shows the toast with Undo; Change label shows the dry run counts then applies.
- [ ] **Step 2:** `cd frontend && npm test -- --run` → new tests FAIL.
- [ ] **Step 3:** Implement following the existing dialogs' patterns (`Restore.tsx`, `SnapshotSettings.tsx`).
- [ ] **Step 4:** `npm test -- --run && npm run build` → PASS.
- [ ] **Step 5:** Commit `feat: show moves across disks with progress, and change a folder's label in Settings`.

### Task 9: Docs and full check

**Files:**
- Modify: `CHANGELOG.md` (Unreleased: Added copy across, Added change label, Fixed rekey), `docs/guide.md` ("Moving between folders", "Changing a label"), `docs/reference.md` (op kind `copy_across`, job endpoints, relabel endpoint, safety model sentence), spec status lines.

- [ ] **Step 1:** Write the docs (no em or en dashes).
- [ ] **Step 2:** Full check from Global Constraints → all pass.
- [ ] **Step 3:** Run the app on the demo archive with a second temp folder as an extra folder (`uv run python -m dam.demo <scratch>/demo`, `--data-dir <scratch>/demo/data`), confirm the Settings card and a same-disk preview still work in the browser.
- [ ] **Step 4:** Commit `docs: copy across and changing a label`, push, open the PR.
