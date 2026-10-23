# Learned Filing Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** dam drafts a filing rule from a manual filing, proves it against past filings before use, keeps a track record per rule, and lists rules in Settings → Filing rules.

**Architecture:** Backend: a learned-rules file loaded first (`rules/learned.py`), pure draft and replay modules (`rules/draft.py`, `rules/replay.py`), a track-record table and service (`services/rule_record.py`), the offer computed in `InboxService.file_it`, and a `/api/rules` router. Frontend: a `via` on filing, an offer on the filed-toast, a shared `RuleSheet` (draft or edit, with the replay), and a Settings section.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy Core, Alembic, pytest; React, TypeScript, TanStack Query, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-23-learned-filing-rules-design.md`

## Global Constraints

- Never touch a real archive or the default data directory; tests use `fake_archive` / `app` fixtures only.
- Text IO always with `encoding="utf-8"` (`tests/test_encoding.py`).
- Config writes go through `dam.codes.configfile.write_config_file(path, text, verify)`.
- Migration `backend/migrations/versions/0027_rule_outcomes.py`, `revision = "0027"`, `down_revision = "0026"`, `downgrade()` raises `NotImplementedError("downgrade is not supported")`.
- Rule matching in the replay and draft uses the engine's own `_matches` and `fold`; regex timeout `_REGEX_TIMEOUT` (0.2 s) as is.
- Learned file name `learned.yaml`, loaded before the name-ordered files.
- Request models forbid unknown fields (`_In`); new body field `via: Literal["form", "batch", "codes"] = "form"` on `FileBody`.
- After API changes: `npm run gen:api` in `frontend/`, commit `src/api/schema.d.ts`.
- Every user-visible change: `CHANGELOG.md` under `## [Unreleased]`, plain words; guide updated.
- Done means: `uv run ruff check . && uv run pytest -q -W error` in `backend/`; `npm test -- --run && npm run build` in `frontend/`.

## Review Focus

1. A rule word that occurs only in the file name, never in the text: the draft must not propose it (it would never match). Test in Task 3.
2. A document with no date anywhere (no prefix, no text date): folder/name patterns keep no `{year}`/`{doc_date}`, the replay compares without them, nothing crashes on `TemplateError`. Tests in Tasks 3 and 4.
3. A replay over a large archive: stops at the time budget and says "checked N of M" (`truncated`). Test in Task 4.
4. Undoing a filing removes its track-record rows, so an undone filing never counts as "kept". Test in Task 2.
5. A rule file the owner wrote by hand with a regex or `folder_is`: editing that rule in the app keeps both conditions and the other rules in that file. Test in Task 1.

---

### Task 1: Learned rules file, loaded first, and rule file writes

**Files:**
- Create: `backend/src/dam/rules/learned.py`
- Modify: `backend/src/dam/rules/model.py` (`load_rules`), `backend/src/dam/app.py` (methods below), `defaults/rules/00-examples.yaml` (header line)
- Test: `backend/tests/test_rules_learned.py`

**Interfaces:**
- Produces: `LEARNED_FILE = "learned.yaml"` (in `rules/model.py`); `load_rules` returns rules with `learned.yaml` first, then the others by name.
- Produces in `rules/learned.py`: `rules_text(rules: list[Rule]) -> str` (YAML list, `model_dump(exclude_defaults=True, mode="json")`, `sort_keys=False`, `allow_unicode=True`); `write_rules_file(path: Path, rules: list[Rule]) -> None` (via `write_config_file`, verify = `_load_file(path)` equals `rules`); `rule_file(rules_dir: Path, rule_id: str) -> Path | None` (which file holds a loaded rule).
- Produces on `App`: `save_rule(rule: Rule, replaces: str | None = None) -> None` (a rule not yet in any file, or one in `learned.yaml`, is written to `learned.yaml`; a rule from another file is rewritten in that file; a duplicate id raises `InvalidRequest`), `delete_rule(rule_id: str) -> None` (`NotFound` if unknown), `move_rule(rule_id: str, delta: int) -> None` (only within `learned.yaml`; else `InvalidRequest("only learned rules can be moved here")`). Each reloads rules afterwards.

- [ ] **Step 1: Write the failing tests**

```python
def test_learned_file_loads_first(app): ...
    # write 00-examples.yaml with generic rule "invoice" and learned.yaml with "fortum";
    # load_rules → [fortum, generic, ...]

def test_save_rule_creates_learned_file_and_reloads(app):
    app.save_rule(Rule(id="fortum", when={"text_contains": ["fortum"]}, then={"folder": "11. Bills/{year}"}))
    assert (app.rules_dir / "learned.yaml").is_file()
    assert app.rules[0].id == "fortum"

def test_editing_a_hand_written_rule_keeps_its_conditions_and_neighbours(app):
    # hand file 10-mine.yaml with rules a (filename_matches "(?i)^scan", folder_is "##. Organize") and b
    # save_rule(edited a with new then.folder, replaces="a")
    # → 10-mine.yaml still holds a (regex and folder_is kept) and b; a backup 10-mine.yaml.bak-* exists

def test_save_rule_refuses_a_duplicate_id(app): ...   # InvalidRequest
def test_delete_and_move_learned_rules(app): ...      # order changes; move of a non-learned rule refused
```

- [ ] **Step 2: Run** `uv run pytest -q tests/test_rules_learned.py` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `LEARNED_FILE` ordering in `load_rules` (sort key `(p.name != LEARNED_FILE, p.name)`), `rules/learned.py`, and the three `App` methods. Add one header line to `defaults/rules/00-examples.yaml`: `# Rules you make in the app are kept in learned.yaml, which is read first.` (and update `layouts._EARLIER_EXAMPLES` with the previous file's hash so existing installs stay seedable).
- [ ] **Step 4: Run** the same tests — Expected: PASS; also `uv run pytest -q tests/test_layouts*.py`.
- [ ] **Step 5: Commit** `feat: a learned rules file, read first, and saving rules from the app`

### Task 2: Track record table and service, removed on undo

**Files:**
- Create: `backend/migrations/versions/0027_rule_outcomes.py`, `backend/src/dam/services/rule_record.py`
- Modify: `backend/src/dam/db/tables.py`, `backend/src/dam/services/activity.py` (undo cleanups), `backend/src/dam/app.py` (wire the service)
- Test: `backend/tests/test_rule_record.py`

**Interfaces:**
- Produces table `rule_outcomes`: `id` Integer PK, `batch_id` Text not null (indexed), `drive_id` Text not null, `rule_id` Text not null (indexed), `field` Text not null (`"folder"` | `"name"` | `"tray"`), `kept` Boolean not null, `created` Float not null.
- Produces `RuleRecord(engine)` with `record(batch_id: str, drive_id: str, outcomes: list[tuple[str, str, bool]]) -> None` (rule_id, field, kept), `remove_created_by(batch_id: str) -> int`, `stats() -> dict[str, RuleStats]`; `@dataclass RuleStats(suggested: int, changed: int, last_used: float | None, flagged: bool)`. `suggested` counts filings (distinct `batch_id, drive_id`); `changed` counts filings with any `kept = False`; `flagged` is True when 2 or more of the rule's last 5 filings have a folder or name not kept.
- `App.rule_record: RuleRecord`; `ActivityService` gains a `rule_record` constructor argument and calls `rule_record.remove_created_by(batch_id)` with the other cleanups.

- [ ] **Step 1: Write the failing tests**

```python
def test_stats_count_filings_and_changes(engine): ...     # 3 filings, 1 changed → suggested 3, changed 1
def test_flagged_after_two_changes_in_last_five(engine): ... # kept,kept,changed,kept,changed → flagged
def test_undo_removes_the_batch_outcomes(app, fake_archive): ...  # file via API, undo, stats empty
```

- [ ] **Step 2: Run** `uv run pytest -q tests/test_rule_record.py` — Expected: FAIL.
- [ ] **Step 3: Implement** the migration, table, service and wiring (writes in `write_tx`).
- [ ] **Step 4: Run** the tests and `uv run pytest -q tests/test_migrations*.py tests/test_activity*.py` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: a track record of what each rule suggested and what was kept`

### Task 3: Drafting a rule from a filing

**Files:**
- Create: `backend/src/dam/rules/draft.py`
- Test: `backend/tests/test_rules_draft.py`

**Interfaces:**
- Consumes: `similar._tokens`, `similar._STOP`, `core.naming.parse_doc_date`, `engine.check_template`.
- Produces: `@dataclass DraftWord(word: str, ticked: bool)`; `@dataclass RuleDraft(id: str, words: list[DraftWord], folder: str | None, name: str | None, tags: list[str], tray: str | None, payee: str | None)`;
  `draft_rule(*, text: str, original_name: str, filed_name: str, filed_folder: str, doc_date: date | None, tags: list[str], tray: str | None, payee: str | None, doc_frequency: Callable[[str], float], taken_ids: set[str]) -> RuleDraft | None` (None when no word is left);
  `folder_pattern(folder: str, doc_date: date | None) -> str`; `name_pattern(filed_stem: str, original_stem: str, doc_date: date | None) -> str`.
- Rules (from the spec): words from the **text only** (`_tokens("", text)`), minus words with `doc_frequency(word) > 0.3` (share of filed documents containing it); one ticked word: the lowest frequency, ties to the earliest; at most 6 words offered. Folder: each path part equal to `str(doc_date.year)` → `{year}`. Name: a leading `YYYYMMDD` equal to `doc_date` → `{doc_date:%Y%m%d}`; the rest after `_` equal to `clean_stem(original_stem)` → `{stem}`. Id: the ticked word, slugified; `-2`, `-3` … when taken. Every pattern passes `check_template`.

- [ ] **Step 1: Write the failing tests**

```python
def test_folder_year_becomes_a_pattern():
    assert folder_pattern("11. Bills & Receipts/2026", date(2026, 10, 15)) == "11. Bills & Receipts/{year}"
    assert folder_pattern("11. Bills & Receipts/2025", date(2026, 10, 15)) == "11. Bills & Receipts/2025"
    assert folder_pattern("13. Taxes", None) == "13. Taxes"

def test_name_date_and_stem_become_patterns():
    assert name_pattern("20261015_Fortum", "lasku 123", date(2026, 10, 15)) == "{doc_date:%Y%m%d}_Fortum"
    assert name_pattern("20261015_lasku 123", "lasku 123", date(2026, 10, 15)) == "{doc_date:%Y%m%d}_{stem}"
    assert name_pattern("Fortum contract", "scan", None) == "Fortum contract"

def test_draft_ticks_the_rarest_text_word_and_never_a_name_only_word():
    d = draft_rule(text="Fortum Oyj\nAsiakasnumero 123\nHelsinki", original_name="helen.pdf", filed_name="20261015_Fortum.pdf",
                   filed_folder="11. Bills/2026", doc_date=date(2026, 10, 15), tags=["bill"], tray=None, payee=None,
                   doc_frequency=lambda w: {"helsinki": 0.5}.get(w, 0.01), taken_ids=set())
    assert [w.word for w in d.words if w.ticked] == ["fortum"]
    assert "helsinki" not in [w.word for w in d.words] and "helen" not in [w.word for w in d.words]
    assert (d.id, d.folder, d.name, d.tags) == ("fortum", "11. Bills/{year}", "{doc_date:%Y%m%d}_Fortum", ["bill"])

def test_draft_id_is_unique(): ...          # taken_ids={"fortum"} → "fortum-2"
def test_no_draft_without_words(): ...      # text of stop words only → None
```

- [ ] **Step 2: Run** `uv run pytest -q tests/test_rules_draft.py` — Expected: FAIL.
- [ ] **Step 3: Implement** `rules/draft.py` (pure; no DB access).
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat: draft a filing rule from what was just filed`

### Task 4: Replay and explain

**Files:**
- Create: `backend/src/dam/rules/replay.py`
- Test: `backend/tests/test_rules_replay.py`

**Interfaces:**
- Consumes: `engine._matches`, `engine._render_folder`, `engine._render_name`, `model.fold`, `layouts.special_names`, `ops.guards.is_under`, tables `files`, `file_text`.
- Produces: `@dataclass ReplayHit(drive_id: str, path_now: str, path_rule: str)`; `@dataclass ReplayResult(matched: int, same: int, different: list[ReplayHit], inbox: int, shadowed: list[tuple[str, str]], checked: int, total: int, truncated: bool)`;
  `replay(engine: Engine, rule: Rule, rules: list[Rule], special: SpecialFolders, budget_s: float = 5.0) -> ReplayResult`. `rules` is the load order with `rule` in its place (`replaces` handled by the caller); `shadowed` lists `(drive_id, winning_rule_id)` where an earlier rule gives the folder or name.
  `explain(rec: FileRecord, text: str, rules: list[Rule], special: SpecialFolders, inbox_alias: str | None) -> list[RuleExplain]`; `@dataclass RuleExplain(rule_id: str, matched: bool, why: str, wins: list[str])` (`why`: "word ‘fortum’", "file name matches …", "not in the inbox", "no word found"; `wins`: fields this rule gives, from `suggest`'s sources).
- Rules: population = indexed files with text, not dir/link/missing/parked, not under any special folder; `folder_is` ignored; date = `files.doc_date` else `parse_doc_date(name)`; `{stem}` rendered with the current stem minus its date prefix and one `_`; a `TemplateError` for a file counts it as different with `path_rule = ""`; inbox files are counted in `inbox`, not compared.

- [ ] **Step 1: Write the failing tests** (`add_in` / `add_filed` helpers from `test_codes_apply.py` / `test_inbox.py`)

```python
def test_replay_counts_same_and_different(app, fake_archive):
    # filed: "11. Bills/2025/20250110_Fortum.pdf" and "11. Bills/2026/20260210_Fortum.pdf" (text "Fortum"),
    #        "20. Home/20260301_Fortum.pdf" (text "Fortum"); inbox: one "Fortum" file
    rule = Rule(id="fortum", when={"text_contains": ["fortum"], "folder_is": "##. Organize"},
                then={"folder": "11. Bills/{year}", "name": "{doc_date:%Y%m%d}_Fortum"})
    r = replay(app.engine, rule, [rule], app.settings.special_folders)
    assert (r.matched, r.same, r.inbox) == (3, 2, 1)
    assert [h.path_rule for h in r.different] == ["11. Bills/2026/20260301_Fortum.pdf"]

def test_replay_without_dates_never_crashes(app, fake_archive): ...   # undated file, {year} pattern → different, path_rule ""
def test_replay_reports_an_earlier_rule_winning(app, fake_archive): ... # generic "invoice" rule first → shadowed
def test_replay_stops_at_the_budget(app, fake_archive): ...  # budget_s=0 → truncated, checked < total
def test_explain_says_which_word_matched_and_what_wins(app, fake_archive): ...
```

- [ ] **Step 2: Run** `uv run pytest -q tests/test_rules_replay.py` — Expected: FAIL.
- [ ] **Step 3: Implement** `rules/replay.py` (one `engine.connect()` read; stream rows).
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat: replay a rule against past filings, and explain which rule files a document`

### Task 5: The offer in a filing, and its state

**Files:**
- Create: `backend/src/dam/rules/state.py`
- Modify: `backend/src/dam/services/inbox.py` (`file_it`), `backend/src/dam/api/schemas.py` (`FileBody.via`, `FileItResultOut.offer`, new `RuleDraftOut`, `RuleOfferOut`), `backend/src/dam/api/routers/inbox.py`
- Test: `backend/tests/test_rules_offer.py`

**Interfaces:**
- Consumes: Task 1 (`LEARNED_FILE`, `rule_file`), Task 2 (`RuleRecord.record`), Task 3 (`draft_rule`).
- Produces in `rules/state.py`: `@dataclass RulesState(offer: bool = True, declined: list[list[str]] = [])`; `load_state(data_dir: Path) -> RulesState`, `save_state(data_dir: Path, state: RulesState) -> None` (`rules-state.json`, utf-8).
- `InboxService.file_it(reqs, dry_run=False, origin="ui", via: str = "form") -> FileItResult`; `FileItResult` gains `offer: RuleOffer | None`; `@dataclass RuleOffer(kind: Literal["new", "update"], rule_id: str | None, drive_id: str, draft: RuleDraft)`.
- Behaviour: before applying, for `via in ("form", "batch")` compute `_suggest` per request; after a completed filing, record outcomes per rule-sourced field (`folder_source`, `name_source`, `tray_source` starting `rule:`; kept = request value equals suggestion, NFC-compared). Offer only when `via == "form"`, one request, done, `state.offer`, the folder or name was not a rule's value or was changed, and the drafted ticked-word set is not in `state.declined`; kind `"update"` (with that `rule_id`) when the changed value came from a rule in `learned.yaml`, else `"new"`.
- API: `FileBody.via: Literal["form", "batch", "codes"] = "form"`, passed to `file_it`; `FileItResultOut.offer: RuleOfferOut | None`.

- [ ] **Step 1: Write the failing tests**

```python
def test_manual_filing_without_a_rule_offers_a_new_rule(client, app, fake_archive): ...
    # inbox "lasku.pdf" with text "Fortum Oyj ...", file to "11. Bills/2026" as "20261015_Fortum.pdf"
    # → offer.kind == "new", draft.folder == "11. Bills/{year}", ticked word "fortum"
def test_changing_a_learned_rules_folder_offers_an_update(client, app, fake_archive): ...  # kind "update", rule_id
def test_kept_rule_suggestion_records_and_offers_nothing(client, app, fake_archive): ...  # stats suggested 1, changed 0
def test_no_offer_for_batches_codes_declined_or_switched_off(client, app, fake_archive): ...
def test_unknown_via_is_refused(client): ...   # 422
```

- [ ] **Step 2: Run** `uv run pytest -q tests/test_rules_offer.py` — Expected: FAIL.
- [ ] **Step 3: Implement** state, the `file_it` changes (draft's `doc_frequency` from an FTS document count over filed files; computed once per filing), schemas and router.
- [ ] **Step 4: Run** the tests and `uv run pytest -q tests/test_inbox*.py tests/test_api*.py` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: offer a rule after a manual filing, and keep a record of rule suggestions`

### Task 6: The rules API

**Files:**
- Create: `backend/src/dam/api/routers/rules.py`
- Modify: `backend/src/dam/api/main.py` (register router), `backend/src/dam/api/schemas.py`, `frontend/src/api/schema.d.ts` (regenerated)
- Test: `backend/tests/test_api_rules.py`

**Interfaces (all under `/api/rules`):**
- `GET ""` → `RulesOut{ rules: [RuleOut{ id, file, learned: bool, when, then, stats: RuleStatsOut }], errors: [RuleErrorOut], state: RulesStateOut{offer, declined: int} }`.
- `POST /replay` body `RuleReplayIn{ rule: RuleIn, replaces: str | None }` → `ReplayOut` (fields of `ReplayResult`; `different` as `{drive_id, path_now, path_rule}`).
- `PUT /{rule_id}` body `RuleIn` (+ `replaces` query) → `RulesOut` (`App.save_rule`); `DELETE /{rule_id}` → `RulesOut`; `POST /{rule_id}/move` body `{delta: int}` → `RulesOut`.
- `POST /explain` body `{drive_id}` → `[RuleExplainOut]`.
- `PUT /state` body `{offer: bool | None, clear_declined: bool = false}`, `POST /state/decline` body `{words: list[str]}` → `RulesStateOut`.
- `RuleIn` mirrors `Rule` (`id`, `when{text_contains, filename_matches, folder_is}`, `then{folder, name, tags, tray, payee}`); validation errors → 400 `{"error"}` as in `routers/codes.py`.

- [ ] **Step 1: Write the failing tests** (one per route: list with stats, replay shape, save/replace, delete 404 for unknown, move refusal, explain, state toggle and decline).
- [ ] **Step 2: Run** `uv run pytest -q tests/test_api_rules.py` — Expected: FAIL.
- [ ] **Step 3: Implement** the router; `cd frontend && npm run gen:api`.
- [ ] **Step 4: Run** the tests and `uv run ruff check .` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: the rules API: list, replay, save, delete, move, explain, offer state`

### Task 7: Filing says where it came from; the offer on the filed-toast; the rule sheet

**Files:**
- Create: `frontend/src/components/rules/RuleSheet.tsx`, `frontend/src/components/rules/ReplayResult.tsx`
- Modify: `frontend/src/api/client.ts` (hooks; `useFileIt` takes `via`), `frontend/src/screens/useFiling.ts` (`fileIt(requests, batch = false, via?: Via)`), `frontend/src/screens/BatchCard.tsx` (`via "batch"`), `frontend/src/components/codes/MarkedBatch.tsx` (`via "codes"`), `frontend/src/screens/Inbox.tsx` (toast actions)
- Test: `frontend/src/components/rules/RuleSheet.test.tsx`, additions to `frontend/src/screens/useFiling.test.tsx` and an Inbox flow test

**Interfaces:**
- Consumes: Task 6 routes and generated types (`Schemas["RuleOfferOut"]`, `Schemas["ReplayOut"]`, …).
- Produces in `client.ts`: `type Via = "form" | "batch" | "codes"`; `useRules()`, `useReplay()` (mutation), `useSaveRule()`, `useDeleteRule()`, `useMoveRule()`, `useExplain()`, `useRulesState()` mutations; `keys.rules = ["rules"]`.
- Produces: `RuleSheet({ initial: RuleDraft | Rule, replaces?: string, onClose })`: match words as chips (ticked/unticked, add a word), folder and name patterns each with "gives …" for the document, tags, tray, payee (each with a leave-out box), More conditions (`filename_matches`, `folder_is`), and `ReplayResult` below, refreshed 400 ms after the last edit. Save: when `different.length > 0` asks "N documents would land somewhere else. Save anyway?"; zero matches shows "Not tested yet: no filed document matches it".
- Inbox toast: when `result.offer`, the filed toast gets a second action, **Make a rule…** (or **Update rule <id>…**), opening `RuleSheet`, and **Not for these** (`POST /api/rules/state/decline` with the ticked words).

- [ ] **Step 1: Write the failing tests**: the body posted by BatchCard has `via: "batch"`, MarkedBatch `"codes"`, ReviewCard `"form"`; a filing result with an offer shows the two actions; RuleSheet shows the replay counts and the different rows; Save with differences asks first; unticking the only word disables Save ("Tick at least one word").
- [ ] **Step 2: Run** `npx vitest run src/components/rules src/screens` — Expected: FAIL.
- [ ] **Step 3: Implement** the hooks, plumbing, sheet and toast.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat: offer a rule after filing, with its proof, from the filed message`

### Task 8: Settings → Filing rules

**Files:**
- Create: `frontend/src/components/rules/FilingRules.tsx`
- Modify: `frontend/src/screens/Settings.tsx` (`SECTIONS`: `{ id: "filing-rules", label: "Filing rules", scope: "archive" }` after Filing codes), `frontend/src/components/SuggestionChip.tsx` (flag note), `frontend/src/styles.css`
- Test: `frontend/src/components/rules/FilingRules.test.tsx`, `frontend/src/screens/Settings.test.tsx`

**Interfaces:**
- Consumes: Task 7 hooks and `RuleSheet`.
- Produces: one line per rule in load order (id, ticked words, "→ folder", "kept 9 of 9" or "changed 2 of 5", a flag "Corrected recently", the file for non-learned rules), clicking opens `RuleSheet` with `replaces`; New rule; Delete (asks); Up/Down for learned rules; Test a document (pick an inbox file → `useExplain` list); the files that could not be loaded on top; the offer switch and "Forget N declined senders". `SuggestionChip` adds the note "this rule was corrected recently" when the source is `rule:<id>` and that rule is flagged (from `useRules`).

- [ ] **Step 1: Write the failing tests**: lines and stats render; opening a rule shows its sheet; delete asks then calls DELETE; move calls the move route; a non-learned rule has no Up/Down and names its file; Test a document lists the explain rows; the switch posts state; a flagged rule's chip shows the note.
- [ ] **Step 2: Run** `npx vitest run src/components/rules src/screens/Settings.test.tsx src/components` — Expected: FAIL.
- [ ] **Step 3: Implement** the section, the chip note and styles (follow `.code-line` styles).
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** `feat: Settings → Filing rules: every rule with its record, edit, test, delete`

### Task 9: Docs, full checks, the real app

**Files:**
- Modify: `docs/guide.md` (a "Learned rules" part under filing rules; Settings section list), `CHANGELOG.md`, `docs/reference.md` (`learned.yaml`, `rules-state.json`), `README.md` only if it lists features
- [ ] **Step 1:** Write the guide and changelog entries (no em dashes; plain words).
- [ ] **Step 2: Run** the full check from Global Constraints — Expected: all pass.
- [ ] **Step 3:** On the demo archive (`--data-dir` in the scratchpad): file an inbox document by hand, make a rule from the offer, see the replay, save, file the next matching document and see the rule's suggestion; undo it and see the record drop.
- [ ] **Step 4: Commit** `docs: learned filing rules in the guide, reference and changelog`
