# Reports

> **🇬🇧 English** · [🇨🇳 中文](../i18n/zh-CN/guide/reports.md) · [🇫🇷 Français](../i18n/fr/guide/reports.md) · [🇪🇸 Español](../i18n/es/guide/reports.md) · [🇵🇹 Português](../i18n/pt/guide/reports.md) · [🇮🇹 Italiano](../i18n/it/guide/reports.md) · [🇩🇪 Deutsch](../i18n/de/guide/reports.md) · [🇳🇴 Norsk](../i18n/nb/guide/reports.md)

`ekte check` and `ekte compare` print a verdict and write the report to `reports/`
(`--out-dir`) as JSON, Markdown, HTML and PDF (`--format all`, the default);
`--format json|md|html|pdf` writes one format. `--json` and `--compact` print to
stdout instead.

```text
╭─ ✗ HIGH RISK — Strong evidence the relay does not deliver the claimed model… ─╮
│ Target : my-relay · model gpt-4o · provider openai                            │
│ Mode   : check · suite deep                                                   │
│ Score  : 53.5/100 (rating F) · confidence medium                             │
│                                                                               │
│ Overall health score 53.5/100. Findings: 3 high. …                            │
╰───────────────────────────────────────────────────────────────────────────────╯
  • Self-identifies as a rival brand (anthropic) under the claimed model id gpt-4o
  • Real context window ~8000 << declared 128000 (silent truncation suspected)
  • Reported prompt tokens far exceed independent estimate
```

A report contains the verdict (risk, confidence, score, rating), the key
findings with recommendations, the per-dimension scores and **Dimension
details**, every detector's findings with evidence, the performance section, the
knowledge-base profile used and the probe languages. Relay-controlled text is
redacted and escaped before it is written.
