# Folder moves Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move a whole folder in Browse, on one disk (one rename) and across disks (a verified copy of every file, then one move of the source folder to To Delete), with Stop, merge on a second move, and Undo.

**Architecture:** Browse accepts one folder row per move. On one disk the existing MOVE handles it. Across disks the planner expands the MOVE into made MKDIRs, one COPY_ACROSS per file (or a `present` check for a file already there), and one final QUARANTINE of the source that carries the planned tree and the destination (`copied_to`, journaled). The executor checks the tree before that QUARANTINE and moves the folder rows to the destination after it; undo and recovery mirror both.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy Core, Alembic, pytest; React + TypeScript, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-26-folder-moves-design.md` (read with `2026-10-26-archive-folders-step-2-design.md` "Part 1").

## Global Constraints

- CONTRIBUTING safety rules: nothing deleted; only `dam/ops` writes to the archive; every change previewed, journaled, undoable; `backend/tests/test_no_delete.py` untouched.
- Tests use fake archives only; cross-disk is simulated by patching `primitives.same_disk` (see `tests/test_copy_across.py` for the fixture pattern).
- Text IO with `encoding="utf-8"` (`tests/test_encoding.py`).
- Migration `backend/migrations/versions/0036_operation_copied_to.py`, `revision = "0036"`, `down_revision = "0035"`.
- One folder per move; folders and files never mixed in one request; Link and Copy refuse folders.
- One disk, taken name: `_2` (`2009_2`). Across disks, existing folder: merge.
- `.DS_Store` is not copied; a `.dam-copy-*` entry inside the source refuses the move; links inside are not copied; a protected entry inside refuses a move across disks.
- After API changes: `npm run gen:api` in `frontend/`, commit `src/api/schema.d.ts`.
- CHANGELOG entry under `## [Unreleased]`; published text without em/en dashes as punctuation.
- Full check before done: `uv run ruff check . && uv run pytest -q -W error` (backend), `npm test -- --run && npm run build` (frontend).

## Review Focus

1. A folder of thousands of files: the preview response and `PlanPreview` must stay usable (the op list is long; the summary carries the meaning). Test in Task 6: 300 files render with the summary and no crash.
2. Stop during the last file, then a second move: no `_2` copies, source to To Delete. Test in Task 3 (`test_second_move_after_stop_merges`).
3. A file added to the source after its sibling copies, while the job runs: never swept into To Delete uncopied. Test in Task 3 (`test_file_added_during_job_stops_before_quarantine`).
4. Undo after the scanner indexed the destination folders and the originals in To Delete: the owner's folder row (with its collection) survives in the right place. Test in Task 4 (`test_undo_after_scan_keeps_folder_collection`).
5. Relabel after a folder move across disks: the batch stays undoable (`copied_to` rewritten). Test in Task 4 (`test_relabel_rewrites_copied_to`).

---

### Task 1: Folder moves on one disk (service and identity)

**Files:**
- Modify: `backend/src/dam/services/browse.py` (`_move_ops`, `_move_label`, `_drop`)
- Modify: `backend/src/dam/services/__init__.py` (`check_disk_identity`)
- Test: `backend/tests/test_folder_move.py` (new)

**Interfaces:**
- Produces: `BrowseService._move_ops` accepts exactly one folder row (alone) and emits `Op(OpKind.MOVE, folder_path, dest)`; `check_disk_identity` accepts a folder source when the row `is_dir`; Activity label `"Moved folder {name} to {dest label}"`.

- [ ] **Step 1: Write failing tests** in `test_folder_move.py`:
  - `test_moves_a_folder_on_one_disk`: folder `20. Home/2009` with `a.pdf` and `sub/b.pdf`, a tag on `a.pdf`, the folder in a collection; `browse.move([folder_id], "80. Misc")` → on disk `80. Misc/2009/sub/b.pdf`; `repo.get(folder_id).path == "80. Misc/2009"`; tag and collection membership intact; batch label `"Moved folder 2009 to 80. Misc"`.
  - `test_undo_puts_the_folder_back`: undo → `20. Home/2009` back, rows back.
  - `test_taken_name_gets_suffix`: `80. Misc/2009` exists → lands at `80. Misc/2009_2`, preview op note is `COLLISION_NOTE`.
  - `test_refusals` (parametrized, `InvalidRequest`): an extra folder's root; `##. Ongoing`, `##. Important`, To Delete and the inbox themselves; a folder inside Ongoing or To Delete; into itself (`20. Home/2009` → `20. Home/2009`), into its own subfolder (`→ 20. Home/2009/sub`); a folder plus a file in one request (`"Move one folder at a time, without files"`); two folders; `mode="link"` and `mode="copy"` with a folder (`"Folders can only be moved"`).
  - `test_locked_file_inside_refuses`: a locked file inside → `GuardError` with the lock message (planner).
  - `test_identity_folder_replaced`: after planning the folder is replaced by a file of that name → `InvalidRequest` "scan and try again"; a Drive-id folder whose xattr changed → refused.
- [ ] **Step 2:** `uv run pytest tests/test_folder_move.py -q` → FAIL ("folders cannot be moved yet").
- [ ] **Step 3: Implement.** In `_move_ops`, replace the `is_dir` refusal: a folder row is allowed only when `len(requested) == 1` and `name is None`; refuse the roots and special areas listed above (`paths.is_root`, `paths.folder_of(rec.path).label` with no `/` in the remainder, `self.special.*`, `paths.quarantines`, `self.special.inbox`); refuse `is_under(dest, rec.path)`. `_link_copy_ops` refuses `rec.is_dir` with `"Folders can only be moved"`. In `check_disk_identity`, when `os.lstat` gives `S_ISDIR` and the op's source is a folder row (`repo.get(drive_id).is_dir`), accept it (skip the size check); a non-folder where a folder was indexed, or a folder where a file was, refuses.
- [ ] **Step 4:** run the file again → PASS; `uv run pytest tests/test_move.py tests/test_browse*.py -q` → PASS.
- [ ] **Step 5:** commit `feat: move a folder in Browse on one disk`.

### Task 2: Planning a folder move across disks

**Files:**
- Modify: `backend/src/dam/ops/model.py` (`ResolvedOp` fields), `backend/src/dam/ops/planner.py` (`_relocate`, new `_copy_folder`), `backend/src/dam/ops/primitives.py` (constant only)
- Test: `backend/tests/test_folder_copy_plan.py` (new)

**Interfaces:**
- Consumes: Task 1's folder MOVE in a `Plan.copy_across` plan.
- Produces:
  - `ResolvedOp.method == "present"` on a COPY_ACROSS whose destination already holds a file with the source's size and mtime (`PRESENT = "present"` in `primitives`).
  - `ResolvedOp.copied_to: str | None`: on the final QUARANTINE, the destination folder path.
  - `ResolvedOp.tree: dict[str, tuple[str, int | None, float | None]] | None`: on the final QUARANTINE, folded relative path (from the source folder) → (kind `"file"|"dir"|"link"`, size, mtime) as listed when planned; `.DS_Store` excluded.
  - Op order: MKDIRs (made=True, parents first, only missing ones), then COPY_ACROSS per file in sorted tree order, then the To Delete MKDIRs (`quarantine_root`), then the final QUARANTINE. A Stop between the To Delete MKDIRs and the QUARANTINE leaves an empty To Delete folder, which PR 1 already accepts.

- [ ] **Step 1: Write failing tests** (preview only, `Executor.preview`, `same_disk` patched False):
  - `test_layout`: `A/2009/{a.pdf, sub/b.pdf, empty/}` moved to `Old years` → kinds in order `[mkdir 2009, mkdir 2009/empty, mkdir 2009/sub, copy_across a.pdf, copy_across sub/b.pdf, (mkdir To Delete …), quarantine A/2009]`; every MKDIR `made`; the QUARANTINE has `copied_to == "Old years/2009"` and a `tree` with 5 entries.
  - `test_merge_into_existing`: `Old years/2009/a.pdf` exists with the source's size and mtime, `sub` exists → no MKDIR for `2009` or `sub`; `a.pdf` op has `method == "present"` and `dst == "Old years/2009/a.pdf"`; a same-name file with another size gets `a_2.pdf` and `COLLISION_NOTE`.
  - `test_ds_store_not_copied`, `test_dam_copy_leftover_refuses` (`GuardError` "Remove the unfinished copy .dam-copy-x-a.pdf first."), `test_protected_inside_refuses` ("2009 holds a protected entry, so it is not copied across disks."), `test_not_enough_space` (`_check_space` counts all files except `present` ones).
  - `test_links_left_behind_noted`: a link inside → no op for it; QUARANTINE note contains `"1 link is not copied; it goes to To Delete with the folder"`.
  - `test_cloud_only_flagged`: `is_dataless` patched True for one file → its op `cloud_only`.
  - `test_plain_plan_still_refused`: same folder MOVE without `copy_across` → `OpFailed(different_disks_message(...))`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement `Planner._copy_folder(self, op: Op, folder: str) -> None`**, called from `_relocate` when `self._copy_plan and kind == "dir"` across disks. Walk the source on disk with `os.scandir` (no links followed), sorted by folded name. Destination root: `join(folder, name)` where a taken name by a folder means merge and a taken name by a file or link gives `_N` via `_free_or_exact`. Existing destination entries are read through `self.sim` so names stay consistent. `present` means equal `st_size` and equal whole seconds of mtime (`st_mtime_ns // 1_000_000_000`), since exFAT and FAT disks keep coarser times than APFS; the hash at act time is the real check. Each copied file reuses the body of `_copy_across` (factor out `_plan_copy(src, dst_folder, wanted) -> ResolvedOp`) without its QUARANTINE. Then `_relocate(Op(QUARANTINE, src, None), self._quarantine_folder(src))` and set `copied_to`, `tree`, and the note `copied to <dst>` (plus the links note).
- [ ] **Step 4:** run → PASS; `uv run pytest tests/test_copy_across_plan.py tests/test_move.py -q` → PASS.
- [ ] **Step 5:** commit `feat: plan a folder move across disks`.

### Task 3: Running it (executor, journal, background job)

**Files:**
- Create: `backend/migrations/versions/0036_operation_copied_to.py`
- Modify: `backend/src/dam/db/tables.py` (`operations.copied_to` Text nullable), `backend/src/dam/ops/executor.py`, `backend/src/dam/ops/primitives.py` (`present_matches`), `backend/src/dam/services/browse.py` (job result text)
- Test: `backend/tests/test_folder_copy.py` (new)

**Interfaces:**
- Consumes: Task 2's `method`, `copied_to`, `tree`.
- Produces: `primitives.present_matches(src: Path, dst: Path, stop: Callable[[], bool] | None) -> None` (raises `OpFailed("<name> at the destination differs from the original; nothing more was moved.")`); `Executor._follow_folder_rows(src: str, dst_root: str) -> None`; `JournalEntry.copied_to`.

- [ ] **Step 1: Write failing tests** (`same_disk` patched False, run through `browse.move` and wait for the job as `tests/test_copy_jobs.py` does):
  - `test_folder_copied_and_original_to_to_delete`: tree copied, mtimes equal, source at `##. To Delete/2009` in its own folder; every file row at its copy with tags; the folder row at `Old years/2009` with its collection, rekeyed to a `local:` id when it had a Drive id.
  - `test_stop_leaves_source_whole`: stop after the first file → `stopped`, source untouched and complete, one copy at the destination, no QUARANTINE row.
  - `test_second_move_after_stop_merges`: move again → first file `present` (done, nothing written), rest copied, source to To Delete, no `*_2*` file anywhere.
  - `test_present_differs_stops`: destination file edited (same size and mtime, other bytes) → batch stops at it with the message, source not in To Delete.
  - `test_file_added_during_job_stops_before_quarantine`: a `progress` hook adds `A/2009/new.pdf` after the first copy → the final QUARANTINE fails with `"2009 changed during the move (new.pdf was added). It stays where it is; move it again to copy the rest."`; nothing in To Delete.
  - `test_file_edited_after_copy_stops`, `test_file_removed_during_job_stops` (message says "was changed" / "was removed").
  - `test_copied_to_journaled`: the QUARANTINE row has `copied_to == "Old years/2009"`.
  - `test_job_result_text`: done → `"Moved folder 2009 (2 files) to 'Old years'"`; stopped → `"Copied 1 of 2 files; 2009 stays in place until all are copied"`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement.**
  - Migration 0036 adds `copied_to` (Text) and `followed` (Text, JSON) to `operations`; `_journal_planned` writes `copied_to=rop.copied_to`; the follow step writes `followed`.
  - `_act` for COPY_ACROSS with `method == PRESENT` calls `present_matches` (hash both with `file_sha256`, honouring `stop`); `_precheck_copy_across` for `present` requires the destination to exist as a regular file instead of being free; `_verify` for `present` checks both still exist.
  - The pair rule in `_run_resolved` stays as is (a folder batch has no per-file QUARANTINE). Before the final QUARANTINE (a QUARANTINE with `tree`), `should_stop` is not consulted if every earlier op is done, so Stop never lands between the tree check and the move.
  - Each COPY_ACROSS done updates `tree[rel]` of the batch's final QUARANTINE with the size and mtime its snapshot read (keep a reference while running the batch).
  - `_precheck` for a QUARANTINE with `tree`: walk the source again (as the planner does, `.DS_Store` skipped) and compare with `tree`; list differences as added / removed / changed (kind, size, mtime), at most five names, in the message above.
  - After that QUARANTINE acts and verifies, in its index step and before `update_path(src, dst)`: `_follow_folder_rows(src, copied_to)`: for every indexed `is_dir` row at or under `src`, the mirrored path under `copied_to`; drop a scanner row already at the mirrored path unless it `has_attachments` (then leave both and log); rekey by the `_repoint_copy` rule (destination folder's own Drive id, else fresh `local:` when the row had a Drive id); re-path that one row only (`FileRepo.update_path(old, new, recursive=False)`, a new keyword, since `update_path` re-paths descendants). It returns `[(old_id, new_id, old_path, new_path)]`, journaled as JSON in the QUARANTINE row's `followed`.
  - `BrowseService` job result title for a folder batch (detect by a QUARANTINE with `copied_to`).
- [ ] **Step 4:** run → PASS; `uv run pytest tests/test_copy_across.py tests/test_copy_jobs.py tests/test_ops_apply.py tests/test_migrations*.py -q` → PASS.
- [ ] **Step 5:** commit `feat: move a folder across disks as a background job`.

### Task 4: Undo, recovery and relabel

**Files:**
- Modify: `backend/src/dam/ops/undo.py` (`_inverse`, `_mark_restored_rows`, `recover`, `_happened`), `backend/src/dam/ops/executor.py` (restore step for folder rows), relabel module that rewrites `operations.src`/`dst` (find with `grep -rn "operations.c.dst" src/dam`)
- Test: `backend/tests/test_folder_copy_undo.py` (new)

**Interfaces:**
- Consumes: `copied_to` on journal rows; `_follow_folder_rows`.
- Produces: `ResolvedOp.follow_back: list[tuple[str, str, str, str]] | None` (the undone row's `followed`) on the MOVE that undoes a folder QUARANTINE.

- [ ] **Step 1: Write failing tests:**
  - `test_undo_folder_move_across`: after a full move, undo → source folder back with every file, copies in `Old years/##. To Delete/2009/...`, made folders under `Old years` removed, file rows and the folder row (with its collection) back at the source with their original ids.
  - `test_undo_after_scan_keeps_folder_collection`: run a scan of both folders between the move and the undo → same result, one row per path, the collection still on the source folder.
  - `test_undo_keeps_nonempty_made_folder`: a new file put in `Old years/2009` after the move → undo leaves `Old years/2009` with that file, and the result's `kept` names it.
  - `test_undo_of_stopped_batch`: copies to To Delete, made folders removed, source untouched.
  - `test_present_has_no_inverse`: undo of the second (merge) batch leaves the first batch's copies in place; undo of the first batch afterwards moves them.
  - `test_recover_final_quarantine_rows_follow`: journal the final QUARANTINE `planned`, perform the rename by hand, run `recover()` → `done`, folder rows at the destination.
  - `test_recover_present_row`: a `planned` present row → `done` when both files match, `needs manual check` otherwise.
  - `test_relabel_rewrites_copied_to`: relabel `Old years` → `Archive 2000s`; the QUARANTINE row's `copied_to` starts with the new label; undo still works.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement.** `_inverse` of a COPY_ACROSS with `method == PRESENT`: no op (filter these rows out of the revert list, mark them `undone` with the batch). `_mark_restored_rows`: a MOVE inverse of a QUARANTINE row with `copied_to` gets `follow_back` from that row's `followed`. The executor's index step for such a MOVE reads the undone row's `followed` and, for each entry, drops a scanner row at `old_path` unless it has attachments, re-paths the row at `new_path` back to `old_path` (`recursive=False`) and rekeys `new_id` back to `old_id`. `recover()`: a done QUARANTINE with `copied_to` and no `followed` runs `_follow_folder_rows`; `_happened` for `present` compares hashes. Relabel: rewrite `copied_to` and the paths inside `followed` like `src`/`dst`.
- [ ] **Step 4:** run → PASS; `uv run pytest tests/test_copy_across_undo.py tests/test_ops_undo.py tests/test_relabel.py tests/test_no_delete.py -q` → PASS.
- [ ] **Step 5:** commit `feat: undo and recover a folder move across disks`.

### Task 5: Links elsewhere warning and API

**Files:**
- Modify: `backend/src/dam/services/browse.py` (preview note), `backend/src/dam/api/schemas.py` (`ResolvedOpOut.method: str | None = None`), `frontend/src/api/schema.d.ts` (generated)
- Test: `backend/tests/test_folder_move.py`, `backend/tests/test_api_browse*.py` (whichever holds move preview API tests)

**Interfaces:**
- Produces: the folder op (one disk: the MOVE; across: the final QUARANTINE) has a note `"1 link elsewhere points into this folder and will point to nothing: <names, at most five>"` when indexed links outside `##. Ongoing` / `##. Important` resolve into the folder (use `services/links.py` resolution on `is_link` rows); `method` in the preview API.

- [ ] **Step 1: Failing tests:** `test_warns_about_links_into_folder` (a Link-drop link in `30. Work` to `20. Home/2009/a.pdf`; an Ongoing link is not counted), API `test_move_preview_has_method` (`present` shows).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement; `cd frontend && npm run gen:api`.
- [ ] **Step 4:** backend tests PASS.
- [ ] **Step 5:** commit `feat: say which links a folder move leaves pointing to nothing`.

### Task 6: Browse UI

**Files:**
- Modify: `frontend/src/dnd.ts` (folder drag read by Browse folder targets), `frontend/src/screens/Browse.tsx` (folder row drops, folder panel Move to…), `frontend/src/components/MoveTo.tsx` (folder request: Move only, confirm label), `frontend/src/components/PlanPreview.tsx` (folder summary)
- Test: `frontend/src/screens/MoveFlows.test.tsx`, `frontend/src/components/PlanPreview.test.tsx`, `frontend/src/dnd.test.tsx`

**Interfaces:**
- Consumes: `FOLDER_DRAG_TYPE` (`{id}`), the move API with `drive_ids: [folderId]`, `ResolvedOpOut.method`.
- Produces: `MoveRequest.folderMove?: true` (Move only: `modes` sets `link` and `copy` to `"Folders can only be moved"`).

- [ ] **Step 1: Failing tests:**
  - dnd: a Browse folder row, the other pane and a breadcrumb accept a folder drag; a tray, the Inbox and the sidebar folders still do not; a folder dropped on itself or its subfolder is refused before the drop ("Cannot move a folder into itself").
  - MoveFlows: folder panel shows **Move to…**; picking `Old years` previews and the confirm says "Copy and move" when the preview has `copy_across` ops, "Move folder" otherwise; Option held does not switch to Copy.
  - PlanPreview: a folder plan shows "Copies 2 folders and 812 files (3.1 GB) to 'Old years'", "120 are there already and are skipped" when `present` ops exist, the existing "originals go to To Delete" line reworded to "The folder goes to To Delete in <source> once every file is copied", and renders 300 ops without error.
- [ ] **Step 2:** `npm test -- --run` → the new tests FAIL.
- [ ] **Step 3:** implement, reusing the existing drop and Move to… flow (`useMoveFlow`) with `ids: [folder.drive_id]`.
- [ ] **Step 4:** `npm test -- --run && npm run build` → PASS.
- [ ] **Step 5:** commit `feat: drag a folder or use Move to… to move it in Browse`.

### Task 7: Docs and full check

**Files:**
- Modify: `docs/guide.md` ("Moving between folders": the "Only files move this way for now" bullet goes, a folder bullet added; the Browse drop table gets a folder row), `docs/reference.md` (move endpoints accept one folder; identity check for folders; `present`; `copied_to`/`followed` journal columns; the safety model line about folder moves), `CHANGELOG.md` (Added), the step 2 spec's "PR 2" paragraph points to the new spec.
- [ ] **Step 1:** write the docs.
- [ ] **Step 2:** `cd backend && uv run ruff check . && uv run pytest -q -W error` → all pass; `cd frontend && npm test -- --run && npm run build` → all pass.
- [ ] **Step 3:** try it on the demo archive (`uv run python -m dam.demo <scratch>/dam-demo`, `--data-dir` explicit) with an extra folder on the same disk to check the one-disk path in the real app; cross-disk is covered by tests only.
- [ ] **Step 4:** commit `docs: folder moves in the guide and reference`; open the PR.
