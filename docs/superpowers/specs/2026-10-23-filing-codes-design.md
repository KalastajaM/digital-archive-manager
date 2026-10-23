# Filing codes: design

Status: Steps 1 and 2 built (2026-10-23); step 3 (pen codes) optional, not built.

## Intent

When the owner scans paper, each sheet's fate is usually already decided in their head:
it needs action, it is a bill to pay, or it is already handled and only needs to go to
its folder. Today that decision is made a second time, document by document, in the
Inbox. This feature lets the owner attach that decision to the document before or while
it enters the inbox, and confirm a whole batch of such documents with one click.

A decision is expressed as a **filing code** from the owner's own table (for example `P`
for "To pay", `V3` for "car insurance folder"). A file can get its code three ways:

- **Inbox folders**: the file is saved or dropped into a subfolder of the inbox that
  belongs to a code, for example `##. Organize/To pay/`.
- **Pen codes**: the code is hand-written on page 1 as `*P*` before scanning.
- **QR stickers**: a small printed sticker carrying the code is stuck on page 1.

The aim is an easy, close to foolproof way to semi-automate archiving. "Foolproof" here
means a misread costs no more than a normal Inbox visit: nothing is filed without the
owner seeing it first, and a code that is not read cleanly falls back to today's flow.

## Build steps

One design, built in three steps. Each step is usable on its own.

1. **Code table, the File N marked batch, the "file as suggested" code, and inbox
   folders.** No OCR; works on every platform; proves the whole confirm flow.
2. **QR stickers** (printing sticker sheets, and reading them on every platform).
3. **Pen codes** (Apple Vision, macOS only). Optional: decided after QR stickers have been
   built and tested in daily use.

Parked until all three are done: Tesseract-based pen codes for Windows and Linux.

## Goals

- A coded file arrives in the Inbox with the code's values filled in.
- A code can fill any subset of the filing form: tray, folder, name pattern, tags,
  collections. One code can do several things at once (for example "To pay" plus the
  electricity folder plus a tag). This also covers "stored actions" (`A1` meaning a saved
  set of steps), because every step is a pre-filled form value.
- One review screen, **File N marked**, lists every coded file with what will happen, and
  one confirm files them all as a single journaled, undoable batch.
- Codes are the owner's own, configured in Settings, with a warning when two codes are
  easy to confuse on paper.

## Non-goals (this design)

- Filing without a confirm. Every change is still previewed (CONTRIBUTING safety rules).
  This holds for inbox folders too: a file in `##. Organize/To pay/` is pre-assigned, not
  filed.
- Pen codes on Windows and Linux (see Build steps).
- Reading codes from a PDF's existing text layer (see Evidence).
- Codes on pages after page 1, for speed. The guide says codes go on page 1.
- A general step engine (actions that run on their own, conditions, chains).

## Anti-goals

- A stray symbol or QR code in a printed document turning into a filing suggestion. Only
  codes in the owner's table can ever match.
- A file moving without the owner having seen where it goes.
- Code text steering the other suggestions.

## Step 1: codes, the batch, inbox folders

### The code table (Settings)

A new Settings section, **Filing codes**, holds the owner's codes. Each code has:

- `code`: 1 to 4 letters or digits, unique, stored upper case;
- `label`: a short description shown in chips, in the review, on stickers ("Electricity
  bills");
- any of: `tray` (a tray id), `folder` (a folder template, as a rule's `then.folder`),
  `name` (a name template, as a rule's `then.name`), `tags`, `collections`;
- `as_suggested` (boolean): see below;
- `inbox_folder` (optional): the name of the code's subfolder in the inbox.

Stored as `config/filing_codes.yaml` in the data folder, next to the trays and rules, so
it backs up and can be edited by hand like the other config. Template validation reuses
`check_template` in `rules/engine.py`, whose placeholders are `doc_date`, `year` and
`stem`.

Seeded codes, all editable, one for every shipped tray plus one for file as suggested:
`A` (tray To action, inbox folder "To action"), `P` (tray To pay, inbox folder "To pay"),
`R` (tray To read, inbox folder "To read"), `F` (tray Follow up, inbox folder "Follow-up")
and `D` (file as suggested, inbox folder "File as suggested"). Seeded codes and folder names are not tied to any language's words; the
owner renames them as they like. Seeding follows the trays' pattern (`seeded_trays`): a seeded code the owner
deleted stays deleted.

A code that points at a tray, collection or template that is not valid any more is shown
with an error in Settings and is not matched, so it never produces a suggestion
(designer's call).

**Confusable codes.** When saving, dam warns (does not block) if the new code is one
confusable step from an existing one, using these groups: `0 O Ø D Q`, `1 I L 7`, `5 S`,
`2 Z`, `8 B`, `U V`, `6 G`. Example: adding `O` when `0` exists. The warning names the
existing code. (This matters for pen codes; QR and folders cannot be misread.)

### "File as suggested"

A code with `as_suggested: true` means "already handled: file it where dam suggests, no
tray". It sets no fields itself; the row in the batch uses the existing suggestions
(rules, similar files, the name pattern) as they are. If those suggestions have no folder,
the row is flagged **needs input**. It can be combined with tags or collections on the
same code.

### Codes as a suggestion source

A matched code is the strongest suggestion source, `code:<CODE>`, above rules and similar
files. For each field the code sets, the form starts with the code's value and the chip
reads "Suggested: <value>, from code `P`" (for an inbox folder: "from folder To pay").
Fields the code does not set fall back to the existing suggestions exactly as today. A To
pay code still gets payee, amount, due date and IBAN from the scan and the bank barcode.

Several codes on one file (say a pen code and an inbox folder): list fields (tags,
collections) are united; scalar fields (tray, folder, name) conflict when their rendered
values differ. A file-as-suggested code counts as "no tray", so it conflicts with any
code that names a tray (D with P, A, R or F); the same code found twice, or a tray code
with a code that sets only a folder, is combined without a conflict. A conflict marks
the file **conflict**; the owner resolves it in the Inbox form, not in the review list
(designer's call). Every batch row shows all the codes found for its file.

This needs `Suggestion` (`rules/engine.py`) to carry collections and a tray source, and
the `InboxService._suggest` hook (where similar-file folders are added today) to apply
codes on top, so the suggestion API and its frontend types change.

### Inbox folders

Today the inbox is only the files directly in `##. Organize` (`in_inbox_path` in
`index/repo.py`), and the Inbox list, counts and Today rely on that. With this feature,
files directly inside a subfolder whose name is a code's `inbox_folder` also count as
inbox files and carry that code. Other subfolders of the inbox (the owner's own) keep
their current meaning; deeper levels are not included.

- Folder names are matched like other special folder names (NFC, case-insensitive on
  case-insensitive file systems; follow `core/foldernames.py`).
- dam does not create these folders by itself. Settings offers **Create inbox folders**,
  which creates the missing ones through the operation layer with a preview, a journal
  entry and undo, like any other change to the archive.
- Renaming or clearing a code's `inbox_folder` does not rename the folder on disk; Settings
  shows folders that no longer belong to a code, and the files in them are plain archive
  files again until the owner moves them.
- Filing a file from an inbox folder moves it out like any inbox filing; the empty folder
  stays (it is the owner's drop target).
- This changes a core rule, so it needs its own tests across the Inbox list, counts,
  Today, the watcher and undo.

### File N marked (the batch)

- The Inbox header and Today's "Found in the inbox" strip show **File N marked** when at
  least one inbox file has a matched code. While new files are still waiting for a code
  pass (QR, pen), the button shows "Reading filing codes…" so the count is not
  mistaken for final.
- It opens a review list, one row per coded file: thumbnail, the code and how it was found
  (folder, pen, QR; for pen the raw read when it differs), and the resulting name, folder,
  tray, tags and collections. For a tray code the row also shows the tray fields that will
  be stored (for To pay: payee, amount, due date), because what is filed must be what was
  shown.
- Before the list shows, each row is checked with the existing dry run. Three flags, each
  unticked by default: **unclear** (a pen read that matched only after a confusable
  substitution), **conflict** (codes disagree), **needs input** (the filing would be
  refused, for example To pay with no due date found, or "file as suggested" with no
  folder; the row says what is missing). The owner fixes a flagged row in the Inbox form.
  Unflagged rows are ticked.
- **File** files the ticked rows through the existing `InboxService.file_it` (a list of
  `FileRequest`s), so it is one journaled batch with one undo.
- Unticked rows stay in the Inbox with their suggestions pre-filled.

## Step 2: QR stickers

### Reading

The barcode pass already renders the first pages of inbox files and reads them with
zxing-cpp (core dependency, all platforms), today only for Code 128 bank barcodes. It also
reads QR codes on page 1. A QR code counts only when its text is `dam:<CODE>` and `<CODE>`
is in the table; any other QR code (on invoices, letters) is ignored. QR reads are never
unclear. Results are stored with the pen reads or alongside them (builder's call).

### Printing sticker sheets

Settings → Filing codes has **Print stickers**: choose codes and how many of each, choose
a sheet layout, and dam produces a printable HTML page (opened in the browser and printed
from there; no PDF library). QR images are generated with zxing-cpp
(`zxingcpp.create_barcode(..., BarcodeFormat.QRCode).to_svg()`), so no new dependency.
Each sticker holds the QR code with the code in bold and its label in small print beside
it. Labels are capped at 24 characters and wrap or shrink to fit the sticker. The QR text
holds only `dam:<CODE>`, so stickers stay valid when the code's meaning changes. The
`dam:` prefix leaves room for richer sticker content later (a different form after the
prefix); this version ignores any form it does not know.

Sheet layouts:

- A short built-in list of common A4 label sheets, chosen by product number. The first
  candidate is Avery Zweckform L7651 (65 per sheet, 38.1 × 21.2 mm); others to be added
  only after checking the manufacturer's published dimensions.
- **Custom**: columns, rows, label width and height, top and left margin, horizontal and
  vertical gap, in mm. Saved, so it is entered once.
- **Plain paper**: a grid with cutting lines, for anyone without label sheets.
- **Start at label N**, to use up a half-used sheet.
- **Test print**: the same layout with label outlines only, to print on plain paper and
  hold against a label sheet. The page tells the owner to print at 100% (no "fit to
  page"), since browser and printer scaling is the usual cause of misaligned labels.

Print-and-scan trial (2026-10-23, laser print, Doxie 300 dpi black and white, sheets fed
crooked and one upside down): zxing-cpp read all 28 test codes, `dam:P` at 6, 8, 10, 12,
15 and 20 mm in every error-correction level (L, M, Q, H) and a 12 mm code with a quiet
zone of 0, 1, 2 and 4 modules, at both 300 and 200 dpi rendering. Stickers cut from plain
paper and taped onto a real form and a real bill were read too, next to the bill's own
Data Matrix and bank barcode (only QR codes in the `dam:` form count). Reading QR on a
rendered page took about 10 ms. Defaults from this: QR 12 mm or larger on stickers,
error correction M, a quiet zone of at least 1 module. When reading both QR and Code 128,
pass the formats as a tuple: the `|` operator is deprecated in zxing-cpp and the test
suite runs with `-W error`.

### Star and Important tick boxes

A sticker can carry two tick boxes, ★ (star) and **!** (important), so the owner marks a
single document Starred or Important with the pen. The QR text says the sticker has boxes
(`dam:1:<CODE>`, the version after the prefix naming the box layout); plain `dam:<CODE>`
stickers have none. The boxes sit at fixed positions in QR module units relative to the QR,
so the reader finds them from the QR's corner points on any rotation. No OCR is involved.

Blind trial (2026-10-23, blue ballpoint, Doxie 300 dpi black and white, crooked feeds, two
full sheets and two stickers on documents; the owner revealed the truth only after the
reading): 15 ticked and 249 empty boxes. The QR corner points alone place the boxes up to
about 0.75 module off, so the reader first aligns each box pair on its printed outline
(search within ±1.5 modules), then measures the share of dark pixels inside the box with a
15 % inset from the edge. Result: every ticked box measured at least 3.8 % ink, every empty
box at most 0.2 %. Thin ballpoint ticks give low fill, so thresholds are low: ticked at 1 %
or more, empty below 0.5 %, **unclear** in between (the batch flag). With these, the trial
classified all 264 boxes correctly. Box sizes 3.7, 5.0 and 6.2 mm all worked; the smallest
that the owner finds comfortable to tick decides the sticker layout.

## Step 3 (optional): pen codes

### Evidence (spike, 2026-10-23)

The owner hand-wrote test codes in blue ballpoint and scanned them in black and white on a
Doxie sheet-fed scanner (300 dpi PDF). Results:

| Written | Apple Vision read | Tesseract read |
|---|---|---|
| `*V3*` | `*V3*` | nothing usable |
| `*A1*`, `*L*`, `*I*` | exact | nothing usable |
| `*1*` | `* 1*` | nothing usable |
| `*Ø*` | `*Ø*` | nothing usable |
| `[V3]`, `//V3`, `=V3=` | exact or with a space | `[VAA`, `-V3-` |
| `*A*`, `*O*` | `*AX`, `* OX` (closing star read as X) | nothing usable |
| `*p*` | `*рж` (Cyrillic р and ж) | nothing usable |
| `*SØ*` | `*Ø5*` (S read as 5, order swapped) | nothing usable |
| `#V3#` | not found on the test sheet; exact on a real document | `HV3E` |

On a real printed form with codes written in the margins, Vision returned each code as its
own line, separate from the printed text.

Doxie PDFs carry their own OCR text layer, and dam uses a PDF's text layer as-is when it
has at least 20 characters per page (`extract/pdf.py`, `MIN_CHARS_PER_PAGE`). That layer
garbles codes (`*` codes came out as `¥00^`, `>0^`, `zw`; `[V3]` as `CV3J`), so code
reading needs its own Vision pass on the page image. Tesseract cannot read this
handwriting without preprocessing, hence macOS only. The spike script is not in the repo.

### The format

One or more letters or digits between two asterisks, in a blank area of page 1: `*P*`,
`*V3*`, `*A1*`. Position on the page does not matter and is not configured.

Matching:

- Only codes in the table match; unknown codes are ignored.
- Case-insensitive; spaces inside the mark are ignored (`* 1*` reads as `1`).
- A wrapper character read as `X`, `x`, `ж` or `Ж` counts as an asterisk (`*AX` reads as
  `A`).
- Lookalikes are normalised first: Cyrillic letters to the Latin letter they resemble
  (`р` to `p`), `Ø`/`ø` to `0`.
- A read that matches only after a confusable substitution (`*Ø5*` to `SØ` via 5/S)
  counts only when exactly one code is reachable, and is marked **unclear**.

### Reading

- A background pass modelled on the bank barcode pass in `index/content.py`
  (`read_barcodes`, its timeout and retry, `file_barcodes` keyed by `drive_id` and
  `sha256`) runs Apple Vision on page 1 of inbox files (PDF, JPG, PNG), whether or not the
  PDF has a text layer. It runs only when `ocr.engine() == "vision"`; elsewhere Settings
  and the Inbox show "Pen filing codes need Apple Vision, which is only on macOS".
- It stores the raw lines (text, confidence, box) in a new table, so matching reruns when
  the code table changes without reading the image again. Rows for other content
  (`sha256`) are ignored and the file is read again. Rows are kept after filing and only
  used while the file is in the inbox, so an undone filing returns with its code.
- The pass takes an injected reader `(image) -> list[(text, confidence, box)]` as the test
  seam, defaulting to a new Vision function that keeps boxes and confidence (the existing
  `_ocr_vision` joins text only and stays as it is).
- Indexed text is not rewritten (designer's call): the pass runs after content extraction,
  and a garbled code in a scanner's text layer cannot be found reliably anyway.
- Rendering and limits are the builder's call, starting from the barcode pass (300 dpi
  greyscale, its timeout and retry); sharing the rendered page 1 with that pass is
  preferred if the coupling stays small.

## Constraints

- Safety rules in CONTRIBUTING apply in full: only the operation layer writes to the
  archive (including creating inbox folders), everything previewed, journaled and
  undoable, `test_no_delete.py` untouched.
- No new dependencies: Vision through `ocrmac`, zxing-cpp for reading and writing QR.
- Tests use fake archives. Pen tests inject OCR lines; macOS-only tests may run real Vision
  on a generated image; QR tests can generate and read real codes on every platform.
- "Marks" already means Starred and Important in dam (`api/marks.py`). This feature is
  called **filing codes** everywhere (UI, code, config).
- Each step is a user-visible change: a CHANGELOG entry under Unreleased, a "Filing codes"
  section in the guide (extended per step), and a regenerated
  `frontend/src/api/schema.d.ts` after API changes.

## Left to the builder

API shapes and routes, the new tables' columns, the review screen's layout (follow the
existing Inbox and tray styles), where the Settings section sits, files per pass run, the
exact normalisation tables beyond those above, and the sticker page's typography.

## Later

- Tesseract with margin cropping and preprocessing, for pen codes on Windows and Linux, to
  be tested for reliability and speed after the three steps are done.
