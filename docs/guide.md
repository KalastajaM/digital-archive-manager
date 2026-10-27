# Digital Archive Manager: user guide

## Contents

- [What dam is](#what-dam-is)
- [How dam works](#how-dam-works)
- [Getting started](#getting-started)
  - [Starter layouts](#starter-layouts)
  - [Getting documents in](#getting-documents-in)
  - [New folders](#new-folders)
  - [Run it as its own app window](#run-it-as-its-own-app-window)
  - [Signing the browser in](#signing-the-browser-in)
- [The window](#the-window)
- [Today](#today)
- [Filing from the Inbox](#filing-from-the-inbox)
- [Filing codes](#filing-codes)
  - [Inbox folders](#inbox-folders)
  - [QR stickers](#qr-stickers)
  - [Assigning a code](#assigning-a-code)
  - [Several codes on one file](#several-codes-on-one-file)
  - [File N marked](#file-n-marked)
- [Filing rules](#filing-rules)
  - [Making a rule from a filing](#making-a-rule-from-a-filing)
  - [The proof](#the-proof)
  - [Rules by where text sits on page 1](#rules-by-where-text-sits-on-page-1)
  - [Several areas for one rule](#several-areas-for-one-rule)
  - [Picture areas](#picture-areas)
  - [Seeing the areas](#seeing-the-areas)
  - [Changing an area](#changing-an-area)
  - [People and the address area](#people-and-the-address-area)
  - [From and For on a document](#from-and-for-on-a-document)
  - [Where rules are kept, and in what order](#where-rules-are-kept-and-in-what-order)
  - [The record](#the-record)
  - [The rules list in Settings](#the-rules-list-in-settings)
  - [Reading page 1](#reading-page-1)
- [Trays](#trays)
  - [Row icons](#row-icons)
  - [Working on an item](#working-on-an-item)
  - [Files on an item](#files-on-an-item)
- [Paying a bill with the bank barcode](#paying-a-bill-with-the-bank-barcode)
- [Collections](#collections)
  - [Parent collections](#parent-collections)
  - [Order of collections](#order-of-collections)
  - [Groups](#groups)
  - [Export](#export)
  - [Converting existing folders](#converting-existing-folders)
- [Starred and Important](#starred-and-important)
- [Locking a file](#locking-a-file)
- [Browse](#browse)
- [Searching](#searching)
- [Tags](#tags)
- [Quick Look and the viewer window](#quick-look-and-the-viewer-window)
- [Activity and undo](#activity-and-undo)
- [Maintenance](#maintenance)
  - [Duplicates](#duplicates)
  - [The other checks](#the-other-checks)
- [Settings](#settings)
  - [Snapshots](#snapshots)
- [Notes and checklists](#notes-and-checklists)
- [Reminders](#reminders)
- [AI (optional)](#ai-optional)
- [Several archives](#several-archives)
- [Several archive folders](#several-archive-folders)
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

### Signing the browser in

Only the browser dam opened can use dam: `dam serve` opens it through a sign-in link,
and the browser stays signed in for a year. If a page says **Not signed in** (another
browser, or a bookmark opened before dam signed that browser in), run `dam open` while
dam is running; it opens the app and signs that browser in. `dam open --print` prints
the link instead, to paste into a browser yourself.

## The window

The window has a **sidebar** on the left, like Mail or Finder, and each screen has a
toolbar at the top: its title, a short count, icon buttons (hover one for its name and
shortcut) and, where it applies, a search field. Light and dark follow your system
setting. The sidebar, from the top:

- **Today**, with a red badge counting overdue and due-today items;
- **Inbox**, with its count;
- **Browse**, the whole archive;
- **Trays**: one row per tray, each with its open count;
- **Collections**: **Important** and **Starred** first, then the open collections as a
  tree (a parent's children nest under it; the chevron folds it). The caption opens the
  list of all collections, with New collection and the closed ones;
- **Tags**: the caption opens the [Tags](#tags) screen; below it your pinned tags, then
  the tags you used most lately, eight at most, each opening its files in Browse;
- **Archive**: **Ask** (AI questions about the archive), **Activity**, **Maintenance**
  (checks you start yourself), **Settings** and **Help** (this guide).

Trays, Collections, Tags and Archive fold: hold the pointer on the caption and click the chevron
at its right. A folded Trays shows its open total next to the caption. dam remembers in
this browser which sections you folded.

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
- **Search** is a box on top of the second column: type and press Enter, and Browse opens
  with that search (filters such as `tag:name` work too, see [Searching](#searching); the
  **?** next to the box lists them).

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
  you type. The **...** button beside the field lists every tag by group with its number
  of files; click one to add it.
- **Also add to collection** works the same way: the collections the file will be added
  to are chips (the x takes one out), matching collections are suggested as you type, and
  Enter or a click adds one. A name that is no collection yet is offered as **Create
  collection "name"** and is created when you file. The **...** button opens the
  collections as a tree. Nothing is applied until you file.
- **Detected fields** (dates, amounts, IBAN, reference, the bank barcode) name where they
  came from. You can remove one, change its value with the pencil, or **Add field**;
  **Reset to detected** brings back what the scan found.
- **Several documents**: ⌘-click and ⇧-click select several, and a batch form files them
  together. Each gets its own tray item, filled in from its own scan.
- **From** and **For** show who a letter is from and who it is for, and where each came
  from; click one to change it (see [From and For on a document](#from-and-for-on-a-document)).
- **Ask AI** (the sparkle button) asks for suggestions when AI is on; they arrive as
  chips like the others.
- A name that looks like broken text (`NÃ¤kymÃ¤` for `Näkymä`) is repaired before it is
  suggested.
- In a narrow window the preview hides (**Space** opens Quick Look, **Show preview**
  brings it back), and below about 760 px everything stacks.

**Editing a filed document** works the same way wherever its details are shown (Browse, a
collection, a tray item): clicking the name renames it (the extension stays), the
folder icon beside the path moves it, and tags are chips written at once. A rename or move
is shown as a plan first and has **Undo**.

**The file view has the same order everywhere** (Browse, a collection, a tray item): the
name and folder with the lock, the tags, the collections the file is in (chips like tags:
the x takes the file out, and typing in the field adds it, offering **Create collection
"name"** for a new one; **...** opens the tree; both apply at once and the toast has
**Undo**), the summary, then what only that view
has (in a tray: the fields, **Mark done** or **Mark paid** and the action row; in a
collection: the group), the
preview with its toolbar (zoom, select box, print, open, show in Finder, open in window and Quick Look), and last the notes, checklist and history. The summary, notes,
checklist and history fold. A tray item with several files shows the collections of the
file you chose.

## Filing codes

When you scan a paper you usually know already what it is for: a bill to pay, something
to do, or something already dealt with that only needs to go to its folder. A **filing
code** carries that decision with the document, so you do not make it again in the
Inbox. A code is one to four letters or digits from your own table, for example `P` for
To pay, and it can set any part of the filing form: the tray, the folder, a name pattern,
tags and collections.

A file gets its code from where you save it (an [inbox folder](#inbox-folders)), from a
[QR sticker](#qr-stickers) on its first page, or from you in the Inbox
([assigning a code](#assigning-a-code)). Either way nothing is filed until you have
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
Collections are chips like tags (type to find one, or **…** to browse), and tags work
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

### Assigning a code

A document that arrives as a file (an email attachment, a download) cannot carry a
sticker, but you can give it a code in the Inbox as if it had one. Press **c**, or click
the QR button in the Inbox toolbar, and pick a code: type the code or part of its label,
then press Enter, or click it. The code goes to the selected files, or to the file on
screen. The file then shows the code in its row and fills in the form from it, and
**File N marked** includes it.

Nothing is written into the file or moved: dam only remembers your choice, and filing
still goes through the usual preview. The toast has **Undo**; **×** on the code at the top
of the form takes it off again, and so does **No assigned code** in the picker. Giving a
file another code replaces the one it had.

A code you assign wins over the code of the file's inbox folder or a sticker on it, so
they never disagree: the others still show in File N marked, struck through as
"overridden". A sticker's ★ and **!** boxes still count. If you later remove the code
from your table, the assigned code sets nothing and the file's other codes count again.

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

## Filing rules

A filing rule fills in the Inbox form for you: when a document contains certain words
(or a picture such as a logo), the rule suggests the folder, the name, the tags, the tray
and the payee. A rule can look for its words or picture in an area of page 1, and can file
per person. dam drafts rules from how you file, and proves each one against the documents
you have already filed before you save it. Rules only fill in the form. Nothing is filed
until you confirm, and no AI is involved.

### Making a rule from a filing

After you file one document by hand from the Inbox form, the "Filed" message offers
**Make a rule…** when the folder or name was not what a rule suggested (or you changed
it). If the value you changed came from a rule made in the app, it offers **Update rule
<id>…** instead, which opens that rule as it is with the folder and name from this
filing. There is no offer after filing several documents at once, after File N marked,
or when a filing code did the filing.

**Make a rule…** opens a sheet drafted from what you just did. It has two parts, each
under its own heading: **When a document matches** holds what a document must have, and
**Then file it like this** holds what the rule sets. The test comes after both.

When a document matches:

- **When the text contains**: the match words, as chips, and a box to add a word of your
  own. One is ticked: the most distinctive word near the top of the text, usually the
  sender. A rule matches when **any** ticked word is in the text, so ticking more words
  widens the rule. Words that appear in more than 3 in 10 of your filed documents are not
  offered. When no usable word is left, there is no offer.
- **Areas**: when the rule comes from boxes drawn on page 1, each area is a group of its
  own under this one (see
  [Rules by where text sits on page 1](#rules-by-where-text-sits-on-page-1)).
- **From (sender)**: optional. It is filled in from the document's own From when it has
  one, and the senders you have used are offered as chips. With a sender, the proof also
  says how many of the documents you set as from that sender the rule finds, and which it
  misses.
- **For**: **Anyone** or **Only for** a person; see
  [People and the address area](#people-and-the-address-area).
- **More conditions** (closed to begin with; a line beside it says what is set, such as
  "Only in the inbox"): a file-name pattern (a regular expression searched anywhere in the
  file name, see the tip beside it), and the folder the file must be in.

Then file it like this:

- **Filed as**: the folder and name you gave the document just now, which the patterns
  were made from.
- **Folder**: type it, or press the "…" button to pick a folder from the tree; the path
  you pick goes into the field.
- **Name**: the file name to give.
- **Patterns** in Folder and Name: `{year}`, `{doc_date:%Y%m%d}`, `{stem}` and `{person}`
  stand for the document's year, its date, its original file name and the person the
  letter is for, and are filled in for each document the rule files (the tips beside the
  fields list them).
- **Tags** and **Tray**: what the rule sets. An empty field is one the rule does not set;
  to leave a field out, clear it.
- **Add to collection**: the collections the Inbox form starts with in "Also add to
  collection" when this rule matches, as chips (type to find, or the
  "…" button). It works like tags: the collections of all matching rules are added
  together, and you can still change them on the card before filing. A name that does not
  exist yet is created when the document is filed. The test does not compare collections
  (it only checks where documents would be filed).
- **Payee**: only there when the chosen tray has a payee field (To pay does). It is the
  name filled in as the payee when the rule puts a bill in that tray. A rule that already
  has a payee keeps showing it.

### The proof

When the sheet is open for a document (the one you just filed, or the one you drew boxes
on), the test starts with one line about that document: "This rule matches this
document", or "This rule does not match this document" with the reason, in the words of
**Test a document** ("no word found in the area", "the picture in the area scores 0.71,
needs 0.85", "the document is not for Tiina"). It is judged as live filing would judge it:
a document in the inbox by the rule as written, a filed one without the folder condition.
It updates as you change the rule, so you can edit the rule until it no longer matches
that document. The document is left out of every count and list below, the ones filed
before, the inbox count, the scores, the documents that could not be judged yet and the
marked documents. A rule opened
from Settings has no such line.

Under the sheet, dam replays the rule against the documents you filed before and shows
the result again after each edit: "Matches 14 documents you filed before: 12 would land
exactly where they are", then every one that would land somewhere else, current place
beside the rule's place. It also says how many documents in the inbox now the rule
catches, and, when an earlier rule already wins for some of the matches, "For 3 of them
rule fortum comes first". If no filed document matches, it says so, and you can still
save.

Documents the test could not judge yet are counted ("2 documents could not be judged
yet") and listed, closed, under **Could not be judged yet**, grouped by reason. Each group
says what the reason means and what happens next: "Page 1 not read yet" (dam reads page 1
in the background and the test picks the documents up when they are read; **Read page 1
of these N now** does it first), "Person unknown" (the address area does not say who the
letter is for, so a rule that files by person cannot be judged; set For on those
documents, or add the people in Settings), "No OCR engine", "Missing", "Took too long",
"Not read yet" and "No picture of page 1". A rule that names no person (Anyone, and no `{person}` in the
Folder or Name) never has documents in "Person unknown". While you edit, the result on
screen is the one for the rule before your last change, and the sheet says so until the
test of the rule as it is now answers.

**Save** waits ("Testing…") until the proof for what is on screen is in. If some
documents would land elsewhere it asks "2 documents would land somewhere else. Save
anyway?".

**Not for these** closes the offer and remembers the match words of that document, so
dam does not offer again for documents with the same words. Settings can forget them.

### Rules by where text sits on page 1

Most post comes from the same senders, with the letterhead in the same place each time.
A rule can require its words in an area of page 1, so a bill that only mentions
"Pohjola" somewhere is not taken for a letter from Pohjola. A rectangle you draw is a
**box**; once it is part of a rule it is an **area**.

In the preview of a PDF or image (the Inbox card, Browse, a collection, Quick Look, the
document window or a link's target), turn on **Draw a box** and drag a rectangle over
page 1. The panel "Boxes on page 1" lists the words dam found in it. Every box you draw
is kept as it is drawn, numbered on the page and in the list (Box 1, Box 2, ...), with
its own x to remove it. Esc drops the box you are dragging, then the last box, then
closes the tool; the x at the top of the panel ("Close and drop the boxes") drops them
all. The panel offers:

- **Make a rule…**: a rule sheet opens with the words in the boxes as chips under "Words
  in area 1", "Words in area 2" and so on (one group for each box; "Picture in area 3" for
  a picture box). With more than one area, the ? beside "When a document matches" says the
  document needs a word or the picture in every area. Each text area has its **Words
  match** choice next to its word box. The rule does not have to be about
  a sender: a box can just as well pick out the kind of letter or any other fixed text.
  The proof works as above. Documents whose page 1 has not been read yet are read first
  ("Reading page 1 of N documents…"); any that cannot be read are listed under **Could
  not be judged yet**, never counted as a miss.
- **Address area for this rule's letters**: for a rule whose letters put the address
  somewhere unusual; shown when one box is drawn and a rule made the current suggestion.
- **Address area for all letters**: where dam looks for who a letter is for; shown when
  one box is drawn.

**How the words of an area match.** Each area with words has a choice, **Words match**:

- **Starts a word** (the choice for new areas): the word must begin a word but may have
  an ending. "kela" finds Kela, Kelan and Kelalta, and "vakuutus" finds Vakuutuskirja, but
  "vakuutus" does not find Henkivakuutus.
- **Whole word**: only the word itself. "kela" finds Kela but not Kelan.
- **Anywhere**: the letters anywhere in a word, so "vakuutus" also finds Henkivakuutus.

A word starts or ends where a space, hyphen, slash, dot or other mark that is not a letter
or digit is (or at the edge of the line), so "pohjola" is found in "OP-Pohjola". Digits
count as part of a word. Capitals and accents do not matter. A word of several words
(such as "maksu pohjolaan") has to appear in that order. Changing the choice tests the rule
again. Rules written before this choice existed keep matching anywhere, so nothing changes
for them until you change it.

dam keeps where each word of page 1 sits, so a box drawn tightly around one word lists
only that word, and a rule word has to be among the words inside the box. Letters that
were read before dam kept word positions are matched by whole lines (a line counts when
half of it is inside the box) until the file's content changes and page 1 is read again;
dam does not re-read them on its own. For scans read by Apple Vision on a Mac, the
position of each word inside a line is an estimate, so a box that cuts a line in the
middle can be off by a letter or two. Stray marks that OCR reads as one-letter words (like
"•ö") are left out of the lists and the word chips.

A box allows for a few millimetres of shift between scans.

### Several areas for one rule

A sender writes many kinds of letters, and the kind is usually printed in a fixed place
too, such as the title under the letterhead. A rule can need more than one area: every
area must have one of its words, so "Pohjola in the letterhead" and "vakuutuskirja in the
title" together file a policy and leave a Pohjola bill alone.

Draw as many boxes as you need, one after the other (see above). **Make a rule…** uses
all of them, with one word ticked in each. The rule sheet shows each area as its own group
of word chips with a **Remove** button; a rule needs at least one word or area. Within an
area any ticked word is enough.

For folder and name the first matching rule wins, so a rule with more areas has to come
before a plainer rule for the same sender. When you make a rule from boxes drawn on a
document that a learned rule matches already, dam saves the new rule directly above that
rule. Rules you wrote in your own files are never reordered; the proof still says "For N
of them rule X comes first" if the order is wrong.

### Picture areas

Some letterheads are only a picture: a logo, and the box holds no text. Then dam can
recognise the picture itself. Draw the box and, in its row, choose **Picture** instead of **Words**
(it is offered for any box, not only an empty one). The panel shows the picture that was
cut out of it. **Make a rule…** then makes a rule with that area; the rule sheet shows the picture and a slider, **Match
needed**; the small reset button right of its value ("Use the default (0.85)") puts the
score back to the default, and is greyed out while it is there.

How it works: dam keeps a small grayscale picture of page 1 of each PDF and image (about
25 KB, in the cache folder, never in the archive). It looks for the cut-out picture in
the area you drew, allowing a shift of 5 % of the page in any direction, sizes from 90 %
to 110 %, a lighter or darker scan, scan noise and a skew of a degree or two. The score
runs from 0 to 1; the rule needs at least **Match needed**, usually 0.85. Another logo in
the same place scores clearly lower (0.63 and under in dam's own tests with dark logos on
white), and a block of small text with other words in the same layout scores about 0.74,
which is why the limit is not lower. Fine print is the hardest to recognise on a crooked
scan: a skew of 2 degrees can bring it down to about 0.82, so lower the slider a little for
a picture of small text. The slider goes from 0.50 to 1.00.

The test under the rule sheet lists the scores in two groups. **Matched** has the lowest
scores of the documents the rule matched. **Close, but not matched** has the highest scores
of the documents that were not matched but came within 0.15 of what is needed, and only
documents where the picture was the one thing that failed: a document that has the word
somewhere else on the page but not in your area is never listed with a score. If the two
groups are far apart, the rule is safe. If they touch, move the slider, or add a text box
so the picture only has to decide between a few documents. A picture alone also takes
longer to test, because every filed PDF and image is looked at (the test does not open the
files in the archive, only the small pictures). Pictures not made yet are made first,
inbox before the rest; a document without one is listed under **Could not be judged yet**, never as a miss.

Every path in the test result is a button. It opens the document in the preview with the
rule you are testing drawn on its first page: its areas, and for a picture area the place
where it fits best with its score. When a picture rule finds nothing, open a letter you
know it should match and read the score and the place the picture was found. In any
preview with the box tool (Inbox, Browse, Quick Look, the viewer), the areas of picture
rules that did not match are drawn dashed too, with the score they got on that document, or
the reason there is none (for example that the picture of page 1 is not made yet).

The test runs in the background and fills in as it goes: "Checked 1 240 of 10 875
documents…" with a **Stop** button. It looks at the likely documents first (the ones you
set as from the rule's sender, the ones in the same folder as the document you drew the
boxes on, and for a picture area the pages that look most like it), so real matches show
up early; the final counts are the same in any order. It goes on until every document is
checked, and ends if you stop it, change the rule or close the sheet. After a stop,
**Test again** starts over. If some documents are still waiting for page 1 to be read, it
says "Waiting for page 1 of N" and looks at them again as they are read. **Read page 1 of
these N now** puts exactly those documents first in the page-1 queue and reads them at full
speed, one at a time and with the usual time limit for each; the test picks them up as they
arrive. Without it they are read in the background at the normal pace.

A picture area is only for something that tells who a letter is from or what kind it is.
The address area never takes a picture: a person is found from text only. The picture of
an area is a few KB and is kept with the rules, in `config/rules/areas`. Deleting a rule
leaves its pictures there; Settings → Filing rules lists the ones no rule uses. Next to
that list, **Move N unused pictures to To Delete** shows the plan and, once you confirm,
moves them into `##. To Delete` as `dam rule picture <name>.png`. You empty that folder
yourself, like for any file you mark for deletion. The result has an **Undo** (also in
Activity), which puts the pictures back into `config/rules/areas`; it refuses if a picture
with the same name has been saved there since. Only pictures no rule uses can be moved. If
your rules folder and your archive are on different disks (for example the archive is in
Google Drive), dam copies each picture into `##. To Delete`, checks the copy against the
original, and only then removes its own copy from the rules folder; the plan says
"copied, then removed from dam's settings folder". These pictures are dam's own files, not
documents from your archive. If anything fails, the copy stays in `##. To Delete` and the
original stays too, and the message says so. Undo across disks copies the picture back and
leaves the one in `##. To Delete` for you to empty. Moving or resizing a picture area cuts the picture again from
the document you changed it on.

### Seeing the areas

On page 1 of a preview, **Show areas** (on by default when there are areas) draws the
areas of every rule that matched the document, labelled with the rule's id. The rule that
gave the folder or name is drawn stronger. The lines that matched inside each area are
highlighted; a picture area shows where the picture fits best, with its score ("acme:
picture 0.93"). The address area that was used (the archive's or the rule's own) is drawn
too, with the line where the person was found: "For: Tiina, found here".

In Settings → Filing rules, **Test a document** draws the areas of all rules on page 1.
The areas of rules that did not match are dashed and say why ("no word found in area 2").

### Changing an area

Click an area on page 1 to select it. Drag it to move it, or drag one of its handles to
resize it. When you let go, the rule sheet opens with the changed area and the test runs
again, with a line saying how the rule did before ("Before the change it matched 14
documents"), so you see the effect on the documents you filed before you save. Cancel
leaves the rule as it was. The address area works the same way: a rule's own address area
changes that rule; the area for all letters asks once and is saved to the settings.
Areas cannot be moved while **Draw a box** is on.

In Settings → Filing rules, open a rule that has areas and the sheet shows them on a
sample page: the last document the rule was used on, or any file in the Inbox you pick.
Drag them there in the same way; the test below follows.

### People and the address area

List the people in your household under **People** in Settings → Filing rules: a name
(what `{person}` becomes in a folder or name) and the ways it is written on letters
("Michiel Visser", "M. Visser"). dam looks for them in the address area of page 1 only,
never in the rest of the text, and allows one misread letter in a name of eight or more
letters. Use `{person}` in a rule's folder or name to file per person, such as
`Insurance/Pohjola/{person}`. When nobody is found the rule gives no folder; a letter to
two people asks **For whom?**. The address area starts at the usual place of the address
on a Finnish business letter; change it there or with Draw a box.

The rule sheet's **For** row says who the address area found on the document the rule was
made from ("Tiina, found in the address area", "Nobody found", "Tiina and Michiel found",
or, when the People list is empty, where to add people). Choose **Anyone** or **Only for**
a person from the list; the rule then applies to letters for that person only, and the
test follows. **Use the person in the folder**, on the same row, puts `{person}` in the
Folder field: it replaces a folder part that is the person's name already, else adds
`/{person}` at the end. It is independent of Anyone / Only for: each letter then goes to
the folder of its own person. It works with Anyone, and with Only for it is usually not
needed, because the folder can simply name that person (its ? says this).
A line under the buttons shows where this letter would go ("This letter would go to
50. Medical/Tiina/Kela"). For a rule opened from Settings there is no document, so the
row has the choice but no "found" line.

### From and For on a document

The Inbox card shows **From** (who sent a document) and **For** (who it is for) with where
each came from (address area, a rule, you). Click one to change it. To set them for many documents at once, use
**From…** and **For…** in an Inbox batch or on a selection in Browse. What you set always
wins over what dam detects. Filing a document into a folder made with `{person}` also
records the person. These are kept in dam's index, not in the files.

### Where rules are kept, and in what order

Rules made in the app go to `config/rules/learned.yaml`, which dam reads before the other
rule files. A rule about one sender therefore wins over a broad one such as the shipped
`generic-invoice`. For the folder and name the first matching rule wins; tags from all
matching rules are added together. Rules you wrote by hand in other files keep working
as before. If you edit or delete one of them in the app, dam rewrites that file: the
comments in it are lost, and a `.bak-<time>` copy of the old file is kept next to it.
The sheet and the delete question say so.

### The record

Each rule keeps a record: how often it was suggested and how often you changed what it
suggested. When you corrected a rule in 2 of its last 5 filings it is flagged
"Corrected recently" in Settings, and its suggestion in the Inbox says "this rule was
corrected recently". Undoing a filing removes it from the record.

### The rules list in Settings

Under "This archive", Settings lists every rule in the order dam tries them, with its
words, where it files, its record and any flag. Rules not made in the app show the file
they are in. Click a rule to edit it (the proof is shown there too). You can:

- add a **New rule**, or **Delete** one (dam asks first);
- move rules made in the app up or down with the arrows on their row; rules in other
  files are reordered in their files;
- **Test a document**: pick a file from the inbox and see which rules match it, why
  (the word or pattern that matched) and which field each rule gives;
- turn off "Offer to make a rule after I file a document by hand";
- **Forget N declined senders**, to be offered rules for them again.

Files with rules that could not be loaded are listed at the top, with the reason. The
**People** list is further down on the same page (see
[People and the address area](#people-and-the-address-area)).

### Reading page 1

To match by area, dam keeps the position of the text on page 1 of each PDF and image
when it reads it, and for picture areas a small grayscale picture of the page; this
costs no extra reading for new scans. Documents read before this feature, and PDFs that
have a text layer, get theirs in the background, inbox first, when dam has nothing else
to do.
The Index sheet (click the status line at the foot of the sidebar) has a **Page 1** row in
its totals: how many documents are read, an estimate of the time left while reading goes
on, and how many wait because page 1 cannot be read now and why (for example no OCR
engine, or it took too long). The row links to Settings → Indexing. While reading is not
complete, the status line also says "page 1 read 1 240 of 10 875". Settings → Indexing
has the switch "Read page 1 of older documents in the background" (it pauses the reading)
and **Page 1 reading speed**. PDFs that have a text layer are read quickly (300 a
minute unless you choose another speed), because that takes no OCR; scans and photos need an
OCR engine and are read at the indexer's pace (30 a minute), and so is any file that is slow
to fetch, such as a Google Drive file that has to be downloaded first. The estimate of the
time left adds the two: "about 18 min left (5 000 PDFs with text at 300 a minute, 30 scans
and photos at 30 a minute)".

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
highlight and open the item. An item has a title, one or more files, the tray's fields, a
note, a checklist and a history.

### Row icons

At the right end of a row, before the date, small icons say what the item has: a pencil
for a note, a checklist icon with the number of to-dos still open (hover for "2 of 5
to-dos open"; nothing once all are done), and a sparkle for an AI summary or a text icon
for one you wrote. With several files, a summary you wrote on any of them shows as
written, otherwise any AI summary.

### Working on an item

- Click the title to edit it in place: Enter or clicking away
  saves, Esc cancels, an empty title is refused. The file's tags are right under it.
- The date and **Mark done** are one row. The file's icon buttons are in the header at
  the right, over the item, the same group as in Browse (see below). **Quick Look** is in
  the toolbar of the file preview, with zoom and open.
- Summary, Checklist, Notes and History have an arrow in their heading that folds them to
  one line (for example "2 of 5 done"). Each section stays folded or open the way you left
  it, for all items, collections and documents in this browser.
- **Mark paid** (or **Mark done**) finishes an item; **Reopen** undoes it. It asks in a
  small popover under the button (Enter confirms, Esc or a click outside cancels). While
  one of the item's files is still in the inbox, **Mark paid and file…** marks it done and
  opens that file in the Inbox for filing.
- **Move to tray** (a menu in the header's icons) moves an open item to another tray. It stays
  the same item (title, note, checklist, history and files); fields the other tray also
  has carry over, and the rest come back if you move it back. A file has at most one open
  item at a time.
- **Remove from tray** (the icon in the header, or ⌫) asks first, then deletes the item with
  its note, checklist and history. The files are never touched, so there is no undo for
  this.
- **Back to inbox** (in the header's icons) moves the file the item shows into the inbox, with the usual preview and Undo; the item stays in its tray.
- **Move to To Delete** (the bin, last in the header's icons) acts on the file the item
  shows, with its usual confirm and Undo; the item keeps the file, now shown as in To
  Delete. It is not the same as Remove from tray.

### Files on an item

- **Add another file…** opens a picker: type to search the whole archive (each hit shows
  its path), or choose **Browse folders…** and walk the folders. Click a file, or use the
  arrow keys and Enter, to attach it. Files already on the item are marked and cannot be
  added twice. **Add file** in the list's toolbar searches the archive and makes a new item
  for the file you pick.
- With several files, each file tab has a small **×** (on hover or focus, and always
  reachable with the keyboard). It takes that file off the item; the file stays where it is,
  and **Undo** in the toast puts it back in the same place. An item keeps at least one
  file, so a lone file has no ×.
- **Drag an item onto another one** in the list to merge them. A small dialog asks first;
  then the dragged item's files, notes and checklist are added to the other item and the
  dragged one is removed. The other item keeps its own title, tray, dates and fields.
  **Undo** in the toast restores both as they were, as long as you have not changed the
  other item since.
- **Drag a file** from Browse or the search results onto an item in the list, or onto the
  open item's panel, to attach it. Nothing is moved or renamed.

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
checklist. The selected file shows on the right with its details.

The header has the same two parts as Browse and the trays. The left part is for the
collection: its name and subtitle, **New group**, the folder button, **Export…** and **⋯**.
Over the selected file, at the right, is one group of icons for the file actions, in this
order: **Put in tray** (a menu of the trays), **Remove from collection** (not in Starred and
Important, where the star and the exclamation mark do that), **Back to inbox**,
**Move to…**, **From…**, **For…**, **Ask AI**, **Star**, **Important**, **Restore** (for a
file in To Delete) and **Move to To Delete**. They are the same as in Browse: a move shows
its preview first and has Undo, and the file stays in the collection (it follows the file,
and its row shows the new folder). A greyed icon says why when you hover it: a locked or
Important file, a file in To Delete, a missing file, and a folder (moved from Browse). The
preview's toolbar keeps only the viewing tools and Quick Look. In a narrow window the left
part takes the row and the file actions follow at the right.

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
the middle of another collection in the sidebar or on the Collections page (or onto the
**Collections** caption for the top level; see Order of collections),
or use **Move to…** in its **⋯** menu; **New collection inside…** creates a child. In
`##. Ongoing` a child is a folder inside its parent's folder. A parent with open children
cannot be closed, and a child under a closed parent cannot be reopened.

### Order of collections

Collections are listed in your own order: **Important** and **Starred** always come first
and cannot be moved; the others follow in the order you give them, among the collections
with the same parent. A new collection goes at the end of its siblings, and so does one
you move into another.

Drag a collection (in the sidebar or on the **Collections** page) onto another row. The row
has three zones. The **top third** puts the dragged collection just before the row and the
**bottom third** just after it, shown by a line. The **middle third** puts it inside that
collection, shown by a highlighted row. When the row belongs to another parent, the line
moves the collection to that parent as well, at that place: that is how you take a nested
collection back out. Dropping on the **Collections** heading in the sidebar (or on the
strip that appears above the list on the Collections page while you drag) moves it to the
top level, as the last one. A collection cannot go inside itself or one of its own
collections.

From the keyboard, press **Alt+↑** or **Alt+↓** on a collection, or use **Move up** and
**Move down** in its right-click menu (sidebar and page) or in the **⋯** menu on its page.
For a nested collection **Move out one level** (or **Alt+←**) puts it right after its
parent. Each move is announced. A move within one parent changes only the order: no file
or link moves.

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

Clicking a file name in the **Starred** card on Today opens Browse in the folder the file
sits in, with the file selected and previewed; Back returns to Today. On a collection's
own page, Starred and Important included, a click selects the file there, and **Show in
folder** in the file's panel opens it in Browse.

Mark or unmark with one click wherever a file is shown. **Marking never moves or renames
a file.** A file marked Important cannot be moved to To Delete (unmark it first), nor can
a folder holding one. An Important file is also locked (see the next section).

## Locking a file

A lock is a safety catch against slips, such as a drag and drop in the wrong place. A
locked file can still be viewed and described: tags, notes, checklists, From and For,
trays, stars, the Important mark, summaries and previews all work. What it refuses is
anything that changes the file on disk: rename, move (also drag and drop, Move to… and
Back to inbox), filing from the Inbox, and Move to To Delete. A locked file shows a closed padlock in lists and in its details, and those controls are
off, with the reason as their tooltip.

The padlock beside a file's name is also its button. A closed padlock means locked;
an open one means not locked.

- **Important files are always locked.** Click the closed padlock (**Unlock**) to unlock
  one **for now**.
- **Any other file can be locked** with the open padlock (**Lock**). Click the closed
  padlock (**Unlock**) to unlock it again; it asks **For now** or **For good**. For good
  removes the lock.
- **For now lasts until you leave the file.** The details say "Unlocked until you leave
  this file", with an open padlock, **Lock again**. Select another file, close the panel,
  go to another page or reload, and the file is locked again. While it is unlocked you can
  make as many changes as you like.

If a change would touch a locked file, dam refuses the whole change before anything moves
and says "This file is locked. Unlock it to change it." For several files at once it
names the locked ones. There is no password: the lock stops mistakes, not other people
using your computer. Undo still works on a locked file, since it only puts back what you
did.

## Browse

Browse shows the archive's folders, with search. Click a file, or step to it with `j`/`k`,
and the detail beside the list shows the file view: name and folder, tags, collections,
summary, actions, the preview and the note. Folders open on click. Drag the edge between list and detail to change the
list's width.

- **Two panes**: the split toggle in the toolbar shows two folders side by side, for
  moving files between them. The active pane has an accent edge.
- **The file actions** are one group of icons at the right of the header, over the file
  pane, and the trays have the same group over the item. In this order: **Put in tray**
  (a menu of the trays), **Back to inbox**, **Move to…** (⇧⌘M), **From…**, **For…**,
  **Ask AI**, **Star**, **Important**, **Restore** (for files in To Delete) and **Move
  to To Delete**. They act on the selected files; **Ask AI** needs exactly one file shown
  in the preview. A greyed icon says why when you hover it. The preview's own toolbar
  keeps only the viewing tools. A move always shows its preview first.
- **Restore.** What is in `##. To Delete` is read-only: starring, Important, trays,
  collections, tags, From and For, the summary and the notes are off (hover a greyed
  control for "Marked for deletion: restore it first"), and so is moving it. To get a
  file back, select it, or several with the checkboxes or Select all, and use **Restore**
  in the header, or the two buttons in the file's panel. **Restore to where it was**
  puts it back at the path it was marked at; **Restore to Inbox** puts it in the inbox. A
  folder marked for deletion has the same two choices in its right-click menu and its
  panel. The preview shows a folder that is gone being made again and a name that is
  taken getting a number (`_2`). Nothing is deleted; Activity shows "Restored 3 files
  from To Delete" and Undo puts them back in To Delete. The tags, collections, notes and
  tray items the files had are still there. A file that stood at the top of the archive,
  or in `##. Ongoing`, can only be restored to the inbox.
- **Collection** filters a pane to one collection's files; **Folders / Files** switches
  between the folder view and a flat list of every file below the current folder, with
  sortable Name, Folder, Date and Size columns (up to 500 rows).
- **Search** looks at file names, paths and text (the Search card on Today opens Browse
  with the same search). Beside words it takes filters such as `tag:medical`, `type:pdf`
  or `-in:"90. Other People"`; each finished filter becomes a chip in a row under the
  pane's toolbar and the search box keeps only the words. See [Searching](#searching).
- **Search results by folder.** With **Folders** selected, results are grouped under the
  folders that hold them: one header per folder with its path and the number of matches,
  folders in the order of the folder tree. The arrow at the left of a header folds the
  folder's files (all are open at first, and a new search opens them again). Click the
  folder's name to open that folder in Browse; this ends the search. Rows under a header
  select, preview, drag and Quick Look as usual, and the arrow keys skip the headers.
  **Files** shows the flat list with the Folder column.
- **Links.** A link to a file inside the archive previews and opens as that file, with
  **Go to target**. A link to something outside the archive only has Show in Finder.

## Searching

The search box in Browse (and the Search card on Today, which opens Browse) takes plain
words, which search file names, paths and the text of the files, and **filters** of the
form `name:value`. The **?** next to the box lists them; a click on an example puts it in
the box. A search with only filters lists the matching files by name.

| Filter | Finds | Example |
|---|---|---|
| `name:` | Words in the file name only. `*` stands for any text and `?` for one character. Without a `*` or `?` the text can be anywhere in the name; with one, the pattern must fit the whole name. | `name:*kela*`, `name:2026*` |
| `in:` | Files in a folder and the folders below it (the case of the name is ignored). | `in:"50. Medical"` |
| `tag:` | Files with the tag. | `tag:insurance` |
| `collection:` | Files in a collection, including the collections inside it and, for a folder that is a member, the files in that folder. | `collection:"House sale"` |
| `from:` | Files whose sender (From, as you set it on the file) contains the text. | `from:Kela` |
| `for:` | Files whose person (For) is that person. Only what you set, or what a confirmed filing recorded, is searched; the names found on page 1 are not. | `for:Tiina` |
| `type:` | The kind of file: an extension (`pdf`, `docx`) or a group: `image`, `doc`, `sheet`, `slides`, `text`, `mail`, `archive`, `audio`, `video`. | `type:pdf`, `type:image` |
| `date:` | The document date: the date at the start of the file name (`20261003_...`), and for a file without one the date it was last modified, which is the Date column in Browse. Takes `YYYY`, `YYYY-MM` or `YYYY-MM-DD`. | `date:2026-10` |
| `after:` | Dated on or after the first day of that year, month or day. | `after:2025` |
| `before:` | Dated before the first day of that year, month or day. | `before:2026-06` |
| `tray:` | Files with an open item in that tray, by its id or name. | `tray:to-pay` |
| `is:` | `starred`, `important`, `locked` (the locks you set yourself; Important files are always locked but are found with `is:important`), `todo` (an open checklist entry on the file or on its open item), `note` (the file has a note), `summary` (the file has a summary), `disconnected` (the file is in an archive folder that is not connected now; see [Several archive folders](#several-archive-folders)). | `is:locked` |

Tips:

- Put a value with spaces in quotes: `in:"50. Medical"`.
- A `-` in front leaves out what matches, for any filter: `-tag:paid`,
  `-in:"90. Other People"`.
- Filters combine with each other (a file must satisfy all of them) and with words:
  `kela type:pdf after:2025`. Two `tag:` filters need both tags unless you pick **Any**
  in the filter row, which asks for at least one.
- Typing the start of a filter name (`col`) offers `collection:`, and after the colon the
  collections, tags, people, senders, trays, folders or file types that fit. Enter or a
  click takes a suggestion; a finished filter followed by a space becomes a chip. The cross on a chip
  removes that filter.
- A word with a colon that is not a filter name (such as `http:`) is searched as text. A
  date that does not exist, or an unknown `is:` word, is refused with a message.
- The whole search is in the address (`/browse?q=kela type:pdf`), so Back and a copied
  link bring the same search.

## Tags

The **Tags** screen (sidebar, under Collections) lists every tag with the number of files
that have it, with a filter box. Click a tag to see its files in Browse. Each tag has a
menu, and every change shows a toast with **Undo**:

- **New tag** makes a tag with no files; it stays until you use or delete it.
- **Rename** changes it on every file. If the new name is another tag's, dam offers to
  merge instead.
- **Merge into** (or tick tags and use **Merge selected**) puts the tag you keep on all
  their files and removes the others. The sheet first says what happens, such as "3 files
  get 'medical'; 'health' is removed".
- **Delete** removes the tag from all its files after a confirm that names how many.
- **Pin to the sidebar** puts a tag first in the sidebar's Tags section; the rest of its
  eight places go to the tags you put on files most lately.
- **Groups**, one level: **New group** makes a heading such as Health; move a tag into
  it from its menu or by dragging it onto the group. A tag is in at most one group.
  Groups only arrange this screen. A group has its own menu to rename or delete it;
  deleting a group keeps its tags, ungrouped.

**Searching by tag.** Type `tag:medical` in a search, or click a tag here or in the sidebar,
and Browse shows the files with that tag (see [Searching](#searching)). With several tags,
**All / Any** in the filter row picks files with every tag or with at least one.

Tags are kept in dam's own database, not in the archive, so changing them moves no file.

## Quick Look and the viewer window

**Space** opens the selected document nearly full window: zoom (the buttons, ⌘-scroll,
`+`/`−`/`0`), drag to pan, page through it, and see its details. It opens at Fit, the whole
page visible. `→`/`←` (or `j`/`k`) go to the next or previous document of the list; Space
or Esc closes it. It works in the Inbox, the trays, a collection and Browse.

The printer button next to the zoom buttons (in the file view, Quick Look and the viewer
window) prints a PDF or an image through the browser's print dialog: every page of a PDF
(up to 300), one page per sheet of paper.

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

## Maintenance

**Maintenance** (sidebar, Archive) holds checks for tidying the archive. Nothing on it runs
by itself or in the background: a check starts when you click its button, shows how far
it has come, and has a **Stop** button. Leaving the screen stops a check that is running.
A check ends in a list, and what you do with the list is the usual previewed batch: you
see every operation first, confirm, and the toast offers **Undo**. Nothing is ever deleted.

Each check's card folds to one line with the arrow before its title (what it found, or
that it has not run); **Collapse all** and **Expand all** are in the toolbar, and dam
remembers the folds in this browser. The reset icon at the top right of a card forgets
that check's result (and ends it if it is running), and **Reset all** in the toolbar
forgets every result, so the screen is as before any check
ran. Reset changes nothing in the archive.

**Ignore** on an entry leaves it out of that check's results from then on, for example a
duplicate you want to keep or a folder that is meant to be empty. dam keeps the ignored
entries with the archive, so they stay ignored after Reset and after a restart. A card's
**ignored entries** link lists them, each with **Stop ignoring**. An ignored duplicate group
shows again when a new copy with the same content turns up, and the same goes for a name
shared by files with different content. Waiting in To Delete has no Ignore: it is a
reminder. Ignoring changes nothing in the archive.

### Duplicates

**Find duplicates** looks for files with exactly the same content.

- Before you start, the card says how many files will be read and how big they are. Only
  files that share a size with another file are read at all, and a file read before (its
  fingerprint is stored in the index) is not read again. Empty files, links, and the app's
  own folders (`##. Ongoing`, `##. Important`, `##. To Delete`) are left out.
- **Google Drive for desktop:** reading a file that is kept online-only downloads it. The
  card warns about this when there is something to read. **Stop** ends the check at any
  moment; the fingerprints already made are kept, so the next run goes on from there.
- **Identical copies** come in groups. In each group you pick the copy to **Keep**. The
  suggestion is a copy in a numbered folder rather than in the Inbox, then the oldest; a
  copy marked Important or locked is suggested first, because it cannot be removed. A copy
  marked Important or locked is never removed, and the row says it stays.
- Each copy shows its folder, and under it its size and date, and its name too where it
  differs from the group's name.
- Each other copy has three icons: **leave** it where it is, move it **to To Delete** (the
  starting choice), or replace it with a **link**: the copy goes to To Delete and a link to
  the kept copy is put at its old path, so anything that points there still opens the
  file. Copies in one group can have different choices.
- **Apply** under a group does what its copies are set to; **Apply the ticked groups** does
  every ticked group at once, and **Set every copy in them to** To Delete or Link sets all
  their copies in one click. The preview lists every operation. It is one batch and one
  Undo: Undo removes the links and brings the copies back. (On Windows, links need
  Developer Mode.)
- **Also add what the removed copies had** (ticked by default) adds their tags,
  collections, star, note, checklist entries, tray items and From and For to the kept copy.
  The preview lists exactly what will be added. It only adds: a note is appended below the
  kept copy's note, and a From or For the kept copy already has is not replaced. Undo takes
  back the collection memberships and a note that the batch created; tags, appended text
  and the other additions stay, and you can remove them by hand.
- **Same name, different content** lists files whose names are the same (ignoring case)
  but whose content differs. These are probably versions of a document, or the same
  document saved another way (a PDF exported twice, say). **Compare side by side** shows
  two of them next to each other in the preview, with one zoom for both, and **Keep this
  one** under each. Each file then has the same choices as an identical copy (leave, To
  Delete, link), but every file starts as **leave**, so nothing happens until you choose.
  The preview says the files are not copies. There is no bulk Apply for these: each name
  is decided on its own. Suggested to keep: a file that is Important or locked, then one in
  a numbered folder, then the newest.

### The other checks

- **Empty folders** (not the top level, not the app's own folders, and not the folders the
  archive is set up with, such as `##. Organize/To pay`, which may well be empty): tick
  the ones to **Mark for deletion**; the folder moves to To Delete like a file.
- **Broken links**: links whose target is gone. A broken link in `##. Ongoing` or
  `##. Important` can be removed (the app may remove links there). Everywhere else a link is
  moved to To Delete, which you can Undo. Undo of removing a link in Ongoing or Important
  cannot make a link to a file that is gone, so that one stays removed.
- **Collections and trays**: collection members and files of open tray items that are gone
  or in To Delete. Each entry links to its collection or tray item and shows where the file
  is, or for a gone file where it was last seen. **Take out** removes a gone file from its
  collection (there is no Undo, because the file is gone). A file in To Delete keeps its
  entries, so it comes back with them if you restore it. For a tray item, open the tray and
  take the file out or mark the item done.
- **File names**: files in the numbered folders whose name does not start with
  `YYYYMMDD_`, with a suggested name from the date the name already starts with, else the
  document date, else the day the file was last changed. **Rename** is the normal previewed
  rename.
- **Waiting in To Delete**: files that have been in To Delete longer than a number of days
  (30 to begin with; change the number). It shows how many and how big. dam never empties
  To Delete: when you are sure, empty it yourself in Finder (or File Explorer). How long a
  file has waited comes from the Activity journal; for a file put there some other way it
  is the time the file last changed place, marked "about".
- **Unfinished copies**: copies a move to another disk left half done when it failed, was
  stopped or the app was closed. Their names start with `.dam-copy-`, which Finder and File
  Explorer hide until you show hidden files. The original was never moved for them, so
  each is a spare copy you can remove yourself; dam never deletes. A copy shows up here
  after the next scan.
- **Moved outside dam**: files that were renamed or moved in Finder (or File Explorer)
  and so lost their tags, notes, collections, tray items, From and For and the rest. This
  happens to files without a Google Drive id (on Windows and Linux, all files): dam knows
  such a file by its place only, so after the move it sees a new file and marks the old
  one missing. The check pairs a missing file that had something with a new file that has
  nothing, when both have the same size and the same content. It reads the new files of a
  matching size to compare them (Stop works as for duplicates); a missing file can only be
  compared when dam read it before it moved. Each pair shows the old and the new place and
  what would move. **Reconnect** (on a pair, or for the ticked pairs) shows a preview and
  then gives the file back what it had. This changes only dam's own records, never the
  files, so it is not in Activity; **Undo** in the message afterwards puts the old,
  missing file back with what it had, and leaves what you gave the file since with it.
  Undo is refused for a file when another file is now indexed at its old place. A file
  whose content matches more than one file is listed but not reconnected, because dam
  cannot tell which one it is.
- **Left alone after a Drive restart**: the links and folders dam made in ##. Ongoing and
  ##. Important that it now leaves alone because they look different from before. dam
  knows each entry it made by its device and inode number. When Google Drive for desktop
  restarts, its folder can get a new device number, and then every entry looks like
  something else and is no longer kept up to date. The check lists, per folder, the
  entries that kept their place, kind and inode number but have another device number.
  When only the device number changed, the same way for every one of them, and they are
  on the same device as the folder itself, **Take over** shows a preview and then records
  the new number, after which dam keeps them up to date again. Nothing on disk changes,
  it is not in Activity, and **Undo** in the message afterwards puts the old numbers back.
  A folder where an entry also has a new inode number, or whose entries came from more
  than one device, stays left alone and the check says why: dam cannot then be sure the
  entries are still its own.

## Settings

Settings is where dam's own options are kept. The row at the top has one section for
each area, grouped by what it applies to; one section shows at a time.

- **This archive** (the one open now; each archive has its own):
  - **Filing codes**: your table of codes, one line each; click one to edit it. **Add a
    code** adds one, **Print stickers…** prints sticker sheets, and the bar at the bottom
    saves or discards your changes. Missing inbox folders, and inbox folders that belong
    to no code, are pointed out above the list. See [Filing codes](#filing-codes) and
    [QR stickers](#qr-stickers).
  - **Filing rules**: every rule in the order it applies, with its record; edit, test,
    delete or add rules, test a document from the inbox, and switch the offer to make a
    rule on or off. The **People** list and the address area are here too. See
    [Filing rules](#filing-rules).
  - **Archive folders**: the main folder and any extra folders, each with its status
    (Connected, Not connected or Detached), **Add folder**, **Detach**, **Attach again** and
    **Forget**.
    See [Several archive folders](#several-archive-folders).
  - **Indexing**: whether page 1 of older documents is read in the background, and the
    **Page 1 reading speed** for PDFs that have a text layer. See
    [Reading page 1](#reading-page-1).
  - **Snapshots**: take a snapshot of this archive's database and settings, export or
    import one, and restore one. See [Snapshots](#snapshots).
- **This browser** (every archive alike):
  - **Appearance**: Light, Dark, or Auto to follow your system setting. It applies at
    once, and is remembered by this browser (another browser starts on Auto).

### Snapshots

**Settings, Snapshots** keeps snapshots of what dam knows about this archive: the
database (the index, tags, collections, notes, checklists, tray items, activity and
Undo) and the settings (rules, trays, filing codes, people, archive folders, the AI
on/off switch). Your documents are not in a snapshot; back those up with your cloud
drive or your usual backup. The AI key and the e-mail password stay in the Keychain
and are not in a snapshot either.

- **Take snapshot** takes one while dam keeps running. Snapshots are kept in a
  `snapshots` folder inside the archive's data folder; **Show folder** opens it.
- A snapshot in the data folder is on the same disk as dam, so it helps when a change
  goes wrong but not when the disk or the computer fails. **Export** on a snapshot
  saves the zip through your browser: keep it on another disk, a NAS or a cloud folder.
  Export only copies the file, so copying it from the folder yourself (or letting your
  usual backup pick up the `snapshots` folder) works just as well.
- **Import…** adds a snapshot zip you saved earlier (on this computer or another one).
  dam checks the whole file first and adds it to the list marked "imported"; nothing is
  restored until you choose **Restore…**. You can also copy a snapshot file into the
  `snapshots` folder yourself: it shows in the list as long as its name still has the
  form `dam-snapshot-YYYYMMDD-HHMMSS.zip` (a browser may add `(1)` to a second download;
  rename it back, or use Import, which takes any name). It is then checked when you
  restore it rather than when it is added.
- dam never removes a snapshot. Remove old ones from the folder yourself.
- **Restore…** first asks **Take a snapshot of the current state first?** **Take
  snapshot and restore** keeps the state you have now as a snapshot (listed as "taken
  before a restore") and then restores; **Restore without snapshot** restores straight
  away; **Cancel** changes nothing. The archive then closes and opens again, and the
  window reloads.
- A snapshot of another archive folder (for example from your old computer, where the
  folder had another path) is marked "Of another archive folder". To restore it, tick
  the box in the restore sheet: dam then restores it but keeps this archive's own
  folders in the settings. Do this only for the same documents.
- A restore always keeps this archive's own folders, its protected paths and the folders
  never sent to AI as they are now. The snapshot can add protected paths or excluded
  folders, but not remove any.
- After a restore, Activity and Undo go back to the moment of the snapshot. Files moved
  since then are found again when dam scans the archive. The settings that were
  replaced are moved to a `replaced-…` folder beside the snapshots, not deleted.
- A snapshot taken by an older version of dam is updated when it is restored. One from a
  newer version cannot be restored or imported; the list says why.

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

## Several archive folders

One archive can span several folders, for example a synced cloud folder for current
papers and an external disk for the old years. Search, Browse, tags, collections and
Maintenance treat them as one archive. (Several *archives* are separate; see above.)

- **Add a folder**: Settings, **Archive folders**, **Add folder**. Give it a label and its
  path. The label is the name the folder has at the top of Browse and in paths (you can
  change it later, see below). A label cannot be empty, cannot start with `##.`, and cannot
  be the name of a folder already in the main folder or the label of another archive
  folder (case is ignored). dam also refuses a folder that is, contains or sits inside
  another folder of this or any other archive, or that cannot be read, and says why. Adding
  changes nothing on disk; dam then indexes the folder like the main one.
- **The main folder stays special.** The Inbox, `##. Ongoing` and `##. Important` live only
  in the main folder. A folder with one of those names inside an extra folder is an
  ordinary folder.
- **Each folder has its own `##. To Delete`**, made when you first move something to it.
  Moving a file to To Delete is a rename, which cannot cross disks, so a file goes to the
  To Delete of the folder it is in, and Restore brings it back there. The To Delete views
  list them all. You empty them yourself, as always.
- **Moving between folders**: on the same disk a move is a rename, as anywhere else. To a
  folder on another disk (drag, Move to…, or Restore to a folder there), dam copies each
  file, checks the copy against the original (its size and its content), keeps the file's
  modification date, and only then moves the original to the To Delete of the folder it
  came from. Nothing is deleted: you empty To Delete yourself once you are happy with the
  copies. Tags, notes, collections, tray items and locks move with the file.
  - The preview says how many files are copied, how big they are, and how many are in the
    cloud only: those are downloaded first, which takes longer. It also checks that the
    other disk has room for all of them.
  - The move runs in the background. A dialog shows the files and the amount copied and
    the file being copied; **Hide** leaves a line at the bottom of the window, and you can
    keep working. Closing the window does not stop the move. **Stop** lets the file being
    copied finish (its original goes to To Delete too) and ends there, so every file is
    either moved or untouched; move the rest later. The amount copied moves along within
    a large file too. While a large file is being copied,
    other changes (another move, a rename, an undo) wait until that file is done, and
    Undo waits until the whole move has finished.
  - **Undo** (in the toast or Activity) moves the originals back from To Delete and the
    copies to the To Delete of the other disk.
  - If a copy does not match, or the app is closed during a copy, the move stops there
    and the message names the unfinished copy (its name starts with `.dam-copy-`). The
    original is untouched; remove the unfinished copy yourself. Maintenance lists any
    that are left under **Unfinished copies**.
  - A name that is within 19 characters of the longest name a disk takes (255 bytes) is
    refused in the preview, because the copy is first written under a longer temporary
    name. Shorten it and move it again.
  - A protected file is not copied across.
- **Moving a folder**: drag a folder row in Browse onto a folder row, the other pane or a
  breadcrumb, or use **Move to…** in the folder's panel. One folder moves at a time, and a
  folder drop offers Move only (no Link or Copy). The top of an archive folder, `##. Ongoing`,
  `##. Important`, `##. To Delete`, the inbox and anything inside them stay where they
  are, and a folder cannot go into itself.
  - On the same disk it is one rename, with its files, tags, notes and collections going
    along. A taken name gets `_2` (the preview says so). Links inside the folder move with
    it.
  - On either kind of move the preview warns about links that will point to nothing: links
    elsewhere that point into the folder and, on the same disk, links inside it that point
    into it. Links in `##. Ongoing` and `##. Important` are left out.
  - To a folder on another disk dam makes the folder tree there (empty subfolders too),
    copies and checks every file as above (modification dates kept), and only when every
    file is copied moves the whole original folder to the To Delete of its own archive
    folder. The preview lists the links inside that are not copied (they go to To Delete
    with the folder).
    The folder's own collections and notes follow it. The move runs in the background as
    above, and **Undo** puts everything back and removes the folders it made while they
    are empty.
  - **Stop** ends the move after the file being copied. The original folder stays whole
    where it is, and the copies made so far stay at the destination. Move the folder again
    to finish: it merges into the folder already there and skips files already copied
    (checked by content), so nothing is duplicated. To undo both, undo the second move
    first: until then the first one cannot be undone, because its copies are the only
    ones left outside To Delete.
  - If the original folder changed during the move (a file added, removed, renamed or
    edited after it was copied), the last step stops: nothing goes to To Delete, the
    message names what changed, and moving the folder again copies the rest. An edited
    file is copied next to its old copy as `name_2`; the old copy is never overwritten.
  - A folder that holds an unfinished copy (`.dam-copy-`) or a protected file is refused,
    and so is one holding two names that differ only in case or accents (`a.pdf` and
    `A.pdf`, possible on some disks): rename one of them first.
    `.DS_Store` files are not copied.
- **A folder that is not connected** (unplugged disk, cloud drive not signed in) gets a "Not
  connected" mark on its row in Browse. Its files stay in the index, search and
  collections, where they carry the same mark, and are not marked missing; the file view says the folder is not connected
  and turns off Open and Show in Finder until it is back. `is:disconnected` finds them,
  and `-is:disconnected` leaves them out. Changes that involve the folder are refused
  until it is back. dam looks about every 30 seconds and picks the folder up by itself;
  nothing needs restarting. Links in `##. Ongoing` and `##. Important` that lead into it
  are left alone.
- **Detach** takes a folder out of the archive; it changes nothing on the disk. Its files
  leave Browse and search, but their tags, notes and collection memberships are kept, and
  **Attach again** brings everything back. Tick **Also forget their tags, notes and
  collection places** to drop them as well (the confirmation says how many files); the
  folder then leaves the list and its label is free for another folder. A folder that is
  already detached has **Forget** for the same. Links that lead into a detached folder are
  left alone.
- **Maintenance** marks links into an unplugged or detached folder as "Folder not
  connected" or "Folder detached" instead of broken, and **Archive folder names** lists a
  folder at the top of the main folder that has the same name as an archive folder. The
  archive folder wins: rename the folder in the main folder, or detach the archive folder
  with Also forget.
- **Change label**: on an extra folder's row in Settings, **Change label** gives the folder
  a new label. **Preview** says how many index and history entries change and which
  settings and rule files are edited; **Change label** then does it. Nothing on the disk
  changes, the folder keeps its files, tags and notes, earlier changes can still be undone,
  and protected folders, folders kept from AI, the `folder` and `folder_is` values in
  your rules and the folders of your filing codes follow the new label. The rule files are edited value by value, so your
  comments and layout stay; a value written over several lines is refused with its file
  and line, for you to change by hand. dam takes a snapshot first (Settings, Snapshots,
  marked "before a label change") and reopens the archive.
- While a Maintenance check, a rule replay or a move to another disk runs, adding,
  detaching, attaching and changing a label are refused until it has finished.

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
| A file, onto a folder in Browse (a folder row, the other pane, or a breadcrumb) | **Move, Link or Copy, always behind a preview and confirm**, with **Undo**. The confirm has the three ways side by side: **Move** (the default), **Link** (a shortcut in that folder that opens the file; the file stays where it is; Undo removes the shortcut) and **Copy** (marked "not recommended: makes a duplicate"; Undo moves the copy to To Delete). Hold **Option** (Alt) while dropping to start with Copy. A taken name gets `_2`. |
| A folder row, onto a folder row, the other pane or a breadcrumb | **Move** only, behind a preview and confirm ("Move folder" on one disk, "Copy and move" to another disk), with **Undo**. See **Moving a folder** above. |
| The file's own folder | Move and Link are refused with "Already in this folder". Copy works if you hold Option while dropping (the copy gets a number). |
| A row of `##. Ongoing` onto a folder | Move moves the **real file** (the link's target), not the link. The confirm names the folder it is in now and where it goes; it stays in its collections and the link in Ongoing follows. Link and Copy use the original. |
| A row of `##. Important` onto a folder | Link and Copy use the original. Move is refused: "This file is marked Important; unmark it first". |
| A row of `##. To Delete` onto a folder | A **restore** into that folder, with a preview and Undo (which puts it back in To Delete). No Link or Copy. |
| A collection's folder in `##. Ongoing` | **Adds the files to that collection** (with Undo); the link appears when Ongoing is updated. Nothing is moved. |
| `##. Ongoing` itself, `##. Important`, `##. To Delete`, the top of the archive, search results | Refused. While you drag, the reason shows on the folder or pane itself, and dropping there anyway shows it as a message. To send a file to To Delete use **Mark for deletion**. |

Every drop has a keyboard or menu equivalent: the Inbox form, **Put in tray…** and **Add
to collection…** on a file, the group menu, and **Move to…** in Browse (for a file or a
folder). A folder can also be dragged to a collection in the sidebar. Breadcrumbs take
file drops too. A drop that is refused shows the reason.

Link needs permission to make links. On Windows that means Developer Mode; without it Link
is off in the confirm, with the reason, and Copy still works.

## What dam never does

- **It never deletes your documents.** **Move to To Delete** (⌘⌫) moves a file into
  `##. To Delete`, keeping its original path; you empty that folder yourself, or
  **Restore** a file from it (previewed, with Undo). The only
  things dam ever removes are its own links and its own empty folders in `##. Ongoing` and
  `##. Important`, and only after checking they are still exactly the ones it made. The one
  exception: **Undo** of a **Link** (a drop that made a shortcut anywhere in the archive)
  removes that shortcut, and only while it is still a shortcut pointing at the same file; a
  regular file, a folder or a shortcut you made yourself is never touched.
- **It never moves or renames a locked file.** Important files are always locked, and you
  can lock any file; you unlock it on purpose, and for Important files only until you
  leave the file.
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
