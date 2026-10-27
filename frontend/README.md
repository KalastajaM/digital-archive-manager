# dam frontend

React + TypeScript + Vite single-page app for the Digital Archive Manager. It talks only
to the JSON API under `/api`. `dam serve` serves the production build from `frontend/dist`.

## Node version

Use Node 22 or 24 (LTS); `.nvmrc` says `24` (`nvm use`). `package.json` declares
`"engines": {"node": ">=22 <25"}`: Vitest 5 and jsdom 30 do not support the odd-numbered
Node 25, and npm warns (EBADENGINE) when it is used.

## Commands

```sh
npm ci                # install the pinned dependencies
npm run build         # type-check and build into dist/ (what `dam serve` serves)
npm test -- --run     # Vitest + Testing Library (jsdom)
npm run gen:api       # regenerate src/api/schema.d.ts from the backend's OpenAPI schema
```

`gen:api` runs `dam --data-dir <throwaway> openapi` against a temporary data dir whose
settings point at an empty folder, so it never reads your archive or data dir. It writes
`openapi.json` (not committed) and then `src/api/schema.d.ts` (committed). Run it after
changing the API's routes or schemas.

## Development

Run the backend and the Vite dev server side by side:

```sh
# terminal 1 (from backend/)
DAM_DEV_ORIGIN=http://localhost:5173 uv run dam serve --no-open

# terminal 2 (from frontend/)
npm run dev           # http://localhost:5173
```

Vite proxies `/api` to `http://127.0.0.1:8765` with `changeOrigin: true`. The API refuses
anything that does not look local (see `backend/src/dam/api/security.py`):

- **Host** must be exactly `127.0.0.1:<port>` or `localhost:<port>`. `changeOrigin`
  rewrites it to `127.0.0.1:8765`; without it every request gets 403.
- **Origin** on POSTs must be the server's own origin or `DAM_DEV_ORIGIN`. The proxy keeps
  the browser's `Origin: http://localhost:5173`, so `DAM_DEV_ORIGIN` must be set to exactly
  that. If you open the dev server as `http://127.0.0.1:5173` instead, set
  `DAM_DEV_ORIGIN=http://127.0.0.1:5173`. Only `http://localhost:<port>` and
  `http://127.0.0.1:<port>` are accepted; other values are ignored with a warning.
- **Sec-Fetch-Site** from the browser is `same-origin` (page and `/api` are both on
  port 5173), which passes. `cross-site` is always refused.
- POSTs must send `Content-Type: application/json` (the client always does).
- **Sign-in**: every `/api` request needs the cookie that the sign-in link sets
  (`backend/src/dam/api/auth.py`). With `DAM_DEV_ORIGIN` set, `dam serve --no-open` prints
  the link as `http://localhost:8765/auth?t=...`: open it once, it sets the cookie on
  `localhost` (cookies do not depend on the port, so the page on port 5173 sends it too,
  and the proxy passes it on) and redirects to `http://localhost:5173/`. `dam open --print`
  prints the link again. Without the cookie the page shows "Not signed in".

The dev server port is fixed at 5173 (`strictPort`) so it always matches `DAM_DEV_ORIGIN`.
If the backend uses another port (`dam serve --port`), change the proxy target in
`vite.config.ts` too.

## Layout and design system

- `src/theme.css` holds the design tokens (type scale, spacing, radii, shadows, motion
  and every colour, light and dark). It is the only place with colour values; screens use
  classes and these custom properties, and `prefers-color-scheme` switches the theme.
- `src/components/ui/` holds the shared Mac components: `Sidebar` (the app's navigation,
  with the tray and collection rows as drop targets), `Toolbar` (every screen's header:
  title, subtitle, icon buttons, search), `IconButton` (a Lucide icon with a tooltip,
  its shortcut, and `disabledReason` for a disabled one), `Segmented`, `Sheet` (the
  confirm dialogs: a fixed title and `footer`, a scrolling body), `Card`, `Tag` (red,
  orange, grey, blue, green), `EmptyState` and `Menu` (entries take a `reason` for a
  disabled one, shown under the label). New screens are built from these.
- `src/App.tsx` is the shell: the sidebar, the banners (archive unavailable, recovery),
  and the routes: `/` Today, `/inbox`, `/trays/<id>`, `/collections` and
  `/collections/<id>`, `/browse`, `/ask` (AI questions), `/activity`, `/ongoing`
  (Convert ##. Ongoing) and
  `/viewer/<drive id>` (the separate viewer window, without the sidebar).
- Drag and drop is native HTML5 (`src/dnd.ts`: the payload is
  `application/x-dam-files` for files, `application/x-dam-collection` for a collection
  dragged in the sidebar tree, `application/x-dam-card` for cards; a target reads one
  kind and ignores the others); Quick Look is `components/QuickLook.tsx` with
  `useQuickLook`; the viewer window follows the selection over a `BroadcastChannel`
  (`src/selection.ts`).
- Parent collections: `components/collectionTree.ts` holds the tree helpers
  (`childrenOf`, `pathOf`/`pathLabel`, `isWithin`, `moveRefusal`, `movedText` with the
  "(recreated N links)" note past 50, `subtreeOf`, and the one-move-at-a-time guard
  shared by the sidebar drag and **Move to…**); `components/MoveTo.tsx` is the picker
  sheet. The sidebar's folds are in `localStorage` (`dam.sidebar.collections.folded.v1`,
  every access in try/catch). `components/collectionText.ts` has the server's status
  prefixes (`not managed: `, `not shown: `) and the close refusal text the ⋯ menu shows.
- Browse keeps each pane's state (`path`, `collection`, `view`) in the URL
  (`?path=&collection=&view=` for one pane, `left`/`right` + `lcol`/`lview`/`rcol`/`rview`
  for two); the Files view is `useBrowseFiles` (`FLAT_LIMIT` 500) and the filter chip
  and picker are in the pane bar. `FilePreview` renders a link as `LinkPreview` ("Link to
  …", **Go to target** → `/browse?path=<folder>&select=<id>`).
- AI (Phase 3) is in `src/components/ai/`: `SendSheet` (the "What will be sent" sheet:
  task, model, cost, budget, the exact text; arming as the confirm sheets), `useAI.tsx`
  (`useAIState` hides every AI button while AI is off or has no key and shows the
  "Turn on AI" hint; `useAISend(task, onResult)` prepares, shows the sheet and runs the
  prepared token only on Send), `AIBadge` (the per-field marker on the review card),
  `SummaryBox` (a file's summary: the bill/item view and the Browse file panel) and
  `AIProposal` (a collection or group summary line with Use or Discard). The screens:
  the Inbox review card and Today (**Ask AI**), the item view and Browse (the summary
  box), a collection (**Summarize with AI**), **Ask** (`screens/Ask.tsx`: answers with
  numbered citations that open Quick Look, kept in the query cache for the session) and
  **Activity → AI** (the call log, the month's spend and the on/off switch). Untrusted
  AI text is always shown through `visible()`.
- `public/manifest.webmanifest` and the icons make the app installable as its own window
  (see the top-level README, "Run it as its own app window").

## Trying the full flow against the demo archive

The demo archive is a throwaway folder with about a dozen sample files: a bill that is
already overdue, a water bill with a printed bank barcode, a collection with nested groups
(already published in `##. Ongoing`), and a `##. Ongoing` with two links, a real folder
and a real file. Your real archive is never touched. From `backend/`:

```sh
cd ../frontend && npm run build && cd ../backend   # dam serve serves frontend/dist
uv run python -m dam.demo /tmp/dam-demo   # must not exist or be empty
uv run dam --data-dir /tmp/dam-demo/data serve --port 8766
```

`serve` opens http://127.0.0.1:8766 in your browser (add `--no-open` to open it
yourself). Port 8766 keeps the demo apart from your own `dam serve` on 8765. Wait until
the status line at the sidebar's foot shows everything indexed, then try:

1. **Sidebar**: Today, Inbox (with its count), the trays, the open collections (**2026
   House sale**), Browse, Ask and Activity. Switch the system to dark mode: the app follows.
2. **Inbox**: select `scan_water_bill.pdf`, press **Space** for Quick Look (`←`/`→`
   step through the inbox, Space closes). Press **⤢** in the preview to open the viewer
   window, then select another document in the inbox: the window follows (pin it to keep
   it). ⌘-click a second document for the batch form. File a scan (`⌘Enter`), then undo it
   from the toast.
3. **Today**: **Found in the inbox** lists the bills; **Put in To pay** creates the item
   (the file stays in the inbox) with **Open** and **Take back** in the toast.
4. **Drop on a tray**: drag `scan_water_bill.pdf` from the Inbox list onto **To pay** in
   the sidebar. Open the item: the bill view shows the payee row, IBAN, reference (12344),
   amount (47,90 €) and due date (5.11.2026) with Copy buttons, and the barcode built from
   those fields. Change the amount: the barcode changes, and a warning offers **Use the
   printed barcode's values** (the barcode on the scan still says 47,90). Point a banking
   app's barcode scanner at the screen, or copy the 54 digits.
5. **Collection groups**: open **2026 House sale**. **Needs attention** shows the member
   still in the inbox. Fold `Paperwork`, rename `Photos` from its **⋯** menu, drag
   `beach.jpg` into `Paperwork › Bank`; in Finder, `##. Ongoing/2026 House sale/` follows
   (each group a subfolder).
6. **Browse → search**: type `tiliote`. The Northbank statement appears with the word
   highlighted. Clear the box to get the folder listing back.
7. **Browse → folders**: open `10. Financial` → `Banks` (click, or `j`/`k` + `Enter`;
   `⌫` goes up, ⌘[ / ⌘] go back and forward, the breadcrumb goes anywhere). Click the PDF
   to preview it.
8. **Browse → move**: turn on **two panes**, open `40. Family` on the left and `30. Home`
   on the right, and drag `beach.jpg` across. The sheet lists the exact move; **Move**,
   then **Undo** from the toast. Or select a file and press **⌘⇧M** (Move to…). On the
   command line: `uv run dam --data-dir /tmp/dam-demo/data move "40. Family/beach.jpg"
   --folder "30. Home" --dry-run`.
9. **Mark for deletion**: select the PDF, press **Mark for deletion** in the toolbar. The
   dialog lists the new folders and `10. Financial/Banks/… → ##. To Delete/10. Financial/Banks/…`.
   **Apply**; the file is now under `/tmp/dam-demo/archive/##. To Delete/10. Financial/Banks/`.
   Try it on `##. Important/passport.pdf` too: the dry run is refused (protected), and
   there is no Apply.
10. **Activity**: a timeline under **Today** / **Yesterday** / date headers; each batch
    says what it did and has its own **Undo**, which shows "These files will be moved
    back:"; confirm, and the file is back (folders created under `##. To Delete` stay;
    nothing is ever deleted). The undo batch itself has no Undo, and the automatic
    `##. Ongoing` syncs (origin `workflow`) say to undo the collection change instead.
11. **File a bill into a tray**: in the Inbox open `scan_bill.pdf`. Under "Then put it in"
    choose **To pay**: the due date (15.10.2026), amount (84,20), IBAN and reference show
    as "found in scan". Add a note, press **File it**, confirm.
12. **Trays**: open **To pay** in the sidebar (`j`/`k`, `Enter` opens an item, `d` marks
    it done, Space is Quick Look). Press **Mark paid**; the Done filter lists the paid bill;
    open it and **Reopen** it. Edit the due date, tick a checklist entry and see the
    history.
13. **Collections**: in Browse select a file and choose **Add to collection…**, typing a
    new name, or drag it onto a collection in the sidebar (no confirm: only app-owned
    links in `##. Ongoing` change, and the result is shown). Try **Rename**, **Close**
    and **Reopen**: each shows a preview first. **Export** as zip and as PDF; the browser
    downloads the file.
13b. **Parent collections**: on **2026 House sale** choose **New collection inside…**
    (say `Sauna`) and add a file to it from Browse: in Finder the child is a folder (or a
    single link) inside `##. Ongoing/2026 House sale/`. Drag `Sauna` in the sidebar onto
    the **Collections** caption (top level) and back onto its parent, or use **Move
    to…**; the toast shows what `##. Ongoing` did. **Close collection…** on the parent is
    disabled while `Sauna` is open inside it.
13c. **Browse by collection**: in Browse press the **Collection** menu and pick
    **2026 House sale**: only the folders on the way to its members remain, and the button
    shows its name. Switch to **Files** for a flat, sortable list of every file below
    the folder; both are in the URL, per pane.
14. **Convert ##. Ongoing**: Today shows a notice that `##. Ongoing` holds unmanaged
    entries; follow **Convert**. Pick an entry (e.g. the link `2026 Sauna conversion`,
    or the folder `Legal`, for which you choose a destination folder; every entry and
    the items of a folder have Quick Look, Open and Show in Finder, and the form marks
    what is required), read the preview, **Apply**; then undo that entry from the
    Activity page. **Skip** hides an entry only
    until you reload the page; skipped entries stay "not managed". Converting `Legal` also
    removes the emptied real folder (undo restores it). The collection's own
    `2026 House sale` folder is listed as managed.
15. **AI with the fake provider**: stop the server and start it again with
    `DAM_AI_FAKE=1` in front (`DAM_AI_FAKE=1 uv run dam --data-dir /tmp/dam-demo/data
    serve --port 8766`). Nothing is sent anywhere: the fake answers from the payload and
    logs each call as `fake` at no cost. Try **Ask AI** on an inbox document (the form
    fills, each changed field marked **AI**), **Summarize with AI** on a bill and in
    Browse (**Use this summary**, then again over your own text to see the replace
    confirm), **Summarize with AI** on **2026 House sale** (a line per group, Use or
    Discard), **Ask** with a question such as `lasku` (click a citation for Quick Look),
    and **Activity → AI** for the log and the **Use AI** switch (off hides the buttons).
16. Stop the server with Ctrl+C and remove `/tmp/dam-demo`.

For reminders use the CLI with the demo data dir only, never `--install`:
`uv run dam --data-dir /tmp/dam-demo/data remind --dry-run --now 2026-10-20T09:00`.
The demo settings have `reminders: {mac: false}`, so `dam serve` sends no macOS
notifications for it.

## Production constraints

`index.html` is served with `default-src 'self'; script-src 'self'; style-src 'self';
img-src 'self' data: blob:; …`, so: no inline `<script>` or `<style>`, no CDN fonts or
scripts, no `eval`. Vite's build already satisfies this; React `style={{}}` props are fine.
`/api/files/{id}/raw` is CSP-sandboxed: show it with `<img>` only, never in an iframe.
