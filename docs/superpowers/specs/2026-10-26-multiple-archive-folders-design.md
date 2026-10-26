# Multiple archive folders: design

Status: step 1 built (2026-10-26); step 2 (copy across, relabel) not built.

## Intent

Some owners keep their documents in more than one place: a synced cloud folder (iCloud
Drive, Google Drive) for current papers and an external disk for the old years, for
example. Today an archive is exactly one folder. This feature lets one archive span
several folders, possibly on different disks or cloud services, so search, Browse, tags,
collections and Maintenance see one combined archive.

The folders may not overlap: no folder may be, contain or sit inside another folder of
the same archive or of any other archive profile.

## Terms

- **Main folder**: today's `archive_root`. It keeps the special folders (`##. Organize`
  inbox, `##. Ongoing`, `##. Important`, `##. To Delete`) and every path the index
  already stores.
- **Extra folder**: a further folder joined to the archive. It has a **label**, which
  is the name it appears under at the top of Browse.

## Path model

Archive-relative paths stay the single currency of the index, the journal and the API.
A path whose first component is an extra folder's label belongs to that folder; every
other path belongs to the main folder:

```
Taxes/2024/assessment.pdf        -> <main>/Taxes/2024/assessment.pdf
Old years/2009/car/invoice.pdf   -> <extra "Old years">/2009/car/invoice.pdf
```

Only `ArchivePaths` (`core/paths.py`) knows about this. `abs()` maps the first
component to the right folder, and `rel()` tries each folder's resolved root. All other
code keeps calling `rel()`/`abs()` as now. `ArchivePaths.root` is replaced by
`roots` (label to path, the main folder under `""`), plus a `root_of(rel)` helper for
the few callers that need the real folder (watcher, scanner, executor link targets).

Nothing stored today changes: the main folder's paths have no prefix, so no data
migration of `files`, `operations` or the publisher tables is needed.

## Settings

`settings.yaml` gets a list next to `archive_root`:

```yaml
archive_root: ~/Library/Mobile Documents/com~apple~CloudDocs/Archive
extra_folders:
  - label: Old years
    path: /Volumes/Archive disk/Archive 2000-2015
```

It is written through `settings_write.py` like the other settings, never edited by
the operation layer.

## Adding an extra folder

Settings gets an **Archive folders** card: the main folder, each extra folder with its
label, path and status, and **Add folder**. Adding one checks, in this order, with a
plain message for each refusal:

1. **Overlap.** `profiles.related()` (already used by `root_conflict`) against the main
   folder, every other extra folder, every profile's folders and data folders, and the
   app's own data folder. "same", "inside" and "around" are all refused. The comparison
   is on resolved real paths, case-insensitive where the file system is.
2. **Label.** Not empty, one plain name (the rules in `foldernames.py`), not starting
   with `##.`, unique among labels, case-folded and NFC, and not the name of an
   existing top-level entry in the main folder.
3. **Readable.** The folder can be listed now.

Then the folder is scanned like the main folder after first run (throttled indexing,
Drive ids read where present). Adding a folder changes nothing on disk.

**Label clashes later.** The operation layer refuses to create, move or rename a
top-level entry in the main folder whose name equals a label. If one appears from
outside dam (Finder, sync), the extra folder wins in Browse. The clashing main-folder
entry is not indexed, and Maintenance reports it with the fix: rename it or change
the label.

**Changing a label** (build step 2; in step 1 the label is fixed when the folder is
added, because labelled paths also live in rule and tray files) rewrites the prefix of every stored path under it in one database
transaction (index, journal, publisher tables, collections). It touches nothing on
disk, except that app-made links pointing into that folder are unaffected anyway
because link targets are absolute (`Executor.link_target`).

## Detaching an extra folder

**Detach** removes the folder from the archive and touches nothing on disk. Its entry
stays in `settings.yaml` with `attached: false`, so Settings can offer **Attach again**
and Maintenance can recognise links into it. Its index
rows are kept and marked missing, exactly as when the folder is offline, so attaching
the same folder again (same label) brings back tags, notes and collection memberships.
**Also forget** on the Detach confirmation (or **Forget** on a folder that is already
detached), which names the number of files, purges them with everything given to those
files and removes the entry from the settings, so the label is free again. App-made links in `##. Ongoing` / `##. Important` that
point into it are left alone. Maintenance lists them as pointing into a detached folder.

## Offline folders

This is the main risk for real data: an unplugged disk or a cloud folder that is not
mounted must never look like deleted files.

- **Availability is per folder.** A folder is *connected* when its root can be listed
  and it does not list nothing while the index has rows under its label
  (`core.paths.folder_connected`). The scanner already aborts without marking anything missing when
  the root cannot be listed. That rule moves from "the archive root" to "each folder's
  root": a scan of the whole archive scans each connected folder and skips the others
  completely.
- **Status changes** are detected by a local check (no network) at each scan tick and
  when the watcher reports an unmount. On reconnect, the folder gets an incremental scan.
- **Watcher**: one watchdog schedule per connected folder. A schedule whose folder goes
  away is dropped and added again on reconnect.
- **What the owner sees**: in Browse the folder's row carries a "Not connected" mark,
  and the file view names the folder. Its files stay in search results and collections, marked as not connected; opening
  or previewing them gives a plain message. Inbox counts and Today are unaffected
  because the inbox lives in the main folder.
- **Search**: a new `is:disconnected` value (in `query.IS_VALUES`) finds the files of
  every folder that is not connected now, and `-is:disconnected` leaves them out. It
  combines with the other filters, for example `in:"Old years" is:disconnected tag:car`.
  Files of a detached folder are marked missing and are not found at all.
- **Operations**: planning refuses any operation whose source or destination is in a
  folder that is not connected, with the folder's label and path in the message. Undo of
  such a batch waits until the folder is back.
- **Publisher**: `ongoing sync` must not repair, replace or report as broken any link
  whose target lies in a folder that is not connected. Maintenance shows those links as
  "folder not connected", not "missing".
- **Main folder offline**: as today, the app shows the archive as not available. Extra
  folders are not usable on their own, since the inbox and special folders live in the
  main folder.

## To Delete in every folder

Moving a file to To Delete is a rename, and a rename cannot cross disks. So each extra
folder gets its own `##. To Delete`, created on demand at its top
(`Old years/##. To Delete/<path inside the folder>`). **Move to To Delete** on a file in
an extra folder uses that folder's To Delete. **Restore** moves it back within the same
folder. The To Delete views and Maintenance list all of them together, grouped by
folder. Emptying them is still the owner's job.

`##. Ongoing`, `##. Important` and the inbox stay in the main folder only. A folder
with one of those names inside an extra folder is an ordinary folder.

## Moving between folders

Within one folder (or between folders on the same volume) a move stays a rename.
Between volumes the rename fails with `EXDEV` and `move_between_folders` already turns
that into a plain `OpFailed(DIFFERENT_DISKS)`. **Build step 1 stops there:** a
cross-disk move is refused in the dry run with a message that names both folders.

Build step 2 adds a new operation kind, **copy across**, with dry run, journal and undo
like every other kind:

1. Hash the source (`file_sha256`) and journal the hash with the plan.
2. Copy to the destination with exclusive create and fsync, then check size and hash
   (`copy_picture` already does this for rule pictures; it is generalised).
3. Move the original into its own folder's `##. To Delete`, keeping its path, with
   a note saying where the copy went. Nothing is deleted.
4. Re-point the index row (same `drive_id` where the id is `local:`; a new Drive id
   is taken from the copy's xattr if it has one) so tags, notes, collection memberships
   and links follow the file. App-made links to the old path are re-pointed by the
   publisher.

**Undo** moves the original back from To Delete (a rename on its own volume) and moves
the copy into the destination folder's To Delete. Both steps are renames, so
`test_no_delete.py` needs no new allowed call.

Folders move the same way, file by file inside one batch. If any file fails
verification, the batch stops: files already copied stay in both places, and the
journal shows which ones.

## Cloud folders

iCloud Drive and Google Drive in streaming mode keep files cloud-only. Indexing reads
each file, which downloads it, as already documented under "Cloud drives" in
`docs/reference.md`. That now applies per folder. Drive ids are read on macOS and Linux
for Google Drive folders only. iCloud files get `local:` ids, so a move made in Finder
inside an iCloud folder is followed by path and content as today.
Copying a cloud-only file across first downloads it, and the dry run says so.

## Profiles

`root_conflict` and `root_problems` in `profiles.py` take every folder of every profile
into account, so two profiles can never share or nest folders.

## Platforms

Nothing here is macOS-only. On Windows an extra folder on another drive letter is a
different volume (the copy across applies), and links into it need Developer Mode as
links do today. Paths in settings are stored as given and resolved at start.

## Tests

All with temporary fake archives: a main folder and one or two extra folders in
separate temp directories.

- Path mapping: `abs`/`rel` round trips, label case-folding and NFC, escapes refused
  per folder, a path under one folder never resolving into another.
- Add folder: each overlap case (same, inside, around, against another profile, against
  a data folder), each label rule, the main-folder top-level clash.
- Offline: rename the extra folder away and scan. Nothing is marked missing, operations
  touching it are refused, publisher sync plans nothing for its links. Rename it back
  and the incremental scan restores it.
- Detach and attach again keeps tags, notes and memberships. Forget purges.
- To Delete and Restore in an extra folder stay inside that folder.
- Cross-disk: simulate `EXDEV` by patching `rename_excl`. Step 1 refuses in the dry
  run. Step 2 copies, verifies, moves the original to To Delete, re-points the row,
  and undo restores both. A hash mismatch stops the batch with both files kept.
- Label change rewrites every stored prefix in one transaction.

## Build steps

1. **Extra folders without cross-disk moves.** Settings and API, path mapping, add and
   detach with the overlap and label checks, per-folder scanning and watching, offline
   handling, To Delete per folder, Browse and Maintenance showing folder status, profile
   checks. Cross-disk moves are refused with a plain message. Usable on its own: files
   on the external disk are searchable and can be tagged, collected and filed within
   that disk.
2. **Copy across and relabel.** The new operation kind with dry run, journal and undo,
   and changing a folder's label.

Both steps need a `CHANGELOG.md` entry, a guide section and a reference section
(settings key, API, safety model update for per-folder To Delete).

## API

Paths keep the label prefix, so every existing endpoint works unchanged. Every file
and folder record the API returns (Browse, search, collections, trays, the file view)
also gets two fields, so the frontend never parses labels out of paths:

- `folder`: the extra folder's label, or `null` for the main folder.
- `connected`: whether that folder is connected now (always `true` for the main folder
  while the app runs).

A new `GET /api/archive-folders` lists the main and extra folders with label, path,
status and file count. `POST /api/archive-folders` (add),
`POST /api/archive-folders/{label}/detach` (with `forget: true` to purge index entries)
and `POST /api/archive-folders/{label}/attach` all take `dry_run` and answer with what
would change, like the other settings endpoints. Relabel comes with build step 2. After these changes `npm run gen:api`
regenerates `schema.d.ts`.

## Decisions

- The API exposes `folder` and `connected` explicitly (above), not just the path
  prefix. (2026-10-26)
- A disconnected folder's files stay visible in search and collections, marked as not
  connected, and `is:disconnected` finds them. (2026-10-26)
