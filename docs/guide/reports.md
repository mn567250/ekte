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

## Evidence files

With `--evidence PATH` (`check`, `compare`, `image`, `audio`), and by default
for every run saved to history, ekte also writes every raw HTTP request and
response of the run to one file: JSON Lines in one zstd stream,
`<run_id>.jsonl.zst` (a directory given as `PATH` gets that name). The first
line describes the run; every further line is one request with its response,
including when each chunk of the response arrived. A line's `seq` is the
request's `seq` in the report's `performance.requests`, so every request the
report lists can be looked up. The report's `evidence` names the file with its
SHA-256 and its number of exchanges.

```bash
ekte check --base-url https://relay.example.com/v1 --model gpt-4o --evidence reports/
zstd -dc reports/<run_id>.jsonl.zst | jq -c 'select(.seq == 12)'
```

Keys and sensitive headers are removed before anything is written (see
[Privacy](privacy.md)). Each line matches `ekte/schemas/evidence.schema.json`
([Schemas](../reference/schemas.md)). In the web UI, **Show evidence** under a
finding of a saved run lists the requests of the check behind it and opens
each raw request and response.
