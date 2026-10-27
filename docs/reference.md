# Digital Archive Manager: technical reference

Installing dam, the command line, the config files, the API details and the safety
internals. For how to use the app, see the [user guide](guide.md) (also under **Help** in
the app's sidebar).

## Contents

- [Requirements](#requirements)
- [Setup](#setup)
- [Platform support](#platform-support)
- [The data folder and first run](#the-data-folder-and-first-run)
- [The demo archive](#the-demo-archive)
- [Running dam](#running-dam)
- [Command line](#command-line)
- [Several archives](#several-archives)
- [Several archive folders](#several-archive-folders)
- [Snapshots](#snapshots)
- [Config and rules](#config-and-rules)
- [Tray files](#tray-files)
- [Reminders setup](#reminders-setup)
- [AI setup](#ai-setup)
- [Moves across disks](#moves-across-disks)
- [Folder moves](#folder-moves)
- [Safety model in detail](#safety-model-in-detail)
- [Maintenance](#maintenance)
- [Index errors](#index-errors)
- [Open, reveal and previews](#open-reveal-and-previews)
- [Logs](#logs)
- [Cloud drives](#cloud-drives)
- [Development](#development)

## Requirements

dam runs on **macOS, Windows and Linux** (Python 3.14+, see "Platform support" below for
what works where).

- [uv](https://docs.astral.sh/uv/) for `backend/` (it installs the right Python itself).
  Install: macOS/Linux `curl -LsSf https://astral.sh/uv/install.sh | sh` (or
  `brew install uv`); Windows `winget install --id=astral-sh.uv -e` (or
  `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`).
- Node as in `frontend/.nvmrc` (24; 22 also works), for `frontend/`.
- Optional, for scanned documents and photos on Windows and Linux: **Tesseract OCR**
  (macOS uses Apple Vision and needs nothing). Install the program plus the language data
  for the languages in `ocr_languages` (English by default; add e.g. `fi-FI` for Finnish):
  - Linux: `sudo apt install tesseract-ocr` (more languages: `tesseract-ocr-fin` and so
    on; Fedora: `sudo dnf install tesseract tesseract-langpack-fin`)
  - Windows: `winget install --id UB-Mannheim.TesseractOCR`, tick any extra languages
    in the installer, and make sure the install folder (usually
    `C:\Program Files\Tesseract-OCR`) is on `PATH`

  Without it, scanned PDFs and images are indexed as "unsupported: no OCR engine
  installed"; everything else works, and PDFs with a text layer need no OCR.
- Optional, for Outlook `.msg` e-mails: the `msg` extra, `uv sync --extra msg` (or
  `pip install "dam[msg]"`). It pulls in `extract-msg`, which is GPL-licensed, so it is
  not part of the core install. Without it `.msg` files are indexed as unsupported with
  the reason "Outlook .msg files need the optional package: install dam[msg]".

## Setup

```sh
cd backend && uv sync                     # add --extra msg for .msg support
cd ../frontend && npm ci && npm run build   # dam serve serves frontend/dist
```

The same commands work in PowerShell on Windows. Run the program with `uv run dam ...`
from `backend/`.

## Platform support

| | macOS | Windows | Linux |
|---|---|---|---|
| Install, index, search, file, undo, collections, export, reminders by e-mail | yes | yes | yes |
| OCR of scans and photos | Apple Vision (no Finnish) | Tesseract, optional | Tesseract, optional |
| Google Drive item ids (`xattr`) | yes | no: files keep a local identity (moved or renamed outside dam, Maintenance reconnects them) | no (no Drive client) |
| Open / Show in folder | `open`, `open -R` | default app, Explorer | `xdg-open` (reveal opens the folder) |
| Quick Look thumbnails of any file | yes | no: PDF pages and images still render | no: same |
| Desktop notifications | yes | not yet | not yet |
| Daily reminder job (`dam remind --install`) | LaunchAgent | not yet: schedule `dam remind` with Task Scheduler yourself | not yet: a systemd user timer or cron yourself |
| Links in `##. Ongoing` / `##. Important`, and **Link** on a drop in Browse | yes | needs Developer Mode (otherwise refused with a clear message; Browse turns Link off) | yes |
| `.msg` e-mails | `dam[msg]` | `dam[msg]` | `dam[msg]` |

Windows and Linux install and pass the test suite in CI (macOS, Windows and Ubuntu), and
degrade with a plain reason where a feature is missing; full parity with macOS is not
there yet. Unknown file junk such as `.DS_Store`, `Thumbs.db` and `desktop.ini` is ignored
by the index and never deleted.

Two Windows details. Links need Developer Mode (or an administrator account); CI runs the
link tests on a Windows runner that has the privilege. And a folder in `##. Ongoing` /
`##. Important` that holds a Finder `.DS_Store` is left in place when its collection is
closed or undone: dam only deletes that file through an open folder handle (to be sure it
is the very file it checked), which Windows cannot do. Drive for desktop does not sync
`.DS_Store`, so this only matters for an archive that was copied over by other means.
Settings and other text files are read and written as UTF-8, and an existing Windows
(CRLF) line ending is kept when dam edits a file.

## The data folder and first run

State lives in the data folder, never in the archive: the SQLite database, caches, logs
and config (one data folder per archive: see "Several archives" below). Default:
`~/Library/Application Support/DigitalArchiveManager/` on macOS,
`%LOCALAPPDATA%\DigitalArchiveManager` on Windows and
`~/.local/share/DigitalArchiveManager` on Linux (the platform's user data folder). Override
with the `DAM_DATA_DIR` environment variable or `dam --data-dir <dir> ...` (the flag goes
before the command). To keep a test archive apart from your real one, add a second archive
instead of juggling data folders.

On first use `config/settings.yaml`, `config/rules/`, `config/trays/` and
`config/filing_codes.yaml` are seeded from `defaults/`. The defaults contain nothing personal and **no archive folder**: dam never
guesses where your documents are. You choose the folder once, either on the app's
first-run screen (see the user guide) or with **`dam init`** in a terminal.

`dam init` looks for cloud-drive folders on your computer (Google Drive, OneDrive,
Dropbox, iCloud Drive, Box, Nextcloud, pCloud, Insync), lists them with their provider
names, lets you pick one and then the folder inside it (or create one), shows the one line
it will write to `config/settings.yaml`, and asks before writing it. For scripts:
`dam init --archive PATH [--yes]`; with `--layout household|minimal|empty` (and
`--numbered/--no-numbered`) it also starts a new archive there, without questions.
Interactively, an empty folder asks "Start a new archive here?", then which layout,
numbering, the special folder names and edits to the list (`r 3 New name`, `d 3`,
`a Name`), shows every folder and asks before making them.

The folder must exist, be readable and writable, and not be your home folder, the top of
a disk or inside dam's own data folder. Until one is set, every other command stops with
"No archive folder configured yet" and exit code 1.

The starter layouts are data files, `defaults/layouts/*.yaml` (one folder list, example
rules and the folders kept from the AI per file): add your own beside them. The special
folder names you choose are written to `special_folders` in `settings.yaml` (and
`protected_paths` follows a renamed Important folder).

## The demo archive

A throwaway demo archive with about a dozen fake files and its own data folder. It touches
nothing else (the target must not exist or be empty). It has:

- an electricity bill whose due date is already past;
- a water bill scanned as an image, with a Finnish bank barcode printed at its foot (the
  index reads it back);
- a `##. Ongoing` with two links, a real folder and a real file;
- a collection, **2026 House sale**, with nested groups (`Paperwork › Bank`,
  `Paperwork › Taxes`, `Photos`) and one member still in the inbox, already published as
  group subfolders in `##. Ongoing/2026 House sale/`.

```sh
cd backend
uv run python -m dam.demo /tmp/dam-demo
uv run dam --data-dir /tmp/dam-demo/data serve --port 8766
```

The demo uses another port than the default 8765, so it never collides with your own
`dam serve`. The demo settings turn macOS notifications off (`reminders: {mac: false}`);
never run `dam remind --install` against the demo, and do not copy its settings to a real
data folder. Then open http://127.0.0.1:8766 if it did not open itself. `frontend/README.md`
has a walkthrough. Remove `/tmp/dam-demo` afterwards.

The app can also make a demo archive: **Add archive… → Create a demo archive**.

## Running dam

```sh
cd backend && uv run dam serve          # scans, watches and indexes in the background
```

Options: `--port N` (default `server_port`, 8765), `--no-open`. Ctrl+C stops it cleanly.

`dam serve` opens the browser on a sign-in link, `http://127.0.0.1:<port>/auth?t=<token>`,
which signs that browser in and redirects to the start page (so the token is not left in
the address bar or the history). With `--no-open` it prints that link once instead. Only
a signed-in browser can use the app: see **Local-only API** under
[Safety model in detail](#safety-model-in-detail). `dam open` opens the link for the
`dam serve` that is running (it reads the port from `serve.json`); `dam open --print`
prints it. A bookmark to `http://127.0.0.1:<port>/` keeps working in a browser that is
signed in; in another browser the page says **Not signed in** and how to sign in.

If the archive folder is not there (the cloud drive not running or signed out, or a wrong
`archive_root`), every command except `dam openapi`, `dam remind`, `dam trays` and
`dam collections` (which read only the database) stops with exit `1` and says so;
`dam serve` does not start. An archive that disappears while `dam serve` runs is never
taken for an empty one: scans are skipped (nothing is marked missing), a warning is
logged, `/api/status` reports `archive_available: false` and the UI shows a banner.

`dam serve` without a built frontend (`frontend/dist/index.html`) prints
"frontend not built — run `cd frontend && npm ci && npm run build`", serves only the
API and does not open the browser.

## Command line

| Command | Purpose |
| --- | --- |
| `dam --archive NAME-OR-ID ...` | Use another archive (also `DAM_ARCHIVE`); without it the archive in use is taken. The flag goes before the command |
| `dam init` | Choose the archive folder, optionally start a new archive there |
| `dam archives list` | The archives dam knows; `*` marks the one in use |
| `dam archives add NAME [--color C] [--folder PATH] [--demo]` | Add an archive and set it up (the `dam init` questions, or `--demo` for the fictional demo archive in `--folder`) |
| `dam archives switch NAME` / `rename OLD NEW` / `color NAME #RRGGBB` | Make an archive the one in use; rename it; change its colour |
| `dam archives forget NAME [--switch-to OTHER]` | Remove an archive from the list; nothing is deleted, the paths are printed |
| `dam archives where NAME` | Print an archive's data folder and archive folder |
| `dam scan` | Sync the file index with the archive |
| `dam index [--limit N]` | Extract text / OCR for files not yet indexed, and read page 1 of inbox files (older documents get theirs in the background) |
| `dam errors [--all] [--retry]` | List the files whose text could not be indexed, with the reason (`--all`: also unsupported files); `--retry` queues every listed file for indexing again |
| `dam inbox` | List inbox files with suggested name, folder and sources |
| `dam add FILE... [--yes]` | Copy files into the inbox (the originals stay) |
| `dam file PATH-OR-DRIVE-ID --folder F [--name N] [--tag T]... [--dry-run] [--yes]` | Rename, move and tag one file; shows the plan and asks first unless `--yes` |
| `dam search QUERY [--folder F] [--limit N]` | Full-text search |
| `dam move PATH-OR-DRIVE-ID... --folder F [--dry-run] [--yes]` | Move files (not folders) into another archive folder, names kept (`_2` on a collision); not from or into `##. Ongoing`, nor into `##. To Delete`. Shows the plan and asks first unless `--yes`; undo with `dam undo` |
| `dam quarantine PATH-OR-DRIVE-ID... [--dry-run] [--yes]` | Move to To Delete (into `##. To Delete`) |
| `dam activity [--limit N]` | Recent batches of operations |
| `dam undo BATCH-ID [--yes]` | Revert a batch |
| `dam recover` | Settle operations interrupted by a crash (reads the disk, changes no archive files) |
| `dam openapi` | Print the API's OpenAPI schema |
| `dam open [--print]` | Open the running app in the browser and sign the browser in; `--print` prints the sign-in link instead. Changes nothing; exit `1` when no `dam serve` is running |
| `dam trays [--tray ID] [--done]` | List the items in each tray |
| `dam collections [--closed]` | List collections with member count and `##. Ongoing` status |
| `dam ongoing sync [--dry-run]` | Bring `##. Ongoing` in line with the open collections |
| `dam ongoing entries` | List the top-level entries of `##. Ongoing` (managed or convertible) |
| `dam star PATH-OR-ID…` / `dam unstar …` / `dam starred` | Mark, unmark and list ★ Ongoing files |
| `dam important PATH-OR-ID… [--group "Houses/Hillside"]` / `dam unimportant …` / `dam important --list` | Mark, unmark and list ! Important files |
| `dam remind [--now T] [--dry-run]` | Send the reminders that are due; `--dry-run` only lists them |
| `dam remind --install` / `--uninstall` / `--set-email-password` | Daily LaunchAgent; e-mail password (see Reminders setup) |
| `dam remind --test-notification [--dry-run]` | Send one test message through each enabled channel; marks nothing |
| `dam ai --set-key` / `--clear-key` / `--status` / `--log` / `--on` / `--off` | AI key, status, call log and switch (see AI setup) |

Exit codes: `0` success; `1` user error (unknown file, invalid request, guard refusal,
declined confirmation); `2` command line usage error; `3` internal error (traceback in
`logs/`); `4` a batch problem (an operation failed, index error or tagging error).

`dam move` is the same move as a drop on a folder in Browse:

```sh
uv run dam move "40. Family/beach.jpg" --folder "30. Home" --dry-run   # show the plan
uv run dam move "40. Family/beach.jpg" --folder "30. Home"             # asks, then moves
uv run dam undo <batch id>                                             # from dam activity
```

## Several archives

On the command line: `dam archives add Test` (the same questions as `dam init`) or
`dam archives add Demo --demo --folder ~/Documents/Demo`. `dam archives switch Test`
changes the one `dam` uses by default, and `dam --archive Test scan` (or
`DAM_ARCHIVE=Test`) uses another for one command.

In the app the switch happens in the same window and the same server: the scanner,
watcher, indexer and reminder check of the archive you leave are stopped first, then the
other archive's start, so two archives' background work never runs at the same time.
Every change the page asks for names the archive it shows (`X-Dam-Archive`); a window
left open on the old archive after a switch is refused with a clear message (409) instead
of changing the wrong archive.

**Run two at once**: `dam serve` serves one archive. Start another with its own port:

```sh
dam serve                              # the archive in use, port from its settings
dam --archive Test serve --port 8766   # the Test archive, side by side
```

Each served archive holds a lock file in its data folder (`serve.lock`); a second
`dam serve` (or a switch in the app) for an archive that is already open somewhere else
is refused and tells you the port. The sign-in cookie carries the port in its name
(`dam_auth_<port>`), so signing in to one server never signs the browser out of another.

Commands that change an archive hold the same lock while they run, so the app and a
command (or two commands) never write one archive at the same time. `serve.json` beside
the lock says who holds it: `kind` `serve` with the `port`, or `kind` `cli` with the
`command` (`dam file`). A command is refused while the app has the archive open ("This
archive is open in the app on port 8766. Do this there, or close the app first.";
`dam recover` points to Run recovery in the app instead), and the app or another command
is refused while a command runs ("A dam command (dam scan) is changing this archive
right now. Wait for it to finish, then try again."). `dam archives list` shows either.
Commands that hold the lock: `scan`, `index`, `errors --retry` and
`--retry-unsupported`, `file`, `quarantine`, `move` and `add` (each not with
`--dry-run`), `undo`, `recover`, `init` (also through `archives add`), `star`, `unstar`, `important`
(marking), `unimportant`, `ongoing sync` (not with `--dry-run`) and `ai --on`/`--off`.
The others only read, or change only the archive list (`archives switch`, `rename`,
`color`, `forget`) or the system keychain, and run alongside the app. `dam remind` also
runs alongside it, so the daily job sends while the app is open: it only marks
reminders as sent in the database. While another process has the archive, commands do
not warn about interrupted operations: they may be changes under way there.

**Keeping them apart**: two archives cannot have the same archive folder, nested folders
(one inside the other), or an archive folder inside any archive's data folder. `dam init`,
`dam archives add` and the first-run screen refuse such a folder with the reason (paths are
compared after resolving links, and case-insensitively on case-insensitive disks).
The reminder job is per archive: `dam remind --install` for the archive `test` writes the
LaunchAgent `nl.dam.remind.test` and runs `dam --data-dir <base> --archive test remind`;
the label of "Main" stays `nl.dam.remind`. Once you have more than one archive, install
the job again for "Main" too (`dam --archive Main remind --install --force`): the new form
names the archive, whereas a job installed before archives existed follows whichever
archive is in use. The API key and e-mail password live in the system keychain, once per
computer, shared by all archives.

**Where it lives**: the list is `archives.yaml` in the *base* data folder (the platform
data folder, `DAM_DATA_DIR` or `--data-dir`):

| | base data folder | "Main" archive's data | other archives' data |
|---|---|---|---|
| macOS | `~/Library/Application Support/DigitalArchiveManager` | the base folder itself | `<base>/archives/<id>/` |
| Windows | `%LOCALAPPDATA%\DigitalArchiveManager` | the base folder itself | `<base>\archives\<id>\` |
| Linux | `~/.local/share/DigitalArchiveManager` | the base folder itself | `<base>/archives/<id>/` |

Existing installs need nothing: a data folder that already has `config/settings.yaml` or
`dam.sqlite` and no `archives.yaml` becomes the archive **Main** on first use, with its data
folder being the base folder itself. Nothing is moved, renamed or rewritten; only
`archives.yaml` is created. `dam --data-dir X ...` on a data folder from before archives
means that folder is "Main", as ever.

## Several archive folders

One archive can have extra folders next to `archive_root`, in `settings.yaml`:

```yaml
archive_root: ~/Library/Mobile Documents/com~apple~CloudDocs/Archive
extra_folders:
  - label: Old years
    path: /Volumes/Archive disk/Archive 2000-2015
    attached: true
```

`attached: false` is a detached folder: it stays listed but is not mapped, and its label
stays reserved (a main-folder entry with that name is left out) until it is forgotten. The main
folder's paths have no prefix; a path whose first component is an extra folder's label
belongs to that folder (`Old years/2009/car/invoice.pdf`). Labels compare NFC and
case-folded. Changing one rewrites every stored path under it (see `relabel` below).

**API** (all under `/api/archive-folders`; `400` carries the reason in plain words,
`404` an unknown label, `409` while a maintenance check, rule replay or move across disks
runs):

| Call | Does |
|---|---|
| `GET /api/archive-folders` | The main folder, then every extra folder (detached ones too), with label, path, `attached`, `connected` and file count. |
| `POST /api/archive-folders` `{label, path, dry_run}` | Adds a folder after the overlap, label and readable checks. |
| `POST /api/archive-folders/{label}/detach` `{forget, dry_run}` | Detaches it. Its index rows are marked missing. With `forget` (also for a detached folder) the entry leaves the settings and its rows are removed together with the notes, checklists, collection and item places, summaries, fields, sender and person, and locks of those files; collections and items stay. |
| `POST /api/archive-folders/{label}/attach` `{dry_run}` | Attaches a detached folder again, after the same checks as adding. |
| `POST /api/archive-folders/{label}/relabel` `{label, dry_run}` | Gives the folder (attached or detached) a new label. Answers with `label`, `new_label`, `counts` (`files`: index rows, `operations`: journal rows, `made_folders`, `maintenance_ignored`, `reconnects`), `files` (each settings or rule file edited, with the lines that change), `warnings` and `restart_needed`. See below. |

Each answers with `label`, `path`, `files` and `restart_needed`; `dry_run` answers the
same and writes nothing. A change takes effect at once (the server reopens the archive);
`restart_needed` is true only when it could not. A detach writes the settings, reopens and
only then changes the index, so no scan of the old App puts rows back; every full scan
marks the rows of a detached label missing again. Every file record carries `folder` (its
label, null for the main folder) and `connected`. `is:disconnected` finds the files of
every folder that is not connected now; files of a detached folder are marked missing and
are not found.

**Changing a label** (`relabel`, `dam.relabel`). The new label passes the rules for a new
one, except that the folder's own old label does not count as taken (a change of case is
allowed). Refused while a journal row is still `planned` (Run recovery in the app). Nothing on
disk changes. Every value equal to the old label, or starting with `<old label>/`, becomes
the new label: `files.path`, `path_nfc` and the folder's own top row's `name`, the
`file_fts` rows, `operations.src` and `dst` (except `abs:` paths and the plain file names a
`copy` from outside or a rule picture keeps), `made_folders.rel`, and the keys of
maintenance entries set aside (except duplicate and version groups), and the old row's path
(and a top row's name) in each journaled reconnect. In `settings.yaml`:
the folder's `extra_folders` label, and `protected_paths` and `ai.exclude_folders` entries
under it. In `config/rules/*.yaml`: every `folder` and `folder_is` value under it (a
template whose first part is a placeholder, like `{payee}/x`, is left alone), and the
same for each code's `folder` in `config/filing_codes.yaml`. Tray files name no folders. The YAML files are edited value by value (`dam.core.yamledit`: only the
characters of each value change, in the quoting it had; a plain value that would read
differently is written in double quotes), each new file is loaded again and compared with
the old one with only those values changed, and a value that is folded, literal, spread
over lines or an alias refuses the whole change with its file and line. Applying takes a
snapshot (kind `before-relabel`), rewrites the database in one transaction, then writes
the files (each with its `.bak-<time>`); if a file cannot be written, the files already
written get their old content back and the database is rewritten back. It runs inside
`Host.close_and_reopen` (the archive is closed, so no scan writes old paths back); the API
without `dam serve` answers 409.

**Folders that are not connected.** A folder is connected when its root can be listed and
it does not list nothing while the index has live rows under its label (a signed-out cloud
drive leaves an empty mount point); `core.paths.folder_connected` is the one definition the
scanner, the guards, the watcher and the API use. A scan skips a folder that is not, and marks nothing in it missing. The server checks about
every 30 seconds and rescans a folder that comes back. Planning refuses any operation
whose source or destination is in an unplugged folder, naming its label and path. The
publisher leaves Ongoing and Important links into an unplugged or detached folder alone.
Maintenance shows them as "Folder not connected" or "Folder detached", and its **Archive
folder names** check lists main-folder entries that share a folder's label.

## Snapshots

A snapshot is one zip per archive in `<data folder>/snapshots/`, named
`dam-snapshot-YYYYMMDD-HHMMSS.zip` (`…-before-restore.zip` for the one taken just before
a restore, `…-before-relabel.zip` for the one taken before a folder's label changes,
`…-imported.zip` for one added with Import, named by when it was taken). It
holds:

- `dam.sqlite`, copied with SQLite's online backup API, so it is consistent while the
  app runs (the WAL is included);
- all of `config/` (`settings.yaml`, `filing_codes.yaml`, `rules/` with its picture
  crops, `trays/`, `layouts/`);
- the state files beside it: `ai-state.json`, `rules-state.json`,
  `tray-defaults-seeded.json`, `tray-defaults-dismissed.json`;
- `manifest.json`: format, time, kind (`manual`, `before-restore` or `before-relabel`), app version, the
  database's migration revision, the archive folder and the file list.

Left out: `cache/` (thumbnails, page-1 pictures, exports; rebuilt), `logs/`, the lock and
server files, `archives.yaml` and the other archives' data folders, the archive's own
files, and the Keychain entries. The zip is built in a temporary folder inside
`snapshots/` and moved into place in one step. dam never removes a snapshot.

**Export** is `GET /api/snapshots/{name}/download`: the zip as it is, as a download.
**Import** is `POST /api/snapshots/import` with the zip as the body
(`application/octet-stream`, up to 2 GB; besides the inbox upload it is the only route
that takes a non-JSON body). The file is unpacked into a temporary folder and checked as
for a restore (below, apart from the archive folder and the settings it keeps, the
unpacked copy is migrated and compared too); then it is copied in as `…-imported.zip`. A taken name gets `-2`; nothing is overwritten.

**Restore** (`POST /api/snapshots/{name}/restore {snapshot_current, other_folder_ok}`;
`snapshot_current` is required) only takes a snapshot by name from this archive's
`snapshots/` folder. Before anything changes it unpacks the zip into a temporary folder
and checks it: only the expected entries (no absolute paths, `..`, `:` (drives and
streams on Windows), Windows device names or links, on every platform), at most 10,000
entries, deflated or stored only, no large entry packed more than 250 times smaller, at
most 16 GB unpacked in all (counted again while unpacking, so a zip that declares less
than it holds stops there) and no more than the free disk space, the manifest format,
`PRAGMA integrity_check`, a migration revision this version of dam knows (a newer or
unknown one, such as one from another branch of dam, is refused), no trigger, view or
table that a fresh database migrated to that revision does not have, and a readable
`settings.yaml`. The snapshot's database is opened with `PRAGMA trusted_schema=OFF`
throughout. It is then migrated to the current revision and compared with dam's table
definitions (`alembic` `compare_metadata`, the full-text index's own tables aside): any
difference is a 409, since bare revision ids are shared with an older app that had
another layout. A snapshot whose `archive_root` differs from the open archive's is a 409
unless `other_folder_ok` is true. Every restore sets `archive_root` and `extra_folders` in
the unpacked `settings.yaml` to the open archive's (the index stores paths relative to the
archive folders, so the rest still fits; `kept_folders` says whether they differed), and
keeps every current entry of `protected_paths` and `ai.exclude_folders`: the snapshot's
entries are added after them, but none of the current ones is dropped, so a snapshot file
cannot add a folder to the archive or lift a protection. It is refused while an interrupted
operation waits for recovery (Run recovery), and while a maintenance check or rule replay runs.
With `snapshot_current` a `before-restore` snapshot is taken next. Then the server closes
the archive (`Host.close_and_reopen`: background work stopped, App closed), writes the
unpacked database into the live `dam.sqlite` with the backup API (one transaction, no file
is renamed or removed), moves the current `config/` and state files to
`snapshots/replaced-YYYYMMDD-HHMMSS/` and moves the snapshot's into place (exclusive
renames), and opens the archive again, which starts its background scan. Nothing is
deleted, and `tests/test_no_delete.py` is unchanged. A restore needs `dam serve`; an API
used on its own refuses it.

Other routes: `GET /api/snapshots` (the list, newest first, each with `other_folder` and
with `problem` when it cannot be restored here), `POST /api/snapshots` (take one now) and
`POST /api/snapshots/reveal` (show the folder).

## Config and rules

All in the data folder under `config/`:

- `settings.yaml`: `archive_root` (not set in the seeded file: `dam init` or the first-run
  screen writes it; to change it later run `dam init` again, which keeps a
  `settings.yaml.bak-<time>` copy, or edit the line by hand), `special_folders` (inbox,
  ongoing, important, quarantine), `protected_paths`, `indexer_reads_per_minute`,
  `ops_throttle_ms`, `server_port`, `ocr_languages`, `reminders` (`hour`, `mac`, `email`),
  `ai` (see AI setup), `page1_backfill` (read page 1 of older documents in the background,
  default `true`), `page1_text_reads_per_minute` (how fast page 1 of PDFs with a text layer
  is read, 1 to 6000, default 300; scans, photos and slow reads keep
  `indexer_reads_per_minute`), `people` (a list of `name` and `match` strings) and `address_zone`
  (`[x0, y0, x1, y1]` as fractions of page 1, origin top left).
- `trays/*.yaml`: one tray per file (see Tray files).
- `filing_codes.yaml`: the filing code table (see Filing codes file below).
- `sticker_sheets.yaml`: the saved custom sticker sheet, if any (see Sticker sheet
  layout below).
- `rules/*.yaml`: filing rules, loaded in name order. A bad file is reported and
  skipped; rule ids must be unique across files. For folder and name the first matching
  rule wins; tags from all matching rules are merged. The seeded `00-examples.yaml`
  documents the format. In `when`, all *given* conditions must match; for
  `text_contains`, one matching term is enough. `{doc_date}` and `{year}` need a
  detected date; without one, the rule's template is not applied.
  `zones` is a list of areas of page 1, and every one must match. A zone matches when one
  of its words is in the text of the box: the words of page 1 that lie at least half
  inside the box (grown by 3 % of the page on every side), joined per line, so a term of
  several words matches across consecutive words of one line. Page 1 keeps a box for each
  word (the text layer; Tesseract's word boxes; for Apple Vision, whose engine gives line
  boxes only, an estimate that shares the line's width in proportion to the characters).
  A page-1 layout read before word boxes were kept has none: such a line counts as a whole
  when half of it is inside the box, until the file's content changes and page 1 is read
  again (existing rows are not re-read). `match` says how a word matches the text:
  `word_start` (it must begin a word, any ending: `kela` finds Kela, Kelan, Kelalta and
  `vakuutus` finds Vakuutuskirja but not Henkivakuutus), `whole_word` (bounded on both
  sides) or `anywhere` (a substring). A word boundary is the edge of the text or any
  character that is not a letter or digit (Unicode-aware; hyphen, slash, dot, space and
  underscore are boundaries, digits are word characters). **Without `match` the default is
  `anywhere`**, so rule files written before the key existed behave as they always did;
  the rule sheet sets `word_start` on new areas, and the rule is written with `match` only
  for `word_start` and `whole_word`. It applies to the whole-text check, the test and the
  suggestions alike. A picture area takes no `match`. A zone has `box` and either `text_contains` or, for a
  picture area, `image` (see "Picture areas" below). A rule with more zones has to come
  before a plainer rule for the same sender. `{person}` needs a person
  (set by you, or found in the address area); without one the template is not applied.
- `rules/learned.yaml`: rules made or edited in the app, a YAML list created when first
  needed. It is read **before** the other rule files, so a learned rule wins over broad
  ones. Saving a rule that lives in another file rewrites that file (comments are lost; a
  `.bak-<time>` copy is kept). See the user guide, "Filing rules".
- `<data dir>/rules-state.json` (beside the config folder, not in it): the switch for
  offering a rule after a manual filing, and the match words of documents you answered
  "Not for these".

To add a rule, create e.g. `config/rules/10-mine.yaml` (a YAML list):

```yaml
- id: benefits-letters
  when:                                  # all given conditions must match
    text_contains: ["acme benefits", "eläkekassa"]   # case/diacritics-insensitive
    filename_matches: "(?i)scan"         # optional regex on the file name
    folder_is: "##. Organize"            # optional; see below
    # zones:                             # optional: areas of page 1, all must match
    #   - box: [0.05, 0.02, 0.45, 0.14]  # x0, y0, x1, y1 as fractions, origin top left
    #     text_contains: ["acme benefits"]   # any one of these words in the area
    #     match: word_start              # optional: word_start, whole_word or anywhere
    #   - box: [0.55, 0.05, 0.95, 0.12]  # a second area, such as the title
    #     text_contains: ["policy"]
    #   - box: [0.05, 0.02, 0.35, 0.10]  # a picture area, such as a logo
    #     image: areas/acme-1.png        # a file in config/rules/areas
    #     min_score: 0.9                 # optional, 0 to 1 (default 0.85)
    # person: Tiina                      # optional: the document is for this person
  # person_zone: [0.06, 0.10, 0.52, 0.30]  # optional: this sender's address area
  # sender: Acme Benefits                # optional: the sender the rule identifies
  then:
    folder: "13. Taxes/{year}"           # templates: {doc_date:%Y%m%d}, {year}, {stem}, {person}
    name: "{doc_date:%Y%m%d}_Benefits"      # stem only; the extension is added
    tags: ["benefits"]
    # collections: ["Taxes 2026"]        # optional: the Inbox form starts with these in "Also add to collection"
    # tray: to-pay                       # optional: the tray it is guessed to belong in
    # payee: "Acme Benefits"        # optional: prefills the To pay tray's payee
```

**Picture areas.** A zone with `image` matches when the picture in the file appears in
its `box` on page 1. `image` is `areas/<name>.png`: a plain file name in the folder
`config/rules/areas` (a path that leaves it, with `..`, a drive or a backslash, is
refused, and so is a link that points outside). The file is an 8-bit grayscale PNG of the
box, cut from page 1 rendered 1000 px wide, its long side at most 300 px; the app makes it
(`<rule id>-<n>.png`, the first free number, never overwriting) and keeps a `.bak-<time>`
copy if it ever replaces one. A zone has words or a picture, not both, and `min_score`
(above 0, at most 1; default 0.85) is only for a picture.

The score is the best normalised cross-correlation (numpy) of the picture over the
search window, the box grown by 5 % of the page on every side, at the scales 0.9, 0.95,
1, 1.05 and 1.1, after a light blur of both; about 6 ms a document, 3 for loading the picture and 3 for the
match. A picture zone has no
text pre-filter, so it is checked last, after every other condition of the rule. A
document without a page-1 picture yet cannot be judged yet (the same as a missing page-1 layout); the test lists it under "could not be judged yet".
The matching works at the stored width, 1000 px, with a blur of 0.8 px (it used 500 px and
1.2 px: at that size a block of small text with other words in the same layout scored 0.89,
above the default). In tests, other dark logos on white score 0.63 or less and a block of
other small words 0.74; a rescan of a logo with a shift, a size change of 10 %, noise, a
darker copy or a 2 degree skew scores 0.92 and over, and small text 0.94 and over with
noise or a darker copy, 0.93 with a 1 degree skew and 0.82 with a 2 degree skew. The default
0.85 stays; fine print on a crooked scan needs a lower `min_score`. A match takes about 20 ms.

The page-1 pictures are cache, in `<data dir>/cache/page1/<drive id>-<sha256 prefix,
16 hex digits>.jpg` (8-bit grayscale JPEG, quality 70, 1000 px wide, the page as it is
shown: its own rotation and an image's EXIF orientation). They are made while a scan is
read for OCR, and by the page-1 background pass for the rest (inbox first, then files a
test asked for, then the others while `page1_backfill` is on); they are made again when the
content changes. Once after the first full scan at startup, `prune_page1_pictures` removes the stale
pictures: files directly in that folder, named exactly like a cache picture, that are regular
files and whose drive id is unknown or whose sha256 prefix is not the file's
current one (symlinks are never touched, nor anything outside `cache/page1`). This is the
app's own cache, not the archive; the no-delete AST test allows that one function in that
one module. Nothing in the archive is written.

Next to them the cache holds `page1-thumbs.npz`: a 48 x 68 grayscale thumbnail of every
page-1 picture (about 3 KB each) in one array file, keyed by the picture's file name. It is
added to when a picture is made, made from the pictures already in the cache by the
indexer when it is idle, and written as one whole file (a torn or unreadable file counts as
empty and is made again; a thumbnail of a picture that is gone is dropped from the next
write). A rule test with a picture area scores every thumbnail in one numpy operation (the
crop reduced to the size of its box, best normalised correlation over the same search window)
to decide which documents to look at first. It only orders them: the precise match decides.
Nothing removes this file.

API: `POST /api/rules/area-picture {drive_id, box, save?, rule_id?}` cuts the box from the
document's page-1 picture and returns `{width, height, png (base64), image}`; with `save`
(and `rule_id`, which names the file) it also keeps the file and `image` is its path, else
null. `POST /api/rules/draft-zone` takes `picture_boxes` next to `boxes` and returns the
saved crops in `pictures`. `GET /api/rules/areas/{name}` serves a saved picture. The
replay answer has `scores: [{path, drive_id, score, matched, needed}]` for a rule with picture
areas: the lowest 20 matches and the highest 10 near misses, which are documents where every
other condition held and only a picture area failed, with a score within 0.15 of `needed` (the
score that area asked for; null for a match). A document that fails a word, an area, the file
name, the folder or the person has no score. Every row of the replay carries `drive_id`
(`different`, `not_checked`, `scores`, and `marked.missed`, which is a list of `{path,
drive_id}`) so the document can be opened. The rule sheet tests a rule with a background job
(next paragraph); `POST /api/rules/replay` is the same test as one blocking request with a
time budget (5 s), kept for other callers. It takes `after` and answers `next_after`: when
`truncated` is true, post the same rule with `after` set to it to go on with the documents
not looked at yet, in the same order. The cursor is opaque (`r1.<id>.<n>`): the server
remembers the order of the last six tests, and answers 400 "run it again" for a cursor it
no longer has. A plain path as `after` still works (path order). `total` is still all filed
files, the other counts are for that part, and `marked` is only computed without `after`.
Both take `near_drive_id` (the document the areas were drawn on).

The documents are tested in this order, which changes when things show up and never the
result: the documents assigned to the rule's `sender`, then those in the folder of
`near_drive_id`, then, for a picture rule, the rest by the thumbnail score above (best first),
then the rest by path. The lists in a result (`different`, `shadowed`, `not_checked`,
`marked`) are always in path order.

**Background tests**: `POST /api/rules/replay/jobs {rule, sheet, replaces?, place_above?,
near_drive_id?}` starts a test and answers at once with `{job_id, state, version, looked_at,
total, waiting, elapsed_s, error, result}` (`result` null: nothing yet). `GET
/api/rules/replay/jobs/{job_id}?since=<version>` answers the same with `result`, a replay
answer for what has been found so far, left null when it has not changed since `since`;
`state` is `running` (going through the documents), `waiting` (all looked at; `waiting`
documents wait for page 1 to be read and are looked at again as it is), `done`, `stopped` or
`error` (a fixed message; the details are in the log). `looked_at` of `total` is the progress.
`POST .../stop` ends it where it is and keeps the result so far; `DELETE .../{job_id}` ends
it and forgets it (404 for a job that is gone). One job per `sheet` (a new start for the same
sheet ends the first), at most four jobs, finished ones go first; a job nobody has asked
about for two minutes stops by itself, a `waiting` job with nothing new for 30 minutes ends
as `done`. `POST .../{job_id}/read-now` answers `{queued}`: it asks the page-1 pass to read the
documents the job waits for at full speed (see below); 404 for a job that is gone. A job reads
the index and the cache only; it writes nothing. The time of each step
of a test (listing, fetching text, folding, loading layouts, word checks, picture decoding,
matching) is written to `dam.log` at INFO, as numbers only, once per test.

`POST
/api/rules/areas-for {rule, drive_id}` answers `{areas}`, the rule's areas on that document in the
shape of a suggestion's `areas` (matched lines, the best place and score of a picture area, and
`reason` for one that did not match or has no score), with the rule's `folder_is` ignored as in
the replay; it reads only the index and the cache and changes nothing. `GET /api/rules`
lists `unused_pictures` (files in `areas` no loaded rule uses) and `default_min_score`.
`POST /api/rules/unused-pictures/quarantine {names, dry_run}` moves those pictures into
the quarantine folder as `dam rule picture <name>` (a taken name gets `_2`, ...) and
answers like `POST /api/quarantine` (a batch with `done`, `failed`, `error`, `batch_id`);
with `dry_run: true` it only resolves the plan. Every name must be in `unused_pictures` at
that moment (400 otherwise, nothing planned); a link is also a 400. On two disks the plan notes say so. It runs as two operation kinds: `picture_to_quarantine` (`src` is the `abs:` path of a
regular file directly inside `config/rules/areas`, never a link; `dst` the quarantine folder)
and its undo-only inverse `picture_back` (refused when the name is taken in `areas`, or the
file in `##. To Delete` was changed or moved). Both never overwrite. On one disk they are
renames. On two disks `picture_to_quarantine` copies the file (exclusive create, fsync, size
and sha256 of the copy checked) and only then removes the original with `remove_moved_picture`,
and `picture_back` copies it back and leaves the file in `##. To Delete`. The journal records
the `method` (`rename` or `copy`) and the `content_hash` (sha256), which undo and crash
recovery use: after a crash, a verified copy with the original still there is finished by
removing the original only if its hash matches, and a partial or unverified copy leaves both
files and is reported. The journal keeps the file name only, not the path on this computer. Undo goes through
`POST /api/activity/{batch_id}/undo`, as for every batch.
A suggestion's `areas` has `kind: "image"` with `score` and, in `lines`, where the picture
fits best.

`folder_is` is the folder the file sits in. The inbox (`##. Organize`) also matches files
directly in a filing code's inbox folder (such as `##. Organize/To pay`); naming a code's
folder (`folder_is: "##. Organize/To pay"`) matches only the files in that folder.

`then.collections` is a list of collection names, like `tags`: the collections of all
matching rules are added together and prefill the Inbox form's "Also add to collection"
(each suggested collection says which rule it came from). Names are trimmed, a repeat is
dropped, and a name is at most 120 characters. A collection that does not exist yet is
created when the document is filed. A rule file without the key loads as before. The
rule test (replay) does not compare collections.

`then.tray` and `then.payee` come from the same rule as the folder (the first matching
rule with a folder; if no rule gives a folder, the first matching rule that has either).
Without a `then.tray`, an inbox document whose scan found a due date and an amount, plus
an IBAN or a reference, is guessed **To pay**. Guesses are plain code, no AI.

The top-level folder (`13. Taxes` here) must already exist; dam never creates top-level
folders on its own (the quarantine folder is the only exception). Make it yourself with
**New folder** in Browse, or start from a layout.

When a starter layout is applied and your rules folder holds no rules of your own
(nothing, or only the shipped `00-examples.yaml` exactly as shipped), it is replaced by
rules that point at the new folders (receipts to `Bills & Receipts/{year}`, tax letters
to `Taxes/{year}`, ...); a rule whose folder you removed is left out. The Finland bank
examples stay in that file, commented out. Rules you wrote are never touched.

### Filing codes file

`config/filing_codes.yaml` holds the filing codes (see the user guide, "Filing codes").
It is seeded from `defaults/filing_codes.yaml` only while the file does not exist, so an
update never changes your table, and a table you emptied stays empty. An install from
before filing codes gets the seeded table on its first start with this version.

```yaml
- code: P                     # 1 to 4 letters or digits, unique; stored upper case
  label: To pay               # at most 24 characters; shown in chips, the batch and on stickers
  tray: to-pay                # a tray id (see Tray files)
  inbox_folder: To pay        # its subfolder of the inbox; unique
- code: V3
  label: Car insurance
  folder: "20. Vehicles/{year}"          # templates as in a rule's then.folder
  name: "{doc_date:%Y%m%d}_Insurance"    # as in a rule's then.name; the extension is added
  tags: ["car", "insurance"]
  collections: ["Car"]                  # collection names as in the app (not Ongoing or Important)
- code: D
  label: File as suggested
  as_suggested: true          # already handled: file where dam suggests, in no tray
  inbox_folder: File as suggested
```

Every key but `code` is optional. An entry that is invalid, repeats a code or an inbox
folder, or names a tray that does not exist is reported in Settings and skipped. The app
rewrites the whole file when you save there (keeping the old one as
`filing_codes.yaml.bak-<time>`), so comments you added by hand are not kept; entries
that were skipped are dropped too, and Settings says so before you save.

### Sticker sheet layout

The built-in sheets (Avery Zweckform L7651 and plain paper) are part of dam. A custom
sheet saved from Settings → Print stickers is written to `config/sticker_sheets.yaml`
(the old file kept as a backup), one layout in mm on an A4 page:

```yaml
id: custom
name: My labels
columns: 5
rows: 13
label_w_mm: 38.1
label_h_mm: 21.2
top_mm: 10.7
left_mm: 4.7
gap_x_mm: 2.5
gap_y_mm: 0.0
cut_lines: false
```

A label must be at least about 31.7 × 14 mm to hold a sticker, and the grid must fit on
the page. An invalid file is skipped (and logged), as if no custom sheet were saved.

## Tray files

A tray is a YAML file (one tray per file) in `config/trays/`. Four are seeded from
`defaults/trays/`:

| Tray | Fields | Reminders |
| --- | --- | --- |
| **To pay** | `payee` (prefilled from a rule's `then.payee`), `due_date` (required), `amount`, `iban`, `reference`, prefilled from the scan; copy buttons on amount, IBAN and reference; "Mark paid" asks for `paid_on` (default today) | 3 days before, on the day, and once when overdue; Today shows the open total |
| **To action** | `action_date` (required) | 1 day before and on the day |
| **To read** | none | one nudge when an item has waited 30 days |
| **Follow up** | `check_by` (optional date), `waiting_for`; "Done" asks for nothing more | on the check date and once when it is overdue |

**Add a tray**: put a file such as `config/trays/50-to-sign.yaml` in `config/trays/`. It
is read when `dam serve` (or any `dam` command) starts: restart `dam serve` after changing
a tray file.

```yaml
id: to-sign                   # starts with a letter or digit; then a-z, 0-9, - and _
name: To sign
order: 5                      # position in the nav and on Today
item_title: "{name} ({date:%d.%m})"   # {name}; {date:...} needs date_field
fields:
  sign_by:  { type: date, required: true }
  where:    { type: text }
  fee:      { type: money, copy: true }          # copy: true shows a copy button
  # prefill takes due_date | total | iban | reference from the scan, or payee from a
  # rule's then.payee (a text field), on a matching type:
  # iban:   { type: iban, prefill: iban, copy: true }
date_field: sign_by           # sorts the tray; drives reminders and "overdue"
done:
  label: Signed
  fields:
    signed_on: { type: date, default: today }
reminders:                    # each fires once; needs date_field
  - { days_before: 2 }
  - { days_before: 0 }
  - { overdue: true }
summary: { sum: fee }         # a money field; shown as the total on Today
# nudge_after_days: 30        # alternative for undated trays: one reminder after N days
```

Field types: `text`, `date`, `money`, `iban`, `reference`, `checkbox`. A file with a
mistake is reported (file and line, in the UI and by `dam trays`) and skipped; the other
trays keep working. If you remove a tray file, its items stay in the database and show as
"tray removed".

**New default trays.** A tray file added to `defaults/trays/` in a later version (such as
`40-follow-up.yaml`) is copied into `config/trays/` once, the first time the app starts
with it, unless you already have a tray with that id. The names offered so far are kept in
`<data dir>/tray-defaults-seeded.json`, so a tray file you delete stays deleted and is not
offered again; the three original files count as offered already. To get one back, copy it
from `defaults/trays/`.

**Picking up new defaults.** Seeded tray files are yours: a newer `defaults/trays/`
file (for example the `copy: true` on `amount`, or the **payee** field) is never copied
over them. Instead `GET /api/trays/{tray_id}/defaults-diff` compares your file with the
default file of the same name and lists only the settings your file is **missing**
(`added: [{path, value, problem}]`, e.g. `fields.iban`, `fields.amount.copy`). Your
values are never removed or changed, and lists (`reminders`) are never merged. You
choose which to add: `?paths=…` (repeatable; default: every one without a `problem`)
gives the text that choice would write (`new_text`, with `error` if it would not be a
valid tray), so one setting that does not fit your file (its `problem`) never blocks
the others. `POST /api/trays/{tray_id}/apply-defaults {paths, expect_current_text,
expect_new_text}` adds only those, and only if your file and the result are still
exactly what you were shown (else `stale_preview`), after a byte-for-byte backup
`<file>.bak-YYYYMMDD-HHMMSS` next to it; then the trays reload.
`POST /api/trays/{tray_id}/defaults-dismiss {paths}` stops offering settings you do
not want; they are remembered in `<data dir>/tray-defaults-dismissed.json`, not in the
tray file. Missing keys are added as YAML text after the last entry of their mapping,
so your comments and layout stay. A one-line `{ ... }` mapping that gains keys is
rewritten as one `{ ... }`, and comments inside its braces would go. A file whose edit
cannot be checked to load back exactly (YAML anchors, unusual keys) is written out
whole by PyYAML, without comments; the diff shows this first. New fields go after your
existing ones; move the line if you want them elsewhere. Existing items simply have no
value for a new field until you set one.

The move of an item between trays is `POST /api/items/{id}/move`, and its undo
`POST /api/items/{id}/undo-move` (only while the move is the item's latest change).

Files on an item: `POST /api/items/{id}/files {drive_id, position?}` attaches a file (at
the end, or at `position`, 0-based, which is how an Undo puts a taken-off file back in its
place; a file already on the item stays) and `POST /api/items/{id}/files/remove {drive_id}`
takes one off (an item keeps at least one file, else 400). Both change the database only.

Merging items: `POST /api/items/{id}/merge {item_id}` merges the open item `item_id` into
the open item `{id}` in one transaction and returns the target. The target keeps its
title, tray, dates and fields; it gains the other item's files (in order, those it has
already skipped), its note (appended after a line `--- <title> ---`) and its checklist
(appended, with the done flags). The other item is then removed. 400 for merging an item
into itself, for a done item, or when the combined note would pass the note limit
(nothing changes then); 404 for an unknown id. The target's history gets a `merged_in`
event (title, files added, whether a note and how many checklist entries came along). The
event also holds the removed item whole (files, history, note, checklist, reminder
records), which `GET /api/items/{id}/history` leaves out. `POST /api/items/{id}/undo-merge`
uses it to bring both items back as they were, under the old item's id; it answers 409 once
the target changed since (a new event, or its note edited). No archive file is touched.

## Reminders setup

A reminder check runs hourly while `dam serve` is up (the first one a minute after the
start), and from the daily job below. A lock file in the data folder keeps two checks from
running at once (the second says "skipped").

```sh
cd backend
uv run dam remind --dry-run                      # list what is due, send and mark nothing
uv run dam remind --dry-run --now 2026-11-03T09:00   # ... as of another time
uv run dam remind                                # send what is due now
uv run dam remind --install                      # daily LaunchAgent (shows the plist, asks first)
uv run dam remind --uninstall                    # unload and remove it
uv run dam remind --set-email-password           # store the SMTP password in the keychain
uv run dam remind --test-notification            # one "dam test notification" per channel
```

**Before installing the LaunchAgent** (macOS), run `dam remind --test-notification` once
in Terminal and allow notifications for Script Editor when macOS asks (the notification is
sent with `osascript`; until it is allowed, macOS drops it without an error). It sends one
harmless "dam test notification" through each enabled channel, prints the result per
channel and marks nothing; with `--dry-run` it only says what it would send.

`--install` writes `~/Library/LaunchAgents/…plist` (the only file the app writes outside
its data folder), which runs `dam remind` daily at `reminders.hour` and at login, and works
even when the archive is unavailable. It loads with RunAtLoad, so `dam remind` runs
**immediately** on your real data: run `dam remind --dry-run` first to see what would go
out. Both the install and uninstall show the plist and ask first (`--yes` skips the
question). Afterwards, `launchctl print gui/$(id -u)/nl.dam.remind` shows the job. On
Windows and Linux, schedule `dam remind` yourself (Task Scheduler, a systemd user timer or
cron).

Delivery is a macOS notification (`reminders.mac`, default on) and, optionally, one e-mail
per run to yourself. Configure e-mail in `config/settings.yaml`:

```yaml
reminders:
  hour: 8
  mac: true
  email:
    to: me@example.org
    smtp_host: smtp.example.org
    smtp_port: 587          # 465 = implicit TLS; other ports use STARTTLS
    smtp_user: me@example.org
```

then run `dam remind --set-email-password`: the password is prompted for and stored in the
system keychain (Keychain on macOS, Credential Manager on Windows, Secret Service on
Linux), never in a file; the login is refused without TLS. A failed channel is logged and
shown on Today; if every channel failed, the reminder is retried at the next check, but if
one channel delivered it counts as sent. There is no retry loop.

## AI setup

```sh
dam ai --set-key       # prompts for the key (not echoed) and stores it in the keychain
dam ai --status        # on/off, key present, this month's spend and the cap
dam ai --log           # the call log, newest first (--limit N)
dam ai --off           # switch AI off (the key stays); dam ai --on turns it back on
dam ai --clear-key     # remove the key from the keychain
```

The key lives in the system keychain (service `dam-anthropic`, account `api-key`), never
in a file, the log or the API. The running app asks the keychain at most once a minute, so
a key added or removed with `dam ai` shows up there within a minute or two
(`dam ai --status` always asks it afresh).

`dam ai --off` / `--on` and **Activity → AI → Use AI** write `<data dir>/ai-state.json`
(never `settings.yaml`) and read it back to check it stuck. A missing file means on; a
file that cannot be read or is not valid means **off** (it fails closed): a warning is
logged, `dam ai --status` and Activity → AI say why, and switching AI on again rewrites
the file. `ai.enabled: false` in `settings.yaml` switches AI off too.

Under the hood every AI action is a two-step API, `prepare` then `run` with a per-process
token: `run` rebuilds the payload and refuses if anything changed since the preview.
Answers are validated against the task's schema; document text is sent inside a delimited
block and treated as data.

**Settings** (the `ai:` block in `settings.yaml`, see the commented defaults): models,
prices, the EUR rate, the budget, the language (`ai.language`, default `en`), the thinking
effort (`ai.effort`, default `low`), the output limits and the excluded folders.

- **Budget**: `ai.monthly_budget_eur` (default €5). A call is blocked before sending when
  this month's spend plus the worst-case estimate would go over it. The estimate counts
  input as characters ÷ 3.5 and prices the output at the task's `max_tokens` (filing
  2500, document summary 1500, collection summary 3000, questions 3000). The model's
  thinking counts against `max_tokens` too, even at `ai.effort: low`, so these leave room
  for it; a typical call costs far less than its estimate.
- **Costs**: tokens × the per-model price table `ai.prices` (USD per million tokens),
  converted at `ai.usd_to_eur` (default 0.92). The defaults are `claude-haiku-5-5`
  ($0.10 in, $0.50 out) for filing and summaries and `claude-sonnet-5-5` ($2 in, $10
  out) for questions. **Check these against Anthropic's current price list** and edit
  `ai.prices` and `ai.models` in `settings.yaml` when they change; the app cannot know.
- **Time limit**: 60 s plus 1 s per 500 estimated input tokens and 1 s per 50 output
  tokens allowed, rounded up to 10 s and capped at 3 minutes.
- **Excluded folders**: `ai.exclude_folders`, default `50. Medical`, `70. Work`,
  `90. Other People`; paths from the archive root, each covering everything inside it
  (case and Unicode form ignored). Activity → AI edits the list (`PUT
  /api/ai/exclude-folders`): it writes the whole list to `settings.yaml` (replacing the
  defaults, keeping other settings and comments, with a `.bak-<time>` copy of the old
  file) and applies at once, no restart. A request previewed before a folder was
  excluded is refused at Send.

**Demos: `DAM_AI_FAKE=1`.** For demos and tests only, `DAM_AI_FAKE=1` replaces the
provider with a deterministic fake. It makes **no network calls**, counts as having a key,
and gives demo answers read from the payload. Its calls are logged with outcome `fake`,
the model as `fake:<model>`, at no cost, and never cached.

```sh
cd backend && uv run python -m dam.demo /tmp/dam-demo   # a small fake archive
DAM_AI_FAKE=1 uv run dam --data-dir /tmp/dam-demo/data serve --port 8777 --no-open
```

## Moves across disks

A move the owner makes by hand (`POST /api/browse/move` with mode `move`, and
`POST /api/restore`) carries `Plan.copy_across`. In such a plan a `move` of a **file**
whose source and destination folders are on different disks (`os.stat().st_dev` of the two
folder roots) is planned as two operations, always next to each other:

1. `copy_across` (`src` the file, `dst` its path in the other folder; a taken name gets
   `_N`). The preview's op carries `size` and `cloud_only` (macOS `SF_DATALESS`: reading it
   downloads it first). The journal row is written (`planned`) before anything is copied.
   The copy is written under `.dam-copy-<8 hex>-<name>` next to the destination
   (exclusive create, fsync, no size cap, only the free-space check) in one read of the
   source that also hashes it, then read back and checked to have that size and hash.
   This part runs without `INDEX_LOCK`, so scans and other changes go on meanwhile (a
   scan leaves the copy in progress out of the index). Then, under the lock again, the
   source must still be the file the journal row saw (same file, size and modification
   time) and the name still free, else the op fails naming the `.dam-copy-` file, which
   stays. The sha256 goes into the row (`content_hash`), the copy gets the source's
   access and modification time and only then is renamed to its name without
   overwriting. The file's index row then
   describes the copy, so tags, notes, checklists, collection and tray item places, locks,
   summaries, fields and rule outcomes follow; it takes the copy's own Drive id if it has
   one, else a fresh `local:` id when the original's was a Drive id (the original keeps
   that id on disk, so it becomes a new, empty row on the next scan).
2. `quarantine` of the original into its own folder's To Delete, with the note
   `copied to <dst>`. A restore across disks has no step 2: the original stays in To
   Delete (note `the original stays in To Delete`).

The dry run refuses (with a plain message) a folder or a link (only files cross disks),
a protected file, a locked file, a folder that is not connected, too little free space
on the destination for the whole batch (`primitives.has_room`), and a destination name
whose temporary name would be over 255 bytes (UTF-8; the prefix adds 19). Every other caller (filing, rules, conversions,
filing codes) and every undo keeps the refusal "... are on different disks, so this cannot
be moved between them here."

**In the background.** A move whose plan holds a `copy_across` answers at once with
`job_id` (and an empty batch); refusals still answer the request. One such move runs at a
time (a second is 409), it does not end when nobody polls, and closing the app ends the
copy in progress at its next chunk (its `.dam-copy-` file stays and the op fails naming
it). While it runs, adding, detaching, attaching or relabelling a folder and restoring a
snapshot are 409. Those changes hold `CopyJobs.held()` from their check until they are
done, so a move started meanwhile is 409 too ("The archive is being changed. Try the move
again in a moment.") instead of being ended by the reopen. `bytes_done` moves after each
1 MB chunk of the file being copied. A job that fails keeps dam's own reason in `error`
(a refusal from the planner or a failed copy); anything else is
"<type>: the move could not be completed".

| Call | Does |
|---|---|
| `GET /api/browse/move/jobs/{job_id}` | `state` (`running`, `done`, `stopped`, `error`), `done`/`total` files, `bytes_done`/`bytes_total`, `current` (the file being copied), `elapsed_s`, and once it is over `result`: the batch (`batch_id` for Undo; `stopped` and `error` "Stopped: N of M files moved." when it ended early). |
| `GET /api/browse/move/jobs/latest` | The latest move of this run, or null. |
| `POST /api/browse/move/jobs/{job_id}/stop` `{}` | Ends the move after the file in hand: a verified copy is always followed by the move of its original to To Delete, so each file is either moved or untouched. For a folder move see [Folder moves](#folder-moves). |

**Undo** (renames only, so `test_no_delete.py` allows nothing new): the `quarantine` of the
original is undone by moving it back; the `copy_across` by a `quarantine` of the copy into
the destination folder's own To Delete, after which the index row describes the original
again (its path and journaled id; a row the scanner gave the original in To Delete
meanwhile is dropped from the index first). Undo checks that the copy still has the
journaled size and hash, and waits until both folders are connected. While a move across
disks runs, undo (and its preview) is 409, so it can never land between a copy and the move
of its original. If the index step after a copy never ran (the row still describes the
original, and a scan gave the copy a row of its own), undo leaves both rows as they are
when the original's row carries anything of the owner's (tags, notes, collection or tray
places, a lock).

**Recovery** settles a `planned` `copy_across` from the disk: no copy and no `.dam-copy-`
file means it never started; a copy with the journaled size and hash, with the source
still there, means it finished (the index is re-pointed); a `.dam-copy-` file only, or a
copy that does not match, needs a manual check and every file is left alone. The
Maintenance check `unfinished_copies` lists indexed `.dam-copy-*` files (looked at on disk
first) with `size`, and `total`/`total_size`; the owner removes them.

`rename_excl` uses the system's no-overwrite rename: `renamex_np(RENAME_EXCL)` on macOS,
`renameat2(RENAME_NOREPLACE)` on Linux. On Windows `os.rename` never replaces. Where the
volume or C library has none (some exFAT, FAT and network volumes, older glibc), it checks
and then renames, which leaves a short window.

### Folder moves

`POST /api/browse/move/preview` and `/api/browse/move` (mode `move`) also take one folder
in `drive_ids`, alone (a folder together with files, or two folders, is a 400: "Move one
folder at a time, without files"). Refused with a 400 before planning: the top of an
archive folder, the inbox, `##. Ongoing`, `##. Important`, `##. To Delete` and anything
inside them, and a folder into itself or its own subfolder. A folder that is not
connected, a locked file inside it, and a top-level destination in the main folder are
refused by the planner as for files. Link and Copy modes stay files only.

`check_disk_identity` has a folder case, used when the requested row is a folder: the
folder on disk must carry the Drive id of the row (a `local:` row must carry none, or only
one belonging to another indexed entry) and `lstat` must say a real folder (not a link,
not a file). There is no size check, and the files inside are not checked against the
index (the planner lists them from disk and each copy reads its hash when it runs).

**On one disk** it is one `move` of the folder: a rename, the folder row and every row
under it re-pathed, undone by a move back. A taken name gets `_N` ("renamed to avoid
collision").

**Across disks** the folder's `move` is planned as, in order:

1. `mkdir` of the destination folder and every subfolder of the tree, parents first,
   empty ones included, each flagged as made by this batch.
2. One `copy_across` per file, in tree order, each into its mirrored place (no
   `quarantine` after each one). Dot files are copied, `.DS_Store` is not. A
   `.dam-copy-*` file in the source refuses the move ("Remove the unfinished copy <name>
   first."), and so does a protected entry anywhere inside, or a folder anywhere inside
   holding two names that differ only in case or normalization ("<folder> holds <a> and
   <b>, which differ only in case or accents. Rename one of them first."). Links are not
   copied.
3. One `quarantine` of the whole source folder into its own archive folder's To Delete,
   with the note `copied to <dst>` and a note counting the links that are not copied. It
   carries the planned tree and `copied_to`.

When the destination folder already exists, the move merges into it: existing subfolders
are reused, a free name is copied, and a name taken by a regular file with the same size
and a modification time at most 2 seconds off (FAT32 keeps 2-second steps) is planned as
a `copy_across` with
`method` `present` (`ResolvedOpOut.method`; note "already at the destination; checked, not
copied again"). When it runs, both hashes are read: equal means nothing is written,
different stops the batch before the last step ("<name> at the destination differs from
the original; nothing more was moved."). A name taken by anything else gets `_N`. If the
folder's own name is taken by a file or link, the destination folder is `name_N`. Undo of a
`present` op does nothing; the earlier batch's undo moves that copy.

Before the last `quarantine` acts, the source folder is listed again and compared with the
planned tree (names and kinds, and for each copied file the size and modification time its
copy read). On any difference nothing goes to To Delete, the copies stay, and the batch
stops with "<folder> changed during the move (<up to five changes>). It stays where it is;
move it again to copy the rest."

**Index rows.** Each file's row follows its copy as soon as it is copied (as for files), so
after a Stop the originals still in the source are new, bare rows after the next scan. When
the last `quarantine` has acted, every folder row of the source tree is re-keyed (the
destination folder's own Drive id, else a fresh `local:` id when the row had a Drive id,
else kept) and re-pathed to its mirrored folder, so a folder's collections and notes
follow it; a row the scanner already made for a destination folder is dropped first unless
it has attachments. The journal records this in two columns added by migration
`0036_operation_copied_to`: `operations.copied_to` (where the copy of a folder went) and
`operations.followed` (JSON `{"rows": [[old_id, new_id, old_path, new_path], ...],
"applied": false}`, the folder rows that follow, written before any of them moves; `applied`
turns `true` once they and the rows under the source have followed). `dam recover` runs the
follow step again only for a done `quarantine` whose `followed` is missing or not
`applied`, then sets `applied`; a finished one is never followed again, so an original put
back from To Delete keeps its row. Relabel rewrites both columns (the paths in `rows`).

**Undo**, newest first: the folder comes back from To Delete (its rows follow back from
`followed`), each copy goes to the destination's To Delete (rows go back to the originals),
then each made folder is removed while it is still the folder the batch made and empty. A
made folder that is not empty stays and the result lists it. A stopped batch undoes the
same way without the first step. While a later move of the same folder that used its
copies (`present`) is done and not undone, undo of the stopped batch (and its preview) is
a 409 "Undo the later move of <folder> first.", since those copies are then the only live
ones.

**Preview and job.** The preview carries no new fields: the folder summary is built from
the ops (folders made, files copied and their size, files `present`, where the folder goes
and which To Delete it ends in). For any folder move, on one disk or across, it warns about
links outside `##. Ongoing` and `##. Important` that point into the folder: "N links
elsewhere point into this folder and will point to nothing" and, on one disk, "N links
inside this folder point into it and will point to nothing" (across disks those are in the
"not copied" note), names listed up to five. On a Stop the job result is "Copied N of M files; <folder> stays in place until all
are copied"; when it finishes, "Moved folder <name> (M files) to <place>". Activity says
"Moved folder <name> to <folder>" on one disk. Stop for a folder move ends the batch after
the file in hand; unlike a file move, no `quarantine` follows each copy, so the source
stays whole.

## Safety model in detail

The user guide's "What dam never does" gives the short version. The details:

- **Never deletes your files.** **Move to To Delete** (`dam quarantine` on the command
  line) moves a file to `##. To Delete/<original path>`. You empty that folder yourself.
  **Restore** (`POST /api/restore {drive_ids, to: "original" | "inbox" | "folder", folder?,
  dry_run}`, answering
  like `POST /api/quarantine`) moves entries (files, links or folders) out of it again as
  ordinary `move` operations in one journaled batch titled "Restored N files from To
  Delete": `original` is the path with the `##. To Delete` prefix stripped (a missing
  folder gets a `mkdir` in the plan, a taken name `_N` with its note), `inbox` the inbox
  folder. An entry inside another selected folder comes along with it; a folder that stood
  at the top of the archive, or an original place in `##. Ongoing`, is a 400 (use the
  inbox). `to: "folder"` (with `folder`) is a drag out of To Delete onto a folder in Browse:
  the same `move` operations into that ordinary folder (made if missing, a taken name `_N`);
  the top of the archive, `##. Ongoing`, `##. Important` and `##. To Delete` are a 400.
  Undo is the ordinary undo of a move and puts the entries back in To Delete.
  **To Delete exists per archive folder, and a rename never crosses disks.** A file in an
  extra folder goes to `<label>/##. To Delete/<path inside the folder>`, created on demand,
  and Restore moves it back inside the same folder. A move between folders on different
  disks is a verified copy followed by a move of the original to its own folder's To
  Delete (see [Moves across disks](#moves-across-disks)); nothing is deleted. One folder
  at a time moves the same way: a rename on one disk, and across disks every file copied
  and verified first, then the whole source folder to its own To Delete in one move (see
  [Folder moves](#folder-moves)). A folder that is not connected refuses every operation that touches it.
  While in `##. To Delete`, a file is read-only for the API: setting tags, a summary or a
  note, a checklist entry, ★ / !, a tray item and adding to a collection answer 400
  ("Marked for deletion: restore it first"); its existing tags, collection membership,
  notes and tray items stay, so a restore brings them back.
  **Link and Copy on a drop.** `POST /api/browse/move/preview` and `/api/browse/move` take
  `mode`: `move` (default), `link` or `copy`. `link` makes a symlink named like the file in
  the folder (`symlink` operation; the file stays; a taken name gets `_N`); `copy` makes a
  copy (`copy` operation with an archive path as its source, into an ordinary folder only,
  never the top of the archive, `##. Ongoing`, `##. Important`, `##. To Delete` or a
  protected path; a taken name, also the file's own in its own folder, gets `_N`; a file
  over 200 MB is refused). A row of `##. Ongoing` or `##. Important` stands for the file
  it links to (a link that leads outside the archive or nowhere is a 400); a move of a
  row of `##. Important`, or of a file marked Important, is a 400 ("This file is marked
  Important; unmark it first"). A file in `##. To Delete` is restored first. Each is one
  journaled batch ("Linked a.pdf in 20. Home", "Copied a.pdf to 20. Home"). Undo of a copy
  moves the copy to `##. To Delete` (never deletes it). `GET /api/status` has `can_link`
  (false only on Windows without Developer Mode, where Link is refused with a clear message).
  **Undo may remove a link the app made, anywhere in the archive** (approved by the owner;
  the one exception to "removals only inside `##. Ongoing` / `##. Important`"). It is
  narrow: only the undo of a journaled `symlink` operation (the planner builds the removal
  only for undo, flagged `exact`, carrying the target the link was made with), and the
  entry must still be a symbolic link pointing at exactly that target when the removal is
  planned and again just before it, so a regular file, a folder or a link someone else made
  is never removed; never inside `##. To Delete` or a protected path. It uses the same single
  `Path.unlink` as before (the AST test is unchanged).
  Apart from that, the only removals in the archive are inside `##. Ongoing` and `##. Important`
  (`special_folders.important`), under the same rules for both: a symlink (the app's own
  links, or a shortcut of yours that a previewed **Convert** replaces with the app's link
  at the same place), and an empty folder inside either one
  (`remove_empty_dir`, never recursive, never one that still holds anything): one the app
  created for a collection, for one of its groups (a subfolder of the collection's own
  folder) or for one of its **child collections** (a subfolder of the parent's folder,
  at any depth), always identity-checked (the very folder the app recorded when it made
  it), or your own real folder (e.g. `Legal`) that **Convert** has emptied by moving its
  contents out. Undo of a conversion restores that folder (if you unmarked a converted
  file, mark it again, in the same group, before undoing the conversion: the undo needs the
  app's link to be where the conversion put it). One exception covers Finder's
  cache: before removing such an empty folder, the app deletes a `.DS_Store` in it, but
  only a genuine Finder cache file (regular, a single link, Finder's magic bytes, no
  Drive id), only inside that folder, never anywhere else. Outside the archive the app
  removes only its own export cache (`prune_exports`), the stale files of its own page-1
  picture cache (`prune_page1_pictures`, see "Picture areas"), its reminder LaunchAgent
  plist (`--uninstall`) and, when the rules folder and the archive are on different disks,
  its own copy of a rule picture in `config/rules/areas` after the picture was copied to
  `##. To Delete` and the copy was verified by size and content hash
  (`remove_moved_picture`: only a regular file, not a link, directly inside the real
  `areas` folder, with the same hash as the copy; the owner's rule is that "no delete" is
  for archive files, not for dam's own temporary or cached files). An AST test pins these few calls, and only the operation layer writes
  to the archive. One more thing is removed, by undo and only when it is certain it is the
  app's own: an empty folder that a New folder / layout batch made (identity-checked,
  never one with anything in it). Undo of "Choose files…"/`dam add` *moves* the copy to
  `##. To Delete`. Rule pictures no rule uses (`config/rules/areas`) are moved to
  `##. To Delete` the same way (renamed on one disk, copied and then removed across disks),
  as `dam rule picture <name>`, previewed and undoable; the
  one file source outside the archive other than `dam add` is exactly that folder.
- **"Is this still the folder/link the app made?" is answered by file identity.** The
  app records, right after it creates a folder or link, its device number, inode number
  and **creation time**. It removes or touches the entry later only while the device and
  inode numbers still match, the kind is the same (folder or link) and, for a link, the
  target is exactly the one it wrote. The creation time is kept but **not compared**:
  Google Drive for desktop re-writes a newly created item a few seconds after it appears
  (same inode, a later creation time), so a changed creation time alone is the app's own
  entry. The app then stores the new creation time. A different inode, a different link
  target or a different kind is "not the same": the entry is kept and reported, never
  removed. A folder is also removed only while it is empty. The creation time is the
  macOS/Windows birth time; on Linux it is the `statx` birth time (ext4, xfs, btrfs,
  recent tmpfs), or for a link without one its change time. Because it is not compared,
  a folder or link you delete and recreate so that it gets the same inode number
  (Linux file systems reuse them at once) goes unnoticed for a folder, and for a link
  only if its target is also exactly the same, which is harmless; what could be removed
  is still only an empty folder inside `##. Ongoing`/`##. Important` (or one this app
  made), never a file. Identities are stored as text (Windows file indexes exceed
  SQLite's integers); records from older versions have no creation time.
- **Every change is journaled and undoable.** Each move/rename/folder creation is
  recorded before it happens, in batches. Undo first checks that each moved entry is still
  the one that was moved: for Drive files the same Drive ID, type and size (the
  modification time is ignored, because Drive rewrites it; so a same-size edit made in
  place does not block undo); for files without a Drive ID, size and mtime too. The Undo
  confirm lists exactly what undo will run, as the server plans it
  (`POST /api/activity/{batch_id}/undo/preview`, read only). An Activity title is the
  `label` the workflow stored with the batch (`operations.label`); older batches get a
  title derived from their operations.
- **Preview before apply.** On the command line, `file`, `quarantine` and `undo` print the
  plan and ask for confirmation unless `--yes` is given; `--dry-run` previews only. Name
  collisions get `_2`, `_3`, ... and never overwrite.
- **Guards.** `protected_paths` (default `##. Important`) are protected against marking
  for deletion and against removal; they are not frozen: you can still rename and move
  files inside them (previewed and undoable, like everywhere). The app's own links and
  empty folders in `##. Important`, above, are the one removal exception, and it covers
  only `special_folders.important`, never another protected path. **No top-level folder is
  ever created automatically** (filing suggestions, rules, syncs), except the quarantine
  folder (`##. To Delete`) itself when marking for deletion needs it. The one other way is
  a folder *you* ask for: **New folder** and **Set up folders**/`dam init` build a plan
  flagged `new_folders` (`Plan.new_folders`, used by nothing else), which the planner
  accepts only if it holds nothing but folder creations with valid names (no `/`, `\`,
  reserved Windows names, trailing dots, `##.` unless it is a special folder), none inside
  the app's own folders. Every path is confined to the archive root (no `..`, no escaping
  symlinks). A refused dry run has no Apply.
- **Locks.** A locked file is not renamed, moved or quarantined. Files marked Important
  (and everything under a marked folder) are always locked; any other file can be locked
  by the owner (table `file_locks`, migration 0031: `drive_id` primary key, `locked_at`;
  keyed by drive id so a lock survives moves and renames). The planner
  (`dam.ops.planner`) refuses a RENAME, MOVE or QUARANTINE of a locked file, of a folder
  holding one, and of a file inside a locked folder, for every route (rename, Move to…,
  drag and drop, Back to inbox, filing, Move to To Delete, conversions, the command
  line), before anything is journaled. One refusal names every locked file of the plan
  ("This file is locked. Unlock it to change it." for one, "These files are locked (a.pdf,
  b.pdf). Unlock them to change them." for several). Links, new folders and the app's own
  link syncs are not file changes; tags, notes, checklists, From and For, trays, stars,
  the Important mark and summaries are the app's own data and stay open. Undo is not
  gated (it only puts back what was done and is verified as always). The existing refusal
  to quarantine an Important file ("unmark it first") stays and comes first.

  A temporary unlock is a grant held in the server's memory (`dam.locks.LockService`),
  never stored, so a restart or a crash locks everything again. `POST /api/files/{id}/unlock
  {mode: "now"}` answers `{drive_id, locked, reason ("important" | "file" | null),
  unlocked_now, token, expires_after_idle_seconds}`; the page sends its tokens in the
  `X-Dam-Unlock` header (comma separated) and the planner accepts a locked file only when a
  live grant for exactly that file is among them. A grant expires after 15 minutes without
  use (each accepted use renews it) and is dropped by `DELETE /api/files/{id}/unlock`,
  which the page calls when the file is left. `{mode: "for_good"}` removes an ordinary
  lock (409 "An Important file can only be unlocked for now." for an Important file).
  `POST /api/files/{id}/lock` stores a lock (only files; also ends the file's grants).
  `GET /api/locks` answers `{files: [{drive_id, reason}], folders: [path]}`. The
  command line has no way to unlock, so `dam file`, `dam quarantine` and the like refuse a
  locked file; unlock it in the app first. Locking is not journaled (it changes nothing in
  the archive). It is a catch against mistakes, not a security boundary: whatever is
  signed in to the local API (your browser, or a program that has read the token file)
  can unlock.
- **`##. Ongoing` ownership.** The app owns an entry only if it still is the exact thing
  it created (the identity above). An entry you made yourself, or one that was replaced,
  is never touched, never adopted and never deleted. If a name is taken by something
  foreign, the app publishes under `<name>_2` (then `_3`, ...). The automatic sync after
  each scan uses the origin "workflow" in Activity and cannot be undone as such.
- **Local-only API.** The server binds `127.0.0.1`, checks the `Host` header (DNS
  rebinding), refuses `Sec-Fetch-Site: cross-site`, and requires mutating requests to
  carry a local `Origin` (or, without `Origin`, `Sec-Fetch-Site` of `same-origin` or
  `none`). POST requests must be JSON (`Content-Type: application/json`), except the two
  file uploads, "Choose files…" (`POST /api/inbox/upload`) and snapshot Import
  (`POST /api/snapshots/import`), which take `application/octet-stream` and pass the same
  host and origin checks. The UI is served with a strict CSP. Other
  web pages cannot read or change your archive.
- **Signed-in API.** The checks above stop web pages, not other programs on the same
  computer, which can all reach `127.0.0.1`. So every request under `/api` (file
  contents, page images, exports, sticker sheets, snapshots, and every change) also
  needs a secret token: the cookie `dam_auth_<port>` or the header `X-Dam-Token`;
  without it the answer is `401` with a plain message (`code: "not_signed_in"`), and the
  UI shows a full-page **Not signed in** with what to do. The start page and its assets
  need no token. The token (`secrets.token_urlsafe(32)`) is made on first use in
  `api-token` beside `archives.yaml`, so one token serves every archive the server can
  switch to; on macOS and Linux the file is mode `0600` (a looser mode is tightened
  again); on Windows it relies on the permissions of the user profile folder, which only
  you and administrators can read. `GET /auth?t=<token>` compares it in constant time,
  sets the cookie (`HttpOnly`, `SameSite=Strict`, `Path=/`, one year) and redirects (303)
  to `/`. The token is never logged (the access log shows `t=<hidden>`). Anything that
  can read your user files (the token file, or the browser's cookies) can still use the
  API: this keeps out other user accounts, sandboxed apps and web pages, not a program
  that runs as you with access to your files.
- **The database only.** Trays, items, notes, checklists, reminders, collections, stars,
  locks and tags live in `dam.sqlite` in the data folder. Nothing about them is written into the
  archive; the only archive writes for them are links and folders in `##. Ongoing` /
  `##. Important` and the moves of the conversion screens, always previewed and journaled.

## Maintenance

The Maintenance screen (`/maintenance`) runs checks the owner starts. Nothing is scheduled
and nothing runs in the background: each check is a job started by a request, polled, and
stopped by a request. A job also ends by itself when nobody has asked about it for 60
seconds, and the screen stops its running job when it is left. Jobs live in memory only.

- `GET /api/maintenance/duplicates/estimate` answers `{files, candidates, known,
  to_read_files, to_read_bytes}` from the index alone: `candidates` are the regular files
  that share a size with another (empty files, links and the app's own folders are left
  out), `known` those with a stored sha256, `to_read_*` what the check would open. Reading a
  file kept online-only in Google Drive for desktop downloads it.
- `POST /api/maintenance/jobs {kind, days?}` starts a check (`duplicates`, `empty_folders`,
  `broken_links`, `references`, `names`, `waiting`, `label_clashes`,
  `unfinished_copies` or `moved`; `days` only for `waiting`, default
  30) and ends an earlier job of that kind. `GET /api/maintenance/jobs/{job_id}` answers
  the progress (`state` running, done, stopped or error; `done`/`total`, `bytes_done`/
  `bytes_total`, `current`) and, once it is not running, `result` as the field named after
  its kind (`duplicates`, `empty_folders`, ...). Entries that moved or were marked for
  deletion since are left out of a result on every read. `GET
  /api/maintenance/jobs/latest/{kind}` answers the latest job of the kind (null for none).
  `POST /api/maintenance/jobs/{job_id}/stop` ends it where it is; what it found stays.
  `DELETE /api/maintenance/jobs?kind=` (Reset) forgets the jobs of the kind, or of every
  kind without `kind`, ending one still running; answers `{forgotten}`. Nothing in the
  archive changes.
- Ignoring results: `GET /api/maintenance/ignored` lists them (newest first: `id`, `kind`,
  `key`, `label`, `created`), `POST /api/maintenance/ignored {kind, key, label, members?}`
  adds one (again: label and members are replaced), `DELETE /api/maintenance/ignored/{id}`
  takes one back (404 if unknown). They live in the `maintenance_ignored` table (0034) and
  are left out of every result read, with the totals lowered. Keys per `kind`:
  `duplicates` the sha256, `versions` the name (folded), `empty_folders`, `broken_links`
  and `names` the drive id, `references` `"<collection|tray>-<owner id>-<item id>-<drive
  id>"`, `moved` `"<old drive id>><new drive id>"`. For `duplicates` and `versions`, `members` (required) are the group's drive ids;
  the group stays out only while all its files are among them.
- The `references` check gives a missing file's `path` as last seen: its index row's
  path, else the latest done journal operation for its drive id (null when neither
  knows). A gone collection member is taken out with the existing
  `POST /api/collections/{id}/members/remove`.
- The empty-folder check leaves out the top level, the app's own folders (`##. To Delete`,
  `##. Ongoing`, `##. Important`), protected paths and the folders an archive is set up
  with: the special folders themselves and the filing codes' inbox folders
  (`##. Organize/To pay`), which are often empty on purpose.
- The duplicate check hashes only the candidates, reads each file in chunks and checks for
  a stop between chunks, and stores the sha256 in `files.sha256` for the file as the scan
  recorded it (size and modified time must still match; the scanner clears a hash when a
  file changes). The index state is left alone, so the content pass still indexes the file.
  Exact groups are files with equal size and hash; `keep` is suggested by: not removable
  (Important or locked) first, then a numbered folder before the inbox or elsewhere, then
  the oldest, then the path. The same-name list compares names NFC-normalised and
  case-folded, and lists a name when two of its files differ in size or in a known hash.
- `POST /api/maintenance/duplicates/resolve {groups: [{keep, others, links?}], action:
  "quarantine" | "link", carry_over?, dry_run?}` is one batch for all groups: a
  `quarantine` of each file in `others` and, for `link` or a file in its group's `links`
  (which must be among `others`), a `symlink` at its old path to the kept file (an exact
  path: the quarantine has just freed it). The app sends `action: "quarantine"` with the
  copies to link in `links`, so one batch can move some copies and link others. Undo is the ordinary
  undo: it removes the link (a link the app made, still pointing at that file) and moves
  the copy back, so no new kind of removal exists. 400 when a copy is Important or locked
  (also unlocked "for now"), when the files are not known to have the same content (both
  need a stored hash), when a file changed on disk since the scan, when a file is in the
  app's own folders, or for a link without the symlink privilege. The answer is a batch
  result plus `carry_over` (per kept file: `tags`, `collections`, `notes`, `checklist`,
  `items`, `sender`, `person` that are or were added) and `carry_errors`. The carry-over is
  computed on a dry run and applied after the batch for the copies that were moved: tags
  are added, collection memberships are added with the batch id (Undo removes them),
  the removed copy's note is appended (or stored with the batch id when the kept copy has
  none), checklist entries the kept copy lacks are added, the kept copy is added to the
  tray items of the removed one, and From or For is filled only where the kept copy has
  none. A copy cannot be Important, so that mark is never carried.
- `POST /api/maintenance/links/remove {drive_ids, dry_run?}` removes broken links inside
  `##. Ongoing` or `##. Important` with the existing `unlink_symlink` operation (400 for a
  link anywhere else, or one that leads somewhere). Its undo needs the link's target to
  exist, so it is refused for these.
- The `moved` check ("Moved outside dam") finds files with a `local:` id (no Drive id,
  so the scanner matches them by path only) that were renamed or moved outside the app:
  the scan made a new row and flagged the old one missing, and what the owner gave the
  file stayed on the old row. It pairs a missing row that has something given (tags,
  collection places, tray item files, a lock, From and For, the filing code, summaries,
  edited fields, rule outcomes, a note or checklist entries) with a present row that has
  none, outside the app's own folders, of the same size (above zero) and sha256. The
  missing row needs a stored sha256 (`unhashed` counts those without); a present row
  without one is hashed as the duplicate check hashes (stored back, cancellable, with
  progress; `unreadable` counts failures). A content shared by more than one missing or
  more than one present row makes its pairs `ambiguous`. Each pair (`old_id`, `old_path`,
  `new_id`, `new_path`, `size`, `same_ext`, `ambiguous`, `moves`: what would move, counted
  by kind) drops out of a result on a read once it no longer holds.
- `POST /api/maintenance/moved/reconnect {pairs: [{old, new}], dry_run?}` reconnects
  pairs (`FileRepo.reconnect`, one transaction per pair): every row naming the file by
  the old id (the tables above, plus `member_link_names`; notes and checklists by
  `target_id`) moves to the new id, then the old row goes with its text, FTS row and
  content reads (the new row has its own). It changes the database only: nothing in the
  archive is touched, so it goes through no batch and is not in Activity. In the same
  transaction each pair is journaled in `reconnects` (migration 0039): the old `files`
  row as JSON and, per table, the keys besides the file id of each row that moved.
  Afterwards the collections sync runs, so a published link follows the file. 400 when a file is named twice, the old row is not missing or has nothing given,
  the new row is not a present regular file, is in the app's own folders, has something
  given or changed on disk since the scan, the stored hashes or sizes differ, or the pair
  is ambiguous; 404 for an unknown id. The answer is `{dry_run, pairs, errors, undo_id}`
  (`pairs` with what moved; `undo_id` is null for a dry run or when nothing moved). The
  AI call log keeps the old id: it is history.
- `POST /api/maintenance/moved/undo {undo_id}` undoes a reconnect
  (`FileRepo.undo_reconnect`, one transaction per pair): the old row is inserted again
  from the journal, still missing and with `index_state` pending (its text and content
  reads are not kept), with an FTS row for its name and path, and each journaled row
  still on the new id moves back by its keys. What the file was given since stays on the
  new id. A pair whose old id or old path is in use again, or whose new row is gone, is
  left as it is and named in `errors`. The answer has the shape of a reconnect's, with
  what moved back in `pairs`. 400 when it was undone already, 404 for an unknown id.
- Empty folders and broken links elsewhere are marked for deletion with `POST
  /api/quarantine`, a name is fixed with `POST /api/browse/rename`: the existing previewed
  endpoints.

## Index errors

Text is read from PDFs (OCR for scans), images, plain text, `.docx`, `.msg`,
`.xlsx`/`.xlsm`/`.xls`, `.pptx` (slides and notes),
`.doc`/`.dot`/`.dotx`/`.docm`/`.odt`/`.html`/`.webarchive` (macOS only, with `textutil`),
and Pages, Numbers and Keynote files (the preview inside the bundle, with OCR for
pictures). `GET /api/index/summary` gives the Index sheet's counts per state, the not
readable files per type and a page (`limit`, `offset`) of those files with their reasons, and
`page1`, the progress of the page-1 pass: `{read, total, backfill, rate_per_min, blocked:
[{reason, count}], text_left, scans_left, text_per_min, scans_per_min}`. `text_left` counts the
unread PDFs whose text came from their text layer (read quickly, no OCR) and `scans_left` the
unread scans and photos (OCR); `text_per_min` is `page1_text_reads_per_minute` and
`scans_per_min` the indexer's rate, so the time left is `text_left / text_per_min +
scans_left / scans_per_min`. `PUT /api/settings/page1-speed {reads_per_minute}` sets the
first (400 outside 1 to 6000). A read is "slow" and followed by the indexer's pause when it
needs OCR, fails to fetch the file or takes more than 3 seconds (a cloud-only file that had
to be downloaded; dam does not detect a cloud-only file beforehand, the indexer does not
either); a quick local text-layer read is followed by the shorter pause. "Read now" (the
test's button, `ContentIndexer.read_now`) adds the documents to the files the pass reads
next (after the inbox) and, until they are read, cannot be read now (timed out, no OCR
engine, missing) or 30 minutes have passed, the pause after every step is 50 ms; reads stay
one at a time and each keeps its time limit. `blocked` counts the documents whose page 1 cannot be read now (no OCR
engine, missing, took too long, no picture can be made, or waiting to be tried again) and
`rate_per_min` is the reads finished per minute over the last ten minutes (null when there
were fewer than three). `GET /api/status` has the same `page1`.

A file whose text could not be extracted is `error` (something a retry might fix: a
crash in the extractor, an extraction over 5 minutes) or `unsupported` (retrying will
not help: a `.docx` that is not a valid Word file or not a Word document, a
password-protected Word file or PDF, a type with no extractor, a file over 256 MB, a
Word, Excel, PowerPoint or iWork zip that would unpack to more than 512 MB, holds more
than 10,000 parts or has a part over 1 MB packed more than 200 to 1). The
reason is stored with the file (`files.last_error`). While a file is read its
`last_error` is `dam: reading`; recording the outcome replaces it, and closing dam clears
it. A file still marked on the next start (dam was killed mid-read, say out of memory)
becomes `error` with "reading this file stopped dam unexpectedly; it is skipped until you
retry it", so it is not read again until it is retried. `GET /api/index/errors` lists the
`error` files (`?all=1` adds the unsupported ones) with `reason` and `retry_at`, newest
file (mtime) first; `POST /api/index/retry {drive_ids}` puts those of them in `error` or
`unsupported` back to `pending` (attempts and reason cleared) and wakes the indexer. On
the command line: `dam errors [--all] [--retry]`.

## Open, reveal and previews

- `POST /api/files/{drive_id}/open` and `/reveal` run macOS `open <path>` or
  `open -R <path>`, on Windows `os.startfile` or `explorer /select,<path>`, on Linux
  `xdg-open <path>` (reveal opens the containing folder); an argument list, never a shell.
  The path comes only from the index by drive id, is resolved (symlinks followed) and must
  lie inside the archive root, so a stale entry or a symlink pointing elsewhere is refused
  (400); a missing, parked or vanished file is 404; on any other system 501. **Open**
  refuses apps, scripts and installers (`.app .command .terminal .workflow .sh .pkg .mpkg
  .scpt .action`, and any file with an executable bit, plus Windows and Linux program,
  script and shortcut types such as `.exe .bat .ps1 .lnk .desktop`) with 409 "Won't open
  apps or scripts from the archive — use Show in Finder"; Reveal still works for them.
  It also refuses web pages, SVG and XML files (`.html .htm .xhtml .svg .svgz .xml
  .webarchive .mht .mhtml`, by the file's, the resolved or the link's name), whose
  default app is a browser that would run their scripts as a local page, with 409 "Won't
  open web pages, SVG or XML files from the archive, as their scripts would run in the
  browser. Use Show in Finder".
- `GET /api/tags?prefix=&limit=` lists the tags in use with the number of files that have
  each (`[{"name", "files"}]`), those starting with `prefix` (case and accents ignored),
  most used first then by name, at most `limit` (default 8, up to 50): the tag field's
  suggestions.
- **Tags** (all in `dam.sqlite`, nothing journaled; the `tags` table also holds each tag's
  pin time, group and last use, `tag_groups` the groups, and `file_tags` has an index on
  the tag so "files with this tag" is a lookup, not a scan):
  - `GET /api/search?q=&tag=a&tag=b&tag_mode=all|any&folder=&limit=` searches. `q` is plain
    words (full text over names, paths and text; case and accents ignored) and filters
    `name:value` (module `dam.query` parses them in one place). Filters: `name` (file
    name only, `*` and `?` wildcards; without one the text may be anywhere in the name),
    `in` (a folder and below), `tag`, `collection` (the collection, the collections below
    it, and the files under a member folder), `from` / `for` (the sender or person assigned
    in `file_assignments`, contains, case and accents ignored), `type` (an extension or a
    group: image, doc, sheet, slides, text, mail, archive, audio, video), `date` /
    `after` / `before` (`YYYY`, `YYYY-MM` or `YYYY-MM-DD`; the date is `doc_date`, the date
    prefix of the file name, else the modified time; `after` includes the first day of the
    period, `before` excludes it), `tray` (open items, by tray id or name) and `is`
    (`starred`, `important`, `locked`, `todo`, `note`, `summary`). A `-` in front excludes.
    Values with spaces are quoted. Every filter must hold. A name before the colon that is
    not a filter is a plain word. A bad value (a date that does not exist, an unknown `is`
    word, a filter with no value) is a 400 with the reason; a tag, collection or tray that
    does not exist matches nothing (a `-` filter on it excludes nothing). `tag` (repeat it)
    adds tag filters beside the ones in `q`. With `tag_mode=all` (the default) a file needs
    every positive tag, with `any` at least one (one lookup over the union of the tags in
    the `file_tags` index; an unknown tag is then ignored, no known tag: nothing); `-tag:`
    always excludes. With no words the matching files are listed by name; a query with
    neither words nor filters finds nothing. Another `tag_mode` value is a 422. Tags,
    folders, assignments, trays, notes, checklists and collections are looked up through
    their own indexes; `type`, `date` and `name` compare columns of `files`. Browse keeps
    the whole query in `?q=` and, only for Any, `?tag_mode=any` (an old `?tag=` link is
    moved into `?q=`).
  - `GET /api/tags/all?query=` lists every tag, also those no file has yet:
    `{"tags": [{"name", "files", "pinned", "group_id"}], "groups": [{"id", "name"}]}`;
    `GET /api/tags/sidebar` the sidebar's tags (pinned first, then most recently put on a
    file, eight at most): `[{"name", "files", "pinned"}]`.
  - `POST /api/tags` `{name}` creates, `/rename` `{name, new_name}` (409 when another tag has
    that name: merge instead), `/merge` `{sources, into, dry_run}` (the dry run answers
    `{gains, removes, message}` and changes nothing), `/delete` `{name}`, `/pin`
    `{names, pinned}`, `/group` `{names, group_id | null}`. Each answers
    `{message, undo}`; `POST /api/tags/undo` takes that `undo` unchanged and puts the
    change back (`drop`: tags to delete, `detach`: links to drop, `restore`: tags back
    with their files, pin, group and last use).
  - Groups (one level, a tag is in at most one, never written on files):
    `POST /api/tags/groups` `{name}`, `/groups/{id}/rename`, `/groups/{id}/delete` (its tags
    are ungrouped; the answer lists them) and `/groups/restore` `{name, members}` for Undo.
- `GET /api/files/{drive_id}/thumb.png?width=300..2000` (default 1200) is a Quick Look
  thumbnail of any file type, rendered at the step at or above the width (600, 1200 or
  2000 px): `qlmanage -t -s <step> -o <dir> <file>` with a 20 s timeout, at most two at
  once, cached in `<data dir>/cache/thumbs/` per content (sha256, else drive id + mtime
  + size) and step; never written into the archive. No output, a hang or a non-macOS
  system is 404 `{"error": "no preview"}` (a failure is not retried for 10 minutes);
  so is waiting over 25 s for a render slot, which is not counted as a failure.
- `GET /api/files/{drive_id}/text?max=` returns the first 200 KB (or `max` bytes) of a
  txt, md, csv, log, json, xml or yaml file as UTF-8 (bad bytes replaced) and
  `truncated`.
- Browse: `GET /api/browse?path=&collection=` and
  `GET /api/browse/files?path=&collection=&sort=&dir=&limit=` (at most 500). Collections:
  `POST /api/collections {name, parent_id?}` and
  `PATCH /api/collections/{id}/parent {parent_id}` (null for the top). Order:
  `POST /api/collections/{id}/move {before_id?, after_id?}` puts an ordinary collection
  just before or after another one (give exactly one; 400 for a built-in collection on
  either side, itself, a cycle or none/both, 404 for an unknown id, 409 for a closed
  parent). With a sibling only the order changes and the answer has `batch: null` (no
  sync, no journal). With a collection of another parent it also moves into that parent,
  as `PATCH .../parent` does, at that position, and the answer carries the Ongoing sync's
  batch. Table `collections` has `position` (migration 0032,
  integer, default 0): the order among the collections with the same parent, backfilled
  from the name order; a new or reparented collection goes last; built-ins ignore it.
  Every list (`GET /api/collections`, the sidebar, pickers) is in tree order: built-ins
  first, then `position`, then folded name. `CollectionOut` has `position`. Browse takes
  `?path=<folder>&select=<drive id>` to open a folder with that file selected and
  previewed (a file no longer in it gives a notice). Notes:
  `POST /api/notes/{kind}/{target}/append`.

## Logs

Every command logs to `<data dir>/logs/dam.log`: INFO and up, rotated at 5 MB with 3 old
files kept (`dam.log.1` ... `dam.log.3`). Warnings and errors also go to stderr.
Internal-error tracebacks go to the log file only.

If a previous run was interrupted, commands warn you to run `dam recover` (not while the
app or another command has the archive; `dam serve` points to Run recovery in the app).

## Cloud drives

dam works on any folder: a plain local folder or one synced by Google Drive, OneDrive,
Dropbox, iCloud Drive and the like. The database, caches, logs and config are never inside
the archive folder.

**Google Drive for desktop** in streaming mode keeps most files cloud-only. Indexing reads
every file, so Drive downloads the **whole archive** into its local cache over time: plan
for free disk space about the size of the archive. The indexer is throttled
(`indexer_reads_per_minute`, default 30) and incremental, so the first full index is slow
by design. Scanning only reads metadata (and Drive IDs from the
`com.google.drivefs.item-id#S` xattr on macOS), so moves and renames made in Finder or on
the web are followed by Drive ID. An export skips files Drive has not downloaded
("cloud-only") and lists them.

With several archive folders this applies to each cloud-synced folder separately, so
plan the disk space for all of them.

**Check once on Google Drive.** These depend on how Drive for desktop behaves and cannot
be tested against a fake archive:

1. **Ongoing ownership.** The app recognizes its own links and folders by inode, assuming
   they keep it under Drive for desktop. Use a throwaway document and a new test
   collection: file the document into it, wait for Drive to finish syncing, then run
   `dam ongoing sync --dry-run`; it should show no operations. If it plans changes or the
   collection shows "Needs attention", Drive changed the inode. (A changed creation time
   with the same inode and link target is not a problem: Drive does that, and the app
   accepts the entry as its own and updates the stored time.) An entry with the same name
   and the same link target but a new inode is left alone: the sync reports
   "… looks different from before (Google Drive may have re-created it), so it was left
   as it is" and neither removes it nor publishes a `_2` beside it, and that collection is
   not synced until this is resolved. If you see this message, please report it (with the
   output of `dam ongoing sync --dry-run`): it means Drive does not keep inodes and
   ownership needs another way.
2. **Undo after Drive touches a file**: with a throwaway document, file it, let Drive
   sync, then undo it from Activity; it should still be accepted (same Drive ID, type and
   size).
3. **Group subfolders.** After converting an entry or grouping a collection's files, check
   that the group subfolders in `##. Ongoing/<collection>/` sync as expected in Finder
   and on drive.google.com, and that `dam ongoing sync --dry-run` then shows no operations.
4. **The reminders job after install.** See "Reminders setup": the LaunchAgent runs at
   once on your real data.

## Development

```sh
cd backend && uv run pytest -q -W error && uv run ruff check .
cd frontend && npm test -- --run
cd frontend && npm run gen:api     # regenerate src/api/schema.d.ts after API changes
```

Tests use temporary fake archives and never touch a real one. For UI work, run the
backend and the Vite dev server side by side:

```sh
cd backend && DAM_DEV_ORIGIN=http://localhost:5173 uv run dam serve --no-open
cd frontend && npm run dev         # http://localhost:5173
```

`DAM_DEV_ORIGIN` lets the API accept the dev server's `Origin`. With it set, the printed
sign-in link names `localhost` (`http://localhost:8765/auth?t=...`) and `/auth` redirects
to the dev server: the cookie is then on `localhost`, which the browser also sends to
port 5173, and the Vite proxy passes it to the API. Details in
`frontend/README.md` and [CONTRIBUTING.md](../CONTRIBUTING.md).
