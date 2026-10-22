## Summary

<!-- What changed, in a sentence or two. -->

## Why

<!-- The problem this solves. -->

## Safety checklist

- [ ] No user file is deleted; `backend/tests/test_no_delete.py` is untouched
- [ ] Only the operation layer writes to the archive
- [ ] New changes are previewed, journaled and undoable
- [ ] Tests use temporary fake archives only
- [ ] No personal data in code, tests, docs or screenshots

## Tests run

- [ ] `cd backend && uv run ruff check . && uv run pytest -q -W error`
- [ ] `cd frontend && npm test -- --run && npm run build`

## Screenshots (UI changes)

<!-- Before / after, from the demo archive. -->
