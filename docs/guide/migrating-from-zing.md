# Coming from zing

> **🇬🇧 English** · [🇨🇳 中文](../i18n/zh-CN/guide/migrating-from-zing.md) · [🇫🇷 Français](../i18n/fr/guide/migrating-from-zing.md) · [🇪🇸 Español](../i18n/es/guide/migrating-from-zing.md) · [🇵🇹 Português](../i18n/pt/guide/migrating-from-zing.md) · [🇮🇹 Italiano](../i18n/it/guide/migrating-from-zing.md) · [🇩🇪 Deutsch](../i18n/de/guide/migrating-from-zing.md) · [🇳🇴 Norsk](../i18n/nb/guide/migrating-from-zing.md)

ekte continues [zing](https://github.com/cenbonew/zing) (its last release was
0.11.0) under a new name. What changes for an existing install:

- **Package and command.** `pip install ekte` (was `zing-audit`), the command
  `ekte` (was `zing`), the Python package `ekte`. Extras keep their names, e.g.
  `pip install 'ekte[web]'`. The two packages don't share a command or a module,
  so `zing-audit` can stay installed next to ekte.
- **Environment variables.** `EKTE_*` replaces `ZING_*` (`EKTE_DATA_DIR`,
  `EKTE_SECRET_KEY`, `EKTE_HOST`, …). An old `ZING_*` variable still works while
  its `EKTE_*` name is unset; ekte names it once on stderr.
- **Data directory.** On its first run ekte copies `~/.zing` to `~/.ekte`
  (history, monitors, knowledge base) if `~/.ekte` does not exist yet, and from
  then on works from `~/.ekte` only. `~/.zing` is left as it is, for zing if it
  still runs; delete it yourself once you no longer need it. A directory set
  with `EKTE_DATA_DIR`, `ZING_DATA_DIR` or `--data-dir` is used as it is.
- **Web UI.** Language, theme and filter settings and a master key saved in the
  browser's password manager carry over. zing's classic UI is gone: its
  addresses (`/tools`, `/console`) open the audit page (`/`).
- **Reports and probes.** Reports, webhooks and file names say `ekte` (e.g.
  `"tool": "ekte"`, `ekte-report.json`), and so do the probes sent to relays.
  Scripts that look for `zing` in them need updating.
- **Timeline.** The whole compatibility layer (the `ZING_*` fallback, the `~/.zing` copy, the carry-over of browser settings, cookies and the saved master key, and the classic UI addresses) is deprecated and removed in ekte **1.0.0** (1.0.0rc1 is the first release without it). Until then every part keeps working and its notice names this version; the old `/v2/…` page addresses redirect until 1.0.0 as well. ekte never deletes an old `~/.zing`, even after the copy is removed.
