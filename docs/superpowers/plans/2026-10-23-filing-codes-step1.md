# Filing codes, steps 1 and 2: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The owner keeps a table of filing codes; files in a code's inbox folder or carrying a printed QR sticker arrive pre-filled from that code (tick boxes on the sticker add Starred and Important), and **File N marked** files all coded inbox files as one journaled, undoable batch. Tasks 1 to 9 are step 1 (inbox folders), Tasks 10 to 14 step 2 (QR stickers), Task 15 the docs for both.

**Architecture:** A new backend package `dam.codes` owns the code table (YAML in the data folder), matching (step 1: by inbox folder only; pen and QR plug in later as more sources), applying codes on top of the existing suggestion, and building the batch rows. Inbox membership widens from "directly in the inbox" to "directly in the inbox or directly in a code's inbox folder", in one place on `FileRepo`. The frontend gets a new Settings screen whose first section is the codes editor, code chips and tray preselection in the Inbox form, and a batch review panel reachable from the Inbox and Today.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy Core, pydantic, PyYAML, pytest (uv); React + TypeScript, TanStack Query, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-23-filing-codes-design.md` (sections "Build steps", "Goals" to "Anti-goals", "Step 1", "Step 2: QR stickers" incl. "Star and Important tick boxes", "Constraints").

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

### Task 10: Sticker layout and QR payload (shared geometry)

**Files:**
- Create: `backend/src/dam/codes/sticker.py`
- Test: `backend/tests/test_codes_sticker.py`

**Interfaces:**
- Produces (single source of truth for printing and reading):
  - `QR_VERSION_MODULES = 21` (QR version 1; every payload must fit version 1 at error correction M, asserted).
  - `PLAIN = "dam:{code}"`, `BOXED = "dam:1:{code}"`; `parse_payload(text: str) -> tuple[str, int] | None` returns `(code, layout)` with layout 0 (plain) or 1 (boxes); any other text, including other `dam:` forms, gives None. Code upper-cased, 1 to 4 letters or digits.
  - Layout 1 geometry, in QR modules relative to the QR's top-left corner (spike values, keep verbatim): text column starts at `X0 = 25`, and everything in it is left-aligned on that column (ink edge, not font origin); row 1 the code in bold with its ink top on the QR's top edge, row 2 the label (one line, shrunk from 6.5 pt down to 5 pt to fit) centred on the QR's middle, row 3 the boxes bottom-aligned with the QR; `STAR_SLOT = 6` modules before the star box holding a drawn 5-point star about 65 % of the box height; box side `BOX = 8`; `GAP = 2` after the star box; `BANG_SLOT = 3` modules holding a bold `!` before the important box. The QR plus text block is centred on the label horizontally and vertically. `box_rects(layout=1) -> dict[Literal["star", "important"], tuple[float, float, float]]` (x, y, side) = star `(31, 13, 8)`, important `(44, 13, 8)`.
  - `qr_svg(code: str, layout: int) -> str`: zxing-cpp `create_barcode(payload, BarcodeFormat.QRCode, ec_level="M").to_svg()`.
- [ ] **Step 1: Write the failing tests:** `test_parse_payload` (`dam:P` -> ("P", 0); `dam:1:v3` -> ("V3", 1); `dam:2:P`, `dam:`, `dam:TOOLONG`, `https://x` -> None); `test_longest_payload_is_version_1` (`dam:1:ABCD` decodes back from `qr_svg` rasterised, or from `create_barcode(...).to_image()`, with 21 modules); `test_box_rects`.
- [ ] **Step 2: Run** `uv run pytest tests/test_codes_sticker.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: one sticker layout shared by printing and reading`.

### Task 11: Read QR stickers and tick boxes in the barcode pass

**Files:**
- Create: `backend/src/dam/codes/qr.py`, `backend/migrations/versions/0026_file_qr_codes.py`
- Modify: `backend/src/dam/index/barcodes.py`, `backend/src/dam/index/content.py` (`_read_barcode`, `run_barcodes_once`), `backend/src/dam/index/repo.py`, `backend/src/dam/db/tables.py`
- Test: `backend/tests/test_codes_qr.py`

**Interfaces:**
- Consumes: Task 10.
- Produces:
  - `@dataclass QrRead: code: str; layout: int; star: Literal["ticked", "empty", "unclear"] | None; important: (same) | None` (None for layout 0).
  - `read_qr(image: PIL.Image.Image) -> list[QrRead]` in `codes/qr.py`: page 1 only. For layout 1: map box rects through the QR corner points (`position.top_left/top_right/bottom_left`, 21 modules), register each box pair on its printed outline by searching offsets within ±1.5 modules in 0.25-module steps (maximise dark share along the four edges of both boxes), then measure the dark share (< 128) inside each box with a 15 % inset. Thresholds (from the blind trial, keep verbatim): `>= 1 %` ticked, `< 0.5 %` empty, otherwise unclear. A box partly off the page is unclear.
  - `barcodes.read_page1(path, ext, data) -> tuple[list[str], list[QrRead]]`: one render of page 1 (300 dpi greyscale, as today) feeds both the Code 128 bank-barcode read (all pages up to `MAX_PAGES`, unchanged) and `read_qr`. Pass zxing formats as a tuple, never with `|` (deprecated; the suite runs `-W error`).
  - Table `file_qr_codes` (migration `0026`, `down_revision = "0025"`): `drive_id` (PK, FK files), `sha256`, `reads` (JSON text of the `QrRead` list, `[]` = none found), `read_at`. Same lifetime rules as `file_barcodes`: a row for other content is ignored and the file is read again.
  - `FileRepo.qr_for(drive_id) -> list[QrRead]`, `FileRepo.save_qr(drive_id, sha256, reads) -> bool`; `next_for_barcodes` also returns inbox files that have a barcode row but no `file_qr_codes` row for their content, so existing inbox files get read once after the update.
- [ ] **Step 1: Write the failing tests**, generating stickers in the test with `codes.sticker` and Pillow (no fixture files): `test_plain_sticker_read`; `test_boxed_sticker_ticks` (draw a 2 px cross in the star box, nothing in the other: star ticked, important empty); `test_rotated_page_still_reads` (rotate 178 degrees); `test_faint_mark_is_unclear` (a few dark pixels giving 0.5 to 1 %); `test_foreign_qr_ignored` (`https://example.com` QR); `test_bank_barcode_still_read_with_qr` (existing Code 128 fixture plus a sticker on the same page); `test_reads_recorded_per_content` (save, change sha, row ignored); `test_existing_inbox_file_gets_qr_read_once`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new tests plus `uv run pytest tests/test_barcodes*.py tests/test_content*.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: read filing-code QR stickers and their tick boxes`.

### Task 12: QR hits, Starred and Important in suggestions and the batch

**Files:**
- Modify: `backend/src/dam/codes/apply.py` (`codes_for`), `backend/src/dam/rules/engine.py` (`Suggestion`), `backend/src/dam/services/inbox.py` (`FileRequest`, `_follow_up`, `_run_follow_up`), `backend/src/dam/codes/batch.py`, `backend/src/dam/api/schemas.py`
- Test: `backend/tests/test_codes_qr_batch.py`

**Interfaces:**
- Consumes: Tasks 5, 6, 11; `MarkService.star(drive_ids)`, `MarkService.mark_important(drive_ids)` (`collections/marks.py`).
- Produces:
  - `codes_for` adds a `CodeHit(code, via="qr")` per known code read by Task 11 (unknown codes ignored). A code read both from the folder and a sticker is one code, two hits.
  - `Suggestion.star: bool | None`, `Suggestion.important: bool | None` from the tick boxes (True when any boxed sticker has it ticked); `Suggestion.marks_unclear: bool` when a box is unclear.
  - `FileRequest.star: bool = False`, `FileRequest.important: bool = False` (and `FileRequestIn`): applied after filing in the same follow-up as tray and collections, so undo of the batch removes them like collection membership. Existing callers that do not send them behave as before.
  - Batch: rows carry `star`, `important` in the request; a row with `marks_unclear` gets flag `unclear` with problem "Tick box unclear: star" (or important).
- [ ] **Step 1: Write the failing tests:** `test_qr_hit_fills_suggestion` (sticker P in a root inbox file -> tray to-pay, `codes[0].via == "qr"`); `test_ticked_star_files_starred` (file the batch row, file is in Starred; undo removes it); `test_ticked_important_files_important`; `test_unclear_box_flags_row`; `test_unknown_sticker_code_ignored`; `test_folder_and_sticker_conflict` (folder P, sticker A with different trays -> conflict).
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** them plus `tests/test_codes_apply.py tests/test_codes_batch.py tests/test_inbox.py -q`. Expected: PASS.
- [ ] **Step 5: Regenerate the API types** (`npm run gen:api`); frontend tests and build still pass.
- [ ] **Step 6: Commit** `feat: QR stickers fill the filing, tick boxes star or mark important`.

### Task 13: Sticker sheet page (backend)

**Files:**
- Create: `backend/src/dam/codes/sheets.py`, `defaults/sticker_sheets.yaml`
- Modify: `backend/src/dam/api/routers/codes.py`
- Test: `backend/tests/test_codes_sheets.py`

**Interfaces:**
- Consumes: Task 10, `App.codes`.
- Produces:
  - `SheetLayout(BaseModel)`: `id`, `name`, `columns`, `rows`, `label_w_mm`, `label_h_mm`, `top_mm`, `left_mm`, `gap_x_mm`, `gap_y_mm`, `cut_lines: bool`. Built-ins in `defaults/sticker_sheets.yaml`: `l7651` "Avery Zweckform L7651 (65 per sheet, 38.1 x 21.2 mm)" with columns 5, rows 13, 38.1 x 21.2, top 10.7, left 4.7, gap_x 2.5, gap_y 0 (verify against Avery's published template before release; the guide says to check the pack); `plain` "Plain paper, cut out" with the same grid and `cut_lines: true`. A saved custom layout lives in `config/sticker_sheets.yaml` (`custom` id), written like `filing_codes.yaml`.
  - `render_sheet(codes: list[FilingCode], counts: dict[str, int], layout: SheetLayout, start_at: int = 1, boxes: bool = True, blank_labels: bool = False, outlines_only: bool = False) -> str`: a complete HTML document, A4 `@page { size: A4; margin: 0 }`, absolutely positioned labels in mm, each with `qr_svg` (12 mm QR, layout 1 when `boxes`, else 0), the code in bold, the label (empty when `blank_labels`), and the ★ and ! boxes; `outlines_only` draws only label outlines (the test print). A note at the top of the screen view (hidden in print): "Print at 100 %, without fit to page."
  - `GET /api/filing-codes/sheets` -> layouts; `PUT /api/filing-codes/sheets/custom`; `POST /api/filing-codes/sheet` body `{codes: {code: count}, layout, start_at, boxes, blank_labels, outlines_only}` -> `text/html`.
- [ ] **Step 1: Write the failing tests:** `test_sheet_positions_match_layout` (parse the HTML: label N at the expected mm offsets for l7651); `test_start_at_skips_labels`; `test_counts_and_overflow` (more stickers than fit -> second page); `test_qr_payloads` (each svg decodes, via zxing on a rasterised copy, to `dam:1:<CODE>` or `dam:<CODE>`); `test_blank_labels`; `test_outlines_only`; `test_unknown_code_400`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** No new dependency: SVG from zxing-cpp, HTML by hand (escape labels).
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Regenerate the API types**; commit `feat: printable filing-code sticker sheets`.

### Task 14: Print stickers in Settings, QR and tick boxes in the UI

**Files:**
- Create: `frontend/src/components/codes/PrintStickers.tsx`, `frontend/src/components/codes/PrintStickers.test.tsx`
- Modify: `frontend/src/screens/Settings.tsx`, `frontend/src/components/codes/MarkedBatch.tsx`, `frontend/src/screens/ReviewCard.tsx`, `frontend/src/api/client.ts`

**Interfaces:**
- Consumes: Tasks 12 and 13.
- UI: a "Print stickers" section in Settings: pick codes and a count per code, the sheet layout (built-ins, Custom with its fields), Start at label N, With tick boxes (default on), Blank labels, then **Open sheet** (opens the HTML in a new tab for the browser's print dialog) and **Test print** (outlines only). The batch panel and the Inbox form show "from sticker `P`" for `via == "qr"` and preselect Starred and Important from the suggestion; an unclear box shows "Tick box unclear: check star".
- [ ] **Step 1: Write the failing tests:** section renders built-in layouts; Custom shows the mm fields and saves; Open sheet posts the chosen counts; Test print posts `outlines_only: true`; the review form preselects Starred from `suggestion.star`; the chip reads "from sticker `P`".
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test -- --run` and `npm run build`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: print filing-code stickers from Settings`.

### Task 15: Docs and the full check

**Files:**
- Modify: `docs/guide.md` (new "## Filing codes" section after "Filing from the Inbox", a line in "Today", a "Settings" section for the new screen, and the table of contents), `docs/reference.md` (`filing_codes.yaml` format under "Config and rules"), `CHANGELOG.md` (`## [Unreleased]` / `### Added`), `README.md` (a bullet under "Why you might like it" and a screenshot row, light and dark, in the screenshot table)
- Create: `docs/images/filing-codes-light.png`, `docs/images/filing-codes-dark.png` (the File N marked panel on the demo archive)

Filing codes are a distinguishing feature (like Activity with undo), so the README bullet sits high in "Why you might like it" and says plainly what it does for the user: decide on paper or by where you save a file, and dam files the whole batch after one look. Cover inbox folders, QR stickers with tick boxes, and printing sticker sheets; the README screenshot row may show the batch panel and a printed sticker sheet.

- [ ] **Step 1: Write the guide section:** what a code is, the seeded codes, inbox folders and Create inbox folders, File N marked and its three flags, that hand comments in `filing_codes.yaml` are not kept when saving from the app. Plain words, no em dashes.
- [ ] **Step 1b: Write the README bullet and add the screenshot row** (screenshots taken in Step 4, light and dark, demo archive only, matching the existing `<picture>` rows).
- [ ] **Step 2: Write the CHANGELOG entry** (also say that existing `##. Organize` subfolders named "To pay", "To action" or "File as suggested" become inbox folders after the update): "Filing codes: drop files into a code's folder in the inbox (To pay, To action, File as suggested, or your own) and file them all at once with File N marked."
- [ ] **Step 3: Run the full check:** `uv run ruff check . && uv run pytest -q -W error` in `backend/`; `npm test -- --run && npm run build` in `frontend/`. Expected: all pass.
- [ ] **Step 4: Run the app on the demo archive** (`uv run python -m dam.demo <scratch>/dam-demo`, `uv run dam --data-dir <scratch>/dam-demo/data serve --port 8766`): create inbox folders, drop a demo bill into "To pay", file it via File N marked, undo it. Screenshot for the PR with no personal documents.
- [ ] **Step 5: Commit** `docs: guide and changelog for filing codes`.
