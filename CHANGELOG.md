# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Activity: search, filters and paging (server-side), with the filter bar kept in the URL.
- An Index sheet (opened from the status line) with totals per state and the files that
  could not be read; the status line now says "searchable", "waiting" and "not readable".
- Text readers for `.xlsx`/`.xlsm`/`.xls`, `.pptx`, `.doc`/`.dot`/`.dotx`/`.docm`/`.odt`/
  `.html`/`.webarchive` (macOS only, through `textutil`) and Pages, Numbers and Keynote
  files (their preview, with OCR where an engine is available). Migration 0025 queues
  files of these types that were marked unsupported once more. New dependencies:
  `openpyxl`, `xlrd`, `python-pptx`.
- A filed file's name, folder and tags are edited in place (rename, move, tag chips and
  Ask AI chips), replacing the Edit details dialog.
- Browse: select all, and batch star and Important.
- A search scope bar, a tray menu ("Put in tray"), and a collection browser.
- New folder in the folder picker.
- Folder members expand in a collection.
- Convert Ongoing to inbox; Important folders of shortcuts need no archive folder; Undo on
  converted cards.
- Resizable list/detail split on Trays, Inbox and collections.
- New folder makes the folder on disk at once, listed in Browse straight away, as its own
  change in Activity; undo removes it while it is empty. In the folder picker too.
- Browse: a New folder button in the toolbar (⇧⌘N, Ctrl+Shift+N elsewhere) with a name row
  at the top of the list.
- Browse: a "Collection" menu (a tree of the open collections, with ★ Ongoing and
  ! Important) replaces the filter icon; a folder member brings its contents at any depth.

### Fixed

- Links and folders the app made in Google Drive are no longer flagged "looks different"
  after Drive re-writes them.

### Changed

- A plan with a single step is shown as a sentence, not a numbered list.
- Text that is cut off shows in full on hover; folder paths are shortened in the middle,
  keeping the last folder.

## [0.1.0] - Unreleased

First public release.

### Added

- Inbox filing: dam suggests a name, folder and tags for each new file in
  `##. Organize`; you preview the change, confirm, and can undo it.
- Browse and full-text search over file names, text and OCR (Apple Vision on macOS,
  optional Tesseract on Windows and Linux).
- Trays, including To pay with the Finnish bank barcode read from bills, plus Today and
  reminders (desktop and e-mail).
- Collections with groups and child collections, kept in a managed `##. Ongoing` folder;
  export of a collection.
- Activity page that journals every change, with undo of a whole batch.
- Quick Look previews, drag and drop, keyboard shortcuts, and a two-pane Browse.
- Optional AI (your own Anthropic key, in the OS keychain): suggestions, summaries and
  questions, only on click, after a preview of exactly what is sent, with a monthly
  budget and a call log.
- First-run setup: `dam init` or a welcome screen finds your cloud-drive folders
  (Google Drive, OneDrive, Dropbox, iCloud Drive, Nextcloud and others) and asks before
  saving anything.
- Several archives: add a test or demo archive next to your real one and switch between
  them (menu in the sidebar, `dam archives ...`, `dam --archive NAME ...`). Each has its
  own settings, index, logs and reminders; forgetting one never deletes a folder.
- Cross-platform install for macOS, Windows and Linux, with CI on all three.
- Safety by design: never deletes your files, every change previewed and undoable,
  local-only server on `127.0.0.1`.
- Optional `dam[msg]` extra for Outlook `.msg` e-mails (GPL-3.0 dependency, not part of
  the core).
- MIT licence.
