# Security policy

## Supported versions

Only the latest release (and `main`) gets security fixes.

## Reporting a vulnerability

Please report privately. Do not open a public issue.

Use GitHub's **private vulnerability reporting**: on the repository go to
**Security -> Advisories -> Report a vulnerability**. Include what you found, how to
reproduce it (with a fake archive, never real documents) and the affected version and
platform. You will get a reply as soon as the maintainer can, normally within a week.

## Scope

dam is a local tool. In scope:

- The local server binds `127.0.0.1` only and checks `Host` and `Origin` (and
  `Sec-Fetch-Site`) to resist DNS rebinding and cross-site requests. Anything that lets
  another web page, or another machine, read or change an archive is in scope.
- Anything that lets dam delete, overwrite or move files outside its previewed,
  journaled operations, or write outside the archive root (path traversal, symlink escapes).
- The optional AI feature: it sends selected extracted text to the provider only when you
  click Send, after a preview of exactly what goes out; excluded folders are never sent.
  Any path where text leaves the machine without that click is in scope.
- Secrets: API keys and the reminder e-mail password live in the OS keychain, never in a
  file, the log or the API. Leaks of these are in scope.

Out of scope: attacks that need an attacker who already controls your user account or
can edit your files and settings, and vulnerabilities in third-party services.
