# Digital Archive Manager: user guide

## Contents

- [What dam is](#what-dam-is)
- [How dam works](#how-dam-works)
- [Getting started](#getting-started)
- [The window](#the-window)
- [Today](#today)
- [Filing from the Inbox](#filing-from-the-inbox)
- [Filing codes](#filing-codes)
- [Trays](#trays)
- [Paying a bill with the bank barcode](#paying-a-bill-with-the-bank-barcode)
- [Collections](#collections)
- [Starred and Important](#starred-and-important)
- [Browse](#browse)
- [Quick Look and the viewer window](#quick-look-and-the-viewer-window)
- [Activity and undo](#activity-and-undo)
- [Settings](#settings)
- [Notes and checklists](#notes-and-checklists)
- [Reminders](#reminders)
- [AI (optional)](#ai-optional)
- [Several archives](#several-archives)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Drag and drop](#drag-and-drop)
- [What dam never does](#what-dam-never-does)
- [Known limitations](#known-limitations)

## What dam is

dam keeps a folder of personal documents tidy. You put new documents in an inbox folder;
dam reads them (file names, text, and OCR for scans), suggests a name, a folder and tags
for each, and moves a file only after you have seen exactly what will change. Bills and
to-dos go into trays with reminders, related documents into collections, and everything
dam does can be undone.

The archive is an ordinary folder on your computer, for example inside Google Drive,
OneDrive, Dropbox or iCloud Drive, or a plain local folder. dam runs on your own computer
and opens in your browser; nothing is sent anywhere unless you turn on the optional AI
and click to send something.

Installing dam, the command line and the config files are in the
[technical reference](reference.md).

## How dam works

**The archive** is your folder of documents. dam keeps its own data (an index of the
files, your trays, collections, notes and settings) in a separate data folder on your
computer, never inside the archive.

**Four special folders** sit at the top of the archive. Their default names start with
`##.` so they sort first:

- `##. Organize` is the **inbox**: put new documents here.
- `##. Ongoing` shows your open **collections** as folders of links, so you see them in
  Finder or Explorer too. dam manages this folder.
- `##. Important` shows the documents you marked **Important** (passports, deeds) as
  links. dam manages this folder too.
- `##. To Delete` is where dam puts files you want gone. dam never deletes a file; you
  empty this folder yourself.

**The index.** dam scans the archive in the background, reads the text of each document
(PDFs, Office files, images and scans) and keeps it searchable. The status line at the
foot of the sidebar shows how far it has got.

**Preview, then apply.** Every change to your files (filing, moving, renaming, new
folders) is shown first as a list of exactly what will happen. Nothing moves until you
confirm, and every change can be undone from Activity.

## Getting started

The first time you open dam, a welcome screen asks for the archive folder. It lists the
cloud-drive folders it finds on your computer, or you can type any path. The folder is
checked as you type; when you press **Use this folder** the app starts in the same window.

- **A folder that already has documents** is used as it is: dam creates nothing, and
  uses each special folder once it exists (the inbox stays empty until there is a
  `##. Organize` with files in it). You can still add a starter layout later.
- **An empty folder** is offered **Start a new archive here**, with a starter layout.
- **Create a demo archive** builds a small fictional archive (a few bills, a scanned
  water bill with a bank barcode, a collection with groups) in a new or empty folder,
  so you can try everything without touching real documents.

### Starter layouts

A new archive needs folders to file into, and dam never makes a top-level folder on its
own. So the welcome screen (and, any time later, **Browse > Set up folders…**) offers a
starter layout:

- **Household**: Finance, Bills & Receipts, Insurance, Taxes, Home, Vehicles, Health,
  Education, Work, Personal, Other. **Minimal**: Documents, Receipts, Other. **Empty**: only
  the special folders.
- **Numbered prefixes** (on by default): `10. Finance`, `11. Bills & Receipts`, ... which
  keep the folders in your order in any file manager.
- The list is **editable before anything is made**: rename, remove or add rows, and
  rename the four special folders.
- **Preview, create, undo.** The preview lists every folder (ones already there are
  marked and left alone). Undo removes only folders that are still empty.
- If you have no filing rules of your own yet, example rules for the new folders are set
  up too (receipts to `Bills & Receipts/{year}`, tax letters to `Taxes/{year}`, ...).

### Getting documents in

Put new documents in `##. Organize`: drag them there in Finder, Explorer or your file
manager, or point your scanner at it. An empty Inbox has **Show in Finder** (or Explorer)
to open the folder, and **Choose files…**, which *copies* files into the inbox (the
originals stay; up to 200 MB each; a name already taken gets `_2`). Undo of a copy moves
it to `##. To Delete`.

You can also drop files or folders from Finder (or Explorer) on the Inbox list; they are
copied the same way. A folder's files at any depth land side by side in the inbox (its
subfolders are not kept), hidden files such as `.DS_Store` are left out, and one drop
copies at most 100 files. Documents dragged inside dam are never taken by the Inbox.

### New folders

**New folder** in Browse (toolbar or ⇧⌘N) adds a name row in the folder you are in, with
"untitled folder" selected; right-click a folder for **New folder inside…**. The folder is
made at once and can be undone while it is empty. Names with `/`, `\`, `< > : " | ? *`,
reserved Windows names (`CON`, `NUL`, ...), a leading or trailing dot, or a `##.` prefix
are refused. Nothing is made inside the four special folders.

### Run it as its own app window

The app can run in its own window, without browser tabs, with its own icon in the Dock or
taskbar:

- **Chrome or Edge:** open the app, then click the install icon at the right end of the
  address bar (or the menu: **Cast, save and share → Install page as app…**).
- **Safari:** open the app and choose **File → Add to Dock…**.

dam must be running for the window to work.

## The window

The window has a **sidebar** on the left, like Mail or Finder, and each screen has a
toolbar at the top: its title, a short count, icon buttons (hover one for its name and
shortcut) and, where it applies, a search field. Light and dark follow your system
setting. The sidebar, from the top:

- **Today**, with a red badge counting overdue and due-today items;
- **Inbox**, with its count;
- **Trays**: one row per tray, each with its open count;
- **Collections**: **Important** and **Starred** first, then the open collections as a
  tree (a parent's children nest under it; the chevron folds it). The caption opens the
  list of all collections, with New collection and the closed ones;
- **Archive**: **Browse**, **Ask** (AI questions about the archive), **Activity**,
  **Settings** and **Help** (this guide).

Banners above the screen tell you when the archive folder is not available (a cloud drive
not running, for instance), when an interrupted operation needs settling, or when a tray
file has a mistake. The **status line** at the sidebar's foot shows the inbox count and
indexing progress ("N searchable, N waiting, N not readable"); click it for the files that
could not be read and why, with **Retry**.

## Today

The front page: a greeting, one line saying what waits ("6 to file · 1 bill due soon ·
nothing overdue", or "All clear") and the date, then cards.

- **To pay** has the open total and each bill with its payee, amount and an urgency tag
  (red overdue, orange within 3 days, grey later).
- **Inbox** has the count, the age of the oldest document, a bar for this week, last week
  and older, and **Found in the inbox**: documents whose scan says they belong in a tray,
  each with **Put in <tray>**. When inbox files have a filing code, **File N marked**
  opens them as one batch (see [Filing codes](#filing-codes)).
- **To action**, **To read** and your other trays, the open collections that still have
  to-dos (open checklist entries, or files still in the inbox), **Starred** files, and
  the result of the last reminder check.

Trays with nothing open are folded into one **Clear** card, so the cards with content get
the room. Each tray row has a round checkbox that marks the item done at once (a bill is
marked paid today), with a toast to undo it; only a done field that needs a value you must
give opens a small form. Drag a card by its header to reorder, or press ⌥↑ / ⌥↓ with the
focus on it; **Reset layout** under the date restores the default order.

Today also shows a banner while `##. Ongoing` or `##. Important` holds things dam does not
manage yet, with a **Convert** button (see [Converting existing folders](#converting-existing-folders)).

## Filing from the Inbox

The Inbox has three columns: the sidebar, the list (thumbnail, suggested name, original
name, date, and a chip with a scanned due date and amount) and the document: its preview
with a form beside it for name, folder, tags, tray, tray fields, collections and a note.

1. **Pick a document.** The form starts with the filing rules' suggestion for each empty
   field.
2. **Check the suggestions.** Every other suggestion that differs from a field is a chip
   below it, **Suggested: <value>**, with its source (a rule, the scan, similar files or
   AI) and **Use**. **Use all** takes every chip. Nothing is applied by itself.
3. **Choose a tray** (optional) with the segmented control or the keys `1`–`9` (`0` for
   none). The tray's fields appear, filled in from the scan where it found them ("found in
   scan"): the due date only from a labelled date such as `eräpäivä` or `due date`, never
   guessed, and the amount from a total line, else the largest amount.
4. **Preview** (Enter) shows the planned changes below the form. **File it** (⌘Enter)
   applies exactly what was previewed; the toast has **Undo**.

More on the form:

- **Folder**: the first suggestion is active as you type; Enter takes it, ↑/↓ move, Esc
  closes. When no rule names a folder, dam suggests the folder where the most similar
  already-filed documents are ("similar files").
- **Tags** are chips: Enter or a comma adds one, and tags already in use are suggested as
  you type.
- **Detected fields** (dates, amounts, IBAN, reference, the bank barcode) name where they
  came from. You can remove one, change its value with the pencil, or **Add field**;
  **Reset to detected** brings back what the scan found.
- **Several documents**: ⌘-click and ⇧-click select several, and a batch form files them
  together. Each gets its own tray item, filled in from its own scan.
- **Ask AI** (the sparkle button) asks for suggestions when AI is on; they arrive as
  chips like the others.
- A name that looks like broken text (`NÃ¤kymÃ¤` for `Näkymä`) is repaired before it is
  suggested.
- In a narrow window the preview hides (**Space** opens Quick Look, **Show preview**
  brings it back), and below about 760 px everything stacks.

**Editing a filed document** works the same way wherever its details are shown (Browse, a
collection, a tray item): the pencil beside the name renames it (the extension stays), the
folder icon beside the path moves it, and tags are chips written at once. A rename or move
is shown as a plan first and has **Undo**.

## Filing codes

When you scan a paper you usually know already what it is for: a bill to pay, something
to do, or something already dealt with that only needs to go to its folder. A **filing
code** carries that decision with the document, so you do not make it again in the
Inbox. A code is one to four letters or digits from your own table, for example `P` for
To pay, and it can set any part of the filing form: the tray, the folder, a name pattern,
tags and collections.

A file gets its code from where you save it (an [inbox folder](#inbox-folders)) or from a
[QR sticker](#qr-stickers) on its first page. Either way nothing is filed until you have
seen it: a coded file waits in the Inbox with the code's values filled in, and you file
it from the form or together with the others through [File N marked](#file-n-marked).

dam comes with five codes, which you can change or remove in **Settings → Filing codes**:

| Code | Label | Does | Inbox folder |
| --- | --- | --- | --- |
| `A` | To action | puts it in the To action tray | `To action` |
| `P` | To pay | puts it in the To pay tray | `To pay` |
| `R` | To read | puts it in the To read tray | `To read` |
| `F` | Follow-up | puts it in the Follow up tray | `Follow-up` |
| `D` | File as suggested | files it where dam suggests, in no tray | `File as suggested` |

**File as suggested** is for paper you have already dealt with: the file goes to the
folder and name that the rules, similar files and the date suggest, and into no tray (a
tray that a rule or the scan suggested is dropped). If dam has no folder to suggest, the
file needs input.

**In the form**, each field a code sets starts with the code's value, and its chip says
where it came from ("from folder To pay", "from sticker `P`"). Fields the code leaves
alone are filled in as before, so a To pay code still takes the payee, amount and due
date from the scan. The tray starts as File N marked would file it: the code's tray
(none for File as suggested), or the tray a rule suggests when the code names none. A
code's name pattern is not used when the file's own name already starts with a date
(`20261015_...`): you named it already, so that name is kept.

**Editing codes.** Settings → Filing codes lists each code on one line: its sticker, the
code, the label and what it does. Click a line to edit that code (one at a time; **Done**
closes it). A code has a label, a tray, a folder, a name pattern, tags, collections, an
inbox folder and the **File as suggested** box, and shows its sticker as it prints,
redrawn as you change the code or label. A line with a problem (a code easy to confuse,
or a name pattern that gives every file the same name) says so even while it is closed.
Changes are saved together from the bar at the bottom, which shows while there are
unsaved changes (**Save** or **Discard**). Leaving Settings keeps them until you come
back, and closing the window asks first.
Collections are picked like folders (type to find one, or **…** to browse), and tags work
as everywhere else. Hold the pointer on a field to see what it does. While
you type a code, dam warns when it is easy to confuse with another one if you write codes
by hand (`0` and `O`, `1` and `I`, `5` and `S`).

The **name pattern** makes each file's name from its details: `{doc_date:%Y%m%d}` is the
document's date, `{year}` its year and `{stem}` the file's own name, so
`{doc_date:%Y%m%d}_Fortum` gives `20261015_Fortum.pdf`. A pattern without the date or
`{stem}` would give every file the same name, and dam says so under the code. The table
is saved in
`config/filing_codes.yaml` in the data folder, with a backup of the old file; comments
you wrote in that file by hand are not kept when you save from the app. See
[Filing codes file](reference.md#filing-codes-file) for the format.

**Codes and AI.** A filing code never lets a file reach AI: if the rules would file it in
an [excluded folder](#ai-optional), it stays excluded, whatever folder the code names.

### Inbox folders

Each code can have an inbox folder: a subfolder of `##. Organize` such as
`##. Organize/To pay`. Save or scan a file straight into it, or drag it there, and it
shows in the Inbox with that code. Only files directly in a code's folder count; a
folder inside it is not looked at.

A filing rule for the inbox (`folder_is: "##. Organize"`, as in the example rules) also
applies to the files in a code's folder, so they get the same folder suggestion as in the
inbox itself. A rule that names a code's folder (`folder_is: "##. Organize/To pay"`)
applies only to the files in that folder.

dam does not make these folders by itself. While some are missing, Settings → Filing
codes says which; **Create inbox folders…** makes them after a preview, and Activity can undo it while they are
still empty. Filing a file moves it out as usual; the folder stays for the next one.
Renaming a code's inbox folder in Settings does not rename the folder on disk.

Other subfolders of the inbox are not inbox folders, and the files in them are not in
the Inbox. Settings → Filing codes names them above the codes ("belongs to no code"), so
a renamed folder is easy to spot.

If your inbox already has subfolders named "To pay", "To action", "To read",
"Follow-up" or "File as suggested", they become inbox folders with this version, and the
files directly in them now show in the Inbox.

### QR stickers

A sticker is a small label with a QR code, the code in bold and its label. Stick it on
the first page of a paper before you scan it. When dam reads the scan it looks for
stickers on page 1 and takes a sticker only when its code is in your table, so QR codes
printed on invoices and letters are ignored. This works on macOS, Windows and Linux. The
QR code holds only the code, so printed stickers keep working when you change what a code
does.

**Tick boxes.** A sticker can have two boxes, ★ and **!**. Tick ★ with a pen to star the
document when it is filed, and **!** to mark it Important (see
[Starred and Important](#starred-and-important)). For a file with a sticker the form
shows **Star when filed** and **Mark Important when filed**, set from the boxes; you can
change them. A box dam cannot read clearly is pointed out ("Tick box unclear: check
star"), and the file starts unticked in File N marked.

**Printing stickers.** In Settings → Filing codes, **Print stickers…** opens the sticker
sheet:

- Tick the codes to print and type how many of each.
- Choose the sheet: **Avery Zweckform L7651** (65 labels of 38.1 × 21.2 mm), **Plain
  paper, cut out** (the same 65-label grid with cut lines), or **Custom**: columns, rows, label
  size, margins and gaps in mm, with or without cut lines. **Save custom sheet** keeps
  it for next time.
- **Start at label** picks the first label to use, to finish a half-used sheet.
- Under the options dam says how many labels fit on the sheet and, once you have chosen
  codes, how many sheets they take and how many labels stay empty on the last one. More
  stickers than one sheet holds go on to the next.
- **With tick boxes** is on by default. **Blank labels** leaves out the label text so you
  can write your own; the code is still printed.
- **Open sheet** opens the stickers in a new tab. Print from there at 100 %, without
  "fit to page", since scaling is the usual cause of labels that do not line up.

**Test print** draws only the label outlines: print it on plain paper and hold it against
a label sheet to check the fit. The L7651 measurements in dam have not been checked
against Avery's own template, so make a test print before printing on labels.

### Several codes on one file

A file can have more than one code, for example a sticker `A` on a paper saved in the
To pay folder. Tags and collections from all codes are combined. If the codes give
different values for the same field (two different trays, or a tray code together with
File as suggested), the file is marked **Codes disagree** and you decide in the form. The
same code found twice (folder and sticker) counts once.

### File N marked

When at least one inbox file has a code, the Inbox toolbar and the Inbox card on Today
show **File N marked**. It opens **Marked files**, one row per coded file: the codes
found and how ("P (folder)", "A (sticker)"), and exactly what filing will do: the new
name, the folder, the tray with the fields that will be stored (for To pay the due
date, amount, IBAN and reference), tags, collections, and Starred or Important from the
tick boxes. While dam is still reading new scans for stickers, **Reading filing codes…**
shows next to the button (or on its own until a coded file is found).

Every row is checked with a dry run before the list shows. A row that needs a look says
why and starts unticked:

- **Needs input**: the filing would be refused or would miss something, such as a file
  with no folder or a bill with no due date. The row says what is missing and cannot be
  ticked. **Open** shows the file in the Inbox form; fix it there and file it from the
  form.
- **Codes disagree**: see above.
- **Tick box unclear**: a sticker's box could not be read clearly.

You can tick the last two on purpose if what the row shows is right, or open them.
**File N** shows the preview of every move and files the ticked rows as one batch: one
entry in Activity, with one **Undo** for all of them. Files you left unticked stay in the
Inbox with their code's values filled in.

## Trays

A tray is a to-do list of documents: once a scanned paper is filed into a tray, the paper
can go. Four trays come with dam:

| Tray | For | Reminders |
| --- | --- | --- |
| **To pay** | bills: payee, due date, amount, IBAN and reference, with copy buttons | 3 days before, on the day, and once when overdue |
| **To action** | things to do by a date | 1 day before and on the day |
| **To read** | reading with no date | one nudge after 30 days |
| **Follow up** | things you wait on from others (a delivery, a reply, a refund), with an optional check-by date | on the check date and once when overdue |

A tray's screen has the list (Open / Done) and the selected item beside it; ↑/↓ move the
highlight and open the item. An item has a title (editable), one or more files, the tray's
fields, a note, a checklist and a history.

- **Mark paid** (or **Mark done**) finishes an item; **Reopen** undoes it. While one of
  the item's files is still in the inbox, **Mark paid and file…** marks it done and opens
  that file in the Inbox for filing.
- **Move to tray ▾** moves an open item to another tray. It stays the same item (title,
  note, checklist, history and files); fields the other tray also has carry over, and the
  rest come back if you move it back. A file has at most one open item at a time.
- **Remove from tray** (or ⌫) asks first, then deletes the item with its note, checklist
  and history. The files are never touched, so there is no undo for this.
- "1 file · **Add another file…**" under the title attaches another file to the item;
  **Add file** in the list's toolbar searches the archive and makes a new item for the
  file you pick.
- **Take this file off the item** removes a file from the item; the file stays where it is.

You can add your own trays (for example "To sign") as small text files; see
[Tray files](reference.md#tray-files) in the technical reference.

## Paying a bill with the bank barcode

A bill in **To pay** shows the Finnish bank barcode (pankkiviivakoodi) with its 54 digits
and **Copy**.

- **It is built from the item's fields**: the IBAN (Finnish only), the amount, the
  reference and the due date. Change a field and the barcode follows.
- **When it is not shown**, one line says why (a missing value, a non-Finnish IBAN, an
  amount over 999 999,99 €, a reference whose check digit is wrong). A wrong barcode is
  never drawn.
- **The printed barcode.** A barcode printed on the scanned bill is read while indexing
  and preferred for filling in the fields. If it disagrees with the item (say you changed
  the amount for a partial payment), a warning names the differences and offers **Use
  the printed barcode's values**; neither side is taken silently.
- **Scanning it with your phone.** If the barcode is too small, press **Show large
  barcode** (or `b`) for **Pay mode**: the barcode at full size with the payee, amount,
  reference, IBAN and due date in large type. In your banking app choose to pay with a
  barcode (in most Finnish banks: *Pay* → *Scan barcode*), hold the phone about 15–25 cm
  from the screen, and check the payee, amount and reference before you confirm. Without
  a camera, **Copy** the 54 digits into the bank's "virtual barcode" field.

## Collections

A collection gathers related documents from anywhere in the archive, for example
everything about a house sale. Files stay where they are; the collection follows them
when they are moved or renamed. A file can be in several collections.

A collection's page has a summary, a **Needs attention** strip (members in an open tray
item or still in the inbox), its child collections, its groups of files, a note and a
checklist. The selected file shows on the right with its details and buttons.

**In Finder or Explorer**, open collections appear in `##. Ongoing`: a collection with
several members is a folder of links, and one whose only member is a folder is a single
link to it. Closing a collection removes its links; reopening brings them back. Entries in
`##. Ongoing` that you made yourself are never touched; if a name is taken, dam uses
`<name>_2` and the collection says why.

**Adding and removing members** (drag files onto the collection in the sidebar, or **Add
to collection…** on a file) applies at once, without a confirm, because it only changes
dam's own links. Renaming, closing, reopening and switching publishing on or off show a
preview first.

### Parent collections

A collection can live inside another, to any depth: `Houses › Sauna › Deck`. Drag it onto
another collection in the sidebar (or onto the **Collections** caption for the top level),
or use **Move to…** in its **⋯** menu; **New collection inside…** creates a child. In
`##. Ongoing` a child is a folder inside its parent's folder. A parent with open children
cannot be closed, and a child under a closed parent cannot be reopened.

### Groups

A collection's files can be arranged in groups, nested to any depth, plus **Ungrouped**.
**New group** adds one; each group's **⋯** menu has Rename, a summary, New subgroup, Move
up / Move down and **Remove group…**, which moves its files to the parent group (no file
or membership is removed). Drag members between groups, or choose the group in the panel
on the right. In `##. Ongoing` each group is a subfolder of the collection's folder.

### Export

**Export** on a collection makes a **zip** (the files, in folders mirroring the archive,
with a contents list) or one **PDF** (PDFs and images merged in order, with a contents
page; other types are listed as not included). It downloads in your browser and is built
outside the archive. Files a cloud drive has not downloaded yet are skipped and listed.

### Converting existing folders

If `##. Ongoing` or `##. Important` already holds folders, files or shortcuts of your own,
**Convert** (offered on Today and from Important) turns them into collections or marks,
one entry at a time, each with a preview of the exact moves and links and its own
**Undo**:

- a link to a folder becomes a collection; a link to a single file is starred, or becomes
  a one-file collection;
- a real folder (e.g. `Legal`) becomes a collection: you choose the archive folder its
  contents move to, and the emptied folder is replaced by dam's own;
- a real file is starred, or added to a collection, and moved to an archive folder you
  choose;
- **Skip** leaves an entry alone for now.

If anything changes between the preview and Apply, nothing moves and you preview again.

## Starred and Important

Two marks for files you need often, without making a collection:

- **★ Starred** is for everyday quick-access files, such as this year's budget sheet.
  Starred files show on Today and in the sidebar's **Starred** row, and as links directly
  in `##. Ongoing`.
- **! Important** is for documents that must always be easy to find: passports, deeds.
  They show in the sidebar's **Important** row and as links in `##. Important`, where
  they can be arranged in groups (such as `Houses › Hillside`).

Mark or unmark with one click wherever a file is shown. **Marking never moves or renames
a file.** A file marked Important cannot be moved to To Delete (unmark it first), nor can
a folder holding one.

## Browse

Browse shows the archive's folders, with search. Click a file, or step to it with `j`/`k`,
and the detail beside the list shows its preview, then its trays, marks, actions, summary
and note. Folders open on click. Drag the edge between list and detail to change the
list's width.

- **Two panes**: the split toggle in the toolbar shows two folders side by side, for
  moving files between them. The active pane has an accent edge.
- **Move to…** (⇧⌘M) and **Move to To Delete** are in the toolbar. A move always shows its
  preview first.
- **Collection** filters a pane to one collection's files; **Folders / Files** switches
  between the folder view and a flat list of every file below the current folder, with
  sortable Name, Folder, Date and Size columns (up to 500 rows).
- **Links.** A link to a file inside the archive previews and opens as that file, with
  **Go to target**. A link to something outside the archive only has Show in Finder.

## Quick Look and the viewer window

**Space** opens the selected document nearly full window: zoom (the buttons, ⌘-scroll,
`+`/`−`/`0`), drag to pan, page through it, and see its details. It opens at Fit, the whole
page visible. `→`/`←` (or `j`/`k`) go to the next or previous document of the list; Space
or Esc closes it. It works in the Inbox, the trays, a collection and Browse.

**⤢ Open in window** opens the document in a separate window that **follows the
selection** of the main window, so you can keep a document beside your work. The pin keeps
it on one document.

**Open** opens a file in its own app and **Show in Finder** (or Explorer) shows it in its
folder. dam will not open apps, scripts or installers from the archive.

## Activity and undo

Activity is a timeline of every change dam made, newest first, under day headers. Each
entry says what you did ("Filed Offer of Näkymä into 80. Misc", "Moved … to To Delete",
"Starred X.xlsx") and has its own **Undo**, which first shows exactly what it will do, and
says why if it cannot (for example when the file was changed or moved again since).
**Expand all** / **Collapse all** sets whether entries show their operations.

- Undoing a filing moves the file back and removes the tray item, collection membership
  and note that filing created. Tags it added stay.
- Updates to `##. Ongoing` that dam makes by itself after a scan have no Undo; undo the
  collection change instead. They link to the collection.

The **AI** view in Activity lists every AI call with its cost, the month's total and the
on/off switch.

## Settings

Settings is where dam's own options are kept. The row at the top has one section for
each area, grouped by what it applies to; one section shows at a time.

- **This archive** (the one open now; each archive has its own):
  - **Filing codes**: your table of codes, one line each; click one to edit it. **Add a
    code** adds one, **Print stickers…** prints sticker sheets, and the bar at the bottom
    saves or discards your changes. Missing inbox folders, and inbox folders that belong
    to no code, are pointed out above the list. See [Filing codes](#filing-codes) and
    [QR stickers](#qr-stickers).
- **This browser** (every archive alike):
  - **Appearance**: Light, Dark, or Auto to follow your system setting. It applies at
    once, and is remembered by this browser (another browser starts on Auto).

## Notes and checklists

Any tray item and any collection can have a plain-text note and a checklist, and you can
add a note to a document while filing it. They are kept in dam's database; your documents
are never changed. Click a checklist row's text to edit it (Enter saves, Esc cancels);
drag a row by its grip, or press ⌥↑ / ⌥↓, to reorder.

## Reminders

dam reminds you of tray items by their date: a bill a few days before it is due, on the
day and once when overdue; an undated item to read after 30 days. Each reminder is sent
once and never for done items. If several are already past when an item is created (an
overdue bill), you get only the latest. Changing an item's date sets up its reminders
again.

Reminders come as a desktop notification (macOS) and, if you set it up, as one e-mail
per check. **What is sent: the item's title, tray, date and amount, never document text.**
Titles come from file names (or what you typed), so keep secrets out of them. The last
check's result is on Today.

dam checks hourly while it runs. To be reminded when it is not running, install the daily
job; see [Reminders setup](reference.md#reminders-setup).

## AI (optional)

dam works fully without AI. With an Anthropic API key, it can suggest how to file a
document, summarise a document or a collection, and answer questions about your archive.
Rules and scan detection always run first, and **AI is only ever used when you click**.
Without a key the AI buttons are hidden and a hint says how to turn it on (see
[AI setup](reference.md#ai-setup)).

**Where it is used:**

- **Ask AI** in the Inbox and on a filed document: its suggestions arrive as chips you
  take one by one. You still file with **File it**.
- **Summarize with AI** on a document, a tray item or a collection (and its groups): the
  answer is a proposal with **Use this summary** or **Discard**. A summary you wrote is
  never replaced without asking. When a file changes, its summary is marked outdated.
- **Ask** in the sidebar: a question about the archive. dam finds the best-matching
  passages itself (no cost), shows them before anything is sent, and the answer has
  numbered sources that open in Quick Look. **Save to notes…** adds the answer to the
  notes of the sources you choose. Answers are not kept after you close the app.

**What is sent, and what never is:**

- **Nothing without a click.** Every AI action first shows a **What will be sent** sheet
  with the exact text, the model, the worst-case cost and this month's spend. The call
  goes out only when you click **Send**.
- **Extracted text only**, never the file itself, and only limited amounts of it.
- **Excluded folders** (by default medical, work and other people's documents) are never
  sent, with no override. See and change them in **Activity → AI → Excluded folders**:
  adding one applies at once; removing one asks first.
- **AI never acts.** Its answers only fill in suggestions; you decide what to take.

**Costs.** A monthly budget (€5 by default) blocks a call before sending if it could go
over. The sheet shows the worst case; a typical call costs far less. A call that does not
answer in time is counted at its estimate, to stay on the safe side. A repeated question
about the same text is answered from the cache for free ("from earlier"). Every call is
listed in **Activity → AI**, where you can also switch AI off.

## Several archives

You can keep several separate archives, for example your real one and a test one, and
switch between them. Each has its own folder, settings, rules, index and reminders;
nothing done in one can touch another.

- **Add one**: the archive menu at the top of the sidebar, **Add archive…**: a name and a
  colour, then the same choices as the welcome screen (including **Create a demo
  archive**).
- **Switch**: choose an archive in the menu. The switch happens in the same window. Every
  archive but "Main" has a thin band in its colour along the top of the window, so a test
  archive is never mistaken for the real one.
- **Manage archives…** renames, recolours, shows each archive's folders, and forgets an
  archive. **Forgetting deletes nothing**: both its folders are shown so you can remove
  them yourself if you want.

## Keyboard shortcuts

Single-letter keys work when the focus is not in a text field (Esc leaves one). On
Windows and Linux, read Ctrl for ⌘ and Alt for ⌥.

| Where | Key | Does |
| --- | --- | --- |
| Lists (Inbox, trays, a collection, Browse) | `j` / `k` or `↓` / `↑` | Next / previous |
| Lists | **Space** | Quick Look of the selected document |
| Quick Look | `→` / `←`, `j` / `k` | Next / previous document |
| Quick Look | Space, Esc | Close |
| Preview, Quick Look, viewer | `+` / `−` / `0`, ⌘-scroll | Zoom in / out / Fit |
| Inbox | ⌘-click, ⇧-click | Select several (the batch form) |
| Inbox | `Enter` | Preview the filing |
| Inbox | ⌘`Enter` | File it (after the preview) |
| Inbox | `n` / `f` | Edit the name / the folder |
| Inbox | `1`–`9` / `0` | Choose a tray / no tray |
| Inbox | `u` | Undo the last filing |
| Trays | `Enter` | Open the item |
| Trays | `d` | Done (Mark paid in To pay) |
| Trays | `⌫` | Remove the item from the tray (asks first) |
| Trays (To pay) | `b` | Show the large barcode (Pay mode) |
| Today | ⌥↑ / ⌥↓ on a card | Move the card |
| Browse | `Enter` | Open the folder or file |
| Browse | `⌫` | Up one folder |
| Browse | ⌘-click, ⇧-click | Select several files |
| Browse | ⇧⌘M | Move to… |
| Browse | ⇧⌘N | New folder in the active pane's folder |
| Browse | ⌘[ / ⌘] | Back / forward in the active pane |
| Browse, a collection, a tray item, Quick Look, the viewer | ⌘⌫ | Move the selected file to To Delete |
| Confirm sheets | ⌘`Enter` | Confirm (only half a second after it opened) |
| Confirm sheets | Esc | Cancel |
| Menus | `↑` / `↓`, Home / End, Esc | Move, first / last, close |

## Drag and drop

Drag documents from the Inbox list, Browse, a collection's file list or a tray list; a
selection drags all of it. A valid target highlights; an invalid one shows why not.

| Drop on | What happens |
| --- | --- |
| A tray in the sidebar | Creates an item per file, filled in from its scan, like **Put in <tray>**. The file stays where it is. A file already in that tray is skipped; a file whose open item is in another tray has that item moved here. The toast has **Open** and **Take back**. |
| A collection in the sidebar | Adds the files to the collection, ungrouped. |
| A collection onto another collection (or the **Collections** caption) | Moves the collection inside the other one (or to the top level), with everything under it. |
| A group inside a collection | Adds the files to that group, or moves them there if they are already members. |
| A folder in Browse (a folder row, or the other pane) | **A move, always behind a preview and confirm**, with **Undo**. Not allowed for `##. To Delete` (use Move to To Delete), `##. Ongoing` and the top of the archive. |

Every drop has a keyboard or menu equivalent: the Inbox form, **Put in tray…** and **Add
to collection…** on a file, the group menu, and **Move to…** in Browse. Only files move;
folders can be opened and dropped on, not dragged.

## What dam never does

- **It never deletes your documents.** **Move to To Delete** (⌘⌫) moves a file into
  `##. To Delete`, keeping its original path; you empty that folder yourself. The only
  things dam ever removes are its own links and its own empty folders in `##. Ongoing` and
  `##. Important`, and only after checking they are still exactly the ones it made.
- **It never changes anything without showing you first.** Moves, renames, new folders
  and conversions are previewed and need your confirmation. A name already taken gets
  `_2`; nothing is ever overwritten.
- **It never loses track of a change.** Every change is recorded in Activity and can be
  undone, after a check that the files are still the ones that were moved.
- **It never creates a top-level folder by itself.** Only when you ask (New folder, a
  starter layout), and `##. To Delete` when it is first needed.
- **It never writes your trays, notes or collections into the archive.** They live in
  dam's own database.
- **It never goes online by itself.** dam runs only on your computer and only your own
  browser can reach it. AI calls happen only when you click Send.

The full details are in [Safety model in detail](reference.md#safety-model-in-detail).

## Known limitations

- Apple Vision OCR (macOS) does not read Finnish, so scanned Finnish text is recognized
  poorly; PDFs with a text layer are unaffected. Tesseract, used on Windows and Linux,
  does read Finnish.
- Previews show no page count.
- No phone or tablet layout: narrow windows stack the columns, but the app is made for a
  desktop window. Pay mode covers paying from your phone.
- Clicking a reminder notification does not open the document.
- Desktop notifications and the daily reminder job are macOS only for now; on Windows and
  Linux use e-mail reminders and schedule the job yourself.
- On a cloud drive that keeps files online only (such as Google Drive in streaming mode),
  indexing downloads every file over time, so plan for free disk space about the size of
  the archive. The first full index is slow by design.
