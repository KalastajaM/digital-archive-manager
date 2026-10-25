# Contributing

Thanks for helping. dam handles people's personal documents, so the rules below about
safety matter more than speed.

## Safety rules (not negotiable)

- **Never delete user files.** Marking for deletion moves a file to `##. To Delete`; the
  user empties it. The few allowed removals (app-made links and empty folders in
  `##. Ongoing` / `##. Important`, and, on Undo only, a link the app itself made
  anywhere in the archive) are listed in docs/reference.md "Safety model in detail".
- **Only the operation layer writes to the archive.** No other code moves, renames,
  creates or removes anything there.
- **Every change is previewed, journaled and undoable.** Add a dry run, a journal entry
  and an undo path for any new kind of change.
- **`backend/tests/test_no_delete.py` (the AST guard) must never be relaxed without
  discussion.** If you think it needs a new allowed call, open an issue first.
- **Tests use temporary fake archives and must never touch a real archive** or a real
  data directory. Never point a test, script or example at your own documents.
- Keep it local-first: no telemetry, no background network calls. AI calls happen only on
  a click, after a preview of what is sent.

## Dev setup

You need [uv](https://docs.astral.sh/uv/) (it installs Python 3.13+ itself) and Node as
in `frontend/.nvmrc`.

**macOS:** `brew install uv` and `brew install nvm` (or any Node manager), then
`nvm install` in `frontend/`. OCR uses Apple Vision; nothing to install.

**Linux:** `curl -LsSf https://astral.sh/uv/install.sh | sh`, install Node with nvm or
your package manager. Optional OCR: `sudo apt install tesseract-ocr tesseract-ocr-fin`
(Fedora: `sudo dnf install tesseract tesseract-langpack-fin`).

**Windows:** `winget install --id=astral-sh.uv -e` and `winget install OpenJS.NodeJS`
(or nvm-windows). Optional OCR: `winget install --id UB-Mannheim.TesseractOCR`, tick
Finnish, and put the install folder on `PATH`.

```sh
cd backend && uv sync              # add --extra msg for .msg support (GPL, see below)
cd frontend && npm ci && npm run build
```

Try the app on a throwaway demo archive (see README "First run"):

```sh
cd backend
uv run python -m dam.demo /tmp/dam-demo
uv run dam --data-dir /tmp/dam-demo/data serve --port 8766
```

For UI work run the backend with `DAM_DEV_ORIGIN=http://localhost:5173 uv run dam serve --no-open`
and `npm run dev` in `frontend/`.

## Tests and lint

CI runs these on macOS, Windows and Ubuntu (backend) and Ubuntu (frontend); run them
before opening a pull request.

```sh
cd backend && uv run ruff check . && uv run pytest -q -W error
cd frontend && npm test -- --run && npm run build
cd frontend && npm run gen:api     # after API changes, commit the regenerated schema
```

## Commits

Use conventional prefixes: `feat:`, `fix:`, `chore:`, `docs:` (also `test:`, `refactor:`).
Say **why** in the message, not only what.
Example: `fix: keep tags on undo so a refiled document does not lose them`.

## Pull request checklist

- [ ] Follows the safety rules above; `test_no_delete.py` untouched
- [ ] Tests added or updated, using fake archives only
- [ ] `ruff`, `pytest`, frontend tests and build pass locally
- [ ] README or docs updated if behaviour changed; `CHANGELOG.md` entry added
- [ ] Works (or degrades with a plain message) on macOS, Windows and Linux
- [ ] Screenshots for UI changes, with no personal documents in them

## Licensing and the `dam[msg]` extra

dam is MIT. The optional extra `dam[msg]` installs `extract-msg`, which is **GPL-3.0**.
The core does not include or require it; users who install the extra combine the two
on their own machine. Do not add GPL (or other copyleft) code or dependencies to the core.
See [docs/licensing.md](docs/licensing.md). By contributing you agree your work is
released under the MIT licence.

Please also read the [Code of Conduct](CODE_OF_CONDUCT.md). Report security problems
privately, see [SECURITY.md](SECURITY.md).
