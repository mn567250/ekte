# Privacy and local data

> **🇬🇧 English** · [🇨🇳 中文](../i18n/zh-CN/guide/privacy.md) · [🇫🇷 Français](../i18n/fr/guide/privacy.md) · [🇪🇸 Español](../i18n/es/guide/privacy.md) · [🇵🇹 Português](../i18n/pt/guide/privacy.md) · [🇮🇹 Italiano](../i18n/it/guide/privacy.md) · [🇩🇪 Deutsch](../i18n/de/guide/privacy.md) · [🇳🇴 Norsk](../i18n/nb/guide/privacy.md)

- **Local only.** `ekte serve` listens on loopback only (`127.0.0.1`, `::1`,
  `localhost`), answers only to those host names and refuses cross-site
  requests; it has no login because nothing outside your machine can reach it.
  ekte contacts only the endpoints you configure (target, baseline, judge,
  webhooks); it downloads nothing at runtime, not even tokenizer files.
- **Keys.** Reports and history keep only a fingerprint of an API key. The
  monitors' keys are not stored by default (they stay in the server's memory).
  If you opt in to storing them, they are encrypted in `watches.db` and the
  master key that decrypts them is never written to the data directory (you
  keep it, see [Monitoring](monitoring.md)). Either way a copy of the directory
  reveals no API key. The directory is owner-only all the same.
- **Data directory.** `~/.ekte` (or `EKTE_DATA_DIR`), created `0700` with `0600`
  files: `history.db` (audit history), `watches.db` (monitors; their keys only
  if you chose to store them, encrypted) and `kb.db` (your knowledge-base entries). Delete the directory to
  remove everything. `ekte data-dir` prints where it is; `--data-dir PATH`
  picks another one for a single run, e.g. `ekte serve --data-dir .` keeps the
  databases in the current folder. They are plain SQLite files, so you can open
  them (read-only is safest while ekte runs) for your own analysis:
  `history_metrics` holds one row of measured values per run and
  `history_requests` every request record (stored there once, not inside each
  saved report). Don't
  commit `watches.db` if that folder is a repository.

## Responsible use

ekte is a black-box auditing aid. It **cannot prove**:

- that a provider stores or trains on your prompts,
- that it always routes to one exact model (relays can route probabilistically),
- billing fraud beyond what independent token estimation can suggest.

Use reports for your own due diligence. **Do not publicly accuse a vendor** based
on a single run without reviewing sample size, cost settings and local law. Run
`ekte compare` against a trusted baseline before drawing strong conclusions.
