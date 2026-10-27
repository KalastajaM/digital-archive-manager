# CLAUDE.md

dam (Digital Archive Manager) is a local-first app for filing personal documents:
a Python backend (`backend/`, FastAPI, SQLite with Alembic migrations, run with uv)
and a React + TypeScript frontend (`frontend/`, Vite, Vitest).

The contributor rules apply to agents in full, above all the safety rules:

@CONTRIBUTING.md

## Notes for agents

- **Never touch a real archive or the default data directory**
  (`~/Library/Application Support/DigitalArchiveManager` on macOS). To run the app,
  use the demo archive from CONTRIBUTING with an explicit `--data-dir`.
- **Text IO is always UTF-8 explicitly.** `tests/test_encoding.py` fails on any
  text-mode `open()`, `fdopen()`, `read_text()`, `write_text()` or `text=True`
  subprocess call without an explicit `encoding` (use `"utf-8"`), because Windows
  defaults to cp1252.
- **Cross-platform:** backend CI runs on macOS, Windows and Ubuntu. Use `pathlib`, no
  shell-specific commands, and give macOS-only features (Apple Vision OCR, `textutil`)
  a plain fallback message elsewhere.
- **Migrations** live in `backend/migrations/versions/`, named `00NN_<topic>.py` with
  `revision = "00NN"`. Take the next free number and set `down_revision` to the
  current head.
- **Changelog:** every user-visible change gets an entry under `## [Unreleased]` in
  `CHANGELOG.md` (Keep a Changelog sections), in plain words from the user's view.
- **After API changes** run `npm run gen:api` in `frontend/` and commit the regenerated
  `src/api/schema.d.ts` and `src/api/schema-input.d.ts`.
- **Before calling work done** run the full check from CONTRIBUTING:
  `uv run ruff check . && uv run pytest -q -W error` in `backend/`, and
  `npm test -- --run && npm run build` in `frontend/`.
