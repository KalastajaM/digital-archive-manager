# Settings screen: what goes in it, and in what order

Status: draft plan, 2026-10-23. Not ready to build until the open decisions at the end
are settled.

## Why

Most of dam's configuration can only be changed in `config/settings.yaml` or with the
CLI. The filing codes work (branch `claude/auto-archive-file-feature-12bb03`, commit
`af34883`) adds a Settings screen at `/settings` with a sidebar row, built as one section
per area ("Filing codes is the first; later areas slot in below it"). This plan decides
what the other sections are, so they arrive in a sensible order instead of one by one as
they come up.

## Coordination with the filing codes branch

The filing codes branch owns the Settings screen until it is merged: `screens/Settings.tsx`,
its test, the `/settings` route in `App.tsx`, the Settings row in `Sidebar.tsx` and the
`.settings` styles in `styles.css`. Nothing in this plan edits those files before that
merge.

One piece can be done earlier without touching them: the theme groundwork in
`theme.css`, `index.html` and `main.tsx` (see Appearance). The filing codes branch does
not change those three files (checked against `main...claude/auto-archive-file-feature-12bb03`
on 2026-10-23).

## Two kinds of setting

- **This app, in this browser:** Appearance. The same for every archive.
- **This archive:** everything that lives in the archive's own `settings.yaml` (each
  archive in the switcher has its own data directory, so its own file). Filing codes are
  in this group.

The screen should show the two groups apart, so nobody expects a reminder hour set in one
archive to apply to another. Archive-level sections name the archive they belong to.

## Sections

In build order. Each one gets its own changelog entry and tests on fake archives only.

### 1. Appearance (Light, Dark, Auto)

A three-way segmented control: Light, Dark, Auto. Auto (the default) follows the system,
which is what dam does today.

- **Storage:** `localStorage` under one app-wide key (for example `dam.appearance`), not
  `archiveKey(...)`, because it is not per archive. Missing or unreadable means Auto.
- **No flash on load:** a small inline script in `index.html` sets `data-theme` on
  `<html>` before the stylesheet paints. React then only updates it on change.
- **Tokens:** in `theme.css` the dark values now sit only under
  `@media (prefers-color-scheme: dark)`. They need to apply under
  `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) }` and under
  `:root[data-theme="dark"]`, with `color-scheme` set to match, so native controls and
  scrollbars follow too. The light values stay the base.
- **Window colour:** the two `theme-color` meta tags in `index.html` follow the system
  only; with a forced theme, one tag's `content` has to be set from the chosen theme.
- **Groundwork first:** the tokens, the early script and a small `useAppearance` hook
  can land before the Settings screen exists, because they touch no file the filing codes
  branch changes. The control itself goes into Settings after the merge.

Strongest objection to `localStorage`: it is per browser and per origin, so changing
`server_port` or opening dam in another browser resets the choice to Auto. The
alternative is an app-wide file in the data directory, like `ai-state.json`, served by
a small endpoint. That costs a backend round trip before first paint (so a flash, or a
cached copy anyway). Recommendation: `localStorage`, since the cost of losing it is one
click.

### 2. Filing codes

Comes from the filing codes branch as it is. Listed here only for its place in the order.

### 3. Reminders

Today the hour, the macOS notification switch and the e-mail settings (`reminders:` in
`settings.yaml`) are file only, and the e-mail password is set with
`dam remind --set-email-password`. A section with: hour, Mac notification on or off,
e-mail on or off with to, SMTP host, port, user and STARTTLS, and possibly a Send test button (new; nothing like it exists yet).
The password stays in the Keychain; the section shows whether one is set and tells the
user the CLI command to set it, so no password field is added to the web UI. On Windows
and Linux the Mac notification row shows a plain "macOS only" note.

### 4. Reading text (OCR)

`ocr_languages` as an ordered list (most likely first), with the engine in use shown
(Apple Vision on macOS, Tesseract elsewhere, or none) and a note for languages one
engine reads and the other does not (Finnish: Tesseract yes, Apple Vision no).

### 5. AI

Today Activity → AI holds the switch, this month's spend, the call log and the excluded
folders. Budget, effort and models are file only.

Decided (2026-10-23): the AI configuration moves into Settings; spend and the log
stay in Activity, with links both ways.

- **Settings → AI** gets the on/off switch (still `ai-state.json`), whether an API key is
  set (the key stays in the Keychain and is set with `dam ai --set-key`; no key field in
  the web UI), the excluded folders (the existing `components/ai/ExcludedFolders.tsx`
  moves here as it is), the monthly budget and the effort. It shows one line with this
  month's spend against the budget and a link to Activity → AI.
- **Activity → AI** keeps this month's spend, the budget as read-only text and the call
  log, and gets a link to Settings → AI where the switch and excluded folders were.
- Models, prices, `usd_to_eur` and `max_tokens` stay file only (designer's call: they
  are tuning values, and a wrong price silently breaks the budget check).
- The README row "AI settings: spend, the switch and the folders never sent" and its
  screenshots (`docs/images/ai-settings-light.png`, `-dark.png`) need redoing for the new
  split.

### 6. Settings file

A last row with the path of this archive's `settings.yaml` and a Reveal button, for the
settings that stay file only.

## Deliberately left out

- **Special folder names and protected paths.** Changing them changes how the archive is
  read; that stays in Set up folders and the file.
- **`indexer_reads_per_minute`, `ops_throttle_ms`, `server_port`.** Tuning values; file
  only, reachable through the Settings file row.
- **Archives (add, rename, colour, forget).** Stays in the archive switcher.
- **Tray defaults, Today's card layout, split widths.** Already edited where they are
  used.

## Backend work the sections share

`settings.yaml` is edited as text so the user's comments survive (see
`with_ai_exclude_folders` in `backend/src/dam/setup.py`). Reminders, OCR and AI need the
same for other keys, so before section 3 that function should be generalised into a
writer for one top-level key or one key in a section, with the same rules: comments
kept, an inline section refused with a plain message, the result read back before it is
saved. Settings are configuration, not archive content, so the operation layer and the
journal do not apply; a backup of the previous file before each save is still worth
having, as tray defaults do.

## Open decisions

1. ~~AI settings: move to Settings, or stay in Activity → AI?~~ Settled: move the
   configuration, links both ways (see section 5).
2. **Appearance storage:** `localStorage` (recommended above) or an app-wide file.
3. **Reminders and OCR:** in this plan, or later? They are the most useful file-only
   settings, but neither is needed by filing codes.
