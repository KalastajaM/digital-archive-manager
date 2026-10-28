# Relatives: the files a document belongs with

Status: draft for agreement, 2026-10-28. Mockups: Design canvas
https://claude.ai/artifact/51hxdmwnqmJpmLEKhg3obJ (boards Related, Tree, AI, Quick look;
the radial Map board is superseded).

## Goal

For one file, show the other files it belongs with, say why, and let the owner act on
them together: tag, collect, move or link them, or say a file is not related. Built from
what dam already stores, with an optional on-click AI pass that finds relatives the
stored data misses.

Working name **Relatives** (block title "Relatives", popup "Relatives of <file>"). The
name is a placeholder until agreed; see the end.

## Phases (one PR each, in this order)

1. **Relatives block** in the file details panel: scoring service, API, ranked list with
   reasons, multi-select actions, Not related.
2. **Relatives popup**: the folder-tree outline with arcs, the "In common" strip, hover
   card, and Quick Look in compare mode.
3. **AI find relatives**: a new on-click AI task over a local shortlist.

Each phase is useful on its own. Phase 1 carries the backend; phases 2 and 3 mostly add
UI on top of the same endpoint.

## How relatedness works

A file is a relative when it shares at least one **link** with this file. Each link adds
its weight; the list is ranked by the sum. Boosters add weight only to a file that is
already a relative and never make one on their own.

| Link | Source (already stored) | Weight |
| --- | --- | --- |
| Same reference number | `items.fields.reference` via `item_files` | 5 |
| Same sender | `file_assignments.sender` | 3 |
| Same collection | `collection_members` | 3 |
| Shared tag (each) | `file_tags` | 2 |
| Same folder | parent of `files.path` | 2 |
| Same IBAN | `items.fields.iban` via `item_files` | 2 |
| Same person ("for") | `file_assignments.person` | 1 |

| Booster | Source | Weight |
| --- | --- | --- |
| Same month | `files.doc_date` (both set, same year and month) | +1 |

Rules:

- **Values that match too much count less.** A tag, IBAN, sender or person shared by
  more than `relatives.common_limit` files (default 200) gives half weight; one shared by
  more than 5 × that gives none. This covers payment services whose IBAN serves many
  merchants, and a catch-all tag. File type and "same year" are never links.
- **Not related wins.** A pair the owner marked Not related is left out whatever it
  shares, AI included.
- Only live files: not missing, not parked, not folders, not links. A link in the archive
  stands for its target (`services/links.py`), so the target is listed once, never the
  link beside it.
- Sender is never guessed from names or text. Files without a stored sender simply lack
  that link.
- Limits: the block shows the top 4 plus "N more"; the API returns at most 200, best
  first.

The weights live in one table in the service so they can be tuned without touching the
UI. They are not settings yet; that can come when real use shows a need.

## Data

One new table, index data (not the archive), so no operation layer and no journal, like
`file_assignments` and `maintenance_ignored`:

```
related_dismissed (migration 0041, down_revision 0040)
  drive_a   Text  primary key part   -- the smaller of the two drive ids
  drive_b   Text  primary key part
  created   Float not null
```

Keyed by drive id, so a pair survives moves and renames. No FK to `files` (rows may be
parked or purged). "Show again" deletes the row; that is a delete of an index row, not
of a user file, so the safety rules are not involved.

## Backend

**`dam/services/relatives.py`**: `RelativesService(engine, links, ...)`

- `of(drive_id, limit) -> Relatives`: one SQL query per link kind, joined in Python,
  scored, ranked. Returns each relative's drive id, path, name, score, its links as
  `(kind, value)` and its boosters; plus `common`, the shared values with counts (the
  "In common" strip); plus `hidden`, the number of dismissed pairs for this file.
- `dismiss(a, b)`, `restore(a, b)`, `dismissed(drive_id)`.

**API** (`api/routers/files.py`):

- `GET /files/{drive_id}/relatives?limit=` → `RelativesOut`
- `POST /files/{drive_id}/relatives/dismiss` `{drive_id}` and `.../restore` `{drive_id}`

Then `npm run gen:api`.

**Actions reuse existing endpoints.** Each one previews first and is undoable as it is
today:

- Tag: the tags endpoints. To check: whether a multi-file tag change with one undo
  exists (Browse selection). If not, add `POST /tags/apply {drive_ids, tag}` as one undo
  step.
- Add to collection: `POST /collections/{id}/members`.
- Move to folder: `POST /browse/move/preview` and `/browse/move` with `mode: "move"`.
- **Link them here**: `/browse/move` with `mode: "link"`, the selected files, and this
  file's folder. Files already in that folder are dropped before the call (the button
  shows the real count, and is disabled with a reason when it is 0).
- **Link this file there**: a link to this file in each distinct folder of the selected
  files. Today's move endpoint takes one target folder. Decision needed (see open
  questions): one batch with several targets, or one batch per folder.
- Links need Developer Mode on Windows; the buttons show the same plain refusal Browse
  gives and hide when Browse turns Link off.

## Frontend

**Phase 1, `RelativesBlock`** in the details panel (`FileDetails.tsx`), New look only
(Classic is temporary and will not get new features; to confirm).

- An "unfiled" card first when a relative is still in the Inbox (link "same sender, not
  filed yet"), with its own "File in <folder>…" shortcut into the normal filing flow.
- Rows: checkbox, name, folder, short labels for the kind of each link (folder, sender,
  tag, collection, IBAN, reference, person) and "+ same month".
- Action bar when anything is ticked: "This file and N related", Tag…, Add to
  collection…, Move to folder…, Link them here, Link this file there.
- Per row: Quick Look (Space) and Not related. "N marked not related" brings them back.
- Empty state: "No relatives yet. Files share a folder, tag, collection, sender, person,
  IBAN or reference to show here."

**Phase 2, `RelativesDialog`** (modal, opened from the block's "Show connections"):

- Left: the folder outline cut down to folders that hold a relative, one row per file,
  then "N folders have no relatives". Long lists fold folders with a count.
- Arcs: one SVG beside the rows, from this file to each relative; width by score,
  orange dashed for an unfiled relative, dotted for an AI suggestion. Only vertical
  scrolling; arcs bulge up to a fixed width, and an arc to a row out of view ends in a
  marker ("↑ 3 above"). No zoom or pan.
- "In common" strip: each shared value once with its count; clicking one highlights its
  files and fades the rest.
- Hover or focus card: the exact shared values, Quick Look, Not related.
- Right: the same action panel as the block, plus quick selections (2+ links, same
  sender, outside this folder).
- Keyboard: arrows move between rows, Space Quick Look, X ticks, N Not related.

**Quick Look compare mode**: extend `QuickLook.tsx` (already a modal with ←/→ and
Space) with an optional second pane for "this file", a footer with what they share, and
verdict keys: N Not related, → Skip, Y Related and next. "Related" only moves on; it
stores nothing, since being related is computed, not stored.

## Phase 3: AI find relatives

A new task `dam/ai/tasks/find_relatives.py` next to `suggest_filing`, through
`AIService.prepare` / `run` as every AI call is.

1. **Shortlist, local and free.** Build an FTS query from this file's text (its rarest
   terms plus reference numbers, IBANs and the sender name) and take the top 28 from
   `search.ranked(engine, match, exclude_folders)`. Every candidate is checked with
   `guard.is_excluded`. Dismissed pairs and files already in the list are left out.
2. **Payload**: this file's name, folder and first 2,000 characters; per candidate a
   short id, name, folder and 300 characters. Document text inside the delimited data
   block, as the other tasks do.
3. **Answer schema**: `[{id, reason, confidence 0..1}]`, ids only from the shortlist
   (anything else is dropped), and "none" allowed. Picks below 0.6 are hidden.
4. **Model** Haiku, `max_tokens` 2,000 (thinking counts against it), cached per (file, shortlist) in `ai_cache` so
   reopening costs nothing.

The preview sheet shows what is sent, what is not (excluded folders, whole files, tags,
notes), the model, the worst-case cost and this month's spend. Results show as rows
marked "AI" with their one-line reason; they change nothing until the owner acts on
them.

## Safety

- Nothing here writes to the archive outside `dam/ops`: every move and link goes through
  the existing planner with its preview, journal and undo.
- No new kind of archive change, so no new undo path is needed. To check in phase 1:
  "Link this file there" with several folders still undoes as one step if done as one
  batch.
- `related_dismissed` and the AI cache are index data.
- AI: on click only, preview of exactly what is sent, budget check, excluded folders
  enforced twice (SQL and `guard.is_excluded`).

## Tests

- Service: each link kind, the booster rule (same month alone is not a relative), common
  values losing weight, dismissed pairs, links counted once with their target, excluded
  or missing files, ranking stability.
- Migration 0041 up on a copy of the demo database.
- API: shapes, 404 for an unknown file, dismiss/restore round trip.
- Frontend: block rendering and counts, the disabled link buttons with their reason,
  action calls carrying the right drive ids, Not related and restore, dialog arcs per
  row, the strip filter, keyboard.
- AI: shortlist respects exclusions and dismissals, ids outside the shortlist dropped,
  "none", cache hit, budget refusal. With `DAM_AI_FAKE=1` only.
- Archive guard and `test_no_delete.py` untouched.

Docs: `docs/guide.md` section "Relatives", `docs/reference.md` for the API, weights and
the AI task; a `CHANGELOG.md` entry per phase.

## Open questions

1. **Link this file there**: one batch with several target folders (needs a planner
   change, one undo) or one batch per folder (no planner change, several undo entries)?
   Recommendation: one batch, since it is one action to the owner.
2. **Classic look**: New look only? Recommendation: yes.
3. **Weights**: the table above is a first guess; adjust after a week of use on a real
   archive copy.
4. **Name**: see below.

## Name

Options, with the trade-off for each:

- **Relatives**: the family-tree idea in a plain word everyone understands; reads well
  in UI ("3 relatives", "Not a relative"). Recommended.
- **Kin**: short and warm, but unusual in everyday English and gives non-native readers
  pause.
- **Family**: friendly, but "family" is also a likely folder name (40. Family), which
  would confuse.
- **Lineage**: suggests versions over time (earlier and later), which is only one of the
  links.
- **Connections**: neutral and clear, no family-tree flavour.
