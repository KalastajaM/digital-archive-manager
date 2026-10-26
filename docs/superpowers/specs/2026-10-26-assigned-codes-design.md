# Assigned filing codes: design

Status: proposed (2026-10-26). Builds on [filing codes](2026-10-23-filing-codes-design.md).

## Intent

A paper document gets a filing code before it reaches dam (a QR sticker, or the inbox
folder it is scanned into). A document that arrives digitally (an email attachment, a
download) cannot carry a sticker, so today its decision is made in the Inbox form, field
by field. This feature lets the owner give an inbox file a filing code from inside the
app, as if a sticker were on it: one action sets everything the code sets (tray, folder,
name pattern, tags, collections), and the file joins **File N marked**.

It also splits work into two passes: go through the inbox giving codes quickly, then
confirm all of them at once in Marked files.

## Build steps

1. **Assign from the keyboard and the batch form**, with a code picker that lists the
   codes. Proves the source, the storage and the flow.
2. **A code palette to drag from** (optional): decided after step 1 is in daily use.

## Goals

- An inbox file can be given one code from the table, and loses it again with one click.
- An assigned code is a filing-code source like the folder and the sticker
  (`CodeHit.via == "assigned"`), so the form, the chips, the conflict check, the dry run
  and File N marked work as they do today.
- Assigning is fast enough to sort an inbox of 20 files in a minute without the mouse.

## Non-goals

- Changing the document. Nothing is drawn on or written into the file; the code is
  dam's record of a decision.
- Filing on assign. Assigning only fills in suggestions; filing still goes through the
  form or File N marked, with its preview.
- Codes that are not in the table. The picker offers only valid codes.
- Assigned codes on files outside the inbox.

## Step 1

### The source

`CodeHit.via` gets a fourth value, `"assigned"`. `codes_for` (`codes/apply.py`) adds the
file's assigned code, if any, as a hit.

**Precedence (designer's call).** An assigned code is the owner's latest and most
deliberate decision, so it overrides the folder and sticker codes instead of being
marked **Codes disagree**: when a file has an assigned code, only that code is applied.
The other hits stay in the list, shown as overridden ("P (sticker, overridden)"), so the
owner sees what was found. A sticker's tick boxes (★, !) still apply: they mark the
document, they are not a code. Removing the assigned code brings the other codes back,
including any conflict between them.

One assigned code per file. Assigning another replaces it. A file that needs two codes'
worth of values needs a code that does both, or the form.

### Storage

A new table in the index database, next to `file_qr_codes`: `drive_id`, `sha256` of the
content it was assigned on, `code` (upper case) and `assigned_at`. Like the QR reads, it is
used only while the file is in the inbox, and kept after filing, so a filing that is
undone brings the file back with its code. A file whose content changed (`sha256`
differs) keeps the code: the decision is about the document, not about the bytes.
(Unlike a QR read, which depends on the content.) A file filed and later moved back into the
inbox shows its old code with its chip, which the owner can remove.

A code later deleted from the table, or made invalid, sets nothing (as for stickers);
the chip shows the code struck through with "not in your codes".

This is dam's own state, not a change to the archive: nothing in the archive moves, so it
needs no operation-layer step, preview or journal entry. The undo for assigning is
removing (and the toast after assigning has **Undo**).

### Assigning

- **Code picker.** With an Inbox file (or a selection) focused, a key opens a small
  picker at the list: each code with its sticker, the code and its label, the same list
  as in Settings. Typing filters by code first, then label; Enter or a click assigns the
  highlighted code to the file or every selected file and closes the picker; Esc closes
  it. The key is the builder's call among the free ones (`j`, `k`, `u` and Space are
  taken in the Inbox; check `keyboard.ts`); `c` if free.
- **Batch form.** With several files selected, the batch form gets a **Filing code**
  field (the same picker as a dropdown) that assigns it to all of them.
- **Form.** The single-file form shows the assigned code as a chip at the top
  ("V3 · Car insurance (assigned)", with ×), and an **Assign code…** button when none is
  assigned, which opens the picker.
- **List.** An Inbox row with an assigned code shows the code in its row, as coded rows do
  now.

After assigning, the form's fields refill from the code exactly as for a sticker; field
chips read "from code `V3` you assigned". Fields the owner had already changed by hand
in the open form are left alone (as when a QR read lands while the form is open; builder
checks the existing behaviour and follows it).

### File N marked

Rows show the assigned code as "V3 (assigned)", with overridden codes after it. Nothing
else changes: the same dry run, flags and one batch.

### API

An endpoint to set or clear the assigned code for a list of `drive_id`s, refusing files
not in the inbox and codes not in the valid table; the inbox and suggestion responses
carry the hit with its new `via`. Shapes are the builder's call. Regenerate
`frontend/src/api/schema.d.ts`.

## Step 2 (optional): a palette to drag from

The owner's original idea: codes shown as a palette, dragged onto a document to apply it.

- The palette is a temporary overlay in the Inbox, shown only while in use (a toolbar
  button **Codes**, or the step 1 key held or pressed twice), so it costs no room
  otherwise.
- Each code is a chip that looks like its sticker. Dropping a chip on a list row, on the
  selection, or on the open document's preview assigns that code, exactly as the picker
  does. Where on the preview it lands means nothing.
- The other direction already exists for trays: rows drag onto sidebar trays. Dropping
  rows onto a palette chip should work the same way.

Decided after step 1 has been used for a while: if the picker is fast enough, the palette
may not be worth its screen space.

## Constraints

- Safety rules in CONTRIBUTING apply; this feature writes nothing to the archive.
- Migration `0035_assigned_codes.py` (next free number at the time of writing).
- Tests use fake archives: the source and precedence in `codes_for`/`apply_codes`, the
  table's lifetime across filing and undo, the endpoint's refusals, the picker, batch
  form and chips in the frontend.
- A CHANGELOG entry under Unreleased, and an "Assigning a code" part in the guide's
  Filing codes section.

## Left to the builder

The picker's key and layout, API shapes, table columns beyond those above, and how the
overridden codes are styled.
