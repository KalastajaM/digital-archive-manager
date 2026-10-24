# Zone identification on page 1

Status: design, 2026-10-24. Builds on `2026-10-23-learned-filing-rules-design.md` (the
draft, the replay, the track record) and reuses the barcode pass's way of reading page 1
in the background.

## Why

A rule matches when any one of its words is anywhere in the document's text (`_matches`
in `backend/src/dam/rules/engine.py`). That is too broad and too blind at once:

- "pohjola" also matches a bank statement or a receipt that only mentions a payment to
  Pohjola, so a sender rule catches documents that are not from the sender.
- Nothing in a rule says who a letter is for. The shipped `medical-visits` example asks
  the owner to write one rule per person by hand, which doubles the rules and still
  matches a name anywhere in the text (a doctor's letter about Tiina that mentions
  Michiel as the contact).

Most post comes from the same senders again and again, and a letter from one sender has
its letterhead in the same place every time. Finnish business letters follow the SFS 2487
layout, so the addressee is in the same window-envelope area on nearly every letter.
Where a word sits on page 1 says far more than whether it is in the text at all.

## Goals

- Keep the position of the text on page 1 of every PDF and image, read once per content,
  at no extra OCR cost for new documents.
- Let the owner draw a box on page 1 in the preview and make a rule from it: "this text
  in this area means this sender".
- Detect who a document is for from one archive-wide address zone and a short list of
  people, and let a rule file per person with `{person}` in its folder or name.
- Let the owner say by hand who a document is from and who it is for, for one document
  or many, without drawing anything.
- Prove zone rules with the existing replay, exactly, without reading every filed
  document first.

## Non-goals

- Matching logos as images (no text in them). Text in or next to the letterhead covers
  most senders; image matching is a later design if real examples need it.
- Pages after page 1.
- Deskewing or rotating scans. A small tolerance around each box absorbs the usual shift
  and skew of a scanner; a page scanned sideways does not match, and the replay shows it.
- Filing without a confirm (CONTRIBUTING safety rules). Zone rules and detected people
  only fill in the Inbox form, as rules do today.
- AI. Everything here is plain code over the index.

## Anti-goals (a failure even if it works)

- A replay that looks better proven than it is. A document whose page 1 has not been read
  yet is counted as "not checked", never as a non-match.
- A person guessed from a name anywhere in the text. A person comes only from the
  address zone or from the owner.
- Slowing down the Inbox. Reading page 1 of a new inbox document happens with its
  normal indexing; the full backfill of old documents runs only when nothing else waits.

## Constraints

- Archive files are only read. Positions, detected people and the owner's assignments are
  index data in `dam.sqlite`; the operation layer and the journal are not involved, as
  for rules (`2026-10-23-learned-filing-rules-design.md`, "Constraints").
- A file's `drive_id` is kept in an extended attribute (`index/driveid.py`) and survives
  moves and renames, so per-file data is keyed by it. Data read from the content is also
  keyed by `sha256`, as `file_barcodes` and `file_qr_codes` are: a row for other content
  is ignored and read again.
- Rules stay in `config/rules/*.yaml`; new keys are optional, so every existing rule file
  loads unchanged. Template keys are checked by `check_template` against `_ALLOWED_KEYS`
  in `rules/engine.py`, which gains `person`.
- The people list and the address zone live in the archive's own `settings.yaml`
  ("This archive" in `2026-10-23-settings-screen-design.md`).
- OCR is Apple Vision on macOS and Tesseract elsewhere (`extract/ocr.py`); both give
  positions. Without an OCR engine, scans get no positions and the UI says so plainly.
- Cross-platform; text IO with explicit `encoding="utf-8"`; a migration for each new
  table (the next free number after `0027`).

## How it works

### 1. Page-1 positions

**What is kept.** For page 1: each line of text with its box, as fractions of the page
width and height (origin top left, after the page's own rotation), plus the page size.
Lines rather than words, because both OCR engines give lines directly and a page has
tens of them, not hundreds (builder's call, also the storage format: a JSON list per
file is enough).

**Where it comes from.**

- *PDF with a text layer*: pypdfium2's text page gives character boxes; group them into
  lines (builder's call how). PDF coordinates start bottom left and are in points:
  normalise by the page size.
- *Scanned PDF or image*: the OCR that already runs. `_ocr_vision` in `extract/ocr.py`
  receives a box per line today and drops it (`for text, _confidence, _box in results`);
  Vision boxes are normalised with the origin bottom left. Tesseract gives boxes through
  `image_to_data` instead of `image_to_string`.

**When.** The content indexer keeps page 1's lines when it extracts a new or changed
file, so a new document costs nothing extra: `ExtractedText` gains an optional `page1`
field, and `repo.save_content` stores it. The page-1 text must come from the same read
as the indexed text, so that a word found in a zone is always also in `file_text` (the
replay depends on this, see 4).

**Table** `file_layouts` (migration 0028): `drive_id` (primary key), `sha256`, `lines`
(JSON; `[]`: read, no text on page 1), `source` (`text-layer` | `vision` | `tesseract`),
`read_at`. A row whose `sha256` is not the file's current one is ignored.

### 2. The backfill

Files indexed before this change have text but no positions. A **layout pass** reads
them, built like the barcode pass (`run_barcodes_once` in `index/content.py`): one file
at a time in a daemon thread, a time limit per read, a read that times out is not
recorded and is retried later, a finished read is recorded even when it found nothing.

The pass renders page 1 only and, for a text-layer PDF, does no OCR at all. For a scan it
OCRs page 1 with the same engine, languages and resolution (`OCR_DPI`) as the indexer
used. The time per scanned page with Vision is not measured yet; the builder measures it
on the demo archive and states it in the guide (an estimate before measuring: about a
second).

**Order** (`repo.next_for_layouts`, like `next_for_barcodes`):

1. Inbox files, so a zone rule can fire on every new document.
2. Files a replay asked for (the **wanted** list, kept in memory, see 4).
3. Everything else by path, when `page1_backfill` is on (a new setting, default on).
   The pass shares the indexer's loop and so its rate (`indexer_reads_per_minute`); a
   separate rate setting was left out as unneeded.

`step()` tries content indexing first, then barcodes, then layouts, so the backfill only
ever uses idle time. Settings shows the progress ("Page 1 read for 1 240 of 2 015
documents") with a switch to pause it.

### 3. Zone conditions in rules

A rule can require text in an area of page 1:

```yaml
- id: pohjola
  when:
    zone:
      box: [0.05, 0.02, 0.45, 0.14]   # x0, y0, x1, y1 as fractions of page 1
      text_contains: ["pohjola"]
    folder_is: "##. Organize"
  then:
    folder: "Insurance/Pohjola/{person}"
    name: "{doc_date:%Y%m%d}_Pohjola"
```

- `zone.text_contains`: any of these words in a line of page 1 that lies in the box, by
  the same folding as today (`fold` in `rules/model.py`). All other conditions in `when`
  still have to match too.
- **Tolerance**: a line lies in the box when at least half of its area is inside the box
  grown by a margin on every side (builder's call: about 3 % of the page). Scans shift a
  few millimetres between letters; a small margin is what makes a box usable.
- A file without a current layout row does not match a zone condition. In the Inbox
  this is rare (inbox files are read first); while it is the case, the suggestion says
  "Reading page 1…" instead of silently offering nothing.

**Drawing a box.** In the preview (`PdfPages` in `FilePreview.tsx` shows pages as
images, so a drag rectangle over page 1 is plain frontend work), on the Inbox card and in
Browse. On release, the server returns the lines inside the box (a new endpoint, read
only). The owner picks what the box means:

- **Sender**: opens the learned-rules draft sheet with `when.zone` filled in (the box and
  its most distinctive word ticked, as the draft does today), the folder and name from
  the owner's filing when there is one, and the replay below.
- **Address area for this sender**: for the few senders whose letters break the usual
  layout. Stored on the sender's rule as `person_zone: [x0, y0, x1, y1]`; when that rule
  matches, people are looked for there instead of in the global address zone.

### 4. Replay with zones

The replay of `2026-10-23-learned-filing-rules-design.md` gains one step and one line:

- **Exact candidates.** A line in a zone is part of page 1's text, and page 1's text is
  part of `file_text` (1, "When"). So every document a zone rule can match already
  contains one of its words in its indexed text. One FTS query over `file_fts` with the
  zone's words gives every possible match; documents outside it cannot match. As
  built, the query is a prefix search per word (FTS tokens), while live matching is a
  substring test: a zone word inside a longer word ("vakuutus" in "henkivakuutus")
  matches live but is not a replay candidate. The replay can undercount for such words,
  never overstate.
- **Reading what is missing.** Candidates without a current layout row are put on the
  wanted list and read first by the layout pass (2). The replay sheet shows "Reading
  page 1 of 23 documents…" and updates as they come in; this is usually tens of
  documents, not the archive.
- **Not checked.** A candidate that cannot be read (no OCR engine, the read timed out,
  the file is missing) is listed as not checked, with the reason. The result line reads
  "Matches 14 documents you filed before (3 not checked yet): …".

The replay stays read-only and sends nothing anywhere.

### 5. People and `{person}`

**The people list** in `settings.yaml`:

```yaml
people:
  - name: Michiel        # what {person} becomes in a folder or name
    match: ["Michiel Visser", "M. Visser"]
  - name: Tiina
    match: ["Tiina Visser"]
address_zone: [0.06, 0.10, 0.52, 0.30]   # x0, y0, x1, y1 of page 1
```

`match` entries are folded like rule words and must all be found within one line or two
adjacent lines of the zone (builder's call: tolerance for OCR errors, such as one wrong
character in a name of eight or more letters). The shipped `address_zone` is the SFS 2487
address field; the builder sets the default from the standard and checks it against the
demo archive's letters. Settings shows a sample page with the zone drawn on it and lets
the owner redraw it.

**Detection.** For a document with a layout row, the person is the one whose `match`
is found in the address zone (or in the matching rule's `person_zone`). Two people found
(a letter to both): no person, and the Inbox shows both as a choice. None found: no
person. Detection is computed from the stored layout when it is needed, not stored, so
a change to the people list or the address zone applies at once; it never looks at the
rest of the text.

**In rules.** `{person}` is allowed in `then.folder` and `then.name`. A rule whose
template needs `{person}` gives no folder or name for a document without a person (the
next rule may give one; the Inbox asks "For whom?" with the people as chips), never a
folder with an empty part. A rule can also require a person: `when.person: Tiina`.

**Replay.** Rendering `{person}` uses the document's person: the owner's assignment (6)
if there is one, otherwise the detected one. A filed document whose person is unknown is
counted as not checked for that rule, not as a mismatch.

**Drafting.** When the owner files a document into a folder whose path contains the
document's person's name as a whole folder name, the draft proposes `{person}` in its
place, as it proposes `{year}` for the year today.

### 6. Saying it by hand

The owner can set **From** (a sender) and **For** (a person) on one document or many:
on the Inbox card, in the Inbox batch, and on a selection in Browse. This covers what a
box cannot: unusual layouts, handwritten envelopes, senders that write once a year.

- **Senders** are short names the owner types once ("Pohjola", "Verohallinto") and picks
  from afterwards. A sender rule made from a box (3) is linked to its sender, so the
  replay can say "your zone finds 14 of the 16 documents you marked as from Pohjola, and
  misses these 2", side by side.
- **People** are the people list (5).
- An assignment beats detection everywhere: in `{person}`, in `when.person` and in the
  replay.
- Filing a document with a folder that a rule rendered with `{person}` records the
  person used as an assignment, so every confirmed filing adds ground truth without an
  extra click (designer's call).

**Table** `file_assignments` (migration 0029, or the same migration as 0028, builder's
call): `drive_id` (primary key), `sender` (nullable), `person` (nullable), `set_by`
(`owner` | `filing`), `set_at`. Keyed by `drive_id` only, not `sha256`: who a document is
from does not change when its content is re-saved. No foreign key, as `rule_outcomes`:
files rows may be parked or purged.

These assignments are owner data that exist only in the database, unlike rules (config
files) and folders (the archive). A rebuilt `dam.sqlite` loses them. How they are kept
safe is an open question (below).

**Naming.** dam already calls ★ Ongoing and ! Important "marks"
(`collections/marks.py`, `api/marks.py`).
This feature never uses that word: the UI says **From** and **For**, the code says
*assignments*.

### 7. Where it shows

- **Inbox card**: the detected or assigned person and sender as chips next to the
  suggestion, with where they came from ("address area", "you set this", "rule
  pohjola"). Clicking a chip changes it.
- **Preview**: a "Draw a box" tool on page 1; existing zones of the matching rule are
  shown faintly, so the owner sees why a rule fired.
- **Settings → Filing rules**: the zone of a rule drawn on a sample page of a document it
  matched; the people list and the address zone; the backfill progress and its switch.
- **Test a document** (learned-rules design, 6) also lists the page-1 lines in each zone
  and the person found, so a missed match can be explained.

## Build order

1. Page-1 positions at index time, `file_layouts`, and the layout pass with its order and
   setting. Nothing visible yet except the progress line.
2. `when.zone`, the endpoint for lines in a box, drawing on the preview, the draft from a
   box, and the replay with exact candidates and "not checked".
3. The people list, the address zone, detection, `{person}`, `when.person`, and
   `person_zone`.
4. Assignments: From and For in the Inbox and Browse, and the replay comparison against
   them.

Each step is useful on its own: after step 2, sender rules are already precise.

## What is decided, and by whom

- Use where text sits on page 1 to identify sender and person; the owner draws boxes;
  one archive-wide address zone with `{person}`; manual From and For; backfill existing
  documents lazily: the owner (2026-10-24).
- Everything marked "designer's call" above: the designer, to be checked by the owner.
- Storage format, line grouping, tolerances, the name-matching tolerance, the default
  address zone's exact values, the pass's time limit and the measured OCR time: the
  builder.

## Open questions

- Should a sender also be a template key (`{sender}`), so one rule could file every
  marked sender's letters to `Correspondence/{sender}`? Not part of this design.
- Assignments live only in `dam.sqlite`. Should they also be written to a file in the
  data folder (as `rules-state.json` is), so a rebuilt index keeps them?
- A letterhead that is only an image gives a zone with no text. How common this is in
  the owner's post decides whether image matching becomes its own design.
