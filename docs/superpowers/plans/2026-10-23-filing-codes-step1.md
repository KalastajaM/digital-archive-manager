# Filing codes, step 1: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The owner keeps a table of filing codes; files in a code's inbox folder arrive pre-filled from that code, and **File N marked** files all coded inbox files as one journaled, undoable batch.

**Architecture:** A new backend package `dam.codes` owns the code table (YAML in the data folder), matching (step 1: by inbox folder only; pen and QR plug in later as more sources), applying codes on top of the existing suggestion, and building the batch rows. Inbox membership widens from "directly in the inbox" to "directly in the inbox or directly in a code's inbox folder", in one place on `FileRepo`. The frontend gets a new Settings screen whose first section is the codes editor, code chips and tray preselection in the Inbox form, and a batch review panel reachable from the Inbox and Today.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy Core, pydantic, PyYAML, pytest (uv); React + TypeScript, TanStack Query, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-23-filing-codes-design.md` (sections "Build steps", "Goals" to "Anti-goals", "Step 1", "Constraints").

## Global Constraints

- CONTRIBUTING safety rules: only the operation layer writes to the archive; every change previewed, journaled, undoable; `backend/tests/test_no_delete.py` untouched.
- No new dependencies.
- All text IO with `encoding="utf-8"` (`tests/test_encoding.py`).
- Cross-platform: `pathlib`, no shell commands. Step 1 has no platform-specific part.
- The feature is called **filing codes** (UI, code, config); never "marks" (that word means Starred/Important).
- Seeded codes and folder names are not tied to any language's words.
- Code: 1 to 4 letters or digits, unique, stored upper case.
- Confusable groups: `0 O Ø D Q`, `1 I L 7`, `5 S`, `2 Z`, `8 B`, `U V`, `6 G`. Warn, never block.
- Seeded codes: `A` (tray `to-action`, inbox folder "To action"), `P` (tray `to-pay`, inbox folder "To pay"), `F` (`as_suggested`, inbox folder "File as suggested").
- Chip copy: "Suggested: <value>, from code `P`"; for an inbox folder source: "from folder To pay".
- Batch flags: **unclear**, **conflict**, **needs input**; flagged rows unticked by default. (Unclear only arises from pen reads, so step 1 never produces it, but the type carries it.)
- Every user-visible change: CHANGELOG `## [Unreleased]` entry and a "Filing codes" section in `docs/guide.md`; regenerate `frontend/src/api/schema.d.ts` with `npm run gen:api` after API changes.
- Full check before done: `uv run ruff check . && uv run pytest -q -W error` in `backend/`; `npm test -- --run && npm run build` in `frontend/`.

## Decisions this plan makes (not in the spec)

- **Where the codes editor lives:** dam has no Settings screen yet. This plan adds one (`/settings`, sidebar entry "Settings") with "Filing codes" as its only section. Moving other settings there (AI excluded folders, tray defaults, archives, folder layout, OCR languages) is a separate follow-up, not this plan.
- **Storage and seeding:** `config/filing_codes.yaml` in the data folder. `defaults/filing_codes.yaml` holds the seed. `AppPaths.ensure()` copies it only when the file is absent, so deleting a seeded code (the file exists) keeps it deleted. The UI writes the whole file (YAML dump, a `.bak-<stamp>` copy first, like `write_ai_exclude_folders`); hand-written comments in that file are not preserved, and the guide says so.
- **Inbox membership is folded** (NFC + casefold) everywhere it is touched, matching `InboxService._in_inbox` and `fold_parts`; the case-sensitive NFC comparisons in `FileRepo` are replaced in the same change.
- **Inbox folders inside the inbox are allowed only through a dedicated plan flag** `Plan.inbox_folders`, which permits MKDIR of a direct child of the inbox and nothing else.
- **Missing required tray fields** do not make `file_it` fail (`TrayService.filing_fields` lets them stay missing), so "needs input" for them is detected by the batch builder itself, not by the dry run.
- **A tray-only code with no folder suggestion** (P on a bill no rule or similar file places) is "needs input: folder".

## Review Focus

1. A user's own subfolder of `##. Organize` that is not a code folder: its files must not appear in the Inbox, counts or Today (Task 3 test `test_own_subfolder_is_not_inbox`).
2. A code folder whose name differs from the code's `inbox_folder` only in case or Unicode normalisation (`to pay`, NFD "Käsi"): it must count (Task 3 test `test_code_folder_matches_folded`).
3. A code edited or removed while files sit in its folder: the files leave the Inbox on the next listing and nothing on disk moves (Task 3 test `test_removed_code_folder_files_leave_inbox`).
4. Two files in the batch with the same target name in the same folder: the batch must flag, not fail as a whole (Task 6 test `test_batch_flags_name_clash`).
5. A code naming a tray that was deleted: no suggestion, an error in the editor, no batch row (Task 1 `test_unknown_tray_is_invalid`, Task 6 `test_invalid_code_gives_no_row`).

---

### Task 1: The code table (model, load, save, seed, confusables)

**Files:**
- Create: `backend/src/dam/codes/__init__.py`, `backend/src/dam/codes/model.py`, `defaults/filing_codes.yaml`
- Modify: `backend/src/dam/config.py` (`AppPaths.ensure`, new property `filing_codes_path`)
- Test: `backend/tests/test_codes_model.py`

**Interfaces:**
- Produces:
  - `class FilingCode(BaseModel)` (`extra="forbid"`): `code: str`, `label: str = ""`, `tray: str | None = None`, `folder: str | None = None`, `name: str | None = None`, `tags: list[str] = []`, `collections: list[str] = []`, `as_suggested: bool = False`, `inbox_folder: str | None = None`. Validator: `code` matches `^[A-Za-z0-9]{1,4}$`, stored upper case; `folder`/`name` pass `check_template`; `inbox_folder` passes `check_folder_name`.
  - `@dataclass CodeProblem: code: str; message: str`
  - `load_codes(path: Path, tray_ids: Collection[str]) -> tuple[list[FilingCode], list[CodeProblem]]`: reads via `rules.model.read_yaml` (a YAML list); a code that fails validation, repeats a code or an `inbox_folder` (folded), or names a tray not in `tray_ids` is reported as a problem and left out. A missing file gives `([], [])`.
  - `save_codes(path: Path, codes: list[FilingCode]) -> None`: backup `<name>.bak-%Y%m%d-%H%M%S` with `"xb"` when the file exists, then write UTF-8 YAML; reads back with `load_codes` and restores the original bytes on mismatch (pattern: `setup.write_ai_exclude_folders`).
  - `confusable_with(code: str, others: Collection[str]) -> list[str]`: the existing codes one confusable substitution away (same length, exactly one position differs, both characters in one group).
  - `AppPaths.filing_codes_path -> Path` = `config_dir / "filing_codes.yaml"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_seed_on_ensure(tmp_path):  # AppPaths(tmp_path).ensure() -> file exists; load gives A, P, F
def test_deleted_seed_stays_deleted(tmp_path):  # save [] then ensure() again -> load gives []
def test_code_is_upper_cased(): assert FilingCode(code="v3").code == "V3"
def test_code_too_long_is_invalid():  # code="ABCDE" -> ValidationError
def test_unknown_tray_is_invalid(tmp_path):  # tray="gone" -> one CodeProblem naming "gone", code left out
def test_duplicate_inbox_folder_folded(tmp_path):  # "To pay" and "to pay" -> second is a problem
def test_bad_template_is_invalid():  # folder="{nope}" -> ValidationError
def test_save_round_trip_and_backup(tmp_path):  # save twice -> one .bak-* file, load == saved
def test_confusable():
    assert confusable_with("O", ["0", "A"]) == ["0"]
    assert confusable_with("S1", ["5I", "SI"]) == ["SI"]  # one position, 1/I; "5I" differs in two
```

- [ ] **Step 2: Run** `uv run pytest tests/test_codes_model.py -q` in `backend/`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the interfaces above and `defaults/filing_codes.yaml` with the three seeded codes (labels "To action", "To pay", "File as suggested"). In `ensure()`, after tray seeding, copy the default with `_copy_new` only if `filing_codes_path` is absent. Check that `_seed` (copying all of `DEFAULTS_DIR` on a fresh install) does not also copy it to a wrong place: the default must land at `config/filing_codes.yaml`.
- [ ] **Step 4: Run** the tests. Expected: PASS. Run `uv run pytest tests/test_config.py -q`: still PASS.
- [ ] **Step 5: Commit** `feat: filing code table with seeding and confusable check`.

### Task 2: App wiring and the codes API

**Files:**
- Modify: `backend/src/dam/app.py` (load codes in `reload_rules`, expose `codes`, `code_problems`), `backend/src/dam/api/schemas.py`
- Create: `backend/src/dam/api/routers/codes.py` (registered where `api/main.py` registers router modules)
- Test: `backend/tests/test_api_codes.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `App.codes: list[FilingCode]`, `App.code_problems: list[CodeProblem]`, loaded in `reload_rules()` after trays (needs tray ids).
  - `App.save_codes(codes: list[FilingCode]) -> list[CodeProblem]`: refuses (raises `InvalidRequest`) if any code is invalid; else `save_codes`, then `reload_rules()` (Task 3 hooks the inbox folder map into that reload).
  - `GET /api/filing-codes` -> `FilingCodesOut { codes: list[FilingCodeOut], problems: list[CodeProblemOut], warnings: list[CodeWarningOut] }` where `CodeWarningOut { code: str, confusable_with: list[str] }`.
  - `PUT /api/filing-codes` body `list[FilingCodeIn]` -> `FilingCodesOut`; 400 with the problem text on invalid input.
  - `FilingCodeIn/Out` mirror `FilingCode`.

- [ ] **Step 1: Write the failing tests:** `test_get_lists_seeded_codes` (3 codes, no problems), `test_put_replaces_and_warns` (PUT `0` and `O` -> both saved, warnings name each other), `test_put_unknown_tray_400`, `test_get_reports_hand_edit_problem` (write a bad entry to the file, `app.reload_rules()`, GET shows one problem). Use `make_client` and `post` helpers from `tests/test_api.py` (with `Origin` header).
- [ ] **Step 2: Run** them. Expected: FAIL (404).
- [ ] **Step 3: Implement** as specified.
- [ ] **Step 4: Run** them. Expected: PASS.
- [ ] **Step 5: Commit** `feat: read and edit filing codes through the API`.

### Task 3: Inbox membership includes code folders

**Files:**
- Modify: `backend/src/dam/index/repo.py` (`FileRepo.__init__`, `in_inbox_path`, `list_dir` use by inbox, `counts`, `transaction`), `backend/src/dam/services/inbox.py` (`list`, `_in_inbox`), `backend/src/dam/ai/tasks/suggest_filing.py` (the `_like_prefix` inbox filter), `backend/src/dam/app.py`
- Test: `backend/tests/test_inbox_code_folders.py`

**Interfaces:**
- Consumes: `App.codes` (Task 2).
- Produces:
  - `FileRepo.code_folders: dict[str, str]`: folded inbox-folder name to code (empty by default; set by `App` after every codes load, and copied in `transaction()`).
  - `FileRepo.inbox_code_of(path: str) -> str | None`: the code whose folder directly contains `path`, else None. Folded comparison.
  - `FileRepo.in_inbox_path(path)` true when the parent, folded, is the inbox or `inbox/<code folder>`.
  - `FileRepo.inbox_files() -> list[FileRecord]`: present, non-dir, non-link, unparked files directly in the inbox or a code folder (replaces `InboxService.list`'s `list_dir(self.special.inbox)` call).
  - `counts()["inbox"]` counts the same set.

- [ ] **Step 1: Write the failing tests** (fake archive, codes seeded):
  - `test_code_folder_file_is_inbox`: `##. Organize/To pay/bill.pdf` -> in `app.inbox.list()`, `counts()["inbox"] == 1`, `repo.inbox_code_of(path) == "P"`.
  - `test_own_subfolder_is_not_inbox`: `##. Organize/Old stuff/x.pdf` -> not listed, not counted.
  - `test_deeper_level_is_not_inbox`: `##. Organize/To pay/2024/x.pdf` -> not listed.
  - `test_code_folder_matches_folded`: folder on disk `to PAY` -> listed with code P.
  - `test_removed_code_folder_files_leave_inbox`: save codes without P -> file not listed; file still on disk at the same path.
  - `test_collection_and_item_in_inbox_flags`: a file in `To pay/` reports `in_inbox` true through `GET /api/items/...` file info and a collection member's attention (reuse fixtures from `test_today_inbox.py` / collections tests).
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.** Replace the NFC-only comparisons with folded ones; the SQL in `counts()` and `inbox_files()` may select files under the inbox (`path_nfc LIKE inbox/%`, escaped) and filter the parent in Python with `in_inbox_path`, since the inbox is small. `suggest_filing.py` treats a MOVE source in a code folder like one in the inbox.
- [ ] **Step 4: Run** the new tests and `uv run pytest tests/test_inbox.py tests/test_today_inbox.py tests/test_watcher.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: files in a filing code's inbox folder count as inbox files`.

### Task 4: Create inbox folders (operation layer)

**Files:**
- Modify: `backend/src/dam/ops/model.py` (`Plan.inbox_folders: bool = False`), `backend/src/dam/ops/planner.py` (`_new_folder_ops`)
- Create: `backend/src/dam/codes/folders.py`
- Modify: `backend/src/dam/api/routers/codes.py`
- Test: `backend/tests/test_codes_folders.py`

**Interfaces:**
- Consumes: Tasks 1 to 3.
- Produces:
  - Planner: when `plan.new_folders and plan.inbox_folders`, an MKDIR whose parent (folded) is exactly the inbox is allowed; anything deeper, or under another special folder, is still refused. `inbox_folders` without `new_folders` raises `GuardError`.
  - `missing_inbox_folders(app) -> list[str]`: code folder names with no folder on disk.
  - `stray_inbox_folders(app) -> list[str]`: direct subfolders of the inbox that are no code's folder.
  - `create_inbox_folders_plan(app, origin) -> Plan` with label `"Created the filing code folders in {inbox}"`.
  - `GET /api/filing-codes/folders` -> `{ missing: list[str], stray: list[str] }`; `POST /api/filing-codes/folders/preview` -> `list[ResolvedOpOut]`; `POST /api/filing-codes/folders` -> `BatchResultOut` (rescan the made folders, as `LayoutService.new_folder` does).

- [ ] **Step 1: Write the failing tests:** `test_preview_lists_missing_folders` (3 MKDIRs into the inbox), `test_create_then_undo_removes_them` (`app.activity.undo(batch_id)`, folders gone, nothing else touched), `test_inbox_folders_plan_refuses_deeper` (MKDIR `##. Organize/To pay/x` -> `GuardError`), `test_plain_new_folder_still_refused_in_inbox` (existing `_new_folder_plan` into the inbox still refused), `test_stray_lists_own_subfolder`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** as specified. Do not touch `test_no_delete.py`; undo already removes `made_folders` for `new_folders=True` batches.
- [ ] **Step 4: Run** them plus `uv run pytest tests/test_new_folder.py tests/test_ops_undo.py tests/test_no_delete.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: create the filing code inbox folders with preview and undo`.

### Task 5: Codes as the strongest suggestion source

**Files:**
- Create: `backend/src/dam/codes/apply.py`
- Modify: `backend/src/dam/rules/engine.py` (`Suggestion`), `backend/src/dam/services/inbox.py` (`_suggest`, `InboxEntry`), `backend/src/dam/api/schemas.py` (`SuggestionOut`, `InboxEntryOut`)
- Test: `backend/tests/test_codes_apply.py`

**Interfaces:**
- Consumes: Tasks 1 to 3.
- Produces:
  - `@dataclass CodeHit: code: str; via: Literal["folder", "pen", "qr"]; raw: str | None = None; unclear: bool = False`
  - `codes_for(app_or_repo, rec: FileRecord) -> list[CodeHit]`: step 1 returns the folder hit from `repo.inbox_code_of`; the hook where pen and QR join later.
  - `apply_codes(found: Suggestion, hits: list[CodeHit], codes: dict[str, FilingCode], doc_date, stem, ext, special) -> Suggestion`: for each field a code sets, sets it with source `f"code:{CODE}"` (folder via `_render_folder`, name via `_render_name`); tags and collections united; scalar fields whose rendered values differ between codes set `conflict = True` and keep the first. `as_suggested` sets nothing.
  - `Suggestion` gains: `collections: list[str] = []`, `tray_source: str | None = None`, `collection_sources: dict[str, str] = {}`, `codes: list[CodeHit] = []`, `conflict: bool = False`. A code's tray sets `tray` and `tray_source`.
  - `SuggestionOut` exposes `tray`, `tray_source`, `collections`, `collection_sources`, `codes: list[CodeHitOut]`, `conflict`.
  - Source string for a folder hit shown in the UI: the frontend renders `code:P` with `via == "folder"` as "from folder <inbox_folder>", else "from code `P`".

- [ ] **Step 1: Write the failing tests:**
  - `test_code_folder_beats_rule`: a rule gives folder X; the P code with folder `Bills/{year}` gives `Bills/<year>`, `folder_source == "code:P"`.
  - `test_unset_fields_fall_back`: P (tray only) keeps the rule's folder and name; `tray == "to-pay"`, `tray_source == "code:P"`.
  - `test_as_suggested_changes_nothing`: F leaves the suggestion equal to the rule-only one, but `codes == [CodeHit("F", "folder")]`.
  - `test_two_codes_conflict_on_folder` (call `apply_codes` with two hits directly) -> `conflict is True`; tags united.
  - `test_api_inbox_entry_has_code_fields`: `GET /api/inbox` row for `To pay/bill.pdf` has `suggestion.tray == "to-pay"` and `suggestion.codes[0].via == "folder"`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.** In `InboxService._suggest`, apply codes after the similar-folder step, so a code folder wins over a similar-files folder; `_in_inbox` uses `repo.in_inbox_path` so similar-folder lookup also runs for code-folder files.
- [ ] **Step 4: Run** them plus `uv run pytest tests/test_inbox.py tests/test_api.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: filing codes fill the Inbox suggestion`.

### Task 6: Batch rows and Today

**Files:**
- Create: `backend/src/dam/codes/batch.py`
- Modify: `backend/src/dam/api/routers/codes.py`, `backend/src/dam/services/today.py`, `backend/src/dam/api/routers/today.py`, `backend/src/dam/api/schemas.py`
- Test: `backend/tests/test_codes_batch.py`

**Interfaces:**
- Consumes: Task 5, `InboxService.list/preview`, `TrayService.filing_fields`, `TrayDef.fields[*].required`.
- Produces:
  - `@dataclass BatchRow: drive_id: str; codes: list[CodeHit]; request: FileRequest; tray_fields: dict[str, str]; flag: Literal["unclear", "conflict", "needs_input"] | None; problem: str | None`
  - `marked_rows(app) -> list[BatchRow]`: one row per inbox entry with at least one valid code hit. `request` is built from the suggestion (name, folder, tags, tray, collections); `tray_fields` is `trays.filing_fields(tray, {}, entry.prefill)` as strings. Flag order: unclear, then conflict, then needs input. Needs input when: folder is None ("folder"); a required tray field is missing (its field name, e.g. "due date"); `InboxService.preview([request])` raises `InvalidRequest`/`GuardError` (its message). After single-row checks, preview all unflagged rows together; when that fails, flag the rows the error names, or fall back to previewing pairs to find clashing targets.
  - `GET /api/filing-codes/batch` -> `list[BatchRowOut]`. Filing uses the existing `POST /api/inbox/preview` and `POST /api/inbox/file` with the ticked rows' requests.
  - `TodayOut.marked: int` (rows without a flag plus rows with one, i.e. all marked rows) for the Today button.

- [ ] **Step 1: Write the failing tests:**
  - `test_tray_code_row_has_tray_fields`: a To pay file with a scanned due date and amount -> row `tray_fields` has `due_date` and `amount`, `flag is None`.
  - `test_missing_due_date_needs_input`: same without a due date -> `flag == "needs_input"`, `problem` names the due date field.
  - `test_as_suggested_without_folder_needs_input`: F file, no rule, no similar files -> `problem == "folder"`.
  - `test_batch_flags_name_clash`: two F files whose suggestions give the same folder and name -> the second is flagged, the first is not.
  - `test_invalid_code_gives_no_row`: a hand-edited code with a deleted tray -> its folder's file has no row.
  - `test_file_ticked_rows_is_one_undoable_batch`: POST `/api/inbox/file` with two rows' requests -> one `batch_id`; `app.activity.undo(batch_id)` puts both back in their code folders and removes their tray items.
  - `test_today_marked_count`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** as specified.
- [ ] **Step 4: Run** them. Expected: PASS.
- [ ] **Step 5: Regenerate the API types:** `npm run gen:api` in `frontend/`; `npm run build` still passes.
- [ ] **Step 6: Commit** `feat: build the File N marked batch from filing codes` (include `frontend/src/api/schema.d.ts`).

### Task 7: Settings screen with the codes editor

**Files:**
- Create: `frontend/src/components/codes/FilingCodes.tsx`, `frontend/src/components/codes/FilingCodes.test.tsx`
- Create: `frontend/src/screens/Settings.tsx`, `frontend/src/screens/Settings.test.tsx`
- Modify: `frontend/src/App.tsx` (route `/settings`), `frontend/src/components/ui/Sidebar.tsx` (entry "Settings" near Activity and Help), `frontend/src/api/client.ts`

**Interfaces:**
- Consumes: Task 2 and Task 4 endpoints.
- Produces: hooks `useFilingCodes()`, `useSaveFilingCodes()`, `useCodeFolders()`, `useCreateCodeFolders()` in `client.ts` (pattern: `useAIExcludeFolders`, `useCreateFolder`); query key `keys.filingCodes`. Saving invalidates inbox, today and status (via `useRefresh`).

UI: `Settings` is a page with a heading and one `section` per area, built so later sections slot in; its first and only section is `FilingCodes`, a `section aria-label="Filing codes"` with one row per code (code, label, tray select from `useTrays`, folder via `FolderPicker`, name, tags, collections, "File as suggested" checkbox, inbox folder), Add and Remove, one Save. Confusable warnings under the affected row: "Easy to confuse with `0` when written by hand." Problems from the file shown at the top. A "Create inbox folders" button when `missing` is non-empty, through `ConfirmPlan` with the preview. `stray` folders listed as "Not a filing code folder: its files are not in the Inbox."

- [ ] **Step 1: Write the failing tests** with `mockFetch` and `renderWithProviders`: the sidebar has a Settings link and `/settings` renders the Filing codes section; renders seeded codes; adding `O` beside `0` shows the warning; Save sends PUT with the edited list; "Create inbox folders" shows the preview and posts on confirm; a 400 shows its message.
- [ ] **Step 2: Run** `npm test -- --run src/components/codes`. Expected: FAIL.
- [ ] **Step 3: Implement** following `ExcludedFolders.tsx` and `TrayDefaults.tsx` for structure and styles.
- [ ] **Step 4: Run** the tests and `npm run build`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: a Settings screen, starting with filing codes`.

### Task 8: Code chips and tray preselection in the Inbox form

**Files:**
- Modify: `frontend/src/screens/ReviewCard.tsx`, `frontend/src/components/SuggestionChip.tsx` (`sourceLabel`), `frontend/src/screens/Inbox.tsx` (`ScanChip` or row badge)
- Test: `frontend/src/screens/ReviewCard.test.tsx`

**Interfaces:**
- Consumes: `suggestion.tray`, `tray_source`, `collections`, `codes`, `conflict` (Task 5).
- Produces: `sourceLabel("code:P", codes)` returns "code `P`" or "folder To pay" (the folder name from the matching `CodeHit` with `via == "folder"`; the frontend gets the folder name from `useFilingCodes`).

- [ ] **Step 1: Write the failing tests:** an entry with `tray_source: "code:P"` opens with To pay selected (today `useTrayChoice` starts at Nothing); the folder chip reads "Suggested: Bills/2026, from folder To pay"; collections from a code are preselected; an entry with `conflict: true` shows "These filing codes disagree; pick the values here." and the list row shows the code badge.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.** Only a `code:` tray source preselects a tray; rule and heuristic tray guesses keep today's behaviour.
- [ ] **Step 4: Run** `npm test -- --run src/screens` and `npm run build`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: filing codes pre-fill the Inbox form`.

### Task 9: File N marked panel (Inbox and Today)

**Files:**
- Create: `frontend/src/components/codes/MarkedBatch.tsx`, `frontend/src/components/codes/MarkedBatch.test.tsx`
- Modify: `frontend/src/screens/Inbox.tsx` (toolbar button), `frontend/src/components/today/InboxCard.tsx` (button), `frontend/src/api/client.ts` (`useMarkedBatch()`)

**Interfaces:**
- Consumes: `GET /api/filing-codes/batch`, `usePreview`, `useFileIt`, `ConfirmPlan`, `TodayOut.marked`.
- Produces: route state `/inbox?marked=1` opens the panel (Today's button navigates there).

UI: button **File N marked** (hidden when N is 0). Panel: one row per `BatchRow` with checkbox (unticked when `flag`), thumbnail, code badge with how found, resulting name, folder, tray, tray fields, tags, collections; a flag line ("Needs input: due date", "Codes disagree"); "Open" selects the file in the Inbox form. **File** previews the ticked requests with `ConfirmPlan`, then files them with one `useFileIt` call and shows the usual undo toast.

- [ ] **Step 1: Write the failing tests:** button shows the count; flagged row starts unticked and shows its problem; File sends one `POST /api/inbox/file` with only ticked requests; Today's button links to `/inbox?marked=1`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** following `BatchCard.tsx` for layout.
- [ ] **Step 4: Run** `npm test -- --run` and `npm run build`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: file all marked inbox files in one confirmed batch`.

### Task 10: Docs and the full check

**Files:**
- Modify: `docs/guide.md` (new "## Filing codes" section after "Filing from the Inbox", plus a line in "Today"), `docs/reference.md` (`filing_codes.yaml` format under "Config and rules"), `CHANGELOG.md` (`## [Unreleased]` / `### Added`)

- [ ] **Step 1: Write the guide section:** what a code is, the seeded codes, inbox folders and Create inbox folders, File N marked and its three flags, that hand comments in `filing_codes.yaml` are not kept when saving from the app. Plain words, no em dashes.
- [ ] **Step 2: Write the CHANGELOG entry:** "Filing codes: drop files into a code's folder in the inbox (To pay, To action, File as suggested, or your own) and file them all at once with File N marked."
- [ ] **Step 3: Run the full check:** `uv run ruff check . && uv run pytest -q -W error` in `backend/`; `npm test -- --run && npm run build` in `frontend/`. Expected: all pass.
- [ ] **Step 4: Run the app on the demo archive** (`uv run python -m dam.demo <scratch>/dam-demo`, `uv run dam --data-dir <scratch>/dam-demo/data serve --port 8766`): create inbox folders, drop a demo bill into "To pay", file it via File N marked, undo it. Screenshot for the PR with no personal documents.
- [ ] **Step 5: Commit** `docs: guide and changelog for filing codes`.
