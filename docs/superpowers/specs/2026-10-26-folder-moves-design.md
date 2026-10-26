# Folder moves (archive folders step 2, PR 2)

Status: proposal 2026-10-26, waiting for the owner's corrections. Builds on PR 1 (#85,
copy across for files), whose spec is `2026-10-26-archive-folders-step-2-design.md`;
read its "Part 1: copy across" first. Where the two differ, this one wins for folders.

## Intent

The owner wants to move the old years (whole folders of several GB) out of the synced
main folder onto the external disk, by dragging a year folder in Browse, and to tidy
folders within one disk the same way. Browse refuses every folder today
(`services/browse.py` `_move_ops`: "folders cannot be moved yet").

## Goals

- Move one folder at a time in Browse, by drag or Move to…, behind the usual preview and
  confirm, with Undo.
- On one disk: one rename, synchronous, exactly like a file move.
- Across disks: every file is a verified copy (PR 1's COPY_ACROSS), and only when all of
  them are copied does the whole source folder go to its own folder's To Delete, in one
  move. Background job with progress and Stop.
- A stopped move leaves the source folder whole; moving it again finishes the job
  without duplicates.
- Tags, notes, collections, tray items and locks follow every file; a folder's own
  collection memberships and notes follow the folder.

## Non-goals

- Moving several folders in one go, or folders and files together. (One folder per
  move; select files inside it to move files.)
- Link or Copy of a folder (the drop modes stay files only).
- Renaming a folder in place (Edit details stays files only).
- Restore of a folder from To Delete across disks (stays refused, as in PR 1).
- Copying links across disks (see "Links").
- Resuming a stopped job. Moving again is the resume (see "A second move").

## Anti-goals

- A file that is in To Delete but whose copy was never verified (a file added to the
  source during a long job, then swept to To Delete with the folder).
- A stopped move that leaves the owner with two half folders and no clear way on.
- The original folder in To Delete taking the folder rows (and so its collections) back
  on the next scan.

## 1. Picking a folder (UI)

- Folder rows become draggable. A drag from a folder row carries only that folder,
  never the checked files with it. It drops where files drop: a folder row, the other
  pane, a breadcrumb.
- The panel shown when the cursor is on a folder (one pane) gets **Move to…**, with the
  same folder picker as files.
- A folder drop offers Move only: the Link / Copy choices are not shown, and Option
  (Alt) does nothing.
- Refused before the preview, with a plain message: the root of an extra folder, the
  special folders (`##. Ongoing`, `##. Important`, To Delete, the inbox) and anything
  inside Ongoing or To Delete; a folder dropped into itself or into its own subfolder;
  a folder that is not connected; a top-level folder that would be created in the main
  folder (as today, needs `allow_top_level`, which this never sets). (My call.)
- The confirm says "Move folder" on one disk and "Copy and move" across disks.

## 2. Identity check for a folder

`check_disk_identity` gets a folder case, used when the requested row is a folder
(`kinds` gains nothing; the op is still a MOVE):

- Drive id row: the id the planner read from the folder on disk equals the row's.
- `local:` row: the folder on disk carries no Drive id, or only one belonging to
  another indexed entry (as for files).
- Always: `lstat` says a real folder (not a link, not a file).
- No size check (folders have none).

The files inside are not checked against the index: the planner lists them from disk,
and each COPY_ACROSS reads its hash at act time, as in PR 1.

## 3. On one disk

One MOVE of the folder, as the op layer already does (rename, `repo.update_path`
re-paths the folder row and everything under it, undo is a MOVE back with `exact`).
Locks and protected paths inside the folder are already handled by the planner
(`_check_locked` looks at "is, holds or lies inside"; `_track_protected`).

A taken name at the destination gets `_2` (`2009_2`), as for files. **Open: see
question 1 at the end.**

## 4. Across disks: the layout

`Plan.copy_across` already set by `BrowseService._drop`. In `Planner._relocate`, a MOVE
of a folder across disks (today `different_disks_message`) expands to:

1. MKDIR the destination folder (`Old years/2009`) and every subfolder, parents first,
   including empty ones. These MKDIRs are flagged `made` (as a New folder batch), so
   undo removes them again while they are empty and still the folder made.
2. One COPY_ACROSS per file, in tree order, each into its mirrored place. No QUARANTINE
   after each one (unlike a file move).
3. One QUARANTINE of the whole source folder into its own folder's To Delete
   (`##. To Delete/2009`, the existing `_quarantine_folder`), note `copied to <dst>`,
   carrying the planned tree (below).

What is copied:

- Regular files, dot files included, except `.DS_Store` (Finder makes it again; the
  original goes to To Delete with the folder).
- A `.dam-copy-*` file in the source refuses the move: "Remove the unfinished copy
  <name> first."
- Links: not copied (see 7).
- A protected entry anywhere inside refuses the move (its original could not go to To
  Delete), as for files.
- Free space: the whole tree's size, checked in the preview (`_check_space`) and per
  file by `copy_file`.

Stop and app close work as in PR 1, between files. Because the per-file pair is gone,
Stop can end the batch after any copy; the final QUARANTINE runs only when every
COPY_ACROSS before it is done. A stopped batch leaves the source folder whole and the
destination holding the copies made so far.

The index follows per file as in PR 1 (`_repoint_copy`): each copied file's row moves
to the copy at once. So after a stop the tagged rows sit at the copies, and the
originals still in the source are indexed by the next scan as new, bare rows. (My
call: it reuses PR 1 unchanged, and the second move below then sends those originals to
To Delete with the folder.)

The preview's `copy_across` summary gains: folders made, files already at the
destination (skipped, see 5), links left behind (7), and the destination folder's name.

## 5. A second move after a stopped one (merge)

When the destination folder already exists across disks, the move merges into it
instead of making `2009_2`:

- Subfolders that exist are reused (no MKDIR); missing ones are made.
- A file whose name is free is copied.
- A file whose name is taken by a regular file with the same size and modification time
  (a copy sets the mtime to the source's) is planned as "already copied": a COPY_ACROSS
  with `method="present"`. At act time it reads both hashes and compares; equal: done,
  nothing is written, journaled like any op; different: the batch stops there, before
  the final QUARANTINE, with "<name> at the destination differs from the original;
  nothing more was moved."
- A file whose name is taken by something else (other size or mtime, a folder, a link)
  is copied under `_N`, with the collision note.
- The preview says "2009 exists in Old years already: N files are there already and are
  skipped, M are copied."

Undo of a "present" op does nothing (the copy belongs to the earlier batch, whose own
undo moves it). Its index step re-points the row as a normal COPY_ACROSS would, only if
the row is still at the original (it is not, after a stop, since the first batch moved
it).

This also applies when the existing folder was not made by dam (a year folder the owner
already has on the other disk): the files are added to it. **Open: see question 1.**

## 6. The source changed during a long job

- A file edited before its copy: copied as it is then (the hash is read at act time, PR
  1).
- Anything else: the final QUARANTINE's precheck walks the source folder again and
  compares it with the planned tree: the same entries (names and kinds), and each
  copied file with the size and mtime its COPY_ACROSS read when it was copied. On any
  difference (a file added, removed, renamed or edited after its copy) the batch stops
  before the QUARANTINE: nothing goes to To Delete, the copies stay, and the message
  names up to five differences: "2009 changed during the move (a.pdf was added). It
  stays where it is; move it again to copy the rest."
- Moving again then copies only what is new (5); an edited file whose copy is stale
  differs in mtime, so it is copied as `a_2.pdf` next to the stale copy, and the preview
  says so. (My call: the stale copy is never overwritten.)

## 7. Links

- On one disk: links move with the folder (a rename). A link made by dam has an absolute
  target; one inside the folder that points into the same folder then points to nothing,
  as a link to any moved file does today.
- Across disks: links inside the folder are not copied. They go to To Delete with the
  original folder. The preview lists them: "2 links are not copied; they go to To Delete
  with the folder." (My call: an external disk may not support links at all, exFAT
  does not, and a failed link would stop the batch half way.)
- Links elsewhere that point into the moved folder: Ongoing and Important links follow
  through their sync (by drive id), as for files. Other links (Link drops) then point to
  nothing; the preview warns with their count and up to five names, found from the
  index's link rows. Not refused.

## 8. Folder rows

- One disk: `update_path` moves the folder row and every row under it; undo moves them
  back. Nothing new.
- Across disks: after the final QUARANTINE acts, and before its own index step, every
  folder row of the source tree follows to its mirrored destination folder: each is
  rekeyed (the destination folder's own Drive id if it has one, else a fresh `local:` id
  when the row had a Drive id, else kept, the same rule as `_repoint_copy`) and
  re-pathed. So the folder's collections and notes follow the folder, and the original
  folder in To Delete is a stranger to them on the next scan. A row the scanner already
  made for a destination folder (it was MKDIR'd earlier in the job) is dropped first,
  unless it has attachments, as `_restore_row` does.
- Undo: the QUARANTINE's inverse (MOVE back from To Delete) gets a matching step that
  re-points each folder row back to its source path and journaled id. Then the copies go
  to the other disk's To Delete (PR 1), then the made folders are removed while empty.
- Crash recovery: a done QUARANTINE whose rows did not follow runs the follow step, as
  `recover()` runs `_repoint_copy` for a COPY_ACROSS.

## Undo, summarised

- One disk: a MOVE back (exists).
- Across disks, newest first: the folder back from To Delete (rows follow back), each
  copy to the destination's To Delete (rows go back to the originals), each made folder
  removed while still empty and the folder made; a non-empty one stays and the result
  lists it, as for a New folder undo.
- A stopped batch undoes the same way, without the first step.
- Undo of a big batch is renames only and stays synchronous (PR 1).

## Messages and Activity

- Activity: "Moved folder 2009 to 'Old years'" (one disk: "Moved folder 2009 to 80.
  Misc").
- Job result: "Copied 812 of 1 240 files; 2009 stays in place until all are copied" on
  Stop; "Moved folder 2009 (1 240 files) to 'Old years'" when done.

## Tests (fake archives only; cross-disk by patching `primitives.same_disk`)

- One disk: folder moved, rows (folder and files, a collection on the folder) follow;
  undo; a taken name (per question 1); refusals (root, special folders, into itself,
  locked file inside, offline).
- Across disks: tree with nested and empty subfolders copied, mtimes kept, source in To
  Delete, every file row and folder row followed (tags, a note on a file, a collection
  on the folder); undo restores all and removes the made folders; a non-empty made
  folder stays.
- Stop half way: source whole, copies and rows at the destination; move again: the
  copied files are "present", the rest copied, source to To Delete, no `_2` files.
- A "present" file whose hash differs: stops before the QUARANTINE.
- Source changed: a file added, an edited file after its copy, a file removed; each
  stops before the QUARANTINE with the message; nothing in To Delete.
- Links inside left behind and listed; a Link-drop link elsewhere warned about.
- `.dam-copy-*` in the source refused; `.DS_Store` not copied; a protected entry inside
  refused; not enough space refused.
- Identity check: folder replaced by a file or link since planning; Drive id changed.
- Crash recovery of the final QUARANTINE with rows not followed.
- `test_no_delete.py` unchanged.

## Docs

`docs/guide.md` "Moving between folders" (the "only files" sentence goes; folders on
one disk and across), Browse's drop table (folder rows); `docs/reference.md` (the folder
case of the move endpoints and the identity check, the `present` method, the folder
summary fields); `CHANGELOG.md` Added: moving folders in Browse, on one disk and to
another disk.

## Open questions for the owner

1. **A taken name on one disk.** Across disks the move merges into an existing folder
   (needed so a stopped move can be finished). On one disk I propose `2009_2`, as for
   files, because a rename has no stopped state and merging on one disk means moving
   each file separately and leaving an empty source folder to send to To Delete. The
   cost: the same drop gives `2009_2` on one disk and a merge across disks. The
   alternative is merging on both.
2. Links across disks left behind in To Delete (7), rather than recreated.
3. Per-file index follow during the job (4), rather than all rows at the end.

## Left to the builder

- How the planned tree travels to the final QUARANTINE's precheck (a field on the
  `ResolvedOp`, updated from each COPY_ACROSS's snapshot).
- Exact message wording, in the existing tone.
- Whether the folder drag reuses `setDragFiles` with a folder flag or a new payload.
