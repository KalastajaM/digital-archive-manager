# Settings screen: what goes in it, and in what order

Status: draft plan, 2026-10-23. Not ready to build until the open decisions at the end
are settled.

## Why

Most of dam's configuration can only be changed in `config/settings.yaml` or with the
CLI. This plan decides what joins the Settings screen, so sections arrive in a sensible
order instead of one by one as they come up.

## Where it starts

The filing codes work (PR #23, merged 2026-10-23) added the Settings screen at
`/settings` with a sidebar row, built as one section per area: Filing codes and Print
stickers. The sections below slot into that screen.

## Two kinds of setting

- **This app, in this browser:** Appearance. The same for every archive.
- **This archive:** everything that lives in the archive's own `settings.yaml` (each
  archive in the switcher has its own data directory, so its own file). Filing codes are
  in this group.

The screen should show the two groups apart, so nobody expects a reminder hour set in one
archive to apply to another. Archive-level sections name the archive they belong to.
For now Appearance says in its hint that it applies to every archive; the group headings
come with the next archive-level section (Reminders or AI).

## Sections

In build order. Each one gets its own changelog entry and tests on fake archives only.

### 1. Appearance (Light, Dark, Auto)

Built. A segmented control, Light, Dark and Auto, at the top of Settings. Auto (the
default) follows the system, which is what dam did before.

- **Storage:** `localStorage` under the app-wide key `dam.appearance` (not
  `archiveKey(...)`, because it is not per archive). Auto is stored as no key; a missing
  or unknown value means Auto.
- **Theme:** `<html data-theme="light|dark">`. `theme.css` has the light tokens on
  `:root` and the dark ones on `:root[data-theme="dark"]`, with `color-scheme` to
  match, so native controls and scrollbars follow too. Always setting a concrete theme
  keeps one dark block instead of a copy for the media query and a copy for the choice.
- **No flash on load:** `public/appearance.js`, a plain script in `<head>`, sets
  `data-theme` and the `theme-color` tag before the first paint. It is a file, not
  inline, because the CSP allows only `script-src 'self'`. `src/appearance.ts` has the
  same rule (a test checks the key and colours match) and keeps the theme up to date:
  the system switching while on Auto, and a choice made in another tab.

Objection weighed: `localStorage` is per browser and per origin, so changing
`server_port` or opening dam in another browser starts on Auto again. An app-wide file
in the data directory would avoid that but needs a request before the first paint.
Losing the choice costs one click, so `localStorage` it is.

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
2. ~~Appearance storage~~ Settled: `localStorage` (see section 1).
3. **Reminders and OCR:** in this plan, or later? They are the most useful file-only
   settings, but neither is needed by filing codes.
