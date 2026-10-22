# Digital Archive Manager — user guide

A local tool for keeping a document archive tidy. The archive is a Google Drive
for desktop folder on this Mac. `dam` indexes it (file names, text, OCR) into a local
SQLite database, suggests a name, folder and tags for each new file in the inbox
(`##. Organize`), and moves files only after you have previewed the change. It has a
command line (`dam`) and a web UI served from `127.0.0.1`.

Phase 1 (foundation, inbox filing, browse/search, mark for deletion, activity/undo),
Phase 2 (trays, Today, collections and an app-managed `##. Ongoing`, export, reminders)
and the Mac redesign (a sidebar, Quick Look, drag and drop, the bank barcode, groups in
collections, two-pane Browse) are built. Designs:
`docs/superpowers/specs/2026-10-19-digital-archive-manager-design.md`,
`docs/superpowers/specs/2026-10-19-phase2-trays-collections-design.md` and
`docs/superpowers/specs/2026-10-20-mac-redesign-design.md`.

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
| Desktop notifications | yes | phase 2 | phase 2 |
| Daily reminder job (`dam remind --install`) | LaunchAgent | phase 2: schedule `dam remind` with Task Scheduler yourself | phase 2: systemd user timer or cron yourself |
| Links in `##. Ongoing` / `##. Important` | yes | needs Developer Mode (otherwise refused with a clear message); other link styles in phase 3 | yes |
| `.msg` e-mails | `dam[msg]` | `dam[msg]` | `dam[msg]` |

Windows and Linux are in **phase 1**: they install and pass the test suite in CI
(macOS, Windows and Ubuntu), and degrade with a plain reason where a feature is
missing. Full parity on each platform is phase 2. Unknown file junk such as
`.DS_Store`, `Thumbs.db` and `desktop.ini` is ignored by the index and never deleted.

Two Windows details. Links need Developer Mode (or an administrator account); CI runs the
link tests on a Windows runner that has the privilege. And a folder in `##. Ongoing` /
`##. Important` that holds a Finder `.DS_Store` is left in place when its collection is
closed or undone: dam only deletes that file through an open folder handle (to be sure it
is the very file it checked), which Windows cannot do. Drive for desktop does not sync
`.DS_Store`, so this only matters for an archive that was copied over by other means.
Settings and other text files are read and written as UTF-8, and an existing Windows
(CRLF) line ending is kept when dam edits a file.

## First run

State lives in the data dir, never in the archive: the SQLite database, caches, logs and
config (one data dir per archive: see "Several archives" below). Default:
`~/Library/Application Support/DigitalArchiveManager/` on macOS,
`%LOCALAPPDATA%\DigitalArchiveManager` on Windows and
`~/.local/share/DigitalArchiveManager` on Linux (the platform's user data folder). Override with
the `DAM_DATA_DIR` environment variable or `dam --data-dir <dir> ...` (the flag goes
before the command). To keep a test archive apart from your real one, add a second archive
instead of juggling data dirs: see "Several archives".

On first use `config/settings.yaml`, `config/rules/` and `config/trays/` are seeded from
`defaults/`. The defaults contain nothing personal and **no archive folder**: dam never
guesses where your documents are. You choose the folder once, in either way:

- **`dam init`** (in a terminal) looks for cloud-drive folders on your computer (Google
  Drive, OneDrive, Dropbox, iCloud Drive, Box, Nextcloud, pCloud, Insync), lists them with
  their provider names, lets you pick one and then the folder inside it (or create one),
  shows the one line it will write to `config/settings.yaml`, and asks before writing it.
  For scripts: `dam init --archive PATH [--yes]`; with `--layout household|minimal|empty`
  (and `--numbered/--no-numbered`) it also starts a new archive there, without questions.
  Interactively, an empty folder asks "Start a new archive here?", then which layout,
  numbering, the special folder names and edits to the list (`r 3 New name`, `d 3`,
  `a Name`), shows every folder and asks before making them.
- **The first-run screen**: run `dam serve` with no archive set and the browser opens a
  welcome screen with the same choices (the folders found, or any path you type) and
  checks the folder as you type. When you press "Use this folder" the app starts in the same
  window; no restart is needed.

The folder must exist, be readable and writable, and not be your home folder, the top of
a disk or inside dam's own data dir. Until one is set, every other command stops with
"No archive folder configured yet" and exit code 1.

**An empty folder (or one dam will create) is offered "Start a new archive here"**
(ignoring OS junk such as `.DS_Store`, `Thumbs.db` and `desktop.ini`); a folder with content
defaults to **Use as is** and can still get a layout added (only folders that do not exist
yet are made, nothing that is there is touched). Choosing a new archive shows the
starter layout, its numbering and the four special folders, all editable, and a preview of
every folder before anything is made: see "Starting from scratch" below. "Use as is" (the
way for everyone who already has an archive) writes only `archive_root` and creates
nothing: dam uses each special folder (`##. Organize`, `##. Ongoing`, `##. Important`,
`##. To Delete`) when it exists and works without them (the inbox is simply empty until you
have `##. Organize` and drop files in it). To see the app first without setting anything up, use the demo archive below.

Try the throwaway demo archive first. It builds a fake archive with about a dozen files
and its own data dir, and touches nothing else (the target must not exist or be empty).
The demo has:

- an electricity bill whose due date is already past;
- a water bill scanned as an image, with a Finnish bank barcode printed at its foot (the
  index reads it back, see "The bank barcode");
- a `##. Ongoing` like the real one (two links, a real folder and a real file);
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
data dir. Then open http://127.0.0.1:8766 if it did not open itself. `frontend/README.md`
has a walkthrough. Remove `/tmp/dam-demo` afterwards.

## Starting from scratch

A new user with an empty folder needs folders to file into, and dam never creates a
top-level folder on its own. So the first-run screen and `dam init` (and, any time later,
**Browse > Set up folders…**) offer a **starter layout**:

- **Household**: Finance, Bills & Receipts, Insurance, Taxes, Home, Vehicles, Health,
  Education, Work, Personal, Other. **Minimal**: Documents, Receipts, Other. **Empty**: only
  the special folders. The layouts are data files, `defaults/layouts/*.yaml` (one folder list,
  example rules and the folders kept from the AI per file): add your own beside them.
- **Numbered prefixes** (on by default): `10. Finance`, `11. Bills & Receipts`, ... the
  convention the older examples use; it keeps the folders in your order in any file manager.
- The list is **editable before anything is made**: rename, remove or add rows.
- The four **special folders** are made too, with editable names (the defaults are
  `##. Organize`, `##. Ongoing`, `##. Important`, `##. To Delete`). Each is explained on the
  screen: *Inbox* for new documents, *Ongoing* for the collections you are working on,
  *Important* for key documents, *To Delete* instead of deleting. The names you choose are
  written to `special_folders` in `settings.yaml` (and `protected_paths` follows a renamed
  Important folder); inside the running app they are fixed by the settings.
- **Preview, create, undo.** The preview lists every folder (the ones already there are
  marked and left alone). Making them is one journaled batch, titled "Created the archive
  layout (14 folders)" in Activity. **Undo removes only folders that are still empty**, and
  only the very folders that batch made (their identity was recorded when they were made);
  one that has gained a file, or was swapped for another, stays, and Undo says which.
- **Example rules and trays for the layout.** If your rules folder holds no rules of your
  own (nothing, or only the shipped `00-examples.yaml` exactly as shipped), it is replaced by
  rules that point at the new folders (receipts to `Bills & Receipts/{year}`, tax letters
  to `Taxes/{year}`, ...); a rule whose folder you removed is left out. The Finland bank
  examples stay in that file, commented out. Rules you wrote are never touched. The seeded
  trays do not refer to folders.

**New folder** (Browse toolbar or ⇧⌘N: a name row at the top of the list, "untitled
folder" selected; or right-click a folder for "New folder inside…", which opens a sheet
that previews what will be made as you type) makes one folder at the top of the archive or
inside the folder you are in, at once. It refuses a name with `/` or `\\`, one of the characters
`< > : " | ? *`, a reserved Windows name (`CON`, `NUL`, `COM1`, ...), a trailing dot, a
leading dot, or a `##.` prefix unless it is one of your special folders; surrounding spaces
are trimmed. It is user-initiated only, journaled ("Created the folder Taxes at the top of the
archive") and undoable while the folder is empty. Nothing is made inside `##. Organize`,
`##. Ongoing`, `##. Important` or `##. To Delete`.

**Getting documents in.** An empty inbox says where they go: put new documents in
`##. Organize` (drag them there in Finder, Explorer or your file manager, or point your
scanner at it), with **Show in Finder** (Explorer / "Show folder") and **Choose files…**,
which *copies* the files into the inbox (the originals stay), each up to 200 MB, a taken
name getting `_2`, never overwriting. Each copy is a journaled batch; **Undo moves the copy
to `##. To Delete`** (the app still never deletes). CLI: `dam add FILE... [--yes]`.

## Several archives

You can have several archives, for example your real one and a test one, and switch
between them. Each archive is completely separate: its own data folder with its own
`config/` (settings and rules), index database, caches, logs, exports and reminder state,
and its own archive folder. Whatever you do in a test archive cannot touch the main
archive's settings or files.

**Add one**: in the app, open the archive menu at the top of the sidebar and choose
*Add archive…* (a name and a colour first; then the usual first-run choices of a folder, or
*Start a new archive here* and a layout; or *Create a demo archive*, the fictional demo
archive built in a new or empty folder you pick). On the command line:
`dam archives add Test` (the same questions as `dam init`) or
`dam archives add Demo --demo --folder ~/Documents/Demo`.

**Switch**: choose an archive in the menu, or `dam archives switch Test` to change the one
`dam` uses by default, or `dam --archive Test scan` (or `DAM_ARCHIVE=Test`) for one command.
In the app the switch happens in the same window and the same server: the scanner,
watcher, indexer and reminder check of the archive you leave are stopped first, then the
other archive's start, so two archives' background work never runs at the same time.
Every change the page asks for names the archive it shows (`X-Dam-Archive`); a window
left open on the old archive after a switch is refused with a clear message (409) instead
of changing the wrong archive. A non-default archive has a thin band in its colour along
the top of the window, and the window title names the archive once there are several.

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
Window state kept in the browser (folded collections, the Today layout, the Browse view) is
kept per archive. The reminder job is per archive too: `dam remind --install` for the
archive `test` writes the LaunchAgent `nl.dam.remind.test` and runs
`dam --data-dir <base> --archive test remind`; the label of "Main" stays `nl.dam.remind`.
Once you have more than one archive, install the job again for "Main" too
(`dam --archive Main remind --install --force`): the new form names the archive, whereas a
job installed before archives existed follows whichever archive is in use. The API key and
e-mail password live in the system keychain, once per computer, shared by all archives.

**Forget**: *Manage archives…* (and `dam archives forget NAME`) removes an archive from the
list. **Nothing is deleted**: neither its data folder nor its archive folder is touched, and
both paths are shown so you can remove them by hand if you want to. The archive in use can
only be forgotten while choosing another one to open, and the last archive cannot be
forgotten. *Manage archives…* also renames, recolours and shows each archive's folders in
Finder / Explorer.

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

## Daily use

```sh
cd backend && uv run dam serve          # scans, watches and indexes in the background
```

Options: `--port N` (default `server_port`, 8765), `--no-open`. Ctrl+C stops it cleanly.

### Run it as its own app window

The app is installable, so it can run in its own window without browser tabs or an
address bar, with its own icon in the Dock:

- **Chrome:** open `http://127.0.0.1:8765`, then click the install icon at the right end
  of the address bar (or the menu: **Cast, save and share → Install page as app…**).
- **Safari:** open the same address and choose **File → Add to Dock…**.

The window follows the system light or dark appearance. `dam serve` must be running for
the window to work; the window opens the app at `/`, like a browser tab would. A
document's **⤢ Open in window** (see Quick Look below) opens a second, plain window next
to it.

| Command | Purpose |
| --- | --- |
| `dam --archive NAME-OR-ID ...` | Use another archive (also `DAM_ARCHIVE`); without it the archive in use is taken. The flag goes before the command |
| `dam archives list` | The archives dam knows; `*` marks the one in use |
| `dam archives add NAME [--color C] [--folder PATH] [--demo]` | Add an archive and set it up (the `dam init` questions, or `--demo` for the fictional demo archive in `--folder`) |
| `dam archives switch NAME` / `rename OLD NEW` / `color NAME #RRGGBB` | Make an archive the one in use; rename it; change its colour |
| `dam archives forget NAME [--switch-to OTHER]` | Remove an archive from the list; nothing is deleted, the paths are printed |
| `dam archives where NAME` | Print an archive's data folder and archive folder |
| `dam scan` | Sync the file index with the archive |
| `dam index [--limit N]` | Extract text / OCR for files not yet indexed |
| `dam errors [--all] [--retry]` | List the files whose text could not be indexed, with the reason (`--all`: also unsupported files); `--retry` queues every listed file for indexing again |
| `dam inbox` | List inbox files with suggested name, folder and sources |
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
| `dam remind [--now T] [--dry-run]` | Send the reminders that are due; `--dry-run` only lists them |
| `dam remind --install` / `--uninstall` / `--set-email-password` | Daily LaunchAgent; e-mail password (see Reminders) |
| `dam remind --test-notification [--dry-run]` | Send one test message through each enabled channel; marks nothing |

Exit codes: `0` success; `1` user error (unknown file, invalid request, guard refusal,
declined confirmation); `2` command line usage error; `3` internal error (traceback in
`logs/`); `4` a batch problem (an operation failed, index error or tagging error).

If the archive folder is not there (Drive not running or signed out, or a wrong
`archive_root`), every command except `dam openapi`, `dam remind`, `dam trays` and
`dam collections` (which read only the database) stops with exit `1` and says so;
`dam serve` does not start. An archive that disappears while `dam serve` runs is never
taken for an empty one: scans are skipped (nothing is marked missing), a warning is
logged, `/api/status` reports `archive_available: false` and the UI shows a banner.

`dam serve` without a built frontend (`frontend/dist/index.html`) prints
"frontend not built — run `cd frontend && npm ci && npm run build`", serves only the
API and does not open the browser.

## The app: sidebar and screens

The window has a **sidebar** on the left, like Mail or Finder, and each screen has a
toolbar at the top: its title, a short count, icon buttons (hover one for its name and
shortcut) and, where search applies, a search field. Light and dark follow the system
setting. The sidebar, from the top:

- **Today**, with a red badge counting overdue plus due-today items;
- **Inbox**, with its count;
- **Trays**: one row per tray, in tray order, each with its open count;
- **Collections**: **Important** first (the built-in collection of documents that must
  always be easy to find), then the open ones as a **tree** (a parent collection's
  children nest under it, A–Z on each level; the chevron at a parent's right end folds
  it, and the folds are remembered). The caption opens the list with "New collection"
  and the closed ones;
- **Archive**: **Browse**, **Ask** (AI questions about the archive) and **Activity**.

The archive-unavailable, recovery and tray-error banners show above the screen. The
status line at the sidebar's foot shows the inbox count and the indexing progress (hover
it for problems).

The screens:

- **Today**: a greeting, one line saying what waits ("6 to file · 1 bill due soon ·
  nothing overdue", or "All clear" when nothing does) and the date, then cards. Trays
  with nothing open are folded into one **Clear** card ("To pay, To action and To read
  are clear"), so the cards with content get the room; the cards are dealt out between
  the two columns by their size (your own order, once you move a card, wins).
  **To pay** has the open total and each
  bill with its payee, amount and an urgency tag (red overdue, orange within 3 days, grey
  later). Each tray row has a round checkbox before its title that marks the item done
  (a toast with Undo); where the tray's done action asks for fields (Mark paid), it opens
  that small form instead. **Inbox** has the count, the age of the oldest document, a bar for this week,
  last week and older (by arrival in `##. Organize`) and **Found in the inbox**:
  documents whose scan says they belong in a tray, each with **Put in <tray>**. Then
  **To action**, **To read**, the open collections that have to-dos (open checklist
  entries, or files still in the inbox; the rest are in the sidebar) and the last
  reminder check.
- **Inbox**: three columns: the sidebar, the list (thumbnail, suggested name, original
  name, date and a chip with the scanned due date and amount) and the document (the
  preview, with a narrow form beside it: name, folder, tags, the tray as a segmented
  control, tray fields, collections, note). ⌘-click and ⇧-click select several; the batch
  form appears for more than one.
  Tags are chips, as on a filed file's details (Enter or a comma adds one, the tags in use
  are suggested as you type); the batch form's tags go on every file. **Ask AI** is the
  sparkle button on the card's action row, and **Preview** (↩) and **File it** (⌘↩) have
  tooltips saying what they do.
  A missing name or folder is flagged on its own field (and focused). In the folder field
  the first suggestion is active as you type: **Enter** takes it, **↑/↓** move, **Esc**
  closes. "Planned changes" appear after the form (stuck to the bottom of the form column),
  so previewing never pushes the fields down. Below 900 px the preview pane is hidden
  (**Space** opens Quick Look; the **Show preview** button brings it back above the form)
  and the list and form stay side by side down to 761 px; narrower, everything stacks.
  Detected fields name their sources in plain words ("file date", "date in the text",
  "barcode", "rule …", "similar files"), and several amounts are told apart (a Total,
  then "Other amount 1, 2"). A tray's required field left empty does not block filing, and
  nothing nags about it.
- **A tray** (`To pay`, `To action`, `To read`): the list with Open/Done, and the selected
  item beside it (`↑`/`↓` move the highlight *and* open the item). A bill shows its title,
  a big amount, then rows with their own Copy button (payee, IBAN, reference, amount, due
  date with its tag), the bank barcode, and one action row: **Mark paid** (the tray's done
  button, **Mark done** where the tray has no label of its own), **Mark paid and file…**
  (only while one of the item's files is still in the inbox: it marks the item done and
  opens that file in the Inbox, where you file it), and the selected file's own buttons:
  Ask AI, Move to To Delete and "Take this file off the item" (the file stays where it
  is). Every button has a tooltip; the eye in the item's header is Quick Look (Space).
  Nothing says "needs a …" for a required field left empty, anywhere (the field just stays
  empty; the API still reports `missing_required` and the "No date" level). Tray list
  rows show no file count. A dated tray (To action) leads with the title, then one row with the date field (narrow), its urgency
  tag and **Mark done** (right-aligned, with **Mark done and file…** when shown), above the
  summary. The action row has **Move to tray ▾** (open items) and **Remove from tray**,
  which asks first and deletes the item with its note, checklist and history (open or
  done; the files are never touched, so there is no Undo). `⌫` on the selected row does the
  same. Under the title, "1 file · Add another file…" attaches another
  file to the item (several files show as tabs, with the same link at their end); **Add
  file** in the list column's toolbar searches the index and makes a new item in the tray
  for the file you pick, which opens.
- **Collections** and **a collection**: the summary, a **Needs attention** strip (members
  in an open tray item or still in the inbox), where it sits ("In Houses › …"), its
  **child collections** with their counts, the groups (see Groups below), notes and a
  checklist; the selected file on the right: a PDF one page at a time (with a pager under
  it), its name, folder, tags, group and a row of buttons (★, !, Ask AI, Move to To
  Delete, an eye for Quick Look, and Remove from collection, which the built-in ★ and !
  collections leave out: the ★ / ! button is that). The member list has its own scrollbar
  on a big collection, so the note and checklist stay within reach.
  The subtitle counts what the collection holds the same way as the list does ("1 folder · 23 files"); a group header counts its own members ("3 files, 1 folder").
- **Browse**: the archive's folders with search, **New folder** (toolbar and ⇧⌘N: a name row in
  the folder you are in; right-click on a folder for "New folder inside…"; made at once and
  undoable, see "Starting from scratch"), in one pane with a preview or in **two
  panes** (the split toggle in the toolbar) to move files between folders. Mark for
  deletion and **Move to…** are in the toolbar. Each pane has a **Collection** menu
  and a **Folders / Files** toggle (see "Browse by collection" below). With one pane, the
  row the cursor is on *is* the selected file: click it or step to it with `j`/`k` and the
  detail beside the list shows it, **preview first** (name and path above it), then the
  file's trays, stars and actions, summary and note. Nothing is highlighted, and the
  detail says "No file selected", until you pick a row. Folders are opened, not selected
  (no checkbox on a folder row). Drag the edge between the list and the detail to change
  the list's width (or focus it and use `←`/`→`); the breadcrumb stays on one line and
  shortens its middle folders with an ellipsis. With two panes the active one has an accent
  top edge and a tinted header.
- **Activity**: a timeline of every journaled batch, newest first (each card is collapsed
  to its top part; the chevron or a click on the title row opens its operations, **Expand
  all** / **Collapse all** sets the default, remembered in this browser, and a search
  shows the cards open), under day headers
  (**Today**, **Yesterday**, then the date). Each batch is titled with what you did and
  to what ("Filed Offer of Näkymä into 80. Misc", "Moved 20250822_… to To Delete",
  "Starred X.xlsx", "Undo of …", "Automatic ##. Ongoing update"). The title is the
  `label` the workflow stored with the batch (`operations.label`, migration 0022);
  older batches get a title derived from their ops. The `##. Ongoing` update a
  collection change causes is titled with what you did ("Renamed collection X to Y",
  "Added 3 files to Z", "Starred X.xlsx", "Moved collection X into Y"); only a sync no
  one asked for (after a scan) reads "Automatic ##. Ongoing update". A batch also shows its state
  (**Undone** for a batch that was undone), its time, and its own **Undo**; batches
  with more than three operations keep the operation list behind a fold, and a batch
  made from the command line says so. Automatic `##. Ongoing` syncs have no Undo; they
  say "Made automatically after a collection change" and link the collection to change
  to undo it. Interrupted operations show a recovery panel
  on top. The **AI** view lists the AI calls (see AI below) with the month's total and
  the on/off switch.
- **Ask**: a question about the archive, answered with numbered sources that open in
  Quick Look (see AI below).
- **Convert ##. Ongoing** (`/ongoing`, linked from Today): one card per entry, with its
  binding preview (see Collections and `##. Ongoing`).

**Links.** A symlink in the archive previews and opens **as its target** when the target
is a live file inside the archive: the preview says "Link to `<path>`" with **Go to
target**, which opens Browse at the target's folder with it selected; Open and Show in
Finder act on the target (the same refusals as for any file). A link to something outside
the archive, missing or not indexed has no preview and no Open, only Show in Finder, which
reveals the link itself.

**Quick Look.** **Space** (outside a text field) opens the selected document nearly full
window: the preview with zoom (the buttons, ⌘-scroll, `+`/`−`/`0`) and drag to pan, page
navigation, **opening at Fit** (the whole page visible, not cropped; `0` returns to Fit, and
the zoom you choose stays while you page through the documents), and its details (name, folder, trays, collections, scanned fields). `→`/`←`
(or `j`/`k`) go to the next or previous document of the list it was opened from; Space or
Esc closes it (Space on one of its focused buttons presses that button). It works in the Inbox, the trays, a collection and Browse.

**The viewer window.** **⤢ Open in window** (in the preview and in Quick Look) opens the
document in a separate browser window with the preview, zoom and details. It **follows the
selection** of the window that opened it, so you can put two things side by side; the pin
toggle keeps it on one document.

### Keyboard shortcuts

Single-letter keys work when the focus is not in a text field (Esc leaves one).

| Where | Key | Does |
| --- | --- | --- |
| Lists (Inbox, trays, a collection, Browse) | `j` / `k` or `↓` / `↑` | Next / previous |
| Lists | **Space** | Quick Look of the selected document |
| Quick Look | `→` / `←`, `j` / `k` | Next / previous document |
| Quick Look | Space, Esc | Close |
| Preview, Quick Look, viewer | `+` / `−` / `0`, ⌘-scroll | Zoom in / out / Fit (the whole page; the default) |
| Inbox | ⌘-click, ⇧-click | Select several (the batch form) |
| Inbox | `Enter` | Preview the filing |
| Inbox | ⌘`Enter` | File it (after the preview's confirm) |
| Inbox | `n` / `f` | Edit the name / the folder |
| Inbox | `1`–`9` / `0` | Choose a tray / no tray |
| Inbox | `u` | Undo the last filing |
| Trays | `Enter` | Open the item |
| Trays | `d` | Done (Mark paid in To pay) |
| Trays | `⌫` | Remove the item from the tray (asks first) |
| Trays (To pay) | `b` | Show the large barcode (Pay mode) |
| Browse | `Enter` | Open the folder or file |
| Browse | `⌫` | Up one folder |
| Browse | ⌘-click, ⇧-click | Select several files |
| Browse | ⌘⇧M | Move to… |
| Browse | ⌘⇧N | New folder in the active pane's folder |
| Browse | ⌘[ / ⌘] | Back / forward in the active pane |
| Confirm sheets | ⌘`Enter` | Confirm (only half a second after it opened, and after a key-up) |
| Confirm sheets | Esc | Cancel (Cancel has the focus) |
| Menus | `↑` / `↓`, Home / End, Esc | Move, first / last, close |

### Drag and drop

Drag documents from the Inbox list, Browse, a collection's file list or a tray list; a
selection drags all of it (the drag image shows the count). A valid target highlights; an
invalid one shows why it is not allowed.

| Drop on | What happens |
| --- | --- |
| A tray in the sidebar | Creates an item per file, prefilled from its scan, like **Put in <tray>**. The file stays where it is (in the inbox, it is filed later). The toast has **Open** and **Take back**. A file that already has an open item in that tray gets none ("already in To pay"). A file whose open item is in another tray has that item moved here instead (see Trays); the toast says "Moved to …" and its Undo moves it back. |
| A collection in the sidebar | Adds the files as members, ungrouped. No confirm (it only changes the app's own links in `##. Ongoing`); the toast shows the result. Refused for a closed collection or when all files are already members. |
| A collection in the sidebar, dragged onto another collection (or onto the **Collections** caption) | Moves the collection inside the other one (or to the top level), with everything under it. No confirm (only the app's own links and folders in `##. Ongoing` change); the toast shows the result, with **Open** for the batch. Refused with a reason when it would make a cycle, the target is closed, or it is already there. |
| A group inside a collection | Adds the files to that group, or moves them there if they are already members. |
| A folder in Browse (a folder row, or the other pane) | **A move, always behind the preview and confirm**: the sheet lists the exact moves (`_2` on a name collision, new folders), then the move is journaled and the toast has **Undo**. A drop never moves a file by itself. Refused for `##. To Delete` (use Mark for deletion), `##. Ongoing` and the archive's top. |

Every drop has a keyboard or menu equivalent: the Inbox form, "Put in tray…" and "Add to
collection…" on a file, the group menu, and **Move to…** (⌘⇧M) in Browse. Only files move;
folders can be browsed and dropped on, not dragged.

**`dam move`** is the same move on the command line:

```sh
uv run dam move "40. Family/beach.jpg" --folder "30. Home" --dry-run   # show the plan
uv run dam move "40. Family/beach.jpg" --folder "30. Home"             # asks, then moves
uv run dam undo <batch id>                                             # from dam activity
```

It takes paths or Drive IDs, keeps the names (`_2` on a collision), and refuses folders,
`##. Ongoing` and `##. To Delete` (use `dam quarantine`).

### The bank barcode

A bill in **To pay** shows the Finnish bank barcode (pankkiviivakoodi, version 4 for a
national reference or 5 for an RF reference) as a Code 128 symbol, with its 54 digits and
**Copy**. It is drawn as large as the pane allows (2 px a module, scaled down to the width
of the pane while a phone can still read it).

- **It is built from the item's fields**, always: the IBAN (FI only), the amount, the
  reference and the due date. What the rows say is what the barcode says; change a field
  and the barcode follows.
- **When it is not shown**: if a value is missing or cannot be encoded (a non-FI IBAN, an
  amount over 999 999,99 €, a reference that fails its check digit), the screen says why
  in one line. The built code is checked against the format's own rules before it is
  shown; a wrong barcode is never drawn.
- **The printed barcode.** A barcode printed on the scan is read while indexing (inbox
  files, and the files of open To pay items). It is the preferred source of the scan's
  prefill. If it disagrees with the item's fields (say you changed the amount for a
  partial payment), a warning names the differing values and offers **Use the printed
  barcode's values**; neither side is taken silently.
- **Scanning it from the screen.** Open the bill; if the barcode is too small for your
  phone, press **Show large barcode** (or `b`) for **Pay mode**: the barcode at full size
  with the payee, amount, reference, IBAN and due date in large type, to check against the
  bill while you scan, and **Copy barcode number**. (A very narrow window says "Too narrow
  to scan"; use Pay mode or widen it.) In your banking app choose to pay with a barcode (in most Finnish banks: *Pay* → *Scan
  barcode*). Hold the phone so the barcode fills most of the camera view, about 15–25 cm
  from the screen, and check the payee, amount and reference the app shows before you
  confirm. Without a camera, **Copy** the 54 digits and paste them into the bank's
  "virtual barcode" field.

The payee is shown above the IBAN. It is a field of the To pay tray, prefilled from a
rule's `then.payee`; see Trays for how to add it to a tray file that was seeded before it
existed.

### Index errors

Text is read from PDFs (OCR for scans), images, plain text, `.docx`, `.msg`, `.xlsx`/`.xlsm`/`.xls`,
`.pptx` (slides and notes), `.doc`/`.dot`/`.dotx`/`.docm`/`.odt`/`.html`/`.webarchive` (macOS
only, with `textutil`), and Pages, Numbers and Keynote files (the preview inside the bundle,
with OCR for pictures). Migration 0025 puts `unsupported` files of these types back to
`pending` once. The status line at the sidebar foot ("N searchable, N waiting, N not
readable") opens the Index sheet; `GET /api/index/summary` gives its counts per state, the
not readable files per type and a page (`limit`, `offset`) of those files with their reasons.

A file whose text could not be extracted is `error` (something a retry might fix: a
crash in the extractor, an extraction over 5 minutes) or `unsupported` (retrying will
not help: a `.docx` that is not a valid Word file or not a Word document, a
password-protected Word file or PDF, a type
with no extractor, a file over 256 MB). The reason is stored with the file
(`files.last_error`, migration 0012). `GET /api/index/errors` lists the `error` files
(`?all=1` adds the unsupported ones) with `reason` and `retry_at`, newest file (mtime)
first; `POST /api/index/retry {drive_ids}` puts those of them in `error` or
`unsupported` back to `pending` (attempts and reason cleared) and wakes the indexer.
On the command line: `dam errors [--all] [--retry]`.

### Open, reveal and previews of any file

- `POST /api/files/{drive_id}/open` and `/reveal` run macOS `open <path>` or
  `open -R <path>`, on Windows `os.startfile` or `explorer /select,<path>`, on Linux
  `xdg-open <path>` (reveal opens the containing folder); an argument list, never a shell. The path comes only from the
  index by drive id, is resolved (symlinks followed) and must lie inside the archive
  root, so a stale entry or a symlink pointing elsewhere is refused (400); a missing,
  parked or vanished file is 404; on any other system 501. **Open** refuses apps, scripts
  and installers (`.app .command .terminal .workflow .sh .pkg .mpkg .scpt .action`, and
  any file with an executable bit, plus Windows and Linux program, script and shortcut
  types such as `.exe .bat .ps1 .lnk .desktop`) with 409 "Won't open apps or scripts from the
  archive — use Show in Finder"; Reveal still works for them.
- `GET /api/tags?prefix=&limit=` lists the tags in use with the number of files that have
  each (`[{"name", "files"}]`), those starting with `prefix` (case and accents ignored),
  most used first then by name, at most `limit` (default 8, up to 50): the tag field's
  suggestions.
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

## Logs

Every command logs to `<data dir>/logs/dam.log` (default
`~/Library/Application Support/DigitalArchiveManager/logs/dam.log`): INFO and up,
rotated at 5 MB with 3 old files kept (`dam.log.1` ... `dam.log.3`). Warnings and errors
also go to stderr. Internal-error tracebacks go to the log file only.

If a previous run was interrupted, commands warn you to run `dam recover`.

## Safety model

- **Never deletes your files.** **Move to To Delete** (the bin, ⌘⌫; `dam quarantine` on
  the command line) moves a file to `##. To Delete/<original path>`. You empty that folder yourself, in Finder or Drive.
  The only removals in the archive are inside `##. Ongoing` and `##. Important`
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
  Drive id), only inside that folder, never anywhere else. Outside the archive the app removes only its own export
  cache (`prune_exports`) and its reminder LaunchAgent plist (`--uninstall`). An AST test
  pins these few calls, and only the operation layer writes to the archive. Two more
  things are removed, both by undo and both only when it is certain they are the app's own:
  an empty folder that a New folder / layout batch made (identity-checked, never one with
  anything in it), and nothing else: undo of "Choose files…"/`dam add` *moves* the copy to
  `##. To Delete`.
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
  recorded before it happens, in batches. `dam activity` / the Activity page list them;
  `dam undo` / the Undo button revert a whole batch. Undo first checks that each moved
  entry is still the one that was moved: for Drive files the same Drive ID, type and
  size (the modification time is ignored, because Drive rewrites it; so a same-size edit
  made in place does not block undo); for files without a Drive ID, size and mtime too.
  **Tags are not journaled**: undoing a filing moves the file back but keeps the tags it
  was given. Undoing a filing also removes the tray items, collection memberships and
  notes it created (DB only). **Undo is refused for automatic `##. Ongoing` syncs**
  (batches the app made by itself after a scan or a member change): undo the collection
  change instead; the Activity page hides Undo for them. The Undo confirm lists exactly
  what undo will run, as the server plans it (`POST /api/activity/{batch_id}/undo/preview`,
  read only); when undo would be refused it says why and Undo stays disabled.
- **Preview before apply.** The UI always shows a dry run (new folders, `from -> to`)
  first, and Apply needs your confirmation. On the CLI, `file`, `quarantine` and `undo`
  print the plan and ask for confirmation unless `--yes` is given; `--dry-run` previews
  only. Name collisions get `_2`, `_3`, ... and never overwrite.
- **Guards.** `protected_paths` (default `##. Important`) are protected against marking
  for deletion and against removal; they are not frozen: you can still rename and move
  files inside them (previewed and undoable, like everywhere). The app's own links and
  empty folders in `##. Important`, above, are the one removal exception, and it covers
  only `special_folders.important`, never another protected path. A file marked
  **! Important** cannot be marked for deletion anywhere; **no top-level folder is ever
  created automatically** (filing suggestions, rules, syncs), except the quarantine folder
  (`##. To Delete`) itself when marking for deletion needs it. The one other way is a
  folder *you* ask for: **New folder** and **Set up folders**/`dam init` build a plan
  flagged `new_folders` (`Plan.new_folders`, used by nothing else), which the planner
  accepts only if it holds nothing but folder creations with valid names (no `/`, `\`,
  reserved Windows names, trailing dots, `##.` unless it is a special folder), none inside
  the app's own folders; the plan is previewed and journaled like any other. Undoing it
  removes a folder only while it is still empty and still the one that was made. Every path
  is confined to the archive root (no `..`, no escaping symlinks). A refused dry run has no
  Apply.
- **Local-only API.** The server binds `127.0.0.1`, checks the `Host` header (DNS
  rebinding), refuses `Sec-Fetch-Site: cross-site`, and requires mutating requests to
  carry a local `Origin` (or, without `Origin`, `Sec-Fetch-Site` of `same-origin` or
  `none`). POST requests must be JSON (`Content-Type: application/json`), except the one
  file upload of "Choose files…" (`POST /api/inbox/upload`, `application/octet-stream`),
  which passes the same host and origin checks. The UI is
  served with a strict CSP. Other web pages cannot read or change your archive.

## Phase 2: trays, collections, reminders

The app keeps all of this in its database (`dam.sqlite` in the data dir). Nothing about
trays, items, notes, checklists or reminders is ever written into the archive; the only
archive writes are links and folders in `##. Ongoing` and the moves of the conversion
screen, always previewed and journaled.

The web UI's sidebar lists **Today · Inbox · the trays · the open collections · Browse ·
Activity** (see "The app: sidebar and screens").

### Trays

A tray is a to-do list of scanned documents: once a scan is filed into a tray, the paper
can go. Four trays are seeded from `defaults/trays/` into `config/trays/`:

| Tray | For | Fields | Reminders |
| --- | --- | --- | --- |
| **To pay** | bills | `payee` (prefilled from a rule's `then.payee`), `due_date` (required), `amount`, `iban`, `reference`, prefilled from the scan; copy buttons on amount, IBAN and reference; "Mark paid" asks for `paid_on` (default today) | 3 days before, on the day, and once when overdue; Today shows the open total |
| **To action** | things to do by a date (e.g. "no water on inspection day") | `action_date` (required) | 1 day before and on the day |
| **To read** | reading with no date | none | one nudge when an item has waited 30 days |
| **Follow up** | things you wait on from others (a delivery, a reply, a refund) | `check_by` (optional date), `waiting_for`; "Done" asks for nothing more | on the check date and once when it is overdue; an item without a date has no reminders and sits after the dated ones |

**One tray per item.** A file's open item lives in exactly one tray. "Put in tray" (the
file's menu, the Inbox's "Then put it in", the quick-put keys, a drop on a tray) for a
file that already has an open item in another tray **moves that item**: it is the same
item, so title, note, checklist, history and files stay, and its history says "Moved from
To action to Follow up". It leaves the old tray's list. Field values are kept by name:
the ones the new tray also has carry over; the others stay in the item's data, hidden, so
moving back restores them; the date is recomputed from the new tray's date field. The
same happens from **Move to tray ▾** on the item (`POST /api/items/{id}/move`). Undo in
the toast (or undoing the filing) moves it back (`POST /api/items/{id}/undo-move`, only
while the move is the item's latest change). A file whose item is already **done** gets a
new open item as before; the done item and its history stay. A file already open in the
target tray is skipped ("already in …").

An item has a title (the file name without its date prefix, editable), one or more files,
its fields, a note and a checklist, and a history; "Reopen" undoes "Mark paid"/"Done".

**Add a tray**: put a YAML file (one tray per file) in `config/trays/`, e.g.
`config/trays/50-to-sign.yaml`. It is read when `dam serve` (or any `dam` command) starts: restart
`dam serve` after changing a tray file.

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

### Today

The front page (`/`): a greeting and the date, then a card per tray, the inbox and the
extras (described under "The app: sidebar and screens"). Bill and item rows carry their
key fields, copy buttons, the first part of the note and the done button; items missing a
required date show "needs a due date" (a date field that is not `required`, like Follow
up's `check_by`, never does). Today also shows a banner while `##. Ongoing` or
`##. Important` holds anything not managed (a message and a **Convert** button; every
screen shows its banners the same way, inside the content column), tray file errors, and
the result of the last reminder check. The collections card lists only the open
collections with to-dos. It reads only the database: no tree walks or scans per request.

### Filing into a tray from the Inbox

On a review card, "Then put it in" is a segmented control with one choice per tray
(`1`–`9`, `0` for none). The tray's fields appear,
prefilled from the scan and marked "found in scan": the due date only from a labelled date
(`eräpäivä`, `due date`, ...), never guessed; the amount from the line after `yhteensä` or
`total`, else the largest amount. Edit them, optionally add a note and "Also add to
collection" (type a new name to create one), then file. The document is filed exactly as
before (preview, confirm, journal), and the item is created only if the move succeeded.
What the preview showed is what is applied. The batch card creates one item per file, each
prefilled from its own scan. Undoing the filing also removes the item, collection
membership and note it created.

The card's "Detected fields" are editable: remove a field with its x, change a value with
the pencil, or add one ("Add field", including your own labelled ones). The list is saved
per file (`file_fields`), replaces the detected one everywhere the scan values are used
(the tray prefill, Quick Look), and "Reset to detected" deletes it.

### Collections and `##. Ongoing`

A collection is a named group of files or folders across the archive, held by Drive ID so
it follows moves and renames; nothing is copied. A file can be in several. Open
collections are published into `##. Ongoing` so they are visible in Finder:

- a collection with several members becomes a folder `##. Ongoing/<name>/` of symlinks;
- a collection whose only member is one folder becomes a single link
  `##. Ongoing/<name>` to it;
- a collection without usable members (empty, or every member missing or in
  `##. To Delete`) is not published;
- closing a collection (or switching "publish" off) removes its links and then its empty
  folder; reopening publishes them again.

A **child collection** (see Parent collections below) is published inside its parent's
folder, in the same two forms: `##. Ongoing/Houses/Sauna/` or one link
`##. Ongoing/Houses/Sauna`.

`##. Ongoing` is **app-managed**. The app owns an entry only if it still is the exact thing
it created: it records the identity (device and inode, and for links the target) of every
link and folder it makes, and ignores everything else. An entry you made yourself, or one
that was replaced, is never touched, never adopted and never deleted. If a name is taken by
something foreign, the app publishes under `<name>_2` (then `_3`, ...) and the collection
shows a **Needs attention** status explaining why. The automatic sync after each scan uses
the origin "workflow" in Activity and cannot be undone as such (undo the collection change
instead).

### Parent collections

A collection can live **inside another collection**, to any depth: `Houses › Sauna ›
Deck`. The sidebar shows the tree (fold a parent with its chevron); a collection's page
says where it is ("In Houses › …") and lists its child collections with their counts;
pickers show full paths. To move one: **drag it** in the sidebar onto another collection
(or onto the **Collections** caption for the top level), or use **Move to…** in its **⋯**
menu (a picker with search: Top level and the open collections by path; the collection
itself and everything under it are left out). **New collection inside…** creates a child.
A move is refused when it would make a cycle, the target is closed, or the collection is
already there. The API: `POST /api/collections {name, parent_id?}` and
`PATCH /api/collections/{id}/parent {parent_id}` (null for the top).

In `##. Ongoing` the tree is mirrored: a child collection is published **inside its
parent's folder**, `##. Ongoing/Houses/Sauna/…` (or, when its only member is one folder
and it has no groups and no published children, the single link
`##. Ongoing/Houses/Sauna`), beside the parent's own links and group folders; a name
clash among them gets `_2`. A parent with nothing of its own is still a folder while a
child is published in it, and a parent that was one direct link becomes a folder when a
child is published (its link moves inside). A child is shown only while every collection
above it is open and published: a child that would be shown but whose parent is not gets
the status **not shown: its parent collection 'Houses' is not shown in ##. Ongoing**
(a status only; the Finder popover on its page says the same).

The rules for closing: **a parent with open children cannot be closed** ("Close or move
its collections first": the ⋯ menu's entry is disabled with that reason, and the close
preview refuses too); **a child under a closed parent cannot be reopened** (reopen or
move the parent first). Closing or unpublishing a parent takes its whole subtree out of
`##. Ongoing`; reopening publishes it again.

**A move recreates the subtree's links.** Moving a collection (or renaming a child)
takes its folder or link, with everything under it, out of the old place and creates it
at the new one, in one batch of the app's own links and folders; the cost grows with the
number of links, so past 50 the toast and the result say "(recreated N links)". A folder
holding something the app did not create stays where it is (with its "Needs attention"
status), as always.

### Groups

A collection's files can be arranged in **groups, nested to any depth**, plus an implicit
**Ungrouped** (shown only when the collection has groups). **+ Group** (the toolbar's
"New group") adds one (a collection that has no groups yet but two or more files shows
"Group files: New group" above the list); each group's **⋯** menu
has Rename, a summary, New subgroup, Move up / Move down and **Remove group…**, and the
chevron folds it. Removing a group moves its files and subgroups to its parent; it never
removes a file or a membership. A file has at most one group per collection (it can still
be in several collections). Drag members between groups, or choose the group in the
panel on the right (the only way for a folder member, or one missing or in `##. To Delete`:
only live files drag).

In `##. Ongoing` **each group is a subfolder** of the collection's folder, nested as the
groups are, still made of links: `##. Ongoing/2026 House sale/Paperwork/Bank/…`. Ungrouped
files sit at the top of the collection's folder. Renaming a group renames its subfolder,
through the journal. The app removes a group subfolder only when it emptied it and it is
the app's own (the same rules as for the collection's folder). A collection whose only
member is one folder keeps the single-link form only while it has no groups.

### Member changes

Adding or removing a member applies **without a confirm dialog**: it touches only
app-owned links (and an emptied app folder), is journaled, and is reversed by the opposite
action. The UI shows the batch that ran. Renaming, closing, reopening and switching
publishing on or off show a preview first.

**Convert `##. Ongoing`** (`/ongoing`, offered on Today; `dam ongoing entries` lists the
same): one entry at a time, each its own batch with its own Undo. Every entry, and every
item listed inside a folder entry, has **Quick Look**, **Open** and **Show in Finder**
(folders: Show in Finder only). The form marks what it needs: a collection (a new name
**or** an existing one, by path) and, for a folder or a file, the archive folder
(required); until then **Preview** is disabled and says why. Entries the app already owns
are listed under **Already managed**, and the ones it cannot convert under **Can't be
converted**, each with its reason.

- a link to an archive folder becomes a collection named after the link; a link to a
  single file is **starred** by default (**Star it**), and **A collection** makes a
  one-file collection named after the file;
- a real folder (e.g. `Legal`) becomes a collection; you choose the archive folder its
  contents move to, and each top-level entry inside becomes a member (links inside become
  their targets);
- a real file: starred by default (it moves to the archive folder you choose); or choose a
  collection (new or existing) and the archive folder to move it to;
- **Skip** hides an entry for now (only until the page is reloaded; "Show skipped" brings
  it back); it stays untouched in `##. Ongoing` and is listed as not managed by the app.

The screen shows a **binding preview**: the exact moves, links and members. Apply sends
the preview's fingerprint; if anything changed since (a file arrived, a link moved), the
apply is refused with "changed since preview" and nothing moves, so you preview again.
Entries that cannot be converted (a symlink to something outside the archive, a missing
target, an empty folder) are refused with the reason. A real folder you convert (e.g. `Legal`) is removed
once its contents have moved out and it is empty, together with a genuine Finder
`.DS_Store` in it (the same narrow exception as above); the app's link or link folder
takes its place. Nothing is removed until the moves have succeeded. **Undo** per entry restores the previous state, including the removed folder (empty
folder, contents moved back), with one caveat: a
relative link comes back as an absolute one (the preview says so). Converting into a
**child collection** puts its entry inside its parent's folder (the folders above it are
created in the same batch when missing); when the parent was one direct link, that link
becomes the parent's folder in the same batch, and undo restores the link.

### Browse by collection

In Browse, each pane has a **Collection** menu button (it shows the chosen collection's
name; "All files" clears it; the open collections are listed as a tree, with ★ Ongoing and
! Important) and a **Folders / Files** toggle. With a filter, the folder view shows only the folders on the way to a member of
that collection, or of any collection below it, plus the member files themselves (inside a
member folder everything is shown, at any depth). The **Files** view lists every file below the current
folder, flat, with sortable Name, Folder, Date and Size columns, **capped at 500 rows**
("N more: narrow the folder or search" says how many there are); `##. Ongoing` and
`##. To Delete` are left out unless you are inside them. Rows select, drag, preview and
Quick Look as in the folder view. Both are kept in the URL per pane
(`?collection=&view=files`, or `lcol`/`lview`/`rcol`/`rview` with two panes). The API:
`GET /api/browse?path=&collection=` and
`GET /api/browse/files?path=&collection=&sort=&dir=&limit=` (at most 500).

### Export

On a collection: **Export** as **zip** (the member files, folder members expanded, in
subfolders mirroring the archive, plus `contents.txt`) or as one **PDF** (PDF members and
JPG/PNG images merged in order, with a contents page; other types are listed as "not
included"). The export is built in the data dir's cache (never in the archive), offered as
a browser download, and pruned after a day. Limits: more than 200 MB asks you to confirm;
a combined PDF takes at most 1 GiB of PDF/image content and 2000 pages (the rest is listed
as not included); a whole export may take at most 10 minutes; files that Drive has not
downloaded ("cloud-only") are skipped with "open it once in Finder" and listed. Names are
sanitized and deduplicated; nothing can escape the zip's folder.

### Reminders

What fires, from the open items of each tray, each **once per occasion** and never for done
items:

- `days_before: N`: from `reminders.hour` (default 08:00 local) on the day N days before
  the item's date, or later if the app was not running then;
- `overdue: true`: the day after the date;
- a tray's `nudge_after_days`: once, at most one nudge per item ever.

If several occasions are already past when an item is created (an overdue bill), only the
latest is sent; the earlier ones are recorded silently so you are not spammed. Editing an
item's date clears the reminders not yet sent and creates new occasions, so rules that
already fired for the old date can fire again for the new one. A reminder check runs hourly while
`dam serve` is up (first one a minute after the start), and from the LaunchAgent below.
A lock file in the data dir keeps two checks from running at once (the second says
"skipped").

```sh
cd backend
uv run dam remind --dry-run                      # list what is due, send and mark nothing
uv run dam remind --dry-run --now 2026-11-03T09:00   # ... as of another time
uv run dam remind                                # send what is due now
uv run dam remind --install                      # daily LaunchAgent (shows the plist, asks first)
uv run dam remind --uninstall                    # unload and remove it
uv run dam remind --set-email-password           # store the SMTP password in the Keychain
uv run dam remind --test-notification            # one "dam test notification" per channel
```

**Before installing the LaunchAgent**, run `dam remind --test-notification` once in
Terminal and allow notifications for Script Editor when macOS asks (the notification is
sent with `osascript`; until it is allowed, macOS drops it without an error). It sends one
harmless "dam test notification" through each enabled channel, prints the result per
channel and marks nothing; with `--dry-run` it only says what it would send.

`--install` writes `~/Library/LaunchAgents/…plist` (the only file the app writes outside
its data dir), which runs `dam remind` daily at `reminders.hour` and at login, and works
even when the archive is unavailable. Both the install and uninstall show the plist and ask
first (`--yes` skips the question).

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
macOS Keychain, never in a file; the login is refused without TLS. **What is sent: the
item's title, its tray name, its date and its amount, never document text.** Titles come
from file names (or what you typed), so avoid putting secrets in them. A failed channel is logged and
shown on Today; if every channel failed, the reminder is retried at the next check (hourly
while `dam serve` runs), but if one channel delivered it counts as sent. There is no
retry loop.

### Notes and checklists

Optional on any tray item and on any collection (and a note can be added to a file while
filing it): a plain-text note and a checklist. They live in the database only; the
documents are never modified. A filing note goes on the tray item when you chose a tray,
else on the file, and never overwrites an existing note. Notes and checklists you edit
yourself are not removed by undoing a filing; ones the filing created are.

A checklist row is edited by clicking its text (Enter or leaving the field saves, Esc
cancels). Drag a row by its grip to reorder, or press Option-Up / Option-Down on a focused
row; the delete button shows on hover or focus.

### Check once on your real Drive

These depend on how Google Drive for desktop behaves and cannot be tested against a fake
archive:

1. **Ongoing ownership.** The app recognizes its own links and folders by inode, assuming
   they keep it under Drive for desktop. Use a throwaway document and a new test
   collection: file the document into it, wait for Drive to finish syncing, then run
   `dam ongoing sync --dry-run`; it should show no operations. If it plans changes or the
   collection shows "Needs attention", Drive changed the inode. (A changed creation time
   with the same inode and link target is not a problem: Drive does that, and the app
   accepts the entry as its own and updates the stored time.) An entry with the same name
   and the same link target but a new inode is left alone: the sync reports
   "… looks different from before (Google Drive may have re-created it), so it was left
   as it is" and neither
   removes it nor publishes a `_2` beside it, and that collection is not synced until
   this is resolved. If you see this message, please report it (with the output of
   `dam ongoing sync --dry-run`): it means Drive does not keep inodes and ownership needs
   another way. An entry whose content differs is still treated as yours, not the app's.
2. **Undo after Drive touches a file** (from Phase 1): with a throwaway document, file
   it, let Drive sync, then undo it from Activity; it should still be accepted (same
   Drive ID, type and size).
3. **Group subfolders.** After converting an entry or grouping a collection's files, check
   that the group subfolders in `##. Ongoing/<collection>/` sync as expected in Finder
   and on drive.google.com, and that `dam ongoing sync --dry-run` then shows no operations.
4. **The reminders helper after install.** `dam remind --install` loads the LaunchAgent
   `nl.dam.remind` with RunAtLoad, which runs `dam remind` **immediately** on your real
   data: due reminders are sent and marked as sent. Run `dam remind --dry-run` first to
   see what would go out. After installing, check `launchctl print
   gui/$(id -u)/nl.dam.remind`, and that a due item produces a notification at the
   configured hour or at the next login.

## Stars, Important and suggestions

### ★ Ongoing and ! Important

Two marks for files you need often, without making a collection:

- **★ Ongoing** (star) is for everyday quick-access files, such as `2026_Plan.xlsx`.
- **! Important** is for documents that must always be easy to find: passports, deeds.

Mark or unmark with one click wherever a file is shown: the inbox review card, Browse,
Quick Look, the viewer window, collection pages, tray items and Today. **Marking never
moves or renames a file.** The ★ and ! icons follow the file into every list.

Each mark is a built-in collection that always exists and cannot be renamed, closed or
deleted. Today has a **Starred** card (Open and Quick Look for each file), and the sidebar
has an **Important** row at the top of Collections. Important may have groups, nested, such as
`Houses › Hillside`; a file is in at most one group.

In Finder, ★ files appear as links directly in `##. Ongoing`, next to the collection
folders (a clash gets `_2`). ! files appear as links in `##. Important`, with the groups
as subfolders. Both folders are app-managed, with the rules of "Collections and
`##. Ongoing`" above: the app only ever removes its own links and empty folders there.

A file marked Important cannot be marked for deletion ("This file is marked Important;
unmark it first"), and neither can a folder holding one.

**Convert `##. Important`** (from the Important row, and from Today while there are
shortcuts the app does not manage yet) adopts what is there, one top-level entry at a
time, behind the binding preview and with Undo: each shortcut becomes a member in the
group that matches its subfolder, keeping its name; each real file is moved to an archive
folder you choose (mirroring its subfolder path) and becomes a member. A second shortcut
to the same file is left untouched, with the reason. **Convert `##. Ongoing`** has a
third choice, **Star it**.

A folder entry that keeps one such untouched shortcut stays on disk (the app never
removes a folder holding a user's file), so the group's own folder is published beside
it with a `_2` suffix: `Houses` (yours, with the shortcut) and `Houses_2` (the app's,
with the group's links). The preview says so. The suffix is stable: emptying `Houses`
later does not move the group's folder back; rename or remove `Houses` and the next sync
keeps `Houses_2` as it is.

CLI: `dam star PATH-OR-ID…`, `dam unstar …`, `dam starred`,
`dam important PATH-OR-ID… [--group "Houses/Hillside"]`, `dam unimportant …` and
`dam important --list`.

### Suggestions you pick one by one

When you file a file, or edit one that is already filed, the app suggests a name, a
folder and tags, and you decide **per item** which ones to take:

- Each suggestion that differs from what a field shows is a chip below it:
  **Suggested: <value>** with its source (`rule <id>`, `scan`, `similar files` or `AI`) and **Use**. Use
  changes that one field only. **Use all** takes every chip (the first suggestion of a
  field when there are several).
- A name that looks like broken text (`NÃ¤kymÃ¤` for `Näkymä`, UTF-8 read as
  Latin-1) is repaired before it is suggested; correct names are never changed.
- When no rule names a folder for an inbox file, the app looks for the folder the best
  matching already-filed files are in (the file's name and the start of its text against
  the full-text index, ignoring the `##.` folders). It suggests that folder, with the
  source `similar files`, when at least two of the top ten matches are in it and they are
  at least half of the matches. Rules always come first.
- Search results show a short excerpt with the match in `[brackets]`; line breaks and
  other control characters in it are shown as single spaces.
- Each suggested **tag** is its own chip: add the ones you want, skip the rest.
- Nothing is applied by itself. One exception keeps filing to one keystroke: an inbox
  file's empty fields start with the rules' suggestion, as before; the chips then show
  the alternatives (and the rules' value again once you edit a field away from it).
- The **batch card** offers each selected file's folder and every suggested tag.
- **Ask AI** answers with chips too (name, folder, each tag, the tray and each of its
  fields), through the "What will be sent" sheet. Its summary is offered as the note.
- What you then preview is exactly what the form shows, and what is filed is exactly
  what you previewed.

**A filed file's details** are edited in place (the Browse preview, the selected file on a
collection page, a tray item's file). The pencil beside the name renames it (the
extension stays), the folder icon beside the path moves it, and the tags under the preview
are chips: Enter or a comma adds one, **×** or Backspace in the empty field removes one,
and tags are written at once. While you type, the tags already in use that start with the
text are listed (most used first, at most eight): **↑/↓** choose, **Enter** adds the
chosen one, **Esc** closes the list. A new name or folder is shown as a plan first (a name already
taken gets `_2`), applied only when you confirm, and the toast has **Undo**. **Ask AI** puts
its suggestions as chips you take one by one (the sparkle button sits beside ★ and !,
on each screen's action row). ★ and ! are in the preview's toolbar. Files in
`##. Ongoing` and `##. To Delete`, folders and links cannot be edited here.

## AI (optional)

The archive works without AI. With an Anthropic API key, the app can suggest how to file
an inbox document, summarise a document or a collection, and answer questions about the
archive. Rules and scan detection always run first; AI is only ever used when you click.
The design is in `docs/superpowers/specs/2026-10-21-phase3-ai-design.md` (§2 is binding).

### Turning it on

```sh
dam ai --set-key       # prompts for the key (not echoed) and stores it in the Keychain
dam ai --status        # on/off, key present, this month's spend and the cap
dam ai --log           # the call log, newest first (--limit N)
dam ai --off           # switch AI off (the key stays); dam ai --on turns it back on
dam ai --clear-key     # remove the key from the Keychain
```

The key lives in the macOS Keychain (service `dam-anthropic`, account `api-key`), never
in a file, the log or the API. Without a key the AI buttons are hidden and the app shows
a "Turn on AI" hint with the command to run. The running app asks the Keychain at most
once a minute, so a key added or removed with `dam ai` shows up there within a minute
or two (`dam ai --status` always asks it afresh).

**The on/off switch** is `dam ai --off` / `--on`, or **Activity → AI → Use AI** in the
app. Either one writes `<data dir>/ai-state.json` (never `settings.yaml`) and reads it
back to check it stuck. While it is off, the AI buttons and any AI proposal on screen
are hidden and every AI call (prepare and run) is refused. A missing file means on; a file that cannot be read or is
not valid means **off** (it fails closed): a warning is logged, `dam ai --status` and
Activity → AI say why, and switching AI on again rewrites the file. `ai.enabled: false`
in `settings.yaml` switches AI off too.

### Where it is used

- **Inbox: Ask AI** on the review card (and on Today, for inbox files the rules could not
  guess), and on a filed file's details. On the review card and there the answer
  never fills the form: each value it suggests becomes a chip below its field, tagged
  **AI** (see "Suggestions you pick one by one"), and you take the ones you want. You still file with **File it** (preview, confirm, Undo).
- **Summaries**: the summary box of a bill or item (the item's first file; a selector
  picks another when it has several, and an item with no file has no AI button) and of
  the selected file in Browse. **Summarize with AI** shows the answer as a proposal with
  **Use this summary** or **Discard**; nothing is saved until Use. A summary you wrote is
  shown first while it is current, and is never replaced without asking ("Replace your
  summary with the AI one? Your text is not kept."). **Edit** saves your own text. When
  the file changes, the summary is marked "outdated (the file changed)" with
  **Summarize again**.
- **Collections**: **Summarize with AI** on the collection's summary proposes a summary
  for the collection and one for each group, each with **Use** or **Discard**. Use asks
  first when it would overwrite a summary that is already there. Members that are not
  sent (excluded folders) are listed in the "What will be sent" sheet.
- **Ask** (sidebar, under Archive): a question box. Retrieval is plain code (the search
  index, no tokens): the best 8 snippets from allowed files, shown in the sheet with the
  question before anything goes out. If nothing matches, the sheet says "Nothing in the
  archive matches" and nothing can be sent (it costs nothing). The answer has numbered
  citations; click one to open that file in Quick Look. **Save to notes…** under an answer
  lists its sources with a checkbox each (all ticked to begin with: the answer was drawn
  from all of them); confirming appends the date, the question, the answer and the cited
  sources to each ticked file's note, below any note it has (`POST
  /api/notes/{kind}/{target}/append`, one atomic write; a note over 10,000 characters
  refuses it and stays as it was), and a toast says where it went. Answers are kept for this session
  only (not saved), apart from the call log.

### What is sent, and what never is

- **Nothing is sent without a click.** Every AI action first shows a **"What will be
  sent"** sheet with the exact text, the model, the task, the worst-case cost and this
  month's spend; the call goes out only when you click **Send**. There are no background
  or automatic calls. Under the hood this is a two-step API, `prepare` then `run` with a
  per-process token: `run` rebuilds the payload and refuses if anything changed since the
  preview.
- **Extracted text only**, never the file itself: at most 12 000 characters per
  document, 1 500 per question snippet (8 snippets), and 800 per collection member (at
  most 40 members).
- **Excluded folders** (`ai.exclude_folders`, default `50. Medical`, `70. Work`,
  `90. Other People`) are never sent, in any task, with no override; case and Unicode
  normalisation (NFC) variants of the names are caught. A file at or under one cannot be
  sent (the sheet says why); Ask skips such files; a collection skips such members. An
  inbox file whose rules would file it under an excluded folder is blocked as well. The
  folder list sent for filing suggestions leaves out everything below an excluded top
  folder and keeps only its name.
- **AI never acts.** Answers are validated against the task's schema; anything invalid
  is an error and nothing is applied. Suggestions only fill the existing forms, and
  summaries are saved only when you click Use. Document text is sent inside a delimited
  block and treated as data; answers are shown as plain text.

### Budget, costs and the log

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
- **One call at a time.** Calls are sent one after the other, each one checked against
  the budget right before it goes out. How long a call may take depends on its size: 60 s
  plus 1 s per 500 estimated input tokens and 1 s per 50 output tokens allowed, rounded
  up to 10 s and capped at 3 minutes (a small question gets about 80 s, a summary of 40
  files about 2 min 20 s). The "What will be sent" sheet states the limit ("Gives up
  after") and, once you send, shows "Waiting for Claude" with the seconds counting up. A
  call that never answers is not retried; the message says Claude didn't answer within
  the limit, that nothing was changed, and that the estimate is counted this month (it
  may have been billed, and the real usage is unknown), so the figure stays on the safe
  side. Closing the sheet meanwhile does not stop the call; **Ask AI** shows its answer
  again for free.
- **The log**: every call is logged with its time, task, model, the files involved, the
  input and output tokens, the real cost, the outcome and its duration. See it in
  **Activity → AI** (with this month's total against the budget at the top) or with
  `dam ai --log`.
- **Cache**: a result for the same file text, task, model and prompt version is reused
  for free ("from earlier"; **Ask again** sends anew).

Models, prices, the EUR rate, the budget, the language (`ai.language`, default `en`),
the thinking effort (`ai.effort`, default `low`), the output limits and the excluded
folders are the `ai:` block in `settings.yaml` (see the commented defaults).

### Demos: `DAM_AI_FAKE=1`

For demos and tests only, `DAM_AI_FAKE=1` replaces the provider with a deterministic
fake. It makes **no network calls**, counts as having a key, and gives demo answers read
from the payload (a filing suggestion, document and collection summaries, an answer that
cites the first sources). Its calls are logged with outcome `fake`, the model as
`fake:<model>`, at no cost, and never cached.

```sh
cd backend && uv run python -m dam.demo /tmp/dam-demo   # a small fake archive
DAM_AI_FAKE=1 uv run dam --data-dir /tmp/dam-demo/data serve --port 8777 --no-open
```

## Config and rules

All in the data dir under `config/`:

- `settings.yaml`: `archive_root` (not set in the seeded file: `dam init` or the first-run
  screen writes it; to change it later run `dam init` again, which keeps a
  `settings.yaml.bak-<time>` copy, or edit the line by hand), `special_folders` (inbox, ongoing, important,
  quarantine), `protected_paths`, `indexer_reads_per_minute`, `ops_throttle_ms`,
  `server_port`, `ocr_languages`, `reminders` (`hour`, `mac`, `email`), `ai` (see AI
  above).
- `trays/*.yaml`: one tray per file (see Trays above).
- `rules/*.yaml`: filing rules, loaded in name order. A bad file is reported and
  skipped; rule ids must be unique across files. For folder and name the first matching
  rule wins; tags from all matching rules are merged. The seeded `00-examples.yaml`
  documents the format. In `when`, all *given* conditions must match; for
  `text_contains`, one matching term is enough. `{doc_date}` and `{year}` need a
  detected date; without one, the rule's template is not applied.

To add a rule, create e.g. `config/rules/10-mine.yaml` (a YAML list):

```yaml
- id: benefits-letters
  when:                                  # all given conditions must match
    text_contains: ["acme benefits", "eläkekassa"]   # case/diacritics-insensitive
    filename_matches: "(?i)scan"         # optional regex on the file name
    folder_is: "##. Organize"            # optional
  then:
    folder: "13. Taxes/{year}"           # templates: {doc_date:%Y%m%d}, {year}, {stem}
    name: "{doc_date:%Y%m%d}_Benefits"      # stem only; the extension is added
    tags: ["benefits"]
    # tray: to-pay                       # optional: the tray it is guessed to belong in
    # payee: "Acme Benefits"        # optional: prefills the To pay tray's payee
```

`then.tray` and `then.payee` come from the same rule as the folder (the first matching
rule with a folder; if no rule gives a folder, the first matching rule that has either).
Without a `then.tray`, an inbox document whose scan found a due date and an amount, plus
an IBAN or a reference, is guessed **To pay**. Guesses are plain code, no AI. Today lists
guessed documents that are not yet in that tray under "Found in the inbox".

The top-level folder (`13. Taxes` here) must already exist; dam never creates top-level
folders on its own (the quarantine folder is the only exception). Make it yourself with
**New folder** in Browse, or start from a layout ("Starting from scratch").

## Google Drive notes

- The archive is in streaming mode: most files are cloud-only. Indexing reads every
  file, so Drive downloads the **whole archive** into its local cache over time: plan
  for free disk space about the size of the archive. The indexer is throttled
  (`indexer_reads_per_minute`, default 30) and incremental, so the first full index is
  slow by design.
- Scanning only reads metadata (and Drive IDs from the `com.google.drivefs.item-id#S`
  xattr), so moves and renames made in Finder or on the web are followed by Drive ID.
- The database, caches, logs and config are never inside Drive.

## Known limitations

- Vision OCR (macOS) has no Finnish; OCR falls back to en-US, so scanned Finnish text is
  recognized poorly (text-layer PDFs are unaffected). Tesseract, used on Windows and
  Linux, does read Finnish.
- Previews show no page count.
- No phone or tablet layout: narrow windows stack the columns, but the app is made for a
  Mac window. The barcode on screen covers paying from the phone.
- Reminders cannot open the file from a notification; clicking one does nothing.
- Phase 4 (cleanup) is not built yet.

## Development

```sh
cd backend && uv run pytest -q -W error && uv run ruff check .
cd frontend && npm test -- --run
cd frontend && npm run gen:api     # regenerate src/api/schema.d.ts after API changes
```

Tests use temporary fake archives and never touch the real one. For UI work, run the
backend and the Vite dev server side by side:

```sh
cd backend && DAM_DEV_ORIGIN=http://localhost:5173 uv run dam serve --no-open
cd frontend && npm run dev         # http://localhost:5173
```

`DAM_DEV_ORIGIN` lets the API accept the dev server's `Origin`. Details in
`frontend/README.md`.
