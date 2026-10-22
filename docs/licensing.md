# Licensing

dam is released under the [MIT licence](../LICENSE).

## The optional `dam[msg]` extra

Reading Outlook `.msg` e-mails needs the optional extra `dam[msg]`
(`uv sync --extra msg` or `pip install "dam[msg]"`). It installs
[`extract-msg`](https://github.com/TeamMsgExtractor/msg-extractor), which is licensed
under **GPL-3.0**.

- The dam core is MIT and does **not** include or depend on `extract-msg`. Without the
  extra, `.msg` files are indexed as unsupported with a plain reason.
- dam does not ship or redistribute `extract-msg`. If you install the extra, you
  combine the two on your own computer. Distributing that combination to others is
  your responsibility and must follow the GPL-3.0 terms.
- `extract-msg` is also in the backend `dev` dependency group so the tests can cover
  `.msg` handling. Do not move it into the core dependencies.

Other dependencies keep their own licences; check them with your usual tooling before
redistributing a bundle.
