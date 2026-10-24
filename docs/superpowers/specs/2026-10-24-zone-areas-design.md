# More areas per rule, picture areas, and areas you can see and change

Status: design, 2026-10-24. Extends `2026-10-24-zone-identification-design.md` (page-1
positions, zone rules, people, From and For). Decided with the owner on 2026-10-24: several
boxes per rule, a picture area when a box holds no text, numpy as the one new dependency,
and areas that stay visible and can be changed after saving.

## Why

One box says who sent a letter, but a sender sends many kinds of letters: a policy
(vakuutuskirja), an invoice, a change notice. The kind is usually printed in a fixed place
too, such as the title under the letterhead. A rule needs both boxes to file each kind to
its own place.

Some letterheads are only a picture: OCR finds no text in the box. Then the picture itself
has to be recognised, on scans that are never identical (shifted, another DPI, slightly
skewed, lighter or darker).

After a box is saved it disappears from the page, and a detected document shows only the
area of the one rule that won. The owner cannot see why a document matched, nor fix a box
that is a little off without drawing it again.

## Goals

- A rule can have several areas; every area must match (any word within an area is enough,
  as today).
- An area can be a picture instead of words, matched by similarity, with the threshold
  proven by the replay.
- On page 1, the owner sees the areas of every rule that matched, the lines that matched in
  them, and the line where the person was found; areas can be moved and resized, with the
  replay shown before saving.
- The rule editor in Settings shows a rule's areas on a sample page.

## Non-goals

- Pages after page 1, large rotations (more than a few degrees), colour matching.
- Picture areas for the address area: a person is only found from text.

## Anti-goals

- Keeping personal content as a picture. A picture area is only offered for an area that
  identifies a sender or a kind of letter, never for the address area, and the owner sees
  the crop before it is saved.
- A picture rule that is slow to test: the replay never re-reads archive files for it.

## How it works

### 1. Several areas: `zones`

`when.zone` becomes `when.zones`, a list (the single `zone` was never released, so no
compatibility is kept):

```yaml
- id: pohjola-vakuutuskirja
  when:
    zones:
      - box: [0.05, 0.02, 0.45, 0.14]      # letterhead
        text_contains: ["pohjola"]
      - box: [0.55, 0.05, 0.95, 0.12]      # title
        text_contains: ["vakuutuskirja"]
    folder_is: "##. Organize"
  then:
    folder: "Insurance/Pohjola/{person}"
```

Each zone has either `text_contains` (words, as today) or `image` (section 2). The rule
matches when every zone matches. The text check of the whole document (a text zone's word
must be in the indexed text before page 1 is looked at) applies to every text zone.

**Order.** For folder and name the first matching rule wins, so a rule with more areas
must come before a plainer rule for the same sender. When a rule is saved from a box drawn
on a document that another learned rule already matches, the new rule is placed directly
above that rule (designer's call). The replay keeps saying "For N of them rule X comes
first" when the order is still wrong.

**Drawing several boxes.** Every box drawn in the preview is kept at once and numbered
(Box 1, Box 2, ...); the panel "Boxes on page 1" lists each with the words found in it
and its own remove button, and its close control reads "Close and drop the boxes". Esc
drops the box being dragged, then the last box, then closes the tool. **Make a rule…**
(the former "Sender…") drafts a rule with all boxes (one ticked word per text box, chosen
as today); who the letter is from is an optional **From (sender)** field in the rule
sheet, prefilled from the document's From assignment, because a box can identify the
kind of letter as well as the sender. The address-area choices ("Address area for this
rule's letters", "Address area for all letters") are shown when exactly one box is drawn. The rule sheet shows each area as its own group of word chips
with a Remove action; a rule needs at least one condition.

### 2. Picture areas

**When it is offered.** Every box row has a choice **Words** / **Picture**; Picture shows
the crop. The address-area choices are never offered for a picture box.

**What is stored.** Page 1 is rendered at a fixed width (`PICTURE_PAGE_WIDTH = 1000` px,
about 120 DPI on A4), converted to 8-bit grayscale, and the box is cut out, its long side
capped at 300 px. It is saved as a PNG under `config/rules/areas/<rule-id>-<n>.png` and the
zone names it: `image: areas/pohjola-1.png`. Not black and white: a threshold turns grey or
coloured logos into blobs or nothing depending on the scan, and the saving is a few KB.
Saving goes through the same backup and read-back as rule files. Deleting a rule leaves its
picture files (no deletes outside the operation layer's allowed list); they are listed in
Settings as unused.

**Page-1 pictures of documents.** The page-1 pass (`ContentIndexer`, layout pass) also
keeps a grayscale page-1 picture of each PDF and image at the same fixed width, as a JPEG
(quality about 70, about 20 to 40 KB) in `cache/page1/<drive_id>-<sha256 prefix>.jpg`. It
is cache: rebuilt when missing or when the content changes, never in the archive. New
documents get it when they are indexed (the page is rendered for OCR anyway); older ones
through the backfill, as the positions. The rendering must use the page's own rotation and
EXIF orientation, as the positions do.

**Matching.** Normalised cross-correlation (numpy) of the crop over a search window, the
box grown by 5 % of the page on every side, at scales 0.9, 0.95, 1.0, 1.05 and 1.1; the
score is the best value (0 to 1). A zone matches when the score is at least its
`min_score` (default 0.85: the builder's call after testing, see the build notes
below). Both images
get a light blur first, which makes the score tolerant of scan noise. numpy is added to the
core dependencies (BSD licence).

**The proof.** The replay shows, for a picture rule, the scores of its matches and of the
best non-matches near the threshold, so the owner can see how well separated they are, and
lets the owner set `min_score` in the sheet. A document without a page-1 picture yet is
"not checked", as for text. Since a picture zone has no text filter, the replay loads the
page-1 pictures of every filed PDF and image; it keeps the time budget and reports
truncation. Combining a picture area with a text area or a sender is recommended in the
sheet ("Add a text box to make this faster and surer").

**Pre-filter (builder's call).** A 64-bit difference hash of the area may be stored to
skip documents quickly, only if it measurably speeds up the replay without losing matches
on the demo archive.

### 3. Seeing areas

**Show areas** is a toggle in the preview toolbar on page 1 (on by default when the
document has any). It draws:

- the areas of every rule that matched the document, labelled with the rule id; the rule
  that gave the folder or name is drawn stronger;
- the lines that matched inside each text area, highlighted, and the best match position
  of a picture area with its score;
- the address area used (the archive's or the rule's own) and the line where the person
  was found ("For: Tiina, found here").

In **Test a document**, the areas of rules that did not match are drawn dashed, with the
reason.

The suggestion (Inbox entries, `GET /api/files/{id}/suggestions`) gains `areas`: one entry
per matched rule area `{rule_id, index, box, kind: "text" | "image" | "address", lines:
[box], score?}`, plus the person's line `{box}` when a person was found.

### 4. Changing areas

Clicking a drawn area selects it: handles to resize and drag to move. On release the rule
sheet opens with the changed area and the replay runs again, so the owner sees the effect
on past documents before saving ("finds 16 of 16, was 14"). A picture area's crop is cut
again from the current document when its box changes. The archive-wide address area and a
rule's own address area are changed the same way (saved to settings or the rule).

Settings → Filing rules: a rule with areas shows them on a sample page, the document it
matched last (from the track record), or one the owner picks; the areas can be changed
there too.

## Build order

1. `zones` in the model, engine, replay, draft and API; several boxes in the panel and
   the sheet; the order rule.
2. Showing areas: the `areas` in the suggestion and explain, the overlay and the toggle.
3. Changing areas in the preview and in Settings.
4. Picture areas: page-1 pictures in the cache, crops, matching, the replay with scores.

## What is decided, and by whom

- Several areas per rule, picture areas with numpy, grayscale low-resolution storage,
  visible and editable areas: the owner (2026-10-24).
- "Designer's call" above: the designer, to be checked by the owner.
- Exact thresholds, sizes, blur, the hash pre-filter: the builder.

## Build notes (step 4, picture areas)

- Default `min_score` is 0.85, not 0.7. On synthetic letters (a logo, text-like bars) a
  rescan with shift, a size change of 10 %, a darker copy, noise or a 2 degree skew scored
  0.94 to 0.998; 60 other random logos in the same place scored at most 0.71. On the
  demo archive's PDFs (one line of text each, so a hard case) the same line of text in the
  same font with other words scored up to 0.80, and the title cropped from a document found
  again on its rescan scored 0.95 to 0.99. 0.7 would have matched most of those other lines.
- A document takes about 6 ms on an M-series Mac, 3 to load its picture (JPEG decoded at
  half size) and 3 to match (FFT correlation at half the stored resolution); no hash pre-filter was added because the replay did not need one.
- The crop file is written when the area is made (the draft, or a moved area), because
  the replay needs the file; if the rule is not saved it stays and Settings lists it as
  unused.
- Stale page-1 pictures (changed sha) are left in the cache: the AST guard allows no
  remover there and it was not changed.

