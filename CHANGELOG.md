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

- Tag suggestions: the tag field lists the tags already in use that start with what you
  type (most used first), with arrow keys, Enter and Esc. New `GET /api/tags`.
- A collection's selected file shows a multi-page PDF one page at a time, with Previous
  and Next page; a collection without groups but with two or more files hints at "New
  group".
- A new default tray, **Follow up**, for things you wait on from others (a delivery, a
  reply, a refund): an optional check date, who you wait on, and a plain "Done" to finish. Its
  items without a date have no reminders. A default tray file added in a later version is
  copied into an existing install once; a tray file you deleted stays deleted.
- Ask: **Save to notes…** under an answer adds the question, answer, date and sources to
  the note of the source files you tick, below any note they have. New
  `POST /api/notes/{kind}/{target}/append`.
- Tray items: "Add file" in the list column puts a file you search for in the tray as a
  new item; "Add another file…" under an item's title attaches a file to that item.
- Activity: creating a folder is a kind of change of its own, "New folders".

- A file lives in one tray: putting a file that has an open item in another tray into a
  tray moves that item (history says "Moved from … to …", Undo moves it back) instead of
  making a second one. The item has a **Move to tray** menu. New
  `POST /api/items/quick` fields `moved` and `moved_from`, `POST /api/items/{id}/move` and
  `/undo-move`.
- **Remove from tray** on an item (and `⌫` on the selected row) deletes it, open or done,
  after a confirm; the files stay where they are. New `POST /api/items/{id}/remove`.
- Checklist rows: click the text to edit, drag by the grip or press Option-Up/Down to
  reorder, delete button on hover; the Edit and arrow buttons are gone.
- A **Starred** row under Important in the sidebar, with its count, opens the ★ Ongoing
  collection page (`/starred`). Inside the Starred card and page the ★ is no longer
  repeated on every row (the ! stays), and likewise the ! inside the Important page.
- Today: the cards' ⋯ menus are gone. Reorder by dragging or with ⌥↑ / ⌥↓ on a card's
  header (announced to screen readers); **Reset layout** is a button under the date.
- Today's tray rows (all of them, also items due later) have a round checkbox before the
  title that marks the item done at once with the done fields' defaults, with Undo. A
  done field that is required and has no default opens its small form.
- A dated tray item shows its date field, urgency tag and Mark done on one row; the
  separate read-only date line is gone.
- Activity cards are collapsible (collapsed by default), with Expand all / Collapse all
  remembered per browser; a search shows them open.

### Fixed

- After adding a group to a collection, **New group** could not add another straight
  away: the click only saved the previous group's name. It now adds the next group.
- A tray date that is optional no longer makes Today call an item without one "undated".
- The "What will be sent" sheet now says what closing it does while the answer is on its
  way: it is still saved, and pressing the same button again shows it at no cost.
- Links and folders the app made in Google Drive are no longer flagged "looks different"
  after Drive re-writes them.
- Disabled buttons now say why on hover: Preview and File it in the Inbox, Done on a tray
  item, Add file on Trays, Preview on Convert Important, Forget… for your only archive and
  Undo in Activity. Before, the reason never showed.
- Esc while editing a group's summary cancels the edit; it used to save it.
- Taking a file off a tray item, and Remove from a tray in the Put in tray menu, now offer
  Undo in their message.
- On Windows and Linux the app no longer says "Finder": Show in Explorer, or Show in file
  manager.

### Changed

- Buttons follow one order and wording across the app: Cancel comes before Save in the
  detected-field editor and in Save to notes (which Esc now closes); "Don't offer these"
  stands at the left of the tray settings sheet; the Barcode and Export sheets close with
  Done; removing a star is "Remove the star" everywhere and unmarking is "Unmark
  Important"; tooltips show shortcuts the same way (Quick Look Space, ⇧⌘M); the Inbox and
  Quick Look say "files", not "documents"; the folder picker calls the deletion folder To
  Delete; the preview toggle on the review card has its own icon instead of the Quick Look
  eye.
- The item panel's title, fields and the done buttons ("Mark done", "Mark paid and file…") sit on one row that wraps only when the panel is narrow, in every tray; the title takes the spare width and a date's "in 3 days" tag follows the date.
- No more "needs a …" text for an empty required field on tray items (Today cards, the
  item's fields, the filing form). The tray list rows no longer show a file count.
- More space between the tag box and the Collections line in the file panel.
- Inbox: the tags field (review card and multi-file card) is the chip field with tag
  suggestions used on a filed file's details; Ask AI is the sparkle icon button; Preview,
  File it and File N have tooltips saying what they do.
- Tray items: the header shows the Quick Look eye button (tooltip "Quick Look Space")
  instead of a text link and key hint, and the "needs a due date" chip is gone from the
  tray list and the item header. Quick Look buttons on Today's Starred card and on
  Convert Ongoing also name Space.
- Ask AI is an icon button on each screen's action row (Browse, a collection's selected
  file, a tray item) instead of a text button beside the file name.
- A collection's selected file: Quick Look is an icon button; the built-in ★ Ongoing and
  ! Important no longer repeat the ★ / ! toggle as "Unstar" / "Remove from Important";
  the member list scrolls in its own box.
- Tray items: "Done" reads "Mark done" and "Done & file it…" reads "Done and file…"
  (shown only while a file of the item is in the inbox), both with tooltips; the Note
  button is gone; the selected file's buttons (Ask AI, Move to To Delete, "Take this file
  off the item") share the action row; one-file items no longer repeat the path above the
  file; a dated item (To action) leads with its title and date.
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
