# Search by tag, a Tags screen, tag groups and a quick search on Today

Status: design, 2026-10-25. Decided with the owner on 2026-10-25.

## Why

Tags exist on every file but are only a field in the file panel. They cannot be searched,
listed, tidied or reached quickly. Typing "Kela" and "medical" together, merging two
spellings of one tag, or opening the tags used most lately all need a place to do them.

## Goals

- Search Browse by tag, alone or with words, from Browse and from a search box on Today.
- A Tags screen to see every tag with its file count and to create, rename, merge, delete,
  pin and group tags, each with an Undo.
- The sidebar shows the pinned tags and the most recently used ones, one click from their files.

## Non-goals

- Tags on folders or collections, nested groups, tag colours.
- A tag as a filing decision: groups only arrange the Tags screen and suggestions. They are
  never written on files.

## How it works

### Storage (migration 0033)

Tags stay dam's own data in the index database, not archive files, so the operation layer,
the journal and Activity are not involved (as for editing a file's tags today: nothing is
journaled). Undo is a toast that sends back an undo record.

- `tags.pinned_at` (pin time, null: not pinned), `tags.group_id` (a tag is in at most one
  group), `tags.last_used_at` (set when the tag is put on a file it was not on).
- New table `tag_groups (id, name unique)`.
- Index `file_tags (tag_id)`: "which files have this tag" is an index lookup, not a scan.

A tag with no files is a row in `tags` with no `file_tags` rows. The existing suggestion
list (`GET /api/tags`) still lists only tags in use.

### Search

`GET /api/search?q=&tag=a&tag=b`. Each `tag` is matched without case or accents; a file
needs all of them. Words are optional when there is a tag (the tagged files are then listed
by name). Each tag becomes `f.drive_id IN (SELECT drive_id FROM file_tags WHERE tag_id IN
...)`, so the cost follows the tag, not the archive. A tag that does not exist finds nothing.

Browse keeps the tag filters in the address (`?tag=a&tag=b`) and the words as `?q=`, so a
link can open a search. In the box, `tag:name` or `tag:"two words"` followed by a space
becomes a removable chip; a matching tag is also suggested as you type, and Enter or a click
makes it a chip. Chips and words combine. Browse searches indexed files by name, path and
text, as before (folders and collections are not searched).

Today gets a Search card (movable and foldable like the others, included in Reset layout).
Enter opens `/browse?q=...`; `tag:` works there too.

### Tags screen (`/tags`)

Every tag with its file count, grouped, with a filter box. A tag opens Browse with its
filter. Actions (menus on each tag; groups have a menu too):

- Create: a tag with 0 files until used.
- Rename: updates every file. A name another tag has asks to merge instead.
- Merge: one or more tags into another. The preview says "N files get 'x'; 'y' is removed".
- Delete: removes the tag from all its files; the confirm shows the count.
- Pin or unpin (for the sidebar).
- Move into a group or out of it (menu; drag onto a group works too). Groups: create,
  rename, delete (its tags are ungrouped).

Every change returns an undo record (`remove`: tags to delete, `unlink`: links to drop,
`restore`: tags to bring back with their files, pin, group and last use). `POST
/api/tags/undo` applies it. Pin and group changes undo the same way.

### Sidebar

A "Tags" section whose header opens the Tags screen. Below, up to 8 tags: pinned ones first
(oldest pin first), then the most recently used to fill up (a tag with no files is not
"recent"). It folds like the other sections, and the fold is remembered.

## Risks and open points

- Migration number: 0033 was chosen to stay clear of 0031 and 0032 on other branches; its
  `down_revision` is "0030" on this branch and must be rechained before merging.
- Existing tags have no `last_used_at`, so only tags used from now on appear as "recent"
  (pinned tags always show).
- Tags differing only in case ("kela", "Kela") are still two tags; creating and renaming
  refuse a name that clashes without case or accents, and the Tags screen offers merging.
