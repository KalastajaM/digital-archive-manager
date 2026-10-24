# Learned filing rules, proven before use

Status: design, 2026-10-23. The Trays editor is a separate design, after this one.

## Why

Filing a document by hand is three jobs each time: read it to see what it is, give it a
name, and find its folder. Most documents come from the same senders again and again,
and filing rules could do all three for those. The owner has written none: a rule
written up front is guesswork (which words, which folder), and an unreliable rule would
be worse than none, because every suggestion would have to be checked anyway.

So dam learns rules from how the owner files, and proves each rule against the
owner's own past filings before it is used. Trust comes from evidence shown up front,
not from watching a rule for weeks.

## Goals

- After a manual filing that no rule covered, offer to make a rule from it, drafted from
  what the owner just did.
- Before a new or edited rule is used, replay it against the documents already filed
  and show the result: how many it matches, how many would land exactly where they are
  with the same name, and each one that would not, side by side.
- Keep a track record per rule (suggested how often, changed by the owner how often) and
  flag a rule whose suggestions are being corrected.
- Settings → Filing rules: every rule in the order it applies, with its record; edit,
  replay, test against an inbox file ("which rule files this, and why"), delete.

## Non-goals

- Filing without a confirm. Every filing is still confirmed by the owner (CONTRIBUTING
  safety rules). Rules only fill in the Inbox form, as today.
- AI. Drafting, replay and the record are plain code over the index.
- A general rule language. The rule format stays as it is (`when`: `text_contains`,
  `filename_matches`, `folder_is`; `then`: `folder`, `name`, `tags`, `tray`, `payee`).
- Trays (their own design).

## Anti-goals (a failure even if it works)

- A rule that suggests a wrong folder or name without the owner having seen evidence for
  it. The replay is not optional.
- Nagging: an offer after every filing, or again for a sender the owner said no to.
- Breaking rules written by hand: their files and comments are left as they are unless
  the owner edits those rules in the app.

## Constraints

- Rules live in `<data dir>/config/rules/*.yaml`, loaded in name order (`load_rules` in
  `backend/src/dam/rules/model.py`). For the folder and name the first matching rule
  wins; tags from every match are merged (`suggest` in `rules/engine.py`). A bad file is
  reported and skipped; a duplicate id skips the later file.
- Templates use `{doc_date:%Y%m%d}`, `{year}` and `{stem}` (`render`, `check_template`).
  A rule's name is not used when the file's own name already starts with a date.
- Rules are configuration, not archive content: the operation layer and the journal do
  not apply to saving them. Writes go through `dam.codes.configfile.write_config_file`
  (or the same pattern: backup of the old file, read back before replacing), as the
  filing codes table does.
- The index keeps each file's full text (`file_text`) and an FTS table
  (`file_fts`: name, path, text), so a replay needs no file reads.
- `filename_matches` regexes run with a timeout (`_REGEX_TIMEOUT`); the replay must keep
  that, and stop early on a time budget for a very large archive.
- Cross-platform; text IO with explicit `encoding="utf-8"`; a migration for any new
  table (next free number after the current head).

## How it works

### 1. The offer (after a manual filing)

When a filing from the single-document Inbox form completes and its folder or name is
**not what the rules suggested** (no rule gave one, or the owner changed the rule's
value), dam offers: "File documents like this automatically next time?" with **Make a
rule…** and **Not for these** (designer's call: an action on the filed-toast, like Undo,
so it never blocks the next document). When the value the owner changed came from a
learned rule, the offer is **Update rule <id>…** instead, opening that rule with the
owner's values filled in. No offer for multi-document batches, File N marked, or
filings by a filing code (the code already decides), nor when the owner turned the
offer off in Settings → Filing rules.

The server knows where a filing came from because the request body says so: a new
optional field on `POST /api/inbox/file`'s body, `via`: `"form"` (the single-document
card, `ReviewCard.tsx`), `"batch"` (`BatchCard.tsx`) or `"codes"` (`MarkedBatch.tsx`),
default `"form"` (designer's call; `origin` is taken: it is the journal's ui/cli/workflow
origin). The server decides whether to offer and returns the offer, with the draft, in
the filing result, so the client only shows it (after the API change run
`npm run gen:api`).

**Not for these** stores the drafted match words for that document (see below) in a
small "declined" list (with the offer switch, in `<data dir>/rules-state.json`, like
`ai-state.json`); a later document whose drafted words are the same set gets no
offer (designer's call). The list can be cleared in Settings.

### 2. The draft

**Make a rule…** opens a sheet with a rule drafted from the filing just done:

- **Match** (`when.text_contains`): in today's format a rule matches when **any one** of
  its words is in the document's text (`_matches` in `rules/engine.py`: a substring of
  the folded text; the file name is not searched). So the draft proposes words as
  chips but ticks **one** by default: the most distinctive word near the top of the
  text (usually the sender), found the way `rules/similar.py` does (`_tokens`), from the
  **text only**, since a word only in the file name would never match a new document
  (designer's call). Words that also appear in most already-filed documents are not
  offered, so "invoice" is never proposed (builder's call: the threshold). Ticking more
  words widens the rule ("any of these"), and the sheet says so; the replay shows what
  that costs. Requiring all words would need a new key in the rule format and is not
  part of this design.
- **Where** (`when.folder_is`): the inbox, as the example rules do, so the rule applies
  to new documents only.
- **Folder** (`then.folder`): the folder the owner chose, with a four-digit year that
  equals the document's date year replaced by `{year}` (`2026` → `{year}`), shown as the
  pattern and as what it gives for this document.
- **Name** (`then.name`): the name the owner gave, with its date prefix replaced by
  `{doc_date:%Y%m%d}` and, when the rest equals the original file's stem, that part by
  `{stem}`; shown the same way.
- **Tags, tray, payee**: as the owner set them on this filing, each with a box to leave
  it out.
- **Id**: from the first match word (`fortum`), unique among the rules.

The draft never contains anything the owner did not do or see; every field can be
edited before saving.

### 3. The proof (replay)

Before a new or changed rule can be saved, dam replays it (the sheet shows the result
as soon as the draft is ready, and again after each edit, debounced):

- **Population**: every indexed file outside the special folders (inbox, Ongoing,
  Important, To Delete). Folders excluded from AI are included: that exclusion is about
  what is sent to AI, and the replay sends nothing (designer's call).
- **Match**: exactly as live filing matches (`_matches`, the same folded text and the
  same regex timeout), with `folder_is` ignored (filed files are no longer in the inbox),
  so a rule that passes the replay fires the same way on a new document.
- **Compare**: for each match, where the rule would put it (folder rendered with the
  file's document date, from its date prefix or the indexed date) and what it would
  name it, against where it is and what it is called now. A name pattern using
  `{stem}` is compared on the part after the date prefix, since the original stem of a
  filed file is not known (builder's call, stated in the result).
- **Result**: "Matches 14 documents you filed before: 12 would land exactly where they
  are. 2 would land somewhere else:" and those, each as current location → rule's
  location. Also "It also catches 1 document in the inbox now." Zero past matches is
  shown plainly ("Not tested yet: no filed document matches it"), and the rule can still
  be saved.
- **Order matters**: the replay also says when an earlier rule (by load order) already
  wins for some of the matches, so this rule would not be used for them.

Saving a rule whose replay shows mismatches asks first ("2 documents would land
somewhere else. Save anyway?"). The replay is read-only.

### 4. Where learned rules are written

Rules made or edited in the app are written to `config/rules/learned.yaml` (one file,
a YAML list, created when first needed). `load_rules` loads it **first**, before the
name-ordered files, so a learned rule (about one sender) wins over broad ones such as
the shipped `generic-invoice`, which matches any document with "invoice" or "receipt"
(designer's call; the guide and the example file's header say so). The replay still
reports when another rule would win for some matches. Once this file exists, choosing a
new folder layout no longer replaces the example rules (`seedable()` in `layouts.py`
sees a rules file of the owner's), which is right: the owner has rules of their own. Editing a rule that lives
in another file rewrites that file, so comments in it are lost; the editor says so and
keeps a backup, like the filing codes. After a save the app reloads rules
(`App.reload_rules`).

### 5. The track record

A new table (migration) records, per completed filing from the Inbox form, which rule
gave the folder, the name, the tray, and whether the owner kept each value unchanged.
The server can compute this itself: at filing time it recomputes the suggestion for the
file (`suggest`, as the Inbox does) and compares it with the request, so the client does
not change. Undoing a filing removes its record (builder's call: or marks it undone).

Per rule this gives "suggested 9 times, changed 0" and the last time it was used. A rule
whose folder or name was changed in two of its last five suggestions (designer's call)
is flagged in Settings and in its Inbox suggestion chip ("this rule was corrected
recently"), with a link to replay and edit it.

### 6. Settings → Filing rules

A section under "This archive", in the Settings layout of
`2026-10-23-settings-screen-design.md`: one line per rule in load order (its id, the
match words, where it files, its record, a flag), opening into an editor like a filing
code's (match words, folder, name, tags, tray, payee, with the replay below). The
editor also shows **More conditions**: the file-name pattern (`filename_matches`) and
the folder the file must be in (`folder_is`), editable and always kept when the file is
rewritten, so hand-written rules survive an edit (designer's call). Also:

- **Test a document**: pick an inbox file; dam shows which rules match it, which one
  wins for each field and why (the matched word, the regex), using `suggest`'s sources.
- **New rule** (blank, with the replay), **Delete** (asks first), and order: learned
  rules can move up or down within `learned.yaml`; rules in other files show their
  file and are reordered there (builder's call whether to allow moving between files).
- The files that could not be loaded (`rule_errors`) at the top, as the codes' problems.
- The offer switch (on by default) and the declined list (clear).

## What is decided, and by whom

- Learn from filings rather than write rules up front; proof against past filings before
  use; nothing filed without a confirm: the owner (2026-10-23).
- Everything marked "designer's call" above: the designer, to be checked by the owner.
- Exact layout, API shapes, the table's columns, thresholds marked "builder's call", and
  the replay's time budget: the builder.
