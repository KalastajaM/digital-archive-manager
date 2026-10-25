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
- [Config and rules](#config-and-rules)
- [Tray files](#tray-files)
- [Reminders setup](#reminders-setup)
- [AI setup](#ai-setup)
- [Safety model in detail](#safety-model-in-detail)
- [Maintenance](#maintenance)
- [Index errors](#index-errors)
- [Open, reveal and previews](#open-reveal-and-previews)
- [Logs](#logs)
- [Cloud drives](#cloud-drives)
- [Development](#development)

## Requirements

dam runs on **macOS, Windows and Linux** (Python 3.13+, see "Platform support" below for
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
| Google Drive item ids (`xattr`) | yes | no: files keep a local identity | no (no Drive client) |
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
| `dam recover` | Settle operations interrupted by a crash (reads the disk, changes no files) |
| `dam openapi` | Print the API's OpenAPI schema |
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
is refused and tells you the port.

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
  the archive). It is a catch against mistakes, not a security boundary: anything that can
  call the local API can unlock.
- **`##. Ongoing` ownership.** The app owns an entry only if it still is the exact thing
  it created (the identity above). An entry you made yourself, or one that was replaced,
  is never touched, never adopted and never deleted. If a name is taken by something
  foreign, the app publishes under `<name>_2` (then `_3`, ...). The automatic sync after
  each scan uses the origin "workflow" in Activity and cannot be undone as such.
- **Local-only API.** The server binds `127.0.0.1`, checks the `Host` header (DNS
  rebinding), refuses `Sec-Fetch-Site: cross-site`, and requires mutating requests to
  carry a local `Origin` (or, without `Origin`, `Sec-Fetch-Site` of `same-origin` or
  `none`). POST requests must be JSON (`Content-Type: application/json`), except the one
  file upload of "Choose files…" (`POST /api/inbox/upload`, `application/octet-stream`),
  which passes the same host and origin checks. The UI is served with a strict CSP. Other
  web pages cannot read or change your archive.
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
  `broken_links`, `references`, `names` or `waiting`; `days` only for `waiting`, default
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
  id>"`. For `duplicates` and `versions`, `members` (required) are the group's drive ids;
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
- `POST /api/maintenance/duplicates/resolve {groups: [{keep, others}], action:
  "quarantine" | "link", carry_over?, dry_run?}` is one batch for all groups: a
  `quarantine` of each file in `others` and, for `link`, a `symlink` at its old path to
  the kept file (an exact path: the quarantine has just freed it). Undo is the ordinary
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
password-protected Word file or PDF, a type with no extractor, a file over 256 MB). The
reason is stored with the file (`files.last_error`). `GET /api/index/errors` lists the
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

If a previous run was interrupted, commands warn you to run `dam recover`.

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

`DAM_DEV_ORIGIN` lets the API accept the dev server's `Origin`. Details in
`frontend/README.md` and [CONTRIBUTING.md](../CONTRIBUTING.md).
