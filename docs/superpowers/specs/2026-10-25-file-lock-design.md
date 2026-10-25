# A lock on files: a safety catch for file changes

Status: design, 2026-10-25. Decided with the owner on 2026-10-25.

## Why

dam already refuses to move a file marked Important to To Delete. Everything else about
such a file (rename, move, refile) is one slip away: a drag and drop in the wrong place,
a batch that included it. The owner wants a safety catch that is on by default for
Important files, that can be put on any other file, and that must be lifted on purpose,
only for as long as the owner is working with that file.

## Goals

- A locked file can be viewed and described but not changed on disk.
- Important files are always locked; any other file can be locked and unlocked.
- Unlocking is temporary by default: it lasts until the owner leaves the file.
- The server enforces it. The page cannot unlock anything on its own, and no unlock
  outlives a crash or a restart.

## Non-goals

- A password or any identity check. This is a catch against mistakes, not a security
  boundary against someone using the local app.
- Locking folders from the interface (the rule works for a folder if one is ever locked).

## Anti-goals

- A silent skip. A batch that includes a locked file is refused with the file named.
- A lock that stops the owner's own data work: tags, notes, checklist, From and For,
  trays, stars, the Important mark, summaries, previews and reads stay open.

## How it works

### What counts as a file change

Every change to a file on disk goes through the operation layer, so the lock lives in the
planner (`dam.ops.planner`), where the batch is resolved before anything is journaled or
done. RENAME, MOVE and QUARANTINE of a locked file are refused, which covers rename,
Move to, drag and drop, Back to inbox, filing and refiling, Move to To Delete and
Convert. A folder is refused when anything locked lies inside it. Links and new folders
(starring, Ongoing, Important links) are not file changes. Undo is not gated: it only puts
back what the owner did earlier and must stay available (it is journaled and verified as
always).

### What is locked

- A file marked ! Important (`MarkService.important_paths`), and everything under a marked
  folder. This needs no stored lock.
- A file in the new table `file_locks`, keyed by `drive_id` so the lock survives moves and
  renames (the same reason as `file_assignments`). Migration `0031_file_locks.py`:
  `drive_id` (primary key), `locked_at`.

### Unlocking: a grant the page holds

`POST /api/files/{id}/unlock` with `{"mode": "now"}` returns a random token and keeps it
in the server's memory only (`LockService`). The page sends its tokens in the
`X-Dam-Unlock` request header on every call; a middleware puts them in a context variable
for that request, and the planner accepts a locked file only when a live grant for that
exact `drive_id` is among them. Because grants live only in memory, a restart or a crash
leaves everything locked. A grant expires after 15 minutes without use (each accepted use
renews it), as a backstop for a page that vanished. The page forgets its token when the
file is left (another file selected, panel closed, navigation, reload) and calls
`DELETE /api/files/{id}/unlock` to release it at once.

`{"mode": "for_good"}` removes the stored lock of an ordinary locked file; it needs no
token afterwards. For an Important file it is refused (409): only "for now" exists.
`POST /api/files/{id}/lock` stores a lock on any file (and drops its grants).
`GET /api/locks` lists the locked files, so lists can show a lock icon without touching
every record.

### Refusals

A refused plan names the files: "This file is locked. Unlock it to change it." for one
file, "These files are locked (a.pdf, b.pdf). Unlock them to change them." when a batch
holds locked files. Nothing in the batch is done. The existing refusal to move an
Important file to To Delete ("unmark it first") stays and comes first.

### Interface

A lock icon on locked files in lists and in the file panel. The rename, move and To Delete
controls are disabled with the reason as a tooltip. Unlock asks "For now" or "For good"
(Important: only for now, with a note that it locks again when you leave the file). While
unlocked the panel says "Unlocked until you leave this file" with "Lock again". Lock is
offered on unlocked ordinary files.

## Testing

Each refused operation kind with and without a grant; metadata changes while locked;
Important without a for-good unlock; expiry, release and renewal; batch refusals naming the
files; the migration; a new `App` on the same data finds every file locked again; the
interface states above.
