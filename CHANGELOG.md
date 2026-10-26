# Changelog

All notable changes are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Move a folder in Browse.** Drag a folder row onto a folder, the other pane or a
  breadcrumb, or use **Move to…** in its panel. On the same disk it is a rename. To a
  folder on another disk, dam copies and checks every file in the background, and only
  when all are copied moves the original folder to the To Delete of its own archive
  folder. **Stop** leaves the original whole; moving the folder again finishes the job
  without duplicates, and if the original changed meanwhile nothing goes to To Delete.
  Links inside the folder are not copied (they go to To Delete with it), and the preview
  warns about links that would point to nothing. Collections and notes on the folder
  follow it, and **Undo** puts everything back (after a Stop and a second move, undo the
  second move first). A folder holding two names that differ only in case or accents is
  not moved to another disk until one is renamed. Breadcrumbs now also take files.
- **Compare and resolve same-name files in Duplicates.** Files with the same name but
  other content (versions of a document, or a PDF saved twice) now open side by side in
  one window with **Compare side by side**, with **Keep this one** under each. They get
  the same choices as identical copies (leave, To Delete, or replace with a link), but
  each starts as leave and the preview says they are not copies. This replaces the old
  link, which only opened the two folders in Browse.
- **Quick Look in Duplicates.** The eye button on each copy, and on each same-name
  file, shows it in Quick Look without leaving Maintenance; ← and → move through the
  other files listed.
- **Give an inbox file a filing code in the app**, as if it had a sticker. Press **c** in
  the Inbox (or click the QR button), pick a code, and the selected files fill in from it
  and join File N marked. Nothing is written into the files; × on the form or Undo takes
  the code off. A code you assign wins over a folder or sticker code on the same file.
- **Swap the panes in Browse.** With two panes, the button next to **Two panes** swaps
  them: each pane keeps its folder, filter, view, sort, history and selection on the
  other side.
- **Quick Look from a file row.** With two panes, hovering a file shows an eye button at
  the right end of its row; it opens Quick Look on that file.
- **Diagrams in Help.** Under **How dam works**, Help now shows how a document goes from
  paper to its folder, where a filed document ends up, when each tray reminds you, how
  every change is previewed and can be undone, and what stays on your computer. They
  follow the Light and Dark appearance.
- **Print a document from its preview.** The printer button next to the zoom buttons (in
  the file view, Quick Look and the viewer window) prints a PDF, every page of it, or an
  image through the browser's print dialog.
- **Snapshots** (Settings, Snapshots): take a snapshot of an archive's database and
  settings while dam runs, and restore one. Before a restore dam asks whether to take a
  snapshot of the current state first. **Export** saves a snapshot through the browser so
  you can keep it on another disk or in the cloud, and **Import…** adds one back (checked
  in full first), also on another computer, where the archive folder may have another
  path: after you confirm, that snapshot is restored with this archive's own folders. The
  replaced settings are moved aside, never deleted, and a snapshot from an older version
  of dam is updated when it is restored. Your documents are not part of a snapshot.
- **One archive can now span several folders.** In Settings, **Archive folders**, **Add
  folder** joins a further folder (for example on an external disk or a cloud drive) under
  a label you choose. Browse, search, tags, collections and Maintenance see one combined
  archive, and dam refuses a folder that overlaps another folder of any archive. **Detach**
  takes a folder out without touching the disk (its notes and tags are kept, and **Attach
  again** brings them back). Ticking **Also forget** (or **Forget** on a detached folder)
  also drops its files' tags, notes and collection places and removes the folder from the
  list, so its label can be used again.
  - **An unplugged disk keeps its files in the index.** A folder that is not connected shows
    "Not connected" in Browse and the file view, its files stay in search and collections
    with the same mark (find them with `is:disconnected`), and nothing is marked missing. dam checks about every
    30 seconds and picks the folder up again by itself. Changes to an unplugged folder are
    refused, and links in `##. Ongoing` and `##. Important` that lead into it are left alone.
  - **Each folder has its own `##. To Delete`**, because a file cannot be renamed onto
    another disk.
  - **Moving files to a folder on another disk** (drag, Move to…, Restore) copies each file,
    checks the copy against the original (size and content), and only then moves the
    original to the To Delete of its own folder: nothing is deleted. Tags, notes,
    collections, tray items and locks follow the file. The preview says how many files are
    copied, how big they are and how many are in the cloud only (downloaded first). The
    move runs in the background with a progress dialog you can hide; **Stop** finishes the
    file in hand, so every file is either moved or untouched. **Undo** puts the originals
    back and moves the copies to To Delete. Whole folders cannot be moved yet. The amount
    copied moves along within a large file too, and a failed move says why it failed. A
    name too long for the temporary copy name is refused in the preview, not half way.
    Maintenance has a new check, **Unfinished copies**, that lists the `.dam-copy-` files a
    failed or stopped move left, for you to remove.
  - **Change label** (Settings, Archive folders) renames an extra folder's label. Every
    path dam keeps under it changes with it: the index, the history (earlier changes can
    still be undone), protected folders, folders kept from AI and the `folder` values in
    your rules and filing codes, which are edited in place so your comments stay. Nothing on the disk
    changes, and a snapshot is taken first.
  - Maintenance marks links into an unplugged or detached folder ("Folder not connected",
    "Folder detached") and lists a folder in the main folder that has the same name as an
    archive folder.
  - **Manage archives** lists each archive's extra folders under its archive folder, each
    with its own **Show in Finder** (or Explorer); a detached one is marked "(detached)".
- **Maintenance screen** (sidebar, Archive, next to Activity) with checks you start
  yourself; nothing runs by itself or in the background, each shows its progress, can be
  stopped, and ends in a list you act on through the usual preview and Undo.
  - **Duplicates:** finds files with the same content. It says first how many files it will
    read and how big they are (with a warning that files kept online-only in Google Drive
    are downloaded), reads only files that share a size with another, and does not read a
    file again once it has been read. In each group you pick the copy to keep (the
    suggestion is a numbered folder before the Inbox, then the oldest) and, for each other
    copy, whether to leave it, move it to To Delete, or replace it with a link to the kept
    copy (icons next to the copy; To Delete to begin with). **Apply** does a group, or all
    ticked groups at once. One preview, one Undo (which removes the links and brings the
    copies back). Tags, collections, star, notes, checklist entries, tray items and From and
    For of the removed copies can be added to the kept one (ticked by default, listed in
    the preview, nothing overwritten). A copy marked Important or locked is never removed.
    Files with the same name but different content are listed as probably versions, for
    review only, with Show in Browse and a side-by-side compare.
  - **Empty folders**, **broken links**, **collection members and tray files that are gone
    or in To Delete**, **file names without the `YYYYMMDD_` prefix** (with a suggested name
    and the normal previewed rename) and **files waiting in To Delete** longer than a number
    of days you choose. dam still never empties To Delete. The empty-folder check leaves
    out the folders the archive is set up with, such as the filing code folders in
    `##. Organize`.
  - Duplicates show each copy's folder with its details under it, and its name only where
    it differs.
  - Collections and trays show where a gone file was last seen instead of an internal id,
    say what each entry means, and offer **Take out** for a gone file in a collection.
  - **Ignore** an entry (a duplicate group, a name used by different files, an empty
    folder, a broken link, a collection or tray entry, a file name) to leave it out of
    later results. Each card lists what it ignores, with **Stop ignoring**. An ignored
    duplicate group comes back when a new copy turns up.
  - Each check's card folds to one line (Collapse all and Expand all in the toolbar,
    remembered in this browser). The reset icon at the top right of each card forgets that
    check's result, and **Reset all** in the toolbar every result, without changing the
    archive.
- **Move, Link or Copy when you drop files on a folder in Browse.** The confirm that
  appears after a drop now has the three ways side by side: **Move** (still the default),
  **Link** (a shortcut in that folder that opens the file, which stays where it is) and
  **Copy** (marked "not recommended: makes a duplicate"). Holding Option (Alt) while
  dropping starts with Copy, as in Finder. Each one is previewed and has Undo: Undo of a
  Link removes the shortcut, Undo of a Copy moves the copy to To Delete. Dropping a file on
  its own folder says "Already in this folder" (Copy works with Option and gets a number).
  On Windows without Developer Mode, Link is off with a message.
- **Rows in `##. Ongoing`, `##. Important` and `##. To Delete` can be dragged.** Dragging an
  Ongoing row moves the real file (the confirm says where it is now and where it goes) and
  its collections keep it; Link and Copy use the original. An Important row can be linked
  or copied, but not moved ("This file is marked Important; unmark it first"). A row from
  To Delete dropped on a folder restores it there, with a preview and Undo.
- **Dropping files on a collection's folder in `##. Ongoing` adds them to that collection**
  (with Undo). Dropping on `##. Ongoing` itself says to drop on a collection's folder.
- **A refused drop now says why.** While you drag, a folder or pane that cannot take the
  files shows the reason on itself, and dropping there anyway shows it as a message
  instead of doing nothing. This also covers a folder dragged onto a folder and a drop on
  search results.

- **Restore from To Delete.** Select one or several files in `##. To Delete` and choose
  **Restore** in the toolbar (or the two buttons in the file's panel): **Restore to where
  it was** puts them back at the path they were marked at, **Restore to Inbox** puts
  them in the inbox. A folder marked for deletion can be restored too, from its
  right-click menu or its panel. It is a normal batch: the preview lists what happens,
  including a folder that is gone and is made again and a name that is taken (the file
  gets a number), you confirm, and Activity shows "Restored 3 files from To Delete" with
  Undo, which puts them back in To Delete.

### Changed

- **Faster indexing and folder moves on large archives.** Updating the search index for
  one file no longer reads the whole index, so the first indexing of a large archive
  and moving a whole folder are much faster (a folder of 300 files in an archive of
  50,000 now takes well under a second instead of about 16 seconds). The status check
  for interrupted changes is cheaper too. The first start after the update maps the
  existing search index once, which takes about a second for 50,000 files.
- **Filing and moves no longer rescan the whole archive.** Filing a document from the
  inbox into another folder, or moving files between folders or disks, used to make the
  folder watcher scan every archive folder, including slow USB and network disks, and
  other changes waited while it ran. The watcher now looks only at the files and folders
  that changed, and skips the changes dam made and indexed itself. Changes made outside
  dam at the same time are still picked up.
- **Inbox and Maintenance tidied.** The Inbox review card no longer repeats the inbox
  folder's name under the file's name; it names only a folder inside the inbox (such
  as a code's folder). In Maintenance, **Show in Browse** is an icon button (the
  Browse icon, with a tooltip), and a group's **Apply…** button lines up with the text
  beside it.
- **The Inbox list shows each file's own name.** The name dam suggests is on the line
  under it, marked "Suggested:", so a file no longer looks renamed before it is filed.
- **Planned changes** (the Inbox's Preview) has a border, an × to close it and its own
  **File it** button.
- **Messages with buttons** (such as "Filed as …" with Undo and Make a rule…) put the
  text on top, at full width, and the buttons under it, so a long path stays readable.
- **Snapshots** have tooltips on Import, Export and Restore (a snapshot that cannot be
  restored says why), and the help says that Export only copies the file, so copying it
  from the snapshots folder yourself works too.
- **Previews list a new folder structure as one step.** When a change needs several
  missing folders, one inside the other (such as the same folder path in To Delete), the
  preview shows one "New folders" line with the deepest folder and how many are made,
  instead of a step per folder.
- **Trays and collections:** the list buttons in the header (Add file, Open and Done; the
  collection's folder and share buttons) sit at the right edge of the list column, over
  the list they act on, instead of right after the title.
- **Undo may now remove a shortcut dam made anywhere in the archive**, not only in
  `##. Ongoing` and `##. Important`. It applies to the shortcut a Link drop made, only
  while it is still a shortcut pointing at the same file. It never removes a regular
  file, a folder or a shortcut you made yourself.
- Dropping files on `##. To Delete` now says "use Mark for deletion", and dropping on
  `##. Important` is refused.

- Files in `##. To Delete` are read-only. Starring, marking Important, putting in a tray,
  adding to a collection, tags, From and For, the summary and the notes are all off for
  them in Browse, with "Marked for deletion: restore it first" as the reason, and the app
  refuses the same changes if they are asked for another way. Their tags, collections,
  notes and tray items are kept, so a restored file comes back with them.
- The search filter `is:locked` now finds only the files you locked yourself. Important
  files are always locked, but you find them with `is:important`.
- The Browse header no longer spans the whole window, and the trays have the same header.
  The left part is for the list: in Browse the
  **Folder / Archive** switch, the search and the **New folder** and two-panes buttons, in a tray its name, count, **Add file** and **Open / Done**. The right part,
  over the file, is one group of icon buttons for the file actions, the same in both and
  in the same order: **Put in tray** (a menu of the trays, **Move to tray** inside a
  tray), **Remove from tray** (in a tray), **Back to inbox** (in a tray it moves the shown file; the item stays), **Move to…**, **From…**,
  **For…**, **Ask AI**, **Star**, **Important**, **Restore** (files in To Delete) and
  **Move to To Delete**. In Browse they act on the selected files, **Star** and
  **Important** also for a single file. The preview's toolbar keeps only the viewing
  tools (zoom, select box, open, show in Finder, open in window, Quick Look), and the
  Browse file panel no longer repeats **Put in tray** and **Back to inbox**. On a narrow
  window the list part takes the row and the file actions follow at the right.
- A collection (your own, **Important** and **Starred**) now has the same header: its
  name, subtitle and list buttons (**New group**, the folder button, **Export…**, **⋯**)
  at the left, and over the selected file one group of icon buttons, in Browse's order:
  **Put in tray**, **Remove from collection**, **Back to inbox**, **Move to…**, **From…**,
  **For…**, **Ask AI**, **Star**, **Important**, **Restore** (a file in To Delete) and
  **Move to To Delete**. Moves and Restore show their preview first and have Undo, as in
  Browse, and a moved file stays in the collection. **Remove from collection** sits where
  **Remove from tray** does in a tray. The file panel
  no longer repeats these buttons, and its toolbar keeps only the viewing tools. The group
  and **Show in folder** stay in the file panel.
- In a tray's header the name with its count, **Add file** and **Open / Done** now sit on
  one row at the left, level with the file buttons, instead of **Add file** and the
  switch on a second row at the right. They wrap only in a narrow window.
- Collections are now a chip field like tags, everywhere a file's collections are set:
  the file view in Browse, a collection and a tray, the Inbox card and batch ("Also add
  to collection"), the rule sheet and the filing codes. The collections show as chips
  (the x takes one out), matching collections are suggested as you type, and a name that
  is no collection yet is offered as **Create collection "name"**. The **...** button
  still opens the collection tree. On a file the change applies at once, with Undo in
  the toast (adding now has an Undo too); in the Inbox and in rules it is kept until
  filing or saving. This replaces the **Add to collection...** button and its box.
- Tag fields have a **...** button too. It lists every tag by group with its number of
  files, and a click adds the tag.

- The file view has one order in Browse, in a collection and in a tray: name and folder
  with the lock, tags, the collections the file is in, the summary, what is specific to
  that view (a tray's fields and Mark done, a collection's group and Remove, Browse's
  Put in tray), the preview, then notes, checklist and history. Tags and the summary used
  to be below the preview in Browse and above it in trays.

### Added

- Search filters. Beside words, the search box in Browse (and Today's Search card) takes
  `name:` (file names only, with `*` and `?`), `in:` (a folder and below), `tag:`,
  `collection:` (with the collections inside it), `from:` and `for:`, `type:` (an
  extension or a group such as `image`, `doc`, `sheet`), `date:`, `before:` and `after:`
  (a year, month or day), `tray:` and `is:` (`starred`, `important`, `locked`, `todo`,
  `note`, `summary`). A `-` in front leaves out what matches (`-tag:paid`), values with
  spaces go in quotes, and filters combine with each other and with words. Typing the
  start of a name offers it (`col` gives `collection:`) and then its values; each finished
  filter becomes a chip in the row under the toolbar. A **?** next to the box lists every
  filter with an example you can click, and the new Searching section of the guide
  explains them. A search with only filters lists the matching files.
- Search results in Browse follow the **Folders / Files** switch. Folders groups the
  results under their folders (a header with the path and the number of matches, in the
  order of the folder tree, each foldable; clicking the folder name opens it and ends the
  search). Files stays the flat list.
- Tag filters now sit in their own row under the pane's toolbar instead of inside the
  search box, with **+ Tag** to add another tag from suggestions. With two or more tags an
  **All / Any** switch chooses between files that have every tag (the default) and files
  that have at least one. The address keeps `tag_mode=any` for the second case. The whole
  search, words and filters, is in the address as `?q=`, so Back and a copied link bring
  it back (old links with `?tag=` still work).
- A tray item shows the collections its file is in as badges (the x takes the file out)
  and has **Add to collection...**, as Browse does.
- Tray list rows show what an item has as small icons before the date: a larger pencil
  for a note, a checklist icon with the number of open to-dos (hover for "2 of 5 to-dos
  open"), and a sparkle for an AI summary or a text icon for a summary you wrote.
- Files on an item: each file tab has a small **×** (on hover or focus) that takes the
  file off the item, with an Undo that puts it back in the same place. It replaces the
  icon in the action row. **Add another file…** now searches the whole archive as you type
  (with each file's path) or lets you browse folders, with arrow keys and Enter, and shows
  files that are already on the item instead of adding them twice.
- Drag an item onto another in a tray list to merge them: after a question, its files,
  notes and checklist are added to the other item and it is removed. Undo restores both.
  You can also drag a file from Browse or the search results onto an item in the list or
  onto the open item to attach it. No file is moved or renamed.
- A rule can now add the document to collections. The rule sheet has an **Add to
  collection** field under Folder, with the same picker as the Inbox ("…" opens the
  collections as a tree). When the rule matches, the Inbox card starts with those
  collections in "Also add to collection", like tags; you can change them before
  filing. In a rule file this is `then.collections`; files without it load as before.
  The rule test does not compare collections.
- The Folder field of the rule sheet has a "…" button that opens the folder browser and
  puts the path you pick in the field. Patterns such as `{person}` and `{year}` can still
  be typed.
- You can change the order of your collections. Drag a collection onto another one in the
  sidebar or on the Collections page: the top third of a row puts it before, the bottom
  third after (a line shows where), the middle third inside it (the row is highlighted).
  Dropping beside a row of another level also moves it to that level, so a nested
  collection can be dragged back out; dropping on the Collections heading moves it to the
  top level. Alt+Up, Alt+Down and Alt+Left, or Move up, Move down and Move out one level
  in the right-click menu or the ... menu, do the same from the keyboard. Important and
  Starred always stay on top. Collections you had keep their A to Z order until you change
  it; new ones go last.

- Clicking a file name in the Starred card on Today opens Browse in the folder the file
  sits in, with the file selected and previewed. On a collection's own page, Starred and
  Important included, a click selects the file there, and Show in folder in the file's
  panel opens it in Browse.

- A lock on files, a safety catch against slips. A locked file can still be viewed, tagged
  and described, but it cannot be renamed, moved (also by drag and drop, Move to… or Back
  to inbox), filed from the Inbox or moved to To Delete. Files marked Important are always
  locked; you can lock any other file with **Lock** next to its name. **Unlock** asks
  **For now** or **For good**. An Important file can only be unlocked for now. Unlocking
  for now lasts until you leave the file (select another, close the panel, go to another
  page or reload), and the details say "Unlocked until you leave this file" with **Lock
  again**. A lock icon shows on locked files in Browse, the Inbox, trays and collections.
  A change that includes a locked file is refused as a whole, naming the file. dam itself
  enforces the lock, so no screen or script can get around it, and no unlock survives a
  restart.
- Search by tag. In Browse, type `tag:medical` (or `tag:"tax return"`) and a space, or pick
  a tag from the suggestions, and it becomes a chip you can remove. Files must have every
  chip, and words work beside them. Today has a new **Search** card that opens Browse with
  what you typed.
- A **Tags** screen with every tag and its file count, a filter box, and menus to create,
  rename, merge, delete and pin tags and to move them into groups (one level, for
  arranging only). Merging and deleting say what happens first, and every change has Undo.
- A **Tags** section in the sidebar with your pinned tags first, then the tags used most
  lately, eight at most; it folds like the other sections.

- The rule test now says on its own line whether the rule matches the document it is made
  from ("This rule matches this document", or "does not match" with the reason, such as
  "no word found in the area" or "the picture in the area scores 0.71, needs 0.85"). The
  document is no longer counted among the documents you filed before or the inbox
  documents, and is left out of the lists and scores. The line updates as you edit the
  rule. Rules opened from Settings have no such line.

- Each area of a rule now says how its words match: **Starts a word**, **Whole word** or
  **Anywhere**. New areas start on Starts a word, so "kela" finds Kela, Kelan and Kelalta
  and "vakuutus" finds Vakuutuskirja, but neither finds a word that only contains it, such
  as Henkivakuutus. Whole word finds "Kela" and not "Kelan". Rules you already have keep
  matching anywhere until you change it. Changing the choice tests the rule again.
- The rule sheet has a **For** row. It says who the address area found on the document the
  rule is made from, lets you pick **Anyone** or **Only for** one of your people, and has
  **Use the person in the folder**, which puts `{person}` in the Folder field and shows
  where this letter would go.
- A box you draw that holds no text now switches to Picture by itself. You can switch it
  back to Words. A box over blank paper, with neither text nor a picture, says so instead
  of becoming a picture area.

- Every document in the test result of a rule is a button that opens it in the preview with
  the rule's areas drawn on its first page, and for a picture area the place where it fits best
  and its score. In any preview with the box tool, picture rules that did not match are
  drawn dashed with the score they got on that document, or the reason there is none, so you
  can find out why a rule found nothing.
- When a test has documents whose page 1 is not read yet, **Read page 1 of these N now**
  reads exactly those first, at full speed (still one at a time, and each read still has its
  time limit). The test picks them up as they are read.
- Page 1 of PDFs that have a text layer is read much faster than the indexer's 30 files a
  minute (300 a minute unless you choose another speed in Settings → Indexing or on the
  Index sheet, **Page 1 reading speed**): it needs no OCR. Scans, photos and any read that
  is slow, such as a Google Drive file that has to be downloaded first, keep the indexer's
  pace. The Index sheet's estimate of the time left now adds the two ("about 18 min left
  (5 000 PDFs with text at 300 a minute, 30 scans and photos at 30 a minute)"). Settings has
  a new section, Indexing, with this speed and the switch for reading older documents.
- The test of a rule looks at the likely documents first, so real matches show up early
  instead of in folder order: the documents you set as from the rule's sender, then the
  documents in the same folder as the one you drew the areas on, then (for a picture
  area) the rest by how much their first page looks like the picture, using tiny
  grayscale thumbnails of the page 1 pictures that dam keeps in one file in the cache
  folder (`page1-thumbs.npz`; it can be rebuilt any time). The order only changes when
  things show up: the counts are the same as in any other order. On a test archive of
  11 000 files, the first five matches of a rule with a word area and a picture came after
  205 documents instead of 8 243. "Test the rest" goes on in the same order.
- The test of a rule runs in the background and fills in as it goes, instead of one
  request that gives up after five seconds. The sheet says "Checked 1 240 of 10 875
  documents…" with a **Stop** button, shows the matches found so far, and goes on until
  every document is looked at. It ends when you stop it, change the rule or close the
  sheet. When all documents are looked at and some still wait for page 1 to be read, it
  says so and looks at them again as they are read. The test only reads the index and the
  cache; it changes nothing. (The old **Test the rest** button is gone: the test no longer
  needs it.)
- The Index sheet shows how far reading page 1 has come, how many documents wait because
  page 1 cannot be read now and why, the switch for reading older documents in the
  background, and an estimate of the time left. The status line at the foot of the sidebar
  says "page 1 read 1 240 of 10 875" until it is complete.
- Rules can recognise a picture, such as a logo that has no text. In Draw a box, choose
  **Match the picture in this area**; the rule sheet shows the picture and a **Match
  needed** slider, and the test lists how well the documents it matched and the ones it
  did not matched the picture, so you can see how far apart they are. It finds the logo
  on a rescan that is shifted, a little bigger or smaller, lighter or darker, noisy or
  slightly crooked. Page 1 pictures are kept as small grayscale files in the cache
  folder, never in the archive; the picture of an area is kept with your rules, in
  `config/rules/areas`. Moving a picture area cuts it again from the document you moved
  it on. Settings lists picture files that no rule uses any more, and **Move N unused
  pictures to To Delete** puts them in `##. To Delete` as `dam rule picture <name>.png`,
  after a preview, with Undo (it puts them back, and refuses if the name is taken again).
  Only pictures no rule uses can be moved. If your rules folder and your archive are on
  different disks, dam copies each picture into To Delete, checks the copy, and only then
  removes its own copy from the rules folder (these are dam's own files, not your
  documents); if anything fails, both stay. Undo across disks copies the picture back and
  leaves the one in To Delete. dam never deletes anything else. The small page 1
  pictures in the cache folder are dam's own temporary files: once after the first scan at
  startup dam removes the ones that no indexed file matches any more. A picture area must
  be at least 1% of the page wide and high; smaller ones are refused.
- dam now keeps where each word of page 1 sits, not only each line. A box drawn tightly
  around one word lists only that word, and a rule word only counts when it is among the
  words inside the box (a name of two words matches when both are inside). Documents read
  before this keep matching by whole lines until their content changes; dam does not
  re-read them on its own. For scans read by Apple Vision the position of a word inside a
  line is an estimate.
- Draw a box now works in every preview of a PDF or image: Quick Look, the document
  window, a collection's file panel, a link's target and the item screen, as well as the
  Inbox and Browse.
- A rule you make from boxes has an optional **From (sender)** field in the rule sheet,
  filled in from the document's own From when it has one.
- A rule can need several areas of page 1, such as "Pohjola in the letterhead" and
  "vakuutuskirja in the title", so each kind of letter from a sender files to its own
  place. In Draw a box, every box you draw is kept and numbered and you draw the next;
  the rule sheet shows each area as its own group of words, and a rule made from boxes is
  saved directly above the learned rule that matches the document already.
- You can see why a document matched: **Show areas** in the preview draws the areas of
  every rule that matched, the lines that matched in them, the address area and the line
  where the person was found. Test a document draws the areas of rules that did not
  match as dashed outlines with the reason.
- You can change an area after it is saved: select it on page 1, drag it or its handles,
  and the rule sheet opens with the test showing how the rule did before and after. The
  address area works the same way, and Settings → Filing rules shows a rule's areas on a
  sample page where they can be dragged too.
- Rules that match by where text sits on page 1: draw a box on page 1 of a document in
  the preview (Draw a box) and make a rule from it, such as "Pohjola in the letterhead
  means a letter from Pohjola". A word only counts when it is inside the area, so a
  bill that merely mentions Pohjola no longer matches. The replay shows how many past
  documents could not be checked yet, and reads their page 1 first.
- Who a letter is for: list the people in your household in Settings → Filing rules,
  and dam finds them in the address area of page 1. Use `{person}` in a rule's folder or
  name to file per person. A letter to two people asks "For whom?". The address area
  can be drawn once for all letters, or per sender for letters with an unusual layout.
- From and For: say by hand who a document is from and who it is for, on the Inbox
  card, for an Inbox batch, or for a selection in Browse. What you set always wins over
  what dam detects, and a sender rule's replay shows how many of the documents you set
  as from that sender it finds, and which it misses.
- dam now keeps the position of the text on page 1 when it reads a document. Documents
  read before this update get theirs in the background, inbox first; Settings →
  Filing rules shows the progress and can pause it. Nothing in the archive changes.
- Learned filing rules: after you file a document by hand, dam can offer to make a rule
  from it (**Make a rule…**, or **Update rule** for a rule made in the app). Before you
  save, it replays the rule against the documents you filed before and shows how many
  would land exactly where they are and which would not. Each rule keeps a record of how
  often its suggestion was kept or changed, and one corrected in 2 of its last 5 filings
  is flagged. Settings → Filing rules lists every rule in the order it applies, lets you
  edit, add, delete and reorder them, test a document from the inbox, and switch the
  offer off. Rules made in the app are kept in `config/rules/learned.yaml`, read before
  the other rule files. Nothing is filed without your confirm.
- Settings → Appearance: choose Light, Dark, or Auto to follow the system setting. It
  applies at once, to every archive, and is remembered by this browser.
- Filing codes: drop files into a code's folder in the inbox (To pay, To action, To
  read, Follow-up, File as suggested, or your own) and file them all at once with File N
  marked. A code is a short letter or number from your own table that fills in the
  tray, folder, name pattern, tags and collections. Five come with dam (A, P, R, F and
  D for "file as suggested": already handled, file it where dam suggests, in no tray).
  Edit them in Settings → Filing codes, with a warning when two codes are easy to
  confuse if you write codes by hand. The table is kept in `config/filing_codes.yaml`;
  comments written in that file by hand are not kept when you save from the app.
- Inbox folders for filing codes: Settings → Filing codes → Create inbox folders makes
  the missing ones in `##. Organize`, after a preview and with Undo. Files directly in a
  code's folder show in the Inbox with that code, and filing rules for the inbox
  (`folder_is: "##. Organize"`) apply to them too. Inbox subfolders that are no code's
  folder are listed in Settings. Existing `##. Organize` subfolders named "To pay",
  "To action", "To read", "Follow-up" or "File as suggested" become inbox folders after
  the update, so the files directly in them now show in the Inbox.
- QR stickers for filing codes: a sticker on page 1 of a scan gives the file its code,
  on every platform. Other QR codes (on invoices, letters) are ignored, and a sticker
  keeps working when you change what its code does. The ★ and ! tick boxes on a sticker
  set Star when filed and Mark Important when filed in the Inbox form; a box that cannot
  be read clearly is pointed out.
- Settings → Print stickers: pick codes and how many of each, a label sheet (Avery
  Zweckform L7651, plain paper with cut lines, or your own sizes in mm, saved) and the
  first label to use, then open the sheet in a new tab and print it at 100 %. Tick
  boxes are on by default, and labels can be left blank to write on. Test print draws
  only the label outlines, to check the fit against a label sheet first.
- File N marked, in the Inbox toolbar and on Today: one row per coded file with the
  codes found (folder, sticker) and exactly what filing will do. Rows that need input,
  whose codes disagree or whose tick box is unclear start unticked and say why; a row
  that needs input is fixed in the form. File files the ticked rows as one batch with
  one Undo. "Reading filing codes…" shows next to it while new scans are still read for
  stickers.
- Browse search results have the Folder, Date and Size columns of the Files view and can
  be sorted by any of them (up to 500 matches); a third click on a column goes back to
  best match first.
- Browse: the search scope sits beside the search box, so you can choose before typing
  whether to search the open folder (with its subfolders) or the whole archive.
- Drop files or folders from Finder (or Explorer) on the Inbox list to copy them into the
  inbox, as Choose files… does. A folder's files land side by side, hidden files are left
  out, and one drop takes at most 100 files.
- Activity → AI lists the excluded folders (never sent to AI) and lets you add or remove
  them, with a folder picker; a folder not in the archive is marked. The change applies
  at once and is saved in settings.yaml. Removing one asks first, since its documents
  can then be sent.
- Help in the sidebar: the user guide inside the app, with its contents alongside, so you
  can jump to any section. It works offline.
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
- Folders join collections from Browse: a selected folder shows its collections and Add
  to collection, and a folder can be dragged onto a collection in the sidebar. A folder
  in a collection brings everything in it, also files put in it later. Folders in
  ##. To Delete, ##. Ongoing and ##. Important cannot be added, and a dragged folder is
  only ever taken by a collection (never moved or put in a tray).
- A × on a file's collection badges (in Browse and in a collection) takes the file out of
  that collection, with Undo (back into its group too). Only where the file is itself a
  member of an open collection; ★ Starred and ! Important keep their toggles.
- A Trays page: the sidebar's Trays caption now lists every tray with its open, overdue
  and total figures, as Collections does, instead of opening the first tray.
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

- **A large file moved to another disk no longer holds up the app.** While a move across
  disks copied a big file (to a USB or network disk, or a cloud-only file being
  downloaded), filing, other moves, undo and the folder watcher waited until that file was
  done, for minutes. They now go on while it is copied. The file is read once instead of
  twice, the progress bar moves from the start of the file, and closing the app ends the
  copy right away instead of after the file was first read through. If the file is
  changed or replaced while it is being copied, the copy is not given its name, the
  original stays where it was, and the unfinished copy is listed in Maintenance as
  before.
- **A `dam` command no longer changes an archive the app has open.** Commands that
  change the archive, its index or its settings (`dam scan`, `index`, `file`, `move`,
  `quarantine`, `add`, `undo`, `recover`, `init`, the stars and Important marks,
  `ongoing sync` and `ai --on`/`--off`) now refuse while the app has that
  archive open, and say on which port: do it in the app, or close the app first. Two
  such commands also wait for each other: the second says which one is running. The app
  likewise refuses to open an archive while such a command runs. Commands that only
  read (`inbox`, `search`, `activity`, dry runs and the listings) still work, and
  `dam archives list` shows an archive a command is busy with.
- **A change still being carried out is left alone.** Undo (from another tab, say) is
  refused until the change has finished, instead of reverting its first files while the
  rest still moved. The Recovery banner no longer shows for a file being moved right now
  (a long copy across disks), so Recover cannot mark it as needing a manual check. A
  snapshot restore, a new label for an archive folder, and detaching or forgetting one
  wait until the change has finished, so its history is not lost.
- **A file that gets its Google Drive id keeps its notes.** When Drive uploaded a file and
  dam picked up its id, the file kept its tags but lost its notes, checklist, collection
  and tray item places, lock, summary and fields. They now stay with it.
- **Forgetting an archive folder** now says how many files it forgets, counting those no
  longer on the disk (a detached folder used to show 0). Files of a main-folder entry with
  the same name as the forgotten label no longer drop out of the index until the next full
  scan, and detaching or forgetting waits at most about 10 seconds for background work to
  stop, instead of up to 30.
- When an extra folder is plugged in again, files dam could not read while it was away are
  read again at once, instead of after a wait of up to an hour.
- Opening a link that leads into a main-folder entry named like an archive folder now says
  why it is refused, instead of showing a path outside the archive.
- On Linux, an extra folder too big to watch (no inotify watches left) is tried again less
  and less often, instead of with a full recursive watch every 30 seconds.
- **A duplicate copied from an Important file can be linked or moved to To Delete.** A
  copy made from a file keeps that file's Google Drive id, so dam took the unlocked copy
  for the locked original and refused with "This file is locked". The lock check now
  goes by the file dam has indexed at that path.

- **A copy of a Google Drive file can be moved again.** Copying a file also copies its
  Drive id, and dam refused to move such a copy ("now has Drive id …, so it is not the
  file indexed there; scan and try again"), which a scan never cleared. This blocked
  Move, filing and the duplicate actions for copies. Such a copy can now be moved, and a
  later scan keeps the Drive id, with its tags and collections, on the original even when
  the copy moves to a place that sorts first, such as To Delete.
- In the sidebar's Tags section, only the tag Browse is filtering by is highlighted.
  Before, every tag looked selected while Browse was open.
- While you edit a rule, the test result still on screen was the one for the rule before
  your last change, with nothing to tell you, so it could show things like "person
  unknown" for a rule that no longer files by person. The sheet now says that the result
  is of the rule before your last change until the new test answers. A rule that names no
  person never lists documents as "person unknown" (covered by a test).
- After dam is updated and restarted, a normal refresh of the browser shows the new
  version. Before, the browser could keep showing the old one until a hard reload.
- Testing a rule with a word area is much faster. It folded the whole text of every
  document twice (once to pick the documents that need page 1, once to test them), one
  character at a time, so a long text cost milliseconds, and a rule that only looks at a
  picture folded it as well. The text is now folded once, only for a rule that has words,
  with a much faster fold that gives exactly the same result; a file that cannot have a
  page 1 is settled without its text; and a picture is blurred only where it is searched.
  On a test archive of 11 000 files (120 MB of text) a rule with a word area went from
  13.5 s to 1.2 s, a plain word rule from 7.5 s to 1.5 s, and a picture rule from 55 s to
  18 s. The log (`dam.log`) now has one line per test with the seconds each step took.
- The test of a picture rule no longer shows documents that did not match as if they were
  results. Documents are listed under **Matched**, and the ones that missed are listed
  under **Close, but not matched** only when the picture was the one thing that failed and
  the score was within 0.15 of what is needed. A document that has the word somewhere
  else on the page but not in your area is never listed with a picture score.
- The **Match needed** slider can now be set to 1.00 (it stopped at 0.99 because the
  value and the link beside it changed its length).
- Pictures are compared at full size with a lighter blur, so a block of small text is no
  longer taken for another block with other words in the same layout (0.89 before, 0.74
  now), and other logos on white score 0.63 or less. A rescan of a logo with a shift, a size
  change, noise, a darker copy or a 2 degree skew still scores 0.92 and over. Small text on
  a scan that is 2 degrees crooked scores about 0.82, so lower the slider a little for it.
- Draw a box no longer lists the lines next to the one you drew around: a box holds
  only the words inside it. A rule still finds its words when a copy is shifted by a few
  millimetres, but a line below no longer counts for the box. The box list and notes now
  sit below the page, so the page stays put while you draw more boxes.
- On Linux, an excluded AI folder typed in another case (`10. financial`) no longer
  shows as "not in the archive"; it is found as the exclusion itself finds it.
- Dropping a folder from Browse on a collection in the sidebar now adds it; the row lit up
  but the browser cancelled the drop.
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

- On the Index page, reading page 1 is a row like the other totals ("Page 1, 8 914 of
  8 914"), with the time left while it runs and what waits. Its switch and speed are no
  longer repeated there; a link opens them in Settings, Indexing.
- The lock button next to a file name shows the file's state: a closed padlock while the
  file is locked (click to unlock), an open one while it is not (click to lock).
- Marking an item done (Mark done, Mark paid, and the "and file" button) now asks in a small
  popover under the button you pressed, instead of in a box further down the page. Enter
  confirms, Esc or a click outside cancels, and the focus goes back to the button.
- The header of a tray list has two rows: the tray name with its count on the first, and
  Add file with the Open / Done switch on the second, so the name and count are no longer
  cut off.
- The rule test explains why documents "could not be judged yet" instead of "Not
  checked yet": they are grouped by reason, and each group says what it means and what
  happens next (page 1 is read in the background, the address area does not say who the
  letter is for, no OCR engine, the file is missing, reading took too long). The line
  above says "2 documents could not be judged yet" rather than "Not tested yet".
- Rule sheet tidying: **Words match** sits next to the word box, the picture score has a
  small reset icon ("Use the default (0.85)") instead of a text link, "The document needs
  a word or the picture in every area" is a ? beside "When a document matches", **Use the
  person in the folder** sits on the Anyone / Only for row with a ? that says how the two
  relate, and areas are called "Words in area 1" and "Picture in area 2" (no more "of page
  1"). The message for a box with nothing in it now has its own line under the box.
- To rename a file, click its name (in Browse, a collection or an item);
  the separate pencil button is gone. The same goes for an item's title and a collection's
  name. The name takes the keyboard focus, so Enter or Space on it works too, and the
  rename is still previewed and can be undone.
- In the box panel, the choice between **Words** and **Picture** for each box is now a
  switch like the rule's "Anyone / Only for": the selected side is filled, so you can see
  which one is on.
- The rule sheet is split into **When a document matches** (the areas, From, For and More
  conditions) and **Then file it like this** (Folder, Name, Tags, Tray, Payee). Payee only
  shows when the chosen tray has a payee field, such as To pay, or when the rule already
  has a payee.
- The item view in the trays is tidier. The title is edited in the header: click it or the
  pencil beside it, press Enter or click away to save, Esc to cancel (an empty title is
  refused). The separate Title field is gone. The icon buttons (move to tray, remove from
  tray, ask AI, take the file off, move to To Delete) now sit at the right end of the same
  row as the date and **Mark done**, and wrap on a narrow window. **Quick Look** is now in
  the toolbar of the file preview, next to zoom and the star, and Space still opens it.
  The file's tags are shown right under the title.
- Summary, Checklist, Notes and History can be folded to their heading and a one-line hint
  (such as "2 of 5 done"). dam remembers each choice in this browser. This applies to
  tray items, collections and documents. The name of a collection is edited the same way
  in its header.

- The rule sheet is easier to read. The "Leave out" boxes are gone: an empty Folder, Name,
  Tags, Tray or Payee is one the rule does not set, and clearing a field never saves an
  empty pattern. The explanations (the From sender, the Folder and Name patterns, and the
  file name pattern, which is a regular expression with examples) are tooltips beside the
  labels. More conditions starts closed and a line beside it says what is set, such as
  "Only in the inbox". The test at the bottom has the heading "Test against your filed
  documents", and when no filed document matches it says so in plain words.
- Draw a box: every box you draw is kept at once, numbered Box 1, Box 2 and so on, and the
  panel "Boxes on page 1" lists each with the words found in it (or "No text found", or
  its picture) and its own x. There is no "Add another box" step any more. Each box has a
  **Words** or **Picture** choice. Esc drops the box you are dragging, then the last box,
  then closes the tool, and the panel's x now reads "Close and drop the boxes".
- "Sender…" in the box panel is now **Make a rule…**, because boxes can pick out the kind
  of letter as well as who it is from. "Address area for this sender" is now "Address area
  for this rule's letters". Both address choices show when exactly one box is drawn.
- Stray marks that OCR reads as one-letter words, like "•ö", are left out of the words a box
  lists and of the word chips in a new rule.

- The sidebar has Browse at the top, under Inbox, and Trays, Collections and Archive
  fold with a chevron beside their caption. A folded Trays still shows how many items
  are open, and the browser remembers which sections are folded.
- A filing code's empty Name pattern now shows `{doc_date:%Y%m%d}_{stem}` (the date, then
  the file's own name) as its example, which fits any code, not a sample sender.
- Settings has a row of sections at the top, grouped by what they apply to (this
  archive, or this browser), and shows one section at a time, each at its own address.
  Filing codes is now a short list, one line per code with its sticker and what it does;
  click a code to edit it. Unsaved changes get a bar at the bottom with Save and Discard,
  are kept when you leave Settings, and closing the window asks first. Print stickers
  opens as a sheet from Filing codes.
- Print stickers says how many labels fit on the chosen sheet and, with codes chosen,
  how many sheets they take and how many labels stay empty on the last one. Plain paper
  now shows its size in the sheet list (65 per sheet, like the Avery L7651).
- A filing code's Name is now called Name pattern, with an example and a line on what
  `{doc_date:%Y%m%d}`, `{year}` and `{stem}` do. A pattern that would give every file
  the same name is pointed out.
- Settings → Filing codes shows each code as a row: its sticker on the left as it
  prints (redrawn as you type the code or label), then Code and Label, Tray and Inbox
  folder, Folder and Collections, Name pattern and Tags, and Remove above File as
  suggested, which lines up with the Tags field. Collections are picked like folders, tags work as in the Inbox, and every
  field explains itself when you hold the pointer on it.
- Today's Starred card shows a file's buttons (Quick Look, Open, Show in Finder, Remove
  the star) only for the row under the pointer or with keyboard focus, so the list reads
  calmer. On touch screens they stay visible.
- Renaming works the same way everywhere, as in Finder: the name turns into a field in
  place, Enter saves, Esc cancels. A collection is renamed in its title (no separate
  form, and the ⋯ menu says Rename), an archive in Manage archives with a pencil button.
  A rename that changes a folder on disk still shows its preview first.
- A file's actions come in one order on every screen: view (Quick Look, Open, Show in
  Finder), then the star and Important, then Ask AI, and the To Delete bin last. Quick
  Look's Close button moved to the right end of its bar.
- Red is kept for the last step of a removal: the confirm button of Move to To Delete,
  Remove group and Forget archive. Menus no longer show red items.
- Ask AI on a single file is always the sparkle button with the same tooltip, also on
  Today's "Not recognised" list; Summarize with AI… carries the sparkle and an ellipsis
  because it opens the What will be sent sheet.
- Key hints under Browse, the Inbox and Trays look the same: arrows for moving, ↩ for
  Enter and one key for a shortcut (⌘↩).
- Tooltips on segmented choices (Folders/Files, This folder/Everywhere, the tray picker)
  now look like every other tooltip.
- The starred built-in collection is called "★ Starred" everywhere (the Browse collection
  filter, its page title, the collection picker and Convert Ongoing), matching the
  sidebar's Starred row. Its folder in `##. Ongoing` is unchanged.
- Collections and Activity: the toolbar's right-hand controls line up with the right edge
  of the list or timeline.
- Selecting a file in a collection shows the same panel as in Browse: the full preview,
  Put in tray, Add to collection, Back to inbox, the summary and the note, with the
  collection's own Group and Remove from collection added. The panel starts wider and can
  be dragged as wide as you like (the list keeps 320px). A link's bin and ★ / ! stay
  while its preview loads.
- A tray item's panel: Quick Look, Move to tray (now an icon) and Remove from tray sit
  together with the file's icons on its action row, instead of a Move to tray pull-down at
  the left and Quick Look in the header. Dragging the item onto a tray in the sidebar
  still moves it too.
- The user guide is rewritten for people using the app. Installing, the command line,
  config files and technical details moved to a new technical reference
  (`docs/reference.md`).
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

### Security

- **Importing and restoring a snapshot checks more.** A snapshot file can come from
  anywhere, so dam now refuses one with entry names that would land outside its
  temporary folder on Windows (drive letters, `:` streams, device names such as `NUL`),
  one that would unpack to far more than it looks (more than 10,000 entries, more than
  16 GB, more than the free disk space, or an entry packed unusually small), and one
  whose database holds triggers, views or tables dam never makes, or does not match
  dam's own database layout (for example a snapshot from an older app that used the
  same version numbers). A restore now always keeps this archive's own folders, its
  protected paths and the folders never sent to AI; a snapshot can add protected paths
  or excluded folders but no longer remove them, or add a folder to the archive.

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
