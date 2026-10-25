# GitHub settings checklist

Do these in the GitHub UI after the first push (repository owner).

- [ ] **Description** (Settings -> General, or the gear next to About):
  > Local-first manager for your document archive in Google Drive, OneDrive, Dropbox or any folder: OCR search, filing suggestions, bills with due dates, collections. Every change previewed and undoable; never deletes a file. macOS, Windows, Linux.
- [ ] **Topics** (same place):
  > document-management, personal-archive, paperwork, digital-archive, file-organizer, ocr, full-text-search, local-first, privacy, self-hosted, google-drive, onedrive, dropbox, bills, fastapi, react, sqlite, python, typescript, cross-platform

- [ ] **Social preview**: Settings -> General -> Social preview -> upload a 1280x640 PNG: `docs/images/social-preview-light.png` (or `-dark.png`)
- [ ] **Private vulnerability reporting**: Settings -> Code security -> enable
  (SECURITY.md and the Code of Conduct point to it)
- [ ] **Dependabot alerts** and **Dependabot security updates**: Settings -> Code
  security -> enable (version updates come from `.github/dependabot.yml`)
- [ ] **Branch protection for `main`**: Settings -> Branches -> require a pull request
  and the CI check `CI ok` to pass; block force pushes. `CI ok` passes when every CI
  job that ran passed. A PR that only touches the frontend skips the backend jobs (and
  the other way round), so require `CI ok` rather than the individual jobs, which may
  be skipped
- [ ] **Discussions**: decide on or off (Settings -> General -> Features). If on, add a
  link to `.github/ISSUE_TEMPLATE/config.yml` for questions
- [ ] Check that the Security policy, issue forms and PR template show up
