# Multiple archive folders, build step 2: copy across and relabel

Status: design agreed 2026-10-26; PR 1 (copy across for files, relabel) built 2026-10-26. Built in two pull requests: **PR 1** copy
across for files (with the background job) and relabel; **PR 2** folder moves, on one
disk (a rename) and across disks, designed separately before it is built (see "PR 2:
folder moves" at the end). Browse cannot move folders at all today
(`services/browse.py` `_move_ops`: "folders cannot be moved yet").

This builds on `2026-10-26-multiple-archive-folders-design.md` (step 1, shipped in #74
and #76). Read its "Path model", "To Delete in every folder" and "Moving between
folders" first. Where the two documents differ, this one wins for step 2.

## Intent

The owner keeps current papers in a synced cloud folder and the old years on an external
disk. Step 1 lets one archive span both, but a move between folders on different disks
is refused, so the old years cannot actually be moved out. Step 2 makes that move work,
safely, for whole folders of several GB, and lets the owner rename a folder's label
(the name it has at the top of Browse) without losing anything stored under it.

## Goals

- A move of files between archive folders on different disks works where the owner
  moves files by hand: drag in Browse, Move to…, Restore to inbox (PR 1). Whole folders
  follow in PR 2.
- Nothing is ever deleted: the original goes to its own folder's `##. To Delete`.
- Tags, notes, collection memberships, tray items and locks follow the file to the copy.
- Large moves run in the background with progress and a Stop button.
- Changing a label rewrites every stored path under it, with a dry run, and leaves
  rule and tray files readable and commented as the owner wrote them.

## Non-goals

- No copy of extended attributes, Finder tags or colours. The file content and its
  modification time are copied; nothing else.
- No resume of a stopped copy job. A stopped batch is a finished batch; the owner
  starts a new move for what is left.
- Relabel changes nothing on disk, and does not rename the folder on disk.
- Search strings the owner types (`in:"Old years"`) are not stored and not rewritten.

## Anti-goals (a failure even if it technically works)

- A file that exists nowhere complete, at any moment, including a crash or an unplugged
  disk mid-copy.
- The original in To Delete taking the tags back from the copy on the next scan.
- A relabel that leaves the index, the journal and the settings disagreeing about the
  label (old batches no longer undoable, rules pointing at nothing).
- A rule file rewritten so that the owner's comments or layout are gone.

## Part 1: copy across

### Where it applies

The planner's `_check_same_disk` today raises `OpFailed(different_disks_message(...))`
for a MOVE between folders on different disks. In step 2 that refusal is replaced, **only
for plans that ask for it**: a new `Plan.copy_across: bool = False`, set by
`BrowseService.move` (mode `move`) and by Restore (`to="inbox"` and `to="folder"`). In
such a plan a MOVE of a file (with or without a new name) whose source and destination
folders are on different disks is expanded into the ops below. Every other caller (inbox
and rule filing, collections conversion, filing codes, undo plans) keeps the plain
refusal, so their result handling, which reads MOVE and RENAME rows, is untouched. (My
call: filing a new document straight onto another disk is rare; it can follow later.)
RENAME and QUARANTINE never cross folders and are unchanged. Restore from an extra
folder's To Delete to the inbox takes the same path, except that its original is already
in To Delete (see "Restore").

`different_disks_message` and its tests go; the docs sentences saying copying across is
"not built yet" (`docs/guide.md` "Moving between folders", `docs/reference.md` "To
Delete exists per archive folder") are rewritten.

### The ops

A new `OpKind.COPY_ACROSS`. `ResolvedOp.src` is the archive path of the file, `dst` its
archive path in the other folder. It is always followed, directly in the same batch, by an
ordinary QUARANTINE of the original, with the note `copied to <dst>`.

**One file** `A/x.pdf` (main folder) moved to `Old years/2009`:

1. MKDIR for any missing folder at the destination (as for a move).
2. COPY_ACROSS `A/x.pdf` → `Old years/2009/x.pdf` (a taken name gets `_N`, as for a move).
3. QUARANTINE `A/x.pdf` → `##. To Delete/A/x.pdf`.

Several selected files in one move each produce their own pair; the batch is one
journal batch with one Activity title ("Moved N files to 'Old years'").

### COPY_ACROSS act, in the executor

Journal first, as every op: the snapshot reads size, mtime, drive id and the sha256 of
the source (`content_hash`, the column added for rule pictures in 0030), and the row is
written `planned` before anything is copied. Then:

1. Precheck: source still a plain file with the planned drive id (as a move); the
   destination name is free; its folder is a real folder.
2. Copy with the generalised `copy_picture` (rename it `copy_verified`, keep a
   `copy_picture` alias or update its two callers): re-hash the source and compare with
   the journaled hash (refuse if changed), `copy_file` with exclusive create and fsync,
   then check size and sha256 of the copy. For copy across the size limit is not
   `MAX_COPY_BYTES` (200 MB): `copy_file` gets `limit=None` meaning no cap, only the
   free-space check. The copy is written under a temporary hidden name in the
   destination folder (`.dam-copy-<random>-<name>`, exclusive create) and only after
   verification renamed (`rename_excl`) to its final name, so a cut-short copy never
   sits under the real name. After verification, set the copy's mtime (and atime) to the
   source's (`os.utime`). The scanner skips `.dam-copy-*` entries. (My call.)
3. Verify step (the executor's `_verify`): the copy is a regular file with the
   journaled size and hash; the source is still there.
4. Index: the source's row is re-pointed to the copy, so everything keyed by drive id
   follows (tags, text, notes, collections, tray items, locks, assignments). Today
   `repo.rekey` carries only `files`, `file_text`, `file_tags`, `file_barcodes`,
   `file_qr_codes`, `file_layouts` and the FTS row; it is extended to every table that
   refers to a file by drive id (`notes` and `checklist_items` where `target_kind` is
   `file`, `collection_members`, `member_link_names`, `item_files`, `file_locks`,
   `file_assignments`, `file_summaries`, `file_fields`, `rule_outcomes`, `ai_calls` if it
   holds ids; the builder checks `tables.py` for any other). This also fixes the
   scanner's existing local-to-Drive-id rekey, which drops those today; the CHANGELOG
   says so under Fixed. The row's id:
   - the copy has a Drive id xattr of its own: `repo.rekey(old, that id)`;
   - otherwise, if the old id is a Drive id: `repo.rekey(old, "local:<new uuid>")`, so
     the original (which keeps its Drive xattr) is a stranger to the row on the next scan;
   - otherwise (a `local:` id) the id stays.
   Then `repo.update_path(src, dst)`. The QUARANTINE that follows finds no row at the
   source and changes nothing in the index; the next scan indexes the original in To
   Delete as a new file with nothing attached.

On any failure the batch stops (as every batch does). Nothing is removed: a partial or
mismatching copy stays under its temporary name and the error names it (the existing
`copy_file` wording). The QUARANTINE of the original is never reached for a file whose
copy is not verified.

### Refused in the dry run, with a plain message

- Anything the move itself refuses today: folders and links (PR 1 moves files only),
  locked files, a folder that is not connected, special folders.
- A protected entry (`protected_paths`, or inside one): a move of it is allowed today,
  but its original cannot go to To Delete (the guards refuse quarantining anything
  protected), so a cross-disk move of it is refused: "<name> is protected, so it is not
  copied across disks." The safety model is not changed. (My call.)
- Not enough free space on the destination for the whole batch plus the existing margin
  (`_COPY_FREE_MARGIN`), checked once in the preview and again per file by `copy_file`.

### Shown in the preview

The preview lists the ops as today. The copy-across group adds a summary the frontend
shows above the list: number of files, total size, the destination folder, "The
originals go to To Delete in <source folder>", and, on macOS, the number of cloud-only
files (`SF_DATALESS`, as `collections/export.py:_is_dataless` reads it) with "these are
downloaded first". The API returns this as a `copy_across` object on the preview
response (null when the move is a plain rename).

### Background job

A move whose plan holds a COPY_ACROSS runs as a background job, not inside the request.
A move without one stays synchronous, exactly as today.

- A new job kind `copy_across`, run by the job runner of `maintenance/jobs.py` (or a
  shared copy of it in `dam/ops/jobs.py`; the builder decides): one at a time per
  archive; starting a second copy-across move while one runs is a 409 with a plain
  message.
- Unlike maintenance checks, a copy job does not end when nobody polls (no
  `ABANDONED_S`): closing the window must not stop a move halfway.
- Closing the app (quit, Ctrl+C, a reopen) does not wait minutes for a large file:
  `copy_file` takes a stop check that it looks at between chunks, and on app close the
  copy in progress ends there. The temporary `.dam-copy-*` file stays (never deleted by
  dam), the op fails with a message naming it, and the batch is a stopped batch. A crash
  instead of a clean close leaves a `planned` row, which recovery settles (below). An
  explicit Stop never cuts a copy short. (My call.)
- Progress: files done/total, bytes done/total, the current file. Polled like the
  maintenance jobs (`GET /api/browse/move/jobs/{id}`, `POST .../stop`,
  `GET /api/browse/move/jobs/latest`).
- **Stop** lets the current pair finish (a verified copy is always followed by its
  QUARANTINE before stopping) and ends the batch there. Every file is then either fully
  moved or untouched, so moving the rest later is an ordinary new move with no
  duplicates. The result says how far it got ("12 of 40 files moved").
- The executor gets an optional `should_stop` callback and a `progress` callback in
  `_run_resolved`; with neither, behaviour is unchanged.
- `App.jobs_running()` counts a running copy job, so detach, attach, relabel and
  snapshot restore refuse while it runs. Other changes to the archive are not refused:
  each op's precheck catches a source that moved or changed (drive id, hash), and the
  batch stops there.
- The planned batch is resolved and checked (identity, locks) in the request, before the
  job starts; the job runs exactly those ops.
- INDEX_LOCK is held per op as today, so a scan waits while a large file copies. (A
  scan of the destination must not index a half-written copy.)

### Undo

Undo needs no new op kind and no new allowed call:

- QUARANTINE of the original: the existing inverse (MOVE back, exact).
- COPY_ACROSS: inverse is QUARANTINE of the copy into the destination folder's own To
  Delete. After it completes, the executor re-points the index row (now at the copy's
  place in To Delete) back to the original's path, and rekeys it back to the journaled
  `drive_id` (the original's). If the scanner had already indexed the original in To
  Delete as a new row, that row is removed from the index first (a database row, never
  a file; nothing can be attached to it, because files in To Delete are read-only for
  the API), through the repo's existing `_delete_rows`, so neither its id nor its path
  collides. The row with the owner's tags always survives. (My call.)
- `_check_unchanged` for COPY_ACROSS: the copy at `now_at` is a regular file with the
  journaled size and sha256 (as for COPY and rule pictures).
- `mark_reverted`: a QUARANTINE of the copy reverts the COPY_ACROSS row whose `dst` it
  names.
- Undo of a big batch is renames only, so it stays synchronous.
- Both folders must be connected (as every undo).

### Restore

Restore from a To Delete to the inbox or a folder on another disk: COPY_ACROSS to the
destination, and no QUARANTINE (the original is in To Delete already; it stays there with
a note). Undo moves the copy into the main folder's To Delete and points the row back.

### Crash recovery

`recover()` settles a `planned` COPY_ACROSS row: destination missing → interrupted
before execution; destination present with the journaled size and hash and the source
still there → done (and the index update runs); only the temporary `.dam-copy-*` file
present, or a copy that does not match → needs manual check, every file left alone (the
`_picture_copy_happened` pattern, minus any removal). Maintenance lists leftover
`.dam-copy-*` files so the owner can remove them.

## Part 2: relabel

### What the owner does

Settings → Archive folders → an extra folder's row → **Change label**. The dialog asks for
the new label, shows the dry run ("Changes 1 240 index entries, 37 journal entries, the
settings and 2 rule files. Nothing on disk changes."), and **Change label** applies it.
Afterwards the folder appears under the new name everywhere. To go back, change the label
again.

### Checks (refusals with a plain message)

- The new label passes the add-folder label rules (`archive_folders` label checks),
  ignoring the folder's own old label. A case-only change ("old years" → "Old years") is
  allowed.
- No job is running (`jobs_running`), and no journal row is `planned` (run `dam recover`
  first).
- Works for attached and detached folders (a detached folder's rows keep the label too).
  A folder that is not connected can be relabelled: nothing on disk is touched.

### What is rewritten

The change runs inside `Host.close_and_reopen` (the archive closed, as snapshot restore
does), so the old App's scanner and watcher cannot write paths under the old label back
between the database step and the reopen; the 409 for a running job is checked before
closing. Without a Host (`dam` CLI) it runs on a closed App the same way.

Every value equal to the old label, or starting with `<old label>/`, is rewritten to the
new label (component match, NFC, case-insensitive on the first component, as
`label_of` matches):

Database, one transaction:

- `files.path`, `files.path_nfc`, `files.name` (only the folder's own top row, whose
  name is the label), `file_fts.path` (and `file_fts.name` of that row).
- `operations.src`, `operations.dst` (values starting with `abs:` are absolute and
  untouched), so earlier batches stay undoable and Activity reads right.
- `made_folders.rel`.
- `maintenance_ignored` keys that hold a path under the label (the builder checks which
  kinds store paths; the scout could not confirm).
- Not rewritten, because their paths lie in the main folder or are absolute:
  `ongoing_entries`, `ongoing_switched`, `collections.ongoing_rel`, link targets.
  Notes and checklist items point at ids, never at paths (`notes.KINDS` is file,
  collection, item).

Settings (`settings_write.write_keys`, verified read-back): the folder's
`extra_folders[].label`, and every `protected_paths` and `ai.exclude_folders` entry under
the old label.

Rule and tray files (`config/rules/*.yaml`, `config/trays/*.yaml`): the values of
`folder` and `folder_is` in rules, and any tray key the builder finds that names an
archive folder, when under the old label. Edited as text, not regenerated: for each
matching value, the exact scalar in the file is replaced (located through PyYAML's node
marks: `yaml.compose` gives each scalar's start and end position, so only those
characters change and comments and layout stay). After the edit the file is loaded again
and must equal the original with only those values changed; otherwise the file is left
as it was and the relabel is refused before anything is written. A `.bak-<time>` copy is
kept, as `write_config_file` does. A value written in a form the edit cannot handle
safely (a multi-line or folded scalar, an alias) refuses the relabel with the file and
line, so the owner edits it.

Name templates in rules (`folder: "Old years/{doc_date:%Y}"`) are matched on their literal
first component; a template whose first component is itself a placeholder is left alone.

### Order and failure

1. Dry run: compute every change (counts per table, files and their changed lines). The
   API returns it; nothing is written.
2. Take an automatic snapshot (`dam.snapshots`, from #75) of the database and settings,
   named "Before changing label 'X' to 'Y'".
3. Prepare the edited rule and tray file texts and verify each by loading (in memory).
4. Database transaction.
5. Settings write, then rule and tray files.
6. If 5 fails: rewrite the database back (the inverse rewrite, one transaction), restore
   any rule or tray file already written from its `.bak`, and report the error with the
   snapshot's name as the fallback.
7. The archive opens again (the end of `close_and_reopen`), with the new label.

Relabel is not an archive change (nothing on disk), so it has no journal batch; its undo
is a relabel back, and the snapshot is the safety net. Activity gets no entry. (My call.)

A main-folder top-level entry named like the old label was hidden (`main_rel_ok` checks
every label). After the relabel it becomes an ordinary main-folder entry and is indexed
on the next scan; the dry run says so when such an entry exists.

### API

- `POST /api/archive-folders/{label}/relabel` with `{label: str, dry_run: bool}`. The
  dry run answers with the counts, the rule and tray files and lines that change, and
  the warnings; applying answers with the same plus `restart_needed` as the other folder
  changes. 400 for the label rules, 409 while a job runs.
- `npm run gen:api` and commit `schema.d.ts`.

## Frontend

- Move preview: when the preview has `copy_across`, show its summary above the op list,
  and label the confirm button "Copy and move". Applying starts the job and shows a
  progress dialog (files, bytes, current file, Stop). The dialog can be closed; a small
  progress line stays in Browse until the job ends, and the result appears as a toast
  with Undo.
- Settings → Archive folders: **Change label** on each extra folder's row, with the dry
  run shown before applying.

## Tests (fake archives only; cross-disk simulated by patching `primitives.same_disk`)

Copy across:
- A file move copies, verifies, sets mtime, sends the original to its folder's To Delete,
  re-points the row (tags, a note, a collection, a tray item and a lock follow); undo
  restores both and the row points at the original with its original id.
- A hash mismatch (source changed after planning, or a corrupted copy) stops the batch:
  both files kept, the temporary copy named, the journal shows which.
- Stop in the middle of a multi-file move: every file fully moved or untouched; undo of
  the partial batch.
- App close mid-copy: the temporary file stays, the op failed with its name.
- Undo after the scanner indexed the original in To Delete: one row survives, the tagged
  one.
- Plans without `copy_across` (filing) still get the different-disks refusal.
- Drive ids: the copy with its own xattr id (rekeyed), a Drive-id source with an
  id-less copy (fresh `local:` id; the scan of the original in To Delete gives it a new
  row and takes nothing), a `local:` source (id kept).
- Refusals: a folder or link, a protected file, not enough space, offline folder,
  locked file.
- The extended `rekey`: the scanner's local-to-Drive-id rekey now keeps notes,
  collections and tray items.
- Crash recovery of a planned COPY_ACROSS row in each state.
- Restore to inbox across disks.
- `test_no_delete.py` unchanged and passing.

Relabel:
- Every table and settings key rewritten in one go; a case-only change; a detached
  folder.
- Rule file with comments: only the values change, comments and order stay; a folded
  scalar refuses with file and line; nothing written.
- Settings write failing after the DB step: the DB is back to the old label.
- An old batch under the label is still undoable after the relabel.
- Refused while a job runs or a row is planned.

## Docs

`CHANGELOG.md` under Unreleased (Added: copying between folders on different disks;
changing a folder's label), `docs/guide.md` ("Moving between folders" and a "Changing a
label" paragraph in the archive folders section), `docs/reference.md` (the new op kind,
the relabel endpoint, the job endpoints, the safety model: "nothing crosses disks"
becomes "a move across disks is a verified copy plus a move to To Delete"). The step 1
spec's status line points here.

## PR 2: folder moves

Designed and built separately: see `2026-10-26-folder-moves-design.md`. It settles the
questions found here (picking a folder, the identity check, the layout of a cross-disk
move, a second move after a stopped one, a source that changed, folder rows, links
inside a folder), and where the two differ, that spec wins for folders.

## Decisions

- Two pull requests: files and relabel first, folder moves second. (Owner, 2026-10-26)
- Copy across runs as a background job with progress and Stop. (Owner, 2026-10-26)
- Relabel edits rule and tray values in place, keeping comments and layout. (Owner,
  2026-10-26)

## Left to the builder

- Whether the copy job reuses `maintenance/jobs.py` or a shared runner.
- Which tray keys name folders, and which `maintenance_ignored` kinds store paths.
- Exact wording of messages, following the existing tone.
