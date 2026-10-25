# One block order for the file view

Status: design, 2026-10-25. Agreed with the owner on 2026-10-25.

## Why

A file is shown in three places: the Browse file panel, the collection inspector (a member
file) and the item view in a tray. Each grew its own order. Browse put the tags and the
summary below the preview, trays put them above; the tray view showed no collections at
all. The same facts were hard to find twice.

## Goals

- The same blocks in the same order in all three views, with only the view's own block
  differing.
- The tray item view shows the collections the file is in and can add it to one.
- The keyboard order follows the visual order. Nothing that was reachable is removed.

## Non-goals

- New behaviour for tags, summary, notes or the preview. They are the existing components.
- A backend change. The collections of a file (`GET /api/files/{id}/links`) and the
  membership changes (`POST /api/collections/{id}/members`, `.../members/remove`) already
  exist, and the picker and the Ongoing sync work as before.

## The order

1. **Header**: the file name (click to rename), the folder path with Move to, the lock
   control, and the star and Important marks (which sit in the preview's toolbar, the
   app's one toolbar order, see below).
2. **Tags**.
3. **Collections**: the trays and collections the file is in as badges (a collection's x
   takes the file out, with Undo), and **Add to collection...** with the existing picker.
4. **Summary** (foldable, `SummaryBox`).
5. **The view's own block**:
   - Browse: Put in tray, Back to inbox.
   - Collection: its group, Show in folder and Remove from collection, then the same
     Put in tray.
   - Tray: the item's fields, Mark done or Mark paid, the action row, a dated item's
     checklist, the bill's remaining fields.
6. **Preview** with its toolbar (view, star and Important, Ask AI, then the bin).
7. **Notes, checklist, history** (foldable), where the view has them: Browse and a
   collection have the file's note; a tray has the item's note, checklist (not a dated
   item's, which stays in the own block as before) and history.

## How

`components/FileView.tsx` renders the seven blocks in this fixed order from named slots
(`header`, `tags`, `collections`, `summary`, `own`, `preview`, `notes`). A screen fills
slots; it cannot reorder them. Each non-empty block is a `div.file-view-block` with
`data-block="<name>"` and `display: contents`, so styling of the content is unchanged and
the DOM order is the keyboard order. Tests read `data-block` to check the order.

`FileCollections` (in `screens/FileActions.tsx`) is the collections block: the existing
`LinkBadges` and the existing add-to-collection action. `FileActions` keeps only what is
Browse's own (Put in tray, Back to inbox); the summary, the note and Add to collection are
blocks of the shared view.

Browse and the collection inspector both render `FilePanel`, which now fills `FileView`.

### The tray

The item view keeps its earlier decisions: the title in the header, the tags under the
title (so the tags are inside the header block there, and the tags block is left out), one
action row, Quick Look in the preview toolbar, foldable sections. The item header is
followed by the files line (count or tabs), then the shown file's name and folder. The
shown file's header, tags and preview belong to `FileMeta`, so they are portaled into
their slots in the layout. The collections block is for the shown file (for an item with
several files, the tab chosen). The tray item itself is not listed among the badges.

## Risks

- A tray's summary block still has its own "Summary of" picker for items with several
  files, as before; it does not follow the tab.
- Where Browse showed the preview first, the preview now follows the actions. This is the
  intended change.
